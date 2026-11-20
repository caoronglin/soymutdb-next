# 本机运行速查 — WSD509 宿主机（2026-11-09 复核）

> 本文件记录**本机如何把站点跑起来**。历史会话已经重复踩坑若干次
> （重复手搓静态服务器、重复发现构建失败、重复忘记用哪个解释器），
> 故单独成文。**先读本文件，再动手。**
>
> **2026-11-09 全量复核**：本文此前的正文描述的是另一台宿主
> （`/mnt/data02/T25ronglin/...` 路径、`mamba`/`miniforge` 环境、
> `.mamba-root` 下的 3.15 venv、`webdb` 环境里的 PostgreSQL 服务端）。
> **那些路径在本机全部不存在。** 下面正文已按本机实测重写；旧机事实
> 只在第 8 节保留为「换机时的检查清单」。

## 1. 环境：Node 26.13.0 / pnpm 12.11.2 在 `/usr/local/bin`

```bash
export PATH="/usr/local/bin:$PATH"
node -v    # v26.13.0
pnpm -v    # 12.11.2（与 package.json 的 packageManager pin 一致）
```

- 仓库 `.nvmrc` pin **26.13.0**，`package.json` 的 `engines` 要求 `>=26.13.0 <27`。
  `/usr/local/bin/node` → `/usr/local/lib/node/current/bin/node` 正是 26.13.0，**符合 pin**。
- **PATH 里默认排在前面的是 Pi 自带的 Node 22.23.3**
  （`/root/.local/share/pi-node/current/bin`）。它是 Pi 运行时自用的，
  **不要与仓库命令混用**：仓库的 `engines` 不接受 22.x。
  所以每条仓库命令都要先 `export PATH="/usr/local/bin:$PATH"`。
- 本机**没有** mamba / miniforge / conda（`/mnt` 为空）。
  通用 Python 是系统 3.13.5，**不带 pytest 等仓库依赖**；后端一律用
  仓库内 venv（见第 2 节）。
- pnpm store 在 `/root/.local/share/pnpm/store/v11`，可写，缓存可用；
  **不要**把 `PNPM_HOME` / `XDG_CACHE_HOME` 重定向到空目录（会触发重新下载）。

## 2. 后端：仓库内 venv，Python 3.15.0

| 用途 | 路径 | 实测 |
| --- | --- | --- |
| API | `apps/api/.venv/bin/python` | **3.15.0**，已装 `fastapi 0.143.3` / `sqlalchemy 2.1.8` / `redis 8.1.0` / `celery 5.7.0`，以及 editable 的 `soymutdb-api` / `soymutdb-jobs` / `soymutdb-import-protocol` / `soymutdb_bio_core 0.1.2` |
| Worker | `apps/worker/.venv/bin/python` | **3.15.0**，`scanpy 1.12.4` / `anndata` / `cyvcf2` 已装 |

- ⚠️ **`apps/worker/.venv` 没有 `pip`**（由 uv 建的环境）。不要用
  `apps/worker/.venv/bin/pip`；装依赖走
  `python scripts/install_python_workspace.py --venv apps/worker/.venv "apps/worker[dev]"`。
- ⚠️ **`apps/mcp-server/.venv` 不存在**。MCP 的测试需要先按
  `apps/mcp-server/pyproject.toml` 建 venv；`packages/jobs-py` 没有独立
  venv，它被 editable 装进了 API/Worker venv。
- 系统 `python3`（3.13.5）**没有 pytest**。跑 `pytest scripts` 要用
  `apps/api/.venv/bin/python -m pytest scripts -q`。

## 3. PostgreSQL：**本机有 Docker**，用仓库自带的 disposable 服务

本机 Docker 29.9.3 可用（`docker info` 正常）。仓库的
`scripts/with-postgres-service.sh` 会起一个一次性 PostgreSQL 18.6 容器
（`soymutdb-pg-test`，`127.0.0.1:5432`），并打印可直接消费的导出行：

```bash
bash scripts/with-postgres-service.sh --print-exports
# SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_testfixtures
# SOYMUTDB_DATABASE_URL=postgresql://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_testfixtures
# SOYMUTDB_NATIVE_TEST_DATABASE_URL=postgresql+psycopg2://...
# SOYMUTDB_STATIC_TEST_DATABASE_URL=postgresql+psycopg2://...
# SOYMUTDB_WORKER_TEST_DATABASE_URL=postgresql+psycopg2://...
# SOYMUTDB_RUN_POSTGRES_INTEGRATION=1
```

- 这**取代**了旧文档里的「本机 PG16 在 55432 + `postgres/localonly` 凭据」：
  那套凭据在本机**不存在**（本机 5433/5434 上有别的实例，`postgres/localonly`
  认证失败，别拿它跑仓库测试）。
- Worker 的三个同步 URL（`NATIVE` / `STATIC` / `WORKER_TEST`）由脚本从
  `SOYMUTDB_TEST_DATABASE_URL` 派生，**不要手写**。
- 消费方式（CNB stage 里是 `sh`，没有 `source`）：

```bash
PG_ENV="$(bash scripts/with-postgres-service.sh --print-exports)"
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$PG_ENV"
```

## 4. 前端：Node 26 + 线程限制变量

```bash
export PATH="/usr/local/bin:$PATH"
export GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
```

- 本机 **16 核 / 55 GB**，不像旧机 256 核那样触发 webpack Terser 的
  255 worker 线程风暴，所以旧文档里的 `NODE_OPTIONS=-r .cache/cpu-limit/preload.cjs`
  技巧在本机**不必要**（`.cache/cpu-limit/` 里那份 shim 也已不存在）。
- `OPENBLAS_NUM_THREADS=1` 仍要带：`scripts/check:contract` 会导入
  FastAPI → SciPy → OpenBLAS，默认线程数会耗尽 cgroup。
- 旧文档第 12 节说「`turbo.json` 的 `globalEnv` 已转发线程变量」——**这条仍然成立**，
  现行 `turbo.json` 的 `globalEnv` 里有 `GOMAXPROCS` / `RAYON_NUM_THREADS` /
  `UV_THREADPOOL_SIZE` / `OPENBLAS_NUM_THREADS` / `OMP_NUM_THREADS`。
- `pnpm turbo run lint typecheck test` 在本机 `--concurrency=2` 可跑完
  （36/36 任务，6m45s）；不需要 `--concurrency=1`。

## 5. 起服务：用仓库脚本，不要手搓

- **正式入口**：`scripts/start-cloud-dev.sh`（CNB 云开发）。
- **单应用伺服**：`scripts/dev/local-preview-server.mjs`
  ——门户 8090 / 控制台 8091：

```bash
node scripts/dev/local-preview-server.mjs --app portal --port 8090
node scripts/dev/local-preview-server.mjs --app admin  --port 8091
```

- **只看静态产物**（无后端）：`python3 -m http.server 8080 --directory apps/web/dist`。
  后端未起时列表区为空、首页显示降级提示——这是**真实行为**，不是 bug。
- `scripts/dev-local-preview.sh` 硬性要求 PostgreSQL + `SOYMUTDB_JWT_SECRET`，
  本机有 PG 时可用。

> 不要再写临时 `.serve.py`。手搓版本没有 `/api` 代理、没有 clean-URL 映射、
> 还会猜错 `dist/external` 这个路径。

## 6. 端口 80：**本机是 root，可以绑**

旧机是 uid 1001 且 `ip_unprivileged_port_start=1024`，绑不了 80。
**本机 `id -u` = 0**，所以 80 / 443 直接可绑，不需要 `sudo`：

```bash
python3 -m http.server 80 --bind 0.0.0.0 --directory apps/web/dist
```

## 7. 浏览器门禁：Playwright chromium 已装

- `~/.cache/ms-playwright` 里有 `chromium-1248`、`chromium_headless_shell-1248`、
  `ffmpeg-1013`。`e2e/node_modules/.bin/playwright` 存在。
- 10 项离线 artifact E2E 的正式入口：

```bash
bash scripts/build-all-static-apps.sh     # 四套制品（web external/internal + admin + jbrowse）
bash scripts/verify-artifact-e2e.sh        # 10 个门禁 sweep（第 10 项 subpath-artifact 需要先跑 build-pages-artifact.sh，否则报 SKIPPED 并给出命令）
```

- 浏览器必须**在 `e2e/` 目录里**跑（`node_modules` 只装在那里）；从 `/tmp`
  运行会报 `Cannot find package 'playwright'`。

## 8. 本机缺失 / 限制（诚实记录）

| 能力 | 状态 | 影响 |
| --- | --- | --- |
| Docker | **有**（29.9.3） | `compose-acceptance` / `image-build` / `release` / `clickhouse-migration` 仍需要额外凭据或镜像，但不再是「无 Docker」 |
| PostgreSQL 服务端 | 有（容器化 18.6） | 旧文档的 `.mamba-root/envs/postgres16` 与 `webdb` env **不存在** |
| mamba / miniforge / conda | **无** | 旧文档的 `opencode` / `webdb` env 路径全部失效 |
| `.mamba-root/envs/py315/venvs/*` | **无** | 旧文档的 API/Worker/MCP 解释器路径失效；用 `apps/*/.venv` |
| Redis 服务端二进制 | `.deploy/bin/` 不存在 | 需要 Redis 时用容器，或临时起一个（Celery/outbox 链路） |
| `apps/mcp-server/.venv` | 无 | MCP 测试需先建 venv |
| `uv` | 有（0.13.1，`/root/.local/bin/uv`） | 与 `AGENTS.md` 的 uv pin 一致，可建 3.15 venv |
| 端口 80 | **可绑**（root） | 与旧机相反 |
| `/mnt/data02` | 不存在 | 旧机全部路径失效 |

## 9. 临时文件与进程

- `/tmp` 在本机**跨调用持久**（实测写 `/tmp/pi-persist-probe` 后仍在）。
  一次性 PostgreSQL 集群放 `/tmp/<name>/` 是安全的。
- **看不到 ≠ 已死**：每次 bash 调用是自己的进程视角，`ps -p` 查不到 PID
  不能证明进程已结束。判断服务是否在应答用 `pg_isready` 或直接请求端口。
- 工作区 scratch 用完即删：`.ph` `.cache` `.serve.py` `e2e/.shot-*.png`。
- `.cache/` 已在 gitignore；本机的 knip 报告、日志都放这里，不提交。

## 10. 门禁复跑速查（本机实测命令）

```bash
export PATH="/usr/local/bin:$PATH"
export GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

# 前端工作区
pnpm turbo run lint typecheck test --concurrency=2

# 契约套件（scripts/）
apps/api/.venv/bin/python -m pytest scripts -q

# API 全量（真实 PostgreSQL）
PG_ENV="$(bash scripts/with-postgres-service.sh --print-exports)"
while IFS='=' read -r k v; do [ -n "$k" ] && export "$k=$v"; done <<< "$PG_ENV"
cd apps/api && PYTHONPATH=/root/webdb-docker ../api/.venv/bin/python -m pytest tests -q

# Worker 全量（同一套 PG 环境变量）
cd ../.. && PYTHONPATH=/root/webdb-docker apps/worker/.venv/bin/python -m pytest apps/worker/tests -q

# knip（依赖治理门）
pnpm dlx --package knip@5.62.0 --package typescript@5.9.3 knip --config knip.json --reporter json

# 制品 + 离线浏览器门禁
bash scripts/build-all-static-apps.sh
bash scripts/verify-artifact-e2e.sh
```

## 11. 换机时的检查清单

换到新机器后，按顺序核对这些**实测值**，不要照抄旧文档里的路径：

1. `node -v` 是否等于 `.nvmrc`；`which node` 排在前面的是不是 Pi 自带 Node。
2. `pnpm -v` 是否等于 `package.json` 的 `packageManager`。
3. `apps/api/.venv/bin/python -V` / `apps/worker/.venv/bin/python -V` 是否 ≥ 3.15。
4. `docker info` 是否可用；`scripts/with-postgres-service.sh --print-exports` 能否拿到 URL。
5. `~/.cache/ms-playwright` 里有没有 chromium。
6. `id -u` 是否为 0（决定能不能绑 80）。
7. `nproc`（决定要不要限线程 / 用不用 CPU-limit shim）。
