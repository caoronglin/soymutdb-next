# 部署与运维

详细流程以 `docs/ops/ci-cd.md`、`docs/dev/pipeline-migration.md`、
`docs/dev/mamba-validation-environment.md` 为准；本页给出入口与门禁清单。

## 交付流水线

- 权威流水线：`.cnb.yml`；任务体在 `scripts/ci-job-steps.sh`（`list` / `run <job>`）。
- GitHub Actions 仅调用同一批脚本（`.github/workflows/*.yml`），不新增构建/扫描逻辑。
- 镜像验证与发布分离：验证方不持有 registry 凭据；发布方不重建镜像，只发布已验证 digest。

## 门禁命令

```bash
# 前端：安装 → 构建 → 预算 → 单测 → lint → typecheck → 契约
pnpm lint && pnpm typecheck && pnpm test

# 前端产物（含 CSP/_headers、favicon 资产、可见文案预算、页面注册表）
bash scripts/verify-frontend-artifacts.sh

# 后端：架构守卫 + API pytest + worker pytest（真实 PostgreSQL）
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://…/soymutdb_testfixtures' \
  bash scripts/verify-backend-tests.sh

# 冒烟分层（缺前置条件报告 SKIPPED，不计通过）
bash scripts/smoke.sh --profile contracts|static|runtime|e2e|images
bash scripts/acceptance.sh --profile contracts|backend|static|runtime
```

沙箱/CPU 受限环境：`GOMAXPROCS=2 RAYON_NUM_THREADS=1`，turbo 任务图用 `--concurrency=1`。

## 部署

```bash
# Compose（生产）
sudo bash deploy/scripts/upgrade.sh        # 内嵌 backup + migration + 探活 + 失败回滚
bash deploy/scripts/healthcheck.sh         # nginx 入口健康检查

# 无 Docker（Linux systemd / Windows / Conda）
deploy/linux/、deploy/windows/、deploy/conda/README.md
```

- API 容器内监听 `8010`，仅 compose 内网可达；公网入口只有 nginx `8080`。
- 环境变量模板：`deploy/.env.example`（必填镜像 digest、JWT/会话密钥、CORS、数据层凭据）。

## 无 Docker 本机部署（本地完整栈）

本机无 Docker 时，用本地 PostgreSQL + 构建产物 + 同源预览服务器部署完整栈。
已内置支持：`scripts/dev/local-preview-server.mjs --dist <dir>` 与 `/jbrowse/` 前缀。

```bash
# 1) 数据：本地 PG 建部署库并迁移到最新
createdb -p 55432 -h 127.0.0.1 -U soymutdb soymutdb_deploy
cd apps/api && SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_deploy' \
  .venv/bin/python -m alembic upgrade head

# 2) 构建（每个 origin 独立构建；internal 产物另存）
CI= VITE_DEPLOYMENT_MODE=demo VITE_SITE_VARIANT=internal VITE_BASE_URL=/ \
  VITE_API_BASE_URL=http://localhost:8094/api/v1 VITE_JBROWSE_BASE_URL=http://localhost:8094/jbrowse/ \
  pnpm --filter @soymutdb/web build && mv apps/web/dist apps/web/dist-internal
CI= VITE_DEPLOYMENT_MODE=demo VITE_SITE_VARIANT=external VITE_BASE_URL=/ \
  VITE_API_BASE_URL=http://localhost:8090/api/v1 VITE_JBROWSE_BASE_URL=http://localhost:8090/jbrowse/ \
  pnpm --filter @soymutdb/web build
VITE_BASE_URL=/ VITE_API_BASE_URL=http://localhost:8091/api/v1 pnpm --filter @soymutdb/admin build
VITE_BASE_URL=/jbrowse/ VITE_API_BASE_URL=http://localhost:8090/api/v1 \
  pnpm --filter @soymutdb/jbrowse build

# 3) API（8010）
cd apps/api && SOYMUTDB_DATABASE_URL=... SOYMUTDB_JWT_SECRET=<>=32 chars> \
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010

# 4) 三个前端 origin（各自代理 /api → 8010；/jbrowse/ 同源）
node scripts/dev/local-preview-server.mjs --app portal --port 8090
node scripts/dev/local-preview-server.mjs --app portal --dist apps/web/dist-internal --port 8094
node scripts/dev/local-preview-server.mjs --app admin  --port 8091
```

- 端口：external 8090、internal 8094、管理端 8091、API 8010、JBrowse 经 `/jbrowse/`。
- 无 Redis/ClickHouse/MinIO 时 `/api/v1/health/ready` 返回 `degraded`（PG 正常）；
  依赖 ClickHouse 的接口 503、无发布数据时 assemblies 503，均为预期降级。
- 部署前务必确认迁移为最新：`alembic upgrade head`；模型/迁移漂移由迁移 `0042` 修复。

## 备份、迁移与回滚

```bash
bash deploy/scripts/backup.sh             # PostgreSQL + ClickHouse + MinIO + 元数据
bash deploy/scripts/restore.sh            # 恢复
bash deploy/scripts/verify-restore.sh     # 恢复演练校验
bash deploy/scripts/blue-green-rollback.sh
```

- 迁移：`apps/api` 内 `alembic upgrade head`；每次涉及 schema 的变更必须有 PostgreSQL
  升降级测试（示例：迁移 `0040` 的升级/降级已在 55432 实测）。
- 应用回滚不自动回滚已执行的破坏性 migration；使用 expand/contract 步骤。
- 回滚触发条件、审计与演练记录写在对应 PR 与 `docs/ops/` 证据文件。

## 数据维护

| 事项 | 入口 |
| --- | --- |
| 导入创建/校验/发布 | 管理端 `/imports`；`/admin/imports*` API |
| 发布版本切换 | `/releases`；`X-SoyMutDB-Release` 头 |
| 审计 | `/audit`；`/admin` 审计 API |
| 媒体对象 | `/media`；MinIO 桶与校验流程 |
| 静态页面/新闻发布 | `/admin/news`、`/admin/page-builder`、`/admin/build-static` |
