# OPT5 第五轮：内容键接线收口 + 协调者三处纠正（2026-09-27）

- **方式**：协调者（定界/自查/纠正/验收）+ 2 个子代理（A: 4 个列表页；B: 帮助/指南/两个检索页），`nwafu/DeepSeek-V4.1-Flash`。
- **目标**：把 React 真正消费过的 `content.*` 键全部接线，收口 GAP-04。
- **前提**：HEAD `053666680` + 五轮未提交改动；本轮改动同样**未提交**。

## 1. 交付

| 范围 | 内容 |
| --- | --- |
| 首页 | `hero.image`（运营设置的 Hero 图；仅绝对 http(s)/站内相对路径渲染，`javascript:`/`data:`/协议相对/反斜杠一律丢弃）+ 3 条测试 |
| 列表页（A） | BlastView 12 键、DownloadsView 2 键、GenesListView 2 键、VariantsView 2 键 |
| 帮助/检索（B） | HelpView 15 键（含 FAQ `help.faq{i}.q/a` ×12，`faq{i}` ↔ 目录 `q{i}` 一基下标映射）、GuideView 2 键、SearchGenesView 15 键、SearchLocationView 15 键 |
| i18n（协调者） | 补 4 个缺键：`help.q6.q`、`help.q6.a`、`search.genes.resultsRetry`、`search.location.resultsRetry`（此前无覆盖时会**直接显示原始 key**） |

## 2. 协调者自查发现并修正的三处问题（含我自己的错）

### 2.1 我的键表是错的（我的责任）

我给子代理的「不要接的键」清单，是用正则 `_definition\(\s*"content",\s*"([a-z0-9_.]+)"` 提取的——**字符类只有小写**，把 **全部 camelCase 键**（`blast.searchType`、`ui.noResults`、`search.genes.colAssembly`…）误判成"未注册"。

- 实际注册的 content 键是 **131 个**（不是 84），其中 **47 个是 camelCase**。
- 影响：Blast 的 8 个键、SearchGenes/SearchLocation 的多个键被错误地要求"跳过"。
- 处理：重新用大小写正确的提取定界，**立即给两个子代理发更正指令**（A 已收工、被叫回补完 8 键；B 在跑、当场改表），并把提取脚本固化为 `.validation/opt5/content-coverage.py`（大小写正确 + 识别 map 式接线 + 区分"React 从未引用"与"React 引用但仍未接"）。
- **教训**：正则字符类驱动"什么算已注册"这种事实判定太脆；改成脚本化 + 可复跑 + 输出可核对清单。

### 2.2 子代理把两个键接到了语义错误的位置（协调者改回）

| 位置 | 子代理做法 | 问题 | 协调者修正 |
| --- | --- | --- | --- |
| Blast 命中表第 5 列 | 标注为 `blast.hitGeneId` | 该列渲染的是 **`bit_score`**，把分数标成"基因ID"是**描述错误的数据** | 改回 `t("blast.hitScore")`，并注明：React 第 5 列是"subject_id + 跳转基因检索"的按钮列，Vue 命中表列集不同（见 §4），`blast.hitGeneId` 暂无可落列 |
| GuideView 标题 | h1 改成 `get("nav.guide", …)`，另加 `help.documentation` 眉题 | 丢掉了 API 页面标题；React 是「Tag 徽标显示 nav.guide + `<h1>{title}</h1>`」 | h1 恢复 API 页面标题；眉题改为 `get("nav.guide", …)`（对齐 React 的徽标位）；`help.documentation` 不在本页硬造槽位（它已在 HelpView 被消费） |

两处都同步改了对应测试的期望（测试原本把错误结构钉住了）。

### 2.3 子代理顺手发现的一个真 bug（协调者确认并保留）

`BlastView.vue` 模板里 `submitMutation.isError`、`hitsQuery.isLoading` 是 **ref 对象而非解包值** → 恒为真 → **命中表永远不渲染、错误横幅恒显示**。子代理改为 `toValue(...)`（与该文件既有 `isSubmitting` 一致）。协调者确认：这是真 bug 且修法正确，命中表因此才可见（也是本轮表头接线能被看到的前提）。

## 3. 接线覆盖率（`.validation/opt5/content-coverage.py`，可复跑）

```
registered content keys : 131
wired by the portal     : 105
unwired                 :  26
  of which React never referenced (no UI slot to port): 25
  of which React referenced but still unwired (ACTION):  1   -> blast.hitGeneId
```

- **React 真正消费过的注册键已 100% 接线，唯一例外是 `blast.hitGeneId`**（原因见 §2.2/§4）。
- 25 个"React 从未引用"的键（`common.empty/reset/...`、`genes.col*`、`variants.col*`、`search.location.col*`、`tool.*.image`、`ui.submit`、`guide.title/subtitle`…）**不是对等缺口**：React 当年也没消费它们。若要可编辑，属新增产品面（后端已注册，前端只是还没有槽位）。

## 4. 已知剩余差异 —— **已于 goal round 4 闭合**

Blast 命中表的**列集**曾与 React 不同：

| React 列（`routes/blast.tsx`） | 内容键 | Vue 列（本轮之前 → 之后） |
| --- | --- | --- |
| assembly | — | 无 → 无（仍缺，见下） |
| subject（输入序列 ID = query FASTA header） | `blast.hitSequenceId` | 无 → 无（仍缺，见下） |
| identity/coverage（`percent_identity`） | `blast.hitCoverage` | col2 ✅ |
| evalue | `blast.hitEValue` | col4 ✅ |
| gene（`subject_id` + 跳转基因检索） | `blast.hitGeneId` | **无 → 新增第 6 列** ✅ |
| gbrowse（`subject_id:start-end` → JBrowse） | `t("blast.actions.gbrowse")` | **无 → 新增第 7 列** ✅ |

**本轮（round 4）的加法式修复**（不删除 Vue 既有的 score / alignment 列）：

- 新增「基因ID」列：`get("blast.hitGeneId", t("blast.hitGeneId"))`，单元格用 `compactGeneId(hit.subject_id, 18)` 链到 `/search/genes?q=<subject_id>&run=true`（`run` 由 `SearchGenesView` 支持，与 React 的 `search:{q,run:true}` 一致）。
- 新增「JBrowse 2」列：`t("blast.actions.gbrowse")`，用 `subject_id:subject_start..subject_end` 拼 `loc`，并按 React 的 `assemblyForJob` 逻辑（job.database → 数据库表 → `assembly_name`）带上 `assembly`；`isJbrowseEnabled()` 为假时不渲染链接。
- **浏览器实测**（桩 `/api/v1/blast/**` + `site/content` 覆盖）：表头 `输入序列ID 覆盖率 比对长度 E值 得分 运营基因ID JBrowse 2`；基因单元格 `Glyma.01G000100` → `/search/genes?q=Glyma.01G000100&run=true`；JBrowse 单元格 → `http://127.0.0.1:5175?loc=Glyma.01G000100%3A5..125&assembly=Glyma_max_v4` 且 `rel="noopener noreferrer"`。
- 覆盖率脚本随之 **ACTION=0**：React 消费过的注册 content 键 **100% 已接线**。

**仍缺的两列**（不涉及 content 键，属可选增强，已记录）：React 还显示「assembly」列与「输入序列 ID（query FASTA header）」列；Vue 命中表未展示这两项。补齐需要解析 `job.query_sequence` 的 FASTA header 并决定列顺序，属功能设计选择，未擅自改。

## 5. 复跑验收矩阵（全部 exit 0）

| 门禁 | 结果 |
| --- | --- |
| web：`test`（round 4 复跑） | **55 files / 304 tests passed** |
| web：`typecheck` / `lint` | **0 / 0**（lint 退出码 0） |
| web：`check_visible_i18n.py` | **OK** |
| web：`build`（含 SSG） | **exit 0** |
| api-client：`test` | **149 passed** |
| admin：`test` | **98 passed** |
| i18n 字典 | zh/en 各 **1660** key、完全对等、0 引用缺失 |
| 浏览器（zh-CN + 桩 `only_overrides`） | `genes.title`→眉题、`genes.subtitle`→h1、`downloads.title`→h1、`help.faq1.q`→FAQ 第 1 条，全部显示运营覆盖值；无覆盖时中文保持中文 |
| 双站 verifier（无 PREBUILT） | **EXIT=0** |
| internal E2E | **3 passed** |
| 内容覆盖率脚本 | 131 注册 / 105 已接 / ACTION=1（已解释） |

## 6. 未完成 / 未验证

1. ~~§4 的 Blast 命中表列集差异~~ —— **已于 round 4 闭合**（新增基因跳转列 + JBrowse 列，浏览器实测通过，覆盖率 ACTION=0）。仍缺 React 的 assembly 列与输入序列 ID 列（不涉及 content 键，属可选增强）。
2. 25 个"React 未消费但已注册"的 content 键未接线（非缺口，属可选新增面）。
3. 管理端后端聚合端点（`/releases/current`、dashboard storage_growth、审计聚合/导出、导入上传/校验、媒体上传、插件运行时）——前端无法闭合。
4. 真 Redis / 真外网 provider（本机无 `redis-server`）；SW 子路径 scope 与跨浏览器；live 部署态；详情页成功态真机渲染；匿名深链 `/analyses` 落 `/login`（与 React 一致）。
5. repo-wide ruff 404 条（不在任何 CI 门禁内）。
6. **五轮改动仍全部未提交**（`git status` 180+ 项）。

## 7. 回滚点

| 范围 | 回滚 |
| --- | --- |
| 本轮全部 | `git checkout -- <file>` / 删除新增文件（未提交） |
| i18n 新增 4 键 | `git checkout -- packages/i18n-core` |
| Blast col5 / GuideView h1 的协调者修正 | 见本节 diff（本轮工作树） |


## 8. goal round 4：最后一条差异闭合 + 全量复跑

| 门禁 | 结果 |
| --- | --- |
| web：`test` | **55 files / 304 tests passed** |
| web：`typecheck` / `lint` | **0 / 0** |
| web：`check_visible_i18n.py` | **OK** |
| web：`build` | **exit 0** |
| api-client / admin / charts / ui-vue / i18n-core | **149 / 98 / 4 / 5 / 7 passed**（各自 exit 0） |
| 双站 verifier（无 PREBUILT） | **EXIT=0** |
| internal E2E | **3 passed** |
| 内容覆盖率 | **131 注册 / 106 已接 / ACTION=0**；25 个未接全部是 React 从未引用的键 |
| 浏览器：Blast 新列 | 基因跳转 `/search/genes?q=Glyma.01G000100&run=true`；JBrowse `?loc=Glyma.01G000100%3A5..125&assembly=Glyma_max_v4`（`rel=noopener noreferrer`） |

**说明**：`blast.hitGeneId` 现已接到新增的「基因ID」列；Vue 原有的 `bit_score` 列保留并正确标注为「得分」，不再出现"把分数标成基因ID"的错误。
