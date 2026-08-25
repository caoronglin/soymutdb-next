## [09:03] - Bug 修复: 生产配置校验兼容显式管理员凭据与部分配置调用

- **文件**: `apps/api/app/core/config.py`
- **决策**: 保留 baseline/extended 基础设施默认值拒绝；管理员与 ClickHouse 凭据仅在调用方显式提供时校验，避免局部生产配置测试被默认值误报。
- **验证**: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_config_security.py apps/api/tests/test_auth_sessions.py::TestRefreshCookieConfig apps/api/tests/test_cors_security.py apps/api/tests/test_ratelimit.py -q --tb=short`；36 passed, 7 warnings。

## [09:24] - Bug 修复: PostgreSQL 初始迁移和 page-builder 枚举可执行性

- **文件**: `apps/api/migrations/versions/0001_initial_schema.py`, `apps/api/migrations/versions/0004_add_widget_system.py`, `apps/api/migrations/versions/0009_analysis_jobs.py`, `apps/api/migrations/versions/0016_page_builder.py`, `deploy/conda/verify-baseline.sh`
- **决策**: 使用 `sa.text()` 生成 JSONB 默认值，引用 `end` 保留字，匹配大写分析任务枚举默认值，并创建 page-builder 状态枚举；mamba 验证改用 prefix 内工具绕过只读 mamba proc 锁。
- **验证**: Python 3.14.7 + PostgreSQL 16.15；28 个健康/配置测试通过，Alembic 全量升级、API live/readiness 烟测通过。

## [09:41] - Bug 修复: UI-3 生产 Page Definition 禁止虚拟数据回退

- **文件**: `apps/web/src/page-builder/loader.ts`, `apps/web/src/page-builder/__tests__/loader.test.ts`, `apps/web/src/routes/index.tsx`, `deploy/conda/verify-baseline.sh`
- **决策**: 生产模式 API 失败时返回空定义并保持错误语义，不再把 seed/fallback 当真实 Wm82v4.0 数据；baseline smoke 先迁移并 seed Page Builder，再验证 published `/` definition 的 `resource_cards`。
- **验证**: Python 3.14 + PostgreSQL 16；Alembic 0021、7 个 Page Builder seed、live/readiness、Page Builder JSON contract 全部通过；Web typecheck/lint 与 loader 回归通过。

## [09:53] - Bug 修复: UI-3 位置搜索后端拒绝反向坐标

- **文件**: `apps/api/app/api/v1/variants.py`, `apps/api/tests/test_variants.py`, `packages/api-client/src/blast.ts`, `apps/api/app/api/v1/page_definitions.py`
- **决策**: `/variants/region` 强制 start/end >= 1 且 `end >= start`，BLAST client 对齐后端 `expired` 状态和可空 query sequence，整理 Page Definition import。
- **验证**: Ruff UI-3 Python 文件通过；Page Builder registry 26 项、安全配置 25 项通过；4 个区域集成测试因本机无 Docker daemon/外部 PostgreSQL fixture 被阻塞，mamba PostgreSQL/API/Page Builder smoke 已通过。

## [验收整改] - AntD facade 与生产制品占位文本

- **文件**: `apps/admin/src/lib/antd.ts`, Admin 运行时/测试导入文件, `apps/web/index.html`
- **决策**: 将 Admin 的直接 `antd` 导入统一迁移到 facade，补齐 DatePicker/Upload 及类型导出；删除构建 HTML 中会触发生产制品扫描的占位 origin 文本。
- **验证**: Admin facade 回归后 20 文件/57 测试通过，Web/Admin TypeScript 通过，Admin ESLint 0 errors/18 warnings，Admin/Web Vite build 通过；Demo 制品 strict scan 按预期拒绝 fixture，`--allow-demo` 通过；Cloudflare Analytics CSP 构建无重复 origin；视觉回归 15/15 通过（`e2e/visual-artifacts/20260825T020234Z/report.json`）。真实生产环境仍未配置。

## [10:12] - Bug 修复: GitHub frozen lockfile 与 CI 构建环境

- **文件**: `pnpm-lock.yaml`, `.github/workflows/baseline-validation.yml`, `apps/web/vite.config.ts`
- **决策**: 为 JBrowse workspace 补入 `lucide-react` 的完整 lockfile 解析；Web/Admin CI 使用明确的 demo/test origins，API/contract/Windows CI 先安装本地 `packages/jobs-py`；CI 增加 Page Builder published JSON smoke。CSP analytics origin 替换改为幂等。
- **验证**: `PNPM_HOME=/tmp/pnpm-home pnpm install --frozen-lockfile --ignore-scripts --lockfile-only` 通过；GitHub 首轮曾因旧 lockfile 失败，修复提交后已重新触发 workflow；第二轮 Web/Admin 与 OpenAPI 已通过，但两平台配置单测受全局 `SOYMUTDB_DEPLOYMENT_MODE=baseline` 污染，已改为单测步骤显式清除此变量。

## [治理] - 依赖安全、许可证与 Knip 基线收敛

- **文件**: `apps/api/app/core/security.py`, `apps/api/app/core/config.py`, `apps/api/pyproject.toml`, `apps/api/uv.lock`, `apps/worker/pyproject.toml`, `apps/worker/uv.lock`, `apps/mcp-server/pyproject.toml`, `apps/mcp-server/uv.lock`, `dependency-governance.json`, `knip.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.github/workflows/ci.yml`, `docs/ops/dependency-governance.md`
- **决策**: API 使用 PyJWT 并仅允许 HS256/HS384/HS512；升级 Starlette/FastMCP/Uvicorn，固定 lodash/ansi-regex 安全版本；Knip 对动态入口建立显式基线；Python license 审计只运行生产依赖并隔离上游元数据缺失，保留 GPL/LGPL 明确许可清单。
- **验证**: 完整 `scripts/dependency_governance.py audit` 通过：Knip、3 个 deptry、重复版本、循环依赖、前端/Python licenses、pnpm audit、3 个 pip-audit 全部 passed；pnpm audit high/critical 为 0。

## [CI 修复] - JBrowse RxJS 解析与 MCP 启动竞态

- **文件**: `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `.github/workflows/ci.yml`
- **决策**: 将 JBrowse 全 workspace RxJS override 固定到 7.8.0，解决 `@jbrowse/plugin-bed` 从 RxJS 7.0.0 `esm5` 解析不到 `toArray` 的构建错误；MCP e2e 对正确 bearer 请求增加就绪重试，不再仅以反向代理的未授权 401 判断服务已启动。
- **验证**: 远程 CI 已确认 Windows installer、PostgreSQL baseline、Web/Admin baseline、OpenAPI 与 dependency governance 通过；后续提交需复验 JBrowse 与 MCP e2e。

## [CI 修复] - MCP Docker runtime 包导入路径

- **文件**: `apps/mcp-server/Dockerfile`
- **决策**: runtime 镜像显式设置 `PYTHONPATH=/app/src`，避免 uv builder venv 的项目安装路径在多阶段复制后不可用，导致 `python -m mcp_server.server` 启动失败。
- **验证**: 最新远程日志已定位为 `ModuleNotFoundError: No module named mcp_server`；需由下一轮 Docker e2e 验证修复。

## [CI 复盘] - MCP 多阶段镜像 COPY 目标

- **文件**: `apps/mcp-server/Dockerfile`
- **决策**: 仅设置 `PYTHONPATH=/app/src` 不足以修复，因为 runtime `COPY ... ./src` 发生在 `WORKDIR /app` 之前，实际落到了 `/src`；改为绝对目标 `/app/src`。
- **验证**: 远程 readiness 已确认失败仍为 `ModuleNotFoundError`；下一轮需验证 Docker runtime 目录和 MCP e2e。

## [CI 修复] - Native Docker 构建路径与 Compose 校验

- **文件**: `infra/docker/Dockerfile.api`, `infra/docker/Dockerfile.worker`, `apps/mcp-server/Dockerfile`, `docker-compose.yml`, `scripts/test_dependency_governance_contracts.py`, `.github/workflows/baseline-validation.yml`
- **决策**: 将 API/worker/MCP 的 uv 基础镜像统一到 `0.11.33` 以解析当前 lock revision；将本地 `jobs-py` 复制到 lockfile 解析的 `/packages/jobs-py`；删除 ClickHouse migration service 的空 `volumes`；Node SBOM 使用 hoisted pnpm layout；同步治理契约测试。
- **验证**: YAML、`git diff --check`、3 个 `uv lock --check`、治理契约 `8 passed`。

## [CI 修复] - Baseline Node SBOM 证据

- **文件**: `.github/workflows/baseline-validation.yml`
- **决策**: supply-chain job 在 `cyclonedx-npm` 前执行 frozen pnpm install，确保 Node SBOM 工具能读取 lockfile/node_modules，而不是因只有 artifact 输入报 `No evidence`。
- **验证**: 远程日志已定位 `No package lock file nor npm shrinkwrap file` 与 `no node_modules dir`；下一轮 baseline 需复验 SBOM 和 attestations。
