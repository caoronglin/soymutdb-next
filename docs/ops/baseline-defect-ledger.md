# SoyMutDB 基础模式缺陷账本

> **已归档（2026-10-01）**：一次性的基础模式验收战役记录（操作手册仍在 ops/）。继任：`docs/ops/README.md` 及其下的现行运维手册；部署事实见 `docs/dev/project-status.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> Wave 0 审计记录；只记录当前证据，不代表问题已经修复。
> 审计目标：baseline = FastAPI + PostgreSQL + Web/Admin，且不依赖 Docker、Redis、ClickHouse、S3 或 Celery。

## P0：必须先修复

| ID | 问题 | 当前证据 | 影响 | 修复验收 | 状态 |
|---|---|---|---|---|---|
| B-001 | readiness 将可选依赖当成必选依赖 | apps/api/app/api/v1/health.py baseline 分支已只检查 PostgreSQL；extended 保留可选依赖门禁 | 原问题已修复 | test_health_unit.py 覆盖 baseline disabled 和 extended 503；28 个配置/单元测试通过 | verified |
| B-002 | 生产配置存在开发默认凭据/地址 | 配置仍保留开发便利默认值，但 apps/api/app/core/config.py 按 deployment_mode 选择 mandatory fields，并拒绝生产 placeholder/弱凭据 | 误部署可能使用弱凭据或错误依赖 | test_config_security.py 覆盖默认基础设施、弱密码、无效邮箱、baseline optional omission；28 个测试通过 | verified |
| B-003 | 可选异步能力的关闭语义未形成统一门禁 | 方案要求关闭 Celery/S3/ClickHouse 时不能创建假任务；需要逐路由审计 | 用户得到任务 ID 但没有 worker 结算 | 所有 optional 写入口返回统一 CAPABILITY_DISABLED/DEPENDENCY_UNAVAILABLE，并有 API 测试 | open |
| B-004 | 认证、CORS、CSRF、cookie 和 RBAC 尚未完成 baseline 生产闭环证据 | 现有实现分散于 auth/config/middleware；当前没有 baseline 跨平台 smoke 证据 | 生产安全门禁不可证明 | 增加正反向安全测试、生产配置矩阵和 smoke 报告 | open |

## P1：基础模式上线前必须完成

| ID | 问题 | 当前证据 | 影响 | 修复验收 | 状态 |
|---|---|---|---|---|---|
| B-101 | Windows 无 Docker 部署实现缺失 | deploy/windows/ 已新增 common/install/health/service/backup/upgrade/rollback/README | Windows 实机能力仍未验证 | Windows workflow 已加入 PowerShell parser、installer dry-run 和 API liveness；待 GitHub runner | in_progress |
| B-102 | Linux 安装提示与无 Docker 路径矛盾 | deploy/linux/install.sh 已重写为原生 API + PostgreSQL；systemd/journalctl 提示；baseline-*.sh 已新增 | 旧 extended 脚本仍保留供 extended 使用 | bash -n、install/health/backup/upgrade dry-run 通过 | verified |
| B-103 | CI 缺少 Windows 原生 baseline 验证 | .github/workflows/baseline-validation.yml 已新增 api-windows-baseline | GitHub Windows runner 尚未执行 | workflow 包含 parser、dry-run、unit test、liveness smoke；待远程运行证据 | in_progress |
| B-104 | 现有 CI 重点包含 Docker/extended 验证，baseline 门禁未独立 | 新增独立 .github/workflows/baseline-validation.yml，未修改现有 workflow | GitHub required-check 配置尚未设置 | YAML 解析通过、23 个 action 引用均为 40 位 SHA；待 GitHub run 和 branch protection 配置 | in_progress |
| B-105 | OpenAPI/client 契约缺少 deployment mode 和 optional capability 约束 | 当前 OpenAPI/client 已重新生成并与 schema 字节级同步；capabilities 仍有手写类型，且 20 条历史 route debt 仍 allowlisted | 前端可能展示未部署能力 | 已加入 contract hard gate；后续补 capabilities schema、deployment mode 字段和 route debt 清理 | in_progress |
| B-106 | Windows 服务、IIS/静态托管和回滚文档缺失 | deploy/windows/README.md 和 7 个 PowerShell 脚本已新增；入口修正为 apps/api + app.main:app | Windows 实机和 IIS 尚未验证 | 文档和脚本静态检查通过；待 Windows runner/staging | in_progress |
| B-107 | nginx 与 Pages 拆分后的最终拓扑需要确认 | infra/nginx/conf.d/default.conf 仍包含前端 upstream/代理规则；部署文档要求前端移出 Compose | 可能引用不存在的 upstream | 选择 Pages 或本机静态站点之一，并用 nginx config test 验证 | open |
| B-108 | 工作树存在大量未提交变更 | 当前 main 相对 origin/main 有约 71 个变更文件，包含 API/UI/Compose/nginx/CI 和大量未跟踪文档 | 直接实施可能覆盖用户修改或混淆基线 | 每个 Wave 记录 diff，不重置、不清理，变更分批验证 | tracked |

## P2：后续增强

- 可选工具的安装包和监控 dashboard。
- Redis cache-aside 的性能基准和容量建议。
- extended profile 的 ClickHouse/MinIO/Celery/MCP 验收。
- 多副本、蓝绿和高可用生产演练。

## 状态定义

- open：已确认，尚未修复。
- in_progress：已开始实现，尚未完成验证。
- verified：实现和验收证据均已保存。
- accepted-risk：明确记录豁免理由和到期复查时间。
