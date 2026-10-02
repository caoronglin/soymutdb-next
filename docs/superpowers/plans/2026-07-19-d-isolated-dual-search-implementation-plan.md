# Plan D：隔离双搜索与科学 UX 垂直切片实施计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or an equivalent task-by-task execution workflow) to implement this plan. Execute only after Plan C has produced validated publication/projection artifacts and after B-pre-ADR has frozen the initial search ceilings. Do not implement, migrate, add dependencies, or deploy before the plan has passed its required Oracle review and the preceding gates are recorded as passed.

**状态：** Phase 2 实施计划；等待 Plan C 验证制品、B-pre-ADR 搜索边界和本计划复核

**目标：** 在已验证的不可变 publication artifact 之上，把当前内容协商的 `/search` 拆成两个物理和语义隔离的系统：只读已发布 manifest/shard 的 Internal Search，以及只经 allowlist adapter 访问第三方来源的 External Search。为 Worker、Internal API、External API、静态目录和 typed api-client 建立明确契约，并保证任何失败路径都不泄露字段、不跨越版本边界、不把完整数据集过滤搬回主线程。

**不包含：** 新搜索集群、Elasticsearch/OpenSearch、第二搜索数据库、Node 搜索服务、无界 ORM 扫描、完整 ontology tree/inference UI、生产数据库迁移、框架或运行时升级、自动提交或部署。MiniSearch 不是既定依赖；只有实际仓库核验和 B-pre-ADR 容量证据同时满足时才可作为 Worker 实现细节引入。

**前置阻断条件：**

1. **C 阻断：** Plan C 必须交付并验证 `rl_public_projection_schema`、字段 allowlist、敏感字段扫描、immutable artifact digest、manifest membership、ready marker、artifact capability profile、publication approval、pointer CAS/fencing、CDN/static route 和恢复/unknown 证据。D 不重复实现 C 的发布安全边界，也不得读取未通过 `artifact_ready` 的资源。
2. **B-pre-ADR 阻断：** 必须固定大豆和第二物种 walking skeleton 的 `max_shards`、`max_documents`、单次 `limit`、API/Worker timeout、压缩/解压大小、Worker 内存上限、P50/P95 目标和静态目录分页边界。未固定前，不得选择引擎、扩大索引或宣称性能达标。
3. **A0/A1/B 阻断：** 必须有可追溯的 scope、dataset/publication、legacy mapping、capability、审计和 OpenAPI/client contract 证据。Internal Search 不能以当前 live ORM 结果替代已发布资源；External Search 不能写入本地事实。

---

## 1. 当前事实、目标边界与验收结果

### 1.1 已核对的仓库事实

以下事实来自实际文件，不把旧设计名词当作已实现能力：

| 领域 | 当前路径 | 当前行为 | D 阶段处理 |
|---|---|---|---|
| 旧路由 | `apps/api/app/api/v1/search.py` | `/search` 根据 `Accept`/`format` 在 PostgreSQL JSON 和外部 HTML 之间切换 | 保留兼容入口但弃用内容协商；新增显式 Internal/External 路由，兼容行为只走明确迁移策略 |
| 旧内部服务 | `apps/api/app/services/search_service.py` | live `Gene`、`MutantLine`、`Publication` ORM `ilike` 查询，自然顺序不稳定 | 不再作为新的 Internal provider；隔离为 legacy compatibility adapter，最终由 capability/迁移证据决定是否移除 |
| 外部聚合 | `apps/api/app/search/aggregator.py` | 并行调用 NCBI/UniProt/Ensembl/EBI，共享外部聚合代码 | 复用外部 adapter resilience 方向，但独立 route、schema、cache namespace、限流、timeout、breaker 和 provenance |
| 外部 resilience | `apps/api/app/search/adapters/base.py`, `cache.py`, `rate_limiter.py`, `circuit_breaker.py` | 已有 source-specific timeout/retry/cache/rate-limit/circuit-breaker 基础 | 修正命名空间、错误 envelope、Retry-After/limit headers 和 fail-open/closed 语义；不得让 Redis 成为事实源 |
| API schema | `apps/api/app/schemas/search.py` | `GlobalSearchResponse` 是旧的 generic hit/metadata contract | 新增 Internal/External schema；旧 schema 只作为兼容读取，不允许新公开字段通过 `metadata` 任意扩张 |
| client | `packages/api-client/src/search.ts` | 单一 `globalSearch()` 调 `/search` | 拆为 `rl_internalSearch()`、`rl_externalSearch()`、cursor/error/capability 类型和显式路径 |
| Worker | `apps/web/src/workers/search.worker.ts` | 接收任意 `unknown[]` 做 filter/sort | 改为只加载校验通过的 manifest-backed shards/index envelope；禁止传入完整主线程数据集 |
| Worker client | `apps/web/src/lib/search-worker-client.ts` | Worker 不可用时在主线程过滤/排序传入数组 | 删除完整数据集 main-thread fallback；失败改为 Internal API，再失败静态 directory |
| SSG | `apps/web/scripts/ssg-build.ts` | 生成固定 page/widget shell，没有统一 search manifest/generation | 消费 Plan C 已验证的 registered immutable SearchManifest，输出目录入口/分页链接和 release-bound envelope |
| Web route | `apps/web/src/routes/search.tsx` | 当前只渲染旧 api-client global search 与 expression search | 分出 Internal/External sections、scope ledger、provenance、fallback 和精确 capability/error 状态 |
| 测试 | `apps/api/scripts/test_core.py`, `apps/api/tests`, `packages/api-client/src/*.test.ts`, `tests/e2e/search.spec.ts` | 有旧外部 renderer/client/E2E smoke，缺少双系统隔离和字段泄漏测试 | 先写失败测试，再实现；保留不冲突的旧 renderer 回归测试并新增 contract/fixture suites |
| MiniSearch | `apps/web/package.json`, `package.json`, `packages/api-client/package.json` | 当前 package manifests 未发现 `minisearch` | 先核验 lockfile/node_modules/包导入；仅在 B-pre-ADR 允许且实际核验通过后 gated install，不能顺手升级或添加替代引擎 |

### 1.2 目标请求流

```text
公开 /search 页面
  ├─ Worker：加载已发布 SearchManifest → 校验 digest/schema/config/capability
  │       ├─ 成功：bounded shard/index query → Internal envelope
  │       └─ 失败：不在主线程过滤完整数据集
  ├─ Internal API：GET /search/internal
  │       ├─ 只读 manifest 引用的公开规范化 shards
  │       └─ bounded error / static directory link
  ├─ External API：GET /search/external
  │       ├─ allowlist source adapter fan-out
  │       └─ source-isolated cache/rate-limit/timeout/circuit/provenance
  └─ JS/Worker/API 均不可用：versioned static directory/index page
```

**硬边界：** Internal 与 External 不共享结果列表、缓存 key、错误状态、比较资格、版本语义或 provider registry。它们可以共享公开 envelope 的字段命名约定，但不得共享可变实现对象。External timeout/circuit-open 只能影响对应 source 或 External section，不能改变 Internal 结果。

### 1.3 D 的完成定义

- Internal route 不访问 `SearchService` 的 live ORM 查询；provider 只读取已发布 SearchManifest 声明的有限 shards。
- Internal rank tier 固定为：`exact stable ID` → `stable-ID prefix` → `exact alias` → `title match` → `summary/body match`。同 tier 依次按 `canonical_url`、必要时 `object_type`、`stable_id` 做确定性 tie-break。
- Internal cursor 是签名 continuation token，绑定 publication manifest digest、scope、canonical query、filter、sort schema、limit 和 provider version；任一绑定变化都返回 `invalid_cursor`。
- Public result envelope 包含 `publication_release_id`、dataset scope、`scope_type`/scope ledger、stable public ID、canonical URL、provenance、result origin、match explanation、comparison/export eligibility、manifest digest；不包含 internal object ID、bucket/key、internal URI、presigned URL、upload/session/secret、unpublished diagnostic/approval identity。
- External route 只允许 `ncbi`、`uniprot`、`ensembl`、`ebi` 等服务端登记 source；不接受任意 URL、adapter name 或 headers。每个 source 有独立 timeout、cache、rate-limit、circuit-breaker 和错误状态。
- Worker 只处理公开索引/文档的 bounded payload。Worker crash、hash mismatch、schema mismatch、memory/size ceiling 或 capability 缺失均按 Worker → Internal API → static directory 回退；**永不**把完整 dataset 送给主线程做过滤。
- API client 公开 Internal/External 分离函数和 discriminated error/capability types；消费者不能通过旧 `globalSearch()` 继续隐式选择搜索系统。
- 字段 allowlist、旧字段泄漏、跨 publication cursor、scope mismatch、外部故障隔离、性能/上限和无 JS 目录均有自动化测试与命令证据。

---

## 2. 契约先行：schemas、envelope、scope 与错误

### 2.1 目录与模块布局

在 A0/B/C 证据允许后新增以下模块。所有自有业务符号使用 `rl_` 前缀；FastAPI route function、Pydantic field alias、第三方 adapter protocol 和现有公共兼容接口可按框架/协议保留既有名称。

```text
apps/api/app/search/
  internal/
    __init__.py
    contracts.py          # SearchManifest/Document/Envelope/Cursor types
    manifest_provider.py  # bounded manifest-backed provider
    cursor.py             # signed cursor encode/decode/binding validation
    projection.py         # public allowlist projection
    service.py            # short request orchestration, no ORM scan
  external/
    __init__.py
    contracts.py          # external request/result/source capability types
    service.py            # isolated allowlist fan-out
    provenance.py         # public provenance projection
  compatibility.py        # old /search mapping/deprecation diagnostics
apps/api/app/api/v1/
  search_internal.py
  search_external.py
apps/api/app/schemas/
  search_internal.py
  search_external.py
apps/api/tests/
  test_internal_search_contracts.py
  test_internal_search_provider.py
  test_search_cursor.py
  test_public_projection_leakage.py
  test_external_search_isolation.py
  fixtures/search_manifests.py
apps/web/src/workers/
  search.worker.ts        # manifest-backed worker envelope only
apps/web/src/lib/
  search-worker-client.ts # Worker → API → directory state machine
  search-search-manifest.ts
apps/web/src/routes/
  search.tsx              # consumer sections and capability errors
apps/web/scripts/
  build-search-shards.ts  # deterministic publication builder hook
  search-publication-fixture.ts
packages/api-client/src/
  search-internal.ts
  search-external.ts
  search.ts               # compatibility exports/deprecation only
packages/api-client/src/*.test.ts
  search-internal.test.ts
  search-external.test.ts
```

为什么：Internal provider、External adapter 和公开投影如果继续放在 `app/search` 的同一调用入口，未来很容易复用错误的缓存/错误/权限语义；目录级隔离把不应共享的依赖变成可检查边界。

### 2.2 Python 代表性契约代码

以下代码是实施时的完整代表性骨架；实际字段名必须与 Plan C 的 validated manifest/schema 对齐，不能把示例字段直接当作未核验数据库迁移。

```python
# apps/api/app/search/internal/contracts.py
from __future__ import annotations

from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class rl_scope_type(StrEnum):
    SPECIES = "species"
    ASSEMBLY = "assembly"
    DATASET = "dataset"
    PUBLICATION = "publication"


class rl_scope_level(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: rl_scope_type
    public_id: str | None = None
    label: str | None = None
    availability: Literal["available", "unavailable", "not_applicable"]
    canonical_url: str | None = None


class rl_scope_ledger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applicable_levels: list[rl_scope_type]
    levels: list[rl_scope_level]
    explanation: str


class rl_provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_namespace: str
    source_version: str
    license_id: str
    citation: str | None = None
    public_artifact_digest: str
    canonical_url: str


class rl_search_document(BaseModel):
    """Only fields already approved by rl_public_projection_schema."""

    model_config = ConfigDict(extra="forbid")

    stable_id: str
    object_type: str
    canonical_url: str
    title: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    body: str = ""
    publication_release_id: str
    dataset_scope: str
    scope_ledger: rl_scope_ledger
    provenance: rl_provenance
    comparison_eligible: bool = False
    export_eligible: bool = False


class rl_search_manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    provider_version: str
    publication_release_id: str
    manifest_digest: str
    scope_ledger: rl_scope_ledger
    max_shards: int = Field(gt=0)
    max_documents: int = Field(gt=0)
    shard_urls: list[str]
    shard_digests: dict[str, str]
    public_projection_schema: str
    index_config_digest: str


class rl_match_explanation(BaseModel):
    tier: Literal[
        "exact_stable_id",
        "stable_id_prefix",
        "exact_alias",
        "title_match",
        "summary_body_match",
    ]
    matched_field: str


class rl_internal_result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    publication_release_id: str
    dataset_scope: str
    stable_id: str
    object_type: str
    canonical_url: str
    scope_ledger: rl_scope_ledger
    provenance: rl_provenance
    result_origin: Literal["internal_manifest"]
    match_explanation: rl_match_explanation
    comparison_eligible: bool
    export_eligible: bool


class rl_internal_search_response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    results: list[rl_internal_result]
    next_cursor: str | None
    publication_release_id: str
    manifest_digest: str
    scope_ledger: rl_scope_ledger
    provider_version: str
    bounded: bool = True


class rl_search_error(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "invalid_cursor",
        "manifest_unavailable",
        "manifest_mismatch",
        "scope_mismatch",
        "bounded_limit_exceeded",
        "bounded_shard_limit_exceeded",
        "worker_capability_missing",
        "external_source_not_allowed",
        "external_timeout",
        "external_circuit_open",
        "external_rate_limited",
    ]
    message: str
    retryable: bool
    static_directory_url: str | None = None
    provider: str | None = None
```

实现要求：

- `extra="forbid"` 只解决契约层结构扩张，不替代 Plan C 的 publication allowlist；projection 仍必须从内部构造逐字段创建 `rl_search_document`/`rl_internal_result`。
- `scope_ledger` 的 `unavailable` 与 `not_applicable` 必须显式返回。不能因为当前文档只有 species scope 就默认填充 assembly/dataset/publication。
- `result_origin="internal_manifest"` 与 External 的 `result_origin="external_source"` 是不同枚举空间，不允许统一成模糊的 `search`。
- `manifest_digest`、`publication_release_id` 和 `scope_ledger` 从同一冻结 manifest 生成；禁止 API 在请求时拼出当前数据库的“最新”值。

### 2.3 External 契约

```python
# apps/api/app/search/external/contracts.py
from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class rl_external_source(StrEnum):
    NCBI = "ncbi"
    UNIPROT = "uniprot"
    ENSEMBL = "ensembl"
    EBI = "ebi"


class rl_external_source_status(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMITED = "rate_limited"


class rl_external_request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    sources: list[rl_external_source] = Field(min_length=1, max_length=4)
    limit_per_source: int = Field(default=8, ge=1, le=10)


class rl_external_public_provenance(BaseModel):
    """Fixed public DTO; provider raw metadata never crosses this boundary."""

    model_config = ConfigDict(extra="forbid")

    source_namespace: str
    source_version: str
    license_id: str
    citation: str | None = None
    canonical_url: str
    public_artifact_digest: str | None = None


class rl_external_hit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: rl_external_source
    public_id: str
    title: str
    canonical_url: str
    snippet: str
    provenance: rl_external_public_provenance
    result_origin: Literal["external_source"]


class rl_external_source_result(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: rl_external_source
    status: rl_external_source_status
    hits: list[rl_external_hit]
    elapsed_ms: float = Field(ge=0)
    error_code: str | None = None
    retry_after_seconds: int | None = Field(default=None, ge=0)


class rl_external_response(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    sources: list[rl_external_source_result]
    total_hits: int = Field(ge=0)
    elapsed_ms: float = Field(ge=0)
    isolated_from_internal: Literal[True] = True
```

External adapter input必须来自 `_EXTERNAL_SOURCE_REGISTRY` 的静态服务端 mapping。请求不可提交 URL、method、headers、cache key、timeout 或 adapter class。`rl_external_public_provenance` 只允许固定的 public source/version/license/citation/canonical URL/digest 字段；`extra="forbid"` 明确拒绝 provider raw metadata、内部 diagnostics、内部请求 URL、Redis key、presigned URL 和 token。不能把这些值通过 `extra`、嵌套对象或错误 envelope 传给客户端。

---

## 3. Internal Search：manifest-backed、bounded、确定性

### 3.1 Manifest provider 和读取边界

实现 `apps/api/app/search/internal/manifest_provider.py`，输入只接受已注册的 publication manifest/artifact IDs 或 Plan C provider adapter 返回的 immutable public URL。它必须：

1. 校验 `manifest_digest`、`public_projection_schema`、`provider_version`、`index_config_digest` 和每个 shard digest；校验失败返回 `manifest_mismatch`/`manifest_unavailable`，不回退 ORM。
2. 校验请求 scope 是 manifest 的子范围且 publication/dataset/assembly 不冲突；不匹配返回 `scope_mismatch`。
3. 在 B-pre-ADR 固定的 `max_shards`、`max_documents`、timeout 和 response limit 内读取；不得递归发现对象、列举 bucket、读取“当前目录”或扫描 PostgreSQL。
4. 对 shard 读取设置总请求 deadline；单个 shard 失败按 bounded error 处理，并返回静态目录链接；不把部分未知结果伪装为完整结果。
5. 将 cache（若采用）绑定 `manifest_digest + scope + canonical query + filter + sort schema + provider version`，并使用与 External 完全不同的 key prefix。Internal cache 只能加速 immutable resource read，不能决定 publication truth。
6. 静态目录 fallback 只能由已验证 SearchManifest 或服务端创建的 bounded error envelope 提供；该引用必须同时绑定 `publication_release_id`、`manifest_digest`、请求 scope 和 `public_projection_schema`。客户端不能提交、覆盖或拼接 `staticDirectoryUrl`。

代表性 provider 接口：

```python
# apps/api/app/search/internal/manifest_provider.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    rl_internal_search_response,
    rl_search_document,
    rl_search_manifest,
)
from .cursor import rl_cursor_binding, rl_decode_cursor, rl_encode_cursor


@dataclass(frozen=True)
class rl_internal_query:
    query: str
    scope: str
    filters: tuple[tuple[str, str], ...]
    sort_schema: str
    limit: int
    cursor: str | None


class rl_public_shard_store(Protocol):
    async def read_manifest(self, manifest_id: str) -> rl_search_manifest: ...

    async def read_shards(
        self,
        manifest: rl_search_manifest,
        query: rl_internal_query,
    ) -> list[rl_search_document]: ...


class rl_manifest_backed_provider:
    def __init__(self, rl_store: rl_public_shard_store, rl_limits: dict[str, int | float]) -> None:
        self.rl_store = rl_store
        self.rl_limits = rl_limits

    async def search(
        self,
        rl_manifest_id: str,
        rl_query: rl_internal_query,
    ) -> rl_internal_search_response:
        if rl_query.limit > int(self.rl_limits["limit_max"]):
            raise ValueError("bounded_limit_exceeded")
        rl_manifest = await self.rl_store.read_manifest(rl_manifest_id)
        # 为什么：cursor 密钥只能由服务端 key provider 注入，不能从浏览器请求取得。
        rl_cursor_state = rl_decode_cursor(
            rl_query.cursor,
            rl_manifest,
            rl_query,
            rl_secret=self.rl_limits["cursor_secret"],
        )
        rl_documents = await self.rl_store.read_shards(rl_manifest, rl_query)
        rl_ranked = rl_rank_documents(rl_documents, rl_query.query)
        rl_page = rl_apply_cursor_and_limit(rl_ranked, rl_cursor_state, rl_query.limit)
        rl_next = None
        if len(rl_page) == rl_query.limit and rl_page:
            rl_next = rl_encode_cursor(
                rl_manifest=rl_manifest,
                rl_query=rl_query,
                rl_last=rl_page[-1],
                rl_secret=self.rl_limits["cursor_secret"],
            )
        return rl_build_public_response(rl_manifest, rl_page, rl_next)


def rl_rank_documents(
    rl_documents: list[rl_search_document],
    rl_query: str,
) -> list[tuple[tuple[int, str, str, str], rl_search_document, str]]:
    rl_q = rl_query.strip().casefold()
    rl_rows: list[tuple[tuple[int, str, str, str], rl_search_document, str]] = []
    for rl_document in rl_documents:
        rl_id = rl_document.stable_id.casefold()
        rl_aliases = {rl_alias.casefold() for rl_alias in rl_document.aliases}
        rl_title = rl_document.title.casefold()
        rl_text = f"{rl_document.summary} {rl_document.body}".casefold()
        if rl_q == rl_id:
            rl_tier, rl_field = 0, "stable_id"
        elif rl_id.startswith(rl_q):
            rl_tier, rl_field = 1, "stable_id"
        elif rl_q in rl_aliases:
            rl_tier, rl_field = 2, "alias"
        elif rl_q in rl_title:
            rl_tier, rl_field = 3, "title"
        elif rl_q in rl_text:
            rl_tier, rl_field = 4, "summary_body"
        else:
            continue
        # 为什么：排序键必须完整且与 cursor 相同，避免数据库/对象存储自然顺序造成翻页漂移。
        rl_sort_tuple = (rl_tier, rl_document.canonical_url, rl_document.object_type, rl_document.stable_id)
        rl_rows.append((rl_sort_tuple, rl_document, rl_field))
    return sorted(rl_rows, key=lambda rl_row: rl_row[0])
```

上述骨架中的 `rl_store` 具体实现必须调用 C 已验证的 object-store/CDN capability adapter，而不是直接让 API 读取任意用户输入的路径。`rl_build_public_response` 必须通过 `rl_public_projection_schema` allowlist 构造结果；不允许 `model_dump()` 一个内部 ORM/artifact 对象再删字段。

### 3.2 精确 rank tiers 与 tie-break

固定排序 tuple 为：

```text
(tier, canonical_url, object_type, stable_id)
```

其中 `tier` 为：

```text
0 exact stable ID
1 stable-ID prefix
2 exact alias
3 title match
4 summary/body match
```

同一文档不得重复占据多个结果；取最低 tier。`canonical_url` 是首个 tie-break，`object_type` 和 `stable_id` 只在前项相同的情况下继续比较。不得按浮点 MiniSearch score、对象写入顺序、Python dict 顺序、PostgreSQL natural order 或 shard 顺序宣称长期稳定排名。Worker 可以支持额外 fuzzy/prefix 体验，但 API contract 只保证上述 tier 和 tuple；Worker envelope 必须标出 `ranking_profile`，不伪称与 API 完全相同。

### 3.3 签名 cursor

cursor payload 至少包含：

```json
{
  "v": 1,
  "provider_version": "internal-manifest-v1",
  "manifest_digest": "sha256:...",
  "publication_release_id": "...",
  "scope": "species:soybean/dataset:...",
  "canonical_query": "glyma",
  "filters": [["object_type", "gene"]],
  "sort_schema": "tier,url,type,stable_id:asc",
  "limit": 20,
  "last_sort_tuple": [1, "/species/...", "gene", "Glyma.01G001000"],
  "issued_at": 1784450000
}
```

签名实现必须使用服务端配置的 key reference，不把 secret 写入 repository、manifest、日志或 public URL。编码可用 URL-safe base64，签名可用 HMAC-SHA256；密钥轮换时保留验证 key ID 的短窗口并让已过期/不再保留的 manifest 明确失效。签名验证后逐项比较绑定字段；只有 `canonical_query`、filter、sort、limit、scope、provider version 和 manifest digest 全部一致，才可解释 `last_sort_tuple`。

```python
# apps/api/app/search/internal/cursor.py
import base64
import hashlib
import hmac
import json
from typing import Any


def rl_canonical_json(rl_value: dict[str, Any]) -> bytes:
    return json.dumps(rl_value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def rl_encode_cursor(*, rl_manifest, rl_query, rl_last, rl_secret: bytes) -> str:
    rl_payload = {
        "v": 1,
        "provider_version": rl_manifest.provider_version,
        "manifest_digest": rl_manifest.manifest_digest,
        "publication_release_id": rl_manifest.publication_release_id,
        "scope": rl_query.scope,
        "canonical_query": rl_query.query.strip().casefold(),
        "filters": list(rl_query.filters),
        "sort_schema": rl_query.sort_schema,
        "limit": rl_query.limit,
        "last_sort_tuple": list(rl_last[0]),
    }
    rl_body = rl_canonical_json(rl_payload)
    rl_sig = hmac.new(rl_secret, rl_body, hashlib.sha256).hexdigest()
    rl_token = {"payload": rl_payload, "sig": rl_sig}
    return base64.urlsafe_b64encode(rl_canonical_json(rl_token)).decode("ascii").rstrip("=")


def rl_decode_cursor(rl_cursor, rl_manifest, rl_query, rl_secret: bytes):
    if not rl_cursor:
        return None
    try:
        rl_raw = base64.urlsafe_b64decode(rl_cursor + "=" * (-len(rl_cursor) % 4))
        rl_token = json.loads(rl_raw)
        rl_payload = rl_token["payload"]
        rl_expected = hmac.new(rl_secret, rl_canonical_json(rl_payload), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(rl_token["sig"], rl_expected):
            raise ValueError("invalid_cursor")
        rl_expected_binding = {
            "provider_version": rl_manifest.provider_version,
            "manifest_digest": rl_manifest.manifest_digest,
            "publication_release_id": rl_manifest.publication_release_id,
            "scope": rl_query.scope,
            "canonical_query": rl_query.query.strip().casefold(),
            "filters": list(rl_query.filters),
            "sort_schema": rl_query.sort_schema,
            "limit": rl_query.limit,
        }
        if any(rl_payload.get(rl_key) != rl_value for rl_key, rl_value in rl_expected_binding.items()):
            raise ValueError("invalid_cursor")
        return tuple(rl_payload["last_sort_tuple"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as rl_error:
        raise ValueError("invalid_cursor") from rl_error
```

实施时不要把 `rl_secret` 作为 FastAPI query dependency 从用户请求传入；由 server-side key provider 注入。测试必须覆盖签名篡改、manifest 切换、scope/filter/sort/limit/query 变化、过期 key、未知 version 和 malformed token。

---

## 4. External Search：allowlist、缓存、限流、timeout、熔断隔离

### 4.1 route 与 adapter registry

新增 `apps/api/app/api/v1/search_external.py`，建议路径为 `GET /api/v1/search/external`；新增 `apps/api/app/api/v1/search_internal.py`，建议路径为 `GET /api/v1/search/internal`。两个 router 分别 include 到 `apps/api/app/api/v1/router.py`，并在 OpenAPI 中使用独立 tags、schemas 和 error responses。

External source registry 必须是服务端固定 allowlist：

```python
# apps/api/app/search/external/service.py
from dataclasses import dataclass
from typing import Final

from ..adapters import EBIAdapter, EnsemblAdapter, NCBIAdapter, UniProtAdapter
from .contracts import rl_external_source


@dataclass(frozen=True)
class rl_external_provider_spec:
    source: rl_external_source
    adapter_factory: object
    timeout_seconds: float
    cache_ttl_seconds: int
    limit_max: int


RL_EXTERNAL_PROVIDER_REGISTRY: Final = {
    rl_external_source.NCBI: rl_external_provider_spec(
        rl_external_source.NCBI, NCBIAdapter, 5.0, 300, 10
    ),
    rl_external_source.UNIPROT: rl_external_provider_spec(
        rl_external_source.UNIPROT, UniProtAdapter, 5.0, 300, 10
    ),
    rl_external_source.ENSEMBL: rl_external_provider_spec(
        rl_external_source.ENSEMBL, EnsemblAdapter, 5.0, 300, 10
    ),
    rl_external_source.EBI: rl_external_provider_spec(
        rl_external_source.EBI, EBIAdapter, 5.0, 300, 10
    ),
}


def rl_get_allowed_provider(rl_source: rl_external_source) -> rl_external_provider_spec:
    try:
        return RL_EXTERNAL_PROVIDER_REGISTRY[rl_source]
    except KeyError as rl_error:
        raise ValueError("external_source_not_allowed") from rl_error
```

查询参数只包括 `query`、重复/逗号规范化后的 allowlisted `sources` 和 bounded `limit_per_source`。不允许用户指定 `source_url`、`adapter`、`timeout`、`cache_ttl`、HTTP headers 或 provider query DSL。任何未知 source 返回 400 `external_source_not_allowed`，而不是忽略后默默访问默认来源。

### 4.2 资源隔离规则

- **缓存：** External key 由环境、source、adapter version、canonical query、limit 和 public response schema 组成，例如 `external-search:v1:{env}:{source}:{sha256}`。禁止复用 `SearchCache.make_key()` 的旧 `search:` prefix；Internal 使用 `internal-search:v1:`，旧 HTML cache 使用 `legacy-search-html:` 并设迁移 TTL。缓存只存 normalized public result，不能存 provider secret、raw unrestricted response 或内部 error。
- **限流：** 继续使用 `apps/api/app/search/rate_limiter.py` 的 Redis token bucket，但 key 必须含 environment/source/operation，响应在 source 被拒绝时返回 `Retry-After`、`X-RateLimit-Limit`、`X-RateLimit-Remaining`（若可安全计算）。Redis 不可用时的 fail-open/closed 必须按 source policy 明确测试；高风险 outbound source 不得无限 fail-open。
- **timeout：** 每 source timeout、aggregate deadline 和 client timeout 独立配置但固定在服务端；timeout 只返回该 source 的 `external_timeout`，不能拖慢 Internal。禁止为 External 使用 `packages/api-client` 的默认 30s critical timeout；浏览器 External 请求采用较短的 non-critical preset，并支持 abort。
- **circuit breaker：** 复用 `apps/api/app/search/circuit_breaker.py` 的 CLOSED/OPEN/HALF_OPEN 语义；每 source 独立 key。HTTP 5xx、transport error、timeout 计 failure；用户输入导致的 4xx 不应 trip；breaker open 只标记该 source `external_circuit_open`。HALF_OPEN 只允许 bounded probe，必须测试并发 probe 不放大故障。
- **retry：** 只对 connect/read/remote protocol 以及 429/5xx 做 bounded retry；每次 retry 仍受 aggregate deadline，不能在 timeout 后重新开启无限任务。query 不变时可读 normalized cache；缓存命中不触发 outbound breaker success/failure 假象。
- **provenance：** adapter 返回 source、public version/release（若来源提供）、license/citation/canonical URL 和 stable public accession；`extra` 只能通过 allowlist projection，不能直接 `model_dump()` 到 API。
- **failure isolation：** External response 允许 `OK`、`EMPTY`、`TIMEOUT`、`ERROR`、`CIRCUIT_OPEN`、`RATE_LIMITED` 并存；Internal response 完全不包含这些 source statuses。External 全部失败时页面仍保留 Internal 和 static directory。

### 4.3 旧 `/search` 弃用策略

`apps/api/app/api/v1/search.py` 不再依据 `Accept` 在两个系统间选择。过渡期保留 `/search` 作为兼容路由：

- `?format=json` 或 `Accept: application/json` 明确映射到 **Internal legacy compatibility response**，但内部实现只能调用新 Internal service，并在 response header 增加 `Deprecation`/`Sunset`（具体日期由产品确认，不在计划中猜定）。
- `text/html` 不再隐藏地代表 External；旧 HTML consumer 改为调用 `/search/external`，兼容路由返回明确的 migration error 或受控旧 renderer，且不能将 External 结果拼进 Internal JSON。
- 新页面、Worker、api-client、E2E 不得再依赖旧 content negotiation。旧函数保留期间必须有调用清单和测试，避免“兼容”成为永久混合入口。
- `apps/api/app/services/search_service.py` 的 live ORM 查询只能保留给旧接口的明确兼容窗口；任何新 Internal endpoint 一旦检测到 provider manifest 缺失，返回 `manifest_unavailable` + directory link，不调用它。

---

## 5. Public projection、字段泄漏与 provenance

### 5.1 公开投影的实现顺序

1. 读取 C 已验证的 versioned `rl_public_projection_schema` 与 capability profile。
2. 先从 manifest-backed `rl_search_document` 构造公开 `rl_internal_result`；只拷贝 allowlist 中的 stable ID、object type、canonical URL、公开标题/摘要、scope ledger、public provenance 和 eligibility。
3. 对每个结果执行结构扫描作为 defense-in-depth，检查字符串/URL/嵌套值不能出现 internal object ID、bucket/key、`s3://`/internal URI、presigned query token、upload session、secret/token、unpublished source/diagnostic、approval identity、restricted policy detail。
4. 对 External adapter 使用独立 projection；第三方 raw JSON 永远不能直接透传。
5. 将 projection schema version、manifest digest 和 origin 写入 envelope；任何 schema/hash mismatch 阻断 artifact/response，转 API/static fallback。

### 5.2 必须失败的泄漏测试样例

```python
# apps/api/tests/test_public_projection_leakage.py
import pytest


@pytest.mark.parametrize(
    "rl_forbidden",
    [
        "internal_object_id",
        "bucket/key",
        "s3://private-bucket/object",
        "https://cdn.example/x?X-Amz-Signature=secret",
        "upload_session_id",
        "secret-token",
        "unpublished-diagnostic",
        "approval_identity@example.org",
    ],
)
def test_rl_public_search_projection_rejects_forbidden_fields(rl_forbidden, rl_public_document_factory):
    rl_document = rl_public_document_factory(injected_value=rl_forbidden)
    with pytest.raises(ValueError, match="public_projection"):
        rl_project_public_result(rl_document)


def test_rl_scope_ledger_marks_non_applicable_levels_explicitly(rl_public_document_factory):
    rl_result = rl_project_public_result(rl_public_document_factory(scope_type="species"))
    rl_levels = {rl_level.scope_type: rl_level.availability for rl_level in rl_result.scope_ledger.levels}
    assert rl_levels["species"] == "available"
    assert rl_levels["assembly"] in {"unavailable", "not_applicable"}
    assert rl_levels["dataset"] in {"unavailable", "not_applicable"}
```

目录 fallback 的 envelope 也必须是固定、服务端产生的 DTO；客户端只携带 opaque manifest reference 和 query，不携带 URL：

```python
class rl_verified_static_directory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    publication_release_id: str
    manifest_digest: str
    scope: str
    projection_schema: str


class rl_bounded_search_error(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Literal["manifest_unavailable", "bounded_limit_exceeded", "worker_capability_missing"]
    message: str
    publication_release_id: str
    manifest_digest: str
    scope: str
    projection_schema: str
    static_directory: rl_verified_static_directory


def rl_verify_static_directory(
    rl_directory: rl_verified_static_directory,
    rl_manifest: rl_search_manifest,
    rl_scope: str,
) -> rl_verified_static_directory:
    # 为什么：目录跳转属于当前 publication 的公开投影，不允许请求参数改变其版本或路径。
    if (
        rl_directory.publication_release_id != rl_manifest.publication_release_id
        or rl_directory.manifest_digest != rl_manifest.manifest_digest
        or rl_directory.scope != rl_scope
        or rl_directory.projection_schema != rl_manifest.public_projection_schema
        or not rl_is_registered_public_directory(rl_directory.url, rl_manifest)
    ):
        raise ValueError("public_static_directory_binding_invalid")
    return rl_directory
```

代表性拒绝测试必须覆盖伪造任意 URL、跨 publication/digest/scope/projection schema、internal URL、bucket/key、presigned URL，以及客户端试图注入或覆盖 directory 字段：

```python
@pytest.mark.parametrize(
    "rl_forged_url",
    [
        "https://attacker.example/collect",
        "/directory?publication=other-release",
        "/internal/admin/search",
        "s3://private-bucket/search/index.json",
        "https://cdn.example/directory?X-Amz-Signature=secret",
    ],
)
def test_rl_static_directory_requires_verified_same_manifest(
    rl_forged_url, rl_search_manifest_factory, rl_verified_directory_factory
):
    rl_manifest = rl_search_manifest_factory(
        publication_release_id="pub-a",
        manifest_digest="sha256:a",
        public_projection_schema="rl-public-search-v1",
    )
    rl_directory = rl_verified_directory_factory(
        url=rl_forged_url,
        publication_release_id="pub-a",
        manifest_digest="sha256:a",
        scope="species:glycine-max",
        projection_schema="rl-public-search-v1",
    )
    with pytest.raises(ValueError, match="public_static_directory"):
        rl_verify_static_directory(rl_directory, rl_manifest, "species:glycine-max")


def test_rl_client_cannot_supply_directory_or_arbitrary_manifest_url(rl_internal_request_type, rl_worker_request_type):
    assert "staticDirectoryUrl" not in rl_internal_request_type.__annotations__
    assert "manifestUrl" not in rl_worker_request_type.__annotations__
    with pytest.raises(ValueError, match="registered_manifest_ref"):
        rl_resolve_manifest_reference("/var/data/search.json")
```

External provenance 的固定 DTO 同样需要结构化拒绝测试：

```python
@pytest.mark.parametrize(
    "rl_forbidden_field",
    [
        {"provider_raw": {"debug": "raw"}},
        {"internal_diagnostic": "traceback"},
        {"provider_request_url": "https://upstream/?token=secret"},
        {"bucket_key": "private/key"},
        {"presigned_url": "https://cdn/?X-Amz-Signature=secret"},
    ],
)
def test_rl_external_provenance_dto_forbids_raw_provider_fields(rl_forbidden_field):
    with pytest.raises(ValidationError):
        rl_external_public_provenance(
            source_namespace="uniprot",
            source_version="2026-01",
            license_id="CC-BY-4.0",
            canonical_url="https://www.uniprot.org/uniprotkb/P12345",
            **rl_forbidden_field,
        )
```

实际 fixture 必须覆盖 `Gene`/`Transcript`/`Variant`/`MutantLine`/`Publication` 以及 External source raw payload。测试不应只断言几个字段不存在，还应检查 `extra`、metadata、URL query、nested provenance、serialized MiniSearch docs、static directory JSON 和 API envelope 的 JSON 全树。

### 5.3 Comparison/export eligibility

Internal 结果的 `comparison_eligible`/`export_eligible` 由 manifest 的公开 capability/eligibility 冻结值决定；Worker 不得因本地字段存在自行把 false 改为 true。External hits 默认不具备本地比较资格，除非未来有明确、独立批准的 cross-source mapping contract；D 不实现自动合并或本地事实写入。

---

## 6. Build-time MiniSearch shards 与 Worker envelope

### 6.1 依赖核验和 gated install

在任何 `pnpm add` 之前执行以下只读核验：

```bash
test -f apps/web/package.json
test -f apps/web/pnpm-lock.yaml
rg -n '(^|["/])minisearch(["@/]|$)|MiniSearch' \
  package.json apps/web/package.json packages/*/package.json apps/web/pnpm-lock.yaml \
  || true
test -d node_modules/minisearch && node -p "require('./node_modules/minisearch/package.json').version" || true
test -d apps/web/node_modules/minisearch && node -p "require('./apps/web/node_modules/minisearch/package.json').version" || true
```

**Expected before a gated install：** 当前已核对的 root `package.json`、`apps/web/package.json` 和 `packages/api-client/package.json` 没有 `minisearch`，当前 `apps/web/pnpm-lock.yaml` 需要按命令结果记录是否已有 transitive entry；不能从设计文档推断安装状态。

只有以下条件全部满足才允许添加依赖：

1. B-pre-ADR 证明 bounded MiniSearch Worker 在固定 shard/doc/memory/P95 ceilings 内可接受；
2. C 已验证 SearchManifest、public projection、immutable shard artifact、digest/ready marker 和 route capability；
3. 现有 package/lockfile 核验确认不存在可复用的已批准 MiniSearch 依赖；
4. 单独 dependency decision/ADR 记录版本、license、bundle/memory 影响、兼容测试和回滚；
5. 只向 `apps/web/package.json` 添加固定兼容版本并用 `pnpm --filter @soymutdb/web add minisearch@<approved-version>` 更新其 lockfile；不得同时升级 Node/Vite/React/其他依赖；
6. 依赖安装前后执行 diff，确认只影响 `apps/web/package.json`、`apps/web/pnpm-lock.yaml`（以及必要的 workspace lock 记录），并在本计划之外保留审批证据。

如果 MiniSearch 已在 lockfile/node_modules 中存在但未在 manifest 声明，先判断是可清理的 transitive 依赖还是已有 package contract；不得直接 import。若 B-pre-ADR 未达到边界，D 使用自有轻量的 bounded document scan **仅在 Worker 内**，或直接 API/directory fallback；不为替代引擎添加依赖。

### 6.2 SearchManifest 与构建

在 `apps/web/scripts/build-search-shards.ts`（或 C 已注册的生成入口）实现确定性输入：

- 只读取 C/B 批准的 dataset/publication snapshot，不读取 live mutable rows；
- stable ID、alias、title、summary/body、public URL、scope/provenance 等字段先通过 public projection schema；
- 以 `publication_release_id + manifest_digest + provider_version + index_config_digest` 绑定 shard/index；
- 按固定 species/assembly/dataset/object type/language 分片，排序用完整 `(canonical_url, object_type, stable_id)`；
- 每 shard 输出 JSON/压缩文档或 MiniSearch serialized index、digest、byte size、record count 和 capability；
- 在 staging immutable prefix 写入，完成 hash/size/schema/sensitive scan/manifest membership 后才由 C 负责 ready/promotion；D 不改 pointer；
- `MiniSearch` serialization 只作为 Worker implementation detail，不是长期公共 API。外层 envelope 必须含自有 schema/version/config/hash，未来可替换引擎而不破坏 consumer contract。

代表性 manifest envelope：

```json
{
  "schema_version": "rl-search-worker-v1",
  "provider_version": "internal-manifest-v1",
  "publication_release_id": "pub-2026-07-19-001",
  "manifest_digest": "sha256:abc...",
  "projection_schema": "rl-public-search-v1",
  "index_config_digest": "sha256:def...",
  "scope_ledger": {
    "applicable_levels": ["species", "assembly", "dataset", "publication"],
    "levels": [
      {"scope_type": "species", "public_id": "glycine-max", "availability": "available"},
      {"scope_type": "assembly", "public_id": "Glycine_max_v4", "availability": "available"},
      {"scope_type": "dataset", "public_id": "dataset-1", "availability": "available"},
      {"scope_type": "publication", "public_id": "pub-2026-07-19-001", "availability": "available"}
    ],
    "explanation": "Results are limited to the published Glycine max v4 dataset snapshot."
  },
  "limits": {"max_shards": 8, "max_documents": 50000, "limit_max": 50},
  "shards": [
    {"url": "/releases/pub-2026-07-19-001/search/gene-en-0.json.gz", "sha256": "...", "records": 1000}
  ],
  "static_directory": {
    "url": "/directory?publication=pub-2026-07-19-001",
    "publication_release_id": "pub-2026-07-19-001",
    "manifest_digest": "sha256:abc...",
    "scope": "species:glycine-max/assembly:Glycine_max_v4/dataset:dataset-1",
    "projection_schema": "rl-public-search-v1"
  }
}
```

### 6.3 Worker message contract

替换 `apps/web/src/workers/search.worker.ts` 的任意数组 filter/sort 消息为以下 envelope：

```ts
// apps/web/src/workers/search.worker.ts
type rl_worker_request = {
  type: "search";
  requestId: number;
  // Opaque server-created reference; the Worker resolves it only through the verified manifest registry.
  manifestRef: string;
  manifestDigest: string;
  query: string;
  scope: string;
  limit: number;
};

type rl_worker_response =
  | {
      type: "result";
      requestId: number;
      origin: "worker-manifest";
      manifestDigest: string;
      results: Array<{
        stable_id: string;
        object_type: string;
        canonical_url: string;
        publication_release_id: string;
        scope_ledger: unknown;
        provenance: unknown;
        match_explanation: unknown;
        comparison_eligible: boolean;
        export_eligible: boolean;
      }>;
      nextCursor: null;
    }
  | {
      type: "fallback";
      requestId: number;
      reason:
        | "manifest_unavailable"
        | "manifest_mismatch"
        | "projection_invalid"
        | "size_limit_exceeded"
        | "memory_limit_exceeded"
        | "worker_error";
      apiPath: "/search/internal";
      staticDirectory: {
        url: string;
        publication_release_id: string;
        manifest_digest: string;
        scope: string;
        projection_schema: string;
      };
  };
```

`manifestRef` 必须是服务端创建并签名/登记的 opaque reference，不能是 URL、bucket/key、文件路径或用户输入的任意字符串。Worker 只能向固定 manifest registry/API 解析该 reference，并验证返回的 publication release、manifest digest、scope、projection schema、shard URLs 和 static directory binding 全部一致；解析失败返回 `manifest_mismatch`/`manifest_unavailable`。Worker 只能 post public projected results。不能通过 `postMessage` 接收 `data: unknown[]`，不能执行 `JSON.stringify(item)` 全字段搜索，不能在 Worker 失败后把同一数组交给主线程。

### 6.4 Worker → API → static directory 状态机

在 `apps/web/src/lib/search-worker-client.ts` 实现：

```ts
export type rl_search_execution =
  | { source: "worker"; response: InternalSearchResponse }
  | { source: "internal-api"; response: InternalSearchResponse }
  | {
      source: "static-directory";
      staticDirectory: VerifiedStaticDirectory;
      reason: string;
    };

export async function rl_search_with_fallback(
  rl_request: InternalSearchRequest,
  rl_verified_manifest: VerifiedSearchManifest,
): Promise<rl_search_execution> {
  try {
    const rl_worker_response = await rl_run_worker(rl_request);
    if (rl_worker_response.type === "result") {
      return { source: "worker", response: rl_worker_responseToApiEnvelope(rl_worker_response) };
    }
  } catch (rl_worker_error) {
    // 为什么：Worker 不是授权层；校验失败必须回到服务端 contract，而不是扩大浏览器字段或主线程负担。
  }

  try {
    const rl_api_response = await rl_internalSearch(rl_request);
    return { source: "internal-api", response: rl_api_response };
  } catch (rl_api_error) {
    if (!rl_isBoundedFallbackError(rl_api_error)) throw rl_api_error;
  }

  return {
    source: "static-directory",
    // 为什么：目录 URL 必须来自已验证的同一 manifest，客户端不能伪造跨 publication 跳转。
    staticDirectory: rl_verified_manifest.staticDirectory,
    reason: "worker_and_internal_api_unavailable",
  };
}
```

这里的 API fallback 仍是 bounded manifest provider；它不是旧 `SearchService` 的 live database fallback。`VerifiedSearchManifest` 必须来自服务端/manifest verifier，并在消费前比较 `publication_release_id`、`manifest_digest`、scope 和 projection schema；若任一不一致，拒绝静态链接。`rl_run_worker` 的实现必须 terminate/recreate crashed Worker，限制 pending request 数量和总载荷；不可在 `fallbackProcess()` 中同步过滤大数组。现有 `filterSearchResults()`/`sortResults()` 公共函数若仍被其他页面使用，必须单独确认其数据规模和用途；不能把它重新用于 Internal full dataset search。

---

## 7. API client split 与消费者能力错误

### 7.1 新 client 文件

新增 `packages/api-client/src/search-internal.ts`：

```ts
import { http } from "./client";

export type InternalSearchRequest = {
  query: string;
  scope: string;
  types?: string[];
  filters?: Record<string, string>;
  sort?: string;
  limit?: number;
  cursor?: string;
};

export type rl_scope_type = "species" | "assembly" | "dataset" | "publication";

export type rl_scope_level = {
  scope_type: rl_scope_type;
  public_id?: string;
  label?: string;
  availability: "available" | "unavailable" | "not_applicable";
  canonical_url?: string;
};

export type rl_scope_ledger = {
  applicable_levels: rl_scope_type[];
  levels: rl_scope_level[];
  explanation: string;
};

export type rl_public_provenance = {
  source_namespace: string;
  source_version: string;
  license_id: string;
  citation?: string;
  public_artifact_digest: string;
  canonical_url: string;
};

export type VerifiedStaticDirectory = {
  url: string;
  publication_release_id: string;
  manifest_digest: string;
  scope: string;
  projection_schema: string;
};

export type VerifiedSearchManifest = {
  publication_release_id: string;
  manifest_digest: string;
  scope: string;
  projection_schema: string;
  staticDirectory: VerifiedStaticDirectory;
};

export type InternalSearchResponse = {
  query: string;
  results: Array<{
    publication_release_id: string;
    dataset_scope: string;
    stable_id: string;
    object_type: string;
    canonical_url: string;
    scope_ledger: rl_scope_ledger;
    provenance: rl_public_provenance;
    result_origin: "internal_manifest";
    match_explanation: { tier: string; matched_field: string };
    comparison_eligible: boolean;
    export_eligible: boolean;
  }>;
  next_cursor: string | null;
  publication_release_id: string;
  manifest_digest: string;
  scope_ledger: rl_scope_ledger;
  provider_version: string;
  bounded: true;
};

export function rl_internalSearch(
  rl_params: InternalSearchRequest,
): Promise<InternalSearchResponse> {
  return http.get<InternalSearchResponse>("/search/internal", {
    params: {
      query: rl_params.query,
      scope: rl_params.scope,
      types: rl_params.types,
      filters: rl_params.filters ? JSON.stringify(rl_params.filters) : undefined,
      sort: rl_params.sort,
      limit: rl_params.limit,
      cursor: rl_params.cursor,
    },
  });
}
```

在代表性代码中 `scope_ledger` 应在最终实现中引用共享的 `ScopeLedger` type，而不是示例中的 string alias；代码片段刻意保持 api-client 无运行时 schema dependency，真正的 runtime validation 可复用现有 `zod`（当前 `apps/web/package.json` 已有 `zod`）或由 response contract 测试覆盖，不能借此增加第三方包。

新增 `packages/api-client/src/search-external.ts`：

```ts
import { http } from "./client";

export type ExternalSource = "ncbi" | "uniprot" | "ensembl" | "ebi";

export type ExternalSearchRequest = {
  query: string;
  sources?: ExternalSource[];
  limitPerSource?: number;
  signal?: AbortSignal;
};

export type ExternalSourceResult = {
  source: ExternalSource;
  status: "ok" | "empty" | "timeout" | "error" | "circuit_open" | "rate_limited";
  hits: Array<{
    source: ExternalSource;
    public_id: string;
    title: string;
    canonical_url: string;
    snippet: string;
    provenance: rl_external_public_provenance;
    result_origin: "external_source";
  }>;
  elapsed_ms: number;
  error_code?: string;
  retry_after_seconds?: number;
};

export type rl_external_public_provenance = {
  source_namespace: string;
  source_version: string;
  license_id: string;
  citation?: string;
  canonical_url: string;
  public_artifact_digest?: string;
};

export type ExternalSearchResponse = {
  query: string;
  sources: ExternalSourceResult[];
  total_hits: number;
  elapsed_ms: number;
  isolated_from_internal: true;
};

export function rl_externalSearch(
  rl_params: ExternalSearchRequest,
): Promise<ExternalSearchResponse> {
  return http.get<ExternalSearchResponse>("/search/external", {
    params: {
      query: rl_params.query,
      sources: rl_params.sources,
      limit_per_source: rl_params.limitPerSource,
    },
    timeoutMs: 9_000,
    signal: rl_params.signal,
  });
}
```

`packages/api-client/src/search.ts` 仅保留明确 deprecated wrapper 或 type re-export，并增加测试证明新代码不会调用 `/search`。修改 `packages/api-client/src/index.ts` 导出新模块。由于现有 `RequestOptions` 将 `signal` 继承自 `RequestInit`，应确认 `signal` 在 `http.get` 中不会被错误覆盖；补充 `client.test.ts`/external test。不要通过 retry wrapper 重试 `invalid_cursor`、scope mismatch 或 external circuit-open。

### 7.2 capability error 和 UX 状态

API/client/UI 要区分：

| 错误 | 用户可见行为 | 是否自动切换版本/范围 |
|---|---|---|
| `invalid_cursor` | 清除 cursor，显示“结果集已变更，请重新搜索” | 否；只重启同一 query |
| `manifest_mismatch` / `projection_invalid` | 显示 artifact integrity 状态，调用 Internal API | 否 |
| `bounded_limit_exceeded` | 显示当前最大 limit 和静态目录链接 | 否；不偷偷扩大 limit |
| `worker_capability_missing` | 显示 Worker capability 缺失，调用 API | 否 |
| `manifest_unavailable` | 显示当前 publication 暂不可用和 directory link | 否；不读 live ORM |
| External `timeout` | 仅对应 source 显示 timeout/retry-after | 否；Internal 不受影响 |
| External `circuit_open` | 仅对应 source 显示 temporary unavailable | 否；不把 source 当本地结果 |
| External `rate_limited` | 显示 source 限流和 Retry-After | 否 |
| JS/Worker/API 全不可用 | 保留静态目录按 publication/dataset/type/首字母/分页导航 | 否 |

---

## 8. 静态目录与无 JS 回退

### 8.1 目录内容

Plan C 已验证的 publication build 需要包含或引用 versioned static directory/index pages。D 负责消费者语义和路由：

- `directory/index.html` 显示 Species/Assembly/Dataset/Publication scope ledger、manifest digest、provenance/license 摘要；
- 按 `object_type`、首字母/稳定 ID 前缀和固定页码提供链接；
- 每页只链接当前 publication manifest 的公开 canonical URLs；
- 目录不执行客户端全文过滤，不嵌入完整 hidden dataset；
- `next`/`previous` 由构建时固定目录顺序生成，不使用跨 manifest cursor；
- API/Worker failure 状态链接到同一个 publication/dataset scope 的目录，不能跳到“最新”或默认大豆页面；
- unavailable/not-applicable scope level 显示文字状态，不能用空白或猜测值。

### 8.2 route/build integration

在 `apps/web/scripts/ssg-build.ts` 中增加 SearchManifest 读取/验证和 directory page generation hook，复用现有 `fetchJson`/`fetchWithTimeout` 的超时模式，但不把 API fallback 的 live layout 当作 publication validation。生成过程应记录：manifest digest、shard count/doc count、目录页 count、每页 size、fallback link。构建失败不替换现有 dist/current pointer；这部分最终 promotion 仍属于 Plan C。

在 `apps/web/src/routes/search.tsx`：

- Search page 首屏只加载 scope/config，不下载跨物种全部 shards；
- Internal 和 External 使用两个 `useQuery` key，例如 `['internal-search', manifestDigest, scope, query, filters]` 和 `['external-search', query, sources]`；
- Internal section 显示 match tier、scope ledger、manifest digest、provenance/citation；
- External section显示 source badge、source status、provenance、timeout/circuit/rate-limit；
- Worker/API/static source 显示在页面的诊断/availability region，使用 `aria-live`，但不把内部 error payload 直接展示；
- compare/export action 根据 envelope eligibility disabled 并给出原因；
- 搜索 query、scope、publication、cursor 写入 canonical URL，cursor 不跨 manifest 复用；
- 无 JS 时静态 HTML 的 form/action 或 directory link 仍可完成按范围浏览。

---

## 9. TDD 实施任务清单

每个任务先写失败测试，确认失败原因，再写最小实现，最后运行 focused validation。新测试 fixture/helper 名称使用 `rl_` 前缀；Pytest/Vitest/Playwright 的框架钩子名称可按约定保留。

### D0 — Gate evidence and fact lock（只读/阻断）

- [ ] 验证 Plan C artifact/manifest/projection/capability evidence 的路径、digest、ready marker 和 static route。
- [ ] 验证 B-pre-ADR caps 已有具体数值和双物种 fixture；没有则停止 D，不写实现。
- [ ] 运行 MiniSearch 核验命令；将“已存在/不存在/不可判断”记录在执行证据，不擅自安装。
- [ ] 以 `git diff --name-only` 或等价工作区清单确认本阶段执行者只能修改 D 所授权代码/测试文件；本计划文档本身不得再次修改。

### D1 — Contract-first schemas

- [ ] 为 Internal request/manifest/document/result/response/error 写 `apps/api/tests/test_internal_search_contracts.py`：extra fields rejected、limit bounds、scope applicability、origin enum。
- [ ] 为 External request/source/result/response 写 `test_external_search_isolation.py`：unknown source rejected、max four sources、max limit、`isolated_from_internal=True`。
- [ ] 先实现 `apps/api/app/search/internal/contracts.py`、`external/contracts.py` 和 `apps/api/app/schemas/search_internal.py`/`search_external.py`。
- [ ] 运行 `cd apps/api && pytest -q tests/test_internal_search_contracts.py tests/test_external_search_isolation.py`；预期：新增测试全部通过，旧 search tests 不被删除。

### D2 — Public projection and leakage

- [ ] 写 `test_public_projection_leakage.py`，覆盖 JSON、nested provenance、URL query、serialized shard document、External raw extra 的 forbidden values。
- [ ] 写 Internal fallback binding tests：拒绝客户端提交的任意 `staticDirectoryUrl`；拒绝 forged arbitrary URL、跨 `publication_release_id`/`manifest_digest`/scope/projection schema 的目录引用、internal URL、bucket/key 和 presigned URL；目录只能来自已验证 SearchManifest/server-created error envelope。
- [ ] 写 Worker manifest-reference tests：拒绝任意 `manifestUrl`、文件路径、bucket/key、internal URL 和未登记 opaque reference；只接受 server-created verified manifest reference，并校验其 publication/digest/scope/projection binding。
- [ ] 写 External provenance contract tests：`rl_external_public_provenance` 的 `extra="forbid"` 拒绝 provider raw metadata、internal diagnostics、provider request URL、bucket/key、internal URL、presigned URL 和 token。
- [ ] 写 scope ledger test，确保不适用 level 显式 `unavailable`/`not_applicable`。
- [ ] 实现 `internal/projection.py`、`external/provenance.py`，逐字段 allowlist 投影；扫描失败返回稳定 error code。
- [ ] 运行 `cd apps/api && pytest -q tests/test_public_projection_leakage.py`；预期：注入任一 forbidden field 都失败，合法 public fixture 通过。

### D3 — Rank/tie-break/cursor

- [ ] 先写 exact ID、prefix、alias、title、summary/body、same-tier canonical URL/object type/stable ID 的排列测试。
- [ ] 写 duplicate-document、empty query normalization、casefold、stable repeated run 测试。
- [ ] 写 cursor tamper、manifest digest、publication release、scope、canonical query、filter、sort schema、limit/provider version 变化的 invalidation 测试。
- [ ] 实现 `internal/cursor.py` 和 `manifest_provider.py`；签名 secret 从 server-side key provider 注入。
- [ ] 运行 `cd apps/api && pytest -q tests/test_internal_search_provider.py tests/test_search_cursor.py`；预期：rank tuple 每次一致，所有 binding 变化均返回 `invalid_cursor`。

### D4 — Manifest provider bounded behavior

- [ ] 写 fake `rl_public_shard_store` fixture，只能返回 manifest 声明 shard；测试未声明 shard、超过 shard/doc/limit、digest mismatch、timeout、manifest unavailable。
- [ ] 实现 Internal service/router；确保 route 不 import/call `SearchService.global_search()`。
- [ ] 写 route contract test，断言 Internal response 为 public envelope 且无 internal metadata；任何 static-directory error envelope 都绑定同一 publication/digest/scope/projection，并拒绝客户端 URL 覆盖。
- [ ] 运行 `cd apps/api && pytest -q tests/test_internal_search_provider.py`；预期：所有超界请求都返回稳定 bounded error 或 directory URL，不进行 ORM fallback。

### D5 — External isolation and resilience

- [ ] 以 mocked `httpx.AsyncClient` 写 source allowlist、per-source cache key、timeout、retry、circuit-open、rate-limited、partial success tests。
- [ ] 写 test 断言 External error/cache key 不含 `internal-search:`，Internal response 不含 source statuses，External failure 不改变 fake Internal result。
- [ ] 修正 `apps/api/app/search/adapters/base.py`、`cache.py`、`rate_limiter.py`、`circuit_breaker.py` 需要的 namespace/error/header 行为，保持 source adapters (`ncbi.py`, `uniprot.py`, `ensembl.py`, `ebi.py`) 的 allowlisted URL 逻辑。
- [ ] 实现 `search_external.py` route 与 public provenance projection。
- [ ] 运行 `cd apps/api && pytest -q tests/test_external_search_isolation.py` 以及现有 `python3 scripts/test_core.py`；预期：外部 source 失败只影响对应 source，旧 renderer sanitization 继续通过。

### D6 — API/client split

- [ ] 先写 `packages/api-client/src/search-internal.test.ts` 和 `search-external.test.ts`，断言请求路径、参数、timeout、response types、旧 `/search` 不被新函数调用。
- [ ] 实现 `search-internal.ts`、`search-external.ts`、`index.ts` exports；将 `search.ts` 改为明确 deprecation wrapper/type bridge。
- [ ] 如需修正 `RequestOptions.signal` 传递，先在 `client.test.ts` 写 abort test；不要改变全局 timeout/auth 语义。
- [ ] 运行 `pnpm --filter @soymutdb/api-client test` 和 `pnpm --filter @soymutdb/api-client typecheck`；预期：所有旧 client tests 加新 split tests 通过。

### D7 — Build-time shards and Worker envelope

- [ ] 先写 worker message tests：reject arbitrary `data[]`、arbitrary `manifestUrl`/path、unregistered opaque manifest reference、manifest URL/digest mismatch、scope/projection mismatch、record/size/memory caps、public-only response。
- [ ] 根据 D0 MiniSearch decision：若未批准，先实现 bounded public document provider；若批准且 dependency gate 完成，再引入固定 MiniSearch version 和 wrapper。
- [ ] 实现 `apps/web/scripts/build-search-shards.ts` 和 `apps/web/src/workers/search.worker.ts`；所有 index/doc artifact 必须带 schema/config/hash envelope。
- [ ] 删除/禁用 `search-worker-client.ts` 的 full-dataset main-thread fallback；改为 Worker → Internal API → static directory。
- [ ] 运行 `pnpm --filter @soymutdb/web test` 和 `pnpm --filter @soymutdb/web typecheck`；预期：Worker failure 不触发主线程全量 filter，bounded fixture 在 caps 内通过。

### D8 — SSG/static directory

- [ ] 为 `apps/web/scripts/ssg-build.ts` 写 fixture test：同 publication manifest 生成相同目录顺序、digest/link、显式 scope ledger；manifest invalid 不写 ready output。
- [ ] 实现 directory/index pages、首字母/类型/固定分页和 no-JS links；只消费 C/B validated public fixture。
- [ ] 写 test 断言目录中没有 internal IDs/paths/presigned URLs/hidden fields，也没有默认跨 publication link；伪造任意 directory URL、跨 publication URL、internal URL、bucket/key 或 presigned URL 均被拒绝。
- [ ] 运行 `pnpm --filter @soymutdb/web ssg:build`；预期：在受控 fixture/API unavailable 情况下生成 version-pinned directory，失败不替换旧 ready output。

### D9 — React consumer and capability UX

- [ ] 先写 route/component tests：Internal/External sections independent loading/error, provenance, scope ledger, cursor invalidation, compare/export eligibility, aria-live states；fallback 只能渲染 verified manifest directory，不能接受 client-controlled URL。
- [ ] 改 `apps/web/src/routes/search.tsx` 的 query keys、fallback state、canonical URL 和 no-JS directory link；保留 expression search 的独立 contract，不把 expression live query 混入 Internal manifest provider。
- [ ] 更新 `tests/e2e/search.spec.ts`：Internal result origin/scope、External provider failure isolation、Worker/API/directory fallback、no-JS directory navigation、forbidden field absence。
- [ ] 运行 `pnpm exec playwright test tests/e2e/search.spec.ts`；预期：可用 fixture 下 Internal 结果稳定，External timeout 不隐藏 Internal，关闭 JS 后目录可导航。

### D10 — Performance/limits and gate package

- [ ] 用 B-pre-ADR 双物种 fixture 测量 shard download、decompress/load、Worker memory、query P50/P95、API P50/P95、directory response size。
- [ ] 写 limits test：shard/doc/limit/timeout/memory 超界返回 bounded error；不得以“测试数据小”跳过上限。
- [ ] 生成 D evidence：测试命令/输出、manifest/projection digest、field leakage scan、Worker fallback trace、External isolation trace、依赖核验、OpenAPI/client diff 和性能表。
- [ ] 由 Oracle 复核 D；发现 blocking issue 先修复并重跑 focused tests，不宣称 D complete。

---

## 10. 验证命令、预期结果与性能/限制

### 10.1 命令矩阵

以下命令按前置 gate 实际可用性执行；命令失败必须修复或明确记录为 gate blocker，不能用“未连接真实 API”掩盖 contract failure。

```bash
# API focused contract/projection/provider/external tests
cd apps/api
pytest -q \
  tests/test_internal_search_contracts.py \
  tests/test_internal_search_provider.py \
  tests/test_search_cursor.py \
  tests/test_public_projection_leakage.py \
  tests/test_external_search_isolation.py
# Expected: all D contract tests pass; bounded/cursor/leakage/isolation cases green.

# Existing core renderer/resilience smoke
python3 scripts/test_core.py
# Expected: existing renderer sanitization and cache/circuit imports pass;
# no external network success is required for pure core tests.

# TypeScript API client
cd ../../packages/api-client
pnpm test
pnpm typecheck
# Expected: old HTTP client tests plus internal/external split tests pass.

# Web Worker/build/route
cd ../../apps/web
pnpm test
pnpm typecheck
pnpm ssg:build
# Expected: worker envelope tests pass; no main-thread full-dataset fallback;
# SSG emits only validated fixture/versioned directory output.

# Existing app-level checks after focused tests
cd ../..
pnpm lint
pnpm typecheck
pnpm test
pnpm build:web
# Expected: no new lint/type/build regressions; build output references the
# publication-bound search resources and does not expose forbidden fields.

# Browser acceptance
pnpm exec playwright test tests/e2e/search.spec.ts
# Expected: Internal/External sections remain separate, provider failure is
# isolated, and JS-off directory navigation remains usable.
```

实际仓库为 `/mnt/data02/T25ronglin/code/web`，所有命令应从该目录或命令中的明确子目录运行；不使用 `cd ... &&` 作为隐式前提。执行报告需保存 exit code、测试数量、失败用例和 fixture/manifest digest，不保存 secret。

### 10.2 预期限制表

具体数值由 B-pre-ADR 填入执行证据；下表是必须存在的契约字段，不是允许擅自采用的默认容量：

| 限制 | 来源 | 超界行为 |
|---|---|---|
| `max_shards` | B-pre-ADR/SearchManifest | `bounded_shard_limit_exceeded` + static directory |
| `max_documents` | B-pre-ADR/SearchManifest | `bounded_document_limit_exceeded` + API/directory |
| `limit_max` | B-pre-ADR/API contract | 400 `bounded_limit_exceeded` |
| API total timeout | B-pre-ADR/route policy | bounded timeout error；不读 ORM |
| Worker manifest download/decompressed bytes | B-pre-ADR/manifest | Worker fallback API |
| Worker memory ceiling | B-pre-ADR/browser measurement | Worker fallback API；不主线程 filter |
| External per-source timeout | External policy/adapter spec | source `external_timeout` |
| External aggregate deadline | External policy | partial per-source statuses |
| External cache TTL | source policy | source-specific TTL；不与 Internal 共用 |
| Static directory page size/page count | C artifact capability + D fixture | fixed links/next page；不动态全量加载 |

性能验收至少报告：Worker load/query P50/P95、API provider P50/P95、External aggregate wall time、最大内存、compressed/decompressed bytes、首个结果可见时间、fallback time-to-directory、移动端低带宽表现。目标沿用 README 的 Internal API P95 `< 200 ms` 作为待测基线，但只有 B/C 数据和真实 fixture 证据通过后才可判定；不能把旧 live ORM endpoint 的结果当作新 Internal SLO。

---

## 11. 回滚、兼容与清理

### 11.1 回滚顺序

1. 如果新 Internal manifest/provider 失败，先让前端使用同一 publication 的 static directory；不切到 live ORM。
2. 如果 External route 失败，保留 Internal section；按 source status 显示 degraded，不恢复 content-negotiated 混合语义。
3. 如果 Worker bundle/index 失败，回退到已验证的旧 publication artifact 或 API/directory；不把旧 Worker generic array filter 重新接到完整 dataset。
4. 如果 api-client consumer 尚未全部切换，保留明确 deprecated `/search` compatibility route，在审计/telemetry 中统计调用；不扩大其响应字段或内容协商范围。
5. 如果 MiniSearch 依赖 gate 失败，撤回仅属于该依赖的 package/lockfile diff，使用 bounded provider/API/directory；不得升级或引入 FlexSearch/Orama 替代。
6. 任何 publication pointer、ready marker、manifest digest 或 artifact reachability 不确定时，按 C 的 `unknown`/fenced compensation 规则处理；D 不能直接修改 pointer 或删除 artifact。

### 11.2 旧代码清理条件

只有以下证据齐全后才可删除旧 mixed search path 或 generic full-data Worker helper：

- API/client call inventory 显示无未迁移 consumer；
- E2E/contract 证明新 paths、External failure、API/directory fallback 和 no-JS 均覆盖；
- deprecation window 和 owner/telemetry 已完成；
- Oracle review 明确批准删除；
- 删除前运行 `git diff --name-only`/引用搜索，确认不误删 expression/genes/variants 等非 D 搜索；
- 清理 `dist/`/临时索引/coverage 前先确认它们不是 active validated artifact，遵循 README/计划的清理约束。

不得以普通 `rm` 删除仍被 manifest、approval、audit、recovery window 或 legal hold 引用的 artifact；孤儿/保留判断属于 C 的 reference-based reconciler。

---

## 12. 交付物与 Oracle review 包

D 完成时只可提交/说明以下实现范围（实际代码由获授权执行者完成，当前文档不授权实现）：

1. Internal/External 独立 OpenAPI schema、route、service、provider/adapter contract；
2. Internal SearchManifest、rank profile、signed cursor binding 和 bounded error 证据；
3. public projection schema 使用、field leakage test report、scope/provenance envelope sample；
4. External allowlist/cache/rate-limit/timeout/circuit-breaker isolation test report；
5. api-client split、Worker envelope、build-time shard/index manifest、API/directory fallback trace；
6. no-JS static directory sample、scope/pagination links、hash/manifest evidence；
7. B-pre-ADR 双物种性能/内存/上限结果与 C artifact digest/ready/capability references；
8. focused/full test commands、expected/actual output、OpenAPI diff、dependency gate result；
9. rollback/deprecation/consumer capability error matrix；
10. Oracle review response：所有 blocker 修复、简化建议、未解决风险及明确 owner。未通过 Oracle review 不得把 D 标为完成，也不得进入 E。

### 12.1 失败声明规则

- Worker 能搜索不等于授权通过；manifest/schema/hash 校验失败必须失败或 fallback。
- API 返回结果不等于已发布；必须带 publication release、scope ledger、manifest digest 和 provenance。
- External adapter 返回 hit 不等于本地事实；不得自动合并、比较或写 ontology/数据库。
- 缓存命中不等于 publication truth；Redis 故障不应改变发布语义。
- MiniSearch 可工作不等于容量达标；没有 B-pre-ADR ceilings 就不宣称性能。
- Static directory 可导航不等于全文搜索；它只提供固定 scope/type/prefix/page fallback。

---

## 13. 计划自审（writer self-review）

- [x] 仅引用实际仓库路径：`apps/api/app/api/v1/search.py`、`apps/api/app/services/search_service.py`、`apps/api/app/search/*`、`apps/web/src/workers/search.worker.ts`、`apps/web/src/lib/search-worker-client.ts`、`apps/web/scripts/ssg-build.ts`、`apps/web/src/routes/search.tsx`、`packages/api-client/src/*`、相关测试与 package manifests。
- [x] 明确 D 阻断在 C validated artifacts 和 B-pre-ADR search caps；没有把计划写成无条件实施授权。
- [x] 覆盖 Internal/External schema、route、service、contract、manifest-backed bounded provider、精确 rank tiers/tie-break、signed cursor binding、public envelope/scope_type/provenance、External isolation、api-client split、MiniSearch gated dependency、build shards、Worker envelope、API/directory fallback、field leakage、capability errors、performance/limits。
- [x] 已关闭 B-04：Internal request/client/Worker 不接受 client-controlled `staticDirectoryUrl`；fallback directory 只能来自 verified SearchManifest/server-created error envelope，并绑定 publication release、manifest digest、scope 和 public projection schema；已规划 arbitrary/cross-publication/internal/presigned URL 与未登记 manifest reference 拒绝测试。
- [x] 已完成 typed-ledger refinement：API-client 直接使用共享 `rl_scope_ledger`、`rl_scope_level` 和固定 public provenance DTO；External provenance 不再是 `dict<string, unknown>`，固定 DTO 使用 extra-forbid 并拒绝 raw metadata/internal diagnostics/URL/token 泄漏。
- [x] 明确 Worker 失败时禁止 full main-thread dataset filter，并对现有 generic array Worker 说明迁移边界。
- [x] 代表性代码片段含 `rl_` 自有业务命名和中文 why-comments；框架 hook、第三方 adapter、旧公共接口按兼容规则保留。
- [x] 测试按 TDD 排序，包含 Python/Vitest/TypeScript/SSG/Playwright 命令和预期结果。
- [x] MiniSearch 已按实际 manifests 核验为未发现 direct dependency；计划要求先查 lockfile/node_modules，再由 B-pre-ADR/ADR gated install，不自动添加依赖。
- [x] 未要求提交、推送、迁移、部署或其他文件修改。

**自审结论：** B-04 的 client-controlled static directory、arbitrary worker manifest input、跨 publication/internal/presigned URL fallback 和 unregistered manifest reference 风险已改为 verified SearchManifest/server-created envelope 绑定；External provenance 已改为 fixed `extra="forbid"` DTO；API-client scope ledger 已改为共享 typed ledger。Plan D 仍只有在 A0/A1/B-pre-ADR、C artifact/projection/capability 验证和本计划 Oracle review 全部通过后，才可由授权执行者实施。
