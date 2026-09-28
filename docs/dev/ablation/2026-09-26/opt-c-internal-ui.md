# OPT-05 / OPT-06 执行小结（agent C · internal 搜索 client 与双 id UI）

- 日期：2026-09-26
- 范围：`packages/api-client/src/search.ts`、`packages/api-client/src/search.test.ts`、
  `apps/web/src/views/SearchView.vue`、`apps/web/src/ablation/ui02-internal-ids.test.ts`、
  新增 `apps/web/src/ablation/opt06-search-result-fields.test.ts`
- 来源：`docs/dev/ablation/2026-09-26/OPTIMIZATION-CHECKLIST.md` OPT-05（P1）/ OPT-06（P2），
  冻结契约见其 §2 OPT-05 与被消融报告 `frontend.md` 的 W4 弱断言发现。
- **未提交**；未 `checkout/reset/stash` 任何他人文件。

## 1. 目标

1. OPT-05：让 `SearchView` 在内站变体真正消费已存在的后端契约
   `GET /api/v1/search/internal` 与生成类型 `InternalMutantSearchItem{public_id,internal_id,...}` /
   `InternalSearchResponse`：新增手写 `internalSearch()`，内站渲染 internal 结果集、同时可见
   `public_id` 与 `internal_id`，并各有一个复制控件（`data-testid="copy-public-id"` /
   `data-testid="copy-internal-id"`）；外站路径行为零变化。
2. OPT-06：给 `SearchResult` 增加可选 `match_type?` / `cross_version?`（消费 agent A 的后端字段，
   缺失时也要通过），并把 W4 指出的值不敏感弱断言 `not.toContain("internal_id")` 收紧为双向值敏感断言，
   使「把绑定换成 internal_id」时新测试必红。

## 2. 改动（file:line）

### packages/api-client/src/search.ts

- `:1` 引入 `components` 生成类型。
- `:9-30` 新增 `MatchType`（取自生成契约 `components["schemas"]["MatchType"]`）与
  `CrossVersionLink`（字段对齐冻结契约：`gene_accession`、`assembly_*?`、`relation_type`、
  `provenance_source`、`match_type?`）。
- `:56-58` `SearchResult` 增加可选 `match_type?`、`cross_version?`（可选 → 后端未落地也通过）。
- `:144-163` 导出 `InternalMutantSearchItem` / `InternalGeneSearchItem` / `InternalSearchResponse` 生成类型别名、
  `InternalSearchParams`、`internalSearch(query, opts?)`，打 `/search/internal`，
  params 使用后端别名 `query`（非 `q`）+ `limit`，走协调层 `http.get` 以携带 Authorization 与 release pin。
- `packages/api-client/src/index.ts` 未改：已有 `export * from "./search"`，`internalSearch` 随之导出。

### apps/web/src/views/SearchView.vue

- `:76-103` 内站专用的 `internalQuery`（key 含 query/limit/release/site，`enabled = site.isInternal && q`，
  独立于公共 `globalSearch` 链），并把 mutants/genes 两种实体归一为带 `publicId`/`internalId` 的 `InternalRow`。
- `:137-169` `copyId()`：优先 `navigator.clipboard.writeText`，缺失或抛错时回退到隐藏 textarea +
  `document.execCommand("copy")`，全程不向渲染路径抛错。
- `:308-368` 内站专属 `<section data-testid="search-internal-results">`，每行
  `search-internal-row` 同时渲染 `internal-public-id` / `internal-internal-id` 与两个复制按钮
  （`:data-copy-value` 绑定各自的值）。该 section 独立于下方公共 `v-if/v-else-if` 链，外站不渲染。
- `:456-464` / `:496-504` 公共行（含 disabled 分支）条件渲染 `search-result-match-type` 与
  `search-cross-version`（OPT-06，字段缺失即不渲染）；行主标签回退链改为
  `result.name ?? result.public_id ?? result.id`（保留并发会话新增的 `public_id`/`internal_id` 渲染）。

### 测试

- `apps/web/src/ablation/ui02-internal-ids.test.ts`：重写为 4 个用例 —— (a) 真实模块面导出 `internalSearch`；
  (b) 内站渲染双 id 且**双向值敏感**（正断言各自 token，负断言另一个 token），两个复制控件
  `data-copy-value` 各自正确，点击分别复制对应值；(c) 无 `navigator.clipboard` 时不抛错（回退路径）；
  (d) 外站：global 路径调用一次、不调用 internal、行内无 internal token、无任何 internal 控件。
- `apps/web/src/ablation/opt06-search-result-fields.test.ts`（新增）：带 `match_type`/`cross_version` 时渲染，
  且 cross-version accession 正断言、源行 id 负断言（换绑必红）；旧载荷缺两字段时两者都不渲染（防御性）。
- `packages/api-client/src/search.test.ts`：`internalSearch` 打 `/search/internal` 且用 `query` 别名 + `limit`；
  无 opts 时 limit 为 undefined；`SearchResult` 裸形状与带新字段形状均可编译（可选性回归）。

## 3. 红绿证据（命令 + 退出码 + 输出）

均在 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`、`--pool=threads --poolOptions.threads.maxThreads=2` 下运行。

### RED（改源码前）

```
cd apps/web && ./node_modules/.bin/vitest run src/ablation/ui02-internal-ids.test.ts
EXIT:1
 Test Files  1 failed (1)
      Tests  4 failed (4)
```
（原弱断言仅证明「无 internal 客户端 / 不渲染 node-42」；新用例在旧源码下 4 条全红。）

```
cd packages/api-client && ./node_modules/.bin/vitest run src/search.test.ts
EXIT:1
 Test Files  1 failed (1)
      Tests  2 failed | 2 passed (4)
```
（`internalSearch is not a function` ×2。）

```
cd apps/web && ./node_modules/.bin/vitest run src/ablation/opt06-search-result-fields.test.ts
EXIT:1
 Test Files  1 failed (1)
      Tests  1 failed | 1 passed (2)
```
（`search-result-match-type` 不存在。）

### GREEN（改源码后）

```
cd apps/web && ./node_modules/.bin/vitest run src/ablation/ui02-internal-ids.test.ts src/ablation/opt06-search-result-fields.test.ts
EXIT:0
 Test Files  2 passed (2)
      Tests  6 passed (6)
```

```
cd packages/api-client && ./node_modules/.bin/vitest run src/search.test.ts
EXIT:0
 Test Files  1 passed (1)
      Tests  4 passed (4)
```

DoD #2 既有窄门禁：

```
cd apps/web && ./node_modules/.bin/vitest run src/views/SearchView.test.ts src/views/Mutants.test.ts src/ablation
EXIT:0
 Test Files  7 passed (7)
      Tests  29 passed (29)
```

DoD #4：

```
cd packages/api-client && ./node_modules/.bin/vitest run
EXIT:0
 Test Files  26 passed (26)
      Tests  137 passed (137)
```

补充：

- `cd packages/api-client && ./node_modules/.bin/tsc --noEmit` → `EXIT:0`。
- `cd apps/web && ./node_modules/.bin/vue-tsc --noEmit` → `EXIT:2`，但**仅** `src/ablation/p1-04-variants-cursor-key.test.ts`
  的只读元组转型报错（与本次改动无关，属他人 ablation harness 既有问题）；`SearchView.vue`、ui02、opt06 无类型错误。
- 根 `eslint` 对改动文件 `EXIT:0`（`SearchView.vue` 因根配置未覆盖而被 ignore，非错误）。

## 4. 未验证

1. **真实剪贴板**：jsdom 中以 spy 注入 `navigator.clipboard` 断言调用参数；真实浏览器/非安全上下文下
   的权限弹窗、`execCommand` 回退是否真正写入系统剪贴板未在浏览器验证。
2. **真实后端**：未对活的 `/api/v1/search/internal` 发请求；授权失败/未登录（401 → refresh → logout）分支
   只依赖现有 `http`/`authRequest` 语义，未见实网。
3. **内站构建产物**：只跑单测，未构建 `dist/internal` 验证产物与缓存策略（属 W6/OPT-07/08 范围）。
4. **并发写入**：编辑期间检测到另一会话已同时改动 `SearchView.vue` / `search.ts`（新增
   `SearchResult.public_id?/internal_id?` 与内站行内 internal 渲染、`nav.internalBadge` i18n key）。
   已在其基础上**追加**而非覆盖；若该会话后续再写同名文件，需以最终内容为准复跑上面的 GREEN 命令。
5. `internalSearch` 目前只支持 `limit`；后端契约仅有 `query`/`limit`，cursor 分页未做（内站 section 暂不分页）。

## 5. 回滚点

- `git diff -- packages/api-client/src/search.ts packages/api-client/src/search.test.ts apps/web/src/views/SearchView.vue apps/web/src/ablation/ui02-internal-ids.test.ts`
- 新增文件：`apps/web/src/ablation/opt06-search-result-fields.test.ts`（未跟踪，删除即回滚）。
- 单文件回滚即可；无迁移、无生成文件改动（`generated/openapi.d.ts` 未手改）。
- **提交状态（编辑期间并发会话 `caoronglin` 提交了 HEAD）**：`362e7a30b` 已把 `packages/api-client/src/search.ts`
  与 `search.test.ts`（含本次 OPT-05 client / OPT-06 类型）连同其自身的 SearchView 双 id 渲染一起提交；
  因此这两文件相对 HEAD 已 clean。`apps/web/src/views/SearchView.vue` 中本工作流的 internal 结果集
  + 复制控件 + match_type/cross-version 渲染仍是**未提交**工作树改动（相对 HEAD +188/-2）。
  ablation 测试仍在未跟踪的 `apps/web/src/ablation/` 下。
- 回滚本工作流只影响上述三处；不会碰到他人已提交内容。
