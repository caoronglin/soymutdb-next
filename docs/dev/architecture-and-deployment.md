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

权威模型包括 `data_sets`、`import_tasks`、`releases`、`release_data_sets`、`active_release`、`provenance`
和 `AuditLog`。导入状态为 `uploading → validating → ingesting → ready → published → rolled_back`，失败
可重试；Release 状态为 `draft → validated → ready → published → rolled_back`。校验失败不能 ingest，
数据集未全 ready 不能发布。发布加行锁，在事务内切换 `active_release`；回滚切回上一指针并审计。

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

## 清理范围

清理目标包括 Tauri/Rust/Windows 打包链、无消费者 search worker、遗留 `search.html` 和 Cloudflare
`_headers`，但保留 news/about 等有效 SSG 链。搜索计划负责契约修复；本次清理不触碰仍在其他计划范围内的
api-client 死接口和发布领域模型。删除前必须确认无生产或测试引用。
