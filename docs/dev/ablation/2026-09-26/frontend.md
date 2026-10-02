# W4 前端与查询键 · 消融实验报告（2026-09-26 / HEAD `8e78116fd`）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

执行者：子代理 D（W4）。审计与执行分离；本文件只记录**实测**结果，不修改生产源码、不提交。

## 1. 目标与范围

对 W4 工作流的保护性不变量逐条做「对照 → 单因素消融 → 翻转判定」：

| 场景 | 不变量 | 判定口径 |
| --- | --- | --- |
| UI-01 | 外部突变体列表/详情只渲染 `public_id`，绝不渲染数值内部键（DB-CORE-2） | 消融字段绑定后断言翻转 = GUARD-ACTIVE |
| UI-02 | internal 授权结果/详情应能区分并复制**两种** id（`public_id` + `internal_id`） | HEAD 是否已有 internal 搜索 UI/客户端 |
| P1-04 | variants 列表查询键必须包含 cursor/分页位置；游标页不得与首页共用缓存条目 | 消融键中的 cursor 后缓存条目塌缩 = GUARD-ACTIVE |
| SRCH-CTX | 若契约要求，搜索结果项必须携带 assembly/release/source 上下文；响应字段不得被前端丢弃 | 消融渲染块后断言翻转 = GUARD-ACTIVE；字段被丢 = GAP |

锚点：`apps/web/src/views/Mutants.test.ts`、`apps/web/src/views/MutantDetailView.vue`、`apps/web/src/views/MutantsListView.vue`、`apps/web/src/lib/query-options.ts`、`packages/query-keys/src/index.ts`、`apps/web/src/views/VariantsView.vue`、`packages/api-client/src/search.ts`、`apps/web/src/views/SearchView.vue`。

## 2. 环境与命令

- Node `v24.19.0`（PATH 已就绪）；Vitest `v3.2.7`。
- 机器受限时前缀 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`，并加 `--pool=threads --poolOptions.threads.maxThreads=2`（已统一使用）。
- 工作目录：`/mnt/data02/T25ronglin/code/web`。
- 对照命令（全部在包目录内执行，使用包内 `./node_modules/.bin/vitest`）：

```bash
# C1
cd apps/web && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run src/views/Mutants.test.ts --pool=threads --poolOptions.threads.maxThreads=2
# C2
cd apps/web && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run src/views/SearchView.test.ts src/views/VariantsView.test.ts --pool=threads --poolOptions.threads.maxThreads=2
# C3
cd packages/query-keys && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run --pool=threads --poolOptions.threads.maxThreads=2
# C4 新增消融 harness（对照）
cd apps/web && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run src/ablation --pool=threads --poolOptions.threads.maxThreads=2
```

- 新增 harness（agent 所有，位于 `apps/web/src/ablation/`，不改生产源码）：
  - `ui01-public-id.test.ts`（3 tests）
  - `p1-04-variants-cursor-key.test.ts`（3 tests，真实 `queryKeys` + 真实 `QueryClient` 内存缓存）
  - `search-context.test.ts`（3 tests）
  - `ui02-internal-ids.test.ts`（2 tests）

## 3. 逐场景结果表

| 场景 | 对照 | 消融 | 判定 | 证据 |
| --- | --- | --- | --- | --- |
| UI-01 列表 | C1 → `exit 0`，`Test Files 1 passed (1)` / `Tests 7 passed (7)`；C4 → `exit 0`，`Tests 11 passed (11)`；harness 以同时含 `public_id:"SM7QF3Z"` 与 `internal_id:"42"` 的载荷断言 `data-public-id==="SM7QF3Z"` 且行内 html 不含 `42` | 临时把 `MutantsListView.vue` 中全部 `line.public_id` 换成 `line.internal_id`（`git diff` 证实 4 处），复跑 C1+harness | **GUARD-ACTIVE** | 消融后 `exit 1`，`Tests 4 failed \| 6 passed (10)`；失败行：`Mutants.test.ts:84 expected undefined to be 'SM7QF3Z'`、`ui01-public-id.test.ts:122 expected "42" to be "SM7QF3Z"`。还原后 `git diff apps/web/src/views/*.vue` 为空 |
| UI-01 详情 | 同上。真实 `MutantDetailView` 的 `[data-testid=mutant-public-id]` 渲染 `SM7QF3Z` | 临时把 `MutantDetailView.vue` 的 `line.public_id` 换成 `line.internal_id` | **GUARD-ACTIVE** | 消融后 `exit 1`；`Mutants.test.ts:137 expected '' to be 'SM7QF3Z'`（原载荷无 internal_id）；harness 中载荷有 `internal_id:"42"`，绑定被换后该 testid 文本变为 `"42"` |
| UI-02 internal 双 id | `ui02-internal-ids.test.ts` → `exit 0`；载荷按 `InternalMutantSearchItem` 形状带 `public_id`+`internal_id` 时，DOM 含 public，**不含** `node-42`，且无复制 affordance | 无源码可消融：HEAD 根本没有 internal 搜索调用/组件 | **GAP** | `api-client exposes NO handwritten internal-search call` 通过（见 §4 定位与 §6 原始输出） |
| P1-04 variants 游标键 | C3 → `exit 0`，`Test Files 1 passed (1)` / `Tests 10 passed (10)`；harness CONTROL 断言首页键 ≠ 游标页键、缓存 2 条、游标页读到 `cursor-page` | 临时删除 `packages/query-keys/src/index.ts` 的 `context.cursor ?? null,` 一行；复跑 C3 与 harness | **GUARD-ACTIVE** | 消融后 C3 `exit 1`，`Tests 1 failed \| 9 passed (10)`，`query-keys.test.ts:156 expected [...11] to not deeply equal [...11]`；harness 消融侧 `exit 1`，`Tests 2 failed \| 1 passed (3)`（CONTROL 与 real-vs-nocursor 两测翻红，ABLATION 自证测通过）。还原后 C3 回到 `Tests 10 passed (10)`，`git diff` 为空 |
| SRCH-CTX 结果上下文 | C2 → `exit 0`，`Test Files 2 passed (2)` / `Tests 16 passed (16)`；harness 断言 actioned 与 disabled 两类行的 `[data-testid=search-result-meta]` 均含 assembly `Wm82 v4/v5`、release `7/8`、source `internal`，无 label 时回退显示 `assembly_id` | 临时删除 `SearchView.vue` 中两个 `data-testid="search-result-meta"` span（正则消融，`git diff` 证实 `2 insertions(+), 24 deletions(-)`） | **GUARD-ACTIVE** | 消融后 `exit 1`，`Tests 3 failed \| 6 passed (9)`（失败全在 harness，`meta.exists()` 为 false / "Cannot call text on an empty DOMWrapper"）。**注意：`SearchView.test.ts` 6 tests 在消融下仍全绿**（见 §4 INERT/覆盖）。还原后 C2+harness 全绿 |

对照全量：`cd apps/web && vitest run src/views/Mutants.test.ts src/views/SearchView.test.ts src/views/VariantsView.test.ts src/ablation` → `exit 0`，`Test Files 7 passed (7)` / `Tests 34 passed (34)`。

## 4. GAP 与 INERT 发现

### GAP-UI02（P0/P1）：internal 授权搜索在前端完全缺失，双 id 无法区分/复制

判定依据（决定性位置）：

- `packages/api-client/src/search.ts:5-17`：手写 `SearchResult` 只有 `type/id/name/description/url/source/score/release_id/assembly_id/assembly`，**没有 `internal_id`，因此无 `public_id` 字段**；`globalSearch()`（同文件 `:81-88`）固定打 `/search`。
- `packages/api-client/src/index.ts`：`grep -n internal` 无任何命中 → 没有导出任何 internal 搜索函数。
- `packages/api-client/src/generated/openapi.d.ts:708-724` 定义了 `GET /api/v1/search/internal`；`:6296-6323` 定义 `InternalMutantSearchItem{public_id, internal_id, matched_field, ...}` 与 `InternalSearchResponse{mutants?, genes?, total_count}`。契约在后端/生成类型里已存在，但**没有手写 typed client，也没有任何 Vue 组件消费它**。
- `apps/web/src/views/SearchView.vue:290-302`（及 disabled 分支 `:311-322`）：行内容只有 `result.name ?? result.id`、`assembly/assembly_id`、`release_id`、`source`，**不渲染 `internal_id`**；全组件无 clipboard/copy 调用。
- 路由 `apps/web/src/router/routes.ts:81-83` 只注册了一个 `/search`，external 与 internal 站点变体共用同一 `SearchView`，没有 internal 专页。

实测：`ui02-internal-ids.test.ts` `exit 0`，其中 `expect("internalSearch" in apiClient).toBe(false)` 通过；载荷带 `internal_id:"node-42"` 时 `wrapper.html()).not.toContain("node-42")` 通过。

**结论：UI-02 在 HEAD 为 GAP。** 缺的是「客户端函数 + internal 结果 UI（双 id 展示/复制）」，不是后端端点。

### INERT / 弱断言发现

1. **`not.toContain("internal_id")` 是值不敏感的弱断言。** `Mutants.test.ts:86/139/194`、`SearchView.test.ts:81`、`VariantsView.test.ts:106` 都断言 HTML 不包含字符串 `internal_id`——那只是字段名，`{:key}` 等不会渲染字段名。把绑定换成 `line.internal_id` 后这些负断言**仍然通过**；真正翻转的是正向断言（`data-public-id` / 文本/`mockedDetail` 调用参数）。属于「断言在场但对该消融不敏感」。
2. **`SearchView.test.ts` 完全不覆盖结果上下文。** 删除 assembly/release/source 渲染块后，`SearchView.test.ts` 6 tests 仍全部通过，只有新增 `search-context.test.ts` 翻红。即 SRCH-CTX 守卫在 HEAD 的既有测试里是**未被守护**的（新增 harness 才使其可被消融检出）。
3. **无死代码**：三处消融均产生行为翻转，未发现「消融后完全不变」的生产守卫。

## 5. 未验证项

- 仅 jsdom 组件级运行，**未跑真实浏览器/Playwright**；未跑 `pnpm typecheck`，新增 harness 的类型正确性未由编译器复核。
- 未连真实 API：`internal_id` 的实际 JSON 形状以 `generated/openapi.d.ts` 类型 + grep 推断，未对活体 `/api/v1/search/internal` 发请求；也未验证授权失败/未登录分支。
- 「复制两种 id」的剪贴板行为未实测（无复制控件 → 以 `data-testid="search-result-copy"` 不存在判定），未验证 `navigator.clipboard` 路径。
- 未跑全 workspace 测试；`apps/admin` 经 grep 也无 `search/internal`，但其搜索页未逐文件审计。
- UI-01 的数值 `id`/`internal_id` 泄露只在 `apps/web` 站点变体下验证；未验证 internal 站点构建产物（属 W6）。
- variants 「cursor 页与首页 page 索引相同」的真实 URL 场景未走 `VariantsView` 端到端（用真实 key builder + 真实 QueryClient 验证，非组件挂载）。

## 6. 原始证据附录

### A. 对照（baseline）

```
$ cd apps/web && GOMAXPROCS=2 RAYON_NUM_THREADS=1 ./node_modules/.bin/vitest run src/views/Mutants.test.ts --pool=threads --poolOptions.threads.maxThreads=2
 ✓ src/views/Mutants.test.ts (7 tests) 125ms
 Test Files  1 passed (1)
      Tests  7 passed (7)
EXIT=0

$ cd apps/web && ... vitest run src/views/SearchView.test.ts src/views/VariantsView.test.ts ...
 ✓ src/views/SearchView.test.ts (6 tests) 118ms
 ✓ src/views/VariantsView.test.ts (10 tests) 275ms
 Test Files  2 passed (2)
      Tests  16 passed (16)
EXIT=0

$ cd packages/query-keys && ... vitest run ...
 ✓ src/query-keys.test.ts (10 tests) 7ms
 Test Files  1 passed (1)
      Tests  10 passed (10)
EXIT=0

$ cd apps/web && ... vitest run src/ablation ...
 ✓ src/ablation/search-context.test.ts (3 tests)
 ✓ src/ablation/ui01-public-id.test.ts (3 tests)
 ✓ src/ablation/p1-04-variants-cursor-key.test.ts (3 tests)
 ✓ src/ablation/ui02-internal-ids.test.ts (2 tests)
 Test Files  4 passed (4)
      Tests  11 passed (11)
EXIT=0

$ cd apps/web && ... vitest run src/views/Mutants.test.ts src/views/SearchView.test.ts src/views/VariantsView.test.ts src/ablation ...
 Test Files  7 passed (7)
      Tests  34 passed (34)
EXIT=0
```

### B. UI-01 消融 diff 与翻转

```diff
--- a/apps/web/src/views/MutantsListView.vue
+++ b/apps/web/src/views/MutantsListView.vue
@@ -80,16 +80,16 @@
-          <li v-for="line in lines" :key="line.public_id">
-              :to="{ path: `/mutants/${line.public_id}` }"
-              :data-public-id="line.public_id"
-              <span ...>{{ line.public_id }}</span>
+          <li v-for="line in lines" :key="line.internal_id">
+              :to="{ path: `/mutants/${line.internal_id}` }"
+              :data-public-id="line.internal_id"
+              <span ...>{{ line.internal_id }}</span>
--- a/apps/web/src/views/MutantDetailView.vue
+++ b/apps/web/src/views/MutantDetailView.vue
-            {{ line.public_id }}
+            {{ line.internal_id }}
```

```
$ ... vitest run src/views/Mutants.test.ts src/ablation/ui01-public-id.test.ts ...
 FAIL src/ablation/ui01-public-id.test.ts:122 → expected "42" to be "SM7QF3Z"
 FAIL src/views/Mutants.test.ts:84 → expected undefined to be 'SM7QF3Z'
 FAIL src/views/Mutants.test.ts:137 → expected '' to be 'SM7QF3Z'
 Test Files  2 failed (2)
      Tests  4 failed | 6 passed (10)
EXIT=1
# 还原：git checkout -- apps/web/src/views/MutantsListView.vue apps/web/src/views/MutantDetailView.vue
# git diff --stat 上述两文件 → 空
```

### C. P1-04 消融 diff 与翻转

```diff
--- a/packages/query-keys/src/index.ts
+++ b/packages/query-keys/src/index.ts
@@ -179,7 +179,6 @@
         context.releaseId,
         context.siteVariant,
         context.page,
-        context.cursor ?? null,
         context.chromosome ?? null,
```

```
$ cd packages/query-keys && ... vitest run ...
 × queryKeys > scopes variant caches ... → expected ['soymutdb','variants',…(11)] to not deeply equal [...(11)]
 FAIL src/query-keys.test.ts:156
 Test Files  1 failed (1)
      Tests  1 failed | 9 passed (10)
EXIT=1

$ cd apps/web && ... vitest run src/ablation/p1-04-variants-cursor-key.test.ts ...
 FAIL ... > CONTROL: a cursor page gets its own key and its own cache entry (line 55)
 FAIL ... > the real key differs from the cursor-less key (the fix is load-bearing) (line 75)
 Test Files  1 failed (1)
      Tests  2 failed | 1 passed (3)
EXIT=1
# 还原：git checkout -- packages/query-keys/src/index.ts
# 复跑 → Test Files 1 passed (1) / Tests 10 passed (10) EXIT=0；git diff → 空
```

harness 对照侧（源还原后）关键断言输出：

```
✓ CONTROL: a cursor page gets its own key and its own cache entry
   getQueryCache().getAll() → length 2；getQueryData(首页键)==="first-page"；getQueryData(游标键)==="cursor-page"
✓ ABLATION: dropping the cursor collapses both pages onto one entry
   noCursorKey(null) deep-equals noCursorKey("c2")；getAll() length 1；游标键读到 "first-page"
```

### D. SRCH-CTX 消融与翻转

```
$ python3: 正则删除 SearchView.vue 中两个 '<span ... data-testid="search-result-meta">…</span>'（共 2 处）
$ git diff --stat apps/web/src/views/SearchView.vue
 1 file changed, 2 insertions(+), 24 deletions(-)

$ ... vitest run src/views/SearchView.test.ts src/ablation/search-context.test.ts ...
 ✓ src/views/SearchView.test.ts (6 tests)          <-- 消融下仍全绿
 FAIL src/ablation/search-context.test.ts (3 tests) → meta.exists() false / Cannot call text on an empty DOMWrapper
 Test Files  1 failed | 1 passed (2)
      Tests  3 failed | 6 passed (9)
EXIT=1
# 还原：git checkout -- apps/web/src/views/SearchView.vue → git diff 为空，复跑全绿
```

### E. UI-02 GAP 取证命令

```
$ grep -rn "search/internal|internalSearch" packages/api-client/src --include=*.ts | grep -v generated
（无输出，rc=1）
$ grep -n "internal" packages/api-client/src/index.ts
（无输出）
$ grep -n "InternalSearchResponse|InternalMutantSearchItem" packages/api-client/src/generated/openapi.d.ts
6296: InternalMutantSearchItem: { public_id; internal_id; matched_field; ... }
6317: InternalSearchResponse: { query; mutants?; genes?; total_count }
11032: internal_search_api_v1_search_internal_get   # GET /api/v1/search/internal
$ sed -n '290,302p' apps/web/src/views/SearchView.vue
  <span data-testid="search-result-meta"> name ?? id / assembly / release_id / source </span>
$ grep -rn "internal" apps/admin/src --include=*.vue --include=*.ts
（无输出）
```

### F. 工作树状态（未永久改动生产源码）

```
$ git status --porcelain
 M apps/jbrowse/package.json                  # 预先存在
 M packages/genome-data/package.json          # 预先存在
 M packages/genome-view-model/src/index.ts    # 预先存在
 M packages/genome-view-model/src/viewport.ts # 预先存在
 M packages/genome-view/package.json          # 预先存在
 M pnpm-lock.yaml                             # 预先存在
?? apps/web/src/ablation/                     # 本报告新增 harness
?? docs/dev/ablation/                         # 报告目录
$ git diff --stat -- apps/web/src packages/query-keys/src
（空）
```
