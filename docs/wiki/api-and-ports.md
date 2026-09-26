# API、路由与端口

## 端口

以下来自 `docker-compose.yml`、`docker-compose.dev.yml`、`deploy/.env.example` 与
各 Vite 配置；`restart`/代理改动后以这些文件为准。

| 服务 | 宿主机 | 容器/开发 | 说明 |
| --- | --- | --- | --- |
| Nginx | `127.0.0.1:8080` | 80 | 唯一公网入口（HTTPS 由隧道/网关终止） |
| API（uvicorn） | 不发布 | `8010`（`expose`） | compose 内网经 nginx 访问；新默认端口 **8010**，`8000` 留给其他服务 |
| PostgreSQL | `127.0.0.1:5432` | 5432 | 权威存储 |
| ClickHouse | `127.0.0.1:8123` / `127.0.0.1:9000` | 8123 / 9000 | 分析投影 |
| Redis | `127.0.0.1:6379` | 6379 | 缓存/队列 |
| MinIO | `127.0.0.1:9001`（S3 API）/ `9002`（控制台） | 9000 / 9001 | 对象存储 |
| MCP server | 经 nginx `/mcp/*` | 9000 | 工具服务 |
| Celery beat | 不发布 | 9808 | 指标端口 |
| Web dev | `5173` | — | `pnpm dev:web`，dev 代理到 `http://localhost:8010` |
| 本地部署预览 | external `8090` / internal `8094` / 管理端 `8091` | — | `local-preview-server.mjs`，同源 `/api` 与 `/jbrowse/` |
| Admin dev | `5174` | — | `pnpm dev:admin` |
| JBrowse dev | `5175` | — | JBrowse 资源 |

端口覆盖：全部支持环境变量（如 `SOYMUTDB_DEV_API_PORT`、`SOYMUTDB_PREVIEW_API_PORT`、
`WEB_API_PORT`）；新默认值统一为 8010。

## API 路由分组

统一前缀 `/api/v1`，路由注册在 `apps/api/app/api/v1/router.py`；OpenAPI 契约见
`packages/api-client/openapi.json`。

| 分组 | 前缀 | 备注 |
| --- | --- | --- |
| 健康 | `/health` | `live` / `ready`；实例探活只用 `live` |
| 认证 | `/auth` | JWT + refresh cookie + CSRF |
| 基因/组装 | `/genes` | 含 `/genes/assemblies`、染色体 |
| 变异 | `/variants` | 列表（label 过滤）、`/variants/region`（label 必填）、详情、导出 |
| 搜索 | `/search` | 本地 + 联邦（`external=1`），来源状态逐源返回 |
| 突变系 | `/mutants` | 公开 `public_id` |
| 工具 | `/blast`、`/tools/seqfetch`、`/tools`（enrichment/exppattern）、`/sra`、`/analyses` | 分析任务走队列 |
| 内容 | `/site`、`/news`、`/content`、`/page-definitions`、`/publications`、`/downloads` | `/site/branding` 按变体返回品牌快照 |
| 站点配置 | `/releases`、`/stats`、`/tracks`、`/table-views` | 发布上下文与表格布局 |
| 管理 | `/admin/*` | 设置、媒体、新闻、导入、发布、审计、插件、实例（`/admin/species-instances`，含 `/{id}/health`） |

已知契约缺口（计划中）：`/variants` 与 `/variants/region` 目前按 assembly **label**
过滤；稳定 `assembly_id` 入参与 ClickHouse `assembly_key` 规范化尚待后端补齐，前端已用
id 做 URL/缓存身份并显式拒绝未知/歧义名称。

## 配置来源

| 配置 | 来源 |
| --- | --- |
| API 地址（构建期） | `VITE_API_BASE_URL`（生产必填 HTTPS origin） |
| 站点变体 | `VITE_SITE_VARIANT`=`external`/`internal`（构建期检查，非法值构建失败） |
| 子路径 | `VITE_BASE_URL`（静态产物与路由 base 一致） |
| 发布版本 | `VITE_SOYMUTDB_RELEASE_ID` → `X-SoyMutDB-Release` |
| 实例探活白名单 | `SOYMUTDB_INSTANCE_HEALTH_ALLOWLIST`（精确 HTTPS origin 列表） |
| 运行时密钥 | 环境变量/部署密钥，不进入仓库与前端产物 |
