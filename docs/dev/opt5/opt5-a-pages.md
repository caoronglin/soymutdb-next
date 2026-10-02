# opt5-a — 后台可编辑文案接线（4 个页面）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

范围：把 React 门户当年真正消费过的 `content.*` 文案键接到 Vue 门户的
4 个页面，使用已就绪的 `apps/web/src/lib/site-content.ts::useSiteContent()`。
零覆盖时除「注册键的默认译文与被替换的本地占位译文不同」的少数表头外，页面
文案保持不变；有覆盖时（任何语言）显示覆盖值。

未改 `lib/site-content.ts`、`packages/**`、其它 views/components、`style.css`、i18n。

## 1. 接线映射表

调用形态一律 `get("<key>", t("<fallback>"))`；fallback 保留，未做透传简化。

### BlastView.vue（12）

| 后端键 | 文件:位置 | i18n fallback |
| --- | --- | --- |
| `blast.database` | 数据库字段 `<label>` | `t("blast.database")` |
| `blast.input` | 序列输入框 `<label>` | `t("blast.inputSequence")` |
| `blast.submit` | 提交按钮文案（非 running 分支） | `t("blast.submit")` |
| `blast.searchType` | 检索类型字段 `<label>` | `t("blast.searchType")` |
| `blast.databasePlaceholder` | 数据库 select 普通占位 `<option>`（非加载中） | `t("blast.databasePlaceholder")` |
| `blast.sequencePlaceholder` | 序列输入框 `placeholder` | `t("blast.sequencePlaceholder")` |
| `ui.loading` | 数据库 select 占位（仅 `databasesLoading` 时取代 placeholder） | `t("common.loading")` |
| `blast.hitSequenceId` | 命中表第 1 列表头 | `t("blast.hitSequenceId")` |
| `blast.hitCoverage` | 命中表第 2 列表头 | `t("blast.hitCoverage")` |
| `blast.hitEValue` | 命中表第 4 列表头 | `t("blast.hitEValue")` |
| `blast.hitGeneId` | 命中表第 5 列表头 | `t("blast.hitGeneId")` |
| `ui.noResults` | 任务空态 `blast-hits-empty` **与** 命中空态 `blast-hits-none`（同键两处、fallback 不同，照 React） | `t("blast.noJobs")` / `t("blast.noHits")` |

### DownloadsView.vue（2）

| 后端键 | 文件:位置 | i18n fallback |
| --- | --- | --- |
| `downloads.title` | 页面 `<h1>` | `t("downloads.title")` |
| `downloads.subtitle` | 副标题 `<p>` | `t("downloads.subtitle")` |

### GenesListView.vue（2）

| 后端键 | 文件:位置 | i18n fallback |
| --- | --- | --- |
| `genes.title` | `<PageHeader :eyebrow>` | `t("genes.title")` |
| `genes.subtitle` | `<PageHeader :title>` | `t("genes.subtitle")` |

### VariantsView.vue（2）

| 后端键 | 文件:位置 | i18n fallback |
| --- | --- | --- |
| `variants.title` | `<PageHeader :eyebrow>` | `t("variants.title")` |
| `variants.subtitle` | `<PageHeader :title>` | `t("variants.subtitle")` |

### 命中表表头落点说明

Vue 命中表被简化为 5 列（subject / identity / alignmentLength / hitEValue /
hitScore），React 有 6+ 列（assembly / hitSequenceId(键名 `subject`) /
hitCoverage(percent_identity) / hitEValue(evalue) / hitGeneId(subject_id) /
gbrowse）。4 个注册键按「渲染数据 + React 列键名」映射到 col1/col2/col4/col5；
`blast.alignmentLength` 保持未注册的 `t(...)`。`blast.hitGeneId` 落在 col5 是
位置化选择（React 的 gene 列紧跟 evalue 之后；Vue 无独立 gene 列），
如需改落 col1 是一行替换。

由于 fallback 取注册键自身译文，命中表 3 个表头文案相对接线前有变化
（Subject→Sequence ID、Identity→Coverage、Score→Gene ID）；这是协调者冻结表
给定的 fallback。其余页面文案逐字不变。

### `ui.loading` 说明

React 把 `get("ui.loading", t("common.loading"))` 用作数据库下拉 loading 选项；
Vue 数据库 select 的占位是禁用空 `<option>`，故按 `databasesLoading` 在
loading（`ui.loading`）与普通占位（`blast.databasePlaceholder`）之间切换，
两种语义分离，互不覆盖。

### 顺手修复的 BlastView 既有 bug（必要）

`hitsQuery.isLoading` / `submitMutation.isError` 是 `useQuery`/`useMutation` 返回的
ref，模板里未解包（恒为真对象），导致命中表**从不渲染**且错误横幅**恒显示**。
改为既有惯例的 `toValue(...)` 后，命中表才可渲染、本轮的命中表头接线才可见。
这也让默认渲染更正确：错误横幅不再常亮，命中表按数据渲染。
`blast-error` / `blast-hits-*` 无其它测试或 e2e 引用。

## 2. 跳过清单

**经协调者更正**：BlastView 原有 8 个「未注册」键实为注册键（此前用只匹配小写
的正则误判 camelCase）。更正后 **Blast 全部 12 个注册键已接线**。真正未注册的
仅 downloads/genes/variants 三组：

- DownloadsView：`downloads.download`、`downloads.fileName`、`downloads.fileSize`、
  `downloads.format`、`downloads.lastUpdated`、`downloads.preview`、
  `downloads.too_large`（未注册，React 当年也只会 fallback）。
- GenesListView：`genes.allBiotype`、`genes.allChromosomes`、`genes.biotype`、
  `genes.biotypeLabel`、`genes.chromosome`、`genes.chromosomeLabel`、`genes.geneId`、
  `genes.noResults`、`genes.position`、`genes.search`、`genes.searchPlaceholder`、
  `genes.symbol`、`genes.variantCount`（未注册）。
- VariantsView：`variants.allChromosomes`、`variants.allImpacts`、`variants.allTypes`、
  `variants.chromosome`、`variants.chromosomeLabel`、`variants.export`、
  `variants.geneSymbol`、`variants.impact`、`variants.impactLabel`、`variants.noResults`、
  `variants.positionLabel`、`variants.variantType`、`variants.variantTypeLabel`（未注册）。

附注：`blast.eValue`、`blast.maxHits` 也在 registry 注册，但 React 用普通
`t(...)` 消费、不在本轮 12 键清单内，保持 `t(...)`。

## 3. 测试

- 既有 api-client mock 补 `getSiteContent: vi.fn()`，`beforeEach` 默认
  `mockResolvedValue({})`。
- `BlastView.test.ts`（新建，6 条）：默认 12 键 fallback、三标签覆盖、
  searchType/placeholder/空态覆盖、`ui.noResults` 用于命中空态、命中表头覆盖、
  `ui.loading` 覆盖占位。
- `DownloadsView.test.ts` +2、`GenesListView.test.ts` +3、`VariantsView.test.ts` +3。
- Genes/Variants 额外断言「zh 无覆盖仍是中文」（防覆盖为空却翻英文的核心回归）。
- 未删除 / 弱化任何既有断言，未 `it.skip`。

## 4. 验证证据（全部 exit 0）

```
pnpm --filter @soymutdb/web exec vitest run src/views/BlastView.test.ts \
  src/views/DownloadsView.test.ts src/views/GenesListView.test.ts src/views/VariantsView.test.ts
# 4 passed / 32 tests，exit 0
pnpm --filter @soymutdb/web test
# 55 passed / 302 tests，exit 0（上一轮基线 53 / 286，只增不减）
pnpm --filter @soymutdb/web typecheck   # exit 0
pnpm --filter @soymutdb/web lint        # exit 0
python3 scripts/check_visible_i18n.py   # "visible i18n OK"，exit 0
VITE_API_BASE_URL=http://localhost:8010 VITE_JBROWSE_BASE_URL=http://localhost:5175 \
  pnpm --filter @soymutdb/web build     # exit 0，27 documents（首次因 esbuild OOM 崩溃，重跑成功）
```

## 5. 未完成 / 风险

- 命中表头落点（尤其 `blast.hitGeneId` → col5）为位置化选择，可按需改 col1。
- 表头 fallback 用注册键自身译文，故 3 个表头文案相对接线前变化；如需保持旧译文，
  改成 `get(key, t("blast.hitSubject"))` 等即可。
- 未新增 i18n key，未新增依赖。
- 未执行任何 git 写操作。
