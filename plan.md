# SoyMutDB Next 当前状态驱动重构计划（第七轮 · PR #1 收敛版）

> 审计日期：2026-09-23
> Canonical plan：`plan.md`（保持小写，禁止再创建 `PLAN.md` 形成双真源）
> Base：`main@4ec2fdb768d368585e76a399f202607e578a0ec2`
> 当前实现分支：`refactor/next-vue-and-p2`
> 本轮审计起点：`ec12ee611f7fd8baae1600c3dffe93aa25c16575`
> PR：#1 `refactor: Vue mainline + pnpm 12 + P2-3 import protocol (Phase C/A/B/D/F)`
> 原则：先关闭 PR #1 correctness / CI / runtime gate，再继续新功能。未通过 Gate 的能力不得以“本地可用”替代真实交付证据。
>
> **2026-09-27 前端方向变更**：React 19 + Umi Max 4 + Ant Design 6 + ProComponents v3 重平台设计见 `docs/superpowers/specs/2026-09-27-react-pro-v6-replatform-design.md`。这项决定取代本文早期的“Vue mainline”前端方向；本文其余记录保留为历史证据，不应当作当前 React 迁移已完成或已验收。

---

## 2026-09-23 收敛执行记录（PR #1 已合并）

PR #1 已 merge 为 `d17c0a96b`。以下工作从该基线继续（CNB `DEFERRED_QUOTA`，未重试；
GitHub Actions 为当前主 gate）。

### 已落地提交

| commit | 内容 |
| --- | --- |
| `d34b012f2` | CI：唯一 Python workspace bootstrap（`scripts/install_python_workspace.py`）；`packages/import-protocol` 不再从 PyPI 解析；ClickHouse job 3.12→3.14 |
| `d4f3c5c63` | Vue：移除 store -> router import cycle（未使用的 `goHome`） |
| `c1e9d0195` | Vue：`cn` falsy 测试满足 `no-constant-binary-expression` |
| `10d273eaf` | 依赖：移除未使用 Vue deps；`pnpm dedupe` 清除 17 组重复版本（-282 lockfile 行） |
| `1a40febbe` | 契约：PLATFORM_CATALOG/pnpm 12/vue-demi 对齐；ADR-0001 pnpm 12.5.1 |
| `472434c48` | ClickHouse：MV 名称断言修复（`mv_gene_impact`）；迁移 SQL `chromosome_summary.cnt` 与 init.sql 对齐；四源交叉契约 + chdb 真实引擎验收 |
| `8b7b06b2b` | governance：Vue SFC cycle 分析（madge 拆分 + `--ts-config`），16/16 analyzer 通过 |
| `c934fce31` | Vue：site variant 严格校验、release header pin、canonical JBrowse origin、env 类型声明 |
| `9dd69532d` | Vue：query key 携带 release/site/assembly/filters；queryOptions 工厂；Mutants/Variants URL 状态；Downloads presign；Search a11y |
| `147237fcf` | Vue：`VITE_BASE_URL` 驱动 Vite base 与 router history base |
| `6e9bf13cf` | Vue：非法 `VITE_SITE_VARIANT` 构建期 fail closed |
| `c89e75da6`+`923d8aa4a` | worker：`test_chdb_harness` 命名；内存契约子进程隔离；PG 序列对齐 |
| `1726f997c` | worker：ADR-0005 正确性（稳定 variant id、fingerprint advisory lock、VERIFYING 恢复、release 全量重建、`mutations_sync`、参数化、冲突 fail-closed、VcfAdapter 接线） |
| `61dffc4b0` | worker：fingerprint advisory lock 改用专用连接（真实 PostgreSQL 暴露的池化缺陷） |
| `ca44c516f` | worker：vcf 移出无 writer fail-closed 矩阵（已有协议专用测试） |
| `bc2b9648d` | CI：artifact 压缩/去重/保留期治理（配额 500MB） |
| `29a99f7de` | seed：Route-B loader 与 worker 统一稳定 variant identity |
| `457695e6e` | seed/worker：统一 `length` 等位跨度定义；MNV 分类修正 |

### 证据（本地）

- smoke contracts 层（13 scripts + `infra/clickhouse/test_schema_contract.py`）→ **231 passed**
- governance `pnpm deps:audit`（注入 demo VITE_*）→ **16/16 passed**（含两个 madge entry）
- `web-vue`：**10 files / 31 tests**；typecheck + lint 干净
- Vite base 构建：`/`、`/soymutdb-next/`、裸 `soymutdb-next` → 产物前缀正确；`VITE_SITE_VARIANT=public` → exit 1
- worker chdb 套件（finalize/vcf/engine/legacy/协议）→ **22 passed**（untouched summary、冲突、注入、VERIFYING 恢复、adapter 接线）
- 真实 PostgreSQL 16（本地临时集群，`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`）：`test_import_manifest_repo.py` + `test_vcf_import.py` → **14 passed**（advisory lock 串行化、VCF e2e、VERIFYING 恢复、序列对齐）。真实 PG 还找到了 lock 在 Session commit 后退池的缺陷（`61dffc4b0`）
- GitHub api-tests：apps/api pytest **1542 passed**；worker pytest 348 passed + 1 个旧断言（已在 `ca44c516f` 更新）
- 本地 API 全量复现的 131 errors 为共享库 seed 冲突（CI 用全新 testcontainers），非代码问题
- GitHub：ClickHouse migration fixture（真实 24.8）→ **success**；MCP e2e → success
- artifact 配额：`soymutdb-next` 19.5GB + 账户其它仓库 939MB 旧 artifact 已清理；等待 GitHub 重算（6–12h）

### 本机测试环境重建（2026-09-23 夜）

从零重建本仓库的本地测试环境并逐层验证：

| 组件 | 做法 | 结果 |
| --- | --- | --- |
| JS 依赖 | 删除全部 `node_modules` 后 `pnpm install --frozen-lockfile` | ok（store 复用） |
| API venv | `scripts/install_python_workspace.py` → api[dev] + worker[dev]（CI 布局） | Python 3.14.6 |
| Worker venv | 同脚本 → worker[dev]（chdb/cyvcf2/scanpy） | Python 3.14.6 |
| PostgreSQL | 标准 mamba 实例（`soymutdb`@127.0.0.1:55432），按 `docs/dev/mamba-validation-environment.md` | ok |
| 后端 gate | `verify-backend-tests.sh`（真实 PG + chdb） | API 1542 + worker 349 passed |
| 前端 | turbo test/lint/typecheck（`--concurrency=1`） | 10/10、11/11、11/11 |
| smoke | contracts / static / runtime | 231 passed / PASS / PASS |
| acceptance | contracts / static / runtime / backend | 4× ACCEPTANCE PASS |
| 构建 | `build-static-apps.sh`、`build-pages-artifact.sh` + verify | 均 PASS |
| 双站点 | `build:sites`（demo）+ 隔离检查（noindex 哨兵） | external 0 命中、internal 9 命中 |
| 本地 E2E | `e2e/playwright-public.config.ts`（同源 mock API） | 27 passed, 2 skipped |

本轮环境搭建顺带修复：
- `scripts/with-postgres-service.sh`：外部 PG 路径未导出 `SOYMUTDB_DATABASE_URL`，`--print-exports` 在 `set -u` 下直接失败（`dd7616b2c`）。
- `deploy/cloudflare.md`：双站点本地验证命令缺 API origin 且 standard 模式需真实 API，改为 demo + 显式 origin + 隔离检查（`fc71b5669`）。
- `docs/dev/mamba-validation-environment.md`：测试解释器更新为 3.14 venv，并补充无 Docker 的完整 gate/acceptance/双站点命令。

沙箱注意：构建需 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`，turbo 需 `--concurrency=1`（否则 esbuild/tailwind-oxide 出现 `os error 11`）；E2E 是独立 npm 项目，需在 `e2e/` 内 `npm ci`。

### Phase 2 起步：genes canonical promotion（2026-09-23）

ADR-0004 要求的 “staging → canonical 显式 promotion” 首次落地（genes 先行）：

- 新增 `apps/worker/src/soymutdb_worker/tasks/module_promotion.py`：在 module_tsv
  导入事务内（staging 写完、data_set 标 ready 之前）执行 promotion；失败即回滚整个导入，
  因此“已入 staging 但未 promotion”不可能被提交。
- 映射表 `PROMOTION_TARGETS = {"genes": "genes"}`；未映射 module_key fail closed。
- assembly 解析：`releases.assembly_id` pin，否则要求 release 恰好拥有 1 条 assembly；
  0 或多条 fail closed。
- chromosome 缺失时用观测到的最大 gene end 作为临时长度，只增不减；
  genes 按 `(assembly_id, accession)` upsert，`strand='+'`，`mutation_feature` 存入
  `genes.attributes`。
- 空 staging 不删除 canonical；非空 staging 视为模块完整快照：缺失的 canonical genes
  通过临时表 anti-join 删除（替换语义）。重试幂等（staging 先清后写 + upsert）。
- ADR-0004 追加 implementation amendment（state/consumer/retention/retry/schema 五问）。

证据（真实 PostgreSQL 16，mamba 实例）：

- `apps/worker/tests/test_module_tsv_postgres_integration.py` → **11 passed**：
  promotion 字段/坐标/attributes、幂等+替换删除旧基因、无 assembly fail-closed、
  未映射模块 fail-closed、draft/published 可见性契约、批次中途失败整体回滚、
  并发导入按 release 行锁串行化（终态等于其中一个快照）、空快照不删除。
- `apps/api/tests/test_genes_database_integration.py` → 真实 PG 读取：
  release 隔离（同 accession 不同 assembly）、promoted 列与 attributes 可读。
- `test_data_adapters.py` + `test_module_schema_limits.py` → 73 passed, 1 skipped。

Phase 2 未完：其它 scientific modules 的 promotion 映射、VCF 全链路 E2E、
P2-6 capability 逐个评审（本轮已产出评审表，结论：全部保持 OFF）。

### P2-6 capability 评审（2026-09-23，逐项复核）

评审依据：开启需同时满足 parser / validator / manifest / staging / verify / finalize /
retry / concurrency / crash / real CH / real PG / E2E（不批量开启）。

| capability | 默认 | 实现证据 | 缺口 | 结论 |
| --- | --- | --- | --- | --- |
| `imports.module_tsv` | ON | ModuleTsvAdapter：schema 校验（tsv/csv/xlsx）、staging、checksum verify、ADR-0004 promotion | — | 保持 ON |
| `imports.module_xlsx` | ON | module_schema 的 xlsx 解析（openpyxl、spool 8MiB、worksheet 上限）；worker/api 均有依赖 | —（经复核非虚假 flag） | 保持 ON |
| `imports.local_upload` | ON | 浏览器直传 + checksum + data set 绑定 | — | 保持 ON |
| `imports.vcf` | OFF | VcfAdapter → `import_vcf` → ADR-0005 协议（staging/verify/finalize、fingerprint 锁、VERIFYING 恢复、冲突 fail-closed、参数化） | 生产 HTTP ClickHouse finalize 验收（现为 chdb 嵌入引擎）；Admin→导入→发布 E2E；CNB/Docker 全栈 | 保持 OFF（最接近开启） |
| `imports.fasta` | OFF | FastaAdapter.run 无条件 UnsupportedImportError | writer | 保持 OFF |
| `imports.gff3` | OFF | Gff3Adapter.run Unsupported；`import_gff3` 仅计数不落库 | writer + 落库 + 全链路 | 保持 OFF |
| `imports.blast_db` | OFF | BlastDbAdapter Unsupported | writer | 保持 OFF |
| `imports.seed_data` | OFF | UnsupportedCsvAdapter | writer | 保持 OFF |
| `imports.expression_csv` | OFF | UnsupportedCsvAdapter | writer | 保持 OFF |
| `imports.homolog_csv` | OFF | UnsupportedCsvAdapter | writer | 保持 OFF |

结论：本轮**不开启任何 OFF capability**；VCF 是唯一具备完整协议实现的候选，
但其开启前置（real HTTP ClickHouse + 全栈 E2E + CNB）在外部阻塞下无法完成，
因此 `imports.vcf` 与 `SOYMUTDB_ENABLE_VCF_IMPORT` 都保持关闭。

### Phase 3 起步：双站点构建与隔离 gate（2026-09-23）

AGENTS.md 要求的 external/internal 工件边界此前只在本地手工验证（deploy/cloudflare.md），
没有任何回归门禁。本次将其变为可重复的仓库脚本并接入两端 CI：

- 新增 `scripts/verify-site-variant-artifacts.sh`：demo 离线构建 external + internal，
  断言 internal HTML 带 `noindex, nofollow, noarchive`、internal 不含公开快照
  （`data/content.json`）、external 不含 internal-only 值（复用
  `scripts/check_site_artifact_isolation.py`）。
- GitHub frontend job 新增同名 step；CNB 通过 `scripts/ci-job-steps.sh` 的
  `frontend_run` 调用同一脚本（两端同一字节）。
- `scripts/test_ci_job_contracts.py` 将新脚本列入共享脚本与 delegation 断言。

证据：

- 脚本独立运行 → PASS（external 0 命中，internal 9 个 HTML 带 noindex）；
- 完整 frontend gate（`bash scripts/verify-frontend-artifacts.sh`）→ frontend verification passed；
- 合同测试 → 125 passed。

Phase 3 未完：Vue SSG/静态路由枚举、canonical build/deploy 切换、剩余页面 parity。

### Phase 3 第二步：Vue 静态路由枚举（2026-09-23）

Vue portal 成为 canonical 前的静态托管前置：每条稳定路由获得独立文档与元数据，
而不是依赖 SPA fallback。

- `src/router/routes.ts`：路由元数据（title/description/`prerender`/`sitemap`），
  纯数据、无组件导入（构建脚本可直接加载）。
- `src/lib/static-routes.ts`：枚举 / 文档路径 / head 注入 / sitemap / robots 的纯函数。
- `scripts/generate-static-routes.ts`：`vite build` 后为每条可预渲染路由写
  `<path>/index.html`（注入 title/description/canonical），并写 `routes.json`、
  `robots.txt`、（external 且已知 origin 时）`sitemap.xml`。
- 动态路由（`/genes/:geneId`、`/mutants/:publicId`）永不生成文档；
  internal 变体不生成 sitemap，robots 为 `Disallow: /`。
- `build` = `vite build && tsx scripts/generate-static-routes.ts`；web-vue 增加 tsx。

证据：

- `pnpm --filter @soymutdb/web-vue test` → **12 files / 43 tests passed**；typecheck/lint 干净。
- external 构建：5 个文档（`/`、`/search`、`/mutants`、`/variants`、`/downloads`）
  + `sitemap.xml`（5 URL）+ robots Allow；`/genes` 未生成。
- internal 构建：同样 5 个文档可用，但 robots 为 `Disallow: /`、无 sitemap、
  `routes.json` 的 sitemap 条目为 0。

说明：当前文档是带元数据的 SPA shell（页面内容仍由客户端数据驱动）；
完整 SSG 预渲染需页面布局数据，属 Phase 3 后续。

### Phase 3 第三步：Vue `/news` 列表 + 详情（2026-09-23）

- `packages/query-keys`：新增 `news.list/detail`（可分类/页/页大小敏感，news 为全局内容不绑 release）。
- `query-options`：`newsListQueryOptions` / `newsDetailQueryOptions`。
- `NewsListView.vue`：分类（all/news/update/announcement）与页码走 URL（`?category=&page=`），
  语言 `?lang=zh` 同样入 URL；含 loading/error/empty 与分页导航。
- `NewsDetailView.vue`：标题/日期/正文；正文为 CMS HTML，客户端用 DOMPurify 再消毒后
  `v-html`（与 React 路由一致的纵深防御）；`?lang=zh` 切换中英。
- 路由元数据：`/news` 预渲染 + sitemap；`/news/:slug` 动态不预渲染。

证据：

- `pnpm --filter @soymutdb/web-vue test` → **14 files / 50 tests passed**（含 XSS 消毒断言）；
  typecheck/lint 干净。
- 构建：external 变体生成 6 个文档（新增 `news/index.html`，title 正确）。

### Phase 3 第四步：mutant 详情表型区块（2026-09-23）

- `packages/query-keys`：`mutants.phenotypes(publicId, releaseId, siteVariant)`，
  与 line detail 同一 release/site 上下文。
- `query-options`：`mutantLinePhenotypesQueryOptions`（enabled 由 detail 成功驱动，
  未知 public id 不发行必然 404 的二次请求）。
- `MutantDetailView.vue`：表型观测表（分类/名称/值/单位/描述），含 loading/error/empty
  与“观测不构成因果证据”的边界说明；空值渲染为 `—`。

证据：`web-vue` → **14 files / 52 tests passed**（含表型行、空态与不泄漏 internal_id）；
query-keys 9 passed；typecheck/lint 干净。

### Phase 3 第五步：gene 详情的 transcript 区块（2026-09-23）

- `packages/api-client`：`GeneDetail.transcripts` 从 `unknown[]` 细化为
  `GeneTranscript[]`（含 `GeneExon`），与 API `_transcript_to_response` 一致。
- `GeneView.vue`：transcript 表（名称/生物类型/坐标/外显子数，canonical 标记，
  缺失名称回退到 transcript id）。

证据：`web-vue` → **14 files / 53 tests passed**；api-client 112 passed；
双方 typecheck 与 web-vue lint 干净。

### Phase 3 第六步：gene assembly 预览与关联数据（2026-09-24）

- `GeneModelPreview.vue`：把基因跨度、转录本、外显子合并到一个带 assembly 标签的
  1-based inclusive SVG 视图；错误坐标不会污染其他有效轨道，屏幕阅读器可读取精确区间。
- `GeneView.vue`：增加有界游标分页的 expression / homolog 表和继续加载状态；请求与缓存均
  按 assembly、release、site variant 隔离；表达量缺失值显示 `—`，不折算为零。
- `api-client`：补齐 expression / homolog 分页参数及响应类型，适配 homolog API 的实际路由和
  字段；旧 React 基因详情同步处理空表达值，避免 canonical 站点出现 NaN 或渲染异常。
- `GeneModelPreview.test.ts`、`GeneView.test.ts`、api-client / query-keys 测试覆盖坐标、游标、
  cache scope 和空表达值。

状态：`IMPLEMENTED_UNVERIFIED`。当前工作区依赖链接不完整，Vitest、vue-tsc 和 ESLint 无法
启动；Vue SFC 编译可用本地 compiler 单独核验，完整测试证据待依赖环境恢复后补齐。

### Phase 3 第七步：SeqFetch assembly-aware Vue 工具（2026-09-24）

- Vue `/tools` 与 `/tools/seqfetch`：支持 200 个以内的批量基因 FASTA、单区间提取、assembly
  选择、输入限制、缺失 ID 列表、FASTA 预览和大文件下载。
- API 契约：两种模式都要求 assembly；批量查询在 SQL 中按 assembly_id 限定，同名 accession
  不会跨 assembly 覆盖。FASTA header、Vue 页面和 MCP 返回都保留所选 assembly 名称。
- React 与 MCP SeqFetch 客户端同步传递 assembly，避免现有 canonical 页面或 MCP 工具调用旧的
  无 assembly 请求形状。
- 新增 `SeqFetchView.test.ts`、`ToolsView.test.ts` 与 API 组装范围回归断言。

状态：`IMPLEMENTED_UNVERIFIED`。Vue SFC 与 Python/TypeScript 语法可编译；Python API tests
因缺少 `pytest_asyncio` 无法启动，Vue Vitest/typecheck/lint 依赖链接不完整；OpenAPI 导出器因缺少
`structlog` 且 uv 缓存只读而无法运行，需在依赖完整环境补跑。

此前识别的 enrichment / ExpPattern assembly 范围缺口已在 Phase 3 第八步补齐；实现与验证状态见下。

### Phase 3 第八步：ExpPattern / Enrichment assembly-aware 契约与页面（2026-09-24）

- ExpPattern API 将 assembly 作为必填请求字段，在 SQL 中分别限制基因、表达库和表达值；响应
  显式包含 assembly id/name/version、矩阵和 row_order。响应模型检查矩阵维度及 row_order 排列。
- Enrichment ORA / GSEA 请求与响应都携带必填 assembly 上下文；注释查询带 `assembly_id` 条件。
  表缺失时返回可解释空结果；若注释表缺少 assembly provenance 或元数据检查失败，则 fail closed 为 503。
- React（当前 canonical）与 Vue 工具页接入 assembly 选择；React/Vue 的 ExpPattern 表格与热图都遵循
  服务端 `row_order`。API client、MCP SeqFetch 和现有 React 页面保持 assembly 请求参数一致。
- 新增 ExpPattern / Enrichment Vue 页面和回归测试；补充 external / internal Vue 双工件构建与隔离脚本，
  并接入统一的 `verify-site-variant-artifacts.sh` 门禁。canonical 发布仍保持 React，待 parity 实测后再切换。

验证记录：此前 ExpPattern、Enrichment 与 OpenAPI 合同测试 **81/81 passed**；后续加入 release 过滤后，
本轮单独复跑 ExpPattern 模块 **20/20 passed**，尚未重跑 Enrichment / OpenAPI。CI 脚本合同测试此前
**58 passed**，排除了 SMB 工作区执行位断言（该项检测到脚本被挂载为不可执行）。此前 `ruff`、双站点
shell 语法、artifact isolation self-test 与 `git diff --check` 通过。OpenAPI 临时导出已确认请求必填
assembly、release header 与响应上下文；本轮增加 source 字段后，生成客户端快照仍需官方生成器刷新。

状态：release 约束后的 ExpPattern 后端 `VERIFIED`；Enrichment source response 与新导入流水线
`IMPLEMENTED_UNVERIFIED`；React/Vue 页面及双站点工件仍待前端门禁验证。工作区有 Node 24.19，但 pnpm
12.5.1 不在本机缓存；离线 pnpm 安装因 package store 缺少锁文件 tarball 和供应链元数据而未完成，且共享盘
现有 node_modules 无传递依赖链接。仓库不含真实注释数据，必须由操作人员指定有授权的数据源导入后才会返回富集项。

### Phase 3 第九步：GO / KEGG 有来源注释快照导入（2026-09-24）

- Alembic `0038` 新增注释数据集与断言表；联合外键要求 assembly 属于该 release、gene accession 属于该
  assembly，且每条结果通过 annotation set 关联到对应来源。
- 导入 CLI 只接受 draft release；要求公开 HTTPS source URL、来源版本与 SHA-256，验证 TSV 列、ontology、
  gene accession 和 term 名称，流式校验实际导入字节的 SHA-256，事务失败整批回滚，同一
  release/assembly/ontology 只允许一个不可变快照。
- Enrichment ORA / GSEA 响应和 React / Vue 页面现在显示 source name/version/URL/checksum；旧表缺少
  provenance、来源缺失或 annotation set 与行上下文不一致时 fail closed。导入格式与操作步骤记录在
  `docs/dev/enrichment-annotation-import.md`。
- 新增 TSV parser 回归用例、PostgreSQL import/savepoint 用例和 migration upgrade/downgrade 合同覆盖。

状态：代码实现完成；已完成无数据库后端回归和静态检查，真实 PostgreSQL migration/import 用例与前端门禁
仍未验收。当前没有授权的真实 GO/KEGG 输入文件，不能据此宣称真实富集数据已可用。

### 2026-09-25 定向验证记录

- 当前 Mamba root 中没有 `webdb` 环境（`mamba env list` 仅有 `base` 与
  `zotero-pdf2zh-server`）；使用 Python 3.14.6 的 `mamba run -n base`，并加载仓库 API venv
  与本地 Python workspace 包路径执行。
- `apps/api/tests/test_enrichment.py` → **44 passed**。
- `apps/api/tests/test_enrichment.py tests/test_gene_annotation_import.py tests/test_migrations.py
  tests/test_openapi_contract.py -m 'not integration'` → **75 passed, 6 deselected**。
- `apps/api/tests/test_exppattern.py tests/test_seqfetch.py tests/test_gene_service.py -m 'not integration'`
  → **73 passed**。
- Ruff（本次触及的 enrichment/import/migration 文件）通过；Python `py_compile` 与针对改动文件的
  `git diff --check` 通过。
- 另行包含 `tests/test_genes.py` 的运行有 **73 passed、10 errors**：这 10 项在 conftest 中尝试
  连接 Docker socket，沙箱拒绝访问；未启动 Docker。
- PostgreSQL 测试未运行：本机 5432/55432 无监听服务；仓库 PostgreSQL 包记录的旧前缀为
  `/mnt/data02/...`，该路径不存在，故无法启动临时实例。导入 integration 标记与真实 Alembic
  upgrade/downgrade 仍待可用 PostgreSQL 环境。
- 前端依赖链仍不可用：本机没有 pnpm 12.5.1，Vitest 缺少 `@vitest/utils` 链接；Vue SFC 编译器
  也缺少 `@vue/compiler-sfc`。官方 OpenAPI TypeScript 生成物尚未刷新。

### 阻塞 / 未关闭

- GitHub artifact 上传：已压缩 `pages-demo-dist`、移除无消费者的 dist 上传、缩短证据保留期；等待配额重算（6–12h）后应恢复
- api-tests 的 PG 集成已在本地真实验证；CI 复跑待最新 run 完成
- **G4 review triage：PR #1 的 22 条 review threads 已全部回复结论并 resolve（unresolved = 0）**，映射到修复 commit 或 Phase 3 deferral
- T8 local Docker：本机无 Docker daemon（`LOCAL_DOCKER_T8` PENDING）
- Vue external/internal `build:sites` 和产物隔离检查已接入统一站点工件 gate；本机完整构建待 Node/pnpm 依赖恢复

### Next

1. 恢复仓库 pin 的 pnpm 12.5.1 与前端依赖，跑 Vue / React 针对性质量门禁和 external/internal artifact 构建
2. 用官方 `generate:api-client` 刷新 `openapi.json` 与 TypeScript 声明，再跑 contract check
3. 获取许可明确且与 release/assembly 相符的 GO / KEGG 数据文件，应用 migration 并导入；再用已知数据集核对真实富集结果
4. 继续跟进最新 main CI、Pages artifact 配额与未关闭的 Docker/T8 验收（不属于本次非 Docker 功能实现）

---

## 0. 历史审计快照（2026-09-23 合并前；不代表当前状态）

### 0.1 Git / PR

- `main` 仍在 `4ec2fdb...`。
- PR #1 从 main 前进 31 commits、behind 0；审计时 head 为 `ec12ee61...`。
- PR #1 共 99 changed files，约 +6972 / -600。
- GitHub 报告 `mergeable=true`，但 `mergeable_state=unstable`。
- Copilot review 有 22 个未解决线程：16 High、6 Medium。
- GitHub Actions 两条 PR workflow 均为 failure，因此 PR #1 当前禁止合并。

### 0.2 已实现但尚未等于 Release-ready

| 工作包 | 当前状态 | 证据等级 | 结论 |
| --- | --- | --- | --- |
| Framework-neutral seam | IMPLEMENTED | E2 本地 | shared/query-keys/i18n-core/genome-view-model 已有守卫 |
| Shared import protocol | IMPLEMENTED | E2 本地 + 真 PG | fingerprint/FSM/visibility 已下沉 |
| P2-3 staging/verify/finalize | PARTIAL | E2/E3 单节点 chdb + 真 PG | 有真实引擎证明，但存在 review 指出的 finalize/并发/重试风险，不能关闭 Gate |
| pnpm 12 | IMPLEMENTED_LOCAL | E2 本地 | 12.5.1 + lockfile 已迁，GitHub CI 仍红 |
| Vue shell | IMPLEMENTED_LOCAL | E2 本地 | Router/Pinia/Vue Query/Antdv Next/Tailwind 已建立 |
| Vue Home/Search/Gene/Mutants/Variants/Downloads | PARTIAL | E2 本地 | 页面存在，但 release/site/cache/base URL 等 correctness 尚未关闭 |
| Canonical Vue deployment | NOT_DONE | E1 | 当前正式 build/publish 仍以旧 `apps/web` 为主 |
| TanStack Charts 全迁 | NOT_STARTED | E0/E1 | 不得在 PR #1 correctness 未关闭前批量启动 |
| Vue Admin | NOT_STARTED | E0 | 后置 |
| P1-1 full-stack ID-05 | BLOCKED | E1/E2 局部 | 仍缺真实 seeded release + unreleased sentinel + artifact-level 全栈证据 |
| CNB Docker / Trivy / SBOM | BLOCKED | E1 配置 | PR #1 尚无真实 CNB 成功证据 |
| P2-6 capability reopen | BLOCKED | E1 | 所有原默认 OFF scientific imports 继续 OFF |

### 0.3 PR #1 提交历史已确认

PR 已按可预览逻辑提交推进：framework seam → import protocol → ClickHouse port/finalize → worker manifest → VCF wiring → genome model → pnpm12 → Vue shell → Vue pages → GitHub workflow pins。这个提交模型保留，不 squash 成单一巨型提交。

---

## 1. PR #1 Exit Gate（历史门禁，PR #1 合并后已关闭）

本节保留合并前的门禁与审计依据。PR #1 已于上方记录的 2026-09-23 合并；以下“当前”措辞均指当时审计，不代表现在仍需合并 PR #1。

在以下四组 Gate 全部通过前：

- 不继续批量迁移 Vue 页面；
- 不开始全量 TanStack Charts；
- 不删除 React/ECharts；
- 不开启 VCF 或其他 scientific import feature flag；
- 不把 Vue 声称为已上线 canonical portal。

### G1 · CI / Toolchain Gate

当前 GitHub Actions 真实失败项：

1. API tests：失败在 Python dependency install。
2. Frontend：失败在为 OpenAPI export 准备 API venv。
3. Baseline Ubuntu API：失败在 API/test dependencies install。
4. Baseline OpenAPI contract：失败在 backend/client dependencies install。
5. Baseline Windows：失败在 API package install。
6. Dependency governance：graph/gates 失败。
7. ClickHouse migration fixture：真实 workflow 失败。
8. Web/Admin baseline build 本体与 artifact contract 已通过，但 artifact upload 失败。
9. Docker image / Kind / publish 因上游失败全部 skipped。

最高概率的第一个安装链问题：`apps/api` / `apps/worker` 已声明本地 `soymutdb-import-protocol==0.1.0`，`[tool.uv.sources]` 能告诉 uv 使用本地路径，但 GitHub workflow 使用 plain pip 且只预装 `packages/jobs-py`。必须先用日志/最小复现确认，不能仅凭推断直接宣布原因。

#### G1 实施要求

- 新增一个唯一 Python workspace bootstrap 入口，供 GitHub/CNB/local 共用；不要在多个 workflow 手写不同的 `pip install -e ...` 顺序。
- bootstrap 必须显式安装所有本地 Python packages：至少 `packages/import-protocol`、`packages/jobs-py`，再安装 API/worker。
- 统一 Python 3.14；历史 ClickHouse job 若仍用 3.12，必须说明是否为 fixture 限制，否则收敛。
- 修复 dependency-governance 后必须保留 pnpm 12 双文档 lockfile 支持。
- artifact upload failure 必须读取具体日志，禁止通过 `if-no-files-found: ignore` 等方式绕过。
- 修复后 GitHub 两个 workflow 必须全部 green，再进入 CNB。

#### G1 退出证据

- GitHub Actions PR head：CI = success。
- Baseline validation = success，或明确拆除已被新交付链取代且有 ADR 的历史 gate。
- 所有失败 job 都有 root cause + regression test/contract。

---

### G2 · Vue correctness / deployment-boundary Gate

官方 TanStack Query 文档明确要求：query function 依赖的每个会改变结果的变量，都必须进入 query key；Vue 中 ref/getter 应保持响应式依赖。PR review 对当前 query key 的多项问题与官方契约一致。

必须关闭：

1. API 请求必须绑定 build/runtime 的 release context，不能页面显示 release A、请求实际使用 active release B。
2. Gene detail key：加入 `siteVariant + release + assembly + gene identity`。
3. Mutant detail key：禁止 hard-code null release。
4. Variants key：加入 chromosome/start/end/impact，以及任何 cursor/limit/sort/result-affecting filter。
5. Search/Mutant/Gene/Variant 等 query 应优先使用 Vue Query `queryOptions()` 把 queryKey 与 queryFn 共置，避免两者再次漂移。
6. `VITE_SITE_VARIANT` 必须严格验证，只允许 `external|internal`，非法值 build/start fail-closed。
7. Vite `base` 与 Vue Router history base 必须来自同一个 `VITE_BASE_URL` / normalized deployment base。
8. Mutant filter 必须写入 route query，可分享/刷新/后退恢复。
9. Gene JBrowse 使用 canonical `VITE_JBROWSE_BASE_URL`。
10. Downloads 必须实现真实 download/presign action，不把 metadata-only 页面标成 parity。
11. URL-less Search hit 不能保留可交互 anchor 语义。
12. Vue 进入 canonical build/deploy 前，必须先明确 `preview-only`；不要在同一个 correctness commit 中同时切 production delivery。

#### G2 测试

- query-key contract：release/site/assembly/filter 任一变化必须生成不同 key。
- reactive transition：切 release/site/filter 必须 refetch，而非复用旧缓存。
- deep-link：刷新 URL 后恢复 filter/page/context。
- `VITE_BASE_URL=/soymutdb-next/` build + preview。
- external/internal invalid variant negative test。
- JBrowse origin contract。
- Downloads presigned URL ownership/visibility test。
- keyboard/a11y negative interaction test。

---

### G3 · P2-3 import correctness / security Gate

chdb 是真实 ClickHouse 引擎证据，但不能替代 production HTTP ClickHouse、mutation、并发 worker、cluster/replica 语义。

PR review 当前必须逐条 triage：Confirmed / False Positive / Already Fixed。Confirmed 项必须先补 failing regression test，再修实现。

#### G3.1 实际任务入口

- 确认 Admin/Celery `run_import_adapter(kind=vcf)` 的真实路径最终进入新 ADR-0005 protocol。
- 如果旧 `VcfAdapter.run` 仍 unconditional fail-closed，则只能二选一：
  - 保持 capability OFF 并让路径明确 fail-closed；或
  - 在 P2-6 前把真实 adapter path 接到 protocol。
- 不允许“存在一个新的 `import_vcf` 函数”就宣称功能已接线。

#### G3.2 稳定逻辑身份

- semantic fingerprint 已故意排除 filename/object key。
- variant identity 也必须从稳定 semantic identity + canonical variant coordinates/alleles 推导，不能依赖可变化的 S3 `file_key`。
- same bytes + different object key retry 必须得到同一 logical facts / same variant IDs。

#### G3.3 并发与恢复

- 同一 fingerprint 同时到达两个 worker 时，只允许一个 writer/finalizer。
- 优先在 PostgreSQL control plane 使用 transaction-scoped advisory lock 或等价可证明锁；不要依赖 Celery“通常不会重复”。
- lock key 必须稳定、冲突范围清晰、异常释放可靠。
- CREATED/PARSING/WRITING/VERIFYING/FAILED/PUBLISHED 每个可恢复状态必须有 retry table。
- VERIFYING crash 后 retry 不得执行非法 VERIFYING→VERIFYING。
- PUBLISHED retry 必须是 no-op / return existing result。

#### G3.4 ClickHouse finalize

- ClickHouse mutations 默认异步时，任何 `ALTER ... DELETE` 后立刻重写都存在 race。
- 若保留 mutation，production engine 必须使用同步设置并验证 mutation 完成；否则改为不依赖异步 mutation 的 staging/swap/rebuild protocol。
- v1 仅 draft release，因此优先选择“整 release 可重建且可验证”的简单正确方案，不为增量热更新增加复杂度。
- summary purge/rebuild 范围必须和 base rewrite 范围一致；不能删除整个 release summary 却只重建 touched chromosomes。
- post-finalize 必须对 base + summaries 做完整校验。

#### G3.5 SQL 与重复冲突

- 所有 release/chromosome/输入派生值必须参数化；禁止 f-string 拼接上传文件内容到 SQL。
- exact duplicate variant 可 deterministic dedup。
- 同一 canonical `variant_id` 若 annotation/其他事实冲突：第一版建议 fail-closed，输出 diagnostics；不要静默任选一条。

#### G3 测试矩阵

- same bytes / same key retry。
- same bytes / different key retry。
- same semantic input concurrent workers。
- crash at PARSING/WRITING/VERIFYING/finalize-before-ack/finalize-after-ack。
- async/ambiguous ACK。
- quote/SQL-fragment chromosome negative test。
- duplicate identical row。
- duplicate conflicting row。
- touched subset vs pre-existing untouched chromosome。
- mutation wait failure/timeout。
- final base/summary checksum + count。

---

### G4 · Review / Merge Gate

PR #1 合并条件：

- 22 review threads 全部有 triage 结论。
- 所有 Confirmed High 已有 regression test + fix。
- unresolved High = 0。
- unresolved Medium = 0，或明确记录为 follow-up 且不影响 correctness/deployment/security。
- 重新请求一次 fresh code review。
- GitHub Actions 全绿。
- CNB 真 Docker Gate 全绿。
- feature flags 仍保持当前安全默认。

只有满足 G1–G4，才允许 merge PR #1。

---

## 2. 官方文档驱动的架构修正

### 2.1 Vue / Router / Pinia / VueUse

- Vue 生产线使用 latest stable，不跟 RC/beta；当前迁移基线保持已锁定 stable，升级必须独立提交。
- Vue Router 已进入 v5 稳定线；继续精确治理，不因迁移再引入第二套路由。
- Pinia 只做 client/global UI state；server state 继续由 TanStack Vue Query 管。
- VueUse 15 按 v15 breaking contract 使用，不增加兼容旧 API shim。

### 2.2 TanStack Query

新增项目规则：

- `packages/query-keys` 只表达 framework-neutral identity。
- Vue app 新建 typed `queryOptions` factory 层，将 queryKey/queryFn/staleTime/context 共置。
- 所有 query function result-affecting variables 进入 key。
- site variant / release / assembly 是 SoyMutDB 默认 cache namespace，不得由页面作者自行决定是否加入。

### 2.3 TanStack Charts

官方仍标记为 Alpha 0.x，当前 published line 文档为 0.18.0。允许后续全线迁移，但：

- exact pin，禁止 `^0.x`。
- 必须通过 `@soymutdb/charts` facade。
- 一个 chart 一个/一组可预览 commit。
- 每个 0.x minor upgrade 独立 PR。
- 图表必须有 ariaLabel/ariaDescription 和精确值替代（表格/下载），不能只靠 SVG。
- PR #1 未合并前不启动全量迁移。

### 2.4 pnpm 12

- workspace project settings 继续集中在 `pnpm-workspace.yaml`。
- lockfile 双文档属于 pnpm 12 行为，任何 scanner/governance parser 都必须覆盖。
- `allowBuilds` 保持最小白名单。
- 后续评估 `blockExoticSubdeps`、`trustPolicy: no-downgrade`；先用当前 lockfile 做兼容审计再启用。
- `minimumReleaseAge` 例外必须逐包、逐版本、有注释，不允许通配符放宽。

### 2.5 ClickHouse

- PostgreSQL manifest 是 exactly-once / logical visibility authority。
- ClickHouse 原生 dedup 只能做辅助；其窗口/重试稳定性不能替代应用协议。
- mutation/DELETE 等异步操作必须显式等待或从协议中移除。
- dynamic SQL values 使用 parameters。

### 2.6 CNB

CNB 继续作为 Docker 生产等价证明主骨架：

- `services: docker` 提供 dind + Docker CLI；
- buildx 可做多架构；
- CNB Docker registry 可保存镜像与 registry cache；
- GitHub 与 CNB 必须继续调用同一 shared scripts，禁止双逻辑漂移。

---

## 3. PR #1 关闭后的新 Phase 顺序

### Phase 1 · Full-stack Isolation + CNB Acceptance

目标：把“本地 E2”推进到真实 T8。

- CNB 启动 PostgreSQL + ClickHouse + Redis + MinIO。
- build API/worker/MCP/JBrowse/必要 frontend artifacts。
- migrations。
- seeded published release。
- unreleased sentinel。
- running API。
- external/internal artifacts。
- artifact-level ID-05 negative leakage。
- S3 put/head/get/checksum。
- ClickHouse production engine P2 finalize。
- Docker runtime smoke、Trivy、SBOM。

退出：P1-1 VERIFIED + CNB run/artifact/digest 可引用。

### Phase 2 · P2-4 / P2-5 / P2-6

- `module_data_rows → canonical` 显式 promotion。
- genes 先做第一 canonical module。
- 完整 retry/crash/concurrency matrix。
- 每种 scientific import 单独 Release Gate。
- 默认 OFF 的能力逐个评审，不批量开启。

### Phase 3 · Vue Canonical Portal Parity

在 PR #1 现有页面基础上继续，而不是重写：

- phenotype。
- Gene Preview merged genome context。
- JBrowse deep-link。
- remaining research tools。
- SSG/static route enumeration。
- external/internal build parity。
- canonical build/deploy 切换。

每页必须有独立可预览 commit / route / test evidence。

### Phase 4 · TanStack Charts

建立 `@soymutdb/charts`，逐图从 ECharts 迁移；最后一个单独 commit 删除 ECharts runtime/CDN/helper。

### Phase 5 · Vue Admin

Admin shell → dashboard → Import Studio → release/dataset/content/publication → analytics/settings。

### Phase 6 · Hardening

- dual-site/SSG regression。
- a11y / 390-1024-1440 / dark / reduced-motion。
- performance baseline/regression。
- S3/backup/restore。
- security/upload/SSRF/CSP。

### Phase 7 · React/ECharts Retirement

只有 Vue canonical delivery + full E2E parity 后：

- 删除 React active runtime。
- 删除 AntD React。
- 删除 React Router/Query adapters。
- 删除 ECharts。
- 删除旧 dead configs/scripts。
- historical docs/ADR 保留 archive。

### Phase R · Rust

仅在 import/search/chart/full-stack profile 有真实瓶颈证据后启动；控制面继续 Python。

---

## 4. Subagent 模型（从现在起生效）

默认最多 4 个 active coding subagents。同一文件同时只能一个 writer。

### 当前 PR #1 推荐四 Lane

1. `SUBAGENT-CI`：只处理 Python workspace install、GitHub/CNB shared bootstrap、workflow failure root cause。
2. `SUBAGENT-VUE-CORRECTNESS`：只处理 release/site/queryOptions/base URL/filter/deep-link/download/a11y。
3. `SUBAGENT-IMPORT-CORRECTNESS`：只处理 manifest locking、stable identity、resume、ClickHouse finalize、SQL params、duplicate policy。
4. `SUBAGENT-REVIEW-TEST`：read-only 为主，逐条验证 22 review comments、补 test plan、复核 diff。

主 Agent 独占：

- `plan.md`。
- `pnpm-lock.yaml` 最终协调。
- `.cnb.yml` / shared CI orchestration 的最终合并。
- DB migration sequence。
- feature flag 决策。
- PR merge。

任何 subagent 发现需要越权：STOP → 返回 change request 给主 Agent。

---

## 5. 提交与预览规则

继续保持每个逻辑变化可预览、可 revert。

PR #1 下一批推荐提交链：

1. `fix(ci): install workspace Python protocol packages consistently`
2. `fix(vue): bind release and site context into query options`
3. `fix(vue): honor deployment base and URL-backed filters`
4. `fix(vue): complete download and JBrowse parity`
5. `fix(import): stabilize logical import identity and serialize workers`
6. `fix(import): make ClickHouse finalize synchronous and scope-safe`
7. `fix(import): parameterize SQL and reject conflicting duplicates`
8. `test(import): close retry concurrency and finalize matrix`
9. `test(vue): close cache context and deep-link regressions`
10. `ci(cnb): close Docker runtime acceptance`
11. `docs(plan): record PR #1 exit evidence`

不要 squash 这些有独立诊断价值的 commits。

每个 commit 必须报告：SHA、purpose、changed files、focused test、preview/repro、risk、next。

---

## 6. 测试链 T0–T11

| 层 | 内容 |
| --- | --- |
| T0 | lint/typecheck/contracts/architecture/dependency/feature-flag |
| T1 | unit |
| T2 | Vue component/store/queryOptions/chart facade |
| T3 | real PostgreSQL/ClickHouse/Redis/MinIO integration |
| T4 | API/OpenAPI/RBAC/release/assembly/presign contracts |
| T5 | external/internal artifact/SSG/CSP/SW/leakage |
| T6 | browser E2E research workflows |
| T7 | visual/a11y/responsive/dark/reduced-motion |
| T8 | Docker/CNB runtime |
| T9 | Trivy/SBOM/license/secret/upload/SSRF/security |
| T10 | crash/retry/backup/restore/rollback/publication |
| T11 | bundle/search/import/chart/CI performance regression |

风险越高，要求覆盖层级越高。P2 finalize 不能只以 T1/T2 通过关闭；至少需要 T3 + T8 + T10。

---

## 7. 固定科研回归任务

1. Gene ID → Gene → mutant → variant → JBrowse。
2. Phenotype → mutant → genomic evidence。
3. Region → variants → variant detail → JBrowse。
4. Mutant public ID → phenotype/gene/variant/download。
5. Search exact/prefix/general，release/site 切换后缓存不串。
6. URL filter → reload/back/forward 结果一致。
7. Admin S3 upload → bind release/assembly → validate → import → verify。
8. Failed import → diagnostics → safe retry。
9. Published release vs unreleased sentinel negative leakage。
10. CNB image → migrations → health → PG/CH/S3 smoke。

---

## 8. PR #1 Merge Checklist

- [ ] GitHub CI success。
- [ ] Baseline workflow success / 或正式 ADR 替代。
- [ ] CNB shared scripts success。
- [ ] 22 review threads triaged。
- [ ] unresolved High = 0。
- [ ] queryOptions/cache namespace tests green。
- [ ] base URL/site variant/deep-link tests green。
- [ ] real adapter VCF path verified fail-closed or protocol-driven。
- [ ] per-fingerprint serialization tested。
- [ ] stable variant identity across object-key retry。
- [ ] VERIFYING retry tested。
- [ ] ClickHouse mutation/finalize race closed。
- [ ] summary untouched-partition regression green。
- [ ] SQL parameterization negative test green。
- [ ] conflicting duplicate policy green。
- [ ] P1 feature flags remain safe defaults。
- [ ] fresh review requested。
- [ ] plan evidence updated。

---

## 9. 官方资料索引（2026-09-23 复核）

- Vue releases: https://github.com/vuejs/core/releases
- Vue Router: https://router.vuejs.org/ and https://github.com/vuejs/router/releases
- Pinia: https://pinia.vuejs.org/ and https://github.com/vuejs/pinia/releases
- VueUse 15: https://github.com/vueuse/vueuse/releases/tag/v15.0.0
- TanStack Vue Query keys: https://tanstack.com/query/latest/docs/framework/vue/guides/query-keys
- TanStack Vue Query options: https://tanstack.com/query/latest/docs/framework/vue/guides/query-options
- TanStack Charts: https://tanstack.com/charts/latest/docs/installation
- TanStack Charts a11y: https://tanstack.com/charts/latest/docs/guides/accessibility
- pnpm settings: https://pnpm.io/settings
- pnpm supply chain: https://pnpm.io/supply-chain-security
- ClickHouse docs: https://clickhouse.com/docs/
- CNB grammar: https://docs.cnb.cool/zh/build/grammar.html
- CNB Docker artifacts: https://docs.cnb.cool/zh/artifact/docker.html

---

## 11. 前端全线切换 Vue + 回归（2026-09-25 本轮）

### 11.1 目录与 canonical 切换

- `apps/web-vue` → **`apps/web`**（Vue portal 占据 canonical 路径）；React portal（约 32k 行）与
  `page-builder` 运行时、嵌入 demo fixtures 一并删除。
- 框架中立层落到 `packages/shared`：`deployment.ts`（部署 origin/CSP/dev host 白名单）、`genomics`、
  `primer-design`、`jbrowse-bridge`、`analyses-upload`、`analyses-local`、`incremental-sha256`；
  React admin 与 jbrowse 继续经 `@soymutdb/shared/deployment` 共用同一实现。
- `apps/web` 新构建链：
  `vite build → generate-static-routes → finalize-csp → gzip-compress → gen-sw → release-manifest`
  （`_headers`/`_redirects`/`favicon.svg`/`sw.js` 随应用交付；`gen-sw` 缓存名带 site variant，
  双站点缓存不再共名）。

### 11.2 生产门禁对齐（否则切换只会让 gate 失真）

| 门禁 | 变化 |
| --- | --- |
| `check-bundle-size.sh` | antd/pro/react 拓扑 → `ui`(Antdv Next)/`vue`/`query`/`index` 四个 chunk 预算（实测 79/33/12/106 KB） |
| `check_artifact_headers.py` | “script-src 必须含 sha256” 改为“已 finalize 的证明”：Vue shell 无 inline script，空 hash 并集是合法结果；保留 origin 与 `unsafe-inline` 两项证明 |
| `check_web_query_keys.py` | React 路由清单 → Vue 视图层：必须走 `assembliesQueryOptions()`，禁止手写 `assemblies` key 或直接用 `queryKeys.assemblies` |
| `turbo.json` | strict env 模式漏传 `VITE_SITE_VARIANT`/`RAYON_NUM_THREADS`/`SOYMUTDB_EMIT_GZ`/`SOYMUTDB_VUE_DIST_DIR` → 补入 build env |
| `check_workspace_exports.py` / contract 测试 | 同步新路径（`packages/shared/src/deployment.ts`、Vue 构建脚本）；脚本可执行位在 SMB 挂载下回退到 git index 判定 |

### 11.3 门户产品面补齐

- `HomeView` 从 Checkpoint D 脚手架改为数据库首页：标识符搜索 → 五个任务入口 → assembly 目录 → news；
  e2e 断言“news 不得排在任务入口之前”。
- `SearchGenesView` 结果表改为 `ConfigurableTable`（模板驱动），空结果也渲染表头——列缺失要看得见。
- `SearchLocationView` 支持 `?run=1` 深链自动执行一次（与 React 契约一致），非法区间/染色体不发请求。
- `LoginView` 走 `authRequest` + `setAccessToken`；`?redirect=` 白名单为同站路径（防开放重定向）；
  401 文案统一为通用 "Invalid email or password."（不做账号存在性预言）。

### 11.4 e2e 回归（Vue 制品，`/soymutdb-next/`）

- 静态服务器新增 `/table-views/{kind}` 与 `/news` mock；镜像 API built-in 默认列顺序。
- 重写 homepage / search / genes / blast / accessibility / public-login 规格到 Vue portal 的 testid 与契约。
- 结果：`playwright-public.config.ts` → **29 passed, 2 skipped**（skip 仍是需后端的 live-result 用例）。

### 11.5 回归全量结果

| 层 | 结果 |
| --- | --- |
| `apps/web`（Vue） | 21 files / **79 tests**；typecheck + lint 干净 |
| `packages/shared` | **49 tests**（含 deployment/primer/analyses/sha256） |
| api-client / i18n-core / query-keys / ui-vue / genome-view-model | 116 / 6 / 10 / 4 / 13 |
| `apps/admin` | 48 files / **127 tests**；lint 0 error（53 既有 warning） |
| `apps/api`（真实 PG 55433） | `tests/ -m "not integration"` → **1236 passed**；`a0`（需 `PYTHONPATH=.`）45 passed |
| `apps/worker` | **334 passed, 24 skipped** |
| Python 契约（`scripts/`） | **264 passed, 1 skipped, 9 subtests** |
| 制品门禁 | production 扫描 STRICT OK；artifact headers OK；nginx OK；bundle OK；静态 smoke PASS；acceptance STATIC PASS；双站点隔离 PASS |

顺带修掉两个真实缺陷（均在真实 PostgreSQL 上才暴露）：
- `local_test_preview_service` 的 GROUP BY 无法覆盖 eager 关系列 → 改为相关 scalar 子查询计数。
- `detectLanguage` 在 jsdom（bare global 缺失）下抛错 → 防御式读取 storage。

仍未解决：`apps/admin/src/routes/widgets/$name.tsx` 的 zod v3/v4 resolver 类型不匹配（既有，admin typecheck 红）；
turbo 并发构建在本沙箱触发线程上限（`os error 11`），逐包构建正常，CI 不受影响。

## 13. 基线发布状态（2026-09-25 本轮收尾）

### 13.1 已推送

- `main` 到 `4237ae0ce`（GitHub `origin`）；`v2.1.0` annotated tag 指向同一提交，含发布说明。
- **CNB 推送被凭据阻塞**：本环境无 cnb.cool 凭据（只有 gh 的 GitHub token），
  `git push cnb main` 报 `could not read Username for 'https://cnb.cool'`。
  真实镜像发布流水线 `release-tagged` 在 CNB 上，需要人工推送 main + tag 后触发。

### 13.2 CI 状态（run 36154013825 / tag 同日）

八个 job 中：

| job | 结果 |
| --- | --- |
| MCP transport e2e / ClickHouse migration fixture / API tests | **success** |
| Frontend build + contract | 验证脚本 **通过**，仅 `Upload GitHub Pages demo artifact` 因配额失败 |
| Dependency graphs + governance | 审计 **通过**（16/16），仅 `Upload dependency governance evidence` 因配额失败 |
| Docker/镜像/Kind | skipped（依赖上面两个 job 成功） |

即：**代码层面全绿**，唯一阻塞是 GitHub Actions **artifact 存储配额**（账户级）。
本仓库缓存已从 1.96 GB 清到 0.77 GB；GitHub 每 6–12 h 重算一次配额。
`Deploy Web to Pages` 门控在 CI success，因此也停在 failure，`E2E Smoke` 被 skip。

### 13.3 本机回归（本轮，全部实测）

| 层 | 结果 |
| --- | --- |
| packages | shared 49 / charts 2 / api-client 116 / i18n-core 6 / query-keys 10 / ui-vue 4 / genome-view-model 13 |
| apps | web 79 / admin 8 / jbrowse 2 |
| typecheck + lint | 上述全部包与 app（含 jbrowse）全 OK |
| apps/api（真实 PG 55433） | 1236 passed（+ a0 45，需 `PYTHONPATH=.`） |
| apps/worker | 334 passed, 24 skipped |
| scripts 契约 | 263 passed, 1 skipped |
| 治理审计 | 16/16 passed（knip、deptry×3、cycles×3、licenses×4、audit×4） |
| 制品门禁 | production 扫描 / artifact headers / nginx / bundle 预算 / contracts smoke / 双站点隔离 全 PASS |
| e2e | public 29 passed, 2 skipped；admin production 3 passed |

### 13.4 剩余（均已记录，非本轮可完成）

1. GitHub artifact 配额恢复后，`Deploy Web to Pages` 与两个 evidence 上传会自动恢复。
2. CNB 推送 + `release-tagged` 镜像发布（需凭据）。
3. 远程物种实例访问模型（用户明确后置；`species_instances` 表与登记页已就绪）。
4. e2e 规格尚未覆盖 `/analytics`、`/compare` 与 Vue admin 的登录后页面
   （admin 无公开面，登录后需真实凭据）。

## 12. Phase 4/5 完成：Charts facade + Vue Admin（2026-09-25 本轮）

### 12.1 Phase 4 · `@soymutdb/charts`

- 新包 `packages/charts`（`@soymutdb/charts`）：唯一的图表依赖入口。TanStack Charts
  **精确固定 0.18.0**，落在独立 catalog `charts:`（pre-1.0 不用 caret）。
- `ChartFigure.vue` 强制两件契约：图形带 `aria-label`/`aria-description`，并**始终**附带一份
  精确数值 `<table>`（`<details>` 内）。空数据渲染空态而不是占位序列。零值渲染为 0，
  不折叠成空白（"未观测" 与 "观测到 0" 必须可区分）。
- `categoryBarChart` / `trendAreaChart` 是定义工厂（marks + scales 共置）。
- `apps/web` 的 `/analytics` 页面按此实现：染色体密度、变异类型、影响分布、后果×影响、
  诱变剂对比、365 天发现趋势；每块都是表优先、图其次、错误态可重试。
- 分包：`charts` 独立 chunk（36 KB gzip，预算 60 KB）；此前它被并进 `query` chunk，
  导致 query 预算实际在量图表运行时。

### 12.2 Phase 5 · Vue Admin

`apps/admin` 由 React 切换为 Vue（React admin 约 7.1k 行路由 / 85 文件删除）。

| 页面 | 内容 |
| --- | --- |
| `login` | 走 `authRequest` + `setAccessToken`；401 文案通用（不做账号存在性预言）；`?redirect=` 白名单同站路径 |
| `dashboard` | 当前 release 的状态与计数（来自 release 聚合行，不是分页求和） |
| `releases` | release 列表 + 按需 provenance |
| `imports` | 服务端分页 + 状态筛选的导入任务 |
| `table-templates` | 本轮新增的表格模板管理（列顺序/显隐/同源列/尾部动作/设为默认） |
| `publications` | 完整 CRUD + 删除确认（列出 DOI） |
| `news` | 列表 + 创建/编辑/软删除/恢复，草稿与发布状态显式 |
| `media` | 列表 + 归档（不硬删：被已发布内容引用） |
| `audit` | 只读审计日志（可编辑的审计就不是审计） |
| `features` | 能力开关，含 OFF 项（隐藏 OFF 会让"未实现"与"缺失"不可区分） |
| `settings` | 表单由后端 schema 生成，带 `expected_version` 乐观锁 |

会话与传输边界有专门门禁（`check_admin_content_architecture.py` 重写）：视图不得直接
`fetch()`，不得读写 web storage。admin `_headers` 的 CSP `connect-src` 在构建期由
`injectApiOrigin` 写入真实 API origin（源文件保持保守同源策略，不留占位）。

### 12.3 有意移除（有 ADR）

- **ADR-0008**：不迁移 `/antd-pilot`（自 Referential 组件样例页，无消费者；设计系统契约在
  `@soymutdb/ui-vue` 的 facade 测试里）。
- **ADR-0009**：退役 page builder 与 widget 系统。Vue 门户不消费 `page_definitions`/widget
  registry —— 切换后它们只剩 admin 自己的 preview 一个消费者。表与 API 保留（删数据是另一件事）。

### 12.4 `/compare` 重写为 DB 驱动

React 版 `/compare` 对比的是硬编码 demo fixture，与 release 内容无关。Vue 版改为：id 来自
URL（`?ids=`，上限 4），逐个 `getVariantDetail` 取真实记录，**显式列出当前 release 中不存在的 id**
而不是静默丢弃；字段行由一张表驱动，position 行链到 JBrowse、gene 行链到基因详情。

### 12.5 本轮验证

| 层 | 结果 |
| --- | --- |
| `packages/charts` | 2 tests；typecheck/lint OK |
| `packages/shared` | 49 tests |
| api-client / i18n-core / query-keys / ui-vue / genome-view-model | 116 / 6 / 10 / 4 / 13 |
| `apps/web` | 21 files / **79 tests**；typecheck + lint OK；构建产出 27 个静态文档 |
| `apps/admin` | **4 tests**；typecheck + lint OK；构建 OK |
| `apps/jbrowse` | 2 tests；typecheck + lint OK |
| `apps/api`（真实 PG） | 1236 passed |
| scripts 契约 | **263 passed, 1 skipped** |
| 治理 | `dependency governance: passed`（knip/deptry/cycles/licenses/audit 全绿，16 项） |
| 制品门禁 | production 扫描 OK；artifact headers OK；nginx OK；bundle（ui 79 / vue 33 / query 14 / charts 36 / entry 110 KB）OK；smoke contracts PASS；双站点隔离 PASS |

e2e 尚未按新页面（analytics/compare/admin）扩充规格，仍是上一轮的 29 passed / 2 skipped。

## 10. Phase 3 收尾 + 可配置表格（2026-09-25 本轮）

本轮目标：把 Vue portal 推到“路线齐全”，同时交付运营要求的**可配置表格**与**多物种实例登记**；
React portal 仍为当前 canonical，尚未切换也未删除（Phase 7 前置未完成）。

> **订正（2026-09-26，追加而非改写历史）：** “React portal 仍为当前 canonical” 是本段
> 当时的状态，已被后续提交推翻。本文件 `11.1 目录与 canonical 切换` 记录 `apps/web-vue` →
> `apps/web`，Vue portal 占据 canonical 路径、React portal（约 32k 行）已删除；`12.2 Phase 5 ·
> Vue Admin` 记录 admin 也切换为 Vue。`255`、`974` 行的同类表述同理失效。当前状态以 §11/§12
> 为准，证据：`apps/web/src/App.vue` + `apps/web/src/router/routes.ts`（Vue 路由表）。

### 10.1 测试环境恢复（前轮阻塞解除）

- 本机 pnpm **12.5.1** 可用，`pnpm install --frozen-lockfile --offline` 通过；前端依赖链完整。
- PostgreSQL 16（`.mamba-root/envs/postgres16`）在 **127.0.0.1:55433** 启动（55432 被本地预览实例占用），
  按 `docs/dev/mamba-validation-environment.md` 建 `soymutdb_validation` 与 `soymutdb_testfixtures`；
  `SOYMUTDB_TEST_DATABASE_URL` 绕过 testcontainers，**真实 PostgreSQL 集成测试可运行**。

### 10.2 已落地

| 面 | 内容 | 状态 |
| --- | --- | --- |
| 测试修复 | `web-vue` 9 个失败测试全部修复（表单提交需 attachTo document.body；静态路由期望值与新增路由对齐） | VERIFIED（20 files / 71 tests） |
| 共享层 | `packages/shared` 新增 `genomics`（染色体词表 / 1-based 坐标格式化 / JBrowse 深链）、`primer-design`、`jbrowse-bridge`、`analyses-upload`（纯函数）、`analyses-local`、`incremental-sha256`，并接入 `test`/`lint`/`typecheck` | VERIFIED（33 tests） |
| i18n | `@soymutdb/i18n-core` 的 `detectLanguage` 改为防御式读取 storage；`apps/web-vue/src/lib/i18n.ts` 提供响应式 `t`（**非 computed**，避免 slot 内 `_ctx.t` 解包后 `.value` 为 undefined） | VERIFIED |
| 门户框架 | `PortalLayout` / `PortalHeader` / `PortalFooter`：一条导航 + 站点变体与 release 上下文 | VERIFIED |
| Vue 路由补齐 | `/genes`、`/search/genes`、`/search/location`、`/search/gbrowse`、`/search/primer`、`/browser`、`/blast`、`/analyses`(+`/fastp` `/scanpy` `/:jobId`)、`/sra`、`/seed-request`、`/guide`、`/help`、`/about`、`/publications`、`/login` | IMPLEMENTED（构建产出 25 个静态文档） |
| query-options | 新增 `geneList`/`geneSearch`/`regionVariants`/`assemblyChromosomes`/`tableView` 工厂，视图不再手写 key | VERIFIED（typecheck/lint 干净） |
| 上传链路 | `submitAnalysisFiles` 下沉到 `@soymutdb/api-client`（纯函数留在 shared）；React hook 改为薄封装，两端同一实现 | VERIFIED（api-client 116 tests） |
| **可配置表格** | `table_view_templates` + `species_instances`（migration 0039）、公开 `/table-views/{kind}`、admin CRUD、`ConfigurableTable.vue`、`/search/location` 改为模板驱动、admin `/table-views` 页 | VERIFIED（真实 PG 8 tests + migration 升级/降级 + Vue 6 tests） |
| 清理 | 删除 `eslint_out.txt`、`tsc_out.txt`、`e2e/tmp-dom-dump.mjs`、`e2e/tmp-inspect-deploy.mjs` | 完成 |

### 10.3 本轮验证证据

- `apps/web-vue`：**21 files / 77 tests passed**；`typecheck` + `lint` 干净；`vite build` 产出 25 个
  `*/index.html` + `routes.json` + `robots.txt`（sandbox 需 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`）。
- `packages/shared`：33 tests；`packages/api-client`：116 tests；`apps/web`：145 tests + typecheck。
- `apps/admin`：48 files / 127 tests；lint 0 error（53 个 warning 为既有）。
- `apps/api`：真实 PG 16（55433）→ `test_table_views.py` **8 passed**、`test_migrations.py` **11 passed**
  （含 0039 升级/降级与 `coalesce(release_id,0)` 唯一索引的反例验证：同 kind/species/variant 两条
  `is_default=true` 且 `release_id` 均为 NULL 时，第二次插入被拒）。
- 既有未解决（非本轮引入）：`apps/admin/src/routes/widgets/$name.tsx` zod v3/v4 resolver 类型不匹配，
  `pnpm --filter @soymutdb/admin typecheck` 因此仍红；`apps/api` 的 docker 依赖集成测试在本机不可运行。

### 10.4 未完成 / 下一步

1. **canonical 切换仍未做**：`apps/web`（React）仍是发布路径；本轮的 Vue portal 尚未跑 Playwright E2E parity。
2. `apps/admin` 仍是 React（Phase 5）；本轮只在既有 admin 中新增了模板管理页。
3. 远程物种实例的访问模型（CORS 直连 vs 本地 API 代理）需要决策后才能实现“一个面板管多台服务器”的切换器，
   数据模型已就绪（`species_instances`，无需再迁移）。
4. `.cnb.yml` / `scripts/*` 中的 `apps/web/dist` 路径仍是 React 产物路径。

## 10. 当前 Next（2026-09-24 核对）

PR #1 已合并。仓库 `main` 当前 HEAD 为 `d3904c210`，与 `origin/main` 指向相同提交；最近提交继续推进 Vue Phase 3 页面与 transcript 契约。

### 最近一次可取得的 CI 证据

- CI run `35891669951`（HEAD `d3904c210`）整体失败：API 测试、ClickHouse migration fixture、MCP e2e 和前端验证通过；Dependency governance 与 Pages demo 工件的上传因 GitHub Actions artifact storage quota 用尽而失败。Docker、Kind 和镜像发布因此跳过。
- Baseline run `35891669950` 的 OpenAPI 检查、API 测试和 Web/Admin 构建步骤通过；相关工件上传同样因配额失败。
- Pages run `35892690486` 因同一提交的 CI 未成功而未发布。
- 这些是最近一次成功读取到的 GitHub 状态（2026-09-23 17:00 UTC 左右）。2026-09-24 的刷新尝试遇到 GitHub API 网络错误，不能据此判断配额现在是否恢复。

### 本机阻塞

- 当前 shell 的 PATH 中没有 Docker CLI、`pg_isready`、`clickhouse-client` 或 `redis-cli`；本轮无法启动或核验 T8 所需的本地全栈环境。
- SMB 工作区将脚本呈现为 `0664`，且 `chmod +x` 不改变可见权限；Git 因而显示 45 个仅有 `100755 → 100644` 的工作树差异，没有内容差异。不要将这些权限噪声作为功能改动提交。

### 下一步

1. GitHub API 可用且距上次配额错误达到重算窗口后，检查配额与 `d3904c210` 的新 CI / baseline / Pages 结果；确认工件上传恢复，并处理任何剩余的真实失败。
2. 用 GitHub/CNB 可用的环境推进 Phase 1 full-stack isolation + CNB acceptance；本机缺少 Docker，不能把 T8 记为通过。
3. Phase 1 验收后按主计划继续 Phase 2；Vue Phase 3 已补 gene merged genome context、JBrowse 深链接、gene expression/homolog 与 SeqFetch。Enrichment / ExpPattern 需先完成 assembly-aware API 契约，之后再移植；仍需 external/internal build parity 和 canonical deployment 切换。

> PR #1 的审计门禁与提交证据保留在上文作为历史记录；后续状态以本节最近可验证的运行结果和新 CI 结果回填。
