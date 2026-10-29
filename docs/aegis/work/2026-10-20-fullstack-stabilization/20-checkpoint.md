# 全线稳定性修复检查点

## 2026-10-29 续作轮：CI 门禁复跑 + 导出功能贯通 + 独立审计缺陷修复（未提交 / 未 push / 未合并）

用户要求「读取项目目前状态，继续完成任务；处理好 CI/CD 报错，完善好功能」。本轮在
`fix/fullstack-stabilization-20261020`（HEAD 仍 `01fc163a4`）上继续，**未提交、未 push、未合并**；
基线 `57e2bcdee` 与 Draft PR #26 未动；未连接被标记损坏的 `127.0.0.1:55432` 实例，
本轮另起隔离集群 `.cache/pg-ci`（PG 16.15，`127.0.0.1:55440`，用完可停）。

### 一、本地可复现的 CI 门禁（本轮亲跑）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| smoke-contracts | `bash scripts/smoke.sh --profile contracts` | **SMOKE PASS**，349 passed + 5 subtests，exit 0 |
| API pytest | `apps/api` 全量（Python 3.15.0 + 全新 PG16 库） | **2612 passed / 8 skipped**，exit 0 |
| Worker pytest | `apps/worker/tests`（worker venv 3.15.0） | **672 passed / 35 skipped**，exit 0 |
| jobs-py pytest | `packages/jobs-py/tests` | **107 passed**，exit 0 |
| 架构/退役边界/弃用 API 守卫 | `check_architecture.py`、`check_retired_lane_boundaries.py`、`check_deprecated_api_usage.py` | 各 exit 0 |
| 门户 lint / typecheck | `pnpm --filter @soymutdb/web lint typecheck` | 各 exit 0 |
| OpenAPI 客户端契约 | `pnpm --filter @soymutdb/api-client generate:api-client && check:contract` | exit 0，route visibility `status: PASS` |
| 门户 Vitest | `apps/web` 全量 | 56 files / **503 tests**，exit 0（工作区合计 **1274** 个 JS 测试，turbo 11/11 包） |
| workspace lint/typecheck | `pnpm turbo run lint typecheck --concurrency=1` | **25/25 tasks**，exit 0 |
| **frontend 门禁** | `bash scripts/verify-frontend-artifacts.sh` | **21 个步骤全过 → `frontend verification passed`，exit 0**（构建/占位符扫描/头部契约/构建路径守卫/app shell/可见 i18n/插值/nginx 头/图表闭包预算/bundle 预算/单测/lint/typecheck/Vue 退役/页面注册表/query-key 架构/内容键契约/admin 传输边界/API 客户端契约） |
| 双站隔离 | `SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh` | `portal dual-site artifacts are built and isolated`，exit 0 |

### 二、功能补齐：门户「自定义导出」从死按钮变成可用功能

- **缺陷**：`apps/web/src/routes/downloads.tsx` 的自定义导出卡片有一个**没有任何处理函数**的
  Submit 按钮——文案承诺「提交异步导出任务」，页面却什么都不会发生。
- **修法（单一所有者，不复制逻辑）**：新增
  - `apps/web/src/lib/use-variant-export.ts` —— 导出生命周期的唯一所有者（提交 → 轮询 →
    签名下载），保留原有会话归属规则：注销/过期/换账号都作废在途请求与在途下载。
  - `apps/web/src/components/variant-export-controls.tsx` —— 门户唯一的导出控件；
    `/variants` 与 `/downloads` 共用它，不再有两套实现。
- **能力门禁**：导出端点要求 researcher 能力。控件现在只对**服务器会接受**的会话开放，
  其余会话看到的是登录入口，而不是一个必然失败的按钮（沿用 analyses 模块既有的
  `useIsResearcher` 判定，不新增第二套角色表）。
- **装配体作用域**：导出发起前必须绑定**唯一**装配体命名空间（v4/v5 不可混），
  `/downloads` 新增装配体选择器，默认取该 release 的默认装配体。
- **回归**：`apps/web/src/routes/downloads.test.tsx`（3 例）、`apps/web/src/routes/variants/export-flow.test.tsx`
  （新增 1 例能力门禁）、`apps/web/src/lib/use-variant-export.test.tsx`（2 例轮询窗口）。

### 三、独立审计发现的真实缺陷及其修复

`feature-audit` 子代理对未提交改动做了只读审计（`.cache/feature-audit/REPORT.md`，
0 blocker / 4 should-fix / 5 nit；10 项经核实后**主动放弃**，7 项明确未验证）。
本轮按严重度修复：

| ID | 缺陷 | 修复 |
| --- | --- | --- |
| FA-01 | 导出只校验装配体名长度，**不校验该 release 是否真有该命名空间的变异**：拼错的名字会产出一条 `succeeded`、0 行的导出记录，并对外宣称一个不存在的 release/装配体组合 | API 在排队前用 release 自己的 `variant_facts` 判定命名空间是否存在；不存在则 422 拒绝，**不留记录、不排队** |
| FA-02 | `/mutants?q=` 只匹配 name/cultivar/mutagen，**不匹配 `public_id`**——页面上显示的公开标识粘回搜索框是零结果 | `q` 现在也匹配 `public_id`（`ilike` 字面量），并保持 release/公开可见性不变 |
| FA-03 | Worker 的 `build_export_query` 只要求 release，**不要求装配体**：Celery 任务是被外部可调用的入口，缺装配体会让 SQL 跨命名空间，而记录仍宣称单一命名空间 | 缺装配体直接 `ValueError` 失败；SQL 显式绑定 `v.assembly_key = :assembly` |
| FA-04 | ①门户对永不终结的记录**无限轮询**；②`_claim_export` 在 try 之外，claim 自身失败会让记录永远停在 `pending`（正是 ① 无限轮询的状态） | ①轮询窗口 10 分钟，之后停止轮询、明示「耗时超出预期」并提供显式复查；②claim 移入受保护阶段，失败也进入终态 |
| FA-05 | `variant_export_service.py` 注释称 `get_settings()` 每次都新建 `Settings`（实际是 `lru_cache`） | 注释改正 |
| FA-06 | 4 个 i18n 键无引用 | `blast.hitProteinCoords` **被真正使用**（BLAST 命中表新增「蛋白坐标」列，并注册进 `settings_registry` 以满足内容键契约守卫）；`mutants.loadMore/loadingMore`（该页用分页而非「加载更多」）删除 |
| FA-07 | `/variants` 仍用非响应式的 `getReleaseId()`，与已迁移的 search/mutants 不一致；release 切换后查询键仍宣称旧 release | 改用 `useReleaseId()` |
| FA-08 | API 把 `q` 限 200 字符，门户输入框无上限，超长粘贴只显示通用加载失败 | 输入框 `maxLength=200` |
| FA-09 | 门户导出请求带 `limit: 200`，而服务端**丢弃**该参数：导出的其实是整个装配体，文案却说「最多 1000 万条」 | 门户不再发送无意义的 `limit`；schema 明确写清 `limit` 对导出**不生效**；文案改成真实预算 |

另修一处后端潜在缺陷（后端门禁代理实测发现）：**worker 的 DSN 归一化缺失**——
裸 `postgresql://` 在 SQLAlchemy 2 解析为 psycopg **v3** 方言，而 worker 只装了 `psycopg2-binary`，
其**自带默认 DSN 正是裸写法**，连接会以 `No module named 'psycopg'` 失败。
现统一归一为 `postgresql+psycopg2://`，并补 5 例回归。

### 四、环境限制（不是代码缺陷，也不据此改仓库构建配置）

- 本机 `os.cpus().length = 256`，webpack 自带 `TerserPlugin` 默认 `parallel: true`
  ⇒ 压缩器 worker 数 = 255，本机沙箱拒绝该规模的线程创建，报 `EAGAIN` / `newosproc`。
  实测把「可见 CPU 数」降到 4 后同一棵树 **12.98s 编译成功**。
  本轮用 `.cache/cpu-limit/preload.cjs`（仅本机，不入库）跑完三端构建；
  结论与绕过方法已写进 `.ai-memory/LOCAL-RUN-ENV.md`。
  CI 镜像（GitHub runner 2–4 核、CNB stage）的 `cpus-1` 只有个位数 worker，不会触发。
- 本机**无网络**：`pnpm install --frozen-lockfile` 只能走到 store 锁（全局 store 只读），
  但**未出现 `ERR_PNPM_OUTDATED_LOCKFILE`**，即 lockfile 与 manifests 一致；
  `pnpm audit` / `npm ci --prefix e2e` 等依赖网络的治理步骤本机无法执行。
- 未执行：`install_python_workspace.py`（需 pip 联网安装）、历史 chdb/Python 3.14 迁移通道、
  Docker 相关作业（compose-acceptance / image-build / release / clickhouse-migration / mcp-e2e）、
  真实浏览器 E2E、真实 broker/S3。

### 五、未关闭 / 后续

- 导出仍**缺真实端到端验收**：本轮的 API/Worker 证据是单元与数据库集成层，
  没有跑过「浏览器提交 → outbox → Celery → 对象存储 → 签名下载」整链。
- `variant_exports.filters` 是否会被序列化给客户端，本轮只做了静态核对。
- release 默认装配体与 facts 命名空间是否总是一致，仍只能在有健康 PG 的环境验证。
- 后端 API 套件在**复用**同一数据库时会因迁移 0041 预置的 `active_release.id=1` 冲突
  （324 次 `duplicate key`）：这是本地环境残留，CI 每次用全新容器，不影响门禁；
  修它要改大量测试夹具，本轮只记录。
## 2026-10-25 后续授权验证：构建与相关回归通过，但翻译 mock 契约仍红

用户经确认工具扩大了 Lead **直接验证**权限：不连 DB、不起服务、不提交/合并，超范围缺陷只记录。本轮**无业务源码修改**；固定 Node 26.10.0 / pnpm 12.11.2 / Python 3.15.0。

- 门户相关 **9 文件/100 passed**，管理端相关 **3/28 passed**，客户端相关 **4/23 passed**，JBrowse Node 契约 **71 passed**。不是全仓测试。
- 客户端 typecheck、OpenAPI 同步与路由可见性、三应用 lint/typecheck、locale/插值/可见文案、query-key/admin 架构检查均通过。
- **新构建**：门户 external/internal 各 28 HTML、admin、JBrowse 标准脚本全部 exit 0。新制品的双站 sentinel/noindex/snapshot 检查、头部/路径/壳资源、门户 bundle 和三树图表闭包预算均通过。此前“admin/jbrowse 未重建”在本轮已关闭；**不等于真实浏览器验收或 Vite 运行时验证**。
- Python 3.15 窄跑接受项/翻译 4 契约：接受项相关 **3 passed**，翻译 mock 契约 **1 failed**，当前 **10 个**前端测试仍有 per-render `t`；未放宽断言、未顺手改测试。**仍不能全绿或合并**。
- 过程错误留证：JBrowse lint 首次误用不存在的 app-local binary，exit 127；按既有脚本语义改用 workspace root ESLint，exit 0。未安装依赖。
- 同一份已有全严重度审计经 **Python 3.15** 重新策略评估仍通过、接受项为零；不是新抓 audit，不表示 moderate/low 消失。

精确命令、所有 exit、10 个失败文件及新制品 SHA256 清单见 [授权验证汇总](../../../../.cache/integration-verification-20261025/SUMMARY.md)。HEAD `01fc163a4`、baseline `57e2bcdee` 未变；dirty 路径 **104→104**，未做 Git 写。无浏览器、PG18/迁移、broker/S3、全仓测试/CI 证据；损坏 PG 继续禁止操作。下一步需处理既有翻译测试契约，并在获准的健康环境做数据库/浏览器验收；全局目标**未完成**。

## 2026-10-25 当前状态：中断恢复后的窄回归（取代下文历史“仍红/待批准”现状判断）

用户经确认工具授权 Lead 临时直接执行最小恢复；MiniMax、GLM 清点/恢复代理连续失败的事实保留，不把启动成功当交付。

- **本轮直接修复**：搜索跨装配体选择按钮仅显示版本，不把 API 的当页分布计数冒充总数；新增一条实际 UI 回归，先 1 failed / 27 passed，后 **28 passed**。E2E mock helper 原先只允许默认装配体字面量，现允许已有默认/预览两种 fixture，**TS2322 + TS2367 复现后消除**，不加断言/忽略类型错误。
- **固定工具链**：Node 26.10.0 / pnpm 12.11.2；搜索窄 Vitest、两份 E2E spec 的 bundler-resolution tsc、3 个改动文件 ESLint、apps/web 包级 tsc 均 exit 0。Playwright 正确 public 配置仅 **list 15 项**，未执行浏览器测试。
- **当前完整依赖审计**：全严重度 exit **1**，剩 **2 moderate（react-router）+ 1 low（elliptic），0 high/critical**；未改生产策略，真实空接受清单评估同一报告 **passed=true，accepted=[]**。不等于全治理 job 或全仓通过。此前 body-parser/fast-uri 补丁已落锁；中断代理留存 frozen install=0、dedupe=0、peer check=1（非本轮重跑）。
- **必须披露的偏差**：首次 E2E list 经 pnpm exec 意外自动安装了隔离 E2E 环境 5 个包，再因默认配置只选 online-smoke 而失败；后用现有执行文件+public 配置列举成功，**本轮不得宣称“完全未安装”**。另一次错误 NodeNext tsc、一次相对 env 路径错误均留存，不算目标复现。
- **前端旧报告订正**：A/B MiniMax 双评审及 S1/S2/S3 独立复核已回收；S2 独立 14 web + 5 admin pass，S3 补充回归固定版本 21 pass，均为先前代理证据。S4 留存 6 pass、原子筛选/page 状态及精确 assembly id URL 断言，**尚非独立浏览器验证**。BLAST 已实际传递 assembly，不再沿用“深链缺失”旧结论。
- **接受项测试订正**：已改临时 fixture、独立相关 3 项通过；不再依赖真实文件非空。实施代理跑 68/69 项整模块违反“只窄测试”约束，属过程偏差。其“剩余 high 是 vite 7.3.6”报告归因错误，当时是 body-parser；当前 fresh feed 两者皆无 high。真实接受项仍为零，未新增/续签。
- **未关闭**：损坏 PG 禁止操作、PG18 迁移/DB 集成、真实 broker/S3、全仓门禁、双站新制品与浏览器/390px/读屏验证、vendored body-parser 审计盲点及既有 peer 问题。全局目标仍 **未完成、不可合并**。

主证据与全部失败尝试：[本轮恢复汇总](../../../../.cache/direct-recovery-20261025/SUMMARY.md)；精确日志索引见本目录 [90-evidence.md](90-evidence.md) 顶部。分支/HEAD 仍 `fix/fullstack-stabilization-20261020` / `01fc163a4`，baseline `57e2bcdee` 仍祖先；dirty **103→104**（helpers.ts 新变脏），无提交/推送/合并/回滚。Draft PR #26 是此前已核实结果，本轮未查询远端。

## 2026-10-24 晚间窄切片：注销已失效的 `braces` 风险接受项（用户经确认工具明确授权；治理门禁**仍红**，但红的原因已换成**新的** `body-parser` high）

**授权与边界**：用户经**确认工具**明确授权**注销**已不再匹配当前发现的 `braces` 接受项，并明确**不新增、不续签任何风险接受**。本切片写入面**只有 3 个文件**：`security/advisory-acceptances.json`（**仅**删除 `GHSA-vfj7-8cjw-p6xm` / `braces` 这一条失效 entry）、本目录 `20-checkpoint.md` 与 `90-evidence.md`（追加本节）。**未写治理 doc**（`docs/ops/dependency-governance.md` 本轮**不动** —— 其中仍写着旧的 stale 接受项口径，属**待办欠账**，见下）；**未改代码、未改 lock、未安装、未起服务、未连数据库、未做 Git 写**。

**新鲜 feed（本次亲跑）**：`pnpm audit --registry https://registry.npmjs.org/ --json` → **exit 1**；全严重度 **8 条** = **1 high（`body-parser` `GHSA-27r3-jxmh-p828`）+ 4 moderate（`fast-uri` ×2、`react-router` ×2）+ 3 low（`elliptic`、`fast-uri` ×2）**；**`braces` 仍然 0 条**（`braces_advisories_reported: []`）。包集口径与前次留存**一致**（totalDependencies 1895 / deps 1559 / dev 155 / optional 198）⇒ 3 → 8 的差额**全部来自新发布的 advisory**，不是包集变化，也不是审计器行为变化。

**为什么 `braces` 不再出现（上游事实，非本仓判断）**：GitHub 官方 advisory 记录现标题为 **"Withdrawn Advisory: braces vulnerable to stack-exhaustion denial of service through deeply nested patterns"**，`withdrawn_at = 2026-10-23T12:53:02Z`（`published_at 2026-09-18`），OSV 同记 `withdrawn: 2026-10-23T12:53:02Z`，CVE-2026-93687。**被撤回 ≠ 已修复**：`braces@3.0.3` 与 `sprintf-js@1.1.3` **仍在锁内**（`pnpm-lock.yaml` 仍可 grep 到），**feed 不再报不等于这两个包安全**。

**删除前后同一份报告的门禁判定**（仓库自带 `load_advisory_acceptances` + `evaluate_advisory_report`，脚本 `.cache/stale-braces-retirement/scripts/40-gate-eval.py`，**只读**接受文件）：

| 阶段 | 退出码 | 未接受项 | 接受项数 |
| --- | --- | --- | --- |
| 删除前 | **1（FAIL）** | **2**：`body-parser: high GHSA-27r3-jxmh-p828` + `braces: acceptance ... matches no reported finding`（陈旧） | 1 |
| 删除后 | **1（FAIL）** | **1**：`body-parser: high GHSA-27r3-jxmh-p828` | **0** |

两次评估用的是**同一份** fresh 报告（`audit-fresh-full.json`，sha256 `8e17f2c2…`，前后一致）。⇒ **门禁依旧红**，但红的原因**换了**：陈旧接受项这条噪声被清掉，剩下的是**本次 feed 新出现的、`body-parser@1.20.8`（可修，patched `>=1.20.9`）的 high**。**本次删除没有、也不打算让门禁变绿**；`body-parser` **未**签署接受项（明确禁止新增/续签），留作独立受审后续。

**这不是"包已安全"（必须写清）**：本次删除是**用户授权的注销**（de-registration），**不是**安全结论。`braces` / `sprintf-js` 仍锁内、官方仍无 patched version；**接受项已归零 ⇒ 将来若 `braces` 再被报 high/critical，将没有任何接受项可匹配，门禁会自动失败**（这正是本仓"不腐烂"设计想要的行为）。

**连带代价（必须带出）**：`scripts/test_ci_job_contracts.py::test_advisory_acceptance_is_narrow_expiring_and_signed` **由绿转红**：该测试读取**真实**接受文件并断言 `assertTrue(entries)`（line 810），且后续多处 `payload["acceptances"][0]`（line 858/873/886/896）**结构上要求文件里至少有 1 条 entry**。**本切片不修改该测试**（授权写入面只有 3 个文件），也**不可能**靠"补一条接受项"绕过 —— 那正是被明令禁止的新增/续签风险接受。**基线对照已实测**：接受文件为 HEAD 内容时该套件 **68 tests / 1 failure**（`test_i18n_handling_needs_no_per_render_double`，**脏树既有问题，与本切片无关**）；本切片后 **68 tests / 2 failures**，新增的即上述接受项测试。**最小修复方向（留待授权）**：把该测试改为使用**临时目录内的合成 acceptance fixture**，不再依赖真实文件非空。

**前端口径同步（订正"等待用户批准"的写法）**：用户**已批准**前端改 MiniMax 的**双评审**，A/B **只读评审已启动**。本工作记录此前多处写"前端改 MiniMax 仍未获用户批准 / 双评审未完成" —— **该等待状态已结束**，相应条目已加 〔订正〕 标注，**历史原文一律保留不改写**。前端**双评审结论尚未回收**，前端工作**仍未完成**、不能计入验收。

**范围与 Git**：分支 `fix/fullstack-stabilization-20261020`、HEAD `01fc163a4c6488f97fe44ecf8f587b145cf989aa` **未变**；`git reflog` 末条仍是 2026-10-20 的设计提交 ⇒ **本轮无 Git 写**（未切分支、未 commit、未 push）；基线 Draft PR #26（`57e2bcdee`）**未动**。`git status --porcelain` **94 → 95**，增量 **+1 = 唯一那条被修改的 tracked 文件** `security/advisory-acceptances.json`；本目录两份工作记录位于**原本就是 untracked 的** `docs/aegis/work/2026-10-20-fullstack-stabilization/` 内，**不新增** status 条目。既有 dirty **全部保留**。`pnpm-lock.yaml` / `pnpm-workspace.yaml` / `package.json` 在切片前后 **sha256 校验 OK**（只审计，未安装、未改锁）。

**验收判定**：本切片（注销一条**已被上游撤回**的失效接受项）**自身可接受**；**整体不可合并、未提交、未 push**，**依赖治理目标仍未完成**（门禁红、`vite` 运行时未证、全仓门禁未跑等既有欠账不变）。

## 意图与基线

用户批准按计划分批兼容修复，基线 Draft PR #26 已保存、未合并（历史结果，本轮未查询远端）。目标包括核心功能衔接/UI UX可复现缺陷、已批准导出扩展及兼容依赖迭代，不是仅审计或完成一个切片。

分支 `fix/fullstack-stabilization-20261020`，最后核对HEAD `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（设计提交）；基线PR SHA `57e2bcdee3bab3435578997dba85cf26c3b985bc`。同任务大量dirty改动需保留，不把早期“业务未开始”当现状。无新分支/worktree、无Git写操作授权；后续用户“部署测试一下/继续”已授权本机隔离服务演练，未授权生产发布。最小安全依赖批次写入/安装已单独批准——**2026-10-24 已以 D1 批次形式交付**（workspace override + lock + 治理doc 三文件，见下文 D1 节），此前“收窄override后的提权被拒、已撤回本批配置/锁”的状态已由该批次取代；**同日 vite 定向切片亦已正式落地**（`"@umijs/bundler-vite>vite": 7.3.7`，独立复核 accept-with-gaps，见下文"vite 定向补丁"节）；但**治理门禁仍红**（只剩既有的 stale `braces` 接受项，处置待签署人决定），**不得据此宣称依赖目标完成**。保留三个既有detached validation checkout，不动生产数据/权威存储边界。**〔2026-10-24 晚间订正〕** 上段"治理门禁仍红（只剩既有的 stale `braces` 接受项，处置待签署人决定）"**已被本文件顶部「注销已失效的 `braces` 风险接受项」节取代**：该接受项已按**用户经确认工具的明确授权**注销（上游 GitHub/OSV 记该 advisory `withdrawn_at = 2026-10-23T12:53:02Z`）；**门禁仍红**，但红的原因已换成**本次 feed 新出现的 `body-parser` high `GHSA-27r3-jxmh-p828`**（可修，`patched >=1.20.9`），**未**为其签署任何接受项。

**工作树规模（2026-10-24 本轮只读复核确认）**：`git status --porcelain` = **94 项**（67 已跟踪修改 + 27 未跟踪）。较 2026-10-23 记录的 90 项增加 4 项，增量全部有据：+3 已跟踪（F1b/D1 触及的 `pnpm-workspace.yaml`、`pnpm-lock.yaml`、`docs/ops/dependency-governance.md`）、+1 未跟踪（F1b 新增 `apps/api/tests/test_export_assembly_scope.py`）。dirty **全部保留，未提交、未 push、未合并**；`git reflog` 末条仍是 `01fc163a4 docs(plan): define incremental full-stack stabilization scope`，**本轮无 Git 写**。

执行计划 `docs/aegis/plans/2026-10-20-fullstack-stabilization.md`，设计 `docs/superpowers/specs/2026-10-20-fullstack-stabilization-design.md`。TDD off，回归必须，跨模块身份/导出边界独立复核。环境用LOCAL-RUN-ENV固定Node26路径、workspace PNPM_HOME和低线程；专用PG16测试库 `soymutdb_test_stabilization_20261020`，不是PG18。

## F1b 导出 assembly 长度上限与 422 契约（2026-10-24；单切片可接受，整体不可合并、未提交）

本段**只补工作记录**。本轮（记录补齐）**未改代码/配置/依赖/数据库，未跑测试、未安装、未起服务、未做 Git 写**；只读 `git rev-parse` / `git status` / `git reflog` / `git diff --stat` 与读日志。

**执行者分离（不要混用）**：F1b 的**实施**由受派子代理完成（留存 `.cache/f1b/`）；F1b 的**独立复核**由另一受派子代理完成（留存 `.cache/f1b-review/`）；**我（Lead/记录者）本轮只读核实状态与文件范围，没有亲跑 F1b 的任何测试**。

**F1b 做了什么（据实施与复核两侧一致的记录）**：`apps/api/app/api/v1/variants.py` 的 `_export_assembly_scope()` 对**解析后的有效 assembly**（显式值优先、否则 release 作用域）做 **≤64** 校验，超长抛域 `ValidationError` → 干净 **422**，**不截断、不猜映射**，显式与 release 默认两条路径都覆盖；helper docstring 纠正为「TSV/CSV/JSON 逐行带 assembly，VCF 只在 header、BED 无自由 metadata 字段」；路由新增**路由级** `responses={422: ValidationErrorResponse}` 并说明两类拒绝（请求体 schema 校验失败 / 无法绑定唯一 assembly）。`apps/api/app/schemas/variant.py` 新增 `MAX_ASSEMBLY_KEY_LENGTH = 64`（对齐 `variant_exports.assembly_key` 的 `String(64)`；**未改列宽、未改迁移**），`VariantExportFilters.assembly` 可见描述重写为「显式优先 → 缺省用 release 作用域 → 无 scope 拒绝 → 单装配体 → **只校验长度、不校验存在性**」。新增 `apps/api/tests/test_export_assembly_scope.py`（**18 项纯无库测试**，import 并实际调用生产 helper）；`apps/api/tests/test_variant_exports.py` 增 **3 项 DB 回归**（64 接受并入库 / 65 显式 → 422 且 `error.code=validation_error` 且无记录无事件 / release 默认超长 → 422）——**本机未跑**。

**独立复核结论：accept-with-gaps（F1b 切片本身）**。复核侧**亲自**跑出：`ruff check` 4 文件 → All checks passed exit 0（`.cache/f1b-review/01-ruff-f1b-files.log`）；`pytest tests/test_export_assembly_scope.py`（唯一获准的一次窄测试，DB 用黑洞 URL + 禁 PG 集成变量 + `DOCKER_HOST` 指向不存在路径）→ **collected 18 items → 18 passed**，exit 0（`.cache/f1b-review/02-test-export-assembly-scope-reviewer.log`）；`check-contract.sh` → "client schema in sync" + route visibility `status: PASS`，exit 0（`.cache/f1b-review/03-check-contract-reviewer.log`）；**两种真实 422 handler 输出都符合已声明的 `ValidationErrorResponse`**（域拒绝带统一信封 `error.code=validation_error` 且无 `errors` 键；请求体 schema 拒绝带 `errors` 列表），exit 0（`.cache/f1b-review/04-422-envelope-conformance.log`）；已提交 `openapi.json` 与新鲜导出**一致**（`.cache/f1b-review/05-openapi-snapshot-sync.log`）；**F1b 的 OpenAPI 结构增量恰好 4 个叶子**（assembly 描述、export POST 描述、422 的 `$ref` 由 `HTTPValidationError`→`ValidationErrorResponse`、422 描述），**无 component 增删**，声明 422 的 operation 数不变（237）（`.cache/f1b-review/06-openapi-f1b-structural-delta.log`）。逐项命令、退出码与"我亲跑 / 代理报告"分级见 90-evidence 顶部同名节。

**文件范围偏差（如实记录）**：Lead 原授权只明确允许重生成 `packages/api-client/openapi.json` 且要求不覆盖其它客户端文件；实施代理**额外**重生了 `packages/api-client/src/generated/openapi.d.ts`（同一条既有官方生成链 `generate:api-client` 的产物）。**独立复核判定这是不可避免的同步生成、无破坏**：生成类型 diff 仅 JSDoc 与该 422 `$ref` 变化，`error-codes.json` 字节未变。**记为范围偏差，但不构成越界或数据损坏**；同时新增的 `apps/api/tests/test_variant_exports.py` 3 项 DB 回归**未跑**，是覆盖缺口。

**F1b 仍未关闭（不得记作已解决）**：
1. **release 默认词表 vs facts 词表**未对齐 ⇒ 仍可能「状态 succeeded 但制品为空」；需要**健康 PG** 证据才能推进。
2. **未知/拼错 assembly 仍走成功路径产出空制品**（只校验长度，不校验存在性）——该事实已如实写进契约描述，但缺陷本身**未修**。
3. **3 项新增 DB 回归未跑**；`0049` 迁移往返测试**仍 skip**；手工往返不替代迁移门禁。
4. 本机 PG 16.15 ≠ CI PG 18；PG 18 迁移/端到端未做。
5. **全局 422 形状不一致**（其余 236 个 operation 仍声明 `HTTPValidationError`；`x-error-codes` 12 个码描述全为空串）——**超范围只记录**，修它要改 `apps/api/app/main.py` 与 `core/exceptions.py`。
6. 真实 broker / S3 / 浏览器 / 双站制品闭环仍无证据。

**验收判定**：F1b **单切片可接受**；**整体仍不可合并、不完成**（未提交、未 push、未合并）。

## D1 依赖安全批次：follow-redirects 1.16.1 + hono 4.13.11（2026-10-24；独立复核 accept-with-gaps，治理门禁仍红）

**执行者分离**：D1 的**实施**由受派子代理完成（留存 `.cache/d1-implementation/`、`.cache/d1/`）；D1 的**独立复核**由另一受派子代理完成（严格只读，复算并复跑仓库自带治理判定）；**我（Lead/记录者）本轮只读核实文件范围与状态，没有亲跑 pnpm install/dedupe/audit**。

**D1 改了哪三个文件（唯一写范围）**：`pnpm-workspace.yaml`（唯一 hunk `@@ -54,0 +55,11 @@ overrides:`，新增 `follow-redirects: 1.16.1`（GHSA-q3jh-wrc6-jgq8 / GHSA-8r9p-f939-6h3c）与 `hono: 4.13.11`（GHSA-5r4p-p66f-jhc7），各带可达性说明注释）；`pnpm-lock.yaml`（由 `pnpm install --lockfile-only` 重生，**19 insertions / 17 deletions**，经 `--frozen-lockfile` 验证 "Lockfile is up to date" ⇒ 非手改）；`docs/ops/dependency-governance.md`（**+112 行**）。

**版本目标达成**：`follow-redirects` **1.16.0 → 1.16.1**、`hono` **4.13.9 → 4.13.11**（同主版本 patch，**无新增主版本**）。锁图 delta：package 键新增 `follow-redirects@1.16.1` / `hono@4.13.11`，移除 `follow-redirects@1.16.0` / `hono@4.13.9`；peer 快照变化仅两处（`@hono/node-server` 的 `hono ^4 → 4.13.11`、`@hono/node-ws` 的 `hono ^4.6.0 → 4.13.11`）。

**计数订正（不改原日志）**：实施者日志 `.cache/d1-implementation/05-lock-graph-compare.log` 抬头写的 "packages 1895 / snapshots 1901" 是**把 pnpm 多文档 YAML 相加**的结果，**口径不准确**；**独立复核自行解析复算的有效锁图是 1880 packages / 1886 snapshots / 14 importers**（importers 逐字节未变），且 pnpm 自身的供应链策略检查每次都打印 "1880 entries"，与该口径一致。**原日志保持原样不修改**，仅在此订正口径。

**门禁结果（实施者亲跑，留存 `.cache/d1-implementation/`）**：`pnpm install --frozen-lockfile --ignore-scripts` → exit 0（Packages: +6 -4）；`pnpm dedupe --check` → exit 0；`pnpm audit --registry https://registry.npmjs.org/ --json --audit-level high` → **exit 1**（退出码如实保留，未粉饰）；`pnpm --filter @soymutdb/api-client typecheck` → exit 0；api-client 契约检查 → exit 0 且 route visibility `status: PASS`。

**审计结果**：**11 → 8 条，新增 0 条**。被 D1 修掉的恰是 `hono` 1 条 + `follow-redirects` 2 条；残留 8 条 = **vite 7.3.6 ×5**（含 1 条 **high** `GHSA-587h-7wmj-h5pm`、3 moderate、1 low）、**react-router 6.30.6 ×2**（moderate）、**elliptic 6.6.1 ×1**（low）。两次审计同 registry、同包集（两份 JSON 的 metadata 一致：totalDependencies 1895 / deps 1559 / dev 155 / optional 198），baseline 用 HEAD 锁的**字节级副本**。

**治理门禁仍 FAIL（不可记作通过）**：独立复核跑了仓库自带的 `evaluate_advisory_report` —— BASELINE gate **FAIL 4 条** → AFTER gate **仍 FAIL 2 条**：`vite` 的 high 未接受 + **同一条既有的 `braces` stale 接受项**。即 D1 把「未接受高危」由 3 降到 1，但**门禁仍是红的**；`braces` stale 是**批次前既有**、非 D1 引入；8 条残留里只有 1 条进入门禁（判定只看 high/critical）。

**过程问题（独立复核的独立结论，非转述）**：`ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK` 的真实失败原文是 `Read-only file system (os error 30)` = **EROFS**；根因由复核侧读 `/proc/mounts` 独立确认 —— `tmpfs /run/user/1001 tmpfs ro,...` —— 是**主机只读挂载**，**不是 sandbox policy denial**（实施者 transcript 中 `[sandbox: file access denied under ... mode]` 出现 **0 次**、`escalation available` **0 次**，故不存在「策略拒绝后换路径重试」）。改用工作区内 `.ph/run` 属**运行时目录调整**（该目录早于本批次 3 天即存在，且 LOCAL-RUN-ENV 已把 `PNPM_HOME=$PWD/.ph` 定为标准配置），**未以「已有成功方式」自动免责**。保留意见：实施报告里「the sandbox exposes /run/user/1001 read-only」措辞不准（是主机挂载而非 DSH 策略）；**`XDG_RUNTIME_DIR` 这一具体旋钮本仓 LOCAL-RUN-ENV 未记载 ⇒ 记为运行环境说明缺口**，**本切片不去改 LOCAL-RUN-ENV**。

**D1 未关闭的 gap（独立复核列出）**：G1 治理 `pnpm-audit` 门禁仍 FAIL（vite high + 既有 stale braces 接受项）；G2 `13-final-scope-check.log` 记 108 行、该文件其后 21 秒又被编辑、最终 112（父汇报与 14 号回执用 112，口径正确）；G3 上述 1895/1901 计数口径；G4 `07-installed-versions.log` 内含一次 `MODULE_NOT_FOUND` 失败与空段（论断由 08 号日志与复核侧源码核对补齐）；G5 本地 `node_modules` 仍留孤儿旧版目录（fr 1.16.0 / hono 4.13.9，无 importer 指向、CI 不受影响，但遍历 `.pnpm` 的扫描器仍可见）；G6 api-client 合约检查跑在**脏树**上（回归信号非干净基线）；G7 **未跑全仓 lint/test/双站构建/CI ⇒ install/dedupe/audit 绿不等于仓库仍可构建**。另有 UNKNOWN：`minimumReleaseAge` 窗口天数在 `.npmrc` 内，安全网不可读，**具体值未知**（复核侧读 `.npmrc` 被拦截后未重试、未绕行）。

**未实施的最小下一步（仅讨论）**：未决残余只剩 `vite@7.3.6`。**全局 vite override 不可用**：树内还有 `vitest@5.0.5` 使用的 `vite@8.3.4`（vitest peer `^6.4.0 || ^7.0.0 || ^8.0.0`），全局覆盖会造成 vite 8→7 的**新主版本降级**并重写 vitest/@vitejs/plugin-react 的 peer 声明 —— 实施者排除它是正确的。可讨论的定向形态是父级选择器（如 `"@umijs/bundler-vite>vite": "7.3.7"`），但必须在**独立分支试验锁**上先过三关：① vitest 仍用 vite 8.3.4 且 peer 声明未被改写；② `@vitejs/plugin-react` 的 **peer** 上下文确实落到 7.3.7（peer 边被 override 会改写锁中声明，不能假定）；③ 7.3.7 满足本仓 `minimumReleaseAge`（以 pnpm 策略检查为准）。任一不成立则 vite high 只能走 `security/advisory-acceptances.json` 的签署接受（90 天上限/审批人/到期/可达性论证），属**另一次受审变更**，不并入本批次。react-router 与 elliptic 本批次无可修项。

## vite 定向试验（**历史记录**：当时进行中；**该结论已被下节正式切片取代**）

> **〔2026-10-24 订正〕** 本节记录的是 **2026-10-24 00:41-00:50 那一刻**的试验
> 中间状态，**不是当前状态**。此后正式 vite 定向切片**已落地**（同日的
> 正式 override + 锁 + 治理 doc 三文件），并由独立复核给出
> **accept-with-gaps**；见下一节 **"vite 定向补丁（正式切片已落地…）"**。
> 本节正文**保留原样**作为历史过程记录，其中的两处**错误推断**已在下方
> 就地标注订正，**不改写历史结论、不删除原文**。

本轮另有受派代理在 **`.cache/vite-targeted-trial` 做隔离的定向 vite 试验**。**时序说明**：本记录者第一次只读核对（00:41-00:45）时该目录**尚不存在**；试验于 **00:46 起**建立并推进到 00:50，因此以下是该试验**当时进行中的中间状态**，**不是结论**。

**试验做法（隔离）**：在 `.cache/vite-targeted-trial/` 内建 `baseline / control / trial` 三份工作区副本，**只跑 `pnpm install --lockfile-only --ignore-scripts`**（脚本自述：不安装、不构建、不起服务、不碰数据库、不放宽任何供应链旋钮）。`trial` 副本的 workspace override **只加一条**父级选择器 `"@umijs/bundler-vite>vite": 7.3.7`（注释明确写 "ISOLATED TRIAL ONLY (not the formal repository config)"）；**仓库正式 `pnpm-workspace.yaml` 未被该试验改动**。

**中间结果（【vite 试验代理亲跑】，留存 `.cache/vite-targeted-trial/`）**：`control-vs-official.lock.diff` **0 行** ⇒ 对照组**逐字节复现**正式锁图；`trial-vs-control.lock.diff` **65 行** ⇒ 只动 `vite@7.3.6 → vite@7.3.7` 与随动的 `@vitejs/plugin-react` peer 上下文。验收断言 **8/8 通过**（`out/acceptance-checks.json`、`logs/04-acceptance-checks.log`）：A1 vite 版本集 7.3.6→7.3.7 且 **8.3.4 保留**；A2 vitest 5.0.5 的 vite 边仍解析到 **8.3.4**、vitest snapshot 键完全相同；A3 `vitest@5.0.5` 的 `peerDependencies` 逐字节未变（`vite: "^6.4.0 || ^7.0.0 || ^8.0.0"`）；A4 `@vitejs/plugin-react@5.2.0` 的 peer **范围**逐字节未变（`vite: "^4.2.0 || ^5.0.0 || ^6.0.0 || ^7.0.0 || ^8.0.0"`）；A5 除 vite 外无任何包改变解析版本集；A6 **14 个 importer 块逐字节相同**（无 manifest/依赖改动）；A7 锁的 settings 与 catalogs 逐字节相同；A8 overrides 增量**恰好一条**父>子选择器、无删改。治理门禁评估（`out/governance-gate-evaluation.json`）：**control `passed=false`**（vite high `GHSA-587h-7wmj-h5pm` 未接受 + `braces` stale 接受项）；**trial `passed=false`**（只剩 `braces` stale 接受项，vite high 在该评估里**不再出现**）⇒ 定向 override 命中了 vite high，但**门禁仍因既有的 stale `braces` 接受项而红**。

**必须随结论一起带出的限定（本记录者只读核对所见；①② 已于 2026-10-24 就地订正）**：① 试验的 registry 是 **`https://registry.npmmirror.com/`**（用于依赖**解析/安装**），D1 官方审计用 `https://registry.npmjs.org/`（用于**漏洞审计**）——**〔2026-10-24 订正〕二者用途不同；registry 不同源本身**不足以否定审计结果**。原表述把"不同源"当作削弱审计结论的理由，属口径错误，正式切片的 audit 即以 `--registry https://registry.npmjs.org/` 执行**；② 试验日志打印 `effective minimumReleaseAge=undefined` ——**〔2026-10-24 订正〕这**不能**推出"release-age 策略在该隔离上下文未生效"**。`undefined` 只说明**该次 `pnpm config get` 没有报告这个键**，**不排除**存在默认值，也不排除策略实际在跑：**同一份试验日志**紧接着就打印了 `✓ Lockfile passes supply-chain policies (1880 entries in 13.4s)`，说明 pnpm 的供应链策略校验**在跑且通过**。**具体窗口天数仍为 unknown**（该键在复核侧不可读的 `.npmrc` 内），不得臆测天数；③ 试验只做 `--lockfile-only`，**未安装、未构建、未跑测试**，故"vite 7.3.7 真的能构建并通过回归"**未被证明**；④ 试验的 audit 视图似乎被脚本按范围收敛（control 的 `advisories` 只有 1 条，而其 `metadata.vulnerabilities` 合计为 8），**不得**据此宣称 8 条残余全部消失。

**结论（当时）**：**正式依赖图里的 vite 仍是 7.3.6，audit 的 vite high 仍未关闭，治理门禁仍红**。该试验**尚未获正式应用结论**：要落地仍需另行受审（正式 override 写入 + 独立分支试验锁三关复核 + `minimumReleaseAge` 生效验证 + 安装/构建/回归 + 治理 `braces` stale 接受项处置）。**不得**把该试验写成"已升级 vite"或"vite 已修复"。

> **〔2026-10-24 已被取代〕** 上面这段在记录当时是准确的，但**此后正式切片已落地**：
> 正式依赖图里的 vite 现为 **7.3.7**（`@umijs/bundler-vite>vite` 父级选择器），
> vite high 已消除，全严重度 audit 残留 **3 条（2 moderate + 1 low）**，治理门禁
> **仍红**（只剩既有的 stale `braces` 接受项）。**"vite 已升级"这句话仍然
> 不能照抄试验记录**——必须以正式切片的记录为准，见下一节。

## vite 定向补丁（**正式切片已落地**；独立复核 accept-with-gaps；治理门禁仍红；整体不可合并）

**〔2026-10-24 记录补齐 + 文档订正〕** 这一节取代上一节的试验中间状态。

**执行者分离（不要混用）**：正式 vite 切片的**实施**由受派子代理完成（留存
`.cache/vite-targeted-implementation/`）；**独立复核**由另一受派子代理完成
（严格只读，复算锁图 delta、audit 计数、门禁判定）；**本次文档订正会话**
（`.cache/vite-targeted-implementation/out/correction/`）只做**只读复核 + 文档/
证据口径订正**，**未跑任何测试、未安装、未联网、未连数据库、未起服务、
未做 Git 写**（`git status --porcelain` 前后同为 **94**，HEAD 仍 `01fc163a4`，
`security/advisory-acceptances.json` 逐字节未动）。

**正式落地了什么（唯一写范围 3 文件）**：`pnpm-workspace.yaml` 新增一条父级
override `"@umijs/bundler-vite>vite": 7.3.7`（父级**不含**版本限定；
`"@umijs/bundler-vite@4.7.24>vite"` 是被否掉的备选）；`pnpm-lock.yaml` 由
`pnpm install --lockfile-only` 重生（相对 D1 基线 **65 行** delta）；
`docs/ops/dependency-governance.md` 新增 "Targeted Vite patch" 整节。**未改
manifest / 源码 / pin，未签或移除任何风险接受，未切分支、未 commit、未 push。**

**锁图结论（本次订正会话独立复算，见 `out/correction/02-vite-edge-inventory.md`）**：
包图里 `vite` 解析边共 **4 条**，本切片**动了 2 条**（`@umijs/bundler-vite`
直接依赖边、`@vitejs/plugin-react` peer 上下文边，均 7.3.6 → **7.3.7**）；
`vitest` 与 `@vitest/mocker` 的 **8.3.4** 边**未动**，3 条 peer **范围**声明
逐字节未改，14 个 importer 逐字节未改，packages 1880→1880 / snapshots
1886→1886 / overrides 24→25（恰好新增 1 条）。
**〔订正〕** 实施侧记录曾写"只有 3 条边""只动了其中 1 条"——那与它自己表格里
**2 行** 7.3.6→7.3.7 自相矛盾；并曾断言"`@vitest/mocker` 没有独立的 vite 边"
——**不成立**（它有 `optionalDependencies: vite: 8.3.4(...)`）。旧试验报告的
"4 条边"计数反而是对的。

**门禁与审计（实施侧亲跑，独立复核复算）**：`pnpm install --lockfile-only`、
`--frozen-lockfile --ignore-scripts`、`pnpm dedupe --check`、
`pnpm audit --audit-level high`、`api-client typecheck`、`api-client check:contract`、
双站 `build:sites` 均 **exit 0**；`pnpm peers check` exit 1（既有 11 条，无一条
涉及 vite）。全严重度 audit **实际残留 3 条** = **2 moderate**（`react-router`
6.30.6：GHSA-wrjc-x8rr-h8h6、GHSA-337j-9hxr-rhxg）+ **1 low**
（`elliptic` 6.6.1：GHSA-848j-6mx2-7j84）；vite 的 5 条 advisory 全消。
**治理 `pnpm-audit` 门禁仍 FAIL**，唯一未接受项仍是**既有的** stale `braces`
接受项（`GHSA-vfj7-8cjw-p6xm`，`expires_on 2026-12-09`，`accepted_by
caoronglin`）。

**braces 失效条目的性质与状态（只读分类，未处置）**：按仓库自有
`load_advisory_acceptances` / `evaluate_advisory_report`
（`scripts/dependency_governance.py`）的语义，该条目是**匹配不到任何当前
finding 的接受记录**——删除它属于**注销**（清掉一条不再对应任何报告的记录），
**不是**新增一次风险许可，也不构成"接受新风险"。但它仍是
`security/advisory-acceptances.json` 里的**签署记录**，**删/续签/改范围需要
签署人决定**；本次**未做任何处置**，`acceptance` 内容**未改**，门禁**仍红**。

**构建能证 / 不能证**：双站构建 exit 0，日志明写 `[webpackbar] ℹ Compiling
Webpack` ⇒ 生产门户走 Umi 的 **webpack** bundler，`@umijs/bundler-vite` 在本仓
不被使用 ⇒ **vite 7.3.7 的运行时行为仍未被验证**；构建证明的是"锁变更未扰动
已发布的双站产物管线"。
**〔订正〕"四项产物检查全过"≠"新三 app 构建全绿"**：四项检查是 **web 侧**检查
（`check-production-artifact.sh` 只扫 `apps/web/dist/external`；
`check_artifact_headers.py` 只查 4 个文件；`check_artifact_build_paths.py` 与
`check_app_shell_assets.py` **只是引用** `apps/admin/dist` 与 `apps/jbrowse`
路径而**未重建**）。实测 `apps/admin/dist` 仍是 **2026-10-18 19:54** 的旧产物、
`apps/jbrowse/dist` **不存在** ⇒ admin 与 jbrowse 的重建**仍然欠账**。

**〔订正〕文档行数口径**：治理 doc 曾被记作 "+316"（实为 **diff 文件的 316
行**）与 "+281"（**不对**）。实测：vs `HEAD` **+287/−0**，其中 D1 批次占
**+108**（`.cache/d1-implementation/13-final-scope-check.log`），本切片占
**+179**（行数口径）。本切片**未留治理 doc 的字节级前置副本**（只有 sha256），
且**就地改写了 D1 已新增的两处句子** ⇒ **无法生成真正的单切片 doc diff，
也未伪造**；`out/final-governance-doc.diff` 标注为 **vs HEAD（不同基线）**。
锁文件有字节级基线副本，故 65 行锁 patch **是**单切片 diff。

**〔订正〕证据制品命名**：`out/artefact-hashes.sha256.txt` 实为**源文件**哈希
（workspace/lock/治理 doc），**未改名、未移动、未删除**；另加准确命名的
**source-only** 副本 `out/correction/source-only.post-correction.sha256.txt`。
新增 `out/correction/web-dist-current-read.sha256.txt`（143 个文件：external 72 +
internal 71）——它只证明**当前读到**的产物字节，**不是历史构建时点**的证明，
**不得**据此宣称"构建产物已验证"，也**不进入 docs**。

**独立复核结论**：**accept-with-gaps**（针对该切片本身）。
**不等于**整体验收通过、**不等于**可合并、**不等于**依赖目标完成。
**仍待用户/签署人决定**：① stale `braces` 接受项的注销或续签；
② `react-router` ×2 与 `elliptic` ×1 的后续（Umi 4 不支持 react-router 7）；
③ 前端**改 MiniMax 未获用户批准**（用户只批准了 nwafu 改 amd），前端双评审
未完成；④ F1b 的欠账（release 默认词表 vs facts 词表对齐、未知 assembly 的
空制品处置、**3 项 DB 回归未跑**、`0049` 迁移往返仍 skip）——**18 项无库测试
仍是 F1b 独立复核代理亲跑的 18 passed**，本会话未重跑、不得改记为他人亲跑。

## 最新复核（2026-10-23）

隐私修复仍在当前工作区；重跑专项58 passed（5个新增PG隐私测试、native2项均passed），完整API2589 passed /4 skipped。相比10-22额外skip的是0049临时库创建失败；只读排查PG时返回 `could not open file "global/2964": No such file or directory`。因此业务缺陷已修复，但本机PG环境不应判健康、迁移不能计通过，未擅自重建/修补/删除PG数据。Ruff/OpenAPI-client契约/diff-check通过；无新服务，临时服务端口已关闭。10-22真实HTTP/Redis证明仍是历史实测，本次未重跑完整部署链路；整个稳定性goal/生产上线仍未完成。见90-evidence顶部。

## F1 导出装配作用域收口 + 前端/依赖门禁（2026-10-23，记录补齐；不可合并、整体未完成）

本段**只补工作记录**：本轮未改代码/配置/依赖/数据库，未跑任何测试，未起服务，未做 Git 写。

**分支与基线（本轮只读核实）**：分支 `fix/fullstack-stabilization-20261020`，HEAD `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（未变）；`git status --porcelain` 共 90 项（64 已跟踪修改 + 26 未跟踪），dirty **全部保留，未提交、未 push、未合并**。基线 PR #26 本轮**亲自只读**查询远端：`state=OPEN`、`isDraft=true`、`mergedAt=null`、`baseRefName=main`、`headRefOid=57e2bcdee3bab3435578997dba85cf26c3b985bc` —— 仍是 Draft、**未合并**、head 仍是基线 SHA；`git branch --contains 57e2bcdee` 显示该 SHA 是 `baseline/workspace-20261020` 与 `origin/baseline/workspace-20261020` 的头，且是当前 HEAD 的祖先。

**F1 做了什么（我读真实代码核对，不只凭代理口述）**：`apps/api/app/api/v1/variants.py:116-141` 新增 `_export_assembly_scope()` —— 显式给出的 assembly 优先，否则用已解析 release 自己的 `assembly` 作用域（`apps/api/app/services/release_context.py:37`）；两者皆无则抛 `ValidationError`（`apps/api/app/core/exceptions.py:21,62-64` → 422）**拒绝**导出。POST `/variants/export`（`variants.py:276-293`）把解析结果同时写进**交给 worker 的 filters**（`filters["assembly"]`）与**持久化 export 记录的 `assembly_key`**（`apps/api/app/services/variant_export_service.py` 的 `create_record`）。worker 侧 `apps/worker/src/soymutdb_worker/tasks/export.py:106,124-133` 只有在 filters 带 `assembly` 时才追加 `v.assembly_key = :assembly` 约束——这正是**跨 assembly 混装路径**的关闭点：一条制品只可能来自一个命名空间。F1 落在 3 个文件：`apps/api/app/api/v1/variants.py`、`apps/api/tests/test_variant_exports.py`（4 项回归：release 默认作用域 / 空串视为未指定 / 显式 assembly 优先 / 两者皆无则拒绝，见 `:468,492,508,527`）、`apps/api/tests/test_release_bound_queries.py`（桩 DB 记录 `added`，断言命令 filters 与记录 `assembly_key` 同值、记录与 outbox 同事务）。**mtime 与 `find -newermt` 只作佐证**：它们显示 22:00 后源文件只改了这 3 个，但 `git diff` 范围本身**不足以独自证明"无漏收"**。

**验收结论**：独立复核 `ca386191` 给出 accept-with-gaps；**Lead 判定它只关闭了跨 assembly 混装这一条路径**，因此 F1 **不可合并**，整体**不完成**。

**证据来源分级（不要混用）**：
- **有留存日志**：`.cache/f1-api-suite-final.log` → API **2593 passed / 4 skipped**、exit 0。这是**实施代理执行**的结果，**不是我本轮亲跑**。4 个 skip = 3 个历史 ClickHouse driver skip + `test_variant_exports_migration.py:191`（临时库创建失败）。
- **只有代理报告、无留存日志**：146 passed / 1 skip、worker 29 项、pre/post 失败对照与 SQL 对照输出。`.cache/` 中命中的 "146 passed" 全部来自 2026-10-18 的 admin 前端旧日志，与本切片无关；`.cache/f1-export-scope-evidence.py` 只有脚本、**没有**输出日志，因此 pre/post 对照**不可复核**，不冒称可复现。
- **独立代理报告、同样不是我亲跑**：无库自证 helper 行为、OpenAPI 内存相等、ruff/diff check、collect 36。

**风险（未关闭）**：
1. 默认 `Release.assembly` 是 `String(128)` 自由文本（`apps/api/app/models/content.py:71`），与 facts 的 `assembly_key` 词表（name/version 形态）若不匹配，会产出**零行空制品**且状态 succeeded —— "成功但无数据"。
2. `variant_exports.assembly_key` 是 `String(64)`（`apps/api/app/models/variant_export.py:84`），而 `VariantExportFilters.assembly` **未限长度**（`apps/api/app/schemas/variant.py:98`）：输入超 64 字符会触发 DB 写失败 → 500。
3. 未知/拼错 assembly 同样走成功路径 → 空制品，不会 422/404。
4. 新增"无法解析 assembly"的 422 走 SoyMutDB 错误信封（`error_code=validation_error`），但 OpenAPI 中 422 只声明 FastAPI 的 `HTTPValidationError` 形态，**新契约描述缺失**。
5. `0049` 迁移往返测试**仍 skip**；手工往返**不替代**迁移测试门禁。
6. 本机 PG 16.15 ≠ CI PG 18；PR #26 的 17 个 CI job 因账户计费**从未启动**（`15-baseline-verification.md` §5），GitHub 侧当前不能当门禁。
7. 仍**没有**完整 broker / S3 下载 / 浏览器 / 双站制品证据。

**过程偏差（如实记录）**：实施代理两次 API 全量（2588 passed/9 skipped → 2593 passed/4 skipped）**超出限定范围**；在这台已损坏的 PG（`could not open file "global/2964"`，见 90-evidence 顶部 2026-10-23 节）上创建过临时库，证据脚本执行过 `DELETE`，`soymutdb_f1_scratch` **无法清理**。**不再连接、不再操作该 PG，也不尝试清理或修复**；该实例的清理/修复留给有授权的运维。

**前端门禁**：nwafu 两项失败、amd UIUX 两项失败、amd 功能一项失败，**均无有效报告**（本轮未找到对应留存产物），既不能算已解决也不能算已定位。用户已批准 nwafu 改为 amd；**前端改 MiniMax 尚未获批**；前端**双评审未完成**。

**依赖**：依赖候选仍**未升级**；需拿到**当前安全公告/注册表证据**后再分批实施，本轮不启动安装。

## 匿名变异可见性泄漏修复记录（2026-10-22）

后续用户“那就修复好问题”已授权修复。公共facts列表/count/region/detail/动态原生聚合复用published release + release/name公开元数据EXISTS（不是surrogate主键）；规范化summary用真实FK+同release规则；相邻dashboard品系/表型、homepage品系/seed、mutagens计数同类过滤已补齐。admin角色检查后全量统计显式保留。公共缓存加入public-v2，真实Redis旧键投毒未污染修复后响应。

专项58 passed（含新增5项隐私/metadata PG测试、native migration2项），完整API **2590 passed / 3历史CH skips**，修改文件Ruff/OpenAPI-client契约/diff-check通过；当前匿名真实TCP（原迁移chain库）验证v4仅1001/1002、私有/草稿detail404、v5正确、type/density2与缓存隔离。两个默认模型独立只读审查无阻塞；MiniMax路由失败不计审查通过。旧性能夹具跨release归属不一致已修正、旧缓存精确断言更新，未削弱隐私门禁。双站是既有未改frontend demo制品重扫，不冒充本轮新build/生产E2E。

这个已确认的原生读取泄漏阻塞项已关闭，不等于全站上线批准。已发布Release.variant_count等声明元信息仍是另一统计契约，未宣称等于过滤后facts；本轮未重跑Chromium/Worker-MinIO下载，也未覆盖完整双站授权矩阵或生产部署。临时API/Redis已停、PG与测试数据保留；源码未提交/未合并。完整证据/命令与置信B边界见90-evidence顶部。正式依赖升级、完整发布制品等原goal仍未完成。

## 部署演练结论（修复前历史；2026-10-22，非上线批准）

真实PG16/Redis/Celery/uvicorn/MinIO2025与Chromium门户链路已跑通：登录、202导出提交、后台outbox派发、PG终态succeeded、按需签名下载；最终浏览器6检查点exit0，gzip334bytes解压含2条预期行，无排除行。下载内容是通过真实按钮取得URL后用Playwright APIRequestContext校验，不冒充浏览器原生下载落盘；退出登录中途场景仍未测。此前说MinIO不接受SigV2是错误判断，真实MinIO实验SigV2/SigV4均HTTP200；对象路径桶名+exports前缀一致，未改签名/对象键代码。

修复验证脚本新建行返回None导致新库崩溃，新增2项helper回归通过，Ruff/diff-check通过；两个MiniMax复核失败不计通过。**新确认的上线阻塞：匿名variants列表包含is_public=false品系的变异1003，导出却正确排除；列表/detail/计数同类可见性需后续修复审查。** 专用测试数据与证据见90-evidence顶部，不能宣布隐私门禁通过。

演练结束已停止API8010、preview8090、Redis56389、moto59000、MinIO59010/59011与Worker；TCP逐端口确认关闭，既有PG55432仍应答。保留专用测试库与scratch产物（gitignored），未提交/合并/发布。preview本来固定监听0.0.0.0，故不留带已知测试凭据的对外demo入口。下方Round12为部署演练前历史结论，新证据仅替代其已覆盖部分；正式依赖升级及完整发布制品仍未完成。

## Round12 当前验收汇总（未完成）

新鲜API2584/4 skipped，Worker+jobs773/33 skipped，MCP66通过；根JS11/11（10 cached，web实际55files/456tests），lint12/12（9 cached），typecheck13/13（8 cached），Ruff生产app/修改文件、OpenAPI契约/visibility、locale、architecture/worker package/query keys/admin架构/任务registry25及diff-check通过。门户双站demo制品与隔离证据见round11，本轮require-dual headers4通过。

**不能mark complete**：真实browser/cookie/broker/S3闭环、完整JBrowse/Pages/发布制品与正式依赖升级均未交付；状态GET404/网络错误的恢复提示仍待审查。无新安装/服务/Git写入；goal保持active，轮次耗尽不冒充完成/阻塞。精确命令/缓存与证据边界见90-evidence顶部round12。

## 各切片最新状态

### Task1 BLAST/JBrowse（代码已实现并通过两遍独立复核返修）

BLAST门户/shared client已修：补API已有job release_id/assembly_name声明（normalizer本来保留，并非runtime丢字段），去掉页面局部类型旁路；按点击用job release显式header解析唯一assembly id与精确gene record，核对返回assembly/基因名/有效区间，生成真实chr:start-end。无AA坐标/删后缀猜映射/列表N+1/当前数据库替代旧作业；无映射清晰失败，loading/error可再点恢复，离页取消晚到导航。同tab进/browser避免异步popup blocker。Gene search只在job release与当前pin一致时可用。client31files/196tests、门户当时52files/433tests，两包类型/Lint、OpenAPI+route visibility、locale parity/diffcheck通过；备用独立复核9c3670ab无具体范围内发现（MiniMax36438964失败不能当审查通过）。

JBrowse先修加载前init丢payload/用旧config筛新tracks：纯bridge-init owner保存release/assembly/tracks/locus，scope/track变化撤旧view，等正确config；scope变更未提供locus清旧坐标，config返回name核对。63项初版通过后，MiniMax9af7e48a发现真实集成问题，主代理已核实并返修，不能以63测试反驳runtime契约：
- navToSearchString需完整live Assembly OBJECT，不能给名称；现由session.assemblyManager.waitForAssembly取得对象；坐标用原生navToLocString，负责1→0与跨染色体。只把visibleLocString写坐标状态/URL，不写gene输入。
- 撤销本批自行引入的[]清空bridge语义：兼容bridge-v1旧portal []表示无指定；同scope省略/[]保留选择，跨scope省略/[]用undefined哨兵选择目标defaults。portal不再合成[]。相同track集合顺序/重复不重建。
- config owner defaultTrackIds选目标真实reference+首个Feature+首个Variant IDs；App和config defaultSession共用，不再把gene_models/variants_v4别名当API ID。缺类型如实少轨道，不伪造3。
- 原view.subscribeToViewState不存在，改用已声明MobX reaction（scope guard+cleanup）同步真实viewport/tracks；导航失败用安全双语提示、保留live view。
- portal mirror增加release，同坐标release-only URL变化也发init；viewport带可选release，portal拒绝旧release晚事件，native assembly/track-only变化写URL；兼容旧无release消息。timer view/locus未就绪不发消息。
- “在新标签页打开”改取实时search，不再指向iframe初始session；iframe自身仍保持初始src，live更新走bridge（最终完整web53files/438tests与质量门禁已通过）。

返修后：JBrowse **67 tests passed**、tsc/lint/locale parity/diffcheck全部通过（最终timer guard后bash-103e951791244226已收集）；portal iframe组件新5项通过（缺/显式tracks、release-only init、旧release拒绝、native assembly/track URL），完整门户 **53files/438tests** +tsc/lint/locale parity通过（bash-ee61bf7f1f8f48c3已收集）。

**第二遍独立复核返修（F1–F4，已落地并复测）**：

- **F1**：本机 `@jbrowse/plugin-linear-genome-view@2.18.0` 源码确认 viewport 属性是**复数** `visibleLocStrings`（`esm/LinearGenomeView/model.js:34-46,759`，返回空格连接的字符串），单数 `visibleLocString` 从未存在；`bridge-init.ts`/`App.tsx`/测试桩已统一改为复数，并新增“对着已安装包 `dist/LinearGenomeView/model.d.ts` 断言”的契约测试，防止再次用自写桩掩盖属性名错误。
- **F2**：跨发布携带旧坐标/旧轨道 → 门户 `postInit` 改用 `scopeSafeInitPayload`（作用域变化且值与 iframe 当前所示相同时不下发），JBrowse 侧 `planPortalInit` 继续丢弃继承坐标，并在请求轨道于目标 config 解析为空时回落目标默认轨道（不再出现零轨道浏览器）。
- **F3**：API 轨道列表无 `ORDER BY`，`defaultTrackIds` 改为按 `trackId` 排序后选取，并优先 release 自身标注的 gene/annotation 与 variant 轨道；新增顺序无关回归。
- **F4**：新增单调 `scopeEpoch`（门户按 release/assembly 作用域变化自增并下发，JBrowse 回显到 `locus-change`），门户据此拒绝晚到事件，4→9→4 循环不再重新接受旧事件；release 字段保留为老消息兜底。
- 同链修掉两处真实缺陷：门户 locus 默认值由硬编码 `"chr01"` 改为空串、`buildJbrowseUrl` 无坐标时不下发 locus；JBrowse 手工导航改用 `parseLocusList`，多区域 viewport 不再被误判为 gene 查询。
- 复测：JBrowse **71 tests passed** +tsc/lint（bash-28af193fe0084516）；门户完整 **53files/441tests** +web tsc/lint +locale parity +diff-check 整条 **exit 0**（bash-fafd7984fe2a42ac）。

验证边界：native owner模块与真实portal React iframe消息事件（JSDOM），不是JBrowse React effect/真实FASTA/TRIX/BAM/iframe浏览器验收。E2E spec已更新，但 `pnpm --dir e2e ... --list` 被自动verify-deps安装/只读store sandbox拒绝，exit1/0tests不能算通过；未绕过、未安装或启动服务。

### Task2 变异公开身份/导出筛选

既有未提交实现保留，前序定向API67/Worker15、ruff/OpenAPI同步通过；本阶段未重跑这些后端切片。全线验收前重跑；尚无variant_exports持久模型。

### Task3 全局搜索

五类筛选、URL游标next/prev/深链回首页、q/types/assembly/release/limit变化首render拒旧cursor；resetCursor覆盖URL异步重置竞态。内部目录不伪造分页，独立子工具不被父search release effect导航走。最终审查785cc6c7无具体发现，包含于后续门户全套结果。未做真实API游标/浏览器验收。

### Task4 株系与新闻预览

株系：兼容q/offset与exact mutagen/裸数组/公开身份/release，50+1探测URL分页/重试/发布变化重置。API22含123条PG16分页、页面6/client3及两包类型/Lint、OpenAPI同步通过，独立复核a2c8b45f无发现。未PG18/双站/E2E。

新闻：原config取消VITE_PUBLIC_URL的base/admin-origin猜测；shared校验origin后保留显式门户base path，缺/无效配置提示、禁copy/open、不mint；HTML /news而非API JSONurl，token绑定articleId+slug，旧响应取消，等价props不重发。MiniMaxdbff3241发现子路径/残留loading后已返修；最终admin **33files/224tests**、tsc/lint/diffcheck通过。非localhost HTTP门户仍安全拒绝，LAN opt-in、clipboard文案等遗留见90-evidence，未浏览器/制品验收。

### Task5 变体导出持久化与所有者可见状态（实现中，收口结论已重新打开）

**Round11 整合回归增量**：新增真实SessionProvider/QueryClient整合测试5项，覆盖实际provider登出/失效同id、切换账号新id、旧缓存无observer、focus/active失效不再读取、在途状态/POST/下载隔离及错误清除。网络/auth传输仍mock；不是cookie/browser链路。focused5及门户全套 **55 files/456 passed**（104s）、tsc/lint通过。双站门户demo制品重建/隔离脚本exit0（各28文档；`.validation/round11-site-variant-artifacts.log`），双站headers与实际内部配置host隔离额外检查通过；snapshot/release manifest跳过，非生产发布/浏览器水合/JBrowse完整制品证明。MiniMax测试证据复核55666395无阻塞项；已收窄“错误隐藏≠内部状态清空”的表述，并补旧缓存晚响应和B key无数据断言，focused5/tsc/lint再次通过（产品运行时代码不变）。

**2026-10-22 最新批准与实现**：用户选择过期running安全失败、不自动重算，已替换export resume/CAS续租为受状态+观察时间戳保护的 failed 更新；任务expired只跳过、不执行。原执行晚成功不能覆盖failed；无重投不自动超时、旧进程可能留下未发布对象的边界明确保留。Worker+jobs-py **773 passed/33 skipped**，API导出/真实迁移18通过，Ruff/diff-check通过。过期政策MiniMax只读复核50e6e422未发现阻塞项，强调固定1h无heartbeat的健康长任务也可能安全失败；UI归属4fa0ecbf所审范围无阻塞项，但未读mock框架/JSX，React Query真实语义与Provider/browser整合未验证；完整broker/S3/browser与制品、正式依赖批次未完成。以下各时点记录为历史过程，不得覆盖本段新政策。

**20:33 后续复验优先结论**：旧租约 UPDATE 只按 running 状态保护并不互斥，真实 Barrier 双线程测试复现两次 resume；已补观察时间戳 CAS（含 NULL）与 3 项真实并发回归，Worker 全套 **663 passed / 33 skipped**。仍未实现超租约执行的 attempt fencing，错误字符串裁剪也不等于 SQL/参数脱敏；M2 与完整 M7 链路证据不能称完成。下方早期“全部修复/收口”表述仅为历史记录，已被本段与 90-evidence 顶部纠正。

**20:45 M2 增量**：共享固定公开错误消息已替代字符过滤；Worker 仅存公开消息，API 同样隐藏旧记录的原始诊断。API 全套 2584/4 skipped，Worker 663/33 skipped，共享 jobs-py 107 passed，Ruff 通过。MiniMax 只读复核 da9fd4d2-fbfe-4c68-96e8-3e3797b42b85 未发现补丁阻塞项，O2/O3 已采纳（删除无用异常参数辅助、增加原始异常日志 caplog 断言）；返修后 Worker + jobs-py 合跑 770 passed / 33 skipped。未解决 attempt fencing 与完整链路验收，不标 Task5/整体完成。

**Round9 L5 再修**：退出/过期不改变 sessionId，旧监听不足；且异步提交与下载缺少归属失效检查。渲染层复现5失败，现已改为 sessionId+status 清理、请求版本校验与卸载失效。focused10通过，门户全套54/450（追加unmount参数项前），tsc/lint通过；最新全套54 files/451 passed（100.23s，`.validation/export-session-web-tests-final.log`）。MiniMax只读复核8b240dcd与续派7726c1af均执行失败、未形成结论；独立复核仍待完成，不计通过。

**Round10 M7 增量**：Worker PG 测试现改为真正执行0049迁移（仅users前置表最小化），反射枚举/非空/默认值并跑真实并发认领和终态更新；focused14、Worker+jobs-py全套771 passed/33 skipped（664+107），Ruff/diff-check通过。不是完整broker/S3链路，不掩盖超租约执行竞态。

Task6：用户已授权最小安全批次；普通解析被沙箱拒绝，首次原命令提权获准后发现 Vite 范围 override 改写宽 peer 的兼容风险，未采纳锁图；父依赖限定方案的再次原命令提权被拒，已停止。正式配置/锁已撤回且逐字节/差异校验通过，未安装、未交付安全升级。旧 scratch audit（11→5）不代表当前正式依赖已修复。此前 root JS 11/11 与门户双站 build 通过，但 JBrowse/完整 Pages 构建未通过，不能称全线验收完成。**〔2026-10-24 订正：本段"未安装、未交付安全升级"已被 D1 批次取代 —— D1 已在 workspace/lock/治理doc 三文件内交付 follow-redirects 1.16.1 与 hono 4.13.11，audit 11→8、新增 0；但 vite high 未关闭、治理 gate 仍 FAIL 2 条、frozen/dedupe 绿不等于仓库仍可构建 ⇒ **依赖目标仍未完成**。详见本文件顶部 D1 节。〕**

- **已落地**：PostgreSQL `variant_exports`（owner/status/release_key/assembly_key/format/compress/filters/artifact_path/expiry…）+ 迁移 `0049`（可回退）；POST 响应体不变且**记录与 outbox 事件同事务**落库；新增 `GET /variants/export/{export_id}`（状态）与 `GET /variants/export/{export_id}/download`（**按需**现签，900 秒）；仅**本人或管理员**可读，他人导出按 404（不泄露存在性），viewer 403，未就绪 409，过期 404，不把 UUID 当授权；7 天产物保留（Worker 与 API 常量一致）；制品对象键/文件名由 `packages/jobs-py` 的 `export_artifact` **唯一拥有**；Worker 先认领再执行，失败落终态且**不自动重跑**，任务结果不再携带 24 小时预签名 URL。
- **重试预算核实**：导出任务无 `autoretry_for/self.retry`（仅 email 任务有 `max_retries=3`）；`outbox_max_attempts=5` 是**投递**预算而非执行重试，任务异常不会让 outbox 重投。失败是终态，用户恢复入口是门户“重新导出”显式动作。
- **门户衔接**：api-client 新增 `getVariantExportStatus/getVariantExportDownload`（类型改由生成的 OpenAPI schema 派生），`queryKeys.variants.export(exportId, sessionId)`，变体页提交后轮询状态、就绪出下载按钮、失败显示原因，会话切换即丢弃上一账号的导出，i18n `variants.export*` en/zh 对齐；OpenAPI 快照与生成类型由既有生成链重出（新增 2 路径/2 schema），`check:contract` PASS、route-visibility 无漂移。
- **独立复核（只读子代理 `6db2603a-199c-4934-9581-c1cd37275801`）已逐条答复**：CRITICAL 无；H1 导入遮蔽（改为 API/Worker 无条件优先仓库源码，**不安装**）、H2 重复投递重跑（改为 3600 秒租约 + 受保护 UPDATE 接管，docstring 按实际保证重写）、H3 无记录被静默跳过（改为 `ExportRecordMissingError` 显式失败）——三项 HIGH 全部修复；M1 `private, no-store`+`Vary`、M2 双端错误文本裁剪、M5 `assembly_key` 取请求装配、M7 真实 PostgreSQL 认领测试与“API 签的正是 Worker 的键”断言——均已修复；M3/M4/M6（404 分歧、filters 存株系名、release_key 裸数字主键）与 L7（`create_constraint` 空操作）**只记录不扩范围**；L1–L6 全部修复。逐条依据与证据见 90-evidence 顶部“独立复核逐条答复”节。
- **测试与门禁（返修后重跑）**：API **2584 passed / 4 skipped**；Worker **660 passed / 33 skipped**（本轮把 `SOYMUTDB_NATIVE_TEST_DATABASE_URL` 指向专用 PG16 库，既有 native PG 用例与新增 10 项导出认领用例**真正跑在 PostgreSQL 上**，此前是 skip）；MCP **66 passed**（需先清掉沙箱 `no_proxy=[::1]` 等代理变量，否则 httpx 解析失败使被测服务起不来——环境变量问题，非代码缺陷）；jobs-py 99；门户 **54 files / 445 tests**、api-client 31 files/198、query-keys 12；根 `pnpm lint --concurrency=1` 12/12、`pnpm typecheck --concurrency=1` 13/13 exit 0；`check:contract` PASS、locale 键对齐通过、治理脚本（architecture / worker test package / web query keys / workspace exports / deprecated api usage）与 `git diff --check` 通过；`apps/api` 内 `ruff check app`（CI 阻塞范围）All checks passed。
- **连带修正（不弱化断言）**：`test_release_bound_queries.py` 补传 `current_user` 并**加强**“记录与事件同事务”断言；`test_variant_mutant_identity.py` 的 `export_caller` 改为**真实 researcher 用户**（导出记录有 users 外键）；`test_security_round2_boundaries.py` 的泄漏断言把内部键固定为 `987654321`（原先对自动整型键做子串匹配，键为 `1` 时会命中时间戳，是假阳性）；`packages/api-client/scripts/{generate,check}-api-client.sh` 不再覆盖调用者 PYTHONPATH；`scripts/check-worker-task-registry.py` 补录**基线既有**漏登记的两个任务（`native_retention.cleanup`、`page_builder_publish.publish_definition`，二者早已在 worker include 列表却从未进期望集合，会卡住发布镜像构建），复跑 **25 tasks OK**。
- **证据边界**：无真实 MinIO 端到端下载（签名器打桩）、无 Celery broker 真实投递、无浏览器 E2E、无双站制品；导出认领语义已在真实 PostgreSQL 验证，但“真实 worker 进程 + 真实 broker + 真实 S3”的链路仍未覆盖。
- **F1 导出装配作用域（2026-10-23）**：本切片只关闭“导出制品跨 assembly 混装”一条路径；实现/证据/风险/偏差见本文件顶部 2026-10-23 新增节与 90-evidence 同名节。**未合并、不可合并、整体未完成。**

### Task6 / 全线验收

Task6未安装/升级：兼容候选turbo/router/postcss、安全公告/工具链偏差见90-evidence及前序记录。manifest/lock主代理独占，安装仍须明确授权，不绕过sandbox。全线API/Worker/MCP、JS全套、双站制品、浏览器/权限负例、治理与依赖门禁还未完成，局部绿不等于全线交付。**〔2026-10-24 订正：D1 已交付最小安全批次（fr 1.16.1 / hono 4.13.11，三文件），但 **vite high 未关闭、治理 gate 仍 FAIL、全仓 lint/test/双站构建未跑**，故 Task6 状态 = **部分交付、仍未完成**。详见本文件顶部 D1 节。〕**

## 当前运行/续接优先级

- **Task1 收口**：两遍独立复核的具体发现已全部核实并返修，最终证据为 JBrowse **71 tests**（bash-28af193fe0084516）与门户 **53files/441tests** +全部质量门禁 exit 0（bash-fafd7984fe2a42ac）。
- **Task5 收口**：已批准范围已实现，**独立复核的 H1–H3/M1–M7/L1–L7 已逐条答复并返修**（HIGH 三项全部修复，M3/M4/M6 与 L7 只记录不扩范围）；返修后本机全量门禁（API 2584/Worker 660(含真实 PG 认领用例)/MCP 66/门户 54files-445tests/api-client 31-198/query-keys 12/根 lint+typecheck exit 0/契约与 locale 门禁通过/治理脚本通过/迁移真实往返通过），证据见 90-evidence 顶部“独立复核逐条答复”节。
- **Task5/F1 导出装配作用域（2026-10-23，未合并）**：跨 assembly 混装路径**已关闭**（显式或 release 默认 assembly 同时写入 filters 与记录，两者皆无则 422 拒绝），独立复核 `ca386191` = accept-with-gaps，**Lead 判定仅关闭这一条路径 ⇒ 不可合并、整体不完成**。证据与风险见本文件 2026-10-23 新增节与 90-evidence 同名节。
- **Task5/F1b assembly 长度上限 + 422 契约（2026-10-24，单切片可接受，整体不可合并）**：有效 assembly **≤64** 才放行，超长 → 干净 **422**（不截断）；路由 422 声明 `ValidationErrorResponse`；新增 18 项无库测试（**复核侧亲跑 18 passed**）；契约/ruff exit 0；两种真实 422 handler 输出**符合已声明 schema**。**未关闭**：release 默认词表对齐、未知 assembly 空制品、**3 项 DB 回归未跑**、`0049` 迁移往返仍 skip。生成 `openapi.d.ts` 属**文件范围偏差**，但经独立判断是既有生成链的**必要同步、无破坏**。证据见本文件 2026-10-24 F1b 节与 90-evidence 同名节。
- **Task6/D1 依赖安全批次（2026-10-24，独立复核 accept-with-gaps，治理门禁仍红）**：`follow-redirects` **1.16.0→1.16.1**、`hono` **4.13.9→4.13.11**（同主版本 patch、无新增主版本），仅 3 文件（workspace override + lock + 治理doc）；frozen/dedupe exit 0、api-client typecheck exit 0、契约 exit 0 且 visibility PASS；**audit 11→8、新增 0，但 exit=1 保留**；**治理 `pnpm-audit` gate 仍 FAIL 2 条**（vite high 未接受 + 批次前既有的 `braces` stale 接受项）。**有效锁图口径 = 1880 packages / 1886 snapshots / 14 importers**（实施者日志抬头 1895/1901 是多文档相加，**口径订正、原日志不改**）。`ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK` 已独立判定为**内核 EROFS / 主机只读挂载**，非 sandbox policy denial；`XDG_RUNTIME_DIR` 旋钮**本仓 LOCAL-RUN-ENV 未记载 ⇒ 记为运行环境说明缺口，本切片不改 LOCAL-RUN-ENV**。
- **Task6/vite 定向切片（2026-10-24，独立复核 accept-with-gaps，治理门禁仍红；本轮补记 + 文档订正）**：`"@umijs/bundler-vite>vite": 7.3.7`（父级**不含**版本限定），仍只 3 文件（workspace override + lock + 治理doc）；锁由 pnpm 重生，相对 D1 基线 **65 行** delta；**vite 7.3.6 的 5 条 advisory 全消**，全严重度 audit 残留 **3 条 = 2 moderate（react-router 6.30.6 ×2）+ 1 low（elliptic 6.6.1）**，high **0**；**治理 `pnpm-audit` gate 仍 FAIL，唯一未接受项 = 既有的 stale `braces` 接受项**（注销/续签**待签署人决定**，本次未处置、`acceptance` 未改）。**〔订正〕锁图边数**：包图 `vite` 解析边 **4 条**、本切片**动了 2 条**（bundler 直接依赖 + plugin-react peer 上下文，均 7.3.6→7.3.7），`vitest`/`@vitest/mocker` 的 8.3.4 边未动、3 条 peer 范围声明逐字节未改（实施侧"只有 3 条边/只动了 1 条"与"`@vitest/mocker` 没有独立 vite 边"两句**均不成立**）。**〔订正〕文档行数**：vs HEAD **+287**（含 D1 的 **+108**）⇒ 本切片 **+179** 行；"+316"是 diff 文件行数、"+281"不对。**〔订正〕产物检查**：四项检查是 **web 侧**，`apps/admin/dist` 仍是 **2026-10-18** 旧产物、`apps/jbrowse/dist` **不存在** ⇒ **不等于新三 app 构建全绿**。**〔订正〕release-age 推断**："`effective minimumReleaseAge=undefined` ⇒ 策略未生效"是**错误推断**（`undefined` 不排除默认值；同一份试验日志随后即打印 `✓ Lockfile passes supply-chain policies (1880 entries)`；**具体窗口 unknown**）；**〔订正〕registry 口径**：安装镜像与官方审计 registry **用途不同**，**不足以否定审计**。**〔2026-10-24 晚间订正〕** 上段"唯一未接受项 = 既有的 stale `braces` 接受项（注销/续签待签署人决定，本次未处置）"**已被取代**：该 stale 接受项已按用户授权**注销**；上段"残留 3 条 = 2 moderate + 1 low、high 0"是**该时点**的 feed 事实 —— **2026-10-24 晚间新鲜 feed 已变为 8 条**（1 high `body-parser` + 4 moderate + 3 low，新增自 2026-10-23 晚间发布），`braces` 仍 0 条。
- **前端**：nwafu 两项、amd UIUX 两项、amd 功能一项失败**仍无有效报告**（本轮只读核对：`.validation/` 最新仍是 2026-10-23 21:59 的隐私日志，`.cache/` 最新是 00:50 的 vite 定向试验目录、属依赖试验而非前端产物，**未找到任何前端失败报告产物**）⇒ 既不能算已解决、也不能算已定位。用户已批准 nwafu→amd；**前端改 MiniMax 仍未获用户批准**；前端**双评审未完成**。状态 = 门禁未过，**前端工作未完成**，不能计入验收。**〔2026-10-24 晚间订正〕** 用户**已批准**前端改 MiniMax 的**双评审**，A/B **只读评审已启动**；上段"未获用户批准""双评审未完成"的**等待状态已结束**（原文保留不改写）。**双评审结论尚未回收** ⇒ 前端工作**仍未完成**、不能计入验收（上段该结论不变）。
- **下一步（按门禁顺序）**：1）**前端替代模型待用户确认**（未获批前不动前端模型路线）；2）**F1b 剩余收敛**：release 默认词表与 facts 词表对齐、未知 assembly 的空制品处置 —— **需要健康 PG 证据**，当前损坏实例禁止操作；3）**补跑 F1b 的 3 项 DB 回归**并解决 `0049` 迁移往返 skip（需授权的可用 PG 16/18 环境）；4）**vite high**：**〔2026-10-24 更新〕正式定向切片已落地并经独立复核 accept-with-gaps** —— `pnpm-workspace.yaml` 加 `"@umijs/bundler-vite>vite": 7.3.7`，锁由 pnpm 重生（65 行 delta），vite 7.3.6 的 5 条 advisory 全消，全严重度 audit 残留 **3 条（2 moderate + 1 low）**；**不接受全局 vite override**（会重写 vitest / `@vitejs/plugin-react` 的 peer 范围并把 vitest 的 8.3.4 降成 7.x）。**仍未关闭**：① vite 7.3.7 的**运行时**未证（双站构建走 Umi **webpack**，`@umijs/bundler-vite` 不被本仓使用）；② 治理 `pnpm-audit` gate **仍 FAIL**（只剩**既有的** stale `braces` 接受项，注销/续签**待签署人决定**，属另行受审变更）；③ workspace 全量 Vitest / lint / typecheck 与 `scripts/verify-frontend-artifacts.sh` 全量门禁未跑；④ **admin 与 jbrowse 未重建**（`apps/admin/dist` 仍是 **2026-10-18** 旧产物、`apps/jbrowse/dist` 不存在）⇒ **四项 web 侧产物检查全过 ≠ 新三 app 构建全绿**。**〔订正〕**此前写的"**`minimumReleaseAge` 在该上下文未生效**（`effective minimumReleaseAge=undefined`）"是**错误推断**——`undefined` 不排除默认值，且**同一份试验日志**随后即打印 `✓ Lockfile passes supply-chain policies (1880 entries)`；**具体窗口天数仍 unknown**（在不可读的 `.npmrc` 内）。**〔订正〕**"试验 registry 与官方审计不同源"也**不构成**否定审计的理由：镜像用于安装/解析、官方 registry 用于审计，**用途不同**；正式切片的 audit 即以 `--registry https://registry.npmjs.org/` 执行；5）**全线验收**（API/Worker/MCP 全量、JS 全套、双站制品、浏览器/权限负例、真实 broker/S3 下载、PG18 迁移）。**CI 侧基线 PR #26 的 17 个 job 因账户计费从未启动，GitHub 当前不能当门禁**；**本机损坏 PG 禁止再操作**（`could not open file "global/2964"`），清理/修复留给有授权的运维。整个 goal 保持 active：状态 `needs-verification`，**未合并、未提交、未 push，不宣称工程完成**。**〔2026-10-24 晚间订正〕** 第 1 项"前端替代模型待用户确认"**已获用户批准并启动 A/B 只读双评审**，不再阻塞于等待批准；第 4 项中"只剩既有的 stale `braces` 接受项，注销/续签待签署人决定"**已被"用户授权注销该 stale 接受项"取代** —— 门禁**仍红**，但原因换成**新出现的 `body-parser` high**（未签署接受项，属独立受审后续）。
