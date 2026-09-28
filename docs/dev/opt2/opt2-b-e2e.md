# OPT2-B 小结：internal E2E 真实输入（OPT2-04） + verifier 单条命令（OPT2-05）

- 负责人：B
- 仓库：`/mnt/data02/T25ronglin/code/web`
- 日期：2026-09-26
- 改动文件（仅本人所有权内）：
  - `e2e/tests/internal-site.spec.ts`
  - `e2e/probe-search-input.mjs`（新增，可选证据脚本）
  - `scripts/verify-site-variant-artifacts.sh`
  - `docs/dev/opt2/opt2-b-e2e.md`（本文件）
- 未改动：`apps/**`、`packages/**`、其它 `docs/**`。
- 未执行 `git commit/push/checkout/stash/reset`。

---

## 0. 环境与资源

```bash
export PNPM_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/home
export XDG_STATE_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/state
export XDG_CACHE_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/cache
export XDG_CONFIG_HOME=/mnt/data02/T25ronglin/code/web/.validation/pnpm/config
```

- Playwright 始终 `--workers=1`（资源紧张；`playwright-internal.config.ts` 本身也 `workers: 1`）。
- 本机 `nproc=96`，`vite build` 的 Rust 变换（oxc/lightningcss/tailwind oxide）会让
  rayon 按可见核数建全局线程池，在本机线程预算下报
  `ThreadPoolBuildError { ... Resource temporarily unavailable }` → `exit 134`。
  实测：`RAYON_NUM_THREADS=8` / `=4` 均可正常构建。OPT2-05 里把它固化为脚本默认。
- 证据日志目录：`.validation/opt2b/`。

---

## 1. OPT2-04 — internal 站改走真实 UI 输入

### 1.1 改前：`?q=` 深链绕行原文

`e2e/tests/internal-site.spec.ts`（改前）**第 202–209 行**：

```
202    // Search by the PRIVATE internal identifier (URL-backed search state, the
203    // contract the omnibox restores from). NOTE: the omnibox's antdv `Input` is
204    // `v-model`-bound (not `v-model:value`), so a form fill does not reach the
205    // component state on the built artifact; the deep link is the reliable path.
206    await gotoReady(
207      page,
208      underBase(INTERNAL_BASE_URL, `search?q=${encodeURIComponent(MOCK_MUTANT_INTERNAL_ID)}`),
209    );
```

改后：文件中已无 `search?q=`（`grep -n "search?q=" e2e/tests/internal-site.spec.ts` → 空）。

### 1.2 采用的真实输入方式

页面 `/search` 上有两个检索输入，规格里**两者都真实打字**（`pressSequentially`，逐字符触发真实 `input` 事件）：

| 元素 | 组件 | 归属 | 真实打字后的行为 |
| --- | --- | --- | --- |
| `search-input` | antdv `Input`，`v-model="input"` | `SearchView.vue:311-319` | DOM `value` 正确，但组件 `input` ref 不同步 → 该表单 submit 不产生 `q` |
| `portal-search-input` | 原生 `<input v-model="query">` | `PortalHeader.vue:334-342` | 逐字符同步，`submitSearch()` 自行 `router.push({path:"/search",query:{q}})` → **由组件自己导航** |

因此：真实打字发生在两个输入框上，真正完成导航的是头部 omnibox；**没有使用 `?q=` 深链，也没有退回 `fill`**。

新增/加强的断言（全部保留、无删减、无新增 `test.skip`）：

- `await expect(formInput).toHaveValue(MOCK_MUTANT_INTERNAL_ID)`（antdv 表单字段的 DOM 读回）；
- `await expect(omnibox).toHaveValue(MOCK_MUTANT_INTERNAL_ID)`；
- `expect.poll(() => new URL(page.url()).searchParams.get("q")).toBe(MOCK_MUTANT_INTERNAL_ID)` +
  `expect(pathname).toBe("/search")`（URL 变为携带 `q=` 的搜索结果页，由组件导航）；
- 既有：`captured` 里存在 `query=INT-MUT-000001` 的检索请求；`search-result-row` 可见、
  `data-url="/mutants/SMDB-00001"`、含 `INT-MUT-000001`；
- 加强（internal 双 id + 复制控件）：`search-internal-row` 可见；
  `internal-public-id` 文本与 `data-id-value` = `SMDB-00001`；
  `internal-internal-id` 文本与 `data-id-value` = `INT-MUT-000001`；
  `copy-public-id` / `copy-internal-id` 的 `data-copy-value` 正确，点击 `copy-internal-id` 后按钮变 `copied`；
- 既有：点击结果行 → `/mutants/SMDB-00001` 详情、`mutant-detail` 可见、`mutant-public-id` 正确；
- 既有：`errors`（console/pageerror）为空。

### 1.3 实测证据

证据脚本：`e2e/probe-search-input.mjs`（离线 internal 制品 `http://localhost:4175/`，mock API）。
完整输出：`.validation/opt2b/probe-evidence.log`。关键行：

```
== SearchView form field: INPUT.ant-input.ant-input-outlined
[fill]                    inputValue="INT-MUT-000001" domValue="INT-MUT-000001"
[fill]                    URL=http://localhost:4175/search rows=0 searchApiCalls=0
[pressSequentially]       inputValue="INT-MUT-000001" domValue="INT-MUT-000001"
[pressSequentially]       URL=http://localhost:4175/search rows=0 searchApiCalls=0
[pressSequentially+Enter] inputValue="INT-MUT-000001" domValue="INT-MUT-000001"
[pressSequentially+Enter] URL=http://localhost:4175/search rows=0 searchApiCalls=0
[fill+input-event]        inputValue="INT-MUT-000001" domValue="INT-MUT-000001"
[fill+input-event]        URL=http://localhost:4175/search rows=0 searchApiCalls=0
[fill+input+change]       inputValue="INT-MUT-000001" domValue="INT-MUT-000001"
[fill+input+change]       URL=http://localhost:4175/search rows=0 searchApiCalls=0

== Header omnibox (native <input v-model>)
[omnibox] inputValue= "INT-MUT-000001"
[omnibox] URL=http://localhost:4175/search?q=INT-MUT-000001 resultRows=1 internalRows=1 searchApiCalls=2
[omnibox] search-input value after navigation: ""
[omnibox] search requests: GET /search/internal?query=INT-MUT-000001&limit=20 | GET /search?limit=20&query=INT-MUT-000001
```

**结论：antdv `Input` 用 `pressSequentially` 也“驱动不了组件状态”是实测事实**——
DOM 里 `inputValue()`/`value` 都对，但 5 种真实输入/派发姿势（含补派 `change`、回车提交）
都得到 `URL=/search`、`rows=0`、`searchApiCalls=0`。

### 1.4 “真实输入不可行”的根因（不改应用源码）

- `SearchView.vue:312` 写的是 `v-model="input"`（编译为 `modelValue` + `onUpdate:modelValue`），
  而 `antdv-next@1.5.4` 的 `Input` **只声明 `value` / `update:value`**：

```
$ node_modules/.pnpm/antdv-next@1.5.4_.../node_modules/antdv-next/dist/input/Input.d.ts
31:  value?: any;
77:  'update:value': (value: InputProps$1['value']) => void;
89:  'onUpdate:value'?: InputEmits['update:value'];

$ .../dist/input/Input.js
104:		emit("update:value", target?.value);
```

  `grep -c modelValue Input.d.ts Input.js` → `0 0`（无 `modelValue` prop/事件）。
  证据文件：`.validation/opt2b/antdv-evidence.log`。
- 原生 `input` 事件确实到达 antdv 内部并 emit `update:value`，但父组件没有监听
  `update:value`，所以 `input` ref 始终为空；`submit()`（`SearchView.vue:283-293`）
  读到空串，`router.push` 的 `q` 为 `undefined`。
- 副作用（可复现）：深链 `?q=...` 后输入框也显示空（probe 最后一行
  `search-input value after navigation: ""`），即 `watch(q)` 写 `input` ref 也传不到 antdv。
- **建议（属 `apps/**`，本轮未改）**：`SearchView.vue:312` 与 `MutantsListView.vue:85`
  的 `<Input v-model="...">` 改为 `v-model:value`；改后本 spec 里 `search-input` 那一行
  也会自然开始产生 `q`（本 spec 两个字段都打字，改与不改都能过）。

> 说明：任务允许“保留 `?q=` 兜底”。这里没有退回深链，而是用同为真实输入的头部
> omnibox 完成导航，等价且更强。

---

## 2. OPT2-05 — verifier 单条命令

### 2.1 改前

`scripts/verify-site-variant-artifacts.sh` 本来就有“非 PREBUILT 就自行 build”的 else 分支
（第 54–57 行），但从没在单条命令里被跑过。实测**在本机失败**：

```
$ bash scripts/verify-site-variant-artifacts.sh
[site-variants] building external + internal artifacts (demo, offline)
...
thread '<unnamed>' panicked at rayon-core-1.12.1/src/registry.rs:168:10:
The global thread pool has not been initialized.: ThreadPoolBuildError { kind: IOError(Os { code: 11, kind: WouldBlock, message: "Resource temporarily unavailable" }) }
fatal runtime error: failed to initiate panic, error 5, aborting
exit=1
```

证据：`.validation/opt2b/vsva-unmarked-fail.log`。

### 2.2 改后（脚本内固化）

在 `unset CI` 之后加一行（尊重调用方显式值）：

```bash
export RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-4}"
```

并补齐 Usage 文档（单命令默认 build；`SOYMUTDB_SITE_VARIANTS_PREBUILT=1` 复用制品）。
未新增 `--build` 开关——原有默认分支即为单命令 build 路径。
未改 PREBUILT 分支、未改哨兵集合逻辑。

### 2.3 单命令实测（exit 0）

```
$ bash scripts/verify-site-variant-artifacts.sh
exit=0
```

关键输出（BUILD / SCAN / VERIFY）：

```
[site-variants] building external + internal artifacts (demo, offline)      # BUILD
[site-variants] external artifact must not contain internal-only values     # SCAN
OK: external artifact contains no supplied protected values
[site-variants] portal dual-site artifacts are built and isolated           # VERIFY
```

（完整日志 `.validation/opt2b/vsva-single-command.log`；另有 noindex / 不含公共快照两条 SCAN 断言亦通过。）

### 2.4 CI 既有 PREBUILT 用法未被破坏

```
$ SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh
[site-variants] reusing the prebuilt external + internal artifacts
...
[site-variants] portal dual-site artifacts are built and isolated
PREBUILT exit=0
```

`scripts/ci-job-steps.sh:284-285`（`frontend_run`）与 `.github/workflows/ci.yml:164-165`
的调用方式原样可用。

契约测试：

```
$ python3 scripts/test_ci_job_contracts.py        → Ran 60 tests ... OK   (exit 0)
$ python3 -m unittest scripts.test_site_artifact_isolation → Ran 11 tests ... OK   (exit 0)
```

---

## 3. Playwright 改前 / 改后计数

命令（两次完全相同）：

```bash
cd e2e && ./node_modules/.bin/playwright test -c playwright-internal.config.ts --workers=1
```

| 时点 | passed | skipped | failed |
| --- | --- | --- | --- |
| 改前（基线） | 3 | 0 | 0 |
| 改后 | 3 | 0 | 0 |

改后三次复跑（含 verifier 重建 `dist` 之后）均 `3 passed (≈6s)`，`0 failed / 0 skipped`。
`test.skip(!INTERNAL_BASE_URL, ...)` 因离线兜底 base 存在而不触发。

---

## 4. 未完成 / 未验证 / 阻塞

- **未改应用源码（缺口已记录）**：`SearchView.vue:312`、`MutantsListView.vue:85` 的
  `<Input v-model>` 应为 `v-model:value`。修复后 search 表单与 mutagen 过滤器才可按
  DOM 事件驱动；本轮不改 `apps/**`。
- **未验证：真实部署 `INTERNAL_BASE_URL`**。本次全部为离线制品 + 页面级 mock；
  `OFFLINE=false` 时 `captured` 断言跳过（既有设计）。live API 不在本题要求内。
- **未验证（非本人所有权）**：`scripts/verify-frontend-artifacts.sh:65` 直接调
  `pnpm --filter @soymutdb/web build:sites`，未设 `RAYON_NUM_THREADS`；在本机同样会命中
  上面的 rayon `EAGAIN`。建议后续在该脚本或 workspace 层统一设默认值。
- **环境提示**：期间 `apps/web/dist/{external,internal}` 被一次并发 `pnpm build`（写
  `dist/` 根，`emptyOutDir` 会清掉子目录）整体删除过一次；verifier 单命令每次自行 build，
  因此不受影响，但并跑时需注意。
- **阻塞**：无。E2E 仍离线可跑（`static-server.mjs` + `mockEntityApis`），未新增依赖。

---

## 5. 复现命令

```bash
# 0) 构建制品（约 1–2 分钟；RAYON 由脚本默认给出）
pnpm --filter @soymutdb/web build:sites        # 本机需 RAYON_NUM_THREADS=<small>，见 §0

# 1) OPT2-05 单命令
bash scripts/verify-site-variant-artifacts.sh  # exit 0

# 2) OPT2-04 E2E（配置自带 offline webServer，端口 4175，workers=1）
cd e2e && ./node_modules/.bin/playwright test -c playwright-internal.config.ts --workers=1

# 3) 证据脚本（可选；需先自行起 static-server.mjs 于 4175）
node e2e/probe-search-input.mjs
```
