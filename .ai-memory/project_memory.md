# Project Memory

## Decision Record: 生产控制面保留 PostgreSQL

**日期**: 2026-08-19
**问题**: PostgreSQL 是否可由 SQLite 替代。

### 选项分析

| 选项 | 优势 | 劣势 | 复杂度 |
| --- | --- | --- | --- |
| 保留 PostgreSQL | 保留行锁、`SKIP LOCKED`、advisory lock、PG 类型、迁移与现有灾备 | 需要独立数据库运维 | 低 |
| 增加 SQLite 轻量 profile | 单机演示部署简单 | 必须单进程并禁用或重写 outbox、发布、导入及并发任务；另建 schema/测试 | 中高 |
| 全面替换 SQLite | 单文件存储 | 重写并发协议、迁移、类型、容器、监控和灾备，无法维持当前多 writer 拓扑 | 高 |

### 决策

**选择**: 生产与完整开发栈继续使用 PostgreSQL；只有明确需要离线单机演示时，才评估独立、功能受限的 SQLite profile。
**理由**: 当前 API/Worker 依赖 PostgreSQL 行锁、`FOR UPDATE SKIP LOCKED`、session advisory lock、JSONB/UUID/INET、原生 enum 和 PostgreSQL Alembic 链；生产同时运行多 API worker 与多个 Celery writer。
**Trade-offs**: 接受 PostgreSQL 的部署和备份运维成本；若目标只是降低运维，优先采用托管 PostgreSQL，而不是更换数据库语义。

### 影响范围

- `apps/api` 数据模型、事务、迁移和 outbox。
- `apps/worker` 导入锁与数据库驱动。
- `docker-compose.yml`、`deploy/scripts`、监控及灾备流程。

### 撤销条件

产品明确收缩为单机、单用户、单写进程，且不需要 Celery 并发、发布/回滚、outbox、导入互斥或生产高可用；同时 SQLite schema、并发反例、备份恢复和完整声明功能集均通过独立验证。

## Project Convention: 生物信息学数据库核心与身份边界

**类型**: 架构约束 / 命名规范 / 测试规范
**适用范围**: 突变体、基因、变异、搜索、数据发布，以及 external/internal 站点

### 规范内容

- SoyMutDB 的主产品形态是可检索、可追溯且版本明确的生物信息学数据库；内容页面不能取代标识符搜索、结果列表和实体详情。
- 突变体的稳定公开身份使用 `public_id`；数据库私有身份使用 `internal_id` 语义。外部契约不得暴露或接受内部身份，内部搜索两种 ID 必须由服务端授权。
- v4/v5 是不同 assembly 命名空间；基因、变异、坐标和跨版本映射必须显式绑定 assembly。跨版本等价关系只能来自带 provenance 的 crosswalk/alias 数据。
- external/internal 是独立构建和部署边界。缓存必须至少按 site variant、release、assembly、query 和 filters 隔离。
- 上述变更按 `docs/dev/database-core-contract.md` 的 P0/P1 矩阵执行；隐私、身份和 assembly 隔离的 P0 测试不得 skip/xfail。

### 示例

**正确**:
`external mutant URL -> public_id; authorized internal search -> public_id or internal_id; gene hit -> assembly + release`

**错误**:
`external mutant URL -> numeric database id; v4/v5 hits silently collapsed; cache key -> query only`

### 发现来源

2026-09-06 用户确认的项目核心功能与双版本需求；落地文件为 `AGENTS.md` 和 `docs/dev/database-core-contract.md`。

## Implementation Record: 公开搜索 fail-closed 基线

**日期**: 2026-09-06
**状态**: 部分实现，不能替代双 ID 迁移

- 未认证的 SoyMutDB 全局 JSON 搜索固定使用 `external` 上下文；缓存参数包含 site variant、release、assembly、query、types 和 cursor/limit。
- 基因命中只来自 active published release，并按明确 assembly 进一步过滤；结果携带 release/assembly ID，前端链接保留 assembly 查询参数。
- 现有 `MutantLine` 尚无 `public_id`，因此公开全局搜索暂不返回突变体命中，避免把数值主键包装成公开身份。内部突变体查询分支虽有 release/public/deleted 过滤，但只能由未来的服务端鉴权 internal 路由接入。
- `scripts/check_site_artifact_isolation.py` 递归扫描 external 制品中的调用方哨兵，拒绝重叠根目录与符号链接，并对诊断路径脱敏；其标准库测试入口为 `python3 -m unittest scripts.test_site_artifact_isolation -v`。

## Glossary Entry: public_id

**规范名称**: `public_id`
**别名/变体**: 对外 ID、公开 ID、public ID
**定义**: 面向研究者、URL、导出和引用的稳定公开编号，不随持久化主键变化。
**适用范围**: 突变体公开 API、搜索、页面、下载和发布制品
**禁止使用**: 用裸 `id` 指代公开身份；由 `internal_id` 推导公开编号
**来源**: 2026-09-06 用户需求与 `docs/dev/database-core-contract.md`

## Glossary Entry: internal_id

**规范名称**: `internal_id`
**别名/变体**: 对内 ID、内部 ID、数据库 ID、persistence key
**定义**: 仅供内部关联、运营和审计使用的持久化身份；现有存储字段可以名为 `id`，但对外不得暴露。
**适用范围**: PostgreSQL 关系、授权后的内部 API/搜索和审计
**禁止使用**: public ID；匿名查询键；external URL 或静态制品字段
**来源**: 2026-09-06 用户需求与 `docs/dev/database-core-contract.md`

## Glossary Entry: assembly

**规范名称**: assembly
**别名/变体**: 基因版本、基因组版本、v4、v5
**定义**: 一套明确的参考基因组与注释坐标/标识符命名空间；它与数据 release 是独立维度。
**适用范围**: 基因、转录本、变异、坐标、序列、JBrowse 和搜索缓存
**禁止使用**: 用 release 代替 assembly；静默混合 v4/v5
**来源**: 2026-09-06 用户需求与现有 `Assembly` 模型

## Glossary Entry: site variant

**规范名称**: site variant
**别名/变体**: 站点版本、对外版、对内版、external/internal site
**定义**: 只允许 external/internal 的显式构建与部署安全边界，不是搜索数据来源。
**适用范围**: Web 制品、origin、API 授权、CORS、缓存和 Service Worker
**禁止使用**: federated search source；按 host/IP/cookie/user-agent 推断的访客分类
**来源**: 2026-09-06 用户需求与现有 `SiteVariant` 契约


## Delivery Architecture: CNB 主链路 + GitHub 镜像

**日期**: 2026-09-11
**状态**: IMPLEMENTED_UNVERIFIED（CNB 真实构建待平台触发）

### 决策

交付链路改为 **`.cnb.yml` 为单一事实来源**，GitHub Actions 保留为镜像。关键不是
"翻译 YAML"，而是先把构建/测试/扫描/签名逻辑从 YAML 里抽成脚本，再让两个
provider 引用同一批脚本。

### 理由

- 原 `ci.yml` 有 1189 行内联逻辑；迁移到 CNB 若重写一份，之后必然双向漂移。
- 内联逻辑无法本地复现，任何失败只能推远端等 CI。
- 抽成脚本后 GitHub 侧可先回归验证，等价性可证，而非凭信心重写。

### 落地文件

- `.cnb.yml`、`.cnb/pipelines/*`、`.cnb/web_trigger.yml`、`.cnb/env/*`
- `scripts/ci-job-steps.sh`、`verify-frontend-artifacts.sh`、`verify-backend-tests.sh`、
  `build-release-image.sh`、`release-contract.golden.sh`、`build-pages-artifact.sh`、
  `verify-pages-artifact.sh`、`mcp-transport-smoke.sh`、`smoke.sh`
- `scripts/test_ci_job_contracts.py`（18 用例，防逻辑回流 YAML）

### 不可违反的规则

1. **逻辑不得内联回 workflow/流水线**：契约测试会失败。
2. **镜像校验与发布分离**：校验 pipeline 无 registry 凭据且不 push；发布 pipeline
   不做 `docker build`。发出去的字节必然等于验过的字节。
3. **PR 事件不得持有发布凭据**：CNB 的 PR `CNB_TOKEN` 权限受限。
4. **冒烟不得伪通过**：前置条件缺失必须 `SKIPPED` + 原因，且不计入通过数。
5. **工具链固定一致**：Node 24.19.0 / pnpm 11.21.0 / Python 3.14 / uv 0.11.33。

### 有意保留在 GitHub

Kind/Kubernetes 运行时冒烟（依赖嵌套 docker 与 `helm/kind-action`）、Windows 安装器
dry-run、受保护环境 staging/production dry-run、CycloneDX baseline SBOM。这些
workflow 顶部均有 MIRROR NOTICE。

### 验证证据（2026-09-11 本机）

- `scripts/test_ci_job_contracts.py` → 18 passed
- `bash scripts/smoke.sh --profile contracts` → 134 passed，SMOKE PASS
- CNB 校验器（YAML + 语义 + Schema）→ 三项通过
- `pnpm install --frozen-lockfile` + `pnpm build:web` → 成功；`--profile static` PASS
- 一次性 PostgreSQL 15（55432）+ Python 3.14：
  migrations 0035 全链 → live ok → ready postgres healthy → `/search` 503 空库
  fail-closed → `--profile runtime` PASS
- 后端回归对照：改动前后同为 **33 failed / 1445 passed**，零影响

### 未验证

CNB 真实构建、Docker 镜像构建/Trivy/SBOM（本机无 daemon）、Playwright E2E、ClickHouse 迁移。

### 撤销条件

若 CNB 平台不可用或团队决定回落 GitHub-only：`git revert` 本次提交即可；所有 GitHub
workflow 保留完整可用路径，未删除任何 job。
