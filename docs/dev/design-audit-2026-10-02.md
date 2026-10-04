# 2026-10-02 设计草稿审计

- 日期：2026-10-02
- 状态：**审计结论**。原设计草稿需按下表修订后才可作为执行依据。
- 复审修订：纠正统计推断、审批人外键与企业微信凭据分类；执行依据见
  [`审计后优化执行方案`](../aegis/plans/2026-10-02-audited-optimization-execution.md)，
  新对话启动文本见 [`执行提示词`](execute-audited-optimization-prompt.md)。
  本文记录历史证据；下述源码路径在实施时仍需重新核验。
- 审计对象：`.validation/docopt-2026-10-02/` 的六份草稿（总设计 / 功能消融 / 升级发现 / 数据库 / 认证与企业微信 / UI 审计），及它们所引用的当前代码。
- 审计方法：只读核对。每条发现均给出当前代码的 `文件:行号`；凡本机无法取得证据的，一律写「未验证」而非推断。
- 纪律：本审计**不修改生产源码**，不提交草稿，不引入新架构。判定沿用
  [`BASELINE-GOVERNANCE.md`](../aegis/BASELINE-GOVERNANCE.md) §2–§5 的
  `Design Defect` / `Implementation Drift` / `missing-authority` / `needs-clarification` 口径。

## 0. 结论

发现 **10 项问题，其中 9 项会影响架构判断或执行顺序**。三类：

1. **证据不足被写成结论**（D-01、D-08、D-10）——最危险的一类，因为下游会照着错误前提排期；
2. **把已确定的事实重新当作待裁决项**（D-02）——会让执行方推翻已有契约；
3. **设计引用了错误的业务对象与既有实现**（D-06、D-07）——照此实施会做错表、做重复功能。

**执行建议：先按 §5 顺序修订草稿，再开工。** 已有的三处真实缺陷（Dockerfile 失效 COPY、`.umi` 误报、
`views` 空目录）不受本审计影响，仍应照原计划修。

---

## 1. 证据不足被写成结论

### D-01 · P1 · 「守卫未接 CI」与实际调用链相反

**草稿原文**：`MASTER-DESIGN.md` §4 `P0-CI` 称 `check:page-registry` / `check:web-query-keys` /
`check:admin-content-architecture` 三个 pnpm 脚本「零调用方」，并据此把「守卫接入 CI」列为 P0。
`AUTH-WECOM-DESIGN.md` §4.2 的 K-4 重复了同一前提。

**实测调用链**：

```
.cnb.yml:126 / :204          → bash scripts/ci-job-steps.sh run frontend
scripts/ci-job-steps.sh:278  → scripts/verify-frontend-artifacts.sh
  scripts/verify-frontend-artifacts.sh:107  node scripts/check-react-entry-graph.mjs
                                          :108  node scripts/check-vue-retirement.mjs
                                          :111  python3 scripts/check_page_registry.py
                                          :114  python3 scripts/check_web_query_keys.py
                                          :117  python3 scripts/check_admin_content_architecture.py

scripts/ci-job-steps.sh:491  → scripts/build-release-image.sh
  scripts/build-release-image.sh:101      bash scripts/check-dockerfile-copy.sh
```

**根因**：检索只匹配了 job 文件中直接出现的脚本名，漏掉「job → 共享脚本 → 守卫」的两跳间接调用。
本项目的设计明确要求 job body 只调 `scripts/`（`AGENTS.md`「Delivery Pipeline」），间接调用**正是期望的形态**。

**影响**：P0-CI 会把已接入的门禁重复接线，重复执行与职责错配；K-4「守卫存在但不在链路上」
在 CI 侧不成立。历史本地执行情况未取证；本地统一验证入口是可选维护改进（见 D-01b）。

**处置**：撤回 P0-CI 与 K-4 的 CI 表述。`apps/jbrowse/Dockerfile:19` 的失效 COPY 仍是真实缺陷，
具体漏报原因尚未取得历史运行日志；本轮 `check-dockerfile-copy.sh` 实跑
`exit 1` 并指名该行，只证明当前检查能发现它，不证明本地或 CI 的历史执行情况。

### D-01b · P2 · 应改述为「本地开发态缺一条命令」

真正可执行的动作不是改 CI，而是让本地能一次跑完全部守卫（见 D-10 的门禁分层建议），
以及给 `check-dockerfile-copy.sh` 补一条 `test_ci_job_contracts.py` 断言，
确保 `build-release-image.sh` 未来不会漏掉它。

### D-08 · P1 · 数据库「≈100× 单因素」证据不成立

**草稿原文**：`DB-OPTIMIZATION.md` §1 DB-1 称 `CREATE INDEX` 后
「4.270 ms → 0.042 ms，≈100× 加速」，并标为 P0。

**三个方法学缺陷**：

1. **不是单因素**：实验组同时执行了 `CREATE INDEX` **和** `ANALYZE transcripts`。
   对照组的 ANALYZE 历史未核实（`pg_stat_user_tables.n_live_tup` 全为 0 不足以判断历史），
   统计信息也是实验变量，性能差异中统计信息与索引的贡献尚未分离。
2. **比较层级不一致**：4.270 ms 取自 `Seq Scan` **子节点**的 `actual time`；
   0.042 ms 取自 `Nested Loop` **根节点**。根节点包含两侧，不是同一层级的读数。
3. **无对照重复与冷热控制**：对照组只跑一次，未记录 `buffers`；两组缓存状态不同。

**可保留的结论**：`Seq Scan on transcripts (rows=80374)` 出现在一条只返回 1 行的查询上，
这是需要验证的**索引候选**；样本在加索引与 ANALYZE 后变为 `Index Scan`。这只是方向性观察，
全表扫描本身不自动构成缺陷，是否值得增加索引还需查询频率、写入成本与公平对照。

**不可保留**：「100×」这个数字，以及把它当 P0 的依据。

**处置**：重做 A/B —— 两组都先 `ANALYZE`、都用同一条 SQL 与同一组参数、交替执行 ≥5 次、
记录完整 `EXPLAIN (ANALYZE, BUFFERS, TIMING)` JSON 而非摘取单行，再谈倍数。
索引进入待验证清单；是否创建及优先级由重做实验后决定，暂不作为必加项。

**顺带修正**：`n_live_tup = 0` 只能说明**统计信息陈旧或被重置**，不能推出「从未 ANALYZE」
（`pg_stat_reset()` 之后同样是 0）。DB-3 的表述需弱化为「统计信息不可信」。

### D-10 · P1 · 消融的「9/9 ACTIVE」把单元测试通过当成了系统保护

**草稿原文**：`MASTER-DESIGN.md` §6 与 `AUTH-WECOM-DESIGN.md` §2.35 合计称
「9/9 GUARD-ACTIVE」，其中 F9 标为「会话门控证明」。

**F9 的实际问题**（本轮逐行核对）：

- `apps/web/src/ablation/session-gate.test.tsx:37–55` 断言 `expect(calls).toEqual([])`，
  但该测试**从未调用** mock 的 `probe`。零请求是因为**代码没去发请求**，不是因为门控拦住了它。
- 被测的 `session.ts` 是**本轮新建、尚未接线**的模块。全仓引用它的只有它自己的测试。
  真实的 `use-current-user.ts:28–33` 仍然无条件 `GET /auth/me`。
- 因此「匿名不发探针」这条不变量**当前代码并不满足**，只是新模块内部自洽。

**证据等级降级**：F9 应记为「新模块的单元测试通过，运行时接线与验证未做」，
暂不计入「已验证的运行时守卫」。F1–F8 也要逐项区分函数、静态扫描与组件层证据，
不代表覆盖了调用方（这与 2026-10-02 前一轮记录的 K-1 教训是同一类风险）。

**处置**：`FUNCTIONAL-ABLATION.md` §2 增加「证据等级」列，区分
「函数级消融已翻转」与「端到端不变量已验证」；F9 标注未接线。
接线 `use-current-user.ts` 之前，不应宣称会话门控生效。

---

## 2. 把已确定的事实重新当作待裁决项

### D-02 · P1 · assembly 缓存键的作用域已有契约，不是产品二选一

**草稿原文**：`ESCALATION.md` 与 `MASTER-DESIGN.md` §3.3 把
「assembly 元数据是否随 release/site 变化」列为 `DECIDE-ASSEMBLY`，要求产品拍板。

**实测**：后端已明确按 release 作用域返回。

```
apps/api/app/api/v1/genes.py:45    @router.get("/assemblies") 依赖 get_release_context
                                  :60    缓存键 f"genes:assemblies:release:{release_context.release_id}"
                                  :69    loader 按 release_id 过滤
```

后端把 assembly 目录定义为**当前 release 的引用数据**并据此缓存。这已经是一份可执行契约。

**真正的问题不是「作用域是什么」，而是前端有两套键**：

| 位置 | 键 | 注释主张 |
| --- | --- | --- |
| `apps/web/src/lib/query-options.ts:64` | `queryKeys.assemblies.all()` | 「assembly 是全局参考数据，不随 release / site 变」 |
| `packages/query-keys/src/index.ts:22` | `queryKeys.assemblies.list({releaseId, siteVariant})` | 「目录是 release 与 site 作用域的，切换必须不复用」 |

两处注释**直接对立**，且 10 个页面用手写的 `list(...)`、工厂用 `all()`。后端既有实现支持后者
的注释。所以这是**实现漂移**（前端工厂未跟随后端契约），不是 `missing-authority`。

**处置**：

- 撤回「待产品拍板」的提法，改为按后端既有契约收敛：前端工厂与调用端统一到含 `releaseId` 的键；
- 保留 release 切换后目录必须重新加载这一要求（后端已按 release 缓存，前端必须同构）；
- 站点变体是否也进入键，需要单独核验前端消费方，但这不阻塞 release 维度；
- **验收判据**：`assembliesQueryOptions()` 必须与后端 `release_id` 同构；
  `check_query_factory_usage.py`（草稿 §5.2 已提出）需覆盖全部 10 个页面。

---

## 3. 设计引用了错误的业务对象与既有实现

### D-06 · P1 · 企业微信设计的业务对象错了，且重复了已存在的通知

**草稿原文**：`AUTH-WECOM-DESIGN.md` §3.3 以「`seed_requests` 有 `requester_id` / `reviewer_id` /
`reviewed_by` 外键」为理由，主张表单数据不能直接入库、需先做身份映射。

**实测**：公开申请走的是**另一张表**。

```
apps/api/app/models/seed_request.py:49-64   class SeedRequestContact → 表 seed_request_contacts
                                           字段：name / email / institution / country / gene_ids / notes
                                           **无 requester_id 外键**（提交本身不需要登录）
apps/api/app/api/v1/seed_requests.py:51    「Submit a seed request contact (open to all; no authentication)」
```

`seed_requests`（`models/seed.py:63`）是**已登录用户的种子库存申请**，与公开联系表单不是一回事。
草稿把两者的字段结构混为一谈，据此推出的「必须先映射身份」结论**不成立**——
公开表单本来就是无账号提交，身份字段就是 email + institution。

**同时：新申请到达的机器人推送已经存在**，草稿称「机器人推送已覆盖完成/失败通知，但新申请到达没有实时触达」，
与代码不符：

```
apps/worker/src/soymutdb_worker/tasks/email.py:292-299
    send_wecom_table("收到新的种子申请", [申请编号, 基因数量, 状态])
```

**处置**：

- 业务对象改为 `SeedRequestContact`（公开表单）与 `seed_requests`（登录申请）两条独立链路，
  分别说明各自的通知需求；
- 撤回「表单入库需先映射 requester 身份」——公开表单的字段本就是 email/institution，
  真正需要映射的是**审批侧**（Bitable 里的审批人 ↔ `users` 表），
  `seed_request_contacts` **已有** `processed_by → users.id` 审批人外键，
  见 `models/seed_request.py:84–87`；外部审批人需映射本地用户并经服务端权限与审计链处理；
- 撤回「新申请无触达」——`tasks/email.py` 已有；扩展点应是在既有 outbox 上补充，而非新建通道。

### D-07 · P1 · 多维表格/回调设计缺密钥管理与重放防护

**草稿原文**：`AUTH-WECOM-DESIGN.md` §3.3(c) 列出 5 条安全要求，但设计本身缺三块：

1. **回调的加解密与签名算法未经核实**。草稿写「`msg_signature` + `timestamp` + `nonce`
   三参数 HMAC-SHA1」。本轮尝试读取官方示例（`sbzhu/weworkapi_python` 的 `WXBizMsgCrypt.py`）
   **两次均失败**（GitHub 503；直连 raw 超时），因此**该算法描述目前无来源支撑**，
   实施前必须以企业微信官方文档为准，不得照抄本草稿。
2. **群机器人 webhook 与应用回调凭据应分开建模**。前者是出站 URL 密钥；
   回调 Token / EncodingAESKey 属于已确认回调产品的验证与加密配置；
   智能表格 API 的企业/应用凭据又应以官方产品合同为准。
   草稿仅列未核实的 `WECOM_BITABLE_APPID` / `WECOM_BITABLE_SECRET`，尚不足以实施。
3. **Bitable 同步缺幂等与失败可观测性**。草稿说「以 `request_id` 作幂等键」，但没说
   幂等键存在哪（PG 侧 `seed_request_contacts.id` → Bitable 行的映射表需要一张新表 +
   迁移），也没说同步失败如何重试与告警——现有 `wecom_bot` 是**无状态 best-effort**，
   Bitable 写入有副作用，不能照搬同一模式。

**处置**：

- 回调协议细节全部标「**待官方文档核实**」，本轮不得实施；
- 分清出站 webhook、应用 API 和入站回调凭据；名称以核实后的部署合同为准。
  只注入需要使用它们的服务 secret，回调若由 API 接收则在该接收服务验证，前端与日志不接触密钥；
- Bitable 同步单独设计：需要持久化映射表、幂等写入、重试与死信、与 `send_table` 的
  best-effort 契约区分开；
- 保持「回调只读不写」的边界（草稿这点判断正确，予以保留）。

---

## 4. 其他设计缺口

### D-04 · P2 · 门禁层缺少会话状态机定义

`AUTH-WECOM-DESIGN.md` §2.3 提出 `<RequireAuth>` / `<RequireRole>` / `<WithAuth>` 三种门禁形态，
方向正确，但**没有定义会话状态**。当前 `use-current-user.ts` 只有 `user: CurrentUser | null`
与 `isLoading`，无法区分：从未探测 / 探测中 / 已登录 / 匿名 / 会话过期 / 网络故障。
没有这个状态机，三种门禁的渲染分支会互相打架（尤其「网络故障」会被当成「无权限」）。

**处置**：补会话状态枚举，并明确「网络故障」不得等同于「无权限」——
这是 2026-10-02 前一轮审计里 `researcher-gate` 误报的同类问题。

### D-05 · P2 · 角色判定与后端 grants 不一致

草稿 §2.2 的门禁矩阵与 `apps/api/app/core/security.py:143–156` 的实际授权表存在差异：
后端 `_COMMON_GRANTS` 让 `curator` / `data_manager` / `track_manager` / `blast_manager` /
`seed_manager` / `content_editor` / `auditor` 都**包含** `researcher` 权限；
而 `use-current-user.ts:25` 的 `RESEARCHER_ROLES` 只列 `researcher` 与 `administrator`。

草稿未识别这处既存偏差。**处置**：门禁设计应直接消费后端 `has_role` 语义（或请求一个
capability 端点），不再在前端硬编码角色名——否则这处偏差会被固化。

### D-09 · P2 · 原子部署缺可执行步骤

`MASTER-DESIGN.md` §5.3 提出了正确的分层思路（`pre-commit` → `ci-job` → `release`），
但「原子发布」一节把**数据层 release 指针切换**等同于**部署原子性**。二者不同：
数据库 `active_release` 切换是原子的，但应用版本、制品、迁移的回滚路径没有定义。

**处置**：补「代码版本 ↔ 迁移 ↔ 制品」三者的一致性判据，以及回滚时的迁移处置（down 还是前滚）。

---

## 5. 修订顺序（建议）

> 本节保留历史修订清单；实施顺序、硬性约束与阶段出口以
> [审计后优化执行方案](../aegis/plans/2026-10-02-audited-optimization-execution.md) 为准。

### D-10 补充：UI 与 origin 证据降级

逐行 `<img>` 扫描会漏读多行 `alt`，例如 `news-card.tsx:49–51`；
DataTable 的调用点没有 rowKey，也不代表其适配器没提供默认值（见 `components/data-table.tsx:141`）。
两端门面各自收窄导出不自动构成缺陷，整体 export 也不解决 CLI 的别名解析盲区。
这些命中应作为人工复核候选，不能写成已确认的全局缺陷。

F4 尾斜杠不改变 URL origin；字符串规范化翻转不是 iframe 外源消息被拦截的证明。
postMessage 应通过真实事件的 origin/source、消息白名单、版本与握手负例验证，单列组件或浏览器证据。

### 历史修订清单

| 顺序 | 动作 | 依据 |
| --- | --- | --- |
| 1 | 撤回 `P0-CI` 与 K-4，改为「本地一键跑守卫」 | D-01 / D-01b |
| 2 | 重做数据库 A/B 测量，降级「100×」 | D-08 |
| 3 | 消融报告补证据等级列，F9 标未接线 | D-10 |
| 4 | assembly 按后端既有契约收敛，撤回「待拍板」 | D-02 |
| 5 | 企业微信设计改绑 `SeedRequestContact`，撤回重复的推送设计 | D-06 |
| 6 | 补会话状态机；角色判定改用后端 grants | D-04 / D-05 |
| 7 | 回调协议标待核实；补凭据与幂等设计 | D-07 |
| 8 | 补部署原子性的版本/迁移/回滚判据 | D-09 |

**不受本审计影响、仍应照原计划执行的三项真实缺陷**：

1. `apps/jbrowse/Dockerfile:19` 仍 `COPY packages/ui-vue/package.json`（该包已随 Vue 退役删除），
   镜像构建必失败；守卫已能指出，只差删除该行；
2. `check_admin_content_architecture.py` 扫描 gitignored 的 `.umi*/` 产生 2 条永久误报；
3. `check_web_query_keys.py` 扫描已空的 `apps/web/src/views/` 目录（Vue 退役遗留），
   修复后暴露查询工厂漂移——按已确定的 release 契约修订，不再等待产品二选一裁决。

---

## 6. 本轮验证与限制

**本轮实跑**：

- 两个新增消融文件：`Test Files 2 passed / Tests 11 passed`（`session-gate.test.tsx` 2 项、
  `functional-invariants.test.ts` 9 项）。**这只说明单测通过，不构成守卫在系统里生效的证据**（见 D-10）。
- 逐行核对：`packages/api-client/src/auth.ts`（`hadToken` 门控在 `:208`/`:212`）、
  `apps/web/src/react-app.tsx:40`（`onAuthLogout` 确实注册了硬跳转处理器）、
  `apps/web/src/lib/use-current-user.ts:28`（探针**无条件**发起）、
  `scripts/ci-job-steps.sh:278/491`、`scripts/verify-frontend-artifacts.sh:107-117`、
  `scripts/build-release-image.sh:101`、`.cnb.yml:126/204`。

**纠正草稿中的两处自查错误**（原草稿结论有误，此处更正）：

- 上一轮称「门户无认证、登录功能缺失」并把「门户没有登录跳转触发点」作为 K-1 未复发的依据。
  实测 `react-app.tsx:40–46` **确有** `onAuthLogout` 处理器会 `window.location.href` 跳登录页。
  K-1 是否复发的真正防线在 `auth.ts:208–213` 的 `hadToken` 判定（匿名 401 不触发登出），
  草稿查错了文件，结论侥幸正确但依据无效。
- 上一轮称 `seed-request.tsx`「门户侧零鉴权」是缺口。实测 `seed_requests.py:51` 明确
  公开提交无需认证，**这是设计正确**，非缺口。

**限制**：

- 无 Docker：jbrowse 镜像的真实构建失败**未复现**，D-01 的缺陷判定基于 Dockerfile 与守卫输出，非实际构建日志；
- 无浏览器：F9 的「匿名不跳转」「零探针」**未做端到端验证**；
- 无企业微信凭据：回调加解密与 Bitable API **未调用核实**（官方示例两次取回失败），
  D-07 中所有协议细节标注为待核实；
- 数据库结论基于查询计划与单次计时，**无 `pg_stat_statements`**（未 preload），
  不构成基于真实流量的调优依据。

**产物**：本审计（`docs/dev/design-audit-2026-10-02.md`）。
草稿原文保留在 `.validation/docopt-2026-10-02/`（该目录被 `.gitignore` 排除，
仅作历史证据，不应作为现状引用；其结论以本审计为准）。
