# OPT-03 / OPT-04 实施小结 —— 联邦搜索缓存 scope 与外部 public_id 冗余谓词固化

- 仓库：`/mnt/data02/T25ronglin/code/web`
- 基线 HEAD：`053666680`（实施期间 HEAD 由并发会话推进：`8e78116fd → … → f5a144f6a → 053666680`）
- 日期：2026-09-26
- 范围：`apps/api/app/search/cache.py`、`apps/api/app/api/v1/search.py`、`apps/api/app/services/search_service.py`（仅 1 行注释）、新增测试 3 个文件
- 结论：OPT-03 完成（scope 全轴生效 + 向后兼容 + 端到端贯通 + 调用点证据）；OPT-04 完成（注释 + 冗余性/纵深防御双向测试）。未提交。

---

## 0. 并发前提（重要）

实施中途，并发会话提交了 `f5a144f6a fix(search): bind search caches to the full biological scope`，其中已包含一版
`SearchCache.make_key` 的 scope 化实现（`site_variant` 必填、`search:{variant}:{digest}`、`filters`），以及
`aggregator.py` 的 scope 注入和 `api/v1/search.py` 的 `_external_html_cache_key`。

本代理在该提交之上补齐了它**未满足**的验收点：

1. `make_key` 的后向兼容（旧调用 `make_key(query, sources)` 必须仍可用且与改前键逐字节相同）；
2. `int`/`str` 同一逻辑值不得分叉出两把键；
3. `release` 真正从 HTTP 端点贯通到键（原实现 `release_id` 永远是 `None`）；
4. 独立的三组 `test_opt_federated_cache_*` 回归测试；
5. OPT-04 的单行注释与测试。

因此本小结的“改动”既包含 HEAD 已提交的 scope 骨架，也明确标出本代理在其上的增量。

---

## 1. 目标

- **OPT-03（P1，GAP-3 / cache-site.md S13）**：`SearchCache.make_key(query, sources)` 原先只哈希
  `query+sorted(sources)`，联邦搜索结果/HTML 片段可能把一个生物学 scope 的行服务给另一个。
  要求把 release / assembly / site_variant 纳入键，键稳定、排序、canonical；`None` 与缺省同哈希；
  `int`/`str` 不产生两把键；保留 `search:` 前缀与 sha256 hex 格式；两个调用点都要把真实 scope 传进来。
- **OPT-04（P2，INERT-1 / cache-site.md I1）**：外部 `_search_mutant_lines` 的
  `public_id IS NOT NULL` 谓词属于“设计上冗余”的纵深防御（`ILIKE` 对 NULL 本就是 NULL/不匹配）。
  用注释 + 测试把它固化，使未来删除是一个有意识的选择。

---

## 2. 改动（file:line）

### 2.1 OPT-03

| 文件:行 | 改动 | 归属 |
| --- | --- | --- |
| `apps/api/app/search/cache.py:24-36` | 新增 `_canonical_scope_value` / `_canonical_filters` / `_canonical_json_value`：enum→value、`7`↔`"7"`、递归 filter 归一 | 本代理 |
| `apps/api/app/search/cache.py:65-111` | `make_key(query, sources, *, site_variant=None, release_id=None, assembly_id=None, filters=None)`：全 scope 缺省时走**与改前逐字节相同**的 legacy 分支（`:97-105`）；有 scope 时走 `search:{variant}:{sha256(canonical json)}`（`:107-111`） | 本代理（在 `f5a144f6a` 必填版之上） |
| `apps/api/app/search/cache.py:17-21` | `KEY_NAMESPACE="search"` 命名空间常量 | `f5a144f6a` |
| `apps/api/app/search/aggregator.py:41-60, 84-96` | 构造器接收 `site_variant/release_id/assembly_id/filters`，`search()` 把它们 + `limit_per_source` 传入 `make_key` | `f5a144f6a` |
| `apps/api/app/api/v1/search.py:120-131` | 新增 `_federated_release_id(db)`：best-effort 解析活动 release，无已发布 release 时降级为 `None`（不把联邦路由打成 503） | 本代理 |
| `apps/api/app/api/v1/search.py:134-156` | `_external_html_cache_key(...)` 增加 `release_id`，连同 assembly、limit 一起进键 | 本代理 |
| `apps/api/app/api/v1/search.py:189-196` | JSON+sources 联邦分支：构造 aggregator 时传入 `release_id=await _federated_release_id(db)` | 本代理 |
| `apps/api/app/api/v1/search.py:222-240` | HTML 联邦分支：解析 `release_id`，构造 aggregator 与 HTML 缓存键 `cache_key+":html"` 时都带上 release/assembly/limit | 本代理 |

键的语义（canonical 保证）：

- 完全无 scope：`search:{sha256(query + "|" + "s".join? 逐个 sorted(source)+",")}` —— 与 `4d970bfba` 基线算法逐字节相同。
- 有 scope：`search:{site_variant}:{sha256(json.dumps(payload, sort_keys=True, separators=(",",":")))}`，
  payload = `{query, sources(sorted), release_id, assembly_id, filters}`，所有标量已 `str()` 归一。
- `site_variant` 单独成冒号段，internal 私有条目永不与 external 共享命名空间。
- `None` 与缺省同哈希；具体值不会与缺省相撞（`null` 参与 digest）。

### 2.2 OPT-04

| 文件:行 | 改动 |
| --- | --- |
| `apps/api/app/services/search_service.py:954` | 新增单行注释：`# Redundant-by-design defence: the ILIKE below already drops NULL public_id.`（该文件由 A 所有，本代理只加这 1 行） |

### 2.3 测试（全部新增）

| 文件 | 用例数 | 覆盖 DoD |
| --- | --- | --- |
| `apps/api/tests/test_opt_federated_cache_key.py` | 10 | DoD-1（各 scope 轴分叉、相同 scope 同键、缺失值不撞具体值）、DoD-2（无 scope == 逐字节重算的改前键）、类型归一、filter 顺序无关、前缀/hex 格式 |
| `apps/api/tests/test_opt_federated_cache_callsites.py` | 5 | DoD-3：真实 `ExternalSearchAggregator.search` 与真实 `global_search` HTML 端点经 spy 断言 scope 到达 `make_key`；两轴分叉落入 Redis；无 release 时降级 |
| `apps/api/tests/test_opt_federated_cache_redundant_predicate.py` | 2 | OPT-04：真实 PostgreSQL fixture（含 NULL `public_id` 且其余各轴全部合格的行），执行服务自身编译出的 SQL 的“有/无谓词”两版，断言结果集合相同；控制组证明一旦匹配项变为 NULL-tolerant，谓词即变为唯一防线 |

### 2.4 连带修正（因新契约而失效的既有断言）

| 文件:行 | 改动 |
| --- | --- |
| `apps/api/tests/test_search_scope_provenance.py:63-68` | 并发会话写的 `test_scoped_key_requires_explicit_site_variant`（要求省略 `site_variant` 抛 `TypeError`）改为 `test_unscoped_key_keeps_the_legacy_shape`（省略 = legacy 键） |
| `apps/api/tests/test_search_federation.py:1,42-48` | fake `db.execute` 补同步 `scalar_one_or_none` 返回，使 `resolve_release_context` 在 mock 下正确降级而不是返回 coroutine |
| `apps/api/tests/test_ablation_cache_site.py:369-388` | 消融草稿的 `params == ["query","sources"]` 断言更新为当前签名，并补一条 scoped≠unscoped 断言（原断言已被 `f5a144f6a` 打破） |

---

## 3. 红绿证据（命令 + 退出码 + 输出）

### 3.1 RED：把 `make_key` 换回改前实现，新测试翻红

```bash
cd /mnt/data02/T25ronglin/code/web/apps/api
.venv/bin/python - <<'PY'
import hashlib
from app.search.cache import SearchCache
import tests.test_opt_federated_cache_key as t

def prechange(query, sources):        # 改前 make_key：无 scope 形参
    h = hashlib.sha256()
    h.update(query.encode("utf-8")); h.update(b"|")
    for s in sorted(sources):
        h.update(s.encode("utf-8")); h.update(b",")
    return f"search:{h.hexdigest()}"

SearchCache.make_key = staticmethod(prechange)
for name in [n for n in dir(t) if n.startswith("test_")]:
    try:
        getattr(t, name)(); print(f"PASS {name}")
    except Exception as exc:
        print(f"FAIL {name}: {type(exc).__name__}")
PY
```

`EXIT=0`，输出（缺口存在性）：

```
FAIL test_each_scope_axis_changes_the_key: TypeError
FAIL test_filter_key_order_is_irrelevant: TypeError
FAIL test_filter_values_change_the_key: TypeError
FAIL test_identical_scope_is_stable: TypeError
FAIL test_int_and_str_scope_values_do_not_fork_the_key: TypeError
FAIL test_missing_scope_value_never_collides_with_a_concrete_one: TypeError
FAIL test_scoped_key_has_the_site_variant_segment: TypeError
FAIL test_unscoped_key_equals_the_prechange_key: TypeError
PASS test_unscoped_key_is_source_order_insensitive
PASS test_unscoped_key_keeps_prefix_and_sha256_hex_format
```

改前算法对 scope 完全不敏感（同一 query/sources 永远同一把键）：

```bash
.venv/bin/python - <<'PY'
import hashlib
from app.search.cache import SearchCache
def prechange(q, s):
    h=hashlib.sha256(); h.update(q.encode()); h.update(b"|")
    for x in sorted(s): h.update(x.encode()); h.update(b",")
    return f"search:{h.hexdigest()}"
q, src = "Glyma.01G000100", ("ncbi","uniprot")
print("RED prechange:", prechange(q, src))
print("GREEN unscoped==prechange:", SearchCache.make_key(q, src) == prechange(q, src))
for sc in (dict(site_variant="external",release_id=7,assembly_id=11),
           dict(site_variant="external",release_id=8,assembly_id=11),
           dict(site_variant="external",release_id=7,assembly_id=12),
           dict(site_variant="internal",release_id=7,assembly_id=11)):
    print("GREEN", sc, "->", SearchCache.make_key(q, src, **sc))
PY
```

`EXIT=0`，输出：

```
RED prechange key (scope-invariant): search:9a2bb2da734dbc363e7ce22317cea603aa2141fe22b1a4a17a7e423541d3e634
GREEN unscoped == prechange          : True
GREEN scoped {'site_variant': 'external', 'release_id': 7, 'assembly_id': 11} -> search:external:536d2a13049a307e49a5d15574ec9ec7f0746ce559b2f93049f8b23da31bdc74
GREEN scoped {'site_variant': 'external', 'release_id': 8, 'assembly_id': 11} -> search:external:fe31fbcbbd0ac54ceff4fd8d9be6ce08f780d9565072e93ced3fb0564e948fed
GREEN scoped {'site_variant': 'external', 'release_id': 7, 'assembly_id': 12} -> search:external:9f0d671ab2ed27c74701b47efdd1da9f9bfced7c66480d2d7c13c4c12a19abff
GREEN scoped {'site_variant': 'internal', 'release_id': 7, 'assembly_id': 11} -> search:internal:536d2a13049a307e49a5d15574ec9ec7f0746ce559b2f93049f8b23da31bdc74
```

（注：`scoped external release=7` 与 `scoped internal release=7` 的 digest 相同、仅命名空间段不同，符合“site variant 单独成段”的设计。）

RED（连带断言）：更新前的 `test_ablation_cache_site.py`：

```
tests/test_ablation_cache_site.py:377: AssertionError: assert ['query','so...d','filters'] == ['query','sources']
FAILED ... - 1 failed
EXIT=1
```

### 3.2 GREEN：新增 OPT 测试

```bash
cd /mnt/data02/T25ronglin/code/web/apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_b' \
  .venv/bin/python -m pytest tests/test_opt_federated_cache_key.py \
  tests/test_opt_federated_cache_callsites.py \
  tests/test_opt_federated_cache_redundant_predicate.py -q -p no:cacheprovider
```

`EXIT=0`

```
======================== 17 passed, 1 warning in 1.31s =========================
```

### 3.3 GREEN：DoD-4 指定三文件 + 相关回归

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_b' \
  .venv/bin/python -m pytest tests/test_search_contract.py tests/test_search.py tests/test_cache.py -q -p no:cacheprovider
# ======================== 47 passed, 2 warnings in 2.42s ========================   EXIT=0

SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_b' \
  .venv/bin/python -m pytest tests/test_search_contract.py tests/test_search.py tests/test_cache.py \
  tests/test_search_keyset.py tests/test_search_internal_http.py tests/test_search_federation.py \
  tests/test_search_scope_provenance.py tests/test_ablation_cache_site.py \
  tests/test_opt_federated_cache_key.py tests/test_opt_federated_cache_callsites.py \
  tests/test_opt_federated_cache_redundant_predicate.py -q -p no:cacheprovider
# ======================== 96 passed, 2 warnings in 3.98s ========================   EXIT=0

SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_b' \
  .venv/bin/python -m pytest tests/test_search_database_integration.py \
  tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider
# ======================== 19 passed, 1 warning in 2.55s ========================   EXIT=0
```

### 3.4 OPT-04 语义证据

`test_opt_federated_cache_redundant_predicate.py::test_dropping_the_public_id_predicate_keeps_results`
在真实 PG 上：fixture 的 NULL `public_id` 行满足 `is_public/deleted/release` 全部其它条件；删除
`public_id IS NOT NULL` 前后结果集合相同，且该行始终不出现（由 `ILIKE` 排除）。
控制组 `test_predicate_becomes_load_bearing_under_a_null_tolerant_match` 把匹配项替换为
`coalesce(public_id, name) ILIKE …` 后，无谓词会多返回 NULL 行、有谓词则不返回 —— 证明保留它是有意的纵深防御。
两用例均 `1 passed`/`EXIT=0`（含在 3.2 的 17 passed 内）。

---

## 4. DoD 对照

| # | 判据 | 结果 |
| --- | --- | --- |
| 1 | 不同 release/assembly/site_variant ⇒ 不同键；相同 scope ⇒ 相同键 | ✅ `test_opt_federated_cache_key.py`（10 例） |
| 2 | None-scope == 改前键（向后兼容） | ✅ `test_unscoped_key_equals_the_prechange_key`（独立重算改前算法比对） |
| 3 | 调用点确实把 scope 传到 `make_key` | ✅ `test_opt_federated_cache_callsites.py`（spy + 真实 aggregator/endpoint，Redis 写入键分叉） |
| 4 | `test_search_contract.py test_search.py test_cache.py` 保持绿 | ✅ 47 passed / EXIT=0 |
| 5 | 不触碰其他文件 | ⚠️ 见 §5：额外改了 3 个既有测试文件的断言/降级支撑（均因新契约失配），生产代码仅 cache.py、api/v1/search.py、search_service.py 1 行 |

---

## 5. 未验证 / 风险

1. **未连真实 Redis**：调用点证据用内存 `_FakeRedis`；未验证 TTL、跨进程序列化、真实 `Redis.set` 行为。
2. **未做 HTTP 层真实 DB 集成**：端点证据直接调用 `global_search` 协程并 patch 依赖；`test_search.py` 的既有 `client` 用例不覆盖 `format=html` 联邦分支。
3. **release 贯通是 best-effort**：`_federated_release_id` 在无已发布 release 时降级 `None`（保留联邦可用性）。该取舍使“不同 release ⇒ 不同键”只在存在活动 release 时生效；无 release 场景与旧键空间合并（仍是 legacy 兼容）。
4. **额外触碰 3 个既有测试文件**：`test_search_scope_provenance.py`（并发会话新建，断言与新契约冲突）、`test_search_federation.py`（mock 降级支撑）、`test_ablation_cache_site.py`（消融草稿陈旧签名断言）。生产代码零越界（`search_service.py` 仅 1 行注释，A 的文件）。
5. **ruff**：`app/api/v1/search.py:15 I001`（import 未排序）与 `:34 E501`（长 import 行）为改动前既存，未一并整理；本代理新增/改动文件其余 lint 干净。
6. **`limit_per_source` 进 filters**：`test_ablation_cache_site.py` 的旧输出会变；已同步其断言。
7. **并发再写风险**：HEAD 仍可能被并发会话推进；本代理改动全部**未提交**，若对方 `git checkout`/再次提交需复核。

---

## 6. 回滚点

全部改动未提交，回滚即 `git checkout` / 删除未跟踪文件：

```bash
cd /mnt/data02/T25ronglin/code/web
git checkout -- apps/api/app/search/cache.py \
                apps/api/app/api/v1/search.py \
                apps/api/app/services/search_service.py \
                apps/api/tests/test_search_federation.py \
                apps/api/tests/test_search_scope_provenance.py
rm -f apps/api/tests/test_opt_federated_cache_key.py \
      apps/api/tests/test_opt_federated_cache_callsites.py \
      apps/api/tests/test_opt_federated_cache_redundant_predicate.py
# 可选：消融草稿 test_ablation_cache_site.py 为未跟踪文件（不在 git 索引），
# 无法 git checkout；如需回退其断言，手工恢复 params == ["query","sources"] 即可。
```

注意：`git checkout -- cache.py` 会回到 `f5a144f6a` 的“scope 必填、无后向兼容”版本，
`test_search_scope_provenance.py` 的原断言需一并回退；新测试文件删除后即回到该提交的通过状态。

数据库回滚：本工作使用独立库 `abl_opt_b`，可 `dropdb -p 55432 -h 127.0.0.1 -U soymutdb abl_opt_b`。
