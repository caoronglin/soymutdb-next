# SoyMutDB 可优化清单与执行分派（2026-09-26）

来源：`docs/dev/ablation/2026-09-26/README.md` 的 6 个 GAP + 5 个 INERT + 1 条弱断言发现。
本文件是**执行清单**；每条给出负责子代理、冻结契约、验收判据、验证命令与回滚点。

## 0. 并发前提（所有子代理必须遵守）

- 实验期间存在**并发外部会话**：HEAD 已被推进多次（`8e78116fd` → `412ffc91f`），工作树有大量他人未提交改动（admin/web/眼睛/jbrowse 文档等）。
- 规则：**不要** `git checkout` / `git stash` / `git reset` 任何他人文件；改前先 `read`；只动自己负责的文件；**不提交**。
- 沙箱 `$HOME` 只读：跑 pnpm 前 `source .validation/ablation/artifact/pnpmenv.sh`。
- PostgreSQL 16 常驻 `127.0.0.1:55432`（`soymutdb` trust）；每个代理用独立库 `abl_<domain>`。

## 1. 清单

| ID | 来源 | 级别 | 优化内容 | 负责 | 关键文件 |
| --- | --- | --- | --- | --- | --- |
| OPT-01 | G1 / ASM-04 | **P1** | 搜索服务消费 `gene_crosswalks`，浮出显式跨版本关联 | A | `apps/api/app/services/search_service.py`、`apps/api/app/schemas/search.py` |
| OPT-02 | I2 | P2 | `site_variant` 纵深防御字段补契约测试与注释 | A | 同上 |
| OPT-03 | G3 | **P1** | 联邦搜索缓存键纳入 release / assembly / site_variant | B | `apps/api/app/search/cache.py`、`search/aggregator.py`、`api/v1/search.py` |
| OPT-04 | I1 | P2 | 外部搜索冗余 `public_id IS NOT NULL` 谓词固化/注释 | B | `apps/api/app/services/search_service.py` |
| OPT-05 | G2 / UI-02 | **P1** | internal 搜索 client + internal 结果 UI（双 id 展示/复制） | C | `packages/api-client/src/search.ts`、`apps/web/src/views/SearchView.vue` |
| OPT-06 | W4 弱断言 | P2 | `SearchResult` 补 `match_type`/`cross_version` 并收紧值敏感断言 | C | `packages/api-client/src/search.ts`、`apps/web/src/ablation/*` |
| OPT-07 | I3 | **P1** | 双站扫描要求 `external/*.html` 必需 | D | `scripts/check_site_artifact_isolation.py` |
| OPT-08 | I5 | **P1** | verifier 使用多哨兵（含 `internal.soymutdb.invalid`） | D | `scripts/verify-site-variant-artifacts.sh`、`scripts/check_site_artifact_isolation.py` |
| OPT-09 | I4 | P2 | 空目录名中的哨兵也要检查 | D | `scripts/check_site_artifact_isolation.py` |
| OPT-10 | G4 / G5 | **P1** | 补实体详情页 E2E；解除 JBrowse 深链无条件 `test.skip` | E | `e2e/tests/*.spec.ts` |
| OPT-11 | G6 | **P1** | internal 站 E2E config：登录 → internal_id 检索 → 详情 | E | `e2e/playwright-*.config.ts`、`e2e/tests/*.spec.ts` |

## 2. 冻结契约（跨代理，不得各自发明）

### OPT-01（A 产出，C 消费）

```python
class CrossVersionLink(BaseModel):
    gene_accession: str
    assembly_id: int | None = None
    assembly_name: str | None = None
    assembly_version: str | None = None
    relation_type: str
    provenance_source: str
    match_type: MatchType = MatchType.CROSS_VERSION   # 该枚举终于有生产者

class GeneResultItem(BaseModel):      # 现有类名以源码为准
    ...
    cross_version: list[CrossVersionLink] = Field(default_factory=list)
```

- 方向：`source→target` 与 `target→source` **双向**都要查。
- 作用域：crosswalk 自带 `release_id` 时按 release 过滤；为 `NULL` 视为通用。
- **不新增结果行**（不改变分页/total_count）；v4 exact 命中保持 `match_type=exact`，关联只挂在 `cross_version` 列表。
- 无 provenance 的相似基因**不得**进入该列表（ASM-05 不回归）。

### OPT-05（C 产出）

```ts
// packages/api-client/src/search.ts
export function internalSearch(query: string, opts?: {...}): Promise<InternalSearchResponse>
// 打 /api/v1/search/internal，带 Authorization；类型取自 generated/openapi.d.ts 的 InternalMutantSearchItem
```

- UI 仅在内站变体渲染 internal 结果；每行展示 `public_id` 与 `internal_id`，并各有一个复制控件（`data-testid="copy-public-id"` / `data-testid="copy-internal-id"`）。
- 外站路径行为零变化（回归既有 `SearchView.test.ts`）。

## 3. 每条验收判据（DoD）

1. 目标文件已 `read`；改动最小、无无关格式化。
2. 新增或收紧**回归测试**，先证明"改前失败/缺口存在"，再证明"改后通过"。
3. 至少跑：本包窄门禁 + 对应消融锚点。
4. 交付四要素：已完成（带命令+退出码+输出）/ 未完成 / 未验证 / 阻塞。
5. `git status --short` 中只出现自己负责的文件（外加他人既有改动）。

## 4. 验证命令基线（改后必须仍绿）

```bash
# A / B
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_api' \
  .venv/bin/python -m pytest tests/test_search_database_integration.py tests/test_search_contract.py tests/test_mutants.py tests/test_cache.py -q -p no:cacheprovider
# A 的 G1 目标断言
cd apps/api && SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/abl_opt_api' \
  .venv/bin/python -m pytest tests/test_ablation_assembly_scope_and_crossversion.py -q -p no:cacheprovider -k must_be_exposed
# C
cd apps/web && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run src/views/SearchView.test.ts src/views/Mutants.test.ts src/ablation --pool=threads --poolOptions.threads.maxThreads=2
# D
python3 -m unittest scripts.test_site_artifact_isolation -v
python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external --internal-root apps/web/dist/internal --sentinel 'noindex, nofollow, noarchive' --sentinel 'internal.soymutdb.invalid'
# E
cd e2e && ./node_modules/.bin/playwright test -c playwright-public.config.ts
```

## 5. 出口

- 5 份优化小结（追加到本目录 `OPTIMIZATION-REPORT.md` 或各自 `opt-*.md`）。
- 协调者逐条复跑验收命令，未通过则回退该项并记入未完成清单。
- 全部完成后重跑消融汇总中的对应场景，确认 GAP 关闭且无新回归。
