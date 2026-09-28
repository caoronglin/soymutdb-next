# SoyMutDB 全项目消融实验汇总（2026-09-26）

- **对象**：工作树 `HEAD 8e78116fd`（`8e78116fdbcda533a9399f36680cacedcc08dac2`），未提交。
- **HEAD 变动说明**：实验期间一个**并发外部会话**提交了 `177d36ccc`（治理：断开 genome-view-model 环、删未用依赖）与 `0efde84d6`（handoff 记录），HEAD 前进到 `0efde84d6`。关键结论已在新 HEAD 复跑复核（见 §5 末行），判读不变。
- **执行方式**：总控（协调者）+ 6 个并行子代理（模型 `nwafu/DeepSeek-V4.1-Flash`），每个工作流独立库 / 独立目录，互不重叠。
- **判定口径**：`GUARD-ACTIVE`（消融单一因素后行为翻转＝守卫在起作用）／`GUARD-INERT`（消融后不变＝可能是死代码或冗余）／`GAP`（对照就已经失败＝当前缺陷）。
- **证据要求**：每条结论附精确命令 + 退出码 + 关键输出行；静态推理（E2）与真实运行（E1）分开标注。
- **计划**：`PLAN.md`。分报告：本目录下 6 个文件。

> 本文件是**审计结论**，不是修复声明。运行实验时未持久修改任何生产源码；新增物仅为消融 harness 与报告。

## 1. 总结论

| 指标 | 数量 |
| --- | --- |
| 场景总数 | 51 |
| `GUARD-ACTIVE` | **43** |
| `GUARD-INERT` | **5** |
| `GAP` | **6** |

结论分两面：

1. **大多数不变量是"真守卫"**：公开身份投影、草稿/禁运/未发布负例、assembly 作用域与全量歧义判定、缓存三要素隔离、internal 旁路与 `private,no-store`、VCF assembly 身份与选中样本身份、finalize 汇总清理与跨装配分区、双站制品隔离与符号链接拒绝，全部在真实运行下被单因素消融翻转 —— 不是"测试曾经通过"。
2. **6 个 GAP 全部集中在"已定义但未接线"与"E2E 覆盖缺口"**：跨版本 crosswalk 生产端未消费、internal 前端缺失、联邦搜索缓存键缺生物 scope、E2E 详情/JBrowse 深链/internal 站无覆盖。另发现 5 处冗余或覆盖不足的 `GUARD-INERT`。

## 2. 各工作流结果

| 工作流 | 场景 | ACTIVE | INERT | GAP | 报告 |
| --- | --- | --- | --- | --- | --- |
| W1 身份与公开边界 | 13 | 12 | 1 | 0 | [`identity.md`](./identity.md) |
| W2 assembly 与跨版本 | 6 | 4 | 0 | 1 | [`assembly.md`](./assembly.md) |
| W3 缓存与站点隔离 | 13 | 11 | 1 | 1 | [`cache-site.md`](./cache-site.md) |
| W4 前端与查询键 | 4 | 3 | 0 | 1 | [`frontend.md`](./frontend.md) |
| W5 导入管线与 CH 投影 | 5 | 4 | 0 | 0 | [`pipeline.md`](./pipeline.md) |
| W6 制品隔离与 E2E | 15 | 9 | 3 | 3 | [`artifact-e2e.md`](./artifact-e2e.md) |

### 亮点（翻转证据，均为真实运行）

- **发布边界**：去掉 `is_public` / `release_id==active` / `public_id IS NOT NULL` 任一谓词，禁运行、草稿、NULL-release、缺 public_id 行即刻泄漏；无活动 release 时 `503 → 200`（`identity.md` 表 NEG-01～05）。
- **身份**：把公开投影加上 `internal_id`、或把外部命中的 `hit.id` 改绑持久键，外部响应立刻带出数值主键；给详情加整数回退后 `404 → 200`（ID-01/02）。
- **assembly**：丢弃 `assembly_id` 谓词 → `hits=1 → hits=2`；把歧义聚合移到截断之后 → `limit=1` 时 `ambiguous=True → False`（ASM-01/02/03）。
- **缓存**：删除 `release_id` / `assembly_id` / `site_variant` 任一键字段 → 两个上下文命中同一键、loader 不再执行（`store 2→1`，`second_loader_calls 1→0`）；移除 internal 旁路 → internal 进入共享缓存（CTX-01/02/03）。
- **管线**：从 sha256 去掉 `{assembly}` → v4/v5 同位点 id 相撞；样本身份回退到 `gt_types[0]` → `heterozygous → homozygous_ref`；跳过 summary purge → `summary=4`；`NOT IN`→`IN` → 另一装配的 facts 被跨删（W5 S1～S4）。
- **制品**：注入哨兵 / 删除 internal 入口 / 混入公共内容快照 / 符号链接逃逸 / 根嵌套，扫描与 verifier 全部非零退出（ID-05）。

## 3. GAP 清单（P0/P1 优先）

> **状态更新**：本节 6 个 GAP 与 §4 的 3 个覆盖缺口已于同日的优化 Wave 中全部关闭，
> 见 [`OPTIMIZATION-CHECKLIST.md`](./OPTIMIZATION-CHECKLIST.md) 与 [`OPTIMIZATION-REPORT.md`](./OPTIMIZATION-REPORT.md)。
> 下表保留为**消融基线记录**（改前状态）。

| # | GAP | 严重度 | 决定性位置 | 复现命令 |
| --- | --- | --- | --- | --- |
| G1 | **ASM-04 跨版本关联未接线**：`GeneCrosswalk` 表有数据与 provenance，`search_service` 从不读取；`MatchType.CROSS_VERSION` 全仓零生产者。增删 crosswalk 行对搜索结果**逐字段无影响** | P1（契约 §3 要求） | `apps/api/app/services/search_service.py:28`（未 import）、`_search_genes` 664-796；`apps/api/app/schemas/search.py:29` | `cd apps/api && SOYMUTDB_TEST_DATABASE_URL=... pytest tests/test_ablation_assembly_scope_and_crossversion.py -k must_be_exposed` → **exit 1** |
| G2 | **UI-02 internal 双 id 前端缺失**：后端 `/api/v1/search/internal` 与 `InternalMutantSearchItem{public_id,internal_id}` 已在生成契约中存在，但手写 client 无 internal 函数，`SearchView` 不渲染也不可复制 `internal_id` | P1 | `packages/api-client/src/search.ts:5-17`、`packages/api-client/src/index.ts`（无 internal 导出）、`apps/web/src/views/SearchView.vue:290-302` | `cd apps/web && vitest run src/ablation/ui02-internal-ids.test.ts` |
| G3 | **联邦搜索缓存键缺生物 scope**：`SearchCache.make_key` 只哈希 `(query, sorted(sources))`，无 release/assembly/site_variant，且无锚定测试 | P1/P2 | `apps/api/app/search/cache.py:26-34`；调用点 `apps/api/app/search/aggregator.py:69`、`apps/api/app/api/v1/search.py:183` | 见 `cache-site.md` §4 GAP |
| G4 | **E2E 无详情页覆盖**：13 个 spec 无任何实体详情路由用例 | P1 | `e2e/tests/*.spec.ts` | `ls e2e/tests/*detail*` → 无 |
| G5 | **E2E JBrowse 深链被无条件 skip** | P1 | `e2e/tests/genes.spec.ts:55` | `playwright test -c playwright-public.config.ts` → 该项 `-` |
| G6 | **E2E 内部站完全无覆盖**：无 config/spec 指向 `dist/internal`；把公开套件指向 internal 制品实测 `8 failed / 1 passed`（`No route for /soymutdb-next/login`，internal base 为 `/`） | P1 | `e2e/*.config.ts`（零 internal 命中） | 见 `artifact-e2e.md` §4.4 |

## 4. GUARD-INERT 清单（死代码 / 覆盖不足）

| # | 位置 | 现象 | 判读 |
| --- | --- | --- | --- |
| I1 | `apps/api/app/services/search_service.py:849` | 外部搜索 `public_id IS NOT NULL` 与 ILIKE 冗余，删除后结果不变 | 纵深防御，非缺陷 |
| I2 | `apps/api/app/services/search_service.py:366-374` `site_variant` 字段 | internal 旁路存在时该字段不可达，单独删除不翻转 | 纵深防御；重建旁路时才暴露 |
| I3 | 双站扫描 / verifier | **删除 `external/index.html` 无人拦截**（脚本只要求 internal 有 `*.html`，两站标准不对称） | 真实覆盖缺口 |
| I4 | `scripts/check_site_artifact_isolation.py` | 空目录名含哨兵不被检查（只在文件循环里查路径） | 低危覆盖缺口 |
| I5 | `scripts/verify-site-variant-artifacts.sh` | 只传一个哨兵 `noindex, nofollow, noarchive`；注入 `internal.soymutdb.invalid` 仍 exit 0 | 真实覆盖缺口 |

另有一条**弱断言**发现（W4）：`not.toContain("internal_id")` 是值不敏感断言（只匹配字段名），绑定换成 `internal_id` 后仍通过；真正翻转的是正向断言。`SearchView.test.ts` 完全不覆盖 assembly/release/source 上下文，删除渲染块后其 6 个用例仍全绿。

## 5. 协调者独立复核（不只采信子代理）

| 复核项 | 命令 | 结果 |
| --- | --- | --- |
| 契约锚点基线 | `pytest tests/test_mutants.py tests/test_search_database_integration.py tests/test_search_contract.py`（库 `abl_coord`） | **36 passed**，3.19s |
| W1 消融文件 | `pytest apps/api/tests/test_ablation_identity_public_boundary.py` | **13 passed** |
| W2 消融双支 | `pytest apps/api/tests/test_ablation_assembly_scope_and_crossversion.py -k "not must_be_exposed"` / `-k must_be_exposed` | **6 passed** / **1 failed**（复现 G1） |
| W3 锚点 + 消融 | `pytest tests/test_search_contract.py tests/test_cache.py tests/test_search.py` / `test_ablation_cache_site.py` | **47 passed** / **9 passed** |
| W4 前端锚点 + harness | `vitest run src/views/Mutants.test.ts src/ablation` | **18 passed**（5 文件） |
| W5 管线 harness 1–4 | `cd apps/worker && PYTHONPATH=src:. .venv/bin/python ../../.validation/ablation/pipeline/harness_{1..4}.py` | **4/4 exit 0**，全部打印 `VERDICT GUARD-ACTIVE` |
| W5 CH DDL 门禁 | `pytest tests/test_clickhouse_production_ddl.py tests/test_legacy_clickhouse_migration.py tests/test_vcf_import.py` | **12 passed, 1 skipped** |
| W6 双站扫描 | `python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external --internal-root apps/web/dist/internal --sentinel 'noindex, nofollow, noarchive'` | **exit 0**，`OK: external artifact contains no supplied protected values` |
| W6 审计怀疑项 | `e2e/tests/production-gate.spec.ts:129` 源码 | 已显式要求 JBrowse 帧（`toBeTruthy`），怀疑项澄清 |
| 站点隔离单测 | `python3 -m unittest scripts.test_site_artifact_isolation -v` | **6 OK** |
| **新 HEAD 复跑**（`0efde84d6`） | `pytest tests/test_search_database_integration.py tests/test_search_contract.py tests/test_mutants.py`；`pytest .../test_ablation_assembly_scope_and_crossversion.py -k must_be_exposed`；`vitest run src/ablation src/views/Mutants.test.ts`；`pnpm install --frozen-lockfile` | **36 passed** / **1 failed（G1 仍复现）** / **18 passed** / **exit 0** |

## 6. 环境与方法

- Node `v24.19.0`；`apps/api/.venv`、`apps/worker/.venv` 均为 Python 3.14.6。
- PostgreSQL 16 常驻 `127.0.0.1:55432`（`soymutdb` trust）；每个工作流独立库 `abl_<domain>`；worker 侧用嵌入式 `chdb`。
- Playwright 浏览器缓存可用；`playwright-public.config.ts`（同源 mock）离线跑通 29 passed / 2 skipped，`playwright-jbrowse.config.ts` 5 passed。
- 沙箱 `$HOME` 只读会让 `pnpm` 报 `unable to open database file`；需把 `PNPM_HOME`/`XDG_*` 指到工作区可写目录（见 `.validation/ablation/artifact/pnpmenv.sh`）。

## 7. 未验证项与已知限制

- 全部消融在进程内（pytest/vitest/harness），**无真实 Redis、无真实 ClickHouse 服务、无真实 MinIO**；缓存实验用真实 `get_or_set` 包装器替代 Redis。
- W5 S2 用属性等价的 `FakeVariant`，未喂真实 cyvcf2 二进制 VCF；`compute_variant_id` 无独立单测。
- W6 完整 `verify-site-variant-artifacts.sh`（不带 `PREBUILT=1`）未在单条命令内串起；E2E 的 live-data 与 detail 用例仍缺。
- 未跑 `pnpm typecheck`；新增 harness 的类型正确性未由编译器复核。
- **工作树无关改动（非本次消融产生）**：实验中途曾观察到 `apps/jbrowse` / `packages/genome-view` / `packages/genome-data` 删依赖而 `pnpm-lock.yaml` 未同步，`pnpm install --frozen-lockfile` 报 `ERR_PNPM_OUTDATED_LOCKFILE`；并发会话提交 `177d36ccc` 后已自洽，新 HEAD 上 `pnpm install --frozen-lockfile` **exit 0**。当前未提交的是并发会话进行中的 genome-data alignment fixture 工作（`alignment.bam`/`.bai`/`gc_content.bw`、catalog 类型），与本次消融无关。

## 8. 建议下一步（按优先级）

1. **G1**：`_search_genes` 增加 `gene_crosswalks`（必要时带 release/assembly）join，命中时产出 `match_type=cross-version` + 关联链接；补 anchor 走 search 而非只查表。
2. **G2**：补 `apiClient.internalSearch()` + internal 结果 UI（双 id 展示/复制），复用已有生成类型。
3. **G3**：`SearchCache.make_key` 纳入 release/assembly/site_variant，并补锚定测试。
4. **I3/I5**：双站扫描补 `external/*.html` 必需性与多哨兵集合（`internal.soymutdb.invalid`）。
5. **G4/G5/G6**：补 detail 页 spec、解 skip JBrowse 深链、为 internal 变体建独立 E2E config（注意 base 路径为 `/`）。
