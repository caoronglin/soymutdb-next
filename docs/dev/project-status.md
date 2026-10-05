# SoyMutDB 项目状态（2026-10-01 实跑核对）

> 单一状态视图。执行日志见 `.ai-memory/`，逐项设计与计划见 `docs/superpowers/specs/` 与 `docs/aegis/plans/`，
> 整合视图见 `docs/3.9升级优化文档.md`。本页只回答「现在是什么状态」，且每一条都带本机实跑证据。
>
> **本版相对 2026-09-26 版的实质更正**：三个应用全部是 React 19 + Umi Max 4 + antd 6 + ProComponents v3；
> Vue 已完全退役（0 残留）；上版「三端均为 Vue 3」的表述已作废。旧计数与旧结论一律以本版为准。

> **2026-10-02 实施轮更正**（证据见 [`aegis/baseline/2026-10-02-w0-rebaseline.md` §8](../aegis/baseline/2026-10-02-w0-rebaseline.md)）：
> - 审计后方案 W0–W3 **已实施完成**：守卫维护、assembly 作用域与**运行时 release 切换**、
>   五态会话状态机（匿名零个人请求）、`/auth/me` 加法式 `effective_roles` 能力字段。
>   消融证据 14 组，全部「对照通过 → 单因素变异 → 真实路径翻转 → 恢复复跑」。
> - **既有红灯变化**：可见文案守卫 39 → **33** 个文件；`check:contract` **exit 1 → exit 0**；
>   侧栏整页刷新（第 3 条）已修。仍未消除：可见文案守卫仍 exit 1。
> - **撤回旧结论 3 条**（本轮实跑复核）：`check_web_query_keys.py` 的 9 条红是守卫正则假阳性而非源码缺陷；
>   前一轮 W2 改动**未通过 typecheck**（重复实现 + 残留未用变量）；未跟踪的 `navigation-render.test.tsx`
>   从未真正执行过，其暴露的 `<a href>` 才是真实漂移。
> - **本轮发现但未解决**：API 测试同命令两次结果不一致（21 errors vs 0），原因未查清，已登记不当作已完成。

> **2026-10-02 审计更正**（详见 [`design-audit-2026-10-02.md`](design-audit-2026-10-02.md)）：
> - 本页「已知红灯」第 6 条（`AGENTS.md` pnpm pin 漂移）**已修复**：`AGENTS.md:58,90` 已改为 `12.5.1`，与 `package.json` / `.cnb.yml` 一致。
> - 执行依据更新为 [审计后总方案](../aegis/plans/2026-10-02-audited-optimization-execution.md)：18 条硬约束、W0–W7 与逐阶段验收；
>   [新对话提示词](execute-audited-optimization-prompt.md) 已登记。本次只改文档，业务修复仍待实施。
>   `session.ts` 尚无业务调用，应先按现有认证协调层重设计；不是直接接线该布尔门控就结束。
> - 同日对 2026-10-02 的优化/消融设计草稿做了独立审计，撤回了三项结论：
>   「守卫未接 CI」（实为已通过 `ci-job-steps.sh` 间接接入）、「数据库 ≈100× 单因素加速」（非单因素、比较层级不一致）、
>   「9/9 GUARD-ACTIVE」（F9 所测模块尚未接线）。**本页原有的门禁数字与红灯清单不受影响**，
>   它们均在本轮实跑复现过。
> - 仍然成立的真实缺陷：`apps/jbrowse/Dockerfile:19` 引用已删除的 `packages/ui-vue`（镜像构建必失败）；
>   `check_admin_content_architecture.py` 扫描 gitignored 的 `.umi*/` 产生永久误报；
>   `check_web_query_keys.py` 扫描已空的 `apps/web/src/views/`（Vue 退役遗留）。
> - `apps/api` 消融 149 项与 `pytest scripts` 275 项本轮复跑仍全绿，**未受审计影响**。

## 一句话

技术栈迁移与 Vue 退役已完成并可复跑；**真实缺口集中在三处**——管理后台的 Pro 业务组件体系（6 个页面仍是裸 antd `Table`、
详情页无 `ProDescriptions`）、公共门户可见文案守卫为红（39 个文件）、以及后端若干 mock 测试未跟上 release fail-closed 契约。
本机质量门禁（前端逐包 + `scripts` 契约 275 项 + API 消融 149 项）全绿；后端全量 pytest 在本机会被 OOM kill，
没有可信的全量数字 —— 这本身就是一条待办。

## 技术栈现状（实跑）

| 应用 | 框架 | 单测 | typecheck |
| --- | --- | --- | --- |
| `apps/web` | React 19 + Umi Max 4 + antd 6 | **20 files / 99 tests** | exit 0 |
| `apps/admin` | 同上 + ProLayout | **6 files / 41 tests**（本轮 3/19 → 6/41） | exit 0 |
| `apps/jbrowse` | React + JBrowse 2 | 40 pass | exit 0 |
| `packages/api-client` | — | 27 files / 150 tests | — |
| 其他包 | genome-view 43 · genome-data 121 · genome-view-model 23 · shared 49 · charts 5 · query-keys 11 · i18n-core 10 | 全绿 | — |
| `scripts`（Python 契约） | — | **275 passed / 1 skipped** | — |
| `apps/api` 消融 | — | **16 files / 149 passed / 0 failed** | — |
| `apps/api` 全量 | — | **无法在本机跑完**：约 47% 处被 OOM kill（EXIT=137） | — |
| `apps/worker` | — | 本机 `multiprocessing` spawn 失败，未取得数字 | — |

环境：`Node 24.19.0`（符合 pin）、`pnpm 12.5.1`、`Python 3.14.6`；本机 cgroup 受限，任何构建/测试都必须
`GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1`，否则 turbo/vitest/rayon 因线程耗尽直接崩溃。

## 本轮修掉的真实缺陷（都是工作树里长期存在的契约漂移）

| 文件 | 症状 | 处理 |
| --- | --- | --- |
| `apps/api/tests/test_expression.py` | `/expression/*` 已按 release fail-closed 返回 503，测试仍断言旧的「空列表 200」→ 6 failed | 注入 `get_release_context`；另 3 处旧断言改为当前公开契约（`/libraries/{public_id}`、内部主键不再是 locator、cursor 为不透明签名串）→ **19 passed** |
| `apps/api/tests/test_gwas_api.py` | 路由新增 `response: Response` 后测试漏传 → 1 failed | 补参数 → **18 passed** |
| `apps/api/tests/conftest.py` | 复用的本地测试库在会话被强杀后残留角色行，之后每个会话都在 setup 报 `roles_name_key` 冲突（读起来像代码缺陷，其实不是） | 角色种子插入改 `on_conflict_do_nothing` |
| `apps/api/tests/test_ablation_sra_no_fabrication.py` | 3 个消融用例漏挂 `offline` fixture，实际去访问 NCBI；网络通时守卫反而失败 —— 一个「只在断网时才生效」的守卫不是守卫 | 补 fixture → **11 passed** |
| `packages/query-keys/src/query-keys.test.ts` | 联邦搜索已永久下线、`federated` 已从缓存键移除，测试仍断言该维度 | 按实现口径删断言 |
| `packages/charts/src/ChartFigure.tsx` + 测试 | 图表回退分支没把 description 暴露给辅助技术，测试却断言回退态根本不渲染的 `role="img"` | 回退分支补 visually-hidden description，测试改断言真实可达文本 |
| `scripts/check-vue-retirement.mjs`、`scripts/react-entry-graph.mjs` | 两个守卫都按**包名**把 `@soymutdb/genome-view` 判为 Vue，而该包已按设计重建为 React 渲染器且 `apps/web` 在用 → 自重建后一直红，没人再跑 | 从 denylist 移除该包名，改按**框架**判定；保留 `.vue` 与 `vue/@vue/*` import 扫描；两个守卫各做一次临时副本注入 `.vue` 的消融，均仍 exit 1 并指出文件 |

## 已知红灯（不是「待办的口头描述」，是当前可复现的状态）

| # | 红灯 | 证据 | 归属 |
| --- | --- | --- | --- |
| 1 | 可见文案守卫 exit 1，**22 个文件**（2026-10-02 由 39 降；analyses 模块与第二批 12 个文件已清零） | `node scripts/check_visible_i18n_react.mjs` | `docs/aegis/plans/2026-10-01-admin-pro-migration.md` A5 |
| 2 | 6 个 admin 页面仍是裸 antd `Table`；`ProDescriptions` 0 处、`ProCard` 0 处 | 逐项 grep | 同上 A2/A3 |
| 3 | ~~`ProLayout.menuItemRender` 用 `<a href>`，侧栏点击整页刷新~~ | `apps/admin/src/routes/__root.tsx` | ✅ **2026-10-02 已修**：改用 TanStack `<Link>`（该规范 §3.1 早已批准），`navigation-render.test.tsx` 组件级覆盖 + 消融翻转 |
| 4 | API 全量 pytest OOM（EXIT=137 @ ~47%） | 实跑 | 新增待办：分片或降内存跑法需写进 `scripts/verify-backend-tests.sh` |
| 5 | `Makefile:197` lint 目标指向不存在的 `apps/api/src`（代码在 `apps/api/app`） | 实读 | 工具链缺陷，等修 |
| 6 | ~~`AGENTS.md:58,90` 写 pnpm `11.21.0`，仓库实际 `12.5.1`~~ | 实读 | ✅ **2026-10-02 已修**：改为 `12.5.1` |
| 7 | 15 个 API 测试依赖 testcontainers，本机无 Docker | 实跑 | **SKIPPED ≠ PASS** |
| 8 | 随 Vue 退役丢失的契约覆盖：admin 会话（`lib/auth-context.tsx`）、web 动效可访问性（`lib/motion-*.ts`）、页面定义 href 安全校验 | 对比 Vue 树被删的三个测试文件 | 本轮已补两项（导航可达性、门面导出），会话与动效仍缺 |

## 已完成并留证（要点）

- **Vue 完全退役**：0 个 `.vue`；`packages/ui-vue`、`packages/genome-view`（Vue 版）已删；`scripts/check-vue-retirement.mjs` 常驻门禁；
  `scripts/check-react-entry-graph.mjs` 遍历三端实际发布入口的 import 闭包 PASS。
- **三项查询收口**：Gene ID / Physical Location 的 assembly 作用域隔离（深链不可判定不回退默认版本）、坐标安全整数校验、
  JBrowse 深链携带 `release`。
- **自研基因组视图**：`packages/genome-view` 以 React 重建，`renderGenomeViewSvg()` 纯函数保证预渲染与交互渲染不漂移；
  配套迁移 `0045_transcript_parts` + GFF3 结构导入（transcripts 80,374 / parts 716,349 / exons 563,838，与 GFF3 计数逐一对上）。
- **联邦搜索彻底下线**（API `app/search/` 整包删除 + 前端与客户端清理），`federated` 已退出缓存键。
- **消融测试体系**：API 侧 16 个文件 149 项全绿，覆盖身份边界、assembly/crosswalk、release 作用域、缓存键、快照、ClickHouse 投影。
- **本轮新增前端守卫**：内容管理 URL 真源功能测试、导航可达性消融、antd 门面导出完整性消融（补 `@ant-design/cli usage`
  解析不到 `@/lib/antd` 门面层的盲区）。

## 环境阻碍（影响所有门禁判定）

- **无 Docker**：testcontainers 用例必然 SKIPPED/ERROR，不计通过。
- **裸 `pnpm` 调用**：`apps/web/scripts/build-sites.ts` 内部调 `pnpm exec max build`，PATH 中的 pnpm 版本与状态不可靠；
  绕过方式是用 corepack 缓存里的真实 `pnpm.mjs` 做 shim（`.validation/bin/pnpm`）。不得改 pin 或全局包管理器状态。
- **registry 滞后**：`.npmrc` 指向 `registry.npmmirror.com`，其 `@tanstack/react-query` 最新仅 5.99.2，锁文件已锁 5.104.0；
  任何重新解析锁文件的操作必须临时 `--registry=https://registry.npmjs.org/`，`--frozen-lockfile` 不受影响。
- **本地测试库需为空**：复用的 `soymutdb_*` 库在被强杀的会话后会残留数据；本轮已把角色种子改为幂等，
  但整表残留仍需人工清理或换库。
- **可写隔离 Admin 环境缺失**：截图视觉验收、Admin save→公共渲染 E2E、响应式运行时检查全部 pending。

## 待决策（不自行拍板）

见 `docs/3.9升级优化文档.md` §11：`public_id` 正式格式、internal 检索角色名单、无 assembly 查询的 UX、
v4↔v5 映射展示规则、生产对象存储选择、主导航口径、Gene ID 单行 vs 批量、页脚导航初始 bounds 等。

## 复现

```bash
# 前端（逐包；本机比 turbo 稳）
export GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1
for p in @soymutdb/api-client @soymutdb/charts @soymutdb/genome-data @soymutdb/genome-view \
         @soymutdb/genome-view-model @soymutdb/i18n-core @soymutdb/query-keys @soymutdb/shared \
         @soymutdb/web @soymutdb/admin @soymutdb/jbrowse; do
  pnpm --filter "$p" run lint && pnpm --filter "$p" run typecheck && pnpm --filter "$p" run test
done

# 交付与平台契约
python3 -m pytest scripts -q
node scripts/check-react-entry-graph.mjs && node scripts/check-vue-retirement.mjs
node scripts/check_visible_i18n_react.mjs     # 当前 exit 1，见「已知红灯」第 1 条

# antd CLI（需要 HOME 可写）
HOME=$PWD/.validation/home ./node_modules/.bin/antd lint apps/admin/src
HOME=$PWD/.validation/home ./node_modules/.bin/antd info Table

# 后端（需要一个**空**的本地库；全量在本机会 OOM，建议分片）
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/<empty-db>' \
  .venv/bin/python -m pytest tests --ignore=tests/a0 -q
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/<empty-db>' \
  .venv/bin/python -m pytest tests/test_ablation_*.py -q     # 149 passed
```