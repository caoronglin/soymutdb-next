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

## [前后端对接] - UI-3 真实数据与失败状态

- **文件**: `apps/web/src/components/home/antd-home.tsx`, `apps/web/src/routes/index.tsx`, `apps/web/src/routes/search/genes.tsx`, `apps/web/src/routes/search/location.tsx`, `apps/admin/src/routes/index.tsx`
- **决策**: 首页最新动态改用 `/news/featured`，删除虚拟新闻；生产首页 Page Builder 资源 API 失败时不显示 legacy fallback；基因/位置查询区分 API 失败与空结果；Admin 指标去除零值 placeholder 并显示加载/错误状态。
- **验证**: Web/Admin `tsc --noEmit` 通过；定向 ESLint 0 error（位置页保留 7 个既有 React effect warnings）；Web/Admin Vite build 通过。

## [CI 修复] - CycloneDX pnpm npm-ls 错误

- **文件**: `.github/workflows/baseline-validation.yml`
- **决策**: 根据 CycloneDX npm 官方 CLI 文档，在 Node SBOM 命令加入 `--ignore-npm-errors`；pnpm 的 virtual-store 被 `npm ls` 标为 `ELSPROBLEMS` 时忽略扫描器诊断，但仍保留生成 SBOM 所需的依赖证据。移除未生效的 node-linker 环境变量。
- **验证**: 远程日志确认失败点是 `npm-ls exited with errors: 1`；下一轮需复验 supply-chain artifact。

## [CI 复盘] - uv workspace 路径

- **文件**: `infra/docker/Dockerfile.api`, `infra/docker/Dockerfile.worker`
- **决策**: 新版 uv 已能解析 lockfile，但要求本地 `soymutdb-jobs` 位于 `/app/packages/jobs-py`；此前绝对复制到 `/packages/jobs-py` 反而导致 `Distribution not found: file:///app/packages/jobs-py`，恢复相对 `/app/packages` 目标。
- **验证**: 最新 baseline 全部通过（含 Windows）；Docker amd64/arm64 失败均收敛为该 API build 路径错误，修复后需重跑多架构构建。

## [CI 修复] - Worker runtime Python 与 shared jobs

- **文件**: `infra/docker/Dockerfile.worker`
- **决策**: worker lockfile 与 `packages/jobs-py` 均要求 Python >=3.14，runtime 原为 3.13 且 smoke 进程无法导入 `soymutdb_jobs`；统一 builder/runtime 到 `python:3.14.6-slim`，并显式设置 `/app/packages/jobs-py/src:/app/apps/worker/src`。
- **验证**: `uv lock --check --project apps/worker` 通过；远程 Docker smoke 的唯一失败为 `ModuleNotFoundError: soymutdb_jobs`，需重跑多架构镜像门禁。

## [CI 修复] - JBrowse nginx 正则配置

- **文件**: `apps/jbrowse/nginx.conf`
- **决策**: nginx 的 `location` 正则含 `{8,}` 时必须整体加引号，否则 nginx 将其解析为未知 directive；同时移除默认已包含的 `text/html` gzip MIME，消除重复 MIME 警告。
- **验证**: 远程 amd64/arm64 镜像均已通过 API、Worker（23 tasks）和 MCP smoke；JBrowse smoke 收敛为 nginx `unknown directive`，修复后需重跑多架构门禁。

## [CI 修复] - 基础镜像系统包安全更新

- **文件**: `infra/docker/Dockerfile.api`, `infra/docker/Dockerfile.worker`, `apps/mcp-server/Dockerfile`
- **决策**: Trivy SARIF 确认 API runtime 的主要门禁来自 Debian 基础包（`util-linux`, `perl-base` 等），而不是 Python 依赖；runtime 构建统一先执行 `apt-get upgrade -y`，API 移除不必要的 `curl/wget` 并改用 Python 标准库健康检查，worker 移除不必要的 curl，MCP runtime 同步升级基础包。
- **验证**: 两架构 JBrowse smoke 已通过；最新 Trivy API SARIF 明确包含 `CVE-2026-53612/53613` 等 Debian 包发现，修复后需复验所有镜像安全门禁。

## [安全治理] - Trivy 未修复基础包例外

- **文件**: `.trivyignore`
- **决策**: 系统升级已消除有 fixed version 的 `util-linux` 等发现；对当前 Debian/Trivy 数据库明确标记为无修复版本的 12 个基础包 CVE 建立可审计例外，保留 CRITICAL/HIGH 固定版本发现的阻断门禁。例外仅针对当前镜像基础包，后续刷新基础镜像或漏洞库时必须重新评估。
- **验证**: 升级后两架构 API SARIF 从 64 条高危发现收敛为 17 条（去重后 12 个无 fixed version CVE），待下一轮 CI 确认全镜像扫描与 release artifact。

## [CI 修复] - 显式传入 Trivy 例外文件

- **文件**: `.github/workflows/ci.yml`
- **决策**: Trivy SARIF 已证明例外文件可使结果归零，但 action 日志显示 `INPUT_TRIVYIGNORES` 为空；为避免依赖隐式工作目录，在四个 CRITICAL/HIGH 阻断扫描中显式设置 `trivyignores: .trivyignore`。
- **验证**: 上一轮全镜像构建、运行时 smoke 与 JBrowse nginx 均通过；唯一失败为 Trivy API scan 未读取例外路径。

## [CI 修复] - Trivy SARIF 严重度阈值

- **文件**: `.github/workflows/ci.yml`
- **决策**: Trivy action 默认在 SARIF 模式下取消 `severity` 过滤，导致已审计的 LOW/MEDIUM 发现仍使 `exit-code: 1` 失败；四个镜像门禁显式设置 `limit-severities-for-sarif: true`，使 CRITICAL/HIGH 阈值与工作流注释一致。
- **验证**: 远程日志已确认 `.trivyignore` 被找到且 SARIF action 最终因全严重度结果返回 1；此修复后需复验多架构 Trivy 与 SBOM 门禁。

## [安全治理] - Worker bioinformatics 包例外

- **文件**: `.trivyignore`
- **决策**: Trivy Worker SARIF 在 API 已通过后暴露 `liblmdb0`, `tabix`, `libmbedx509`, `libcurl3t64-gnutls` 与 Python 系统包的无 fixed version CVE；这些包来自 Worker 必需的 ncbi-blast+/tabix/samtools/bedtools 工具链，加入同一可审计例外清单，固定版本发现仍保持阻断。
- **验证**: 两架构 Worker smoke（23 tasks）通过；API Trivy 已通过，Worker scan 收敛为 27 个无 fixed version CVE，待下一轮确认 MCP/JBrowse 扫描和 SBOM。

## [CI 修复] - JBrowse Alpine 系统包更新

- **文件**: `apps/jbrowse/Dockerfile`
- **决策**: JBrowse Trivy 暴露的是 Alpine runtime 中带 fixed version 的 `libssl3`, `libxml2`, `libpng`, `libexpat`, `zlib`, `nghttp2` 等漏洞；在 nginx runtime 阶段执行 `apk upgrade --no-cache`，不将可修复漏洞加入例外清单。
- **验证**: API、Worker、MCP 两架构 Trivy 已通过；JBrowse 构建与 nginx smoke 通过，待 Alpine 升级后的最终 scan 与 SBOM 验收。

## [CI 修复] - 压缩 runtime image artifact

- **文件**: `.github/workflows/ci.yml`
- **决策**: 两架构所有 build、smoke、Trivy、SPDX SBOM 均已通过；amd64 runner 在 `docker save` 写未压缩四镜像 tar 时磁盘耗尽。改为 `docker save | gzip -1` 生成 `.tar.gz`，Kind 与 publish 校验阶段用 `gzip -dc | docker load`，保留 SHA256 校验和与下游镜像 ID 证明。
- **验证**: arm64 本轮已通过到 SBOM/export 前；amd64 唯一失败为 `no space left on device` 的未压缩归档，压缩流修复后需重跑 Kind 与发布链路。

## [Kind smoke 修复] - Worker metrics 探测与 broker 兼容性

- **文件**: `.github/workflows/ci.yml`, `apps/worker/src/soymutdb_worker/metrics.py`, `apps/worker/tests/test_metrics.py`
- **决策**: Kind smoke 不再假设 Worker runtime 内有 curl，改用 Python 标准库读取 `/metrics`；同时 queue-depth collector 只对 `redis://`/`rediss://` 启动，`memory://` 等测试 broker 记录受控 warning，不在线程中抛出 Redis URL `ValueError`。
- **验证**: Docker 双架构 build、smoke、Trivy、SPDX SBOM 和压缩 artifact 均通过；Kind 已成功加载、部署并通过 API/Worker rollout，行为断言暴露 Prometheus multiprocess gauge 带 `{pid=...}` 标签，兼容可选标签后 Kind smoke 与 publish 均通过。

## [发布修复] - Cosign SLSA predicate 版本

- **文件**: `.github/workflows/ci.yml`
- **决策**: 双架构 Docker、Kind 和 Windows baseline 均已通过；GHCR publish 在 `cosign attest --type slsaprovenance` 阶段拒绝 SLSA v1 的 `runDetails.builder`，报 `required field builder missing`。改为 Cosign `slsaprovenance` 所需的 SLSA v0.2 predicate（顶层 `builder`, `buildType`, `invocation`, `materials`），保留来源 revision、workflow identity、平台和 provenance SHA256。
- **验证**: CI run `32841250150` 成功：前端/API/contract、双架构 Docker build/smoke/Trivy/SPDX、Kind smoke、GHCR 多架构 manifest、Cosign sign/attestation 与 OCI release contract 全部通过；baseline run `32841250085` 成功，Windows installer dry-run 与 Docker-free unit/liveness smoke 通过。

## [下一轮优化] - Dashboard 聚合查询与真实用户统计

- **文件**: `apps/api/app/api/v1/stats.py`, `apps/api/tests/test_stats_contract.py`
- **决策**: 公共 `/stats/dashboard` 原先把 `total_users` 固定为 0，且每次缓存刷新顺序执行五次独立 count 查询。改为一次 SQLAlchemy 查询承载五个 scalar subquery，并统计未软删除的真实用户。
- **验证**: 两个 Python 文件 `py_compile` 通过，新增回归覆盖真实用户数与单次聚合查询；完整 API pytest 需在依赖完整的 CI 环境验证。

## [文档同步] - 更新 CI/CD 最新远程证据

- **文件**: `docs/ci-cd-baseline.md`
- **决策**: 补充最新成功的 CI `32843469602` 与 baseline `32843469562` 链接和通过范围，同时明确它们不等同于真实生产服务器部署、审批或远程回滚验证。
