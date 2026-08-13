# SoyMutDB 开发者文档

当前主链由 Web 门户、Web-only Admin、FastAPI、Celery、PostgreSQL/ClickHouse、MinIO、Redis、MCP 和
GitHub Pages 组成。架构、状态机、契约、CI 和部署见 [`architecture-and-deployment.md`](architecture-and-deployment.md)。

```bash
pnpm --filter @soymutdb/web build
pnpm --filter @soymutdb/admin build:web
pnpm --filter @soymutdb/jbrowse build
docker compose -f docker-compose.yml -f docker-compose.dev.yml config
```

开发时以 OpenAPI、后端状态机和审计为权威；UI 不应自行推断发布状态或绕过校验。
