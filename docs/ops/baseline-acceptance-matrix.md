# SoyMutDB 基础模式验收矩阵

> Wave 0 基线。每项必须有命令、日志或 artifact 证据；代码存在不等于验收通过。

## A. API 与数据库

| ID | 场景 | 环境 | 通过条件 | 证据 |
|---|---|---|---|---|
| A-01 | API import/start | Linux + Windows | 无可选服务时 API 能启动 | 待 Wave 1 |
| A-02 | liveness | Linux + Windows | /api/v1/health/live 返回 200 | 待 Wave 1 |
| A-03 | readiness baseline | Linux + Windows | 仅 PostgreSQL 可用时 /api/v1/health/ready 返回 200 | 本地 Docker-free unit + baseline health semantics verified；GitHub/双平台仍待 run |
| A-04 | optional dependency degraded | Linux + Windows | Redis/ClickHouse/S3/Celery 缺失只改变 capabilities/diagnostics，不阻断 baseline | test_health_unit.py baseline/extended cases；28 tests passed |
| A-05 | migration idempotency | PostgreSQL 16+ | Alembic upgrade head 重复执行无变化、无错误 | 待 Wave 3/4 |
| A-06 | auth/RBAC | Linux + Windows | 登录、refresh、退出、未授权、无权限、审计日志均通过 | 待 Wave 1/2 |
| A-07 | error contract | Linux + Windows | 4xx/5xx 均含稳定 code/message/request_id | 待 Wave 1/2 |
| A-08 | query baseline | PostgreSQL | 分页、排序白名单、超时和核心索引通过基准阈值 | 待 Wave 1 |

## B. 前后端契约

| ID | 场景 | 通过条件 | 证据 |
|---|---|---|---|
| B-01 | OpenAPI export | 从当前 API 生成的文档可重现 | 待 Wave 2 |
| B-02 | breaking diff | 删除/破坏性变更阻断；兼容新增有记录 | 待 Wave 2 |
| B-03 | shared client | Web/Admin 只经 @soymutdb/api-client 请求 | 待 Wave 2 |
| B-04 | capabilities | baseline UI 不展示 disabled optional capability | 待 Wave 2 |
| B-05 | API origin | production artifact 不含 placeholder，VITE_API_BASE_URL 可验证 | 待 Wave 2/5 |
| B-06 | auth errors | 401 refresh、403、409、422、503 有可测试 UI 行为 | 待 Wave 2 |

## C. Linux 无 Docker

| ID | 场景 | 通过条件 | 证据 |
|---|---|---|---|
| C-01 | clean install | 全新 Ubuntu，无 Docker，安装脚本完成 | 待 Wave 3 |
| C-02 | systemd | 渲染 unit 后 systemd-analyze verify 通过；service start/restart/status/journal 可用 | 待 Wave 3 |
| C-03 | upgrade | 新 release 安装、迁移、探活、切换成功 | 待 Wave 3 |
| C-04 | rollback | 应用失败恢复旧 release；不误回滚不兼容 migration | 待 Wave 3 |
| C-05 | restore | PostgreSQL 备份可恢复并通过 smoke | 待 Wave 3 |

## D. Windows 无 Docker

| ID | 场景 | 通过条件 | 证据 |
|---|---|---|---|
| D-01 | clean install | 全新 Windows，无 Docker，PowerShell 安装完成 | 待 Wave 4 |
| D-02 | service | WinSW/NSSM 安装、启动、停止、自动重启、日志可用 | 待 Wave 4 |
| D-03 | upgrade | release directory 切换和 migration gate 通过 | 待 Wave 4 |
| D-04 | rollback | 服务可恢复旧 release，配置和日志不丢失 | 待 Wave 4 |
| D-05 | IIS/static | API 反代、静态 fallback、超时和健康检查通过 | 待 Wave 4 |

## E. GitHub Actions

| ID | 场景 | 通过条件 | 证据 |
|---|---|---|---|
| E-01 | PR frontend | build/lint/typecheck/test/contract hard gate | 待 Wave 5 |
| E-02 | PR API | Python matrix、pytest、Ruff/mypy、安全扫描 hard gate | 待 Wave 5 |
| E-03 | PR Windows | windows-latest 原生安装 dry-run + API smoke | baseline-validation.yml 已定义 parser/dry-run/liveness；待 GitHub runner |
| E-04 | release bundle | Web/Admin、API wheel、双平台脚本、SBOM、SHA256SUMS 可下载 | baseline-validation.yml 已定义 artifact/SBOM/SHA256/manifest；待 GitHub run |
| E-05 | artifact replay | bundle 能在 Linux/Windows 重放安装和 smoke | 待 Wave 5/6 |
| E-06 | staging gate | protected environment、备份、迁移、health、smoke、失败恢复 | 待 Wave 5/6 |
| E-07 | production gate | semver tag、人工审批、OIDC/短期凭据、manifest、rollback gate | 待 Wave 5/6 |

## 证据规则

1. 每项证据至少包括 commit、环境、命令、退出码和报告路径。
2. 失败测试不得用 continue-on-error 隐藏；非阻断项必须在缺陷账本登记。
3. PR 只验证 baseline；extended/Docker/大型数据任务放在独立 workflow。
4. 生产发布前必须保存 migration head、artifact hash、contract hash 和备份标识。
