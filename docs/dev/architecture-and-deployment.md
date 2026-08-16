# 架构、契约与部署

本文以已批准数据发布与搜索规格为目标行为；目标行为不等于已完成生产部署验证。已有迁移、数据发布
模型和预签名上传是否可用，以代码库实际状态为准。

## 目标拓扑

```text
浏览器 → GitHub Pages（web 根目录、soymutdb-admin/、soymutdb-jbrowse/）
       → nginx → API / MCP / MinIO
API → PostgreSQL（权威）/ ClickHouse（分析）/ MinIO（对象）/ Redis
worker-analyses → analyses 队列 → analyses bucket
```

生产 Compose 保留 API、worker、ClickHouse、PostgreSQL、MinIO、Redis、MCP 和 nginx。GWAS 使用 `gwas`
bucket，fastp/scanpy 等分析使用 `analyses` bucket。

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

API、worker、MCP 使用不可变显式 tag；发布路径执行 `docker manifest inspect`。PR 没有远端 tag 时只做本地
build/scan/smoke。升级顺序为预检、manifest、拉取、备份、停止/迁移、启动、readiness、smoke 和状态记录。
ClickHouse 迁移输入封装在 worker 镜像内，不可逆迁移进入人工恢复门槛。MCP 使用 `MCP_IMAGE_TAG`，分析
任务由 `worker-analyses` 消费。

## Pages 单次发布

同一 workflow 构建并组装：

```text
/                         # web，含 index.html、404.html、.nojekyll
/soymutdb-admin/          # admin
/soymutdb-jbrowse/        # JBrowse
```

只执行一次 `git push origin gh-pages --force`，保留 `concurrency.group: pages`，发布前断言三个 index 存在
并运行 news/about smoke。GitHub Pages 不解析 Cloudflare `_headers`；安全头由托管层配置。

## 清理范围（已清理）

已移除 Tauri 桌面壳（`apps/admin/src-tauri`）、Rust 热路径（`apps/core-rs`）、Windows 打包链、无消费者
search worker 和遗留 `search.html`/Cloudflare `_headers`；保留 news/about 等有效 SSG 链（`ssg-content.ts`）。
Admin 现在为 Web-only（`/soymutdb-admin/`）。删除前须确认无生产或测试引用。
