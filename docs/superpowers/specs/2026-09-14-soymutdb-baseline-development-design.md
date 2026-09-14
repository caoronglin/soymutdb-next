# SoyMutDB 基线开发五阶段设计规格（冻结）

- 状态：frozen（签发起生效），2026-09-14
- 适用范围：`apps/web`、`apps/admin`、`apps/api`、`apps/worker`、`packages/api-client`、`packages/jobs-py`、`scripts/`、`deploy/`、`infra/`、`.cnb.yml` 及其镜像的 GitHub workflow
- 依据：`AGENTS.md`、`docs/dev/database-core-contract.md`、`docs/dev/deployment-status.md`、`docs/ops/ci-cd.md`、`docs/ops/cnb-startup-acceptance.md`、`docs/dev/database-execution-status.md`、`docs/dev/database-execution-handoff.md`
- 效力：本规格冻结 P0–P4 的范围、顺序、隔离不变量与 PASS 判定。任何阶段缩小验收、放宽隔离、绕过 P0 门禁或修改 PASS 定义的改动，必须修订本文件并重新评审；不得在实现 PR 里口头放宽。
- 用途：把当前"脚本/配置已写、平台未实跑"的基线，推进为在真实 Docker、真实 API、真实浏览器、真实 PostgreSQL/ClickHouse/MinIO 上可判定的交付。

## 1. 不可变前提（任何阶段不得违反）

### 1.1 数据权威边界

| 组件 | 角色 | 强制约束 |
| --- | --- | --- |
| PostgreSQL | 权威存储 | 身份、关系、release、assembly、权限、工作流状态、审计只以 PostgreSQL 为准。不得引入第二权威存储，不得把 SQLite 用于生产/完整开发路径。 |
| ClickHouse | 分析投影 | 只承载批量变异事实；可重建；不签发公开身份、不决定可见性。投影缺失时对应能力必须显式不可用。 |
| MinIO | 对象存储 | 源文件、诊断报告、导出、静态产物对象；对象默认私有，匿名公开 GET 必须被拒。 |
| Redis | 可丢弃状态 | 只作缓存与 Celery broker/result；任何 Redis 数据丢失后系统必须能从 PostgreSQL/对象存储重建。 |

### 1.2 隔离不变量

1. `external` 与 `internal` 是构建与部署安全边界，只能显式选择；禁止依据 host、IP、cookie、user agent 推断。制品、origin、CORS allowlist、缓存、Service Worker 命名空间必须分离。
2. `public_id` 与 `internal_id` 严格分离：`public_id` 用于公开 URL/响应/下载/引用，稳定且唯一；`internal_id` 仅供内部授权与审计。公开边界不得出现或接受 `internal_id`；不得从任一 ID 推导另一 ID。
3. v4 与 v5 是独立坐标/标识命名空间。基因查找键至少为 `(assembly, accession)`；未指定 assembly 的查询必须按 assembly 分组或返回可判定的歧义错误，不得静默选默认版本。
4. v4↔v5 对应关系只能来自带 provenance 的显式 crosswalk；禁止按名称相似或坐标接近推断等价。
5. 公开搜索缓存键必须包含 site variant、release、assembly、实体类型、query、filters、分页/cursor；internal 结果使用私有缓存，且不得被 external 请求命中。

### 1.3 明确排除

- 排除 Portable/Tauri 桌面端、`apps/core-rs`、Windows 打包链及其 IPC 契约。Admin 仅 Web。
- 排除营销、编辑、CMS 扩张类工作；首页与内容模块只有在服务数据库检索、实体详情与 provenance 展示时才算在范围内。
- 排除联邦搜索来源（NCBI/UniProt/Ensembl/EBI）的语义合并；它们与 site variant 是两个维度，本规格不把 federated source 当站点边界。

## 2. 状态语义与 PASS 判定

沿用 `deployment-status.md` 的状态取值，并额外固定升级规则：

| 状态 | 含义 |
| --- | --- |
| NOT_STARTED | 无实现。 |
| IN_PROGRESS | 实现进行中。 |
| IMPLEMENTED_UNVERIFIED | 代码/配置存在，但只在单元测试、静态契约、节点级仿真或代码审阅层面成立。 |
| BLOCKED_ENVIRONMENT | 所需真实底座（Docker daemon、真实 PostgreSQL、真实 ClickHouse、真实 MinIO、真实浏览器、CNB 平台）缺失；必须记录缺失项与解除条件。 |
| FAILED | 真实运行失败。 |
| VERIFIED（PASS） | 在阶段要求的真实底座上运行并留存命令、计数、制品摘要与日志。 |

**升级规则（冻结）**：

1. 静态契约测试、`docker compose config` 之外的节点级插值仿真、`sh -n`、代码审阅、单元测试，均不得把能力从 IMPLEMENTED_UNVERIFIED 升级为 PASS。
2. 只有真实 Docker 启动、真实 API 进程、真实浏览器端到端，才构成对应阶段的 PASS 证据。缺一即 BLOCKED_ENVIRONMENT。
3. 任何 P0 场景不得以 skip/xfail 绕过；跳过即阻断，不得在交付说明中改写为通过。
4. 当前状态定性：`docker-compose.preview.yml` 的 data-only 预览拓扑、`start-cloud-dev.sh` 的数据层拉起、`.cnb.yml` 的 preview 编排目前是 **IMPLEMENTED_UNVERIFIED**。证据来自 `scripts/test_development_compose_contract.py` 的节点级静态断言（含“preview 只加载 `docker-compose.preview.yml`、绝不加载生产 `docker-compose.yml`”的断言），以及未在 CNB 平台实跑的脚本自检；必须由 P0 的真实 CNB 启动与真实数据层 Up 推翻或确认。同理，`apps/web` 双站制品与 CH 503 修复在完成真实 release 数据 + Docker/CH 之前均保持 IMPLEMENTED_UNVERIFIED。

仅当某阶段的"真实验收"逐条满足并留证，该阶段才可标记 PASS；未满足的条目以 BLOCKED 原因与解除条件显式记录，本规格不保留无判定标准的占位项。

## 3. 五阶段总览与依赖

| 阶段 | 名称 | 核心断言 | 依赖 | 允许的 PASS 底座 |
| --- | --- | --- | --- | --- |
| P0 | CNB Preview / 数据层真实启动 | 在 CNB 平台上一键起环境，8686 预览可达，postgres/clickhouse/redis/minio 真实 Up，API 读到真实 PG | 无 | CNB `vscode` 或 `workspace-preview` 事件 + Docker dind |
| P1 | external Release/Assembly 发布隔离 | 发布只切换 `active_release`，external 制品只含已发布公开数据，双站制品/缓存/Service Worker 分离 | P0 | 真实 Docker 生产拓扑或 CNB `publish` 流水线 + 真实 PostgreSQL |
| P2 | Variant assembly/release 上下文 | 变异查询显式绑定 release+assembly，CH 不可用统一 503，前端标签与 JBrowse 一致 | P0、P1 | 真实 ClickHouse 投影 + PostgreSQL + 真实 API |
| P3 | genes assembly 绑定、全局搜索与 provenance 展示 | `(assembly, accession)` 唯一、无版本歧义显式、cross-version 仅来自 crosswalk、全链路上下文不漂移 | P1、P2 | 真实 PostgreSQL + 真实 API + 真实浏览器 |
| P4 | Admin Import Studio 上传到提交闭环 | 上传→服务端 inspection→DatasetVersion→ImportDraft→validate→显式 commit→DataSet ready→发布请求 | P0、P1 | 真实 Docker/API/浏览器 + 真实 MinIO + 真实 PostgreSQL |

顺序冻结：P0 是所有阶段的准入；P1 完成前不得对外启用 P2/P3 的生物数据读取；P3 的 cross-version 展示必须在 P2 的 release/assembly 上下文稳定之后；P4 的 commit 结果必须消费 P1 的发布路径，不得自建第二套发布。

## 4. P0：CNB Preview / 数据层真实启动

### 4.1 目标

在 CNB 平台上，用既有 `vscode`（分支页「启动 SoyMutDB 开发环境」）与 `web_trigger_workspace-preview` 两条入口，得到一个真实可用的开发环境：门户预览在 8686 可达，postgres/clickhouse/redis/minio 容器真实运行，API 能解析到真实 PostgreSQL 并返回可判定响应。禁止以"脚本语法正确"或"静态契约通过"替代。预览数据层只加载 data-only 的 `docker-compose.preview.yml`；CNB preview 命令绝不加载生产 `docker-compose.yml`，也绝不加载 `docker-compose.yml` + `docker-compose.dev.yml`。

### 4.2 组件

- `.cnb.yml`：`vscode` 流水线声明 `services: [docker, vscode]`、`options.onlyPreview`、`SOYMUTDB_DEV_WEB_PORT=8686`；`web_trigger_workspace-preview` 复用同一脚本与模式。
- `.cnb/settings.yml`：按钮文案与 `cpus: 4`。
- `scripts/start-cloud-dev.sh`：`full` / `preview` / `api-preview` 模式，解析 `CNB_VSCODE_PROXY_URI`/平台域名为 `allowedHosts`，按需以 `--env-file /dev/null -f docker-compose.preview.yml` 拉起 data-only 数据层，绑定 `0.0.0.0`，打印原始命令。
- `scripts/setup-workspace.sh`：`corepack`/pnpm 引导与 compose 插值变量兜底（仅当未设置；预览路径的权威默认值在 `docker-compose.preview.yml` 与 `start-cloud-dev.sh`，不依赖本脚本的导出）。
- `docker-compose.preview.yml`：CNB preview 专用的 data-only 拓扑，只声明 postgres/clickhouse/redis/redis-celery/minio 并自带可丢弃的开发凭据默认值，必须用 `--project-directory <repo>` 与 `--env-file /dev/null` 单独加载；预览路径绝不加载生产 `docker-compose.yml`（也绝不加载 `docker-compose.yml` + `docker-compose.dev.yml`），因为 Compose 逐文件插值会在任何 overlay 生效前就要求 `API_IMAGE_REF`/`WORKER_IMAGE_REF`/`MCP_IMAGE_REF`/`JBROWSE_IMAGE_REF`/`MIGRATE_IMAGE_REF`/`MIGRATE_CLICKHOUSE_IMAGE_REF`、`SOYMUTDB_MCP_API_TOKEN`、`GRAFANA_PASSWORD` 与各 `*_PASSWORD` 等必填变量而中止。
- `docker-compose.yml` + `docker-compose.dev.yml`：本地开发 overlay 的 `!reset` 覆盖（仅本地开发入口使用，不属于 CNB preview 路径，也不得被 preview 命令加载）。生产 `docker-compose.yml` 单独加载时仍对上述变量保持 `${NAME:?…}` fail-fast，不回填任何开发默认值。
- `scripts/test_development_compose_contract.py`：节点级静态契约，断言 preview 拓扑 data-only 且 start-cloud-dev preview 路径不加载生产文件（仅作为 IMPLEMENTED_UNVERIFIED 证据，不作为 PASS）。
- `apps/web/src/lib/deployment.ts`、`apps/{web,admin,jbrowse}/vite.config.ts`：`resolveDevAllowedHosts()` 模式匹配 `.cnb.space` / `.cnb.run`。
- `apps/api/app/api/v1/health.py`、`scripts/deploy/preflight.sh`、`scripts/deploy/smoke.sh`。

### 4.3 数据流

```text
CNB 分支页按钮 / web_trigger_workspace-preview
  → vscode 流水线（services: docker + vscode，端口 8686 env）
  → scripts/start-cloud-dev.sh preview
      → 解析 CNB_VSCODE_PROXY_URI / CNB_DEV_DOMAIN → allowedHosts
      → setup-workspace.sh：pnpm install --frozen-lockfile
      → 补齐 POSTGRES/CLICKHOUSE/REDIS/MINIO 开发默认值（空值视为未设置）
      → docker compose --project-directory . --env-file /dev/null -f docker-compose.preview.yml --profile core up -d postgres clickhouse redis minio
      → 导出 SOYMUTDB_DATABASE_URL 指向开发 postgres
      → Vite 监听 0.0.0.0:8686，等待端口可连接后返回
  → 预览代理访问 *.cnb.space:8686 → SSG 门户可交互（data-app-ready=true）
  → API 侧（api-preview / 原生 uvicorn）读真实 PostgreSQL 解析 active release
```

数据层本身不写入任何公开数据；P0 只验证"能真实启动并连通"，不验证业务发布。

### 4.4 安全约束

1. 生产 `docker-compose.yml` 对凭据与 `*_IMAGE_REF`/MCP/Grafana 必填变量保持 `${NAME:?…}` fail-fast；CNB preview 只允许加载 data-only 的 `docker-compose.preview.yml`，绝不加载生产 `docker-compose.yml`（逐文件插值会在 overlay 生效前触发必填变量而中止）。预览/开发默认值只允许出现在 `docker-compose.preview.yml`、`docker-compose.dev.yml` 的 `!reset` 覆盖与 `setup-workspace.sh` 显式补齐，不得回填进基础文件。
2. `allowedHosts` 只接受平台模式（`.cnb.space` / `.cnb.run`）与显式追加主机；禁止 `allowedHosts: true`，避免 DNS rebinding。
3. 预览地址只是开发面，不得作为鉴权边界；P0 不引入 `internal` 数据到预览的公开响应。
4. 环境引导不得输出 secrets；命令与日志不得回显密码。
5. 生产与开发必须使用不同凭据来源；不得让开发默认值进入 release 镜像或生产环境变量。

### 4.5 错误处理

- Docker 不可用且 `SOYMUTDB_DEV_DATA_LAYER=on`：立即非零退出，禁止静默降级。
- 数据层 compose 插值失败：若预览路径因加载生产文件而要求 `*_IMAGE_REF`/MCP/Grafana 等必填变量，打印缺失变量与来源文件后非零退出；`docker-compose.preview.yml` 被单独加载时不得产生任何 `${NAME:?…}` 需求。
- Vite 在绑定 8686 前退出：打印日志尾部并非零退出，不放空预览。
- 端口可达但数据层未就绪：`/health/ready` 必须报告 `postgres.healthy=false`，不得返回整体 ok。
- active release 缺失：搜索返回 503 且消息为"无可用数据发布"，不得 500，不得构造假数据。

### 4.6 真实验收（PASS 条件）

在 CNB 平台真实运行，并留存 build id、命令、日志与响应：

1. `vscode`（或 `web_trigger_workspace-preview`）事件成功，`scripts/start-cloud-dev.sh preview` 退出 0。
2. `docker compose --project-directory <repo> --env-file /dev/null -f docker-compose.preview.yml ps` 显示 preview 命令实际启动的 postgres、clickhouse、redis、minio 均 `running`/`healthy`（`redis-celery` 仅在 preview 文件内定义供按需使用，不由 preview 启停命令拉起）。
3. 数据层驱动级探针通过：`pg_isready` 接受连接，MinIO `/minio/health/live` 返回 200。
4. 8686 预览 HTTP 返回门户 HTML，且 React 提交后 `data-app-ready="true"`（可交互，非空白）。
5. 真实 API：`GET /health/live` → `{"status":"ok"}`；`GET /health/ready` → `postgres.healthy=true`，可选依赖按模式报告。
6. 真实数据链：在一次性迁移库上 `alembic upgrade head` 后，`GET /api/v1/search` 返回 200 或可解释的 fail-closed 503；两者都必须无栈、无主机名泄漏。
7. 允许的 PASS 底座：CNB 平台 + Docker dind。仅当无法取得 CNB 平台时，可用等价真实 Docker daemon 本地复现同一脚本并记录为"本地等价 PASS（平台仍 BLOCKED）"；不得把节点级仿真记为 PASS。

### 4.7 停止 / 回滚条件

- 触发停止：任一数据层容器反复崩溃；预览路径加载了生产 `docker-compose.yml`（逐文件插值触发 `*_IMAGE_REF`/MCP/Grafana 必填变量）或加载了 `docker-compose.dev.yml` overlay；预览空白且日志显示 host 拒绝或端口未绑定；health/ready 谎报 ok。
- 回滚动作：`docker compose --project-directory <repo> --env-file /dev/null -f docker-compose.preview.yml --profile core down`，撤销 `docker-compose.preview.yml` 与 `start-cloud-dev.sh` 的本轮 diff，保留生产 `docker-compose.yml` 与本地 `docker-compose.dev.yml` 不变。
- 在 CNB 平台实跑通过前，`DEV_READY` 不得授予；`STAGING_READY` / `PRODUCTION_READY` 与 P0 无关。

## 5. P1：external Release/Assembly 发布隔离

### 5.1 目标

建立"导入就绪 → Release 组装 → 原子发布 → 双站制品隔离 → 字节级发布"的闭环：发布只做 `active_release` 事务切换；`external` 制品只含已发布公开数据；`internal` 制品与缓存、origin、Service Worker 命名空间完全分离；发布流水线只复制已验证字节、不重新构建。

### 5.2 组件

- `apps/api/app/models/content.py`（`Release`、`DataSet`、`active_release`、`release_data_sets`、`provenance`）与 `release_service.py`、`import_state_machine.py`。
- `apps/api/migrations/versions/*`：`0034_gene_crosswalks`、`0035_release_assembly_id` 及其后续 expand 迁移。
- `apps/web/scripts/build-sites.ts`（`VARIANTS=["external","internal"]`）、`scripts/release-manifest.ts`（生产强制 `SOYMUTDB_RELEASE_ID` + sha256）。
- `apps/web/src/lib/site-variant.ts`、内容快照服务、CORS/origin 配置、Service Worker 命名空间。
- `scripts/check_site_artifact_isolation.py`、`scripts/test_site_artifact_isolation.py`、`scripts/build-pages-artifact.sh`、`scripts/verify-pages-artifact.sh`、`scripts/stage-pages-publication.sh`。
- `.cnb.yml` 的 `main` → `publish` 流水线（字节级复制，不重建）；`deploy/scripts/upgrade.sh`、`deploy/scripts/blue-green-{deploy,rollback}.sh`。

### 5.3 数据流

```text
DataSet ready（PG 权威）
  → Release 组装：draft → validated → ready
  → 发布事务：行锁内切换 active_release 指针 + 写 release/audit（事务内不做构建/网络调用）
  → 提交后触发静态构建：
        build-sites.ts 显式产出 dist/external 与 dist/internal
        release-manifest 记录 SOYMUTDB_RELEASE_ID、逐文件 sha256
  → 制品隔离扫描（external 不得含未发布哨兵/internal_id/内部 origin）
  → publish 流水线：取回已验证静态树，字节级发布（不执行 docker build / 不重新 SSG）
  → 边缘/静态层切换；动态请求携带 release_id（X-SoyMutDB-Release）以锁定快照
```

### 5.4 安全约束

1. 发布是单一权威指针切换；任一必需组件（搜索、API、JBrowse、BLAST、下载、内容快照）未就绪则整体拒绝发布，不进入部分发布。
2. `external` 只读取 `published` 且可公开的数据；未发布、软删除、私有记录不得进入 external 响应、URL、导出、静态制品、source map、manifest、Service Worker。
3. `internal` 含 `noindex`，但 `noindex` 不构成访问控制；internal 的访问控制由 API 服务端鉴权执行。
4. 两套制品的 origin、CORS allowlist、缓存策略、Service Worker 命名空间、hashed assets 不得复用；external 只缓存公开响应，internal 响应 `private, no-store` 并按 `Authorization` 隔离。
5. 制品被构建时 origin 烧入，禁止跨环境复用（H05）；生产模式缺 `SOYMUTDB_RELEASE_ID` 必须失败。
6. 发布/回滚需要理由与结构化审计；生产发布凭据只出现在 main push / tag / 手动按钮，PR 流水线不得持有。

### 5.5 错误处理

- Release 状态机非法转换：服务端拒绝并返回可读错误，UI 只提交 `stage.x.completed`。
- 发布前置组件未就绪：非零退出并说明缺失项；`active_release` 不变。
- 制品扫描命中哨兵：publish 流水线失败，禁止发布该树。
- `SOYMUTDB_RELEASE_ID` 缺失：构建失败，不生成制品。
- 发布后发现不一致：`blue-green-rollback.sh` 校验上一 release manifest 后切回上一 `active_release`。
- 缓存命中不得改变可见性、assembly 或 release；命中即意味着键已含全上下文。

### 5.6 真实验收（PASS 条件）

在真实 Docker 生产拓扑或 CNB `publish` 流水线上运行，并留证：

1. 用真实 PostgreSQL + 合成 fixture 组装 release，原子发布后 `active_release` 指向新 release，审计与理由落库。
2. `pnpm --filter @soymutdb/web build:sites` 在真实 release 上下文产出 `dist/external` 与 `dist/internal`，两者 manifest/hashed assets/Service Worker 命名空间互不复用。
3. 真实制品扫描：`python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external --internal-root apps/web/dist/internal --sentinel "$UNRELEASED_SENTINEL"` 退出 0，external 零命中；同时以污染样例证明扫描器会失败（正常/污染/缺目录三态）。
4. 反向证据：把哨兵注入 internal 制品后扫描必须失败，证明哨兵确实进入过构建输入，而非"随机字符串得到空结果"。
5. `internal` 含 `noindex`、external 无；internal API 响应为 `private, no-store`，匿名访问被拒。
6. `publish` 流水线只复制已验证字节：记录被复制树的摘要与 `verify-pages-artifact.sh` 结果，证明未重新构建。
7. 缓存隔离：external/internal、release A/B 使用同一 query 时，CTX-01/CTX-02 通过，无跨上下文数据。
8. 允许的 PASS 底座：真实 Docker 生产拓扑或 CNB `publish` + 真实 PostgreSQL。缺真实 release 数据（CH 投影）时，标注 BLOCKED 而不是通过。

### 5.7 停止 / 回滚条件

- 触发停止：任何外部制品出现未发布哨兵或 `internal_id`；发布出现部分组件切换；制品 origin 与目标环境不一致；缓存/Service Worker 命名空间复用。
- 回滚动作：优先 `blue-green-rollback.sh` 切回上一 `active_release`；必要时 `git revert` 本轮 diff。数据库只做 expand 迁移，回滚以前滚恢复路径为准，禁止丢失 ID 映射。
- P1 未 PASS 前，external 不得接入 P2/P3 的生物数据读取端点。

## 6. P2：Variant assembly/release 上下文

### 6.1 目标

让变异查询显式绑定 release 与 assembly：请求携带可解析的 release/assembly 上下文，ClickHouse 投影按 release+assembly 过滤，响应返回机器可用与人类可读的 assembly 标识/版本以及 release，前端标签与 JBrowse 链接共享同一上下文；CH 不可用时统一 503，禁止 500 与宿主信息泄漏。

### 6.2 组件

- `apps/api/app/services/release_context.py`（release/assembly 解析、cursor 绑定）。
- `apps/api/app/services/variant_service.py`（`_ch_query` 包装）、`ClickHouseService._capability_guarded`（9 个公开查询方法统一把驱动/传输失败翻译为 503）。
- ClickHouse 投影：`variant_facts`（Replacing 语义）与迁移脚本 `migrate-clickhouse`。
- API 端点：`GET /variants`、`GET /variants/region`、`GET /stats/density`、`POST /tools/{diversity,allelefreq,ld}`、`GET /stats/*` 降级路径。
- Schema/OpenAPI 与 `packages/api-client` 生成类型。
- `apps/web` 变异列表/详情/region 路由与 JBrowse 链接构造器。
- `deploy/scripts` 的 CH 服务定义、`SOYMUTDB_DEPLOYMENT_MODE=baseline|extended`。

### 6.3 数据流

```text
请求（带 release_id / assembly_id 或可解析的深链）
  → release_context 解析：显式优先；未指定按 assembly 分组或返回歧义错误；不静默回落
  → variant_service._ch_query / ClickHouseService._capability_guarded
  → CH 查询绑定 release + assembly 过滤
  → 结果附加 assembly id/name/version + release + provenance/source
  → API 响应（external 仅公开、仅已发布）
  → 前端展示 assembly/release 标签，JBrowse 链接沿用同一 assembly 上下文
  → 缓存键含 site variant/release/assembly/实体/query/filters/cursor
```

### 6.4 安全约束

1. ClickHouse 只作投影：不得据此签发 ID、决定可见性；可见性一律由 PostgreSQL 的 release/权限决定。
2. v4/v5 坐标与结果不得混合；未指定 assembly 时不得把默认 assembly 悄悄应用。
3. external 只返回已发布公开变异；未发布 release 的投影不得可达。
4. CH 错误响应只含能力名，不含 host/port/栈；保持 baseline 模式 0 个 500。
5. 缓存键必须含 release 与 assembly；CTX-02/CTX-03 必须在真实集成中通过。

### 6.5 错误处理

- CH 不可达：`/variants`、`/variants/region`、`/stats/density`、`/tools/*` → 503（"Variant analytics projection (ClickHouse) is unavailable"），无栈、无主机名。
- PG 统计端点可在 baseline 下 200 降级；density 完全依赖 CH 时按能力不可用返回 503，不得构造违反响应模型的值（如 `chromosome_length=0`）。
- 显式 assembly 无匹配：404 风格统一响应。
- 无 assembly 歧义：按 assembly 分组并标记 `ambiguous`，或返回可判定歧义错误。
- literal `%` / `_` 查询：转义后按字面匹配，不得变成 LIKE 通配。
- release 指针切换后旧分页 cursor 不得复用（cursor HMAC 绑定 release/filters）。

### 6.6 真实验收（PASS 条件）

在真实 ClickHouse 投影 + 真实 PostgreSQL + 真实 API 上运行：

1. 用合成 v4 与 v5 投影数据，`GET /variants?release_id=…&assembly_id=…` 只返回对应命名空间结果。
2. `GET /variants/region` 显式带 assembly，返回结果与请求 assembly 一致，坐标不跨版本。
3. `GET /api/v1/search` 等 PG 链路不受影响；CH 端点 6/6 在 CH 不可达时返回 503，**0 个 500**（baseline 模式实测）。
4. REQ：`/stats/density` 在正常 CH 路径由 bins 推导 `chromosome_length`，满足响应契约。
5. CTX-02（跨 release）与 CTX-03（跨 assembly）在真实 CH+缓存集成交替请求下通过。
6. 真实浏览器或真实 API 响应中可见 assembly id/name/version 与 release 标签，JBrowse 链接携带同一 assembly。
7. 允许的 PASS 底座：真实 ClickHouse + PostgreSQL + 真实 API。无真实 CH 时，仅 503 降级可判 PASS，投影正确性标 BLOCKED。

### 6.7 停止 / 回滚条件

- 触发停止：投影无法保证 release/assembly 过滤；出现 500 或宿主信息泄漏；未指定 assembly 被静默默认；v4/v5 结果混合。
- 回滚动作：回退本轮 API/service/schema diff；CH 迁移脚本按 expand 设计可保留投影，回滚应用层。数据库迁移若有 expand，按前滚恢复；禁止删除已发布投影以外的权威数据。
- P2 未 PASS 前，external 不得把 CH 驱动的变异端点作为已发布能力对外宣称。

## 7. P3：genes assembly 绑定、全局搜索与 provenance 展示

### 7.1 目标

冻结基因的身份：`genes.gene_pk` 为内部代理键，`accession` 为语义列，唯一约束 `(assembly_id, accession)`；公开查询使用 `accession + assembly`。全局搜索对基因与变异返回结构化结果，区分 exact / alias / cross-version / text，显式处理无版本歧义，并把 provenance 透传到详情与 JBrowse；跨版本仅来自显式 crosswalk。

### 7.2 组件

- 模型/迁移：`genes.gene_pk` BigInt 代理主键、`id` → `accession` 语义迁移、`(assembly_id, accession)` 唯一约束、6 张 FK 表改引 `gene_pk`、`gene_crosswalks`（source/target `gene_pk` FK、`relation_type`、`provenance_source`、`provenance_evidence` JSONB、可空 release）。
- 搜索服务：`search_service.global_search`（分组 + `ambiguous` + `match_type`）、internal 授权分支、私有缓存策略。
- API/Schema：`/api/v1/search`（JSON）、internal 授权搜索端点、`/api/v1/genes/{accession}?assembly_id=…`、`/api/v1/mutants/{public_id}`。
- `packages/api-client` 生成客户端与 Web/Admin 调用方。
- `apps/web` 全局搜索结果行、基因详情、变异详情、provenance 面板、JBrowse 深链。
- 审计：internal 检索查询事件（结构化，不含凭据）。

### 7.3 数据流

```text
用户查询（首页/搜索结果页）
  → 解析 site variant + release + assembly 上下文
  → 基因：按 (assembly_id, accession) 精确查找；无 assembly → 分组/歧义
  → 突变体：external 按 public_id；internal 授权后按 public_id 或 internal_id，标注 matched_field
  → cross-version：仅通过 gene_crosswalks 关系，标注 exact/alias/cross-version/text 与 provenance
  → 结果：entity_type、canonical public identifier、display label、match_type、release、
          assembly id/name/version、provenance/source、canonical URL
  → 详情：assembly/release 保持一致；JBrowse/序列/表达/关联变异沿用同一 assembly
  → 缓存：external 公开缓存含全上下文；internal 直查（禁用共享缓存）
```

### 7.4 安全约束

1. 公开结果只用 `public_id`；external 响应/URL/下载/静态制品不得出现 `internal_id`。
2. 匿名以 `internal_id` 查询返回空/404 风格统一响应，不透露存在性。
3. internal 检索授权在 API 服务端执行（角色层级 ≥ researcher 复用 `_ROLE_GRANTS`），前端隐藏不构成授权。
4. v4/v5 同名 accession 必须共存且独立检索；跨版本等价只能来自 crosswalk。
5. 搜索缓存键含 site variant/release/assembly/类型/query/filters/cursor；internal 结果不得进入共享缓存。
6. 审计记录检索事件但不记录凭据或不必要敏感字段。

### 7.5 错误处理

- 无版本查询出现多版本命中：返回按 assembly 分组并标记 `ambiguous`，或可判定歧义错误；不静默默认。
- 显式 assembly 无匹配：404 风格响应。
- 迁移唯一性冲突（重复 `(assembly_id, accession)`、重复 `public_id`）：拒绝写入并报告。
- crosswalk 孤儿/缺 provenance：拒绝入库；展示不生成无来源关联。
- unauthorized internal：401/403 且无数据返回。
- literal `%` / `_` 与 LIKE 注入：转义后按字面匹配。
- cursor 跨 release/assembly 复用：拒绝，要求重新查询。

### 7.6 真实验收（PASS 条件）

在真实 PostgreSQL + 真实 API + 真实浏览器上运行 `database-core-contract.md` §7 矩阵，P0 场景不得 skip/xfail：

1. ID-01 … ID-05：external public_id 命中且无 internal_id；existing internal_id 不确认存在性；internal unauthorized 401/403；internal authorized 双 ID 定位同一实体且 match_type 正确；external 制品扫描零命中。
2. ASM-01 … ASM-05：v4/v5 精确命中各自命名空间；无版本歧义分组或显式歧义；v4 精确 + crosswalk 明示 v5 关联；相似但未映射不生成 cross-version。
3. CTX-01 … CTX-03：同一 query 在 external/internal、release A/B、v4/v5 下缓存不串数据。
4. UI-01 / UI-02：external 只显示 public ID；internal 可区分并复制两种 ID。
5. E2E-01 / E2E-02：external anonymous `search→detail→JBrowse` 与 internal authenticated internal-ID 搜索全链路 ID/assembly/release 不漂移。
6. provenance：搜索结果与详情可见 release、assembly、来源与 cross-version 关系类型；证据来自 crosswalk 而非前端拼接。
7. 迁移：upgrade 后已发布突变体 `public_id` 唯一且非空；v4/v5 数据可共存；crosswalk 约束与孤儿处理符合设计；downgrade 或前滚恢复不丢 ID 映射。
8. 允许的 PASS 底座：真实 PostgreSQL + 真实 API + 真实浏览器。缺真实浏览器时 E2E 标 BLOCKED，不得以 Vitest 替代。

### 7.7 停止 / 回滚条件

- 触发停止：任一 ID/ASM/CTX P0 场景失败；crosswalk 无法证明 provenance；external 泄漏 internal_id；双版本无法共存；上下文在详情/JBrowse 漂移。
- 回滚动作：回退本轮模型/迁移/服务/schema/客户端 diff；`public_id` 与 `gene_pk` 采用 expand 迁移，回滚以前滚恢复路径为准，保留 ID 映射与 redirect/alias 策略。
- P3 未 PASS 前不得执行生产数据回填或发布兼容性迁移。

## 8. P4：Admin Import Studio 上传到提交闭环

### 8.1 目标

把 Admin 导入从"填写 S3 URI / 计数即成功"升级为真实闭环：选择/上传不可变对象 → 服务端 inspection → DatasetVersion → ImportDraft → mapping/patches → validate → ready → 显式 commit → DataSet ready → `static_publish_requested` → 进入 P1 发布路径。提交前不得创建可恢复的服务器草稿，不得把部分数据暴露为公开数据。

### 8.2 组件

- `packages/api-client/src/admin-import-studio.ts`：类型化客户端。
- `apps/api/app/api/v1/import_studio.py`、`apps/api/app/schemas/import_studio.py`；`POST /admin/imports/studio/dataset-versions`、`POST /admin/imports/studio/drafts`、validate/commit 端点。
- `packages/jobs-py/src/soymutdb_jobs/module_schema.py`：格式感知 schema registry（txt/tsv/csv/xlsx）。
- `apps/api/app/services/module_import_service.py`、`import_state_machine.py`、`admin_modules`、`admin_imports.py`。
- Worker：`ModuleTsvAdapter`、格式感知 reader、批量写入、release-scoped `module_data_rows`、`static_publish` 任务。
- MinIO multipart 预签名与对象登记；诊断报告对象存储。
- Admin 导入 UI（拖拽/选择、sheet 选择、表头预览、行级诊断、任务详情）、i18n。
- 审计：upload complete / validate / ingest / ready / fail / retry / commit / publish request。

### 8.3 数据流

```text
Admin 选择本地文件
  → 格式/MIME/magic/大小/压缩比预检（拒绝 .xls/.xlsm、宏、伪造扩展名、zip bomb）
  → multipart presign → 浏览器直传 MinIO（不穿 FastAPI 内存）
  → 服务端 inspection：返回 object key、sha256、MIME、source/license、行列形态
  → POST /admin/imports/studio/dataset-versions（只用 inspection 权威值）
  → POST /admin/imports/studio/drafts（同 DatasetVersion 已存在则 resume，不重复）
  → mapping / patches（仅服务端状态）
  → validate（流式、行级诊断、staging 隔离）
  → ready
  → 显式 commit（不可变；committed draft 不可再改）
  → DataSet ready + evidence + 可下载错误报告
  → static_publish_requested → P1 发布路径
```

### 8.4 安全约束

1. 禁止上传前创建服务器草稿：DatasetVersion 必须基于服务端 inspection 的不可变元数据，客户端不得自造 checksum/MIME/行列数。
2. 对象不可变；同 checksum 重试幂等返回原 DataSet；不同 checksum 的同 release/module 明确 conflict。
3. staging 事务按 `transaction_id`/`dataset_id` 隔离；失败只清理当前 staging，不产生部分公开数据，不改变 `active_release`。
4. 拒绝 `.xls`/`.xlsm`、宏、外部链接、合并 header、空/重复/超长 header、控制字符、NUL；限制总大小、解压后大小、ZIP 压缩比、worksheet 数量。
5. 导出/模板防公式注入（`=,+,-,@` 前缀处理）。
6. Admin 仅内网/localhost 且服务端鉴权；输入不携带凭据；页面定义与 TSV 不得含 secrets。
7. 中断的上传不得表现为可恢复的服务器草稿；路由/恢复状态只携带 draft id 且受访问控制。

### 8.5 错误处理

- inspection/DatasetVersion 失败：不留下可恢复草稿，从不可变对象步骤提供重试路径。
- 格式/MIME/magic 不一致、zip bomb、宏：422 并给出可读原因。
- 行级诊断：最多 200 条 inline，完整报告存 MinIO；下载为 CSV/XLSX。
- worker 中途失败：保留部分批次标记，可重试；不把"只读过文件"记为成功。
- 提交后不可变：任何对 committed draft 的修改请求被拒绝。
- 并发同 release/module：明确 conflict，不静默覆盖。
- 发布请求失败：DataSet 保持 ready，发布由 P1 状态机重试；不回滚已 commit 的不可变草稿。

### 8.6 真实验收（PASS 条件）

在真实 Docker/API/浏览器 + 真实 MinIO + 真实 PostgreSQL 上运行：

1. 浏览器完成"选择文件 → 直传 → 预览 → 校验 → 提交"，全程无手填 S3 URI。
2. 服务端 inspection 返回 checksum/MIME/行列数；DatasetVersion 与 ImportDraft 用这些值创建；同源重入 resume 或明确 conflict，不重复数据。
3. 中断上传不产生可恢复草稿；恢复 UI 只显示 draft 身份、inspection 时间、状态与下一允许动作。
4. 非法文件（伪造扩展名、zip bomb、宏、合并 header）返回 422 且无 staging 残留。
5. 成功后 DataSet ready + evidence（format/sheet/schema_version/source_sha256/rows_seen/rows_inserted/parser_version），并出现 `static_publish_requested` 并进入 P1 发布。
6. 真实 MinIO 验证：对象命名空间隔离（跨 release/assembly/module 互不覆盖），未发布对象不可读，匿名公开 GET 403。
7. 真实 PostgreSQL 验证：迁移链 upgrade 到 head，staging 隔离与提交后不可变有集成测试；`module_import_service.py` 在真实 PG（非 `create_all`）上可运行。
8. 允许的 PASS 底座：真实 Docker/API/浏览器 + MinIO + PostgreSQL。缺 MinIO 或浏览器时标 BLOCKED。

### 8.7 停止 / 回滚条件

- 触发停止：提交前出现可恢复草稿；inspection 元数据可被伪造；失败后残留部分公开数据或 `active_release` 被改动；committed draft 可被修改。
- 回滚动作：撤销本轮 Admin/API/worker/schema diff；staging 数据清理；committed draft 本身不可变，只能通过 P1 发布指针回滚回到上一 `active_release`。对象存储保留不可变源对象与诊断报告作为审计。
- P4 未 PASS 前，不得把"计数即成功"路径标记为可用；成功只以完整上传→校验→导入→提交→发布请求链为准。

## 9. 跨阶段门禁与证据

1. 每一阶段必须有对应的窄测试与真实运行证据；命令、测试数、通过数、失败/跳过清单、制品摘要写进 PR 或阶段记录。
2. 契约测试（`scripts/test_*.py`、`scripts/check_*.py`、`python3 -m unittest scripts.test_site_artifact_isolation`）只作为 IMPLEMENTED_UNVERIFIED 证据；真实底座运行才升级为 PASS。
3. 交付链路仍以 `.cnb.yml` 为权威、GitHub workflow 仅镜像；所有 job body 只调用 `scripts/` 下脚本；Node/pnpm/Python/uv pins 必须一致。
4. 镜像校验与发布保持分离：验证流水线无 registry 写权限，发布流水线不重新构建。
5. 变更触及身份、搜索、assembly、release、可见性、缓存或站点变体时，必须跑 `database-core-contract.md` 的 Gate 0–6 与本规格对应阶段的真实验收。
6. 任何 P0 场景 skip/xfail、任何真实底座缺失被记为通过、任何静态检查被当作 PASS，均视为违反本规格，阶段判定回到 BLOCKED 或 FAILED。

## 10. 冻结规则

- 本规格的 P0–P4 范围、顺序、隔离不变量、PASS 判定与停止/回滚条件是冻结内容。
- 实现中若发现必须扩大范围或放宽约束，先修订本文件并重新评审，再改代码。
- 本规格不使用无判定标准的占位项；前置业务输入（`public_id` 正式格式与历史保留策略、internal 检索角色与审计保留期、无版本查询 UX、v4↔v5 映射展示与证据等级、真实映射数据来源）未提供时，对应阶段以 BLOCKED 状态与解除条件表达，不得自行拍板，也不得在生产回填或发布兼容性迁移上前进。
