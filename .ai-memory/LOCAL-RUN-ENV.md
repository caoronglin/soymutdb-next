# 本机运行速查 — T4 宿主机

> 本文件记录**本机如何把站点跑起来**。历史会话已经重复踩坑若干次
> （重复手搓静态服务器、重复发现构建失败、重复忘记 mamba 环境），
> 故单独成文。**先读本文件，再动手。**

## 1. 环境：必须用 mamba

```bash
export PATH="/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH"
```

- `node` v26.10.0、`python3` 3.14.8 都在这个 env 里
- 这个 `python3` 只是**通用工具**。仓库的 `apps/api`、`apps/worker`、`apps/mcp-server`、
  `packages/jobs-py` 都声明 `requires-python >=3.15`，用 3.14 建不了它们的 venv；
  跑后端请用第 10 节的 `.mamba-root/envs/py315/venvs/*`。
- **系统 python 不带依赖**；`/usr/local/bin/corepack` 属于另一套无关的
  Node 安装（0.34.5，四月装的），本机的 `node` 不带 corepack（Node 25+
  已从发行版移除）
- 常规 pnpm 命令沿用现有缓存，不设置 `PNPM_HOME` / `XDG_CACHE_HOME`。
  将它们重定向到空目录会触发重新下载与签名校验，离线时容易卡住。
  仅在 `pnpm dlx` 明确报告缓存不可写时，为该次命令指定可写缓存。

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

注意分工：`webdb` 的价值是**带一整套 PostgreSQL 服务端**，它的 python 是 3.14，只够起库和跑 psql；
API/Worker 本身要用 3.15 解释器（见第 10 节），两者不要混。

Redis 服务端二进制现在仓库内有了（`.deploy/bin/redis-server`，8.10.1，见第 10 节），
起一个隔离实例就能用。**但队列本身还没有实测**：Celery 真正收发任务、以及 API outbox 派发，
都要等 3.15 科学环境装完后再验证（主 agent 负责补）。在验证之前，不要写「Celery 队列已跑通」。
暂时不接 Redis 时，仍可用 `SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false` 让 API 跳过 outbox——
这一条与 Redis 有无无关，一直有效。

### 完整全栈启动（已实测通过）

```bash
E=/mnt/data02/T25ronglin/.miniforge3/envs/webdb
API_PY=/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/api/bin/python
cd /mnt/data02/T25ronglin/code/web

# 1) 集群只需初始化一次
export PATH="$E/bin:$PATH"
PGDATA="$PWD/.local-pg/data"
[ -d "$PGDATA" ] || initdb -D "$PGDATA" -U postgres --auth=trust --encoding=UTF8
postgres -D "$PGDATA" -p 5432 -k "$PWD/.local-pg" -c listen_addresses=127.0.0.1
createdb -h 127.0.0.1 -p 5432 -U postgres soymutdb   # 已存在会报错，忽略

# 2) 迁移（head 目前是 0047，单 head；以 `alembic heads` 的实际输出为准）
cd apps/api
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev $API_PY -m alembic upgrade head

# 3) 本地管理员
cd ../..
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev $API_PY scripts/dev/seed-local-account.py \
  --username admin --email admin@local --password 'LocalDev!2026'

# 4) API
cd apps/api
SOYMUTDB_DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/soymutdb" \
SOYMUTDB_APP_ENV=dev SOYMUTDB_OUTBOX_DISPATCHER_ENABLED=false \
SOYMUTDB_JWT_SECRET="local-dev-only-secret-at-least-32-chars-long" \
SOYMUTDB_REFRESH_COOKIE_SECURE=false SOYMUTDB_CORS_ORIGINS="<前端地址>" \
$API_PY -m uvicorn app.main:app --host 0.0.0.0 --port 8010
```

`$API_PY` 必须是 3.15 解释器（`apps/api` 声明 `requires-python >=3.15`）；`$E/bin/python`（3.14）
只用于上面的 `initdb` / `postgres` / `createdb` 这些 PostgreSQL 服务端命令。

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
- **~~无 Redis 服务端~~（旧记录，已作废）** → `.deploy/bin/redis-server` 8.10.1 可用，可起隔离实例；
  Celery 队列与 outbox 的实测仍待 3.15 环境完成后补齐
- `uv` 在 `~/.local/share/uv/tools` 上是**只读**的 → `deptry-*` / `pip-audit-*`
  本地必然失败，这是环境问题不是代码问题（CNB 上通过）
- **绑不了 80 端口**（见第 5 节）
- **看不到 ≠ 已死**（2026-10-15 复核）。每次 bash 调用跑在自己的 pid namespace，`ps -p` / `pgrep`
  只能看到本 namespace 的进程，所以「`ps` 查不到某个 PID」**不能**证明那个进程已经结束。实测
  `/tmp/trgm-pg/data/postmaster.pid` 仍在（记录 PID 1181260），本调用的 `ps -p` 查不到它；同时
  `pg_isready -h /tmp/trgm-pg/sock -p 55439` 返回 `no response`。真正说明「没有服务在应答」的是
  `pg_isready`，不是 `ps`。要跨调用常驻用 `run_in_background` 托管，不要靠 `nohup ... &` 猜。

## 9. 临时文件

- **`/tmp` 现在是跨调用、跨天持久的**（2026-10-15 复核，与早期记录相反）。实测：10-12 建的
  `/tmp/c2pg`、10-13 建的 `/tmp/spg`、`/tmp/trgm-pg`、10-14 建的 `/tmp/soymutdb-uv-cache`
  在 10-15 全部可见。一次性 PostgreSQL 集群与 uv 缓存放 `/tmp` 是安全的（例如
  `.mamba-root/envs/postgres16/bin/pg_ctl -D /tmp/<name>/data`）。
- 文件持久**不等于**进程状态已知。要判断某个一次性集群是否还在服务，按这个顺序取证，不要靠猜：
  1. `pg_isready -h /tmp/<name>/sock -p <port>`（TCP 端口就换成 `-h 127.0.0.1`）；
  2. `.mamba-root/envs/postgres16/bin/pg_ctl -D /tmp/<name>/data status`——它自己判断 pid 文件里的
     进程是否活着，stale pid 会被识别为 stale，而不是一概当成「还在跑」；
  3. 确认这个数据目录的**归属者**：哪个 PG 版本 `initdb` 出来的、有没有别的调用正在用它。
- **不要为了「解锁」手工删 `postmaster.pid`。** PID 会复用；删掉一个属于**仍在运行**实例的 pid
  文件，可能让下一次 `pg_ctl start` 在同一数据目录上再起一个 postmaster。只有 1、2 都确认该实例确实
  不服务之后才动手，并且优先走 `pg_ctl` 自己的 stale-pid 路径，而不是手删文件。
- 工作区 scratch 用完即删：`.ph` `.cache` `.serve.py` `e2e/.shot-*.png`
- `.local-pg/` 是本地数据库集群，**保留**（重装代价大）；`data/` 在 gitignore 内

## 10. 补充：验证用二进制与候选环境（本节新增，均已实测存在）

第 7、8 节之外，本机还有下列**真实可用**的能力。路径都已核对过，版本号是实际输出，
不是计划值。

### ClickHouse：仓库内有服务端二进制（**历史路径**，不是默认运行时）

```bash
.deploy/bin/clickhouse --version
# ClickHouse local version 26.9.1.147 (official build).
```

所以 **liveCH 可以在本机跑真实 ClickHouse**，不需要 Docker、不需要外部实例。但要清楚它的用途：
PostgreSQL 已经是权威库，ClickHouse 现在只剩「迁移源」身份，验证的是
`deploy/scripts/migrate-clickhouse.sh` / `native_backfill` 这条历史链路，或
`docker-compose.legacy-clickhouse.yml` 显式 overlay 背后的行为。它跑绿**不表示**默认运行时需要它。

- **隔离验证模式：数据目录放 `/tmp`**（例：`/tmp/<name>/`），跑完即弃。这样不会碰到
  任何仓库内或生产数据。
- 日志参考 `.deploy/logs/clickhouse.log` / `clickhouse.err.log` / `clickhouse-init.log`。
- **不要**复制任何现有数据目录来启动，也不要在这条路径上跑破坏性 SQL。这里只做
  「起一个隔离实例 → 写入 → 查询 → 关掉」的验收。
- 坑：进程被回收后 **PID 不存在 ≠ 优雅关闭**。判定要分开写，别把「进程没了」记成
  「干净停机」。

### Redis：仓库内有服务端二进制（2026-10-15 复核，推翻旧记录）

```bash
.deploy/bin/redis-server --version
# Redis server v=8.10.1 sha=931aec3d:0 malloc=jemalloc-5.3.0 bits=64 build=b12c0d6837d75009
.deploy/bin/redis-cli --version
# redis-cli 8.10.1 (git:931aec3d)
```

同目录还有 `redis-cli` 与 `redis-sentinel`。**「本机没有 Redis 服务端二进制 → Celery worker
跑不了」是旧记录，已作废**：二进制在仓库内，起一个隔离实例即可，不需要 Docker。

- 同样用**隔离验证模式**：数据目录放 `/tmp/<name>/`，独立端口，只绑 `127.0.0.1`，跑完即弃，
  不要指向任何现有 dump 或仓库内数据。
- 想让服务跨 bash 调用常驻，用 `run_in_background` 托管（见第 8 节：`ps` 看不到不等于已死）。
- **2026-10-16 已验收 Redis/Celery 基础链路**：独立 Redis 8.10.1、Python 3.15 Worker 定向 ping、任务投递与结果回传成功。API outbox → 业务任务 → S3 的完整链路仍未实测。

### Python 3.15 候选环境（仓库内 `.mamba-root`，不是 miniforge）

| 用途 | 路径 | 实测版本 / 状态（2026-10-15 复核） |
| --- | --- | --- |
| API | `.mamba-root/envs/py315/venvs/api/bin/python` | **3.15.0**，`alembic` / `asyncpg` / `fastapi` 已装，`alembic heads` → `0047 (head)` |
| worker | `.mamba-root/envs/py315/venvs/worker/bin/python` | 3.15.0，最新依赖已完整安装；原生全套 657 passed、零跳过，科学能力检查通过 |
| jobs-py | `.mamba-root/envs/py315/venvs/jobs-py/bin/python` | 3.15 |
| MCP 候选 A | `.mamba-root/envs/py315/venvs/mcp-candidate/bin/python` | **3.15.0** |
| MCP 候选 B（兼容对照） | `.mamba-root/envs/py315/venvs/mcp-compat314/bin/python` | **3.14.8** |
| MCP 正式 | `.mamba-root/envs/py315/venvs/mcp-server/bin/python` | 3.15 |

跑 3.15 侧测试要用**对应 venv 的 python**，不要用系统 python，也不要用 `webdb`
（3.14）。目录名是 `mcp-candidate`，不带 `3.15` 后缀。

Python 3.15 已完成 API / Worker / MCP 本机运行验证；默认 Worker 不再安装 chdb，历史引擎测试单独在 3.14 迁移通道跑。Docker 镜像、生产切换未实测。证据见 `docs/dev/fullstack-validation-20261015.md`。

### PostgreSQL 16（与 `webdb` 里的 PG 独立）

```bash
.mamba-root/envs/postgres16/bin/postgres --version   # PostgreSQL 16.15
```

第 7 节的 `webdb` PG 用于「跑通全栈」；这个 `postgres16` env 用于**临时验证集群**
（`initdb` 到 `/tmp`、`--auth=trust`、只绑 `127.0.0.1`），两者不要混用。

> ⚠️ **PG 16 ≠ CI 的 PG 18。** 用它跑出来的绿，只能证明「代码在本机 PG 16 上绿」，
> 汇报时必须带上这个限定。

### 沙箱权限：socket 与 TestClient 需要窄授权

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| FastAPI `TestClient` 在沙箱里**挂住不返回** | 沙箱禁止/限制本地 socket | 在**同一 env 外**跑即可通过；这是环境问题，不是代码缺陷 |
| 需要绑定端口的探针报 permission denied | 沙箱网络限制 | 申请**窄范围**授权即可，不要申请全网络权限 |

判据固定为：**同一个环境外运行能过**。写结论时要把「沙箱内失败 / 环境外通过」写成
环境限定，不要写成产品缺陷，也不要反过来隐去沙箱内的失败现象。

## 11. 2026-10-17 原生 S3 / 回填 / 灾备验收

- 可用 MinIO/mc 已从官方源码编译在 `/tmp/soymutdb-native-bin`；不要执行 `.deploy/bin/minio*.part`。Go 工具链 `/tmp/soymutdb-go-toolchain/go`，固定源码版本见 `docs/dev/native-validation-20261017.md`。
- 已完成真实 API→outbox→Redis/Celery315→S3导出、PG18.6/六桶恢复115检查、真实CH26.9→PG18.6回填5facts/receipt/门禁/3负例。生产未操作。
- 运维原生模式 `--runtime native --no-repo-env`，PATH必须有PG18全部客户端与mc；写入停止确认与隔离目标配置见灾备指南。
- 本轮 Worker、Redis56389、源S3 59000、目标S3 59010、历史CH58123/59020、PG55448均已干净停止；数据/备份/脱敏证据保留。
- 历史CH演练只用/tmp全新目录，不能复用.deploy历史数据。global thread pool64导致启动池饥饿；改256并限制IO8/parts loading2后就绪。不支持`background_loading_threads`/`foreground_loading_threads`顶层键，不能关闭配置验证绕过。

## 12. 2026-10-17 夜（DSH 多 subagent 轮）环境补充

- **DSH bash 每次调用是新的 bwrap 进程，`/tmp` 是本次调用新建的 tmpfs**（`--tmpfs /tmp`）。
  跨调用 /tmp 不保留（第 9 节的"持久 /tmp"只适用于非 DSH 的 shell）。临时文件放
  `.cache/`（已 gitignore）；不要再用 /tmp 做跨步骤缓存。
- **PNPM_HOME 必须指到工作区内**：全局 store 只读，`pnpm -v` 会报
  `create the temporary package manager install directory ... Read-only file system`。
  用 `export PNPM_HOME="$PWD/.ph"`（`.ph/` 已加入 .gitignore），之后 `pnpm -v` = 12.11.2。
- **turbo 默认 strict env mode 不把线程限制变量传进任务**。受限机器上
  `pnpm turbo run build` 仍可能让 Go/esbuild 用满 CPU 并 `newosproc` /
  `spawn ... EAGAIN`。可用的替代顺序：
  1. 直接逐包构建：`pnpm --filter @soymutdb/web build:sites`、`pnpm --filter @soymutdb/admin build`
     （本机 web 双站与 admin 均成功）；
  2. `TURBO_ENV_MODE=loose` / `--env-mode=loose` 可把 `GOMAXPROCS` 等传进任务，但对
     jbrowse 的 Terser 多进程 esbuild 仍不够；
  3. 不要因为 jbrowse 构建 EAGAIN 就判定代码坏了——同一棵树里 web/admin 构建能过，
     这是进程/线程配额问题，记录为环境限制。
- **2026-10-19 已修：线程限制变量现在由 `turbo.json` 的 `globalEnv` 转发**。
  此前 `RAYON_NUM_THREADS` 只声明在 `build` 任务的 `env` 里，`test`/`lint`/`typecheck`
  任务在 strict env mode 下拿不到它，于是 vitest 启动时 rayon 全局线程池按
  `num_cpus`（本机 256）创建线程，被 cgroup 以 `EAGAIN` 拒绝，报
  `The global thread pool has not been initialized.: ThreadPoolBuildError` /
  `failed to load config ... [Error: Panic in async function]`，**看起来像测试失败，
  实际是环境变量没传进去**。现已把 `GOMAXPROCS`/`RAYON_NUM_THREADS`/`UV_THREADPOOL_SIZE`/
  `OPENBLAS_NUM_THREADS`/`OMP_NUM_THREADS` 加进 `globalEnv`，`export RAYON_NUM_THREADS=1`
  后 `pnpm turbo run lint typecheck test --concurrency=1` 全绿（36/36，3m38s）。
  另：受限机器上 turbo 要串行（`--concurrency=1`），并发跑会 OOM/137。
- **API 测试库**：本机 PG16.15 在 `127.0.0.1:55432`，超级用户 `postgres`（trust）。
  每次验收新建专用库（例 `soymutdb_test_round1`），并设
  `SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://postgres@127.0.0.1:55432/<db>'`、
  `SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`、`PYTHONPATH="<repo root>"`（`tests/a0` 需要 repo 根）。
- **Worker 测试**的 PG 环境变量：`SOYMUTDB_NATIVE_TEST_DATABASE_URL`、
  `SOYMUTDB_STATIC_TEST_DATABASE_URL` 与 `SOYMUTDB_WORKER_TEST_DATABASE_URL`。
  **它们不再是「可选」，缺省即失败**（ISSUE #51）：前两者指向 25 项原生/静态 PG 用例，
  第三者是 BLAST 的 build/pipeline 两个 suite。之前缺省走 `pytest.skip`，在 pytest 汇总里
  和「跑过并且通过」长得一样，于是从未真正执行过。
  正式入口是 `bash scripts/with-postgres-service.sh --print-exports`，它会从
  `SOYMUTDB_TEST_DATABASE_URL` 派生出 **psycopg2 同步 URL**（那几个 suite 用 `create_engine`，
  asyncpg 的 URL 在 worker 环境里连不上）：
  `env $(bash scripts/with-postgres-service.sh --print-exports) pytest apps/worker/tests -q`
  DIAMOND 与 2M 性能档仍然是显式 opt-in。BLAST 的 `SOYMUTDB_TEST_NCBI_BIN_DIR`
  也是显式 opt-in（CI 没有 `makeblastdb`），那一条 skip 是合法的：
  同一次运行里数据库变量必须 fail-closed，二进制可以 skip。
- **MCP `test_transport_auth.py` 的 3 项**会 spawn 真实 `127.0.0.1` HTTP 服务；在 DSH 沙箱内
  子进程起不来（`FastMCP HTTP server did not start`）。这是环境限制，环境外/CI 66 passed。
- **字体子集化**：`scripts/subset-portal-fonts.py` 需要 fontTools + brotli；本机只有
  `/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin/python` 同时具备
  （API/worker venv 有 fontTools 但无 brotli）。产物在 `apps/{web,admin}/public/fonts/harmonyos/`，
  守卫 `scripts/test_portal_font_subset.py` 不需要 fontTools。


## 沙箱进程配额与 vitest worker（2026-10-18 补充）
`apps/admin` 的 `vitest` 配置用 `pool: "forks"`（CI 正确）。当沙箱同时有其它重任务时，forks worker 可能 spawn 失败：
`Error: [vitest-pool]: Worker forks emitted error` + `EAGAIN ... spawn node`，此时测试文件可能已全部通过（例如 16/16 files、119 tests）才报错。
workaround（仅本机）：`pnpm exec vitest run --pool=threads --maxWorkers=1`，本轮 23 files / 172 tests 全绿；不要为此改提交里的 vitest 配置。

## webpack 压缩器线程数与本机 256 核（2026-10-29 补充）

**症状**：本机 `apps/jbrowse`（以及 admin / web 站点构建）打包失败，日志里是

```
runtime: failed to create new OS thread (have 4 already; errno=11)
fatal error: newosproc
...
ERROR in assets/xxxx.js
assets/xxxx.js from Terser plugin
EAGAIN
Error: EAGAIN
    at new Worker (node:internal/worker:380:19)
    at ExperimentalWorker.initialize (.../jest-worker/build/workers/NodeThreadsWorker.js:79:20)
```

**根因（已实测，不是猜测）**：webpack 自带的 `TerserPlugin` 默认 `parallel: true`，
其 worker 数 = `os.cpus().length - 1`。本机 `os.cpus().length` = **256** ⇒ 打包要起 255 个
worker 线程；本机沙箱拒绝这种规模的线程创建，于是每个 async chunk 都报 EAGAIN。
`ulimit -u` 是 3.8e6、cgroup `pids.max` 是 629145、`/tmp` 与磁盘都正常 —— 限制的是**并发线程数**，
不是进程数上限。实测证据：把 `os.cpus()` 报成 4 之后，同一棵树的 webpack **12.98s 编译成功**。

**workaround（仅本机，不改仓库）**：用 preload 缩小“可见 CPU 数”，让压缩器的 worker 池变小。

```bash
mkdir -p .cache/cpu-limit
cat > .cache/cpu-limit/preload.cjs <<'PRELOAD'
// Local-only build shim: this workstation reports 256 CPUs, so webpack's
// minimizer tries to spawn 255 worker threads and the sandbox refuses.
const os = require("os");
const limit = Number(process.env.SOYMUTDB_LOCAL_CPU_LIMIT || 4);
const real = os.cpus();
if (real.length > limit) {
  Object.defineProperty(os, "cpus", { value: () => real.slice(0, limit), configurable: true });
}
PRELOAD
export NODE_OPTIONS="-r $PWD/.cache/cpu-limit/preload.cjs"
```

配合 `GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1` 与
`pnpm turbo run build --concurrency=1`，三端构建均可完成。

**不要**据此判定代码坏了，也不要为此改仓库里的构建配置：
CI 镜像（GitHub runner 2–4 核、CNB stage）`cpus-1` 只有个位数 worker，本来就不会触发。
