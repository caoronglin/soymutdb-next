# Service Layer Pattern（后端分层试点：genes 域）

试点结论：`api/v1/genes.py` 自基线起已是薄控制器，SQL 全部在 `services/gene_service.py`。
本模式供 variants/expression/search/sra/tracks/releases 域复制。

## 分层边界

- **控制器** `api/v1/<domain>.py`：只做 Query 参数解析 → 构造 Params schema → 调 service → 返回响应。不 import 任何 model/SQLAlchemy 类型，不写 SQL。
- **服务** `services/<domain>_service.py`：全部查询/过滤/分页/映射逻辑；方法签名 `async def xxx(self, db: AsyncSession, ...) -> ResponseSchema`；`select()` 用显式 `.where()` 逐条件追加。
- **错误处理**：service 抛域异常（`NotFoundError`/`ValidationError`，见 `core/exceptions.py`），全局 `soy_mut_db_exception_handler` 统一转错误信封；控制器仅对 `get_gene` 类单查做显式 try/except（`SoyMutDBError` re-raise，其余转 500），其余路由依赖全局 handler。**禁止在控制器里改状态码/响应结构**。
- **命名**：`list_<entity>` / `get_<entity>` / `list_assemblies` / `list_chromosomes`；参数对象复用 schemas 里的 `<Domain>ListParams`；私有映射 helper 用 `_<entity>_to_response` 静态方法。

## 测试模式

- 单元测试不依赖 docker：自定义 `FakeDbSession`（实现 `execute` → 按 `"FROM <table>"` 分发 `_Result`），service 测试直接构造 ORM 对象断言映射结果 + `str(session.last_stmt)` 断言 SQL 过滤条件（参照 `tests/test_news_api.py`、`tests/test_gene_service.py`）。
- 控制器测试 patch service 方法（`AsyncMock`），验证参数传递与响应结构（`tests/test_genes.py` 已有）。

## 复制清单（下一批域）

1. 审计路由中的直写 SQL → 移入 `<domain>_service.py`，方法名按上表。
2. 路由只留参数解析 + 调 service；参数 schema 与响应 schema 不动。
3. 补 `tests/test_<domain>_service.py`（FakeDbSession + SQL 断言）并跑 `pytest tests -k <domain>` 全绿。
