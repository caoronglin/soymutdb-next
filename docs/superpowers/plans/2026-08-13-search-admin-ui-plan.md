# Search Contract and Admin UI Implementation Plan

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复搜索契约与结果导航，接入可降级联邦搜索，并将 Admin 收敛为受权限保护的任务优先与资源目录骨架。

**Architecture:** FastAPI/OpenAPI 是唯一契约来源；搜索统一使用 `types`、`cursor`、`limit` 与 `next_cursor`/`has_more`/`total_count`，结果 `url` 永远是前端路由。API client 只暴露真实端点；门户负责内部/外部结果分组、来源健康、URL 状态和完整状态；Admin 删除无后端操作页，由共享 RBAC helper 保护真实资源。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy、Redis adapter/cache/circuit breaker、React 19、TanStack Router/Query、TypeScript、AntD 6、共享 `@soymutdb/ui`、pytest、Vitest、Playwright、openapi-typescript。

---

## 文件结构映射与所有权

### 新建

- `apps/api/tests/test_search_contract.py`：搜索 schema、URL、分页测试。
- `apps/api/tests/test_search_federation.py`：来源选择、聚合、健康和降级测试。
- `packages/api-client/src/search.test.ts`：client 参数、响应和 URL 测试。
- `apps/admin/src/routes/resource-catalog.tsx`：资源目录二级骨架。

### 修改或删除（仅限本计划）

- `apps/api/app/schemas/search.py`：统一搜索请求/结果/分页类型。
- `apps/api/app/services/search_service.py`：前端 URL、`by_type`、cursor 响应。
- `apps/api/app/api/v1/search.py`：统一参数，JSON 联邦聚合复用 adapter/cache/circuit breaker。
- `apps/api/app/api/v1/admin.py`、`apps/api/app/core/security.py`：共享 `_require_admin`、dashboard 权限、删除 level 7 死代码。
- `apps/api/tests/test_openapi_contract.py`：增量增加搜索与 dashboard 契约断言。
- `packages/api-client/src/search.ts`、`expression.ts`、`genes.ts`、`variants.ts`、`blast.ts`、`index.ts`：统一 client，删除六个死接口；`genes.ts`/`blast.ts` 只增量叠加既有未提交修改。
- `packages/api-client/openapi.json`、`src/generated/openapi.d.ts`：由后端重新生成，先保存精确 diff 再逐项确认。
- `apps/web/src/routes/search.tsx` 与 `apps/web/src/routes/search/*.tsx`：全局发现首页、独立工具页、联邦开关、完整状态和 URL 状态。
- `apps/admin/src/App.tsx`、`components/admin-sidebar.tsx`、`routes/__root.tsx`、`routes/index.tsx`：移除七个装饰入口，增加资源目录和任务优先首页。
- `apps/admin/src/routes/users.tsx`、`variants.tsx`、`assemblies.tsx`、`tracks.tsx`、`seeds.tsx`、`blast.tsx`、`releases.tsx`、`lib/tauri-api.ts`：确认零引用后删除或迁移；不删除 `apps/core-rs`、`deploy/windows`。
- `tests/e2e/search.spec.ts`：更新稳定选择器并断言前端 `url`。

### 只读参考

- `apps/api/app/search/` 全部 adapter、`aggregator.py`、`models.py`、`cache.py`、`circuit_breaker.py` 与模板：只复用，不改动。
- `apps/api/app/api/v1/expression.py`：最终依据为 `GET /api/v1/expression/genes/{gene_id}/expression`。
- `apps/api/app/api/v1/router.py`、`packages/api-client/openapi.json`、`src/generated/openapi.d.ts`：只读确认路由/类型。

**边界：** 工作区已有脏改动，特别是 `packages/api-client/src/genes.ts`、`packages/api-client/src/blast.ts`、`apps/api/tests/test_openapi_contract.py`；禁止覆盖、回滚、暂存，必须在现状上增量叠加。

## 任务

### Task 1: 固化搜索 schema 与 service 契约

**Files:** `apps/api/app/schemas/search.py`, `apps/api/app/services/search_service.py`, `apps/api/tests/test_search_contract.py`

- [ ] **Step 1: 写 RED 测试**

```python
def test_search_response_has_url_by_type_and_cursor_fields():
    response = GlobalSearchResponse(
        query="G1",
        results=[SearchResultItem(type=SearchResultType.GENE, id="G1", url="/search/genes/G1")],
        by_type={"gene": 1}, cursor=None, next_cursor=None, has_more=False, total_count=1,
    )
    assert response.results[0].url == "/search/genes/G1"
    assert response.by_type == {"gene": 1}
    assert response.total_count == 1

def test_global_search_signature_is_canonical():
    assert list(inspect.signature(SearchService.global_search).parameters) == [
        "self", "db", "query", "types", "cursor", "limit"
    ]
```

- [ ] **Step 2: 运行 RED**：`cd apps/api && pytest tests/test_search_contract.py -q`；预期因缺少字段/`cursor` 参数 FAIL。
- [ ] **Step 3: 实现类型与函数签名**

```python
class SearchResultItem(BaseModel):
    type: SearchResultType
    id: str
    name: str | None = None
    description: str | None = None
    score: float = Field(default=0.0, ge=0.0)
    url: str | None = None
    source: str = "internal"

class GlobalSearchResponse(BaseModel):
    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    by_type: dict[str, int] = Field(default_factory=dict)
    cursor: str | None = None
    next_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = Field(default=0, ge=0)
```

实现 `global_search(self, db: AsyncSession, query: str, types: list[SearchResultType] | None = None, cursor: str | None = None, limit: int = 20) -> GlobalSearchResponse`；生成 `/search/genes/{id}`、`/search/variants/{id}`、`/search/mutants/{id}`、`/search/publications/{id}`，不得生成 `/api/v1` URL；按类型填 `by_type`，不能可靠统计时填 `total_count=None`。
- [ ] **Step 4: 运行 GREEN**：`cd apps/api && pytest tests/test_search_contract.py -q`；预期 `2 passed`。

### Task 2: 统一 endpoint 与联邦 JSON 响应

**Files:** `apps/api/app/api/v1/search.py`, `apps/api/tests/test_search_federation.py`, `apps/api/tests/test_openapi_contract.py`

- [ ] **Step 1: 写 RED 测试**

```python
def test_search_openapi_uses_canonical_parameters():
    operation = app.openapi()["paths"]["/api/v1/search"]["get"]
    names = {p["name"] for p in operation["parameters"]}
    assert {"query", "types", "sources", "cursor", "limit"} <= names
    assert "page" not in names and "page_size" not in names
    assert {"by_type", "next_cursor", "has_more", "total_count"} <= set(
        app.openapi()["components"]["schemas"]["GlobalSearchResponse"]["properties"]
    )

@pytest.mark.asyncio
async def test_external_json_preserves_source_degradation(monkeypatch):
    response = ExternalSearchResponse(query="Glyma", sources=[
        SourceResult(SearchSource.NCBI, SourceStatus.OK, hits=[]),
        SourceResult(SearchSource.UNIPROT, SourceStatus.CIRCUIT_OPEN, error_message="open"),
    ])
    monkeypatch.setattr(ExternalSearchAggregator, "search", AsyncMock(return_value=response))
    result = await client.get("/api/v1/search", params={"query": "Glyma", "sources": "ncbi,uniprot"})
    assert result.json()["sources"][1]["status"] == "circuit_open"
```

- [ ] **Step 2: 运行 RED**：`cd apps/api && pytest tests/test_search_federation.py tests/test_openapi_contract.py -q`；旧 `page/page_size` 或无结构化联邦 JSON 时 FAIL。
- [ ] **Step 3: 实现签名**：`async def global_search(request: Request, db: AsyncSession = Depends(get_db), q: str = Query(..., alias="query"), types: list[SearchResultType] | None = Query(default=None), sources: list[str] | None = Query(default=None), cursor: str | None = Query(default=None), limit: int = Query(default=20, ge=1, le=50), format: str | None = Query(default=None), accept: str | None = Header(default=None, alias="accept")) -> Response`。JSON 内部搜索调用 service；启用 sources 时调用 `ExternalSearchAggregator(redis).search(q, sources=selected_sources, limit_per_source=max(3, min(10, limit)))`，返回每个 source 的 hits/status/error/elapsed/health。继续保留 HTML renderer 分支；cache key 使用 `SearchCache.make_key`。
- [ ] **Step 4: 运行 GREEN**：`cd apps/api && pytest tests/test_search_federation.py tests/test_openapi_contract.py -q`；预期全 PASS，OpenAPI 无 `page/page_size`。

### Task 3: 收敛 client、修正 expression、删除死导出

**Files:** `packages/api-client/src/search.ts`, `expression.ts`, `genes.ts`, `variants.ts`, `blast.ts`, `index.ts` 及对应测试

- [ ] **Step 1: 写 RED 测试**

```ts
it("serializes types/cursor/limit and never page_size", async () => {
  await globalSearch({ q: "Glyma", types: ["gene"], cursor: "c1", limit: 20 });
  expect(lastRequest.url).toContain("types=gene");
  expect(lastRequest.url).toContain("cursor=c1");
  expect(lastRequest.url).toContain("limit=20");
  expect(lastRequest.url).not.toContain("page_size");
});

it("uses the actual expression route", async () => {
  await getGeneExpression("G1");
  expect(lastRequest.path).toBe("/expression/genes/G1/expression");
});

it.each(["getGeneTranscripts", "getGeneVariants", "getGeneAnnotations", "getGeneVariantSummary", "getExportStatus", "cancelBlastJob"])(
  "does not export %s", async (name) => expect(name in await import("./index")).toBe(false),
);
```

- [ ] **Step 2: 运行 RED**：`pnpm --filter @soymutdb/api-client test -- src/search.test.ts src/expression.test.ts src/genes.test.ts src/variants.test.ts src/blast.test.ts`；旧参数/路径/导出应 FAIL。
- [ ] **Step 3: 实现实际类型**

```ts
export type SearchResultType = "gene" | "variant" | "mutant_line" | "phenotype" | "publication";
export interface SearchParams { q: string; types?: SearchResultType[]; sources?: string[]; cursor?: string; limit?: number; }
export interface SearchResponse { query: string; results: SearchResult[]; by_type: Record<string, number>; cursor: string | null; next_cursor: string | null; has_more: boolean; total_count: number | null; }
export function globalSearch(params: SearchParams): Promise<SearchResponse>;
export function getGeneExpression(geneId: string, params?: { tissue?: string; treatment?: string; library_id?: number; min_fpkm?: number; max_fpkm?: number }): Promise<GeneExpressionResponse>;
```

`getGeneExpression` 请求 `/expression/genes/${geneId}/expression`；expression/genes/variants/blast list 与 results 全部使用 `{ cursor?: string; limit?: number }` 和 `{ cursor, next_cursor, has_more, total_count }`。删除六个死函数及其测试引用，仅做增量补丁，不重写已有脏文件。
- [ ] **Step 4: 运行 GREEN**：`pnpm --filter @soymutdb/api-client test && pnpm --filter @soymutdb/api-client typecheck`；预期全 PASS、tsc 退出码 0。

### Task 4: 再生 OpenAPI 并精确审查

**Files:** `packages/api-client/openapi.json`, `packages/api-client/src/generated/openapi.d.ts`, `apps/api/tests/test_openapi_contract.py`

- [ ] **Step 1: 保存基线**：`cp packages/api-client/openapi.json /tmp/soymutdb-openapi.before.json && cp packages/api-client/src/generated/openapi.d.ts /tmp/soymutdb-openapi.before.d.ts`；预期文件存在。
- [ ] **Step 2: 运行后端契约测试**：`cd apps/api && pytest tests/test_openapi_contract.py -q`；按本任务更新断言，旧搜索快照断言失败、修复后 PASS。
- [ ] **Step 3: 生成**：`pnpm --filter @soymutdb/api-client generate:api-client`；只允许两份契约文件变更。
- [ ] **Step 4: 原始 diff 逐项确认**：`diff -u /tmp/soymutdb-openapi.before.json packages/api-client/openapi.json; diff -u /tmp/soymutdb-openapi.before.d.ts packages/api-client/src/generated/openapi.d.ts`；预期仅有本任务搜索字段/参数、expression 路径、cursor/limit、死端点/权限变化，任何无关变化立即停止并人工合并。

### Task 5: 门户搜索 IA、联邦来源与完整状态

**Files:** `apps/web/src/routes/search.tsx`, `apps/web/src/routes/search/*.tsx`, `packages/api-client/src/search.ts`, `tests/e2e/search.spec.ts`

- [ ] **Step 1: 写 RED E2E**

```ts
test("result row exposes a frontend URL", async ({ page }) => {
  await page.goto("/search?q=Glyma");
  const row = page.getByTestId("search-result-row").first();
  await expect(row).toBeVisible();
  expect(await row.getAttribute("data-url")).toMatch(/^\/search\//);
  expect(await row.getAttribute("data-url")).not.toContain("/api/v1");
});

test("query and external source are URL state", async ({ page }) => {
  await page.goto("/search");
  await page.getByRole("searchbox").fill("Glyma");
  await page.getByTestId("external-source-toggle").check();
  await page.getByRole("searchbox").press("Enter");
  await expect(page).toHaveURL(/q=Glyma/);
  await expect(page).toHaveURL(/external=1/);
});
```

- [ ] **Step 2: 运行 RED**：`pnpm exec playwright test tests/e2e/search.spec.ts`；旧选择器/行为应 FAIL，禁止 `waitForTimeout` 和 `#` fallback。
- [ ] **Step 3: 实现**：`validateSearch` 定义 `q/types/cursor/limit/external/tissue/treatment/min_fpkm`；调用 `globalSearch({ q, types, sources: external ? ["ncbi","uniprot","ensembl","ebi"] : undefined, cursor, limit })`。`total_count === null` 隐藏总数；整行 Link 只在 `url` 存在时可点击，缺失 URL 用 `aria-disabled=true`、`tabIndex=-1`、`data-testid=search-result-disabled`，不使用 `#`。外部结果按四源分组，显示来源/status/health，保留其他源的降级结果。React Query 使用 `placeholderData: previous => previous`；loading 保留旧数据，empty 区分无查询/无数据/无匹配，error 展示 Request ID + Retry；保留科学绿色、HarmonyOS Sans SC、JetBrains Mono、OKLCH token，不引入组件库；同页不混用两套 Card。子工具页不再传 `page/page_size`，移动端保持可操作状态。
- [ ] **Step 4: 运行 GREEN**：`pnpm --filter @soymutdb/web typecheck && pnpm exec playwright test tests/e2e/search.spec.ts`；预期 typecheck 和 E2E 全 PASS。

### Task 6: Admin 清理、目录骨架与任务优先首页

**Files:** `apps/admin/src/App.tsx`, `components/admin-sidebar.tsx`, `routes/__root.tsx`, `routes/index.tsx`, `routes/resource-catalog.tsx`, 七个装饰页、`lib/tauri-api.ts`

- [ ] **Step 1: 写 RED 测试**

```tsx
it("does not expose decorative admin paths", () => {
  expect(renderedSidebarPaths()).not.toEqual(expect.arrayContaining([
    "/users", "/variants", "/assemblies", "/tracks", "/seeds", "/blast", "/releases",
  ]));
});
```

- [ ] **Step 2: 运行 RED**：`pnpm --filter @soymutdb/admin test -- --run`；旧入口存在时 FAIL。
- [ ] **Step 3: 实现**：从 App lazy imports、route declarations、route tree、sidebar、PAGE_TITLES 删除七个操作页；加入 `/resource-catalog`，只链接 Imports/Content/Audit/Settings 等真实页面并说明后续资源目录重建。确认零 import 后删除/迁移七个文件和 `tauri-api.ts`。Dashboard 使用真实 admin stats/series，增加任务优先区；error 显示 Request ID + Retry，刷新保留旧数据，空 series 显示无数据。不要删除 `apps/core-rs`、`deploy/windows`。
- [ ] **Step 4: 运行 GREEN**：`pnpm --filter @soymutdb/admin test -- --run && pnpm --filter @soymutdb/admin typecheck && pnpm --filter @soymutdb/admin build:web`；预期全 PASS。

### Task 7: 统一 RBAC helper、修复 dashboard 权限和死 level

**Files:** `apps/api/app/core/security.py`, `apps/api/app/api/v1/admin.py`, `apps/api/tests/test_openapi_contract.py`, `apps/admin/src/routes/users.tsx`

- [ ] **Step 1: 写 RED 测试**

```python
def test_require_admin_roles():
    assert require_admin_roles([RoleName.ADMINISTRATOR.value]) is None
    with pytest.raises(AuthorizationError):
        require_admin_roles([RoleName.AUDITOR.value])

def test_dashboard_requires_authentication():
    for path in ("/api/v1/admin/dashboard-stats", "/api/v1/admin/dashboard-series"):
        assert app.openapi()["paths"][path]["get"].get("security")
```

- [ ] **Step 2: 运行 RED**：`cd apps/api && pytest tests/test_openapi_contract.py -q -k 'admin or dashboard'`；dashboard handler/helper 旧行为应 FAIL。
- [ ] **Step 3: 实现共享签名**

```python
def require_admin_roles(user_roles: list[str]) -> None:
    if not has_role(user_roles, RoleName.ADMINISTRATOR):
        raise AuthorizationError("Administrator role required")
```

`_require_admin(current_user: User) -> None` 只调用 `require_admin_roles(get_user_roles(current_user))`；两个 dashboard handler 在查询前调用 `_require_admin`。删除 `role.level >= 7`，角色标签改用 `RoleName`/共享 level 映射。
- [ ] **Step 4: 运行 GREEN**：`cd apps/api && pytest tests/test_openapi_contract.py -q -k 'admin or dashboard' && pytest tests -q`；预期低权限为统一 403，目标测试及 API 测试全 PASS。

### Task 8: 自审、全量验证与 diff 所有权

- [ ] **Step 1: 扫描占位符和旧契约**：`rg -n 'TODO|TBD|page_size|page:|getGeneTranscripts|getGeneVariants|getGeneAnnotations|getGeneVariantSummary|getExportStatus|cancelBlastJob|href="?\#|to=.?\#|level\s*>=\s*7' apps/api packages/api-client apps/web apps/admin tests/e2e -g '*.{py,ts,tsx}'`；本任务路径不得剩余对应搜索旧命名、死导出、`#` fallback、level 7。
- [ ] **Step 2: 对照规格第 5、6、9 节**：逐项确认 `url/by_type`、types/cursor/limit、null total、联邦四源/缓存/断路器/降级、七个 Admin 装饰页清理、共享权限、两种 IA、loading/empty/error/URL/mobile、主题 token、OpenAPI/E2E；缺一项补回对应任务。
- [ ] **Step 3: 运行验证**：`cd apps/api && pytest tests/test_search_contract.py tests/test_search_federation.py tests/test_openapi_contract.py -q`; `pnpm --filter @soymutdb/api-client test`; `pnpm --filter @soymutdb/web typecheck`; `pnpm --filter @soymutdb/admin typecheck`; `pnpm exec playwright test tests/e2e/search.spec.ts`；预期全部 PASS。
- [ ] **Step 4: 仅审查 owned diff，不提交**：`git diff -- docs/superpowers/plans/2026-08-13-search-admin-ui-plan.md apps/api/app/schemas/search.py apps/api/app/services/search_service.py apps/api/app/api/v1/search.py apps/api/app/api/v1/admin.py apps/api/app/core/security.py apps/api/tests/test_search_contract.py apps/api/tests/test_search_federation.py apps/api/tests/test_openapi_contract.py packages/api-client/src/search.ts packages/api-client/src/expression.ts packages/api-client/src/genes.ts packages/api-client/src/variants.ts packages/api-client/src/blast.ts packages/api-client/src/index.ts packages/api-client/src/search.test.ts packages/api-client/openapi.json packages/api-client/src/generated/openapi.d.ts apps/web/src/routes/search.tsx apps/web/src/routes/search apps/admin/src/App.tsx apps/admin/src/components/admin-sidebar.tsx apps/admin/src/routes apps/admin/src/lib/tauri-api.ts tests/e2e/search.spec.ts`；预期只见 owned paths，禁止 `git add`、`git commit`、`git reset`。

## 已知风险

1. `genes.ts`、`blast.ts`、`test_openapi_contract.py` 有未提交修改，必须精确增量合并，冲突即暂停。
2. OpenAPI 再生可能带来无关快照变化，必须基线复制并用原始 `diff -u` 逐项确认。
3. JSON/HTML content negotiation 可能有旧消费者；前端使用 `format=json`，保留 HTML 分支。
4. 非搜索真实资源端点仍可能是 page-based，不能机械全库替换。
5. 联邦上游不可控，CI mock aggregator/adapter，生产依赖现有 Redis 断路器和缓存。
6. 删除页面前必须零引用；本计划不越界删除 core-rs、Windows 部署链或修改其他文件。
