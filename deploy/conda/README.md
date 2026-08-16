# SoyMutDB Conda 部署指南（备选路径）

> **主路径是 docker compose**（`docker-compose.yml` + `deploy/linux/install.sh` + `deploy/scripts/upgrade.sh`）。
> 本文档描述 **conda 裸进程部署**（备选路径，D6 重新启用）：无 docker / 离线 / 本地开发服务器使用。
> 环境定义：`deploy/conda/environment-api.yml`、`deploy/conda/environment-worker.yml`；
> 一键脚本：`deploy/scripts/conda-deploy.sh`；
> 完全无 Docker 的数据层探索见 [no-docker-data-layer.md](no-docker-data-layer.md)。

---

## 1. 适用场景与定位

| 场景 | 推荐路径 |
| --- | --- |
| 生产服务器（有 docker） | **docker compose 主路径**（install.sh + upgrade.sh） |
| 无 docker 的服务器 / 内网离线机 / 本地开发 | **conda 备选路径**（本文档） |
| 只有 docker 但想省资源 | docker compose 主路径（保持现状） |

conda 路径与 docker 路径**共享同一套应用**（`apps/api`、`apps/worker`）与**同一套环境变量契约**（`SOYMUTDB_` 前缀，字段对齐 `apps/api/app/core/config.py`）。两者不是二选一互斥：同一台机器可以 docker 起数据层 + conda 跑应用层。

## 2. 推荐组合：docker 起数据层，conda 跑应用层

**最实用的 conda 模式**：数据层（PostgreSQL / ClickHouse / Redis×2 / MinIO）继续用 docker compose 管理（数据持久化、健康检查、重启策略都现成），应用层（api / worker×3 / beat）用 conda 裸进程跑。

```bash
# 只起数据服务（不启动 api/worker 等应用容器）
cd <repo-root>
docker compose up -d postgres clickhouse redis redis-celery minio

# 确认数据层健康
docker compose ps
```

数据层对 conda 应用层的可见性：

| 数据服务 | compose 服务名 | conda 应用层连接（.env 示例） |
| --- | --- | --- |
| PostgreSQL | `postgres` | `SOYMUTDB_DATABASE_URL=postgresql+asyncpg://soymutdb:<PASS>@localhost:5432/soymutdb` |
| ClickHouse | `clickhouse` | `SOYMUTDB_CLICKHOUSE_HOST=localhost` `SOYMUTDB_CLICKHOUSE_PORT=8123` |
| 缓存 Redis | `redis` | `SOYMUTDB_REDIS_URL=redis://:<PASS>@localhost:6379/0` |
| Celery broker/result | `redis-celery` | `SOYMUTDB_CELERY_BROKER_URL=redis://:<PASS>@localhost:6379/0`、`SOYMUTDB_CELERY_RESULT_BACKEND=redis://:<PASS>@localhost:6379/1` |
| MinIO | `minio` | `SOYMUTDB_S3_ENDPOINT=http://localhost:9000` + access/secret key |

> 注意：数据服务端口（5432/8123/6379/9000）在 compose 里只对宿主发布（`ports`），
> conda 进程连 `localhost` 即可。两个 Redis 实例都要起：`redis`（缓存，可驱逐）与
> `redis-celery`（broker，noeviction + AOF）职责隔离，不能混用。

完全无 docker 时，数据层需另备（本机安装 PG/CH/Redis/MinIO，或连远程实例），连接地址相应修改 `.env` 即可——应用层部署流程不变。

## 3. 前置条件

- **Miniforge**（conda）：<https://github.com/conda-forge/miniforge>（`bash Miniforge3-Linux-x86_64.sh` 后 `conda init`，重开 shell）
- 仓库代码：`git clone ... && cd <repo>`（或同步发布目录）
- 外部 CLI 二进制（worker 任务依赖，与 pyproject 注释一致，需按任务启用情况安装）：
  - BLAST：`conda install -n soymutdb-worker -c bioconda blast`（另有 `samtools bcftools tabix bedtools`）
  - fastp（analyses 队列）：bioconda 或宿主机二进制
  - EMMAX / GEMMA（GWAS 队列）：引擎二进制由运维安装到 worker 宿主

## 4. 部署步骤

```bash
# 1) 一键准备（检查 conda → 创建/更新两个环境 → 装应用代码 → 目录 → .env → 校验）
bash deploy/scripts/conda-deploy.sh
#    非 root 时指定可写安装目录：
#    SOYMUTDB_INSTALL_DIR=/home/soymutdb bash deploy/scripts/conda-deploy.sh

# 2) 编辑环境变量（模板已生成：deploy/conda/env.example；必填项见 §5）
vim /opt/soymutdb/.env        # 或 $SOYMUTDB_INSTALL_DIR/.env

# 2.1) （可选）数据层为本机服务时，幂等初始化 PG/CH/MinIO 桶：
#      bash deploy/scripts/conda-data-init.sh --check
#      bash deploy/scripts/conda-data-init.sh

# 3) 一次性迁移（首次 / 每次升级后）
cd apps/api && conda run -n soymutdb-api alembic upgrade head

# 4) 启动 API（FastAPI，4 workers；--proxy-headers 供 nginx 反代取真实 IP）
cd apps/api && conda run -n soymutdb-api uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips=*

# 5) 启动 Celery worker + beat（见 §6 多队列命令）
#    也可用 systemd 生成器一键生成/安装单元：
#    bash deploy/scripts/conda-services.sh --print
#    sudo bash deploy/scripts/conda-services.sh --install
```

推荐用 **systemd 或 supervisor** 托管裸进程（开机自启、崩溃拉起、日志轮转），示例（systemd unit 最小模板）：

```ini
# /etc/systemd/system/soymutdb-api.service
[Unit]
Description=SoyMutDB API (conda)
After=network.target

[Service]
User=soymutdb
WorkingDirectory=/opt/soymutdb/apps/api
EnvironmentFile=/opt/soymutdb/.env
ExecStart=/home/soymutdb/.miniforge3/envs/soymutdb-api/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips=*
Restart=always

[Install]
WantedBy=multi-user.target
```

> `EnvironmentFile` 直接喂 `SOYMUTDB_*` 变量（pydantic-settings 读取），无需 `conda run`；
> ExecStart 用 env 内绝对路径解释器，避开 conda activate 的 shell 依赖。

## 5. 环境变量（`SOYMUTDB_` 前缀，对齐 config.py）

模板：`deploy/conda/env.example` → 复制为 `$INSTALL_DIR/.env`（conda-deploy.sh 自动完成；compose 专用 `API_IMAGE_TAG` / `WORKER_IMAGE_TAG` 不在 conda 模板中）。

**必填（API prod 模式 fail-fast，缺失拒绝启动）：**

| 变量 | 说明 | 示例 |
| --- | --- | --- |
| `SOYMUTDB_APP_ENV` | 环境标识，`dev|staging|prod` | `prod` |
| `SOYMUTDB_DATABASE_URL` | PG 连接（asyncpg） | `postgresql+asyncpg://soymutdb:<PASS>@localhost:5432/soymutdb` |
| `SOYMUTDB_JWT_SECRET` | ≥32 字符随机串 | `openssl rand -hex 32` 输出 |
| `SOYMUTDB_CORS_ORIGINS` | 逗号分隔，禁止 `*` | `https://soymutdb.org,http://localhost:5173` |
| `SOYMUTDB_REDIS_URL` | 缓存 Redis | `redis://:<PASS>@localhost:6379/0` |
| `SOYMUTDB_CELERY_BROKER_URL` / `SOYMUTDB_CELERY_RESULT_BACKEND` | broker/result 独立实例 | `redis://:<PASS>@localhost:6379/0` / `.../1` |
| `SOYMUTDB_S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` | MinIO | `http://localhost:9000` + compose 里设置的凭据 |

**常用可选：** `SOYMUTDB_CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE`、`SOYMUTDB_DB_POOL_SIZE`（默认 5，调大需同步 PG `max_connections`）、`SOYMUTDB_WORKER_DB_POOL_SIZE`（worker 同步 engine）、`SOYMUTDB_CELERY_RESULT_EXPIRES`（默认 604800）。

**不可变静态发布目标（Phase 3，可选）：** 见本目录 `env.example` 注释段。`local` 用
`SOYMUTDB_PUBLICATION_LOCAL_ROOT`；`github_pages` 用 `SOYMUTDB_GITHUB_PAGES_TOKEN/REPO`；
`cloudflare_pages` 用 `SOYMUTDB_CLOUDFLARE_PAGES_API_TOKEN/ACCOUNT_ID/PROJECT`。未配置的
目标 `is_configured=false`，不得发起发布；凭据只存 env，绝不落库。

> worker 与 beat 只读 subset：`SOYMUTDB_DATABASE_URL`（worker 用 `psycopg` 驱动，URL scheme 由代码构造）、ClickHouse、S3、Celery 相关变量。全部字段见 `apps/api/app/core/config.py`。

## 6. 启动命令模板（uvicorn / celery multi）

**API：**

```bash
cd apps/api && conda run -n soymutdb-api uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 --workers 4 --proxy-headers --forwarded-allow-ips=*
```

**Celery workers（队列契约：`ingest / export / stats / cleanup / blast / analyses / default`；与 compose 分工一致）：**

```bash
# 前台（调试）：
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app worker \
    --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=4 \
    --max-tasks-per-child=100 --hostname=worker-default@%h
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app worker \
    --loglevel=info --queues=blast --concurrency=2 \
    --max-tasks-per-child=50 --hostname=worker-blast@%h
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app worker \
    --loglevel=info --queues=ingest,export,stats,cleanup,default --concurrency=2 \
    --max-tasks-per-child=20 --hostname=worker-ingest@%h
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app worker \
    --loglevel=info --queues=analyses --concurrency=2 \
    --max-tasks-per-child=20 --hostname=worker-analyses@%h

# 后台（celery multi，日志写 $INSTALL_DIR/logs/）：
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app multi start \
    worker-default worker-blast worker-ingest worker-analyses \
    -Q:worker-default ingest,export,stats,cleanup,default \
    -Q:worker-blast blast \
    -Q:worker-ingest ingest,export,stats,cleanup,default \
    -Q:worker-analyses analyses \
    --concurrency:worker-default=4 --concurrency:worker-blast=2 \
    --concurrency:worker-ingest=2 --concurrency:worker-analyses=2 \
    --logfile=/opt/soymutdb/logs/worker-%n.log --pidfile=/opt/soymutdb/logs/worker-%n.pid
```

> `analyses` 队列由 `worker-analyses` 独占，消费 fastp/scanpy/GWAS 分析任务；`stats` 队列含
> 静态发布任务（`static_publish`）与静态页构建（`static_pages`），由 worker-default/worker-ingest 消费。

**beat（定时任务）：**

```bash
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app beat \
    --loglevel=info --schedule=/opt/soymutdb/data/celerybeat-schedule
```

**健康检查：**

```bash
curl http://localhost:8000/api/v1/health/live     # 存活
curl http://localhost:8000/api/v1/health/ready    # 就绪（含依赖探活）
conda run -n soymutdb-worker celery -A soymutdb_worker.main:celery_app inspect ping -d worker-default@<hostname>
```

## 7. 对外暴露（nginx 反代或直连）

- **直连**：API 端口 `8000` 直接对外（防火墙放行；`SOYMUTDB_CORS_ORIGINS` 配好前端域名）。
- **nginx 反代**（推荐，与 compose 内 nginx 语义一致）：`/api/v1/*` → `127.0.0.1:8000`、`/mcp/*`（SSE，`proxy_buffering off`）→ MCP server（conda 下需另跑 `mcp_server` 或仍用 compose 的 `mcp-server` 容器）、`/data/*` → MinIO `localhost:9000`。配置可参考 `infra/nginx/conf.d/default.conf` 改动量最小化。

## 8. 与 Docker 部署的差异

| 维度 | docker compose（主路径） | conda 裸进程（备选） |
| --- | --- | --- |
| 应用层运行方式 | 容器（镜像 tag 不可变） | 源码 + conda env（editable 安装） |
| 升级 | `upgrade.sh`：预检 → 拉镜像 → 备份 → 迁移 → 滚动重启 → 健康轮询 → 自动回滚 | 手动/脚本：`git pull` → `conda env update -f` → `alembic upgrade head` → 重启 systemd 服务；**无自动回滚**（可保留旧 release 目录切换） |
| 数据持久化 | compose volumes（`pgdata` 等，`docker compose down` 不删数据） | 数据层仍在 docker 时不变；纯裸机时由本机 PG/CH/Redis 管理 |
| 日志 | `docker compose logs -f <svc>` + systemd journal | 进程 stdout/journald 或 `celery multi` 日志文件（`$INSTALL_DIR/logs/`） |
| 健康检查/自愈 | compose healthcheck + `restart: unless-stopped` | systemd `Restart=always`（自行编写 unit） |
| 监控 | prometheus/grafana/exporters 一套 | 无内置；API/worker 的 `/metrics` 可手动接入外部 Prometheus |
| 依赖隔离 | 镜像内固定 | conda env 固定（`conda env export > environment.lock.yml` 可冻结） |
| 网络 | compose 内网（服务名互访） | 走宿主 localhost/端口；无容器网络隔离 |
| 回滚 | 自动回滚旧镜像 | 手动切回旧代码目录/旧 env 快照 |

## 9. 更新依赖与升级

```bash
# 依赖更新（YAML 变更后）
conda env update -f deploy/conda/environment-api.yml --prune
conda env update -f deploy/conda/environment-worker.yml --prune

# 应用代码更新
git pull
conda run -n soymutdb-api python -m pip install --no-deps -e apps/api
conda run -n soymutdb-worker python -m pip install --no-deps -e apps/worker

# 数据库迁移
cd apps/api && conda run -n soymutdb-api alembic upgrade head

# 重启服务（systemd 示例）
sudo systemctl restart soymutdb-api soymutdb-worker-default soymutdb-worker-blast \
    soymutdb-worker-ingest soymutdb-beat
```

## 10. 常见问题

- **API 拒绝启动（prod fail-fast）**：`SOYMUTDB_JWT_SECRET` <32 字符 / CORS 缺失或含 `*` / 凭据仍是 dev 默认值 → 按 §5 修正 `.env`；`conda-deploy.sh` 第 6 步会先拦截同类问题。
- **任务不进队列**：确认 `SOYMUTDB_CELERY_BROKER_URL` 指向 `redis-celery`（localhost:6379/0）而不是缓存 `redis`（allkeys-lru 会丢消息）。
- **worker 缺 BLAST 等二进制**：`conda install -n soymutdb-worker -c bioconda blast samtools bcftools tabix bedtools`。
- **conda env 路径**：`conda env list`；解释器绝对路径 `$(conda info --base)/envs/<name>/bin/python`（systemd 直接用）。
- **离线安装**：在有网机器 `conda env export > environment.lock.yml` + `conda pack`，拷到离线机解包后改 prefix（`conda-unpack`）。
