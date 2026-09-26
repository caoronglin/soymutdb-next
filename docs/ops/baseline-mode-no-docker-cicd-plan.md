# SoyMutDB 基础模式、无 Docker 部署与 CI/CD 方案

> 状态：仅方案设计，未实施。
> 对应 Goal：goal-515a511b-0c45-4832-9a3d-3f40a300d259

## 1. 目标与边界

先交付最小基础模式：公开 Web、Admin、FastAPI、PostgreSQL、登录/权限、公共查询、基础管理、发布读取、健康检查、迁移、备份、恢复、回滚，以及 Linux/Windows 无 Docker 运行方式。

基础拓扑：

    Browser -> Static Web/Admin -> /api/v1 -> FastAPI -> PostgreSQL

以下不进入基础部署：ClickHouse、MinIO/S3、Celery/beat/worker 集群、MCP、BLAST、GWAS、fastp、scanpy、Prometheus/Grafana、Cloudflare Tunnel、JBrowse 后端数据服务、高可用和多副本。它们以后作为独立 extended profile，不能隐式安装或阻塞 baseline。

## 2. 强制约束

1. 生产继续使用 PostgreSQL，不替换 SQLite。当前控制面依赖行锁、SKIP LOCKED、advisory lock、JSONB/UUID/INET、原生 enum 和 Alembic；SQLite 只能未来另建离线演示 profile。
2. 可选依赖必须 fail-closed。基础模式没有 Redis、ClickHouse、S3、Celery、MCP 时，API 仍可启动；能力返回 disabled/unavailable，不能接受无法结算的假任务。
3. FastAPI OpenAPI 是接口单一来源，生成并校验 packages/api-client，前端不得复制冲突 DTO。
4. 前后端版本可追踪：静态产物记录 commit、contract hash、deployment mode、build time；API capabilities 声明可用能力。
5. demo 与 production 分离：production 产物禁止 placeholder origin、demo 数据和未绑定 release。
6. Linux 使用 systemd；Windows 使用 WinSW（优先）或 NSSM；两端使用 Miniforge/venv + PostgreSQL 服务或托管 PostgreSQL。
7. 基础模式默认单 API 进程、单 PostgreSQL，不承诺分析并发和 HA。
8. 实施前保留当前未提交修改，分阶段审计、修改和验证，不覆盖用户工作。

## 3. 后端优化

### P0 启动、正确性、安全

- 增加 SOYMUTDB_DEPLOYMENT_MODE=baseline|extended 和 server-owned capability registry。
- readiness 拆成 mandatory/optional：PostgreSQL 是 mandatory；Redis、ClickHouse、S3、Celery 只返回诊断状态。
- 对可选服务使用惰性连接、有限超时和统一错误码 CAPABILITY_DISABLED、DEPENDENCY_UNAVAILABLE。
- 生产禁止 JWT、数据库、S3 的 dev 默认密码。
- 审计认证、refresh cookie、CSRF、CORS、JWT rotation、RBAC、审计日志、request-id、敏感字段脱敏。
- 检查写接口幂等、重复提交、状态机、权限、事务边界；基础模式关闭异步功能时不得创建不可结算任务。

### P1 性能、可靠性、可观测性

- 检查 PostgreSQL 的 N+1、分页、排序白名单、索引、慢查询、连接池和 statement timeout。
- 保留 pool pre-ping、连接池上限、Redis bounded timeout；Redis 不可用时直查 PostgreSQL。
- 限制基础模式请求体、并发和查询时间。
- 统一日志字段：timestamp、level、request_id、route、status、duration_ms、user_id、release_id、error_code。
- /health/live 只检查进程；/health/ready 只强制检查 PostgreSQL，同时返回可选依赖状态。
- 增加认证、公共查询、capabilities、migration、错误 envelope 的 baseline smoke 测试。

## 4. 后端与前端衔接

- 继续使用 packages/api-client/openapi.json、generate-api-client.sh、check-contract.sh 和 @soymutdb/api-client。
- CI 启动临时 API/PostgreSQL，导出 OpenAPI，阻断未审批的删除和破坏性接口变更。
- VITE_API_BASE_URL 是唯一 API 地址入口；未配置时使用相对 /api/v1。
- Web 和 Admin 共用 api-client，不复制 fetch、token、timeout 和错误解析。
- 首屏读取 GET /api/v1/capabilities；baseline 隐藏或置灰 BLAST、GWAS、分析、对象上传、MCP 和 ClickHouse 专属图表。
- disabled UI 显示未部署、未配置、依赖异常或权限不足。
- 构建 manifest 注入 commit、contract hash、deployment mode、build time。
- 联调覆盖 CORS、cookie、代理 prefix、401 refresh、403、404、409、422、503。

## 5. Linux 无 Docker

### 组件和目录

Ubuntu 22.04/24.04 或 RHEL 系；Node 24、pnpm 11、Python 3.13/3.14、PostgreSQL 16+；Miniforge 或系统 Python venv；systemd 服务 soymutdb-api.service；Web/Admin 用 GitHub Pages、nginx 或其他静态服务器。

    /opt/soymutdb/releases/<version>/
    /etc/soymutdb/.env
    /var/lib/soymutdb/backups/
    /var/log/soymutdb/

### 流程

1. 安装系统、Node/pnpm、Python、PostgreSQL。
2. 创建专用用户、目录和权限。
3. frozen install，创建 API venv，安装 Python 依赖。
4. 校验生产 env，执行 alembic upgrade head。
5. 构建 Web/Admin，注入真实 API origin。
6. 安装 systemd unit，设置 EnvironmentFile、Restart、NoNewPrivileges、资源限制。
7. 执行 liveness、readiness、baseline smoke。
8. 升级采用 release directory + symlink；新版本迁移、启动、探活成功后切换。

每次升级前备份 PostgreSQL、migration head、版本和 env 元数据。迁移使用 expand/contract；不自动回滚已执行的破坏性 migration。backup.sh、restore.sh、verify-restore.sh 必须做恢复演练。no-Docker 提示必须用 systemctl/journalctl，不得依赖 docker compose logs。

## 6. Windows 无 Docker

Windows Server 2022 或 Windows 11 Pro；Node 24、pnpm 11、Python 3.13/3.14、PostgreSQL Windows service 或托管 PostgreSQL、WinSW/NSSM、IIS 或 GitHub Pages。

    C:\ProgramData\SoyMutDB\config\.env
    C:\ProgramData\SoyMutDB\releases\<version>\
    C:\ProgramData\SoyMutDB\backups\
    C:\ProgramData\SoyMutDB\logs\

服务名为 SoyMutDB-API，默认监听 127.0.0.1:8010，由 IIS URL Rewrite/ARR 或安全网关对外暴露。

提供纯 PowerShell 安装、校验、迁移、健康检查、备份、升级、回滚和卸载脚本；使用 Get-Service、Start-Service、Invoke-WebRequest，不要求 Git Bash。WinSW 优先，配置 stdout/stderr、自动重启和停止超时。CI 验证路径、权限、编码、换行和服务停止行为。

## 7. 已确认缺口和缺陷分级

### P0

- readiness 当前强制检查 ClickHouse/Redis，与 baseline 冲突。
- 生产配置仍有 dev 数据库、ClickHouse、S3/MinIO 默认值风险。
- 认证、CORS、CSRF、cookie、RBAC 需要生产闭环审计。
- optional disabled 时必须不能创建不可结算任务。

### P1

- 已有 Linux 安装/systemd 脚本，但没有 deploy/windows 实现。
- deploy/linux/install.sh 仍提示 docker compose logs，与无 Docker 路径矛盾。
- 现有 CI 有前端/API/Docker/E2E job，但缺 baseline no-Docker 第一门禁和 Windows 原生安装验证。
- OpenAPI/api-client 已存在，但需把 capabilities、deployment mode、optional dependency semantics 纳入契约测试。
- nginx 可能仍包含已移出 Compose 的前端 upstream，需要统一 Pages/静态服务器与 API 反代方案。
- 当前工作树有大量未提交修改，必须先做基线快照。

### P2

可选工具文档、监控 dashboard、扩展性能优化和 UI 辅助提示。

## 8. GitHub Actions CI/CD

### PR CI 硬门禁

在现有 .github/workflows/ci.yml 基础上收敛为：

1. frontend-baseline：frozen install、Web/Admin build、lint、typecheck、Vitest、bundle budget、placeholder scan。
2. api-baseline：Python 3.13/3.14 matrix、ruff、mypy、pytest，使用 PostgreSQL service，不依赖应用 Docker 镜像。
3. contract：临时 API 导出 OpenAPI、contract check、api-client tests。
4. integration-baseline：migration、health、认证、公共查询、Admin 权限 smoke。
5. windows-baseline：windows-latest 安装 Node/Python/pnpm，运行 PowerShell installer dry-run、env validation、Uvicorn 和 smoke。
6. security：pip-audit/uv audit、pnpm audit、gitleaks、锁文件/许可证检查、CodeQL。
7. ci-summary：汇总 required checks；任一硬门禁失败即阻断。

### main 验证型发布

新增 release-baseline.yml：main push、tag、workflow_dispatch 触发；构建 Web/Admin production artifact、API sdist/wheel、Linux/Windows no-Docker bundle；在 Ubuntu 和 Windows runner 分别验证 PostgreSQL、migration、API 和 smoke；上传部署脚本、SBOM、SHA256SUMS、测试报告；默认只发布 GitHub Release/Actions artifact，不自动碰生产服务器。

### Staging 和 Production

新增 deploy-staging-baseline.yml 和 deploy-production-baseline.yml。staging 使用受保护 environment，可用 Linux SSH 或 Windows WinRM/self-hosted runner；部署前备份，迁移后探活和 smoke，失败恢复应用版本。production 仅 semver tag + protected environment，使用 OIDC/短期凭据，执行 preflight -> backup -> migration gate -> deploy -> smoke -> rollback gate，默认人工审批。

所有 action 固定 commit SHA；job 使用最小 permissions；PR 不使用 production secrets；禁止 pull_request_target 执行不可信 PR；发布生成 commit、artifact hash、contract hash、migration head、runner、时间的 manifest。

## 9. 验收标准

- 无 Redis/ClickHouse/MinIO/Celery 仍可启动 baseline API 并通过 readiness。
- PostgreSQL migration 可重复执行；认证、权限、公共查询、错误 envelope、request_id、CORS/CSRF 通过。
- Web/Admin 只使用同一 api-client，能读取 capabilities，产物无 placeholder，401/403/409/422/503 行为可测。
- 全新 Ubuntu 无 Docker 安装、systemd 启动重启、日志、升级、回滚和恢复演练通过。
- 全新 Windows 无 Docker 安装、PowerShell、WinSW/NSSM、日志、重启、升级、回滚和 smoke 通过。
- PR required checks 无假绿；main bundle 可在两端重放；staging/production 有审批、回滚和发布证明。

## 10. 实施 Wave

- Wave 0：基线快照、现有 diff/CI/OpenAPI/部署脚本审计、baseline 文档、缺陷账本、验收矩阵。
- Wave 1：deployment mode/capability、mandatory/optional readiness、可选依赖惰性连接、P0 修复。
- Wave 2：OpenAPI/api-client、capabilities、manifest、错误 envelope、401/403/409/422/503 和 baseline UI 门控。
- Wave 3：Linux no-Docker 安装、升级、备份、恢复、health、systemd hardening、clean-host CI。
- Wave 4：Windows PowerShell、WinSW/NSSM、IIS/静态托管、升级回滚、Windows CI。
- Wave 5：baseline CI、release bundle、staging、production protected workflows、迁移/回放/安全门禁。
- Wave 6：双平台安装回滚、API/前端/E2E 联调、缺陷归零或正式豁免、生产就绪文档。

## 11. 当前实施状态（本轮）

- 已实现：`SOYMUTDB_DEPLOYMENT_MODE=baseline|extended`、生产配置按模式 fail-fast、baseline/extended readiness 语义和 Docker-free unit tests。
- 已实现：Linux 原生 release + venv + systemd API 安装、baseline health/backup/restore/upgrade/rollback 脚本；不安装或启动 Docker/Compose。
- 已实现：Windows PowerShell + WinSW/NSSM 路径、API 入口/venv/migration 修正、dry-run/health/backup/upgrade/rollback 文档。
- 已实现：独立 `baseline-validation.yml`，Ubuntu PostgreSQL、Windows 原生 dry-run/liveness、OpenAPI client contract、artifact/SBOM/SHA256/manifest 和 protected staging/production dry-run gate。
- 待验证：GitHub Actions 实际 run、Windows PowerShell parser/service、Ubuntu clean-host systemd/migration/backup/restore/rollback、受保护环境 OIDC/远程 target adapter。
- 待后续 Wave 2：完整 OpenAPI capability schema 与前端实际 capability gating；本轮只接入已有 contract check，不改动并行中的 Web/Admin 重构文件。

本轮不执行 git reset/clean/stash，不覆盖并行前端重构变更；实际验收以 `docs/ops/baseline-acceptance-matrix.md` 和 `docs/ops/baseline-defect-ledger.md` 的证据状态为准。