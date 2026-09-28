# OPT2-A — API search 收口（OPT2-01 / OPT2-02 / OPT2-03）

> 负责人：A（后端 search 所有权范围）
> 工作区：`/mnt/data02/T25ronglin/code/web`（HEAD 未提交工作树；不 commit）
> 环境：PostgreSQL 16 @ `127.0.0.1:55432`（trust），库 `abl2_optapi`
> 结论一句话：**OPT2-01 已用真实 ASGI HTTP + 真实 DB 覆盖；OPT2-02 证实存在「未发布 release 被静默忽略 / 串味」并已修复；OPT2-03 该文件 ruff 2→0。**

## 1. 改动文件清单

| 文件 | 改动 |
| --- | --- |
| `apps/api/app/api/v1/search.py` | 新增可选 `release_id` 查询参数并贯穿 federated / DB 两条路径；`_federated_release_id(db, requested)` 显式优先；import 排序 + 长行拆分（OPT2-03） |
| `apps/api/app/services/search_service.py` | `global_search(..., release_id=None)`：显式 release 直接作为作用域，不再强制解析 active；显式值进入缓存键与响应 |
| `apps/api/tests/test_opt2_federated_html_http.py` | **新增**：`format=html` 走真实 ASGI/httpx + 真实 PostgreSQL |
| `apps/api/tests/test_opt2_release_scope.py` | **新增**：release 作用域证实/钉住（真实 HTTP + 真实 DB，键与响应双证据） |
| `apps/api/tests/test_opt_federated_cache_callsites.py` | 直接调用端点处补传 `release_id=None`；新增「显式 pin 优先于解析值」断言（既有断言未削弱） |
| `apps/api/tests/test_search_contract.py` | 签名契约加入 `release_id`；新增路由接受 `release_id` 的断言 |

未触碰：`apps/web/**`、`packages/**`、`e2e/**`、`scripts/**`、`apps/admin/**`、`models/**`、迁移文件。`app/search/cache.py` 本轮未改（其 scope 语义已满足要求）。

## 2. 逐条任务

### OPT2-01 真实 HTTP 层 — 已验证

- **改前缺口**：`format=html` 旧用例 `_call_federated_html` 直接调用端点函数并 patch 内部依赖（`resolve_release_context` / `render_search_html` / `ExternalSearchAggregator` / `get_redis`），从未经过 ASGI/httpx 请求-响应栈。
- **做法**：新增 `test_opt2_federated_html_http.py`，用 conftest 的真实 app + `httpx.ASGITransport`，`get_db` 走真实 PostgreSQL 会话；仅替换两处**外部服务**：`get_redis`（本机无 redis-server）与四个 outbound provider adapter（避免真实外网抖动，且不 patch `search_api.ExternalSearchAggregator` 本身）。真实 `ExternalSearchAggregator`、`SearchCache`、`render_search_html`、内容协商全部运行。
- **改后证据**（命令/退出码/关键输出）：

```
$ SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl2_optapi \
  .venv/bin/python -m pytest tests/test_opt2_federated_html_http.py -q -p no:cacheprovider
tests/test_opt2_federated_html_http.py ....                              [100%]
4 passed
EXIT=0
```

断言覆盖：`status_code == 200`；`content-type == text/html; charset=utf-8`；body 以 `<div` 开头、非 JSON（`'"sources"' not in body`）；渲染出真实 `.ext-search` 与外部命中；**负例**：种入 `internal-only` 记录（`MutantLine(id=987650, public_id=None, is_public=False)`）并断言 `"987650" not in body`。另含 Accept 协商、html 缓存键 `...:html` 落盘、无已发布 release 仍 200 三个用例。

### OPT2-02 release 作用域 — 证实串味并修复

- **改前证据（红）**：`release_id` 甚至不是端点参数，FastAPI 直接忽略；`_federated_release_id` 永远解析 active release。

```
$ .venv/bin/python -m pytest tests/test_opt2_release_scope.py -q -p no:cacheprovider
FAILED ...::test_explicit_unpublished_release_scopes_the_json_response
FAILED ...::test_two_unpublished_releases_do_not_share_a_response
FAILED ...::test_unpublished_release_ids_do_not_share_the_html_cache_key
FAILED ...::test_published_release_ids_also_fork_the_html_cache_key
E   AssertionError: assert [] == ['OPT2RA']            # 显式未发布 release 被忽略
E   AssertionError: assert 1 == 2                       # 两个不同 release 共用 1 个 html key
E    +  where 1 = len(['search:external:3a190b91caa72e2eb5fe7be9873347b5b60e18309a642cbe9345c65316fdb09a:html'])
4 failed, 6 passed
EXIT=1
```

  关键点：连**已发布**的两个 release 在 HTTP 层也被折叠成同一 key（`assert 1 == 2`），说明不是「未发布才串味」，而是显式 release 从未进入作用域。

- **做法**：
  1. `/api/v1/search` 增加 `release_id: int | None = Query(default=None, ge=1)`；JSON 本地路径传给 `SearchService.global_search(..., release_id=...)`，federated JSON/HTML 路径传给 `_federated_release_id(db, release_id)`。
  2. `_federated_release_id` 显式值原样返回（发布与否皆然）；无显式值才回退 active 已发布 release，仍保留 best-effort（无已发布 release → `None`）。
  3. `SearchService.global_search` 在 `release_id is None` 时才 `resolve_release_context`；显式值时直接作为 SQL/键/响应作用域（`Assembly.release_id == release_id`，天然可用未发布 release，无需改 `release_context.py`）。

- **改后证据（绿）**：

```
$ .venv/bin/python -m pytest tests/test_opt2_release_scope.py tests/test_opt2_federated_html_http.py \
    tests/test_opt_federated_cache_key.py tests/test_opt_federated_cache_callsites.py \
    tests/test_search_federation.py tests/test_search_contract.py -q -p no:cacheprovider
42 passed
EXIT=0
```

  具体到键字符串（直接验证，三个 release 三个 key）：

```
101  search:external:7fdd5e57693a655a65c82c59b3d4b5a035aac47c623ef01b67b0f740dadec79e:html
102  search:external:17f5c623c4b45743c531b397b70fe65bd4361183da4957d48ddad9ee8c2dc719:html
None search:external:952fe6fd90feb1b848a7f174a147db4567bc2779557fa2af0f11f8512a17b7ea:html
```

  真实 HTTP + DB 用例另外证明：两个未发布 release 的 JSON 响应体不再相同（各自只返回本 release 的 gene，`release_id` 字段分别为各自 id），两个未发布 release 的 html key 不再相同，且已发布 release 反向同样分叉。缓存键被钉在 `search:external:<hash>:html`，并断言 `expected_a in html_keys`（精确键相等，非仅「两者不同」）。

### OPT2-03 ruff — 2 → 0

- **改前**：

```
$ .venv/bin/python -m ruff check app/api/v1/search.py
I001 [*] Import block is un-sorted or un-formatted  --> app/api/v1/search.py:15:1
E501 Line too long (104 > 100)                       --> app/api/v1/search.py:34:101
Found 2 errors.
EXIT=1
```

- **做法**：把游离的 `from ...core.security import RoleName` 归位排序；`from ...search import (...)` 拆多行。仅动 `search.py`，不碰 repo-wide 404 条既有债务。
- **改后**：

```
$ .venv/bin/python -m ruff check app/api/v1/search.py
All checks passed!
EXIT=0
```

## 3. OPT2-02 明确结论

**证实串味已修（ASSUMED LEAK → FIXED）。** 改前：请求里的 `release_id` 被端点完全忽略，任何（含未发布、甚至已发布）显式 release 都塌缩到 active release 的同一缓存键/同一响应。改后：显式 `release_id` 原样进入 federated key 与 DB 查询/响应作用域，发布与否都分叉；反向（存在已发布 release 时不同 release ⇒ 不同键）也有专项断言，既有断言未削弱。无显式 pin 时仍保留 active best-effort（无已发布 release 时 key 为 `None`，路由继续服务），这是有意设计，写在 `_federated_release_id` docstring。

## 4. 未完成 / 未验证 / 阻塞

- **真实 Redis 仍是缺口**：本机无 redis-server，federated 用例仍用进程内 `_FakeRedis`。因此「真实 Redis 往返 / TTL / 并发」未在本轮验证；但键字符串、`:html` 后缀与命中路径均以 fake 观测并断言。
- **ClickHouse 未涉及**：`/search` 两条路径都不依赖 ClickHouse，本轮无缺口变化。
- **真实外网 provider 未打**：provider adapter 用确定性命中替身（真实 adapter 的 HTTP/解析/限流/熔断未在本用例内执行），换取离线稳定；已在报告如实标注。
- **`tests/a0/test_rl_catalog_baseline.py` 收集失败为既有问题**（`ModuleNotFoundError: No module named 'tools'`，与本次改动无关）。排除 `a0` 后全量 `tests` **1348 passed**。
- 未执行任何 `git commit/push/checkout/stash/reset`。

## 5. 复跑命令（协调者用）

```bash
cd apps/api
export SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl2_optapi'
.venv/bin/python -m pytest tests/test_opt2_*.py tests/test_opt_federated_cache_key.py \
  tests/test_opt_federated_cache_callsites.py tests/test_search_federation.py \
  tests/test_search_contract.py -q -p no:cacheprovider        # 42 passed, EXIT=0
.venv/bin/python -m ruff check app/api/v1/search.py           # All checks passed!, EXIT=0
```

> 环境提示：`conftest.py` 走 `Base.metadata.create_all` 且无条件 seed `roles`。若先用 `alembic upgrade head` 建库再直接跑 pytest，会因 roles 唯一键冲突而报错；本报告使用「建空库 → 跑 pytest（create_all）」路径。此差异属既有环境行为，未改 conftest。
