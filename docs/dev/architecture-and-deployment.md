# 架构、契约与部署

本文以已批准数据发布与搜索规格为目标行为；目标行为不等于已完成生产部署验证。已有迁移、数据发布
模型和预签名上传是否可用，以代码库实际状态为准。

## 目标拓扑

```text
浏览器 → GitHub Pages（公开 demo）或 Cloudflare Pages（可选生产静态托管）
       → Cloudflare Tunnel（仅公开 API/基因组数据）→ tunnel-origin → API / MinIO
       → nginx → API / MCP / MinIO（自管/内部入口）
API → PostgreSQL（权威）/ ClickHouse（分析）/ MinIO（对象）/ Redis
worker-analyses → analyses 队列 → analyses bucket
```

生产 Compose 保留 API、worker、ClickHouse、PostgreSQL、MinIO、Redis、MCP 和 nginx。GWAS 使用 `gwas`
bucket，fastp/scanpy 等分析使用 `analyses` bucket。

Cloudflare Pages/Tunnel 是可选生产边缘方案：`cloudflare-tunnel` profile 使用 `cloudflared` 连接仅含 API、
公开基因组数据和健康检查的 `tunnel-origin`。管理端/API、MCP、数据库、MinIO 控制台和监控不经过该 Tunnel；
管理端须使用独立的受保护 origin。完整变量、上线、回滚与验证步骤见 [Cloudflare 部署手册](../../deploy/cloudflare.md)。

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
升级顺序为预检、manifest、拉取、备份、停止/迁移、启动、readiness、smoke 和 digest 状态记录。
ClickHouse 迁移输入封装在 worker 镜像内，不可逆迁移进入人工恢复门槛。完整决策见
[ADR-0001](../adr/0001-platform-delivery-contract.md)。

OCI 发布的 amd64/arm64 在原生 runner 上分别 build、runtime smoke、Trivy 与 SPDX，只有两份验证制品都成功
才合并 manifest；最终 index、平台 digest、SBOM、SLSA provenance 与 release manifest 使用 GitHub OIDC/Cosign
签名并立即验证。blue/green 不复用固定端口 Compose 伪装双槽，而由
[外部 slot adapter 合同](../../deploy/blue-green.md)完成 stage/verify/switch/current；实际负载均衡器、ARM runner、
Sigstore/GHCR 可用性和生产演练仍是外部验收项。

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
