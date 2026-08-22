# SoyMutDB 完全无 Docker 部署探索（数据层裸进程）

> 状态：探索文档 / 备选路径
> 适用：服务器没有 Docker、不允许容器、离线内网、本地开发想全部用系统/conda 服务。
> 应用层仍使用 `deploy/scripts/conda-deploy.sh` + conda 环境；本文只补“数据层完全不用 Docker”的部分。

---

## 1. 组合矩阵

| 数据层 | 应用层 | 说明 |
| --- | --- | --- |
| Docker Compose 数据服务 | conda 裸进程 | 最省事，见 `deploy/conda/README.md` §2 |
| 本机/远程 PG + CH + Redis×2 + MinIO | conda 裸进程 | 本文探索的“完全无 Docker” |
| 托管云服务（RDS/CH Cloud/Upstash/S3） | conda 裸进程 | 连接地址改为远程即可，应用层不变 |

完全无 Docker 时，`conda-deploy.sh` 仍然可用；数据层需自行安装、初始化并保持运行。
本文假设 Ubuntu/Debian 类系统，命令可类比 RHEL/Arch。

---

## 2. 总体架构

```text
[本机 systemd 服务]
  postgresql   :5432   PostgreSQL 16
  clickhouse   :8123   ClickHouse（HTTP 接口）
  redis-cache  :6379   Redis 缓存（allkeys-lru）
  redis-celery :6380   Redis broker/result（noeviction + AOF）
  minio        :9000   MinIO S3 API
  minio-console:9001
        │
        ▼
[conda 裸进程]
  soymutdb-api     :8000   uvicorn
  worker-default / worker-blast / worker-ingest / worker-analyses
  beat
```

应用层读取 `$INSTALL_DIR/.env`（模板 `deploy/conda/env.example`）。

---

## 3. 安装数据层（Ubuntu/Debian 示例）

### 3.1 PostgreSQL

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-client
sudo systemctl enable --now postgresql

# 创建业务用户和库（用 postgres 超级用户）
sudo -u postgres psql <<'SQL'
CREATE ROLE soymutdb LOGIN PASSWORD 'change-me-postgres';
CREATE DATABASE soymutdb OWNER soymutdb;
SQL
```

验证：

```bash
PGPASSWORD=change-me-postgres psql -h 127.0.0.1 -U soymutdb -d soymutdb -c 'select 1'
```

### 3.2 ClickHouse

官方仓库或 conda：

```bash
# 方式 A：官方 DEB 仓库（推荐）
curl https://clickhouse.com/ | sh   # 或按官方文档添加 apt 源
sudo clickhouse install
sudo systemctl enable --now clickhouse-server

# 方式 B：conda（适合不想碰系统服务）
# conda create -n soymutdb-ch -c conda-forge clickhouse-server clickhouse-client
```

初始化数据库和用户：

```bash
clickhouse-client --query "CREATE DATABASE IF NOT EXISTS soymutdb"
clickhouse-client --query "CREATE USER IF NOT EXISTS soymutdb IDENTIFIED WITH sha256_password BY 'change-me-clickhouse'"
clickhouse-client --query "GRANT ALL ON soymutdb.* TO soymutdb"
```

### 3.3 Redis（两个实例）

```bash
sudo apt-get install -y redis-server

# 缓存实例：默认 6379
sudo cp /etc/redis/redis.conf /etc/redis/redis-cache.conf
sudo sed -i 's/^port .*/port 6379/' /etc/redis/redis-cache.conf
sudo sed -i 's/^# requirepass .*/requirepass change-me-redis/' /etc/redis/redis-cache.conf
sudo sed -i 's/^# maxmemory-policy .*/maxmemory-policy allkeys-lru/' /etc/redis/redis-cache.conf
sudo systemctl enable --now redis-server

# Celery 实例：6380，noeviction + AOF
sudo cp /etc/redis/redis.conf /etc/redis/redis-celery.conf
sudo sed -i 's/^port .*/port 6380/' /etc/redis/redis-celery.conf
sudo sed -i 's/^# requirepass .*/requirepass change-me-redis/' /etc/redis/redis-celery.conf
sudo sed -i 's/^# maxmemory-policy .*/maxmemory-policy noeviction/' /etc/redis/redis-celery.conf
sudo sed -i 's/^appendonly no/appendonly yes/' /etc/redis/redis-celery.conf
sudo systemctl enable --now redis-server@redis-celery
```

如果使用 systemd template，需把 `/etc/redis/redis-celery.conf` 放到可被 `redis-server@` 读取的位置（常见为 `/etc/redis/redis-celery.conf` 并启用 `redis-server@redis-celery`）。

### 3.4 MinIO

```bash
# 下载单二进制（也可用 conda 包）
wget https://dl.min.io/server/minio/release/linux-amd64/minio -O /usr/local/bin/minio
chmod +x /usr/local/bin/minio
sudo useradd -r -s /usr/sbin/nologin minio-user || true
sudo mkdir -p /data/minio
sudo chown -R minio-user:minio-user /data/minio

cat >/etc/systemd/system/minio.service <<'UNIT'
[Unit]
Description=MinIO S3 Server
After=network.target

[Service]
User=minio-user
Group=minio-user
EnvironmentFile=/etc/default/minio
ExecStart=/usr/local/bin/minio server /data/minio --console-address ":9001"
Restart=always
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

cat >/etc/default/minio <<'ENV'
MINIO_ROOT_USER=change-me-minio-admin
MINIO_ROOT_PASSWORD=change-me-minio-password
ENV

sudo systemctl daemon-reload
sudo systemctl enable --now minio
```

---

## 4. 初始化 MinIO 桶

需要 `mc` 客户端：

```bash
wget https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc
chmod +x /usr/local/bin/mc
mc alias set local http://127.0.0.1:9000 change-me-minio-admin change-me-minio-password

for bucket in genomic-data user-tracks blast-dbs exports gwas analyses; do
  mc mb --ignore-existing "local/${bucket}"
done
mc policy set public local/genomic-data
mc version enable local/user-tracks
```

没有 `mc` 时，也可以用 Python/boto3 初始化（应用层 conda env 已带 boto3）。

---

## 5. 初始化 ClickHouse Schema

应用层迁移分两部分：

```bash
# 1) PostgreSQL 结构（Alembic）
cd apps/api && conda run -n soymutdb-api alembic upgrade head

# 2) ClickHouse 结构（幂等脚本，读取 .env 中的 SOYMUTDB_CLICKHOUSE_*）
#    设置好环境变量后执行：
SOYMUTDB_CLICKHOUSE_HOST=127.0.0.1 \
SOYMUTDB_CLICKHOUSE_PORT=8123 \
SOYMUTDB_CLICKHOUSE_USER=soymutdb \
SOYMUTDB_CLICKHOUSE_PASSWORD=change-me-clickhouse \
SOYMUTDB_CLICKHOUSE_DATABASE=soymutdb \
bash deploy/scripts/migrate-clickhouse.sh
```

> `migrate-clickhouse.sh` 会从仓库 `infra/clickhouse/upgrade_variant_facts_schema.sql` 读取 DDL；
> 若数据层是全新实例，建议先执行 `infra/clickhouse/init.sql` 或对应 fixture，再跑升级脚本。

---

## 6. 数据层 systemd 单元汇总

| 服务 | 单元名 | 端口 |
| --- | --- | --- |
| PostgreSQL | `postgresql` | 5432 |
| ClickHouse | `clickhouse-server` | 8123 |
| Redis 缓存 | `redis-server` | 6379 |
| Redis Celery | `redis-server@redis-celery` | 6380 |
| MinIO | `minio` | 9000/9001 |

应用层 systemd 示例见 `deploy/conda/README.md` §4（`soymutdb-api.service` 等）。
可将应用层与数据层一并纳入同一 `systemd` 启动顺序：

```ini
[Unit]
After=postgresql.service clickhouse-server.service redis-server.service redis-server@redis-celery.service minio.service
```

---

## 7. 一键脚本现状与建议

现有 `deploy/scripts/conda-deploy.sh` 负责**应用层**（conda env、目录、.env、预检、输出启动命令）。
本轮已补：

- 新增 `deploy/conda/env.example`，包含 conda 模式真正需要的 `SOYMUTDB_DATABASE_URL / CLICKHOUSE / REDIS / CELERY / S3` 变量
- `conda-deploy.sh` 优先复制该模板，并在预检中检查这些连接变量是否为空
- 新增 `deploy/scripts/conda-data-init.sh`：探测本机 PG/CH/MinIO/Redis，幂等创建 PG 用户/库、CH 库/用户、MinIO 桶；支持 `--check` 只检查
- 新增 `deploy/scripts/conda-services.sh`：生成/安装 api/worker-default/worker-blast/worker-ingest/worker-analyses/beat 的 systemd units（`--print` / `--install`）
- 新增 `deploy/conda/environment-data.yml`：纯 conda 数据层环境定义（postgresql / clickhouse-server / clickhouse-client / redis）

仍建议后续增加的脚本：

- `deploy/scripts/conda-services.sh` 的 `--uninstall` 模式（删除 units）
- 数据层 systemd units 生成（postgresql/clickhouse/redis/minio 已由系统包管理时不需要）

---

## 8. 风险与限制

- **无 Docker 不等于无运维**：PG/CH/Redis/MinIO 的备份、监控、升级都要自行负责。
- ClickHouse 的 `ReplacingMergeTree` 依赖稳定的 `release_id`；本机/远程实例同样需要迁移脚本保证 schema 一致。
- Redis 缓存实例绝不能当 Celery broker 用（`allkeys-lru` 会丢消息）；必须两个实例/不同 db 且 broker 开 `noeviction + AOF`。
- MinIO 桶的 `version enable` 只对 `user-tracks` 等需要版本化的桶开启；`genomic-data` 设为 public。
- 离线安装：conda env 可 `conda pack`；系统包需提前下载 deb/rpm，MinIO/ClickHouse 二进制可离线拷贝。

---

## 9. 结论

完全无 Docker 部署是可行的：**数据层用系统服务 + 应用层用 conda 裸进程**，两者通过 `$INSTALL_DIR/.env` 的 `SOYMUTDB_*` 连接变量衔接。当前仓库已有 conda 应用层脚本和文档，本次补上了缺失的连接变量模板；数据层初始化建议按本文第 3–6 节执行。
