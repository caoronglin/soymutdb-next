# OPT-A 优化小结：跨版本关联浮出（OPT-01）与 `site_variant` 缓存参数契约（OPT-02）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 仓库：`/mnt/data02/T25ronglin/code/web`
- 基准 HEAD：`202ae7f92148045e45f8d2d0fb028f2874830a3d`（改动未提交，工作树与他人改动共存）
- 日期：2026-09-26
- 负责代理：A（文件白名单：`apps/api/app/services/search_service.py`、`apps/api/app/schemas/search.py`、`apps/api/tests/test_ablation_assembly_scope_and_crossversion.py`、`apps/api/tests/test_opt_crossversion_links.py`、本文件）
- 解释器：`apps/api/.venv/bin/python`（Python 3.14.6，pytest 9.1.1）
- 数据库：PostgreSQL 16 @ `127.0.0.1:55432`（soymutdb trust），每次重建独立库 `abl_opt_a`

---

## 1. 目标

1. **OPT-01（P1，真修复）**：`GeneCrosswalk`（`app/models/genomic.py:264`）从未被 `search_service` 导入，导致 `MatchType.CROSS_VERSION` 没有任何生产者；增删一行 crosswalk 对搜索输出零影响（GAP / ASM-04）。
   按冻结契约实现：新增 `CrossVersionLink` schema，基因结果项挂 `cross_version` 列表；`search_service` 仅对命中的基因做**一次批量查询**、**双向**解析 crosswalk；crosswalk 自带 `release_id` 非空时按其过滤，`NULL` 视为通用；**不新增结果行**（分页/`total_count` 不变），命中项自身保持 `match_type=exact`；无 crosswalk 的相似基因不得进入列表（ASM-05 不回归）。
2. **OPT-02（P2）**：给共享缓存参数中的 `site_variant` 字段补一条锚定回归测试与代码注释，把它钉为**有意为之的纵深防御**（对应 `cache-site.md` 的 INERT-1 / I2），防止后续被当作“死字段”删掉。

---

## 2. 改动（file:line）

### 2.1 `apps/api/app/schemas/search.py`

- `:66-86` 新增 `CrossVersionLink`（冻结契约字段原样落地）：`gene_accession`、`assembly_id|None`、`assembly_name|None`、`assembly_version|None`、`relation_type`、`provenance_source`、`match_type=MatchType.CROSS_VERSION`。
- `:109` `SearchResultItem` 新增 `cross_version: list[CrossVersionLink] = Field(default_factory=list)`（默认空，向后兼容旧客户端/既有响应）。

### 2.2 `apps/api/app/services/search_service.py`

- `:32` 导入 `CrossVersionLink`；`:29` 导入 `GeneCrosswalk`；`:23` 导入 `sqlalchemy.orm.aliased`。
- `:366-380` `cache_params` 的 `site_variant` 增加**纵深防御注释**并指向本仓 `cache-site.md I2` 与锚定测试（OPT-02 代码侧）。
- `:530-545` `load()` 内、最终 `hits` 截断后：收集命中基因的 `gene_pk`，调用一次 `_resolve_cross_version_links`；注释明确“链接是命中项的元数据，不产生新行，分页/`total_count` 已定稿”。
- `:585-587` 构造 `SearchResultItem` 时填 `cross_version=...get(...)`。
- `:793` `_search_genes` 的命中 metadata 增加 `"gene_pk"`（外部/内部变体都写；仅内部元数据，不进公开契约）。
- `:822-903` 新增 `_resolve_cross_version_links`：
  - 单条 `select`，`aliased(Gene)×2 + aliased(Assembly)×2`；
  - `or_(source_gene_id.in_(matched), target_gene_id.in_(matched))` 命中两个方向；
  - `or_(release_id.is_(None), release_id == 当前release)` 作用域过滤；
  - 按 `(accession, relation_type, provenance_source)` 去重，避免同一对基因重复行产生重复链接；
  - 无命中基因时直接返回 `{}`，不发查询。

### 2.3 测试（白名单内新增/扩展）

- `apps/api/tests/test_ablation_assembly_scope_and_crossversion.py:229-249` **扩展** ASM-04 红→绿测试：在原“target 必须从搜索浮出 + 必须出现 CROSS_VERSION”语义不变的前提下，改为按冻结契约断言——链接在 `cross_version` 内、断言 `total_count==1`/`len(results)==1`（不新增行）、命中项 `match_type` 仍为 `exact`、链接携带 `provenance_source` 与目标 assembly 版本。原断言的 `ids`/`match_types` 在“不新增行”契约下必须落到嵌套字段，故此处必然要改；原失败行 `assert 'Glyma.05G000100' in {'Glyma.01G000100'}` 保留为红证据。
- `apps/api/tests/test_opt_crossversion_links.py`（新增，4 测试）：
  - `test_opt01_similarity_only_genes_have_empty_cross_version`：纯相似、无 crosswalk → 两行均 `TEXT` 且 `cross_version == []`（ASM-05 负向）。
  - `test_opt01_crosswalk_is_resolved_in_both_directions`：一行 crosswalk，查 source 得 target 链接、查 target 得 source 链接；两次都 `total_count==1`、自身 `match_type==exact`、链接 `match_type==cross-version`（双向 + 不新增行）。
  - `test_opt01_null_release_is_generic_and_foreign_release_is_skipped`：`release_id=NULL` 通用行被采纳；指向另一 release 的行被过滤（作用域）。
  - `test_opt02_site_variant_is_pinned_in_global_search_cache_params`：捕获 `get_or_set` 的 `params`，断言 `site_variant` 字段存在且为 `external`（OPT-02 锚定）。

---

## 3. 红绿证据（命令 + 退出码 + 输出）

### 3.1 红：修复前 ASM-04 必须失败

```bash
cd /mnt/data02/T25ronglin/code/web/apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_a' \
  .venv/bin/python -m pytest \
  "tests/test_ablation_assembly_scope_and_crossversion.py::test_asm04_crosswalk_must_be_exposed_as_cross_version" \
  -q -p no:cacheprovider -s
# EXIT=1
# [ASM-04 ROWS] crosswalk_rows=1 target=2
# [ASM-04 DESIRED] ids={'Glyma.01G000100'} match_types={<MatchType.EXACT: 'exact'>}
# E   AssertionError: crosswalk target not surfaced by search
# E   assert 'Glyma.05G000100' in {'Glyma.01G000100'}
# 1 failed, 1 warning
```

### 3.2 绿：修复后同一测试通过

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_a' \
  .venv/bin/python -m pytest \
  "tests/test_ablation_assembly_scope_and_crossversion.py::test_asm04_crosswalk_must_be_exposed_as_cross_version" \
  -q -p no:cacheprovider -s
# EXIT=0
# [ASM-04 ROWS] crosswalk_rows=1 target=2
# [ASM-04 DESIRED] ids={'Glyma.01G000100'} match_types={<MatchType.EXACT: 'exact'>} links=[('Glyma.05G000100', 'cross-version')]
# 1 passed, 1 warning
```

### 3.3 新增定向测试全绿（含负向/双向/作用域/OPT-02）

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_a' \
  .venv/bin/python -m pytest tests/test_opt_crossversion_links.py -q -p no:cacheprovider -s
# EXIT=0
# [OPT01 NEG] results=2 match_types=['text', 'text'] links=[]
# [OPT01 BOTH] forward={'Glyma.01G000100': ['Glyma.05G000100']} reverse={'Glyma.05G000100': ['Glyma.01G000100']}
# [OPT01 SCOPE] generic=['Glyma.05G000100'] foreign=[]
# [OPT02] cache_params={'query': 'Glyma', 'types': ['gene'], 'cursor': None, 'limit': 20, 'site_variant': 'external', 'release_id': 7, 'assembly_id': None}
# 4 passed, 1 warning
```

### 3.4 消融套件 + 新测试一起

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_a' \
  .venv/bin/python -m pytest tests/test_opt_crossversion_links.py \
  tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider
# EXIT=0  -> 11 passed, 1 warning
```

### 3.5 DoD 锚点集仍绿

```bash
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_a' \
  .venv/bin/python -m pytest tests/test_search_database_integration.py \
  tests/test_search_contract.py tests/test_mutants.py -q -p no:cacheprovider
# EXIT=0  -> 36 passed, 1 warning in 3.56s
```

### 3.6 静态检查

```bash
cd apps/api && .venv/bin/python -m ruff check app/services/search_service.py tests/test_opt_crossversion_links.py
# EXIT=0 -> All checks passed!
```

---

## 4. 未验证 / 已知边界

1. **真实 Redis**：测试环境缓存读写失败回退 DB（日志 `cache_read_failed_fallback_to_db`），`cross_version` 的 Redis 命中路径未单独验证；但其已随 `GlobalSearchResponse.model_dump(mode="json")` 进缓存 payload，序列化字段即公开 schema。
2. **OpenAPI/客户端契约**：`CrossVersionLink` 未同步 `packages/api-client` 生成物（属 OPT-06 / C 的工作面）。
3. **`site_variant` 字段可达性**：internal 仍走旁路，故 OPT-02 只钉“字段存在”，未在本项内验证“删字段即串键”的翻转（`cache-site.md` S2 已证）。
4. **`test_ablation_cache_site.py::test_GAP_legacy_federated_searchcache_key_ignores_biological_scope` 当前失败**：由并发代理 B 正在改的 `app/search/cache.py`（`make_key` 新增必填 `site_variant`）引起，不在本白名单，未处理。
5. **未被本项覆盖**：`internal_search`（非 `global_search`）未挂 `cross_version`；`Assembly` 名称/版本以链接目标为准展示，未做前端渲染。
6. 未提交（按并发规则）。

---

## 5. 回滚点

- 新增文件（直接删除即可）：
  - `apps/api/tests/test_opt_crossversion_links.py`
  - `docs/dev/ablation/2026-09-26/opt-a-crossversion.md`
- 生产改动（2 文件，可用 `git diff -- <path>` 精确定位回滚；未提交，故**不要** `git checkout` 他人文件）：
  - `apps/api/app/schemas/search.py`：删除 `CrossVersionLink` 与 `SearchResultItem.cross_version`。
  - `apps/api/app/services/search_service.py`：回滚导入、`cache_params` 注释、`load()` 的解析调用与 `cross_version=` 传参、metadata 的 `gene_pk`、`_resolve_cross_version_links` 方法。
- 测试文件 `test_ablation_assembly_scope_and_crossversion.py` 为未跟踪文件（`??`），其 ASM-04 断言如需回到 HEAD 语义可改回 `ids`/`match_types` 顶层断言（注意与“不新增行”契约冲突）。
- 生产改动最小回滚粒度 = 删除 `SearchResultItem.cross_version` 字段：旧响应形状完全恢复（新字段有默认值，序列化多一个空列表）。

---

## 6. 结论

- OPT-01 的 GAP 已关闭：`MatchType.CROSS_VERSION` 首次拥有真实生产者，且生产者只认 `gene_crosswalks` 的 provenance（相似性不产生链接）。
- OPT-02 完成：字段 + 注释 + 锚定测试三位一体。
- DoD：红→绿证据（§3.1/§3.2）、锚点集 36 passed（§3.5）、负向测试（§3.3 NEG）、双向 + NULL/外来 release 测试（§3.3 BOTH/SCOPE）、白名单外零改动（仅 `git status` 中他人既有改动）。
