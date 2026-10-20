# 架构、契约与部署

本文以已批准数据发布与搜索规格为目标行为；目标行为不等于已完成生产部署验证。已有迁移、数据发布
模型和预签名上传是否可用，以代码库实际状态为准。

## 目标拓扑

```text
浏览器 → GitHub Pages（公开 demo）或 Cloudflare Pages（可选生产静态托管）
       → Cloudflare Tunnel（仅公开 API/基因组数据）→ tunnel-origin → API / MinIO
       → nginx → API / MCP / MinIO（自管/内部入口）
API → PostgreSQL（权威：身份、关系、release、权限、变异事实、匿名分析）
    → MinIO/S3（对象）/ Redis（缓存与 broker，可丢弃）
worker-analyses → analyses 队列 → analyses bucket
历史 ClickHouse 源端 → 仅在显式加载 docker-compose.legacy-clickhouse.yml
                     并选择 legacy-migration profile 时存在（回填源，不是运行时依赖）
```

生产 Compose 保留 API、worker、PostgreSQL、MinIO、Redis、MCP 和 nginx，**不含 ClickHouse**。变异事实、
统计与匿名分析都由 PostgreSQL 提供；Redis 只是可丢弃的缓存与 broker，MinIO 存对象。GWAS 使用 `gwas`
bucket，fastp/scanpy 等分析使用 `analyses` bucket。

旧 ClickHouse 现在只是**迁移源**：历史源端与旧 schema migrator 在
`docker-compose.legacy-clickhouse.yml`（`legacy-migration` profile），必须显式加载。四个默认 compose
（生产、开发、本地、预览）都没有 `clickhouse` / `migrate-clickhouse` 服务，API/Worker 也不再注入
`SOYMUTDB_CLICKHOUSE_*`。逐版本回填与生产切换的真实执行记录见
[原生 PostgreSQL 迁移与验收](native-postgres-cutover.md)，本文不据此宣称生产替代已完成。

Cloudflare Pages/Tunnel 是可选生产边缘方案：`cloudflare-tunnel` profile 使用 `cloudflared` 连接仅含 API、
公开基因组数据和健康检查的 `tunnel-origin`。管理端/API、MCP、数据库、MinIO 控制台和监控不经过该 Tunnel；
管理端须使用独立的受保护 origin。完整变量、上线、回滚与验证步骤见 [Cloudflare 部署手册](../../deploy/cloudflare.md)。Admin 当前页面、API、数据库和性能边界见 [Admin 架构与 API 数据库映射](admin-architecture.md)。

## 模型与状态机

权威模型包括 `data_sets`、`import_tasks`、`releases`、`release_data_sets`、`active_release`、`provenance`、
`AuditLog`、`page_definitions` / `page_definition_versions`（Page Builder，Phase 2）以及
`static_publications` / `publication_counters` / `publication_target_leases`（不可变发布，Phase 3）。

导入状态为 `uploading → validating → ingesting → ready → published → rolled_back`，失败可重试；
Release 状态为 `draft → validated → ready → published → rolled_back`。校验失败不能 ingest，数据集未全
ready 不能发布。发布加行锁，在事务内切换 `active_release`；回滚切回上一指针并审计。

## 不可变多目标静态发布（Phase 3）

发布一条不可变静态制品到 Admin 选择的目标（`local` / `github_pages` / `cloudflare_pages`）。模型为
`StaticPublication`，状态为
`requested → building → validating → deploying → published`，可失败进入 `failed`，可被更新请求 `superseded`，
发布后可 `rolled_back`。关键约束：

- **单调 ID + 租约**：`publication_id` 按目标作用域单调递增（`(target, publication_id)` 唯一），由
  `PublicationTargetLease` 行锁在分配与最终晋升时短暂持有；不做网络 I/O 时持锁。
- **陈旧任务防护**：晋升前比较当前 `publication_id` 与目标最新请求 ID，不等则标记 `superseded`，绝不为过期任务
  调用 promote。构建/校验/部署失败都不改变当前发布指针。
- **制品不可变**：产物树写入 `dist/releases/<release-id>/<manifest-digest>/` 全新目录；`manifest.json` 含逐文件
  SHA-256 + release/page/应用元数据（确定性摘要，排除时间戳）；`validate-static-tree.ts` 拒绝缺路由、意外文件、
  不安全标记、内链断裂与哈希不匹配。
- **三适配器**：`local`（新版本目录 + fsync + `os.replace` 原子替换 `current` 符号链接）、`github_pages`
  （`workflow_dispatch` 输入 `publication_id`/`artifact_url`/`manifest_digest`，下载→摘要校验→烟雾→单次 gh-pages
  提交→更新 ref）、`cloudflare_pages`（上传→轮询→校验→promote，记录部署 ID/时间，CDN 传播视为最终一致）。
- **凭据**：只存目标标识符；令牌/密钥从 env/secret 读取，API 响应与审计日志 redact。
- **release 绑定**：生成 HTML/API client 带 `X-SoyMutDB-Release`（或 `release_id`），静态页固定查询生成时的
  release，active release 切换后仍一致。
- **快照 release 感知**：`/content/snapshot` 接受显式 `release_id` / `page_definition_version`，缓存 key 按 release
  区分；无显式 release 时服务可变 active-release 别名（仅交互读）。

Admin 端点：`/admin/publication/targets`（列目标，redacted）、`/admin/publication/request`（发起发布）、
`/admin/publication/{id}`（检视证据）、`/admin/publication/{id}/rollback`（回滚）。

## 接口、幂等与审计

- `/api/v1` 保持兼容，新增管理能力使用 `/api/v1/admin/*` 或等价端点。
- OpenAPI 是唯一契约来源；搜索结果使用真实前端 `url`，缺失时禁用而非 `#`。
- 搜索统一 `cursor/next_cursor/has_more/total_count`，`total_count=null` 时隐藏总数。
- 导入 dispatch 使用 `idempotency_key`（如 `import:{id}`），状态与 outbox 原子提交。
- 导入、审批、发布、回滚写结构化审计；预签名 multipart 让浏览器直传 MinIO。

## CI、Compose 与 MCP

生产 Compose 使用 `core` / `jbrowse` / `blast` / `analyses` / `mcp` / `cloudflare-tunnel` 能力 profile；
默认启用 `core,blast,analyses,mcp`。API、worker、MCP、JBrowse 的 CI tag 只用于发现，发布后解析远端
manifest 并输出 `image@sha256` 合同，生产仅接受 `*_IMAGE_REF` digest 引用。PR 只在 CI 做本地
build/scan/runtime smoke 与全部 profile 的 `docker compose config` 验收；开发机合同测试不要求 Docker。
升级顺序为预检、manifest、拉取、备份、停止、`migrate`（alembic）→ `app.scripts.verify_native_cutover`
→ 启动、readiness、smoke 和 digest 状态记录。`verify_native_cutover` 不通过就不启动新应用。
旧 ClickHouse schema 迁移已移出默认路径：`upgrade.sh` 不再引用 `migrate-clickhouse`，只有显式加载历史
叠加层并使用 `legacy-migration` profile 时才运行。完整决策见
[ADR-0001](../adr/0001-platform-delivery-contract.md)。

OCI 发布的 amd64/arm64 在原生 runner 上分别 build、runtime smoke、Trivy 与 SPDX，只有两份验证制品都成功
才合并 manifest；最终 index、平台 digest、SBOM、SLSA provenance 与 release manifest 使用 GitHub OIDC/Cosign
签名并立即验证。blue/green 不复用固定端口 Compose 伪装双槽，而由
[外部 slot adapter 合同](../../deploy/blue-green.md)完成 stage/verify/switch/current；实际负载均衡器、ARM runner、
Sigstore/GHCR 可用性和生产演练仍是外部验收项。

## 备份与恢复格式

`deploy/scripts/backup.sh` 默认输出 **v3**：只含权威 PostgreSQL 与 S3 对象，因为默认运行时已经没有
ClickHouse 组件；覆盖不到全部必需组件的运行会失败，而不是产出一个残缺归档。历史 **v2** 包只有显式
`--allow-legacy-v2`，且目标 compose 确实提供 `clickhouse` 服务时才允许 `restore.sh` / `verify-restore.sh`
恢复或校验，缺失组件不会被当成「已校验」。v2 恢复还需要目标目录旁存在
`docker-compose.legacy-clickhouse.yml`（或等价的显式历史目标配置），并提供 `RESTORE_CLICKHOUSE_HOST/USER`
（校验侧为 `CLICKHOUSE_HOST`）。

## 本地复现生产拓扑

`scripts/compose-local.sh` 是显式的开发/自建入口：用同一批 Dockerfile 构建镜像，再由
`docker-compose.local.yml` 覆盖 digest 要求；它不是发布路径的回退。默认 profile 是 `core`，
**不含也不需要** ClickHouse。历史源端只能显式开启：

```bash
SOYMUTDB_LOCAL_LEGACY_CLICKHOUSE=1 bash scripts/compose-local.sh up -d
```

该模式会额外加载 `docker-compose.legacy-clickhouse.yml`、启用 `legacy-migration` profile，并只在此模式
下提供 `CLICKHOUSE_PASSWORD` 与 `MIGRATE_CLICKHOUSE_IMAGE_REF`。`scripts/list-images.sh` 仍保留
`migrate-clickhouse` 条目，让历史回填镜像还能在本地构建。

## Pages 单次发布

同一 workflow 构建并组装：

```text
/                         # web，含 index.html、404.html、.nojekyll
/soymutdb-admin/          # admin
/soymutdb-jbrowse/        # JBrowse
```

自动发布由 CI 在 main 上成功后经 `workflow_run` 驱动：pages.yml 的 gate 只放行本仓库 main 分支的成功
CI（失败/取消/PR 运行被拦截），deploy job 再 checkout `workflow_run.head_sha` 构建发布；`workflow_dispatch`
仍可手动绕过门禁（运维专用）。只执行一次 `git push origin gh-pages --force`，保留 `concurrency.group: pages`，
发布前断言三个 index 存在并运行 news/about smoke。GitHub Pages 不解析 Cloudflare `_headers`；安全头由托管层配置。

## 清理范围（已清理）

已移除 Tauri 桌面壳（`apps/admin/src-tauri`）、Rust 热路径（`apps/core-rs`）、Windows 打包链、无消费者
search worker 和遗留 `search.html`/Cloudflare `_headers`；保留 news/about 等有效 SSG 链（`ssg-content.ts`）。
Admin 现在为 Web-only（`/soymutdb-admin/`）。删除前须确认无生产或测试引用。

## 双站点变体与安全边界

SoyMutDB 的门户现在支持两个**独立静态制品**：external（外部站点）和 internal（内部站点）。两者共用同一份 React 19 / Umi Max 4 代码（`apps/web/package.json`，入口 `src/umi-entry.tsx`），但通过构建变量显式选择，不根据 hostname、IP、请求头、cookie、User-Agent 或访客身份在后端推断站点。`scripts/check-vue-retirement.mjs` 断言仓库里已没有 Vue 运行时依赖，本文不再描述 Vue/Vite 前端。

- 在 apps/web 执行 pnpm run build:sites 会按顺序生成 dist/external 与 dist/internal 两棵完整制品树；每棵树的 hashed bundle、SSG HTML、robots.txt、Service Worker 和 integrity manifest 都独立生成。
- VITE_SITE_VARIANT 只允许 external 或 internal。external 的 site API 可公开缓存；internal 的 site API（about、home、footer、content）必须携带 Bearer 访问令牌，并返回 private, no-store，避免共享缓存泄露内容。
- Admin 设置页的站点变体选择器分别写入 about_external、home_external、footer_external、content_external 或对应的 internal 命名空间。它们继续使用服务端 registry 校验、乐观版本、回滚和结构化审计；旧的无变体设置仅作为迁移期只读 fallback。
- internal 制品不会嵌入 public content snapshot，且所有 SSG 页面带 noindex、nofollow、noarchive。robots/noindex 只是防误索引措施，**不是访问控制**；internal origin 必须额外放在 Cloudflare Access/Zero Trust、VPN、私有负载均衡或等价 SSO/网络策略后面。
- internal API origin 不得复用只面向公开数据的 Tunnel hostname。CORS 必须为每个 external/internal/admin origin 精确列举，禁止使用星号；内部站点的 CDN/Pages 项目也必须关闭匿名公开访问或在边缘强制 Access。

首次切换步骤：先在 Admin 选择 Internal site 保存一套内容，再以 SOYMUTDB_INTERNAL_SITE_URL 配置生产内部 origin，执行 build:sites；将 dist/internal 单独部署到受保护 origin，将 dist/external 部署到公开 origin。发布前用未登录请求验证 internal 的 /api/v1/site/content?variant=internal 返回 401，并用已授权 viewer 验证 200；同时确认响应没有 shared-cache 命中。
