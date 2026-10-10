# 本机运行速查 — T4 宿主机

> 本文件记录**本机如何把站点跑起来**。历史会话已经重复踩坑若干次
> （重复手搓静态服务器、重复发现构建失败、重复忘记 mamba 环境），
> 故单独成文。**先读本文件，再动手。**

## 1. 环境：必须用 mamba

```bash
export PATH="/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH"
```

- `node` v26.10.0、`python3` 3.14.8 都在这个 env 里
- **系统 python 不带依赖**；`/usr/local/bin/corepack` 属于另一套无关的
  Node 安装（0.34.5，四月装的），本机的 `node` 不带 corepack（Node 25+
  已从发行版移除）
- `pnpm dlx` 需要可写 cache：
  `export PNPM_HOME="$PWD/.ph" XDG_CACHE_HOME="$PWD/.cache"`

## 2. 构建：两个必需条件，缺一个就失败

```bash
cd apps/web
export PATH="/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH"
export GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2
export SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true   # 允许 http 源（非 localhost）
export VITE_DEPLOYMENT_MODE=demo
export VITE_SITE_VARIANT=external
export VITE_BASE_URL=/
export VITE_API_BASE_URL="http://100.77.182.76/api/v1"
export VITE_JBROWSE_BASE_URL="http://100.77.182.76/jbrowse/"
./node_modules/.bin/max build
```

失败模式与原因：

| 报错 | 原因 |
| --- | --- |
| `API origin is required for production deployment` | 缺 `VITE_API_BASE_URL` / `SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED` |
| `failed to create new OS thread (errno=11)` | 缺 `GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`（PLAN.md:40 记录过同类） |
| esbuild `EAGAIN` / `newosproc` | 线程/进程耗尽，同上 |

`max dev` 在本机会**卡死在 `Preparing...`**——构建变通管用，dev server 变通不管用。

**构建产物落在 `apps/web/dist/` 根目录**（单变体）。`apps/web/dist/external`、
`dist/internal` 是旧的 `build-sites.ts` 双变体产物，会被普通 `max build` 清掉。
伺服路径别指错。

## 3. 起服务：已有脚本，不要手搓

**`scripts/start-cloud-dev.sh`** 是 CNB 云开发的正规入口：

```bash
SOYMUTDB_DEV_MODE=preview SOYMUTDB_DEV_FRONTEND=preview \
SOYMUTDB_DEV_DATA_LAYER=off SOYMUTDB_DEV_INSTALL=0 \
bash scripts/start-cloud-dev.sh preview
```

**`scripts/dev/local-preview-server.mjs`** 是单应用伺服器，**会把 `/api/*` 代理到
API**，门户 8090 / 控制台 8091：

```bash
node scripts/dev/local-preview-server.mjs --app portal --port 8090
node scripts/dev/local-preview-server.mjs --app admin  --port 8091
```

**`scripts/dev-local-preview.sh`** 是三者一体的封装（portal 8090 + admin 8091 +
API 8010），但它**硬性要求 PostgreSQL**（`SOYMUTDB_DATABASE_URL` +
`SOYMUTDB_JWT_SECRET`，见脚本 40 行），本机没有 PG 时跑不了。

> 不要再写临时 `.serve.py`。手搓的版本没有 `/api` 代理、没有 clean-URL 映射、
> 还得自己猜 `dist/external` 这个已失效的路径。

## 4. 只看静态产物（无后端）

```bash
export PATH="/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH"
python3 -m http.server 8080 --bind 0.0.0.0 --directory apps/web/dist
```

后端未起时列表区为空、首页显示降级提示——这是**真实行为**，不是 bug。

## 5. 端口 80 需要 root

```
ip_unprivileged_port_start = 1024   # 本机
uid = 1001, sudo 需密码
```

代理无特权，**绑不了 80**。要 `http://100.77.182.76/`（无端口）必须由用户执行：

```bash
sudo ln -sf /mnt/data02/T25ronglin/code/web/apps/web/dist \
         /var/www/html && sudo systemctl reload nginx 2>/dev/null || true
# 或最简：
cd /mnt/data02/T25ronglin/code/web && sudo python3 -m http.server 80 \
   --bind 0.0.0.0 --directory apps/web/dist
```

## 6. 本机地址

| 地址 | 说明 |
| --- | --- |
| `10.133.20.92` | 内网 |
| `100.77.182.76` | Tailscale，**用户指定的对外预览地址** |

## 7. ⚠️ 本机**有** PostgreSQL —— 在 `webdb` 环境里

**这一条之前写错过，代价是好几轮"本机起不了后端"的错误结论。纠正如下。**

```bash
mamba env list     # webdb = /mnt/data02/T25ronglin/.miniforge3/envs/webdb
```

`webdb` 环境里有**完整的服务端和依赖**：

| 类别 | 内容 |
| --- | --- |
| PostgreSQL 服务端 | `postgres` `initdb` `pg_ctl` `psql` `pg_isready` `createdb` |
| Python 3.14.7 | fastapi 0.137.1、uvicorn 0.134.3、sqlalchemy 2.1.0、asyncpg 0.31.0、alembic 1.20.0、celery 5.6.3、redis 6.4.0 |

所以**本机可以跑通完整后端**，不必退化成只看静态页面。完整启动顺序见下节。

没有 Redis 服务端二进制，Celery worker 跑不了；用
`SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false` 让 API 跳过 outbox。

### 完整全栈启动（已实测通过）

```bash
E=/mnt/data02/T25ronglin/.miniforge3/envs/webdb
cd /mnt/data02/T25ronglin/code/web

# 1) 集群只需初始化一次
export PATH="$E/bin:$PATH"
PGDATA="$PWD/.local-pg/data"
[ -d "$PGDATA" ] || initdb -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8
postgres -D "$PGDATA" -p 5432 -k "$PWD/.local-pg" -c listen_addresses=127.0.0.1
createdb -h 127.0.0.1 -p 5432 -U postgres soymutdb   # 已存在会报错，忽略

# 2) 迁移（45 个）
cd apps/api
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev $E/bin/python -m alembic upgrade head

# 3) 本地管理员
cd ../..
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev $E/bin/python scripts/dev/seed-local-account.py \
  --username admin --email admin@local --password 'LocalDev!2026'

# 4) API
cd apps/api
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false \
SOYMUTDB_JWT_SECRET="local-dev-only-secret-at-least-32-chars-long" \
SOYMUTDB_REFRESH_COOKIE_SECURE=false SOYMUTDB_CORS_ORIGINS="<前端地址>" \
$E/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

**登录账号**：`admin` / `LocalDev!2026`（administrator）。

**登录需要 `Origin` 头**：curl 测登录必须带
`-H "Origin: http://100.77.182.76:8081"`，否则 401
`Request origin could not be verified`。浏览器自带，无需处理。

**API 路由前缀**是 `/api/v1`，健康检查在 `/health`（**不在** `/api/v1/health`）。

### 构建时指向真实 API

```bash
export VITE_API_BASE_URL="http://100.77.182.76:8010/api/v1"
```

门户与管理端**必须各自独立源**（仓库契约：external/internal 与 portal/console
都是分离的安全边界）。所以构建时 admin 用同一个 API 地址，但**伺服端口不同**：

```bash
node scripts/dev/local-preview-server.mjs --app portal --dist apps/web/dist --port 8080
node scripts/dev/local-preview-server.mjs --app admin  --port 8081
```

> `--dist apps/web/dist` 必须显式给：脚本默认 `dist/external`，而普通
> `max build` 把它删了，会 404。

## 8. 本机确实缺失的能力

- **无 Docker** → `compose-acceptance`、`image-build`、`release`、
  `clickhouse-migration`、`mcp-e2e`、211 个 testcontainers 测试无法本地跑
- **无 Redis 服务端** → Celery worker 跑不了
- `uv` 在 `~/.local/share/uv/tools` 上是**只读**的 → `deptry-*` / `pip-audit-*`
  本地必然失败，这是环境问题不是代码问题（CNB 上通过）
- **绑不了 80 端口**（见第 5 节）
- 每个 bash 调用在**独立 pid namespace**，`pgrep` 看不到上一次调用起的进程；
  但它们仍在服务。后台常驻进程要用 `run_in_background` 托管，
  `nohup ... &` 和 `pg_ctl start` 都会在调用结束后被清理

## 9. 临时文件

- `/tmp` **不跨 bash 调用保留**（踩过两次）→ 临时文件放工作区内
- 工作区 scratch 用完即删：`.ph` `.cache` `.serve.py` `e2e/.shot-*.png`
- `.local-pg/` 是本地数据库集群，**保留**（重装代价大）；`data/` 在 gitignore 内