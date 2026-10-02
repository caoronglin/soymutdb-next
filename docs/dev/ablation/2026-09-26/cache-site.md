# W3 缓存与站点隔离 —— 真实消融实验报告

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 仓库：`/mnt/data02/T25ronglin/code/web`
- HEAD：`8e78116fd`（`docs(handoff): record the lockfile React purge`）
- 日期：2026-09-26
- 范围：共享搜索缓存（`search:global`）的站点变体 / release / assembly 隔离、内部站点缓存旁路、缓存键构造、内部响应 Cache-Control
- 结论摘要：13 个场景行；`GUARD-ACTIVE` 11、`GUARD-INERT` 1、`GAP` 1
- 生产源码零残留改动：实验结束后 `git diff --stat -- apps/api` 为空

---

## 目标与范围

本工作流验证 `AGENTS.md` 与 `docs/dev/database-core-contract.md` 对生物搜索缓存的硬约束：

> 生物搜索的缓存键必须包含 site variant、release、assembly、query 与 filters；internal 响应为私有且不得进入共享缓存。

对每个场景严格执行三段式：

1. **对照**：跑真实代码路径，记录精确命令、退出码、关键输出；
2. **消融**：只中和一个保护因子（优先 pytest `monkeypatch`；无法 monkeypatch 时用临时单点生产改动，事后 `git checkout` 还原并以 `git diff` 证明）；
3. **判定**：`GUARD-ACTIVE`（对照通过、消融后翻转）｜`GUARD-INERT`（消融后无变化，疑似冗余/纵深防御）｜`GAP`（对照即失败）。

范围为 `SearchService.global_search` 的共享缓存这一条真实读写路径；**不做**提交，不永久改生产源码。

### 真实缓存键/参数（源码定位）

| 事实 | 位置 | 内容 |
| --- | --- | --- |
| 共享缓存参数元组（唯一事实来源） | `apps/api/app/services/search_service.py:366-374` | `{query, types, cursor, limit, site_variant, release_id, assembly_id}` |
| 真实键哈希（name + 参数 JSON + sha256，取前 12 位） | `apps/api/app/services/cache.py:52-63`（`make_cache_key`）、`:93`（`key = make_cache_key(name, params)`） | 前缀固定 `cache:`，无参数时退化为 `cache:{name}` |
| 参数规范化 | `apps/api/app/services/cache.py:61` | `json.dumps(params, sort_keys=True, ...)` |
| filters 规范化 | `apps/api/app/services/search_service.py:124-131` | `_normalize_active_types` 去重并按枚举声明顺序排序，故 `types` 列表本身已 canonical |
| internal 旁路（不进入共享缓存） | `apps/api/app/services/search_service.py:599-603` | `if site_variant == SiteVariant.INTERNAL: return ...(await load())` |
| 共享缓存真正读写 | `apps/api/app/services/search_service.py:604-609` | `get_or_set("search:global", ttl=60, loader=load, params=cache_params)` |
| internal 响应头 | `apps/api/app/api/v1/search.py:270` | `response.headers["Cache-Control"] = "private, no-store"` |
| 内部检索完全不缓存 | `apps/api/app/api/v1/search.py:240-270` | `internal_search` 直接查询并审计，无 `get_or_set` |
| 另一条独立缓存（联邦 NCBI/UniProt） | `apps/api/app/search/cache.py:26-34`；调用点 `apps/api/app/api/v1/search.py:183`、`apps/api/app/search/aggregator.py:69,188,207` | 键仅为 `search:{sha256(query + sorted(sources))}`，**无** release/assembly/site_variant |

`AGENTS.md` 要求的 scope 逐项核对：**site variant、release、assembly、query、filters(types)、pagination(cursor+limit) 全部真实存在于键中**（见下方 S12 的实测证据）。

---

## 环境与命令

```bash
cd /mnt/data02/T25ronglin/code/web
git rev-parse --short HEAD          # 8e78116fd

# 每次运行前重建独立库（复用已在 55432 上运行的外部 postmaster）
PG_BIN=$PWD/.mamba-root/envs/postgres16/bin
$PG_BIN/dropdb  -p 55432 -h 127.0.0.1 -U soymutdb --if-exists abl_cache
$PG_BIN/createdb -p 55432 -h 127.0.0.1 -U soymutdb abl_cache

# 锚定测试模板
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_cache' \
  .venv/bin/python -m pytest tests/<file>::<test> -q -p no:cacheprovider
```

- 解释器：`apps/api/.venv/bin/python`（Python 3.14.6，pytest 9.1.1）
- 数据库：PostgreSQL 16.15 @ `127.0.0.1:55432`（trust）
- 消融载体（新增、不提交）：
  - `apps/api/tests/test_ablation_cache_site.py`（9 个测试，真实 `global_search` + 真实 `get_or_set` + 真实 `make_cache_key` + 内存 `FakeRedis`，只 monkeypatch 单一因子）
  - `.validation/ablation/cache/lazy_resolve_ablation.diff` + `lazy_resolve_run.log`（唯一一次临时生产改动）
  - `.validation/ablation/cache/baseline_and_ablation.log`（全量原始输出）

对照组基线（一次性，47 passed，EXIT=0）：

```bash
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_cache' \
  .venv/bin/python -m pytest tests/test_search_contract.py tests/test_cache.py tests/test_search.py -q -p no:cacheprovider
# ======================== 47 passed, 2 warnings in 2.33s ========================
# EXIT=0
```

消融套件（9 passed，EXIT=0）：

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_cache' \
  .venv/bin/python -m pytest tests/test_ablation_cache_site.py -q -s -p no:cacheprovider
# ========================= 9 passed, 1 warning in 0.45s =========================
# EXIT=0
```

---

## 逐场景结果表

所有“对照”行均为真实生产锚定测试；所有“消融”行由 `test_ablation_cache_site.py` 驱动（真实代码路径，仅中和一个因子）。`ABLATION-RESULT ...` 为消融测试打印的关键输出。

| # | 场景 | 对照（命令 / 退出码 / 关键输出） | 消融（单因子） | 判定 | 证据（命令 / 退出码 / 关键输出） |
| --- | --- | --- | --- | --- | --- |
| S1 | CTX-01 internal 完全旁路共享缓存 | `pytest tests/test_search_contract.py::test_internal_global_search_bypasses_the_shared_cache -q` → `1 passed` EXIT=0，`cache.assert_not_awaited()` 成立 | 用命名空间把 `search_service.SiteVariant.INTERNAL` 换为不等值 sentinel，使 `:599` 分支失效（internal 走 `get_or_set`） | **GUARD-ACTIVE** | `pytest tests/test_ablation_cache_site.py::test_ABL_ctx01_... -q -s` EXIT=0；对照 `CTX-01.control_internal_bypass {"internal_cache_awaited": false}` → 消融 `{"external_cache_awaited": true, "internal_cache_awaited": true...}`（`internal2["cache_awaited"] is True`） |
| S2 | CTX-01 site_variant 阻止 internal/external 复用同一条目 | 同上 strong baseline；S1 消融后保留 `site_variant` 字段 → 两条目 | 在 S1 消融之上删除 `cache_params["site_variant"]` | **GUARD-ACTIVE** | 同测试 `CTX-01.ablation_remove_bypass_keep_site_variant`：`external_key=...59117fc35b97`，`internal_key=...a456a517c0c0`，`store_size=2`，`internal_loader_calls=1` |
| S3 | CTX-01 单独删除 `site_variant`（旁路保持原样） | `test_global_search_cache_isolates_site_variant_release_and_assembly` → `1 passed` EXIT=0 | 仅从 params 删 `site_variant`，internal 仍旁路 | **GUARD-INERT** | 字段仅在内层生效；见 S2 才会翻转 → 属纵深防御（见“INERT 发现”） |
| S4 | CTX-02 release 隔离 | 同上锚定测试 EXIT=0（断言 `external_v4_release7 != other_release`） | real `get_or_set` 包装器删除 `params["release_id"]`，同 release/assembly 换 release 再查 | **GUARD-ACTIVE** | `CTX-02.control {"keys": ["...59117fc35b97","...602108ea7385"], "store_size": 2, "second_loader_calls": 1}` → `CTX-02.ablation_drop_release_id {"keys": ["...2121ac37135d","...2121ac37135d"], "store_size": 1, "second_loader_calls": 0}` |
| S5 | CTX-03 assembly 隔离 | 同上锚定测试 EXIT=0（断言 `external_v4_release7 != other_assembly`） | 删除 `params["assembly_id"]`，release 固定、换 assembly | **GUARD-ACTIVE** | `CTX-03.control keys=[...59117fc35b97, ...94fb17cd5eac] store_size=2 second_loader_calls=1` → `CTX-03.ablation_drop_assembly_id keys=[...7c3ed06eb75f, ...7c3ed06eb75f] store_size=1 second_loader_calls=0` |
| S6 | 缓存条目绑定“已解析的 release+assembly” | `test_search_cache_is_bound_to_resolved_release_and_assembly` → `1 passed` EXIT=0，`params["release_id"]==7`、`params["assembly_id"] is None` | 临时生产改动：把 `resolve_release_context` 移到缓存读写之后（“惰性解析”，见 diff 文件） | **GUARD-ACTIVE** | `pytest tests/test_search_contract.py::test_search_cache_is_bound_to_resolved_release_and_assembly -q` EXIT=1：`assert captured["params"]["release_id"] == 7 / E assert None == 7` |
| S7 | 无已发布 release 时必须在任何缓存查询之前失败 | `test_search_without_a_published_release_fails_before_cache_lookup` → `1 passed` EXIT=0 | 同一“惰性解析”临时改动 | **GUARD-ACTIVE** | 消融下 `cache.assert_not_awaited()` 失败：`AssertionError: Expected mock to not have been awaited. Awaited 1 times.`（`lazy_resolve_run.log`） |
| S8 | 缓存键必须包含 params（否则不同 scope 撞键） | `test_cache.py::TestGetOrSet::test_params_are_part_of_the_key` → `1 passed` EXIT=0 | monkeypatch `app.services.cache.make_cache_key` 忽略 params（键退化为 `cache:{name}`） | **GUARD-ACTIVE** | `params_in_key.control {"keys": [...b88cd59238f9, ...f9457cce356d], "store_size": 2}` → `params_in_key.ablation_drop_hash {"store_size": 1}` |
| S9 | 参数在哈希前排序（离序字典同键） | `test_cache.py::TestMakeCacheKey::test_params_are_sorted_before_hashing` → `1 passed` EXIT=0 | monkeypatch `cache_mod.json` 去掉 `sort_keys=True` | **GUARD-ACTIVE** | `sorted_params.ablation_no_sort {"forward": "cache:x:d8497d9d8277", "reverse": "cache:x:d5b8aed26525"}`（不再相等） |
| S10 | 未声明的 cache key 参数必须在装饰期报错 | `test_cache.py::TestCachedDecorator::test_rejects_unknown_cache_key_parameter` → `1 passed` EXIT=0（`ValueError: ... not function parameters`） | monkeypatch `cache_decorator.inspect.signature`，令 `parameters` 额外含 `missing`（等同删掉 `:36-41` 校验） | **GUARD-ACTIVE** | `unknown_key_param.ablation_guard_removed {"decorated": "load"}`（不再抛错） |
| S11 | internal 响应头 `Cache-Control: private, no-store` | `test_search_contract.py::test_internal_search_sets_private_no_store_header` → `1 passed` EXIT=0 | 用静默 `headers` 的响应替身中和 `search.py:270` 的唯一写入 | **GUARD-ACTIVE** | `cache_control.control {"header": "private, no-store"}` → `cache_control.ablation_mute_write {"header": null}` |
| S12 | 键必须覆盖 query / filters / pagination | 真实路径捕获 params 全字段 | 分别改变 query、types、limit、cursor 后重算真实键 | **GUARD-ACTIVE（存在性）** | `key_scope.present {"base_params": {"assembly_id": 11, "cursor": null, "limit": 20, "query": "Glyma", "release_id": 7, "site_variant": "external", "types": ["gene"]}, "distinct": {"query": true, "limit": true, "filters_types": true, "pagination_cursor": true}}` |
| S13 | 另一条联邦搜索缓存键是否含生物 scope | 无对应锚定测试（当前对照缺失） | 直接检查 `SearchCache.make_key` 签名与输出 | **GAP** | `legacy_federated_key {"params": ["query", "sources"], "key": "search:8af2ac4...", "sorted_sources_same": true}` —— 键中无 release/assembly/site_variant |

---

## GAP 与 INERT 发现

### GAP-1（S13）：联邦搜索缓存键缺乏 release/assembly/site_variant 维度
- `apps/api/app/search/cache.py:26-34` 的 `SearchCache.make_key` 只哈希 `(query, sorted(sources))`；`apps/api/app/api/v1/search.py:183` 与 `apps/api/app/search/aggregator.py:69` 都用它缓存联邦结果/HTML 片段。
- 联邦源（NCBI/UniProt）本身与 release 无关，因此**当前**不产生串扰；但 `AGENTS.md` 的措辞是“生物搜索缓存键必须含 site variant、release、assembly、query、filters”，而该键连 site variant 都没有。`/search` 端点写死 `SiteVariant.EXTERNAL`，一旦 internal 站点复用联邦路径就会跨站点复用 HTML 片段。
- 判定：**GAP（对照缺失，非基线失败）**。建议补一条负向锚定：同 query 不同 site/release 必须产生不同 `search:` 前缀键。

### INERT-1（S3）：`site_variant` 字段在 internal 旁路存在时不可达
- 只要 `search_service.py:599-603` 的 internal 旁路存在，internal 根本不会调用 `get_or_set`；因此单独从 `cache_params` 删除 `site_variant`（S3）对任何外部可观测行为零影响 → `GUARD-INERT`。
- 但它是有效的**纵深防御**：一旦旁路被移除或未来有调用方把 INTERNAL 送进共享缓存（S2），缺它就立即串键。保留合理，判定为“朴素 INERT，非死代码”。

### INERT-2（S9 备注）：`sort_keys=True` 对现有调用点属纵深防御
- 所有真实调用点都用固定顺序的 dict 字面量（`search_service.py:366-374`、`stats.py`、`news.py` 等），在 CPython 3.7+ 下 `json.dumps` 的输入顺序本就确定，删排序对现网行为通常无影响。
- 锚定单测 `test_params_are_sorted_before_hashing` 会翻转，故仍记为 `GUARD-ACTIVE`；但按“现网可观测性”是 INERT 级别的备用保护。

### 未发现
- 没有基线失败（`GAP` 仅指 S13 缺锚定，而非现网 bug）。
- 生产源码未被永久修改：首次运行后 `git diff --stat -- apps/api` 为空字符串。

---

## 未验证项

1. **真实 Redis 行为**：消融用内存 `FakeRedis` 走真实 `get_or_set`；未连真实 Redis 验证 TTL 过期、`delete_prefix` 失效、跨进程键序列化差异。
2. **`types` 顺序的跨客户端差异**：`_normalize_active_types` 已按枚举序 canonical，故未单独消融；未验证恶意/乱序 `types` 查询串在 cursor 编码与键之间的一致性（已有 cursor 单测覆盖部分）。
3. **filters 的完整集合**：`global_search` 目前只有 `types` 与 `assembly_id` 两种筛选维度；上游若新增 filter 而未加入 `cache_params`，本套测试不会自动发现。
4. **`assembly_id=None`（跨 assembly 歧义结果）的键**：验证过其为键中的独立 `null` 值（`base_params` 显示 `assembly_id: 11`，S6 锚定显示缺省 `None`），但未做 `None` vs 具体值的撞键消融。
5. **联邦缓存真实串扰**：未搭 mock 适配器跑 `/search?sources=...` 验证不同 release 下同 query 命中同一 HTML 片段（S13 仅静态+键函数级证据）。
6. **并发/竞态**：未验证同键并发 miss 的双写。
7. **`SearchCache` 与 `cache:` 前缀不冲突**：两套前缀（`search:` vs `cache:search:global:`）不同，静态判定无碰撞，未做运行期碰撞测试。

---

## 原始证据附录

### A. 基线（锚定测试，逐条）

```
[EXIT=0] tests/test_cache.py::TestGetOrSet::test_params_are_part_of_the_key                  -> 1 passed
[EXIT=0] tests/test_cache.py::TestMakeCacheKey::test_params_are_sorted_before_hashing        -> 1 passed
[EXIT=0] tests/test_cache.py::TestCachedDecorator::test_rejects_unknown_cache_key_parameter  -> 1 passed
[EXIT=0] tests/test_search_contract.py::test_internal_search_sets_private_no_store_header    -> 1 passed
[EXIT=0] tests/test_search_contract.py::test_internal_global_search_bypasses_the_shared_cache-> 1 passed
[EXIT=0] tests/test_search_contract.py::test_global_search_cache_isolates_site_variant_release_and_assembly -> 1 passed
[EXIT=0] tests/test_search_contract.py::test_search_cache_is_bound_to_resolved_release_and_assembly         -> 1 passed
[EXIT=0] tests/test_search_contract.py::test_search_without_a_published_release_fails_before_cache_lookup   -> 1 passed
```

全量三文件：`47 passed, 2 warnings in 2.33s`，EXIT=0（见 `.validation/ablation/cache/baseline_and_ablation.log`）。

### B. 消融套件关键输出（`-s`，EXIT=0，9 passed）

```
ABLATION-RESULT CTX-01.control_internal_bypass {"external_cache_awaited": true, "internal_cache_awaited": false, ...}
ABLATION-RESULT CTX-01.ablation_remove_bypass_keep_site_variant {"external_key": "cache:search:global:59117fc35b97", "internal_key": "cache:search:global:a456a517c0c0", "internal_loader_calls": 1, ...}
ABLATION-RESULT CTX-01.ablation_remove_bypass_drop_site_variant {"external_key": "cache:search:global:62bc4da601b2", "internal_key": "cache:search:global:62bc4da601b2", "internal_loader_calls": 0, ...}
ABLATION-RESULT CTX-02.control {"keys": ["cache:search:global:59117fc35b97", "cache:search:global:602108ea7385"], "second_loader_calls": 1, ...}
ABLATION-RESULT CTX-02.ablation_drop_release_id {"keys": ["cache:search:global:2121ac37135d", "cache:search:global:2121ac37135d"], "second_loader_calls": 0, ...}
ABLATION-RESULT CTX-03.control {"keys": ["cache:search:global:59117fc35b97", "cache:search:global:94fb17cd5eac"], "second_loader_calls": 1, ...}
ABLATION-RESULT CTX-03.ablation_drop_assembly_id {"keys": ["cache:search:global:7c3ed06eb75f", "cache:search:global:7c3ed06eb75f"], "second_loader_calls": 0, ...}
ABLATION-RESULT params_in_key.control {"keys": ["cache:k:b88cd59238f9", "cache:k:f9457cce356d"], "store_size": 2}
ABLATION-RESULT params_in_key.ablation_drop_hash {"store_size": 1}
ABLATION-RESULT sorted_params.ablation_no_sort {"forward": "cache:x:d8497d9d8277", "reverse": "cache:x:d5b8aed26525"}
ABLATION-RESULT unknown_key_param.ablation_guard_removed {"decorated": "load"}
ABLATION-RESULT cache_control.control {"header": "private, no-store", "vary": null}
ABLATION-RESULT cache_control.ablation_mute_write {"header": null}
ABLATION-RESULT key_scope.present {"base_params": {"assembly_id": 11, "cursor": null, "limit": 20, "query": "Glyma", "release_id": 7, "site_variant": "external", "types": ["gene"]}, "distinct": {"filters_types": true, "limit": true, "pagination_cursor": true, "query": true}}
ABLATION-RESULT legacy_federated_key {"key": "search:8af2ac4de7585c6b2af2e574f7219f24616c296095c51df6a266a8650d51f62f", "params": ["query", "sources"], "sorted_sources_same": true}
```

### C. 惰性解析消融（临时生产改动，已还原）

`git diff -- apps/api/app/services/search_service.py`（完整见 `.validation/ablation/cache/lazy_resolve_ablation.diff`）：

```diff
@@ -342,8 +342,7 @@ class SearchService:
         active_types = _normalize_active_types(types)
-        context = await resolve_release_context(db)
-        release_id = context.release_id
+        release_id = None  # ABLATION: release resolved lazily, after cache lookup
@@ -600,6 +599,8 @@ class SearchService:
             # each other's data under the same query key.
+            context = await resolve_release_context(db)  # ABLATION: lazy resolve
+            release_id = context.release_id
             return GlobalSearchResponse.model_validate(await load())
@@ -607,6 +608,8 @@ class SearchService:
             params=cache_params,
         )
+        context = await resolve_release_context(db)  # ABLATION: after cache
+        release_id = context.release_id
         return GlobalSearchResponse.model_validate(payload)
```

消融下两条锚定测试翻转（EXIT=1）：

```
tests/test_search_contract.py::test_search_without_a_published_release_fails_before_cache_lookup
  AssertionError: Expected mock to not have been awaited. Awaited 1 times.
tests/test_search_contract.py::test_search_cache_is_bound_to_resolved_release_and_assembly
  E assert None == 7
```

还原证明：`git checkout -- apps/api/app/services/search_service.py` 后

```
$ git diff --stat -- apps/api
（空）
$ pytest tests/test_search_contract.py -q
13 passed
```

### D. 新增文件清单（均未提交）

- `apps/api/tests/test_ablation_cache_site.py`（9 tests，草稿消融套件）
- `.validation/ablation/cache/baseline_and_ablation.log`
- `.validation/ablation/cache/lazy_resolve_ablation.diff`
- `.validation/ablation/cache/lazy_resolve_run.log`
- `docs/dev/ablation/2026-09-26/cache-site.md`（本报告）
