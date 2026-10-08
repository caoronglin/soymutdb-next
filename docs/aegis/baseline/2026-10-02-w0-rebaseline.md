# W0 重新基线记录（2026-10-02 实施轮）

- 日期：2026-10-02。
- 状态：**W0 部分确认，恢复轮重新核实中**。此前完成声明缺少完整读集、浏览器和数据库前置核实，现撤回。
- 合同：[审计后全局优化执行方案](../plans/2026-10-02-audited-optimization-execution.md)（H-01–H-18、W0–W7）。
- 口径：按 [Baseline Governance](../BASELINE-GOVERNANCE.md) §2–§5 区分 Design Defect / Implementation Drift / missing-authority / needs-clarification。
- 证据等级按方案 H-16 分层：源码确认 > 基线通过 > 变异被杀 > 组件行为 > 端到端 > 部署态。本文每条结论都标层级；没有取到证据的一律写「未验证」。

## 1. 起始工作树

| 项 | 值 |
| --- | --- |
| HEAD | `9b63ddd416c86757d9a80b70e72cfeb785791de4` |
| 分支 | `main` |
| 已修改（未暂存） | `AGENTS.md`、`docs/ARCHIVE.md`、`docs/README.md`、`docs/aegis/INDEX.md`、`docs/dev/project-status.md` |
| 未跟踪 | `apps/web/src/ablation/`、`apps/web/src/lib/session.ts`、`docs/aegis/plans/2026-10-02-audited-optimization-execution.md`、`docs/dev/design-audit-2026-10-02.md`、`docs/dev/execute-audited-optimization-prompt.md` |

以上全部为**用户既有改动**，按 H-01 保留，不 stash / reset / clean / 覆盖。
其中 `apps/web/src/ablation/` 与 `apps/web/src/lib/session.ts` 按方案 §W0 作为**待审查输入**：既不静默删除，也不默认当作可靠基础（审查方向见 §5）。

## 2. 工具与环境可用性（实测）

| 组件 | 状态 | 证据 |
| --- | --- | --- |
| Node | 可用 `v24.19.0`（与 `.nvmrc` 一致） | `node -v` |
| pnpm | 可用 `12.5.1` | `pnpm -v` |
| Python | 可用 `3.14.6` | `python3 -V` |
| uv | 可用 `0.11.33` | `uv --version` |
| node_modules | 已安装（仓库根） | 目录存在 |
| apps/api/.venv、apps/worker/.venv | 存在 | 目录存在 |
| Docker | **不可用**（命令不存在） | `command -v docker` |
| psql / pg_isready | **不可用**（命令不存在） | `command -v psql` |
| pgcli | **不可用**（命令不存在） | `command -v pgcli` |
| ant CLI | **不可用**（命令不存在） | `command -v ant` |
| PostgreSQL 连接串 | **无** `DATABASE_URL` / `POSTGRES_*` 环境变量 | `env` |
| Python PG 驱动 | asyncpg 0.31.0、SQLAlchemy 2.0.52、testcontainers 可导入；psycopg 缺失非本 API 必需依赖 | API venv 实际 import，exit 0 |
| 浏览器二进制 | Chromium 151.0.7922.34 launch 成功，离线页面 title=W0；非门户 E2E | e2e 内 Playwright launch，exit 0 |

**结论**：当前 PATH 未找到 Docker/psql/pgcli/pg_isready；这不证明数据库服务不存在。尚未取得命名独立测试库可用证据，未启动会 create_all/drop_all 的测试 fixture，未连接未知库。Chromium launch 已验证；门户 E2E 待执行。ant CLI 还需核实仓库局部入口，不能仅依赖全局 command -v。

## 3. 现存红灯（本轮实跑，退出码为真实值）

| # | 命令 | exit | 结果 |
| --- | --- | --- | --- |
| G1 | `node scripts/check-vue-retirement.mjs` | 0 | React-only retirement: PASS |
| G2 | `node scripts/check-react-entry-graph.mjs` | 0 | web/admin/jbrowse 三个入口均 PASS |
| G3 | `bash scripts/check-dockerfile-copy.sh` | **1** | `apps/jbrowse/Dockerfile` → `packages/ui-vue/package.json` 源缺失 |
| G4 | `python3 scripts/check_web_query_keys.py` | 0 | **通过，但输出「0 assembly consumers」——守卫盲区，见 §4-A** |
| G5 | `python3 scripts/check_admin_content_architecture.py` | **1** | 3 条命中，见 §4-B |
| G6 | `python3 scripts/check_page_registry.py` | 0 | Page Builder registry 同步（19 keys） |

**既存红灯只有 G3 与 G5。** G4 的「绿灯」是**假绿**：它没能识别出任何 assembly 消费方，见 §4-A。

## 4. 链路绘制（沿当前源码，非文档转述）

### 4-A. assembly 查询作用域 —— Implementation Drift

后端（release 作用域为已确定契约）：

- `apps/api/app/api/v1/genes.py` 的 `GET /assemblies` 依赖 `get_release_context`，缓存键 `genes:assemblies:release:{release_id}`，loader 按 release 过滤。

前端（当前实测，与后端契约对立）：

- `packages/query-keys/src/index.ts` 的 `queryKeys.assemblies.list({releaseId, siteVariant})` / `.chromosomes(assemblyId, ctx)` —— 注释声明目录是 release + site 作用域。
- `apps/web/src/lib/query-options.ts:62` 的 `assembliesQueryOptions()` —— 键用 `queryKeys.assemblies.all()`（裸前缀），注释声明「assembly 是全局参考数据，不随 release / site 变」。两处注释**直接对立**。

实际消费方（本轮枚举，不沿用旧数字）：

| 位置 | 用法 |
| --- | --- |
| `apps/web/src/routes/search/genes.tsx:96` | `list({ releaseId: getReleaseId(), siteVariant })` |
| `apps/web/src/routes/search/location.tsx:87` | `list({ releaseId, siteVariant })` |
| `apps/web/src/routes/search/location.tsx:105` | `chromosomes(assemblyId, { releaseId, siteVariant })` |
| `apps/web/src/routes/search/gbrowse.tsx:29` | `list({ releaseId, siteVariant })` |
| `apps/web/src/routes/search/primer.tsx:65` | `list({ releaseId, siteVariant })` |
| `apps/web/src/routes/tools/seqfetch.tsx:62` | `list({ releaseId, siteVariant })` |

判定：`assembliesQueryOptions()` **零消费者**，六个消费点全部手写键数组。`check_web_query_keys.py` 输出「0 assembly consumers」，说明它只认工厂、不认手写调用 → **守卫盲区**（G4 假绿）。scope: architecture（实现漂移，非 missing-authority；后端契约已是权威）。

### 4-B. admin 架构守卫红灯（G5）—— 需分流

| 命中文件 | 判定方向 |
| --- | --- |
| `apps/admin/src/.umi/core/terminal.ts` | 生成目录，**误报**（应被过滤） |
| `apps/admin/src/.umi-production/core/terminal.ts` | 生成目录，**误报**（应被过滤） |
| `apps/admin/src/lib/antd-theme.ts` | 业务源码命中「touches web storage」，**需读源码判定**是主题偏好键还是真实凭据持久化 |

后两条与前两条性质不同，不得用同一手段处理，也不得靠扩大白名单抹平。

### 4-C. CI 两跳链 —— 审计 D-01 结论成立（守卫已间接接线）

```
.cnb.yml:126 / :204 / :720        bash scripts/ci-job-steps.sh run frontend
scripts/ci-job-steps.sh:278      bash scripts/verify-frontend-artifacts.sh
  verify-frontend-artifacts.sh:107  node scripts/check-react-entry-graph.mjs
  verify-frontend-artifacts.sh:108  node scripts/check-vue-retirement.mjs
  verify-frontend-artifacts.sh:111  python3 scripts/check_page_registry.py
  verify-frontend-artifacts.sh:114  python3 scripts/check_web_query_keys.py
  verify-frontend-artifacts.sh:117  python3 scripts/check_admin_content_architecture.py
scripts/ci-job-steps.sh:491      bash scripts/build-release-image.sh
  build-release-image.sh:101       bash scripts/check-dockerfile-copy.sh
```

结论：**守卫已通过共享脚本间接接入 CI**，P0-CI / K-4「零调用方」的前提不成立，本轮**不重复接线**、不把逻辑写进 job body。但「调用存在」不等于「运行曾成功」——本机无 CI 日志，历史运行状态**未验证**。

### 4-D. 认证链（源码确认）

| 层 | 事实 |
| --- | --- |
| `packages/api-client/src/auth.ts` | 模块内存 access token（`setAccessToken:154`）；refresh 走 HttpOnly cookie（`AUTH_REFRESH_PATH:36`，解析到 `/api/v1/auth/refresh`）；`refreshAccessToken:135` 单飞（`refreshInFlight`）；`onAuthLogout:72` 登出事件；`authRequest:191` 在 401 时先读 `hadToken`(:208) 再决定是否触发登出(:212)，**匿名 401 不触发登出**；unsafe mutation 不自动重放 |
| `apps/web/src/react-app.tsx:17/40` | 导入并注册 `onAuthLogout`，注册硬跳转处理器 |
| `apps/web/src/lib/use-current-user.ts` | 待 W3 复核：无条件 `GET /auth/me`（匿名也发个人请求）属既存实现缺陷 |
| `apps/web/src/lib/session.ts` | **未跟踪、零生产消费者**（全仓仅自身测试引用） |
| `apps/admin/src/lib/auth-context.tsx` | 已有 `AuthProvider:96` / `useAuth:175`，不得另造 token store |

### 4-E. seed contact / outbox 链（源码确认）

| 事实 | 证据 |
| --- | --- |
| 公开表单 = `SeedRequestContact` → 表 `seed_request_contacts` | `apps/api/app/models/seed_request.py:49` |
| 字段 name/email/institution/country/gene_ids/notes，**无 requester 外键** | 同上 |
| 已有审批人外键 `processed_by → users.id`（ondelete SET NULL） | 同文件模型定义末段 |
| 公开提交**无需认证**（设计正确，非缺口） | `apps/api/app/api/v1/seed_requests.py:51` 注释与路由签名 |
| 事务 outbox 已存在 | `apps/api/app/models/outbox.py`、`apps/api/app/core/outbox_dispatcher.py`、`apps/api/app/core/task_dispatch.py` |
| 新申请到达的机器人通知**已存在** | `apps/worker/src/soymutdb_worker/tasks/email.py:32,292`（`send_wecom_table`） |
| 群机器人出站为**无状态 best-effort**，默认关闭，非官方/非 HTTPS 主机直接拒绝 | `apps/worker/src/soymutdb_worker/utils/wecom_bot.py:1,58,62,80,84` |
| 既有离线测试 | `apps/worker/tests/test_wecom_bot.py` |

结论：审计 D-06 成立。企业微信扩展点必须落在既有 outbox 上，不得新建第二条通知链；`seed_requests`（登录库存申请）与 `seed_request_contacts` 保持分离。

### 4-F. release 切换链

- `apps/api/app/models/data_publishing.py:51` 表 `active_release`；`apps/api/app/services/release_service.py:117` 在切换时写 `AuditLog(action="release_published", old_value={"active_release_id": previous_id}, ... manifest_sha256=...)`。

判定：数据 release 指针切换是 **PostgreSQL 内单事务**；这**不等于**应用版本/静态制品/迁移的整栈原子发布（D-09 仍然成立）。

## 5. 未跟踪实验代码的审查输入

| 文件 | 初始判定 | 处置 |
| --- | --- | --- |
| `apps/web/src/lib/session.ts`（72 行） | 未接线；全仓零生产消费者 | 交 W3 判定复用/重构/废弃，**不得**只把布尔门控接进 `enabled` 就算修复 |
| `apps/web/src/ablation/session-gate.test.tsx` | 断言 `expect(calls).toEqual([])` 但从不调用被 mock 的探针 → 零请求是「没发请求」而非「门控拦住」 | 交 W3 按统一消融协议重写 |
| `apps/web/src/ablation/functional-invariants.test.ts` | 单测通过只证明模块内自洽 | 交 W3 标证据层级，不得计入端到端 ACTIVE |

## 6. 待用户确认项（不阻断已明确任务）

1. 企业微信侧：企业/租户、智能表格真实产品与 API、同步字段白名单与个人信息出站批准、文档搜索的文档域与权限源、外部审批写入范围。
2. 部署侧：部署目标环境与恢复目标（RTO/RPO）。
3. W6 独立测试库与 schema 快照的来源。

以上按方案 §5「单项缺失只阻断该项」，其余包继续推进。

## 7. 实施中 Lead 裁决记录（分包越界项，唯一所有者收口）

分包执行者在包边界处按 H-03 先回报、不越界。以下两项跨包冲突由 Lead 裁定并接管收口，
**不允许两个包各改一半，也不允许加例外白名单**。

### 7-A. assembly 消费点实际为 10 个，且其中 2 个是真实缓存泄漏

W2 分包在包外发现并回报，我已逐行复核属实。W0 §4-A 的 6 个消费点是**不完整枚举**，更正如下：

| 位置 | 键形态 | 判定 |
| --- | --- | --- |
| `apps/web/src/routes/search/genes.tsx:96` | `list({ releaseId: getReleaseId(), siteVariant })` | 工厂旁路 |
| `apps/web/src/routes/search/location.tsx:87` | `list({ releaseId, siteVariant })` | 工厂旁路 |
| `apps/web/src/routes/search/location.tsx:105` | `chromosomes(assemblyId, ctx)` | 工厂旁路 |
| `apps/web/src/routes/search/gbrowse.tsx:29` | `list({ releaseId, siteVariant })` | 工厂旁路 |
| `apps/web/src/routes/search/primer.tsx:65` | `list({ releaseId, siteVariant })` | 工厂旁路 |
| `apps/web/src/routes/tools/seqfetch.tsx:62` | `list({ releaseId, siteVariant })` | 工厂旁路 |
| `apps/web/src/routes/variants/index.tsx:77` | 手写数组 `['assemblies', getReleaseId(), SITE_VARIANT]` | 键不在工厂体系内 |
| `apps/web/src/routes/genes/$geneId.tsx:69` | 手写数组 `['assemblies', releaseId, SITE_VARIANT]` | 键不在工厂体系内 |
| `apps/web/src/routes/tools/enrichment.tsx:147` | `['tools', 'assemblies']` | **H-05 违反** |
| `apps/web/src/routes/tools/exppattern.tsx:73` | `['tools', 'assemblies']` | **H-05 违反** |

后两项共用同一键，缺 release/siteVariant，违背显式作用域合同。
同一 QueryClient 更换上下文时存在串缓存风险；不同部署的 JS realm 不自动共享内存缓存。
实际跨站泄漏未复现，活动目录长期陈旧也尚需运行验证。
定级：`Implementation Drift`，`scope: architecture`；不是已证实的身份泄漏。

### 7-B. G4 假绿的根因（独立于 W1 发现的第二处同型缺陷）

W1 分包独立定位：

- `scripts/check_web_query_keys.py` 约第 31 行用 `VIEWS_DIR.glob('*.vue')`；
  Vue 运行时已退役，`apps/web/src/views` 下当前 0 个 `.vue` 文件；
- 因此 `len(consumers) == 0` 恒成立，`main()` 永远返回 0。
  §3 的 G4「exit 0 / 0 assembly consumers」就是这条假绿，**不是通过**。

同类缺陷的第二处：W1 报 `scripts/check_admin_content_architecture.py:51` 只扫
`{'.ts', '.vue'}`，而 `apps/admin/src` 下有 83 个 `.tsx` + 32 个 `.ts` 业务源文件，
即**绝大多数业务源码从未被这条交付守卫检视过**。「扫 `.vue` 的架构守卫」在全仓已系统性失效。

### 7-C. 收口归属

`scripts/check_web_query_keys.py` 与 `scripts/check_admin_content_architecture.py` 各由**单一所有者**
完成：前者的后缀扩展、空扫描判失败、工厂旁路识别由 W2 收口；后者的后缀扩展与真实正反例
由 W1 收口。两个包不得互相改动对方文件，不得为让守卫变绿而加例外白名单。

### 7-D. release 运行时切换当前不存在（不得宣称已通）

W2 分包核实并回报，我复核 `apps/web/src/lib/deployment.ts:73` 的
`applyDeploymentRelease()` **全仓零调用方**（死缝）。`setReleaseId` 只在
`react-app.tsx` 模块初始化时由 `import.meta.env.VITE_SOYMUTDB_RELEASE_ID` 执行一次，
是构建期常量；`getReleaseId()` 是 api-client 模块级单例的普通读，**非响应式**，
视图内 `const releaseId = getReleaseId()` 不会因切换重渲染。

判定：活动 release 的**运行时切换与目录失效链路当前不存在**。W2 交付的失效/重取缝
必须如实标注「无订阅者时切换不可观测」为已知缺口，
**禁止**用缩短 staleTime 冒充切换失效，**禁止**宣称切换链路已打通。


---

## 8. 实施轮复核记录（2026-10-02 第二轮，Lead 执行）

> 本节只写本轮**实跑**到的结论。没有取到证据的一律标「未验证」。
> 上一轮 §7 的结论本轮逐条复核，其中 3 条被更正（见 §8-C）。

### 8-A. 起始状态（本轮实测）

| 项 | 值 |
| --- | --- |
| HEAD | `9b63ddd416c86757d9a80b70e72cfeb785791de4`（与上一轮同一提交） |
| 分支 / 工作树 | `main`；`git status --porcelain` 32 项（23 已修改 + 9 未跟踪） |
| Node / pnpm | `v24.19.0` / `12.5.1`，均与 pin 一致 |
| Python / uv | `3.14.6` / `0.11.33` |
| Docker / psql / pg_isready / pgcli / ant | **全部 MISSING**（`command -v`） |
| `DATABASE_URL` / `POSTGRES_*` | 未设置 |
| Chromium | `playwright` 二进制存在于 PATH（本轮未启动浏览器） |

### 8-B. 现存红灯（本轮真实退出码）

| 守卫 | exit | 判定 |
| --- | --- | --- |
| `check-vue-retirement.mjs` | 0 | 绿 |
| `check-react-entry-graph.mjs` | 0 | 绿 |
| `check-dockerfile-copy.sh` | 0 | 绿（上一轮的失效 COPY 已修） |
| `check_page_registry.py` | 0 | 绿 |
| `check_web_query_keys.py` | 1 → **0** | 本轮修复后转绿，见 §8-D |
| `check_admin_content_architecture.py` | 1 → **0** | 本轮修复后转绿，见 §8-E |
| `check_visible_i18n_react.mjs` | **1** | **既存红灯**，仍是 39 个文件，与基线 §1.4 R-12 一致；本轮未新增命中（W4 范围） |
| `pnpm --filter @soymutdb/api-client check:contract` | **1** | **既存红灯**：`CONTRACT DEBT`。可判定为非本轮引入——两个比较操作数（`apps/api/**` 与已提交的 `src/generated/openapi.d.ts`）在工作树中均无改动，结果与 HEAD 相同 |
| `python3 -m pytest scripts -q` | 0 | **313 passed / 1 skipped**（基线时为 275/1） |

### 8-C. 对上一轮结论的更正（三条）

1. **「9 个 assembly 消费点报红」是守卫假阳性，不是源码缺陷。**
   `check_web_query_keys.py` 用 `\(([^)]*)\)` 截取工厂实参，遇到
   `assembliesQueryOptions({ releaseId: getReleaseId(), ... })` 在嵌套括号处提前截断，
   因而看不到 `siteVariant`。逐行复核 10 个调用点后确认**源码全部已正确携带 release + site**。
   判定：**守卫 Design Defect（scope: architecture）**，非 Implementation Drift。
2. **上一轮 W2 的改动没有通过 typecheck。** 实跑发现
   `query-options.ts` 存在 `assemblyChromosomesQueryOptions` 重复实现（旧的无作用域键
   `["assemblies", assemblyId, "chromosomes"]` 仍在，属 H-05 违反），
   `primer.tsx` / `seqfetch.tsx` 残留未使用的 `releaseId`。本轮已修，web typecheck 转 0。
3. **未跟踪的 `navigation-render.test.tsx` 从未被真正执行过。**
   它内联了 per-render `t` mock，违反 `test_ci_job_contracts`，导致该文件加载失败；
   修正 mock 后暴露出真实漂移：`__root.tsx` 的 `menuItemRender` 仍是 `<a href>`（整页刷新），
   而 `2026-10-01-admin-pro-migration-design.md` §3.1 已批准改用 `<Link>`。判定为
   **Implementation Drift**，本轮按既有批准方案做最小修复，非新��品决策。

### 8-D. W1（交付阻断与守卫维护）结果

| 包 | 结果 | 证据 |
| --- | --- | --- |
| jbrowse Dockerfile 失效 COPY | 上一轮已删 `packages/ui-vue/package.json` 行 | `check-dockerfile-copy.sh` exit 0 |
| `check_web_query_keys.py` | 改为括号配平扫描（跨字符串字面量），新增 `scripts/test_web_query_keys_guard.py` 7 tests | 守卫 exit 0；负例「删 siteVariant」「删 releaseId」均翻转 |
| `check_admin_content_architecture.py` | 把「主题偏好键」放行升级为**声明式偏好键注册表 + 校验器包裹**（`PREFERENCE_KEYS`），放行 `soymutdb-animation-prefs` 的 `parseMotionPreference(...)` 包裹读取；伪装 token、声明键夹带 token、非校验读取仍失败 | 守卫 exit 0；`scripts/test_admin_content_architecture_guard.py` 29 passed（新增 5 组负例） |
| i18n 交付契约 | 改用共享 `mockTranslation`（异步工厂，避开 hoisting TDZ） | `test_ci_job_contracts.py` 61 passed（上一轮 1 failed） |
| 真实消融 | 向真实 `apps/admin/src/App.tsx` 注入 `localStorage.setItem("soymutdb-animation-prefs", response.access_token)` → 守卫 exit 1 → 恢复 md5 一致 → exit 0 | **GUARD-ACTIVE（源码级）** |

### 8-E. W2（assembly 工厂与作用域）结果

| 验收项 | 结果 |
| --- | --- |
| 10 个消费点统一走工厂且携带 release + site | ✅ 全部复核通过 |
| release A/B 目录不同且缓存不串 | ✅ 新增 `apps/web/src/lib/assemblies-query-options.test.ts`（6 tests，真实 QueryClient） |
| 站点键分离 | ✅ 同上用例 |
| 未知深链无查询 | ✅ 既有 `tool-pages.test.tsx` 4 用例恢复通过 |
| `all()` 仅作失效前缀 | ✅ 全仓仅 `query-keys` 内部与测试使用；前缀关系有断言 |
| 消融 | 删除键中的 `releaseId` → 「每个 release 独立条目」翻转；移除 `assertAssemblyRelease` → 「拒绝与传输层 release 不一致的上下文」翻转；均恢复后复跑通过 |
| **运行时 release 切换** | ❌ **不存在**：`applyDeploymentRelease` 全仓零调用方；`setReleaseId` 仅在 `react-app.tsx` 由构建期 `VITE_SOYMUTDB_RELEASE_ID` 执行一次。**禁止宣称切换链路已通**，列为未完成 |

### 8-F. W3（登录、权限与个人缓存）结果

| 验收项 | 结果 |
| --- | --- |
| api-client 保留单一协调者 | ✅ 复用 token/refresh 单飞/登出事件；新增 `authGeneration` 使过期异步工作不落地 |
| React 层响应式状态 | ✅ 新增 `session-context.tsx`（`SessionProvider` / `useSession`），`react-app.tsx` 接线；移除模块级 `void restoreSession()` |
| 五态状态机 | ✅ `session.ts` 重构为纯状态机（restoring/anonymous/authenticated/expired/error），11 tests |
| 匿名零个人请求 | ✅ `useCurrentUser` 以 `enabled: canQueryPersonal` 门控；hook 级实测 0 次 `/auth/me` |
| 网络/5xx ≠ 无权限 | ✅ 状态机单测覆盖 401/403/502/500/TypeError 五种失败 |
| 账号切换清个人缓存 | ✅ 个人查询键含 `sessionId`；登出与登录各清一次 |
| 公开页不强制跳登录 | ✅ `isPublicPath` 判定，仅非公开页带校验后回跳参数跳转 |
| 研究者判定与后端 grants 一致 | ✅ D-05 源码确认并修正：后端 `_COMMON_GRANTS` 使 curator/data_manager/track_manager/blast_manager/seed_manager/content_editor/auditor 均含 `researcher`，仅 viewer 不含 |
| **并发 401 单飞** | ⚠️ 上一轮的 generation 判定**过度收紧**：兄弟请求刷新完成后，先发请求的并发 401 会直接抛错。已修复并补 `auth-concurrency.test.ts`（3 tests，含 unsafe 方法不重放） |

### 8-G. 本轮未跑 / 未验证（不计入完成）

- Docker 镜像真实构建（无 Docker）
- 浏览器 E2E / 窄屏与键盘焦点验证（未启动浏览器）
- PostgreSQL / pgcli 任何实验（无 psql/pgcli、无连接串、无独立测试库）
- 企业微信 / 智能表格 / 文档搜索（W5，未开始）
- W6 索引 A/B、W7 发布切换（未开始）
- `check_visible_i18n_react` 39 文件与 `check:contract` 契约债（均为既存红灯）

### 8-H. W4-P1 · analyses 模块 i18n（完成，模块内零硬编码）

| 文件 | 本轮前 | 本轮后 |
| --- | --- | --- |
| `components/analyses/researcher-gate.tsx` | 4 | **0** |
| `components/analyses/upload-dropzone.tsx` | 15 | **0** |
| `routes/analyses/index.tsx` | 6 | **0** |
| `routes/analyses/fastp.tsx` | 22 | **0** |
| `routes/analyses/scanpy.tsx` | 26 | **0** |
| `routes/analyses/$jobId.tsx` | 43 | **0** |
| `check_visible_i18n_react` 命中文件总数 | 39 | **33** |

**关键发现**：zh/en 目录**早已包含** `analyses.*` 全部键。R-12 的实质不是「缺翻译」，
而是「组件硬编码英文、没有消费已备好的目录」——只搬文案不改组件不会让任何东西变绿。

- 新增 en/zh 键 89 个，`packages/i18n-core` 补**键对等守卫**（此前只有插值语法守卫，无对等守卫）。
- `quality_phred` / `thread` 等**服务端参数名**未走共享白名单放行，而是进目录（zh 保持原样，因为它们是 API 名）。按 H-13「可记录的 canonical token」处理，不放宽共享白名单。
- 曾用 i18next Intl 复数键（`_one`/`_other`），被新增的解析测试证伪：中文的 `Intl.PluralRules` 只有 `other` 一类，`_one` 永不命中。改为组件内显式选单/多键。
- 新增 `analyses-i18n.test.ts`：用**真实 i18next 实例 + 出厂目录**解析组件实际调用的键，证明目录项可达（存在 ≠ 可解析）。
- 新增 `researcher-gate.test.tsx`：渲染真实组件，en 与 zh 两态均断言，并断言页面上**不出现裸键路径**。

**消融**

| 变异 | 层级 | 对照 | 变异 | 恢复 |
| --- | --- | --- | --- | --- |
| `$jobId.tsx` 把 `analyses.job.totalReads` 改回硬编码 | 源码 + 守卫 | 33 文件 | **34 文件（指名该行）** | 33，md5 一致 |
| `researcher-gate.tsx` 标题改回英文字面量 | 组件（真实渲染，zh） | 3 passed | **1 failed**（en 渲染**无法**区分，字面量恰等于 en 目录值） | 3 passed，md5 一致 |

**自建测试缺陷（已修）**：`researcher-gate.test.tsx` 漏 `cleanup()`，`document.body`
在用例间累积，导致末位用例的 `not.toContain` 依赖运行顺序，同一套件两轮一成一败。
修正后连跑 4 轮稳定 138/138，并**重新取证**了 gate 消融。

### 8-I. 本轮累计验证（真实退出码）

```
web typecheck            0
web test                 0   26 files / 138 tests
web lint（改动目录）      0
i18n-core test           0   11 tests
query-keys test          0   11 tests
check-vue-retirement     0
check-react-entry-graph  0
check_web_query_keys     0   38 modules / 9 consumers
check_admin_content_arch 0   116 files
pytest scripts -q        0   313 passed / 1 skipped
git diff --check         0
check_visible_i18n_react 1   33 个文件（**部分完成**，未扩大 baseline 洗绿）
```

> ⚠️ **这是 §8-I 当时的快照，不是当前值。** 当前状态见 **§9-B**：
> `check_visible_i18n_react` 已 **exit 0 / 0 个文件**；`pytest scripts` 已 **350 passed / 1 skipped**；
> `git diff --check` 由 0 变 2（见 §8-L0）。
> §8-I 作为「当轮实测证据」保留，不回改。

注：全量 `eslint src` 在本机 SIGABRT（core dumped，exit 134），与基线记录的
cgroup 受限一致；改动目录的定向 lint 为 0。**该现象未验证为环境以外的原因，也未修**。

### 8-J. W3 加法式能力字段 `/auth/me.effective_roles`（完成）

**问题**：门户自带一份角色表（`RESEARCHER_ROLES = {researcher, administrator}`），
而 `apps/api/app/core/security.py::_ROLE_GRANTS` 的 `_COMMON_GRANTS` 使
curator / data_manager / track_manager / blast_manager / seed_manager / content_editor / auditor
**全部满足** `require_role(RoleName.RESEARCHER)`。两份表已经漂移（审计 D-05）。

| 项 | 内容 |
| --- | --- |
| 后端 | `core/security.py::effective_roles()`（复用 `_ROLE_GRANTS`，**不新建第二权威源**）；`UserResponse.effective_roles: list[str]`（默认空 = 加法式，旧 payload 仍可校验） |
| 端点 | `GET /auth/me` 带出该字段；`get_user_roles()` 仍是"分配了什么"的唯一来源，superuser 仍注入 administrator |
| 前端 | `grantsResearcher()` 优先读 `effective_roles`；字段缺失时才回落到旧形状，且对 viewer **fail-closed** |
| 测试 | `apps/api/tests/test_me_capabilities.py` **20 passed**（Docker-free，走真实 HTTP 层，非 skip）；`apps/web/src/lib/use-current-user.test.ts` **7 passed** |
| 消融 | 后端停发 `effective_roles` → 15 failed；前端忽略该字段改用旧私表 → 3 failed；均恢复后复跑通过 |

**附带消除一个既存红灯**：`check:contract` 由 **exit 1 → exit 0**。

#### 契约债量化（重要，不可混为一谈）

重生成 `packages/api-client/openapi.json` 后 diff 为 **+2114 / -416 行**，但：

| 来源 | schema 路径数 |
| --- | --- |
| **既存债**（HEAD 后端已有、已提交 `openapi.json` 缺失） | **828** |
| **本次增量**（`effective_roles` 的 items/type/title） | **3** |

取证方法：回退后端三文件到 HEAD → 重新导出 → 与已提交版本逐路径比对 → 恢复改动 → 再导出 → 与回退版比对。
**结论：99.6% 的 diff 不是本轮引入**，已如实标注，未按「我改的」记账。

#### 行尾事故与修复（须记录）

编辑工具把 `apps/api/app/api/v1/auth.py` 的**混合行尾**（HEAD 为 336 CRLF + 52 LF）统一成了 CRLF，
造成 109 行噪声 diff，且触发了 `H-编码纪律`。
处置：`git checkout --` 回到 HEAD 字节 → 改用**字节级补丁**（按各段真实行尾写 `\r\n` 或 `\n`）重做。
现 `auth.py` diff 为 **14 行**、行尾保真；其中 7 行是 Ruff import 排序顺带规范化的既有 LF 行，已披露。

### 8-K. W2 运行时 release 切换（完成，用户 2026-10-02 确认场景存在）

**此前的真实缺口**（本轮复核确认，非沿用旧结论）：`applyDeploymentRelease()` 全仓**零调用方**；
`setReleaseId()` 只在 `react-app.tsx` 由构建期 `VITE_SOYMUTDB_RELEASE_ID` 执行一次；
`getReleaseId()` 是 api-client 的模块级普通读，**非响应式**，视图内 `const releaseId = getReleaseId()` 不因切换重渲染。
即：发布切换在当时**完全不可观测**。

| 层 | 内容 |
| --- | --- |
| 后端 | `GET /api/v1/releases/active` → `ActiveReleaseResponse`。直接读既有 `active_release` 单例（`id=1`），与 `resolve_release_context` 同一权威源；路由声明在 `/{release_id}` **之前**，否则会被 id 路由吞掉并返回 422 |
| 传输 | `setReleaseId()` 仅在**值确实变化**时通知；`subscribeToRelease()` 返回退订函数 |
| web | `lib/release-scope.tsx`：`ReleaseScopeProvider` + `useReleaseId()`；60s 轮询 + `visibilitychange`；切换时 `dropReleaseScopedQueries()` 后按谓词 refetch |
| 失效范围 | **显式声明**的 `RELEASE_SCOPED_PREFIXES`（`assemblies` / `genes` / `search` / `mutants` / `variants` / `analytics` / `gene-search` / `search-region`）。不用结构嗅探：release 槽位在 `assemblies.list` 是倒数第 2、在 `discoveryTrend` 是倒数第 3，而 `news` / `table-views` 根本不带 release |
| 测试 | `apps/api/tests/test_active_release_endpoint.py` **7 passed**（含路由顺序与空态）；`apps/web/src/lib/release-scope.test.tsx` **7 passed** |
| 消融 | 移除缓存丢弃 → 翻转；移除订阅 → 翻转；均恢复后复跑通过，md5 一致 |

**实现与注释矛盾（自测抓到）**：首版用了无过滤的 `queryClient.refetchQueries()`，
实测会把非 release 作用域的新闻缓存一起重取——正是该文件注释警告的「一刀切失效」。
改为 `refetchQueries({ predicate: isReleaseScopedKey, type: "active" })`，并由测试锁定
（`newsRuns` 必须保持 1）。

**未做的事（明确声明）**：没有用缩短 `staleTime` 冒充切换失效；
没有把 `getReleaseId()` 的全部 10 个消费点改成 `useReleaseId()`（传输层仍读 `getReleaseId()`，
查询键在 Provider 内经 React state 响应式）。未 pin 的部署仍跟随服务端默认 release。

### 8-K0. 本轮新增与修改的文件清单（便于审阅）

**新增（测试与实现）**

| 文件 | 作用 |
| --- | --- |
| `apps/web/src/lib/session-context.tsx` | 会话 Provider（单一协调者，响应式五态） |
| `apps/web/src/lib/session.test.ts` | 状态机 11 tests |
| `apps/web/src/lib/use-current-user.test.ts` | 能力判定 7 tests |
| `apps/web/src/lib/assemblies-query-options.test.ts` | release A/B 缓存隔离 6 tests |
| `apps/web/src/lib/release-scope.tsx` | **运行时 release 作用域**（Provider + `useReleaseId` + 精确失效） |
| `apps/web/src/lib/release-scope.test.tsx` | 切换/同值/失败三态 7 tests |
| `apps/web/src/lib/analyses-i18n.test.ts` | 真实 i18next 解析目录键 4 tests |
| `apps/web/src/components/analyses/researcher-gate.test.tsx` | en/zh 组件渲染 3 tests |
| `packages/api-client/src/auth-concurrency.test.ts` | 并发 stale-401 3 tests |
| `scripts/test_web_query_keys_guard.py` | 守卫负例 7 tests |
| `apps/api/tests/test_me_capabilities.py` | `/auth/me` 能力字段 20 tests（Docker-free） |
| `apps/api/tests/test_active_release_endpoint.py` | `/releases/active` 7 tests（Docker-free） |

**修改（守卫与契约）**：`scripts/check_web_query_keys.py`（括号配平）、`scripts/check_admin_content_architecture.py`（偏好键注册表）、
`packages/api-client/src/{auth,client,index,releases}.ts`、`apps/api/app/{core/security,schemas/auth,schemas/content,api/v1/auth,api/v1/releases}.py`、
`apps/web/src/{react-app.tsx,lib/use-current-user.ts}`、`packages/i18n-core/src/i18n-core.test.ts`、两个 locale 目录。

**消融备份与原始证据**：`.validation/opt2026-w0/`（14 组消融，全部已 md5 校验恢复）。

### 8-L0. `git diff --check`：工作树一度报 2，提交后回到 0（更正）

本轮在 `apps/api` 三个文件中新增了行。**`git diff --check` 因此从 exit 0 变为 exit 2**：

```
apps/api/app/api/v1/auth.py       : 8 处
apps/api/app/api/v1/releases.py   : 28 处
apps/api/app/schemas/auth.py      : 7 处
```

**这不是我敲了尾随空格。** 逐字节核验：这三个文件**真实尾随空格行数 = 0**，
全部新增行是 **CRLF**；仓库**没有 `.gitattributes`**，因此 git 把 `
` 判为行尾空白。
这些文件在 HEAD 本来就是 CRLF（或混合）：`auth.py` 336 CRLF + 52 LF、`releases.py` 全 CRLF、
`schemas/auth.py` 184 CRLF + 6 LF。HEAD 里已有的 CRLF 行不报，是因为 `diff --check` 只检查**新增**行。

**处置：保持各文件既有行尾**（新增行继续用 CRLF），不做 LF 转换。
理由：把新增行改成 LF 会在全 CRLF 的 `releases.py` 里首次引入 LF，churn 更大且更不一致；
`git diff --check` **不在任何 CI 门禁或脚本中**（已 grep `scripts/`、`.cnb.yml`、`.github/` 确认），
它只是方案 §6 的手工验证清单项之一。

**若要根治**：为仓库加 `.gitattributes` 统一行尾策略，属于独立的仓库级变更，需单独决策，本轮未做。

#### 更正（收尾时复核）

上述改动随 `160b42e69` **提交后**，工作树的 `git diff --check` 回到 **exit 0**
（它只检查未提交的增量）。但在**提交层面**仍可复现：
`git show --check 160b42e69` 报 **45 处** trailing whitespace，全部是这三个文件的 CRLF 行。

因此准确表述是：**这不是一个持续存在的红灯**。`git diff --check` 未接入任何 CI 门禁
（已 grep `scripts/`、`.cnb.yml`、`.github/` 确认），工作树当前为 0；
仅在需要审阅该提交时会看到 45 条提示。**根治仍需 `.gitattributes` 决策。**

### 8-M. W6 实验框架（已搭建，无库环境下可自证；**未跑过真实 A/B**）

用户 2026-10-02 指示「先搭建框架」。框架与判据已就位，**任何真实测量都还没做**。

| 文件 | 内容 |
| --- | --- |
| `scripts/db_ab_experiment.py` | 单因素 A/B 计划、隔离拒绝、EXPLAIN 根层读数、交替轮次、比较与报告 |
| `scripts/test_db_ab_experiment.py` | **37 passed** |

**结构性地堵住 D-08 的三条方法学缺陷**（不是靠文档提醒）：

1. **统计信息对称**：`Arm.analyse` 默认 `ANALYZE`，`plan_rounds` 每轮对**两个臂都执行**。
   测试断言 ANALYZE 语句数为 `轮次 × 臂数`（对称性而非总数）。
2. **只读根层**：`extract_run` 读根节点的 `Execution Time` / `Planning Time` / buffer 计数；
   没有 `Execution Time`（即没开 ANALYZE）直接拒绝，不再可能拿子节点数字对比。
3. **交替 + 重复**：`rounds < 5` 直接拒绝构造计划；`Comparison.is_decisive` 还要求
   两臂**计划形状相同**且**结果基数相同**且样本数 ≥5，否则不出结论。
   报告强制打印 median / min / max / spread / 样本数，不接受单次计时。

**隔离（H-09）真的会拒绝，且有负例**：

| 拒绝项 | 负例测试 |
| --- | --- |
| 非 `soymutdb_abtest_*` 库名 | `soymutdb` / `postgres` / `prod` / 空 / `abtest` 全部拒绝 |
| `pg_terminate_backend` / `pg_cancel_backend` / `ALTER SYSTEM` / `pg_reload_conf` / `DROP DATABASE` / `VACUUM FULL` / `REINDEX DATABASE` | 含注释混淆（`-- x\nSELECT 1; pg_cancel_backend(1)`、`ALTER /* x */ SYSTEM`）均拒绝 |
| 计划中夹带危险语句 | **执行前**即拒绝，`execute` 未被调用任何一次 |

**消融（真实翻转，md5 已恢复）**：
移除库名隔离门 → **7 failed**；移除 5 轮下限 → **1 failed**；移除 ANALYZE 要求 → **1 failed**；
恢复后 37 passed。

**刻意不做的**：框架**不 import 任何数据库驱动**——只做计划、拒绝与比较，
`execute` 由调用方注入。这样在本机（无 psql/pgcli/Docker）仍可导入并测试全部判据，
而真实测量留到具备独立测试库时再跑。

**仍缺的前置**：命名独立测试库的来源（schema 快照）、真实查询集、真实 A/B 运行、
索引迁移的升级/回退演练。**未取得任何性能结论。**

### 8-L. 本轮未解 / 待查（不得当作已完成）

1. **API 测试间歇性 `Threading failure`（已定位：宿主线程容量，非代码缺陷）**

   症状：同一组 58 个测试，结果在 `58 passed` 与 `31 passed / 27 errors` 之间摆动。

   证据链：
   - 失败时全部 27 条是同一个错误：`argon2.exceptions.HashingError: Threading failure`
     或（哈希缓存生效后）`VerificationError: Threading failure`；
   - `Threading failure` 来自**编译后的 Rust 扩展** `_argon2_cffi_bindings`：
     argon2 每次 hash/verify 都要起一个工作线程，Python 层没有开关可关；
   - **决定性旁证**：同一宿主上 `ruff` 自身崩溃于
     `ThreadPoolBuildError { kind: IOError(Os { code: 11, kind: WouldBlock }) }`，
     numpy 导入亦中止——与基线记录的「cgroup 受限，缺 `GOMAXPROCS/RAYON_NUM_THREADS/
     UV_THREADPOOL_SIZE` 会线程耗尽」同源；
   - 串行单跑稳定 `58 passed`；只有**并发跑多个 pytest/Node 进程**时出现。

   **两次无效修复已回退（如实记录，避免后人重走）**：
   ①在 `make_user()` 缓存 Argon2 哈希 + 预置哈希常量——只消除了一半调用，
   `verify_password` 仍会失败，**不治本**，已 `git checkout --` 回退；
   ②在 `tests/conftest.py` 用 `pytest_runtest_call` 把该错误转成可读提示——
   **该 hook 破坏了执行链**（本可全过的测试变成 27 errors），已回退。

   **结论：这是环境限制，不是仓库缺陷。** 缓解方式（不需改代码）：
   `GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`
   且**不要并发跑多个 pytest/Node 进程**。
   若要在 CI 固化，应写进 `scripts/verify-backend-tests.sh`，本轮未做。
2. **全量 `eslint src` 在本机 SIGABRT（exit 134，core dumped）**，与基线记录的 cgroup 受限一致；
   改动目录定向 lint 为 0。**未验证为环境以外的原因，也未修**。
3. ~~`check_visible_i18n_react` 仍 exit 1~~ → **已关闭：exit 0，0 个文件**。
   39 → 33（analyses 模块 6 个）→ 22（第二批 12 个）→ **0**。
   期间发现并修掉一处**守卫缺陷**：守卫对**任何函数调用的实参**做可见性检查，
   于是 `renderInline(text, `bq-${key}`)` 里的 React key 前缀被判成文案（usage guide 4 处）。
   唯一"修法"竟是把 React key 塞进翻译目录——这正是基线 §2.2 禁止的"让守卫变绿"。
   处置：**窄修**（模板字面量实参不再按可见文案检查，字面量实参仍检查，因为那通常是
   `get(key, "Home")` 这类可见兜底），并补 `scripts/test_visible_i18n_react_guard.mjs`
   **6 tests** 证明未削弱：JSX 硬编码、可见属性、`t(key,{defaultValue})`、
   字面量兜底实参、可见模板文本 **仍全部被报出**；守卫加 `--root` 以便对合成源码树测试
   （CI 不传该参数，扫描面不变）。
   消融：撤销该豁免 → 守卫 11→**12** 翻转、测试 6→**5** 翻转；恢复后复跑通过。

4. **W4 浏览器验证：本轮已做（更正此前「无浏览器」的结论）**

   上一轮 W0 记录「Chromium launch 成功」，而本会话前半段沿用了「无浏览器」。
   **该沿用是错的**：`e2e/node_modules` 的 playwright 与
   `~/.cache/ms-playwright/chromium-*` 均可用，实测 `chromium.launch()` 成功。
   更正后完成四项此前未验证的内容：

   | 项 | 结论 | 证据层级 |
   | --- | --- | --- |
   | 多行 `alt` | 守卫是 **AST** 实现，多行硬编码 alt **能被抓到**；动态 `alt={expr}` 不误报 | 守卫测试 8/8 |
   | 适配器 `rowKey` | 调用点不传时适配器**确实有默认值**（非未定义键），但回落是**索引**；页内稳定、跨页不稳定 | jsdom 渲染 4/4 |
   | 键盘焦点 | skip link 是**第一个 tab stop**、Enter 后焦点到 `<main>`、聚焦时可见、导航链接有焦点指示 | **真实浏览器** 10/10 |
   | 窄屏 | 390px **无横向溢出**；移动菜单可键盘打开并呈现带链接的导航；导航点击目标 ≥24px | **真实浏览器** 10/10 |

   新增 `e2e/verify-a11y-and-layout.mjs`（10 项），跑在**本地生产产物**上
   （`apps/web/dist/external` + `e2e/static-server.mjs`），不是 dev server。

   **消融（真实翻转）**：把两处 skip link 都设为 `tabIndex={-1}` → 重建 → **10/10 变 9/10**，
   指名 "the skip link is the first tab stop and moves focus to main"；恢复后 10/10，md5 一致。

   **过程中两次自纠（如实记录）**：
   ① 断言用英文选择器 `button[aria-label*="menu"]`，而产物**默认 zh**（标签是「打开菜单」），
   导致「菜单不可达」的假失败——改为结构化选择器 `header button[aria-expanded]`；
   ② 首轮变异只改了源码中的**第一处** skip link（文件里共两处，首页渲染的是第二处），
   检查未翻转——**差点误判为 GUARD-INERT**，补齐两处后才真正翻转。

   **仍未验证**：antd 组件库自身的行为（`antd` CLI 在本机 MISSING，
   门面/别名扫描盲区未补）；真实后端联调下的会话/权限流程（无 API）。

5. **W5 / W6 / W7 未开始**；W6 待搭实验框架，W7 受阻于无 Docker 与部署目标。

---

## 9. 当前状态总览（2026-10-02 收尾，下个会话从这里接手）

### 9-A. 交付物：5 个提交，均已推送到 `origin/main`

| # | commit | 内容 |
| --- | --- | --- |
| 1 | `160b42e69` | W0–W3 实施 + analyses 模块 i18n |
| 2 | `79509b7ec` | W6 数据库 A/B 实验框架 |
| 3 | `e211764f5` | i18n 第二批（33 → 22 文件） |
| 4 | `e494b1cb2` | i18n 清零（22 → 0）+ 守卫缺陷修复 |
| 5 | `d721dc118` | 真实浏览器 a11y/窄屏验证 + rowKey + 多行 alt |

推送状态：`origin`（GitHub `caoronglin/soymutdb-next`）**已同步**；
`cnb`（cnb.cool）**仍无凭据，未推送**——本地 `main` 与 CNB 的差异需人工补推。

### 9-B. 红灯现状（全部为实跑退出码）

| 守卫 / 检查 | exit | 说明 |
| --- | --- | --- |
| `check-vue-retirement` | 0 | — |
| `check-react-entry-graph` | 0 | — |
| `check-dockerfile-copy` | 0 | 失效 COPY 已删 |
| `check_page_registry` | 0 | — |
| `check_web_query_keys` | 0 | 38 modules / 9 consumers |
| `check_admin_content_architecture` | 0 | 116 files |
| `check_visible_i18n_react` | **0** | **0 个文件**，本轮由 39 清零 |
| `check:contract` | **0** | 由 1 转 0 |
| `pytest scripts -q` | 0 | **350 passed / 1 skipped** |
| web / admin / api-client / i18n-core 测试 | 0 | 156 / 43 / 153 / 11 |
| 浏览器 a11y+窄屏 | 0 | **10/10** |

### 9-C. 明确的已知限制（不得当作已完成）

1. **无 psql / pgcli / pgcli / Docker** → W6 真实 A/B 未跑，**未取得任何性能结论**；未触碰任何数据库。
2. **`ant` CLI 缺失** → antd 门面/别名的扫描盲区未补。
3. **无真实后端** → 会话、权限、发布切换的端到端联调未验证。
4. **全量 `eslint src` SIGABRT（exit 134）** —— 改动目录定向 lint 为 0，未查因未修。
5. **`git diff --check`** —— 工作树当前 **exit 0**（改动已提交）。
   但 `git show --check 160b42e69` 仍有 45 处 CRLF 行提示；**真实尾随空格 = 0**。
   未接入 CI 门禁。根治需 `.gitattributes` 独立决策（§8-L0）。
6. **API 测试在宿主线程耗尽时 `Threading failure`** —— argon2 的 Rust 扩展起线程失败，
   与 ruff 自身 `ThreadPoolBuildError: WouldBlock` 同源；**环境限制，非代码缺陷**（§8-L）。
7. **两处修复尝试已回退**（哈希缓存、conftest hook），不得重走。
8. **W5 / W7 未开始** —— 受阻于产品确认与部署目标。

### 9-D. 协作风险（本轮发现）

**同一工作树存在并发会话**（`dsh-subprocess-local` 在跑 `check_docs.py` / `git diff --check`）。
本轮已核实它只做只读检查，未污染工作树（`git status` 全程只有本会话的改动）。
但它很可能导致了一次构建 **SIGABRT**（重试即成功）。**多人/多会话同树工作有覆盖风险**，
建议确认另一个会话的任务范围后再继续并发改动。

### 9-D2. 消融场景表（已自动化、可复跑）

方案 §4 要求每个保护因素配一个场景：对照/变异的**真实 exit**、观测、恢复结果、证据层级。
本轮把散做的消融收敛为 `scripts/run_ablations.py` + `docs/aegis/ablations-2026-10-02.md`。

- **14 个可执行场景全部翻转，未翻转 0 个**，全部字节级恢复（`restored=True`）。
- **2 个场景显式未运行**并写明原因：F-01 数据库真实 A/B（无 psql/pgcli/Docker，
  **未取得任何性能结论**）；F-02 构建产物层 a11y（已单独跑过 10/10→9/10，
  重跑需重建双站产物约 4 分钟/次）。

跑器保证：单因素变异、字节级备份与恢复 + 校验和、不干净即拒判、串行执行
（宿主无法承受多个并发重型进程）、未运行场景必须随行给出原因。

#### 跑器自身的缺陷（本轮发现并修复）

首轮跑出 **B-02 一次翻转、两次不翻转**，另有场景出现对照 exit=1。
排查发现：场景在同一 mtime tick 内「写入→恢复」，Python 会命中**陈旧 `.pyc`**
（mtime+size 均未变），**变异根本没被加载**——报出的是幻觉式的「未翻转」。

修复：子进程设 `PYTHONDONTWRITEBYTECODE=1`，并在每次执行前清除目标模块的 `__pycache__`。
修复后连跑 4 轮 × 3 场景**全部稳定翻转**。

**这条本身说明：不能复跑的消融等于轶事。** 若没有跑器，这次「未翻转」会被当成
「该保护是冗余的」写进报告。

### 9-E. 下一步（按可做性排序）

| 优先 | 事项 | 需要什么 |
| --- | --- | --- |
| 1 | `cnb` 远端推送 | CNB 凭据，或人工执行 `git push cnb main` |
| 2 | W6 独立测试库准备流程 | schema 快照来源 + `psql`/`pgcli` + Docker |
| 3 | W5 离线适配层 | 企业微信产品/租户/同步字段/文档域确认 |
| 4 | W7 发布切换脚本 | 部署目标、RTO/RPO、候选环境 |
| 5 | 收尾治理项 | `.gitattributes` 决策；把线程受限缓解写进 `verify-backend-tests.sh` |
