# W6 制品隔离与 E2E — 消融实验报告

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 仓库：`/mnt/data02/T25ronglin/code/web`（HEAD `8e78116fd`）
- 执行者：子代理 F（W6）
- 日期：2026-09-26
- 判定口径：`GUARD-ACTIVE`（消融后行为翻转）/ `GUARD-INERT`（消融后行为不变）/ `GAP`（对照即失败）
- 证据分级：**E1 = 真实运行**（构建/扫描/unittest/Playwright）；**E2 = 仅源码追踪**

> 全程未修改生产源码；所有临时制品与变异副本位于 `.validation/ablation/artifact/`。`git status` 与开工前一致（仅在运行结束后执行了只读的 `git status` 对比）。

---

## 1. 目标与范围

本工作流回答两个问题：

1. **ID-05（双站制品隔离）**：`apps/web` 的 `external` / `internal` 两个制品变体是否真的被隔离，且隔离守卫在制品被破坏时**真的会失败**（而不是“测试曾经通过”）。
2. **E2E-01 / E2E-02 可行性**：离线（无 Docker、无后端、无网络）能否真实跑起公开站与内部站 E2E；若不能，缺少什么前置条件。

范围与 PLAN.md §2 的 W6 一致；同时复核审计怀疑的 `production-gate.spec.ts` JBrowse 帧断言是否“只看标题就能过”。

---

## 2. 环境与命令

### 2.1 关键环境事实（实测）

| 项 | 值 |
| --- | --- |
| Node | `v24.19.0` |
| Playwright | `e2e/node_modules/.bin/playwright` 1.62.1 |
| 浏览器缓存 | `~/.cache/ms-playwright`（`chromium-1234` 存在） |
| 扫描器 | `scripts/check_site_artifact_isolation.py` |
| unittest | `scripts/test_site_artifact_isolation.py`（6 用例） |
| 临时目录 | `.validation/ablation/artifact/` |

### 2.2 沙箱踩坑：`pnpm` 因 `$HOME` 只读而不可用（已解决）

本会话沙箱只允许写工作区；`$HOME=/mnt/data02/T25ronglin` 的 `~/.local/share/pnpm` 为**只读文件系统**。直接调用 `pnpm` 得到：

```
$ pnpm --version
[ERROR] unable to open database file
exit=1
```

解决：把 pnpm 的 home/state/cache/config 全部指向工作区内可写目录（`.validation/ablation/artifact/pnpmenv.sh`）：

```bash
export PNPM_HOME=$PWD/.validation/pnpm/home
export XDG_STATE_HOME=$PWD/.validation/pnpm/state
export XDG_CACHE_HOME=$PWD/.validation/pnpm/cache
export XDG_CONFIG_HOME=$PWD/.validation/pnpm/config
```

设置后 `pnpm --version` → `12.5.1`，`exit=0`。**本报告所有 pnpm 命令都先 source 该脚本**，并按要求加 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`。

### 2.3 ID-05 对照构建（E1）

```bash
CI= VITE_DEPLOYMENT_MODE=demo \
  VITE_API_BASE_URL=https://api.soymutdb.test \
  VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  SOYMUTDB_INTERNAL_SITE_URL=https://internal.soymutdb.invalid \
  GOMAXPROCS=2 RAYON_NUM_THREADS=1 \
  pnpm --filter @soymutdb/web build:sites
```

关键输出：`[sites] external and internal artifacts built`，`BUILD_EXIT=0`
（日志：`.validation/ablation/artifact/build-sites.log`）

对照扫描（真实构建产物，未变异）：

```bash
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel 'noindex, nofollow, noarchive'
```

输出：`OK: external artifact contains no supplied protected values`，`CTRL_SCAN_EXIT=0`
内部制品 27 个 HTML 命中哨兵、外部 0 命中；`apps/web/dist/internal/data/content.json` 不存在。

对照 verifier（复用已构建产物）：

```bash
SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh
```

输出末行 `[site-variants] portal dual-site artifacts are built and isolated`，`CTRL_VERIFIER_EXIT=0`。
→ **verifier 在本环境可运行**；`SOYMUTDB_SITE_VARIANTS_PREBUILT=1` 时只需 `grep` + `python3`，不需要重新构建。

### 2.4 隔离 unittest 套件（E1，作为补充证据）

```bash
python3 -m unittest scripts.test_site_artifact_isolation -v
```

`Ran 6 tests ... OK`，`EXIT=0`。6 项分别是：干净放行 / 嵌套文本与二进制命中且不含明文 / 多哨兵确定性排序 / 路径命中脱敏 / 非法或重叠配置 fail-closed / 外部符号链接拒绝。

---

## 3. 逐场景结果表

### 3.1 ID-05 双站制品隔离

所有消融均对 `.validation/ablation/artifact/scratch/golden/{ext,int}`（对照构建产物的完整副本）执行，**单因素**变异。

| 场景 | 对照 | 消融 | 判定 | 证据（命令 + 退出码 + 关键输出） |
| --- | --- | --- | --- | --- |
| ID-05-a 内网哨兵泄漏进 external | 扫描 exit 0 | 把 `noindex, nofollow, noarchive` 追加进 `external/index.html` | **GUARD-ACTIVE** | `python3 scripts/check_site_artifact_isolation.py --external-root $S/a_ext --internal-root $S/golden/int --sentinel '...'` → exit **1**，`FAIL: ... sentinel #1 found: index.html` |
| ID-05-b1 删除 external 必需入口 `index.html` | 扫描/verifier exit 0 | `rm external/index.html` | **GUARD-INERT** | 扫描 → exit **0**、`OK: ...`；verifier（在真实 dist 上临时改名）→ exit **0**、末行 `portal dual-site artifacts are built and isolated` |
| ID-05-b2 删除 internal 根 | 扫描 exit 0 | 指向不存在的 internal root | **GUARD-ACTIVE** | 扫描 → exit **2**，`FAIL: invalid artifact isolation configuration` |
| ID-05-b3 删除 internal 入口 `internal/index.html` | verifier exit 0 | `mv internal/index.html` 后跑 verifier | **GUARD-ACTIVE** | verifier → exit **1**，`grep: apps/web/dist/internal/*.html: 没有那个文件或目录` + `FAIL: internal HTML does not carry 'noindex, nofollow, noarchive'` |
| ID-05-b4 internal 混入公共内容快照 | verifier exit 0 | 植入 `internal/data/content.json` | **GUARD-ACTIVE** | verifier → exit **1**，`FAIL: internal artifact contains the public content snapshot` |
| ID-05-c1 外部制品符号链接逃逸 | 扫描 exit 0 | `external/escape -> ../outside`（外部目录含 `INTERNAL-ONLY-VALUE`） | **GUARD-ACTIVE** | 扫描 → exit **1**，`FAIL: ... symlink not allowed: escape`（未跟随、未读到敏感值） |
| ID-05-c2 路径名含哨兵的**空目录** | 扫描 exit 0 | 建空目录 `dir-noindex, nofollow, noarchive/` | **GUARD-INERT** | 扫描 → exit **0**、`OK: ...`（空目录名中的哨兵不被检查） |
| ID-05-c2' 同上但目录内有文件 | — | 向该目录放入 `f.txt` | **GUARD-ACTIVE** | 扫描 → exit **1**，`sentinel #1 found in path: dir-<sentinel-1>/f.txt` |
| ID-05-c3 两制品根互相嵌套 | 扫描 exit 0 | external 置于 internal 之下 | **GUARD-ACTIVE** | 扫描 → exit **2**，`FAIL: invalid artifact isolation configuration` |
| ID-05-c4 external 与 internal 同一根 | 扫描 exit 0 | 两参数指向同一目录 | **GUARD-ACTIVE** | 扫描 → exit **2**，`FAIL: invalid artifact isolation configuration` |
| ID-05-c5 哨兵集合过窄 | 扫描 exit 0 | external 注入 `internal.soymutdb.invalid`，但仍用 verifier 的**唯一**哨兵扫描 | **GUARD-INERT** | 用 `--sentinel 'noindex, nofollow, noarchive'` → exit **0**；再加 `--sentinel 'internal.soymutdb.invalid'` → exit **1**，`sentinel #2 found: index.html` |

### 3.2 E2E

| 场景 | 对照 | 消融 / 操作 | 判定 | 证据 |
| --- | --- | --- | --- | --- |
| E2E-01a 公开制品离线全套 | 同源 mock + SPA 就绪等待下真实运行 | 构建单站制品（`VITE_BASE_URL=/soymutdb-next/`、同源 API/JBrowse origin）后跑 `playwright-public.config.ts` | **对照通过** | `E2E_PUBLIC_FULL_EXIT=0`，`29 passed`、`2 skipped`（22.6s） |
| E2E-01b JBrowse shell + portal 嵌入 | 本地同源同时服务 portal 与 shell | 跑 `playwright-jbrowse.config.ts`（`JBROWSE_BASE_URL=/` `PORTAL_BASE_URL=/soymutdb-next/`） | **对照通过** | `E2E_JBROWSE_EXIT=0`，`5 passed`（含 iframe `browser-ready` 桥接） |
| E2E-01c search → detail → JBrowse 的一致性断言 | 表单/列头/列序均有真实断言 | `genes.spec.ts` 的 “JBrowse 2 action opens a locus deep link” 是**无条件 `test.skip`** | **GAP** | `e2e/tests/genes.spec.ts:55` 起 `test.skip(`；全套日志中该项显示为 `-`（skipped） |
| E2E-01d 详情页（detail）覆盖 | — | 13 个 spec 中无任何 spec 访问实体详情路由 | **GAP** | `ls e2e/tests/*.spec.ts`；无 `*detail*` spec |
| E2E-02 内部站登录 → internal_id 检索 → 详情 | — | 无任何 config/spec 针对 internal 变体；把 public 套件指向 internal 制品真实运行 | **GAP** | 无 config 命中（见 §4.4）；真实运行 `8 failed / 1 passed`，`E2E_INTERNAL_EXIT=1`，错误上下文 `heading "404"` / `paragraph: No route for /soymutdb-next/login?redirect=%2Fanalyses.` |
| PG-JBROWSE 审计怀疑项 | `/browser` 有 iframe → 通过 | stub `/browser` 去掉 iframe → 必须失败 | **GUARD-ACTIVE** | 对照：`1 passed`、exit 0；消融：`1 failed`，定位到 `e2e/tests/production-gate.spec.ts:129` `expect(jbrowseFrame, ...).toBeTruthy()` |

---

## 4. GAP 与 INERT 发现

### 4.1 INERT-1：`external/index.html` 缺失无人管（ID-05-b1）

- `check_site_artifact_isolation.py` 只校验「external 是否含哨兵」，不校验「external 是否仍有入口文档」；
- `verify-site-variant-artifacts.sh` 也只在 internal 侧要求 `*.html`（`grep -Rq ... apps/web/dist/internal/*.html`），external 侧只跑哨兵扫描。
- 后果：external 整个 `index.html` 丢失（站点对爬虫/首屏失效）时，双站门禁仍 `exit 0`。同一脚本对 internal 入口缺失是 ACTIVE 的，两站标准不对称。

### 4.2 INERT-2：空目录的哨兵注入不被发现（ID-05-c2）

`scan_external()` 只在「遍历文件的循环」里对文件名做 `if value in relative` 检查；目录名仅用于符号链接判断。因此一个**名字里含哨兵但没有文件**的目录不会命中。实际制品目录通常非空，风险有限，但这是判断逻辑的空档。

### 4.3 INERT-3：哨兵集合是单点、且不覆盖“内网 origin”类泄漏（ID-05-c5）

- `verify-site-variant-artifacts.sh` 使用的哨兵**只有一个**：`NOINDEX_MARKER="noindex, nofollow, noarchive"`；
- `e2e/README.md` 另记有生产哨兵 `Internal Research Workspace for SoyMutDB`，但本次两个变体中都不存在该串（`grep` 命中 0），即该“生产哨兵”当前并未被 verifier 使用；
- 实测把 `internal.soymutdb.invalid` 注入 external，用 verifier 的唯一哨兵扫描 **exit 0（放行）**；只有额外传入该串才会 exit 1。也就是说：任何**非 `noindex` 标记**的内网专用值泄漏，当前门禁看不见。
- 注：`scan_external` 的 docstring 明确说“只扫描调用方给出的哨兵，通用字段名不算泄漏”，因此这是设计取舍；但 verifier 没有把内网 origin / 内网内容 token 传进去，属于覆盖缺口。

### 4.4 GAP-1：E2E-02「内部站登录 → internal_id 检索 → 详情」完全未覆盖

E2（源码追踪，命令与结论）：

- `e2e/tests/*.spec.ts` 全文检索 `internal`，唯一命中是 `public-login.spec.ts:94` 的用例名 “safe internal analyses route”（指的是登录后的 `/analyses` 路由，不是 internal 站点变体）；
- `grep -rn "internal\|external\|VITE_DEPLOYMENT_MODE\|dist/internal" e2e/*.config.ts` → **零命中**：没有任何配置显式指向 `apps/web/dist/internal`；
- `playwright-public.config.ts:19` 的 `testMatch` 只列了 homepage/search/genes/accessibility/blast/public-login，全部按 `BASE="/soymutdb-next"` 硬编码。

E1（真实运行，命令）：

```bash
# 用 scratch server 把 internal 制品挂到 / 与 /soymutdb-next/，再跑公开套件
node .validation/ablation/artifact/serve-internal.mjs   # 后台
cd e2e && ./node_modules/.bin/playwright test -c playwright-public.config.ts \
  tests/search.spec.ts tests/public-login.spec.ts
```

结果 `8 failed / 1 passed`，`E2E_INTERNAL_EXIT=1`；`error-context.md` 显示页面是路由 404：

```
- heading "404"
- paragraph: No route for /soymutdb-next/login?redirect=%2Fanalyses.
```

根因：`build:sites` 产出的变体其 `VITE_BASE_URL` 是 `/`（`internal/index.html` 引用 `/assets/...`），而公开 spec 硬编码 `/soymutdb-next` 前缀 —— 内部站**既没有专属配置、也无法直接复用公开配置**。因此“内部登录 → 按 internal_id 检索 → 详情”这条链目前**没有任何 E2E 覆盖**，且没有现成跑法。

### 4.5 GAP-2：search → detail → JBrowse 的“一致性”没有被执行

`genes.spec.ts` 中真正验证 “JBrowse 2 深链携带 assembly+locus” 的用例被无条件跳过：

```
e2e/tests/genes.spec.ts:55:  test.skip(
e2e/tests/genes.spec.ts:56:    "JBrowse 2 action opens a locus deep link in a new tab",
```

离线全套日志里它是 `-`（skipped）。同时没有任何 spec 访问实体详情页，所以 E2E-01 描述的 “search -> detail -> JBrowse with consistent id/assembly/release” 目前只有**碎片证据**（表单、列头顺序、`/browser` iframe 桥接），没有一条端到端断言 release/id/assembly 三者在跳转链上保持一致。`blast.spec.ts:52` 的 live 用例同样 skip。

### 4.6 审计怀疑项：`production-gate.spec.ts` 的 JBrowse 帧（GUARD-ACTIVE，已澄清）

审计怀疑“只看标题就能过”。在当前 HEAD 上该怀疑已被修复：断言在 `13b71cdaa` 落地，源码决定性行 —

```
e2e/tests/production-gate.spec.ts:123  const jbrowseFrame = frames.find((f) => /jbrowse|\/browser\//i.test(f.url() || ""));
e2e/tests/production-gate.spec.ts:126-128 // 注释：previous form only checked the frame when present, so a stripped iframe passed on the heading alone.
e2e/tests/production-gate.spec.ts:129  expect(jbrowseFrame, "JBrowse frame must be present on /browser").toBeTruthy();
e2e/tests/production-gate.spec.ts:130  await expect(jbrowseFrame!.locator("body")).not.toBeEmpty({ timeout: 15_000 });
```

真实消融（stub `/browser` 保留 `h1/h2` 但删除 `iframe`）：对照 `1 passed`，消融 `1 failed`，失败点正是 `:129`。→ **GUARD-ACTIVE**，标题兜底不再能骗过门禁。

---

## 5. 未验证项

| 项 | 原因 / 缺少的前置 |
| --- | --- |
| ID-05 全流程 `bash scripts/verify-site-variant-artifacts.sh`（不带 `PREBUILT=1`） | 需要在同一命令里完成 `pnpm build:sites`；本报告已分段真实执行了构建（exit 0）与 verifier（exit 0），但未在单条命令内串起（沙箱会回收后台子进程，pnpm 需 §2.2 的 env）。 |
| 真实 `pnpm --filter @soymutdb/web build:sites` 之下的 verifier | 已用 `PREBUILT=1` + 刚构建的产物覆盖；逐条消融在副本上完成。 |
| E2E-01 的 live 数据断言（真实 API） | `blast.spec.ts`、`genes.spec.ts` 的 live 用例为 `test.skip`；离线 mock 只返回空结果，`no fake rows` 策略下无法断言列内容/release。 |
| E2E-01 的 detail 页面 | 无 spec；需要先有一个详情页 spec 才能消融。 |
| E2E-02 内部站全链路 | 缺 internal 变体的 Playwright config / 静态服务器挂载（base `/`）；本次仅用 scratch server 证明“公开配置不适用”，未产出 internal 专属通过用例。 |
| `apps/web/dist` 当前内容 | 报告写作期间 `dist/` 被反复重建（sites ↔ 单站）。收尾已重跑 `build:sites` 恢复到双站布局；单站 E2E 产物与变体副本分别保留在日志与 `.validation/ablation/artifact/scratch/golden/`。 |

---

## 6. 原始证据附录

### 6.1 日志与副本路径

| 文件 | 内容 |
| --- | --- |
| `.validation/ablation/artifact/build-sites.log` | ID-05 对照构建（exit 0） |
| `.validation/ablation/artifact/build-sites-final.log` | 收尾重建 |
| `.validation/ablation/artifact/build-public.log` / `build-public2.log` | E2E 单站构建 |
| `.validation/ablation/artifact/e2e-public.log` | search + public-login 子集（9 passed） |
| `.validation/ablation/artifact/e2e-public-full.log` | 公开全套（29 passed / 2 skipped） |
| `.validation/ablation/artifact/e2e-jbrowse.log` | JBrowse shell + 嵌入（5 passed） |
| `.validation/ablation/artifact/e2e-internal.log` / `e2e-internal-one.log` | internal 变体走公开配置（8 failed / 1 passed） |
| `.validation/ablation/artifact/scratch/golden/{ext,int}` | 对照构建产物副本 |
| `.validation/ablation/artifact/serve-combined.mjs` / `serve-internal.mjs` / `serve-frame-stub.mjs` | scratch 服务器（非生产源码） |
| `e2e/test-results-public/*/error-context.md` | internal 运行的路由 404 上下文 |

### 6.2 复现命令清单（E1）

```bash
# --- 环境修正 ---
source .validation/ablation/artifact/pnpmenv.sh    # PNPM_HOME/XDG_* -> 工作区可写

# --- ID-05 对照 ---
CI= VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
  VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test \
  SOYMUTDB_INTERNAL_SITE_URL=https://internal.soymutdb.invalid \
  GOMAXPROCS=2 RAYON_NUM_THREADS=1 pnpm --filter @soymutdb/web build:sites   # exit 0
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
  --sentinel 'noindex, nofollow, noarchive'                                  # exit 0
SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh  # exit 0
python3 -m unittest scripts.test_site_artifact_isolation -v                  # 6 tests OK

# --- ID-05 消融（节选） ---
S=.validation/ablation/artifact/scratch
printf '\n<!-- noindex, nofollow, noarchive -->\n' >> $S/a_ext/index.html     # a: exit 1
rm -f $S/b_ext/index.html                                                     # b1: exit 0 (INERT)
python3 scripts/check_site_artifact_isolation.py --external-root $S/no_int ... # b2: exit 2

# --- E2E ---
# 单站构建
GOMAXPROCS=2 VITE_DEPLOYMENT_MODE=demo VITE_BASE_URL=/soymutdb-next/ \
  VITE_API_BASE_URL=http://localhost:4173/soymutdb-next/api/v1 \
  VITE_JBROWSE_BASE_URL=http://localhost:4173/ pnpm --filter @soymutdb/web build
cd e2e && ./node_modules/.bin/playwright test -c playwright-public.config.ts   # 29 passed / 2 skipped
```

### 6.3 结论摘要

- ID-05：真实构建 + 真实扫描 + 真实 verifier 对照全部通过（E1）；对“哨兵泄漏 / 根缺失 / 重叠 / 内部快照 / 符号链接”的单因素消融均翻转 → 主体 **GUARD-ACTIVE**。
- 三个 INERT（external 入口缺失、空目录路径哨兵、哨兵集合过窄）是**覆盖缺口**而非误报。
- E2E-01：离线可跑（29 passed + 5 passed，E1），但 “detail / release 一致性 / JBrowse 深链” 仍有 skip 与缺失。
- E2E-02：**GAP**，内部站变体无任何 E2E 归属。
- `production-gate.spec.ts` JBrowse 帧：**GUARD-ACTIVE**（真实对照/消融已验证，非仅源码推理）。
