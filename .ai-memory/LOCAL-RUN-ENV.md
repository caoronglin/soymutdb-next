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

## 7. 本机缺失的能力（不要重复尝试）

- **无 Docker** → `compose-acceptance`、`image-build`、`release`、
  `clickhouse-migration`、`mcp-e2e`、211 个 testcontainers 测试均无法本地跑
- **无 PostgreSQL** → 本机起不了 API
- `uv` 在 `~/.local/share/uv/tools` 上是**只读**的 → `deptry-*` / `pip-audit-*`
  本地必然失败，这是环境问题不是代码问题（CNB 上通过）
- 每个 bash 调用在**独立 pid namespace**，`pgrep` 看不到上一次调用起的进程；
  但它们仍在服务。后台常驻进程要用 `run_in_background` 托管，
  `nohup ... &` 会在调用结束后被清理

## 8. 临时文件

- `/tmp` **不跨 bash 调用保留**（踩过两次）→ 临时文件放工作区内
- 工作区 scratch 用完即删：`.ph` `.cache` `.serve.py` `e2e/.shot-*.png`