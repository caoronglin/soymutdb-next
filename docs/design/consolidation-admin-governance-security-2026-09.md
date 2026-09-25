# SoyMutDB 收口方案：架构收敛 · 旧代码退役 · Admin 全权治理台 · 安全加固

> 版本：v8.0 设计稿（**只做设计，未实施**）
> 核验日期：2026-09-25 · 基线 `main@d3904c210`（工作区另有 212 处未提交：126 modified / 78 untracked / 8 deleted）
> 仓库：`/mnt/smb/t25ronglin/code/web`
> 取证方式：三个只读 subagent 并行调查（后端鉴权与 RBAC、前端存量与死代码、部署与运行时安全）+ 主 agent 逐条核验；凡未核实项均在 §10 标注
> 与既有文档的关系见 §0.3；本文件**不取代** `plan.md`，是它 Phase 5/6/7 的展开与裁决。

---

## 0. 结论摘要

### 0.1 三句话

1. **架构不是要重设计，而是要收口**：后端分层（API → service → model）与契约纪律已经成型，真正的债务是**三条前端栈并存**（React 门户、Vue 门户迁移中、React 后台）加上**两套规划体系并行**，必须先把"谁是主线、谁冻结、谁退役"写死，否则每新增一个功能就多欠一笔迁移债。
2. **后台缺的不是页面，是"治理面"**：Admin 已有 20 个功能模块与完整的发布/导入/内容能力，却**没有任何用户、角色、会话、凭据管理接口**——`/admin/users` 在代码里不存在。这意味着账号只能靠公开注册产生、角色只能靠 seed/DB 手改、禁用用户无处操作、审计无法回答"谁有权做什么"。这是本项目当前最大的能力空洞，也是安全上最大的单点。
3. **安全要分层补，而不是重做**：Argon2id、refresh token family 轮换、CSRF origin 校验、CORS fail-closed、双站点隔离、CSP（构建期 sha256 化）、备份/回滚、Trivy/SBOM/签名等**已经具备**；缺口集中在 MFA、会话治理、审计不可篡改、前端角色感知、admin 授权声明方式、限流与告警。
   其中两条属于**"看起来有保护、实际没有"**，优先修：① `RateLimitMiddleware` 定义了却从未注册（全局限流不存在）② `cleanup_old_audit_logs` 无任何调用方（180 天保留从未执行）。

### 0.2 本方案做什么 / 不做什么

| 做 | 不做 |
| --- | --- |
| 裁决主线（Vue canonical）与冻结边界 | 重写后端分层、引入 repository 层 |
| 旧代码分类 + 归档删除流程与批次清单 | 一次性删 React（会碎掉 CI 与 SSG） |
| 新增 Admin 治理面：用户 / 角色 / 会话 / 凭据 / 审计 | 把 Admin 推到 Vue 重写一遍再补功能 |
| 安全加固：MFA、授权正确性、审计完整性、CSP/限流 | 引入外部 IdP 替换现有认证（除后台可选的 SSO 前置） |
| 计划体系统一（消除双真源） | 新造一个"总纲 v9"与之并行 |

### 0.3 与既有文档的权威关系（第一裁决）

现状是**两套规划并行**，且互相不知道对方：

| 文档 | 时代 | 内容 | 与本方案关系 |
| --- | --- | --- | --- |
| `plan.md`（第七轮，2026-09-25） | **当前主线** | Vue 迁移、PR #1 收敛、Phase 1–7、T0–T11 测试链 | **执行权威**。本方案服从它的 Phase 顺序 |
| `docs/dev/optimization-master-plan.md`（v6.0）+ v1–v5 子方案 | 2026-08 ～ 09-11，React 时代 | 性能、内容链路、Admin 体验、桌面客户端、Rust 评估 | **设计参考**。React 相关条目在冻结后需重新判定有效期 |
| `docs/dev/optimization-master-plan.md` §1 勘误表 | — | 已发生过"凭印象归因、写出不存在的 bug" | 本方案所有结论标注证据路径，未核实项显式标注 |
| `docs/ops/production-security-checklist.md`（G-1..G-7 + Go/No-Go） | 运维安全台账 | 已有部分"已完成"标记 | **安全运维真源**：本方案 D 组与其重叠处不另立条目，只补设计与依赖 |
| `docs/superpowers/plans/2026-09-15-portal-security-ux-perf-optimization.md`（T1–T32） | 门户安全/UX/性能任务矩阵 | 未与 plan.md 交叉引用 | 一并登记进 plan-registry，标注与 Phase 3/6 的重叠 |

裁决：

- **R-01**：`plan.md` 是唯一执行计划；`optimization-master-plan.md` 降级为"设计素材 + 勘误记录"，其 §6 优先级不再直接排期。
- **R-02**：新增 `docs/design/plan-registry.md`（方案登记表），每个方案登记：主题 / 生效区间 / 状态（active / superseded / archived）/ 替代者 / 残余任务。**任何新方案必须先登记再实施**，防止第三套真源。
- **R-03**：凡本方案条目与 `plan.md` 冲突，以 `plan.md` 为准并在实施时回写登记表。
- **R-04**：安全运维类缺口以 `docs/ops/production-security-checklist.md` 为准（它已有 G-1..G-7 与 Go/No-Go），本方案只负责设计、依赖与验收口径，不制造第二份缺口台账。

---

## 1. 现状盘点（只列已核实事实）

### 1.1 仓库与工作区

| 事实 | 证据 |
| --- | --- |
| 单仓 pnpm/Turbo monorepo，7 个 app、10 个 package | `apps/`、`packages/` 目录清单 |
| 工作区活跃且未提交：126 modified、78 untracked、8 deleted | `git status --porcelain` 统计 |
| untracked 主要落在 `apps/web-vue`（33）、`apps/api`（20）、`packages/shared`（10） | `git status --porcelain` 前缀聚合 |
| 已删除但未提交的是 `apps/web/src/lib/*`（8 个文件，含 jbrowse-bridge、primer-design） | `git status --porcelain` `D` 项 |
| `ui-r/`（2 文件，仅文档注释引用）、`recreations/`（1 文件）仍 tracked；`.slim/` 已被 `.gitignore:108` 忽略且 `git ls-files` = 0；`cache/` 目录**不存在**（被忽略的是 `.cache/`） | `git ls-files`、`git check-ignore -v` |

结论：**迁移正在进行中**，任何删除动作都必须先处理"未提交改动 + 迁移半成品"这两个前提，否则会误删仍在被引用的文件。

**已完成、不要重复做的退役项**（核验 2026-09-25）：

- `packages/ui` 目录已不存在，`@soymutdb/ui` 仅剩 `apps/jbrowse/antd-migration-contract.test.mjs:23` 的"不应依赖"断言；`@soymutdb/ui-vue` 是唯一 UI 包（43 个引用）。
- `apps/web/src/lib/web-ui.tsx` 已删除，`lib/web-ui` 引用 0（`docs/dev/webui-removal-spec.md` 描述的迁移已完成）。
- `dump.rdb`、`pages-dist/`、`artifacts/`、`eslint_out.txt`、`tsc_out.txt` 已被 `.gitignore` 覆盖。
- 更正（此前判断有误）：`.slim/` **已被** `.gitignore:108` 忽略、`cache/` 目录**不存在**。
- 🔴 **唯一"删了就真没了"**：`.slim/deepwork/full-stack-upgrade.md`（21 KB，2026-08-12）从未入库（`git ls-files .slim` = 0），删 `.slim/` 后只能靠外部备份 ⇒ 先 `git add -f`。

### 1.2 前端三栈并存

| 应用 | 栈 | `src/` 文件数 | 状态 |
| --- | --- | --- | --- |
| `apps/web` | React 19 + Vite + AntD | 146（93 tsx / 52 ts，36 条路由） | **仍是唯一发布物** |
| `apps/web-vue` | Vue 3.5 + Vite + ui-vue | 74（39 vue / 34 ts，33 条路由） | 迁移目标；`package.json` 自述 "preview-only … apps/web stays canonical until the Phase 3 cutover" |
| `apps/admin` | React 19 + AntD Pro + TipTap | 161（115 tsx / 44 ts，`App.tsx` 手工路由 35 处） | Vue 化程度 = **0**（无 `.vue`、无 `ui-vue` 引用） |

**发布链事实（决定删除顺序，先看清）**：

- `.cnb.yml` 里**零字面量 `vue`**；`scripts/` 中唯一提及 web-vue 的只有 `verify-vue-site-variant-artifacts.sh`，`.github/workflows/` 同样零命中。
- 发布只构建 React：`scripts/build-pages-artifact.sh:46`（`--filter @soymutdb/web build`）、`:62`（`cp -r apps/web/dist`）；`verify-frontend-artifacts.sh:53` 只验 `apps/web/dist`。
- `plan.md:255` 明写"canonical 发布仍保持 React，待 parity 实测后再切换"，`:295-302` 记 Vue 构建待依赖恢复 ⇒ **Phase 3 未收口**。
- parity gap：`/analytics`、`/compare` 尚无 Vue 对应（`apps/web/src/routes/analytics.tsx:20`、`compare.tsx:32`）；`/antd-pilot` 为 dev-only。
- 文档滞后：`AGENTS.md:5` 只列 `apps/web`(React)/`apps/admin`/`apps/jbrowse`，**完全没提 `apps/web-vue`** ⇒ 与当前双栈事实不符，应随 A-01 一并修正。

`plan.md:604-629` 已写明 Phase 4（TanStack Charts）、Phase 5（Vue Admin）、Phase 6（Hardening）、Phase 7（React/ECharts Retirement）——方向正确，但**缺少"迁移期防扩散"机制**：目前没有任何守卫阻止新代码继续写进 `apps/web` 或继续在 `apps/admin` 堆 React 组件。

### 1.3 Admin 能力面：广而浅

已有 20 个 admin 路由模块（`apps/api/app/api/v1/admin*.py` + `router.py:95-111`），覆盖发布、导入、内容、媒体、Page Builder、插件、特性开关、设置、静态构建、表视图、审计查询。

**没有的**：

| 缺口 | 证据 |
| --- | --- |
| 用户管理（列表 / 创建 / 禁用 / 解锁 / 重置密码 / 删改） | `rg "admin/users\|/users"` 于 `apps/api/app/api/v1/*.py` → **0 命中**；`auth.py` 只有 `register`(93)、`login`(144)、`refresh`(232)、`logout`(268)、`me`(306)、`change-password`(315) |
| 角色 / 权限管理（授予、回收、权限矩阵可见） | 无 `admin/roles` 端点；`Role.permissions`（`models/auth.py:45`）是 JSONB 但**授权判定只用 role 名**（`core/security.py:160-170` 的 `has_role`） |
| 组织 / 项目成员管理 | 模型齐备（`models/auth.py:62-288` Organization / Project / ProjectMember），无任何管理端点 |
| 会话治理（在线会话、强制登出、撤销 refresh family） | `refresh_tokens` 表有 family/revoked_at（`models/auth.py:170-221`），但只有登录/登出链路在用，无管理视图 |
| API 令牌 / 凭据管理 | 无模型、无端点 |
| 前端角色感知 | `AuthUser` 只有 `username`（`apps/admin/src/lib/auth-context.tsx:12-14`）；全前端无 `roles`/`permission` 判断 |
| 审计完整性保障 | `log_action` 手工调用（`core/audit.py:18-45`）；180 天物理删除（`core/audit.py:48-65`）；无 hash chain / 无只追加约束 |

后果：**账号生命周期只能绕过产品界面完成**——这既是运维痛点，也是"最小权限"落不了地的根因。

### 1.4 安全资产（已经做对的，别推翻）

| 资产 | 证据 |
| --- | --- |
| Argon2id 口令哈希（非 bcrypt） | `core/security.py:107-114` |
| refresh token 只存 SHA-256、family 轮换 + 盗用检测 | `models/auth.py:170-221`、`core/security.py:253-258` |
| access token 15 分钟、每请求回库校验 `is_active`/`is_deleted` | `core/config.py:176`、`api/v1/deps.py:55-62` |
| CSRF：Origin/Referer 强校验，缺失即拒绝 | `core/csrf.py:41-65` |
| CORS：生产禁止 `*`、默认值 fail-closed 校验 | `core/config.py:366-372` |
| 10 角色显式授权矩阵（非线性继承） | `core/security.py:143-170` |
| 登录限流：Redis 固定窗口 10 次/60s（username + IP），非 dev 环境 Redis 不可用即 fail-closed | `core/ratelimit.py:114-180,201`、`api/v1/auth.py:161`、`core/config.py:143-144` |
| ⚠️ 纠正：`users.locked_until` 是**死字段**（只被读与清、无任何写入点） | `models/auth.py:128`、`api/v1/auth.py:172-184,194-195` |
| ⚠️ 纠正：`RateLimitMiddleware` 已定义但**未注册**到 app（应用层无兜底全局限流） | `core/middleware.py:98,119` vs `main.py:298-316` |
| Admin 网络 ACL（nginx 私网 allowlist） | `infra/nginx/conf.d/default.conf`（`/admin/`、`^~` 前缀） |
| 双站点 external/internal 隔离 + noindex + 负向泄漏测试 | `docs/dev/architecture-and-deployment.md:104-114`、`scripts/test_site_artifact_isolation.py` |
| 配置安全单测（默认密钥/CORS 等）已在 CI 跑 | `apps/api/tests/test_config_security.py`（`.github/workflows/baseline-validation.yml:124`） |
| 生产 fail-closed 校验证：CORS 禁 `*`、JWT 算法白名单、默认密钥检测、admin 口令 ≥12 | `core/config.py:366-441` |
| API 安全头中间件：nosniff / X-Frame-Options DENY / Referrer-Policy / Permissions-Policy（**无 CSP、无 HSTS**，CSP 只在 nginx） | `main.py:261-272`、`infra/nginx/conf.d/security-headers*.inc:41-42` |
| 账号创建/重置现仅靠 CLI（且 CLI 自己写审计） | `apps/api/app/scripts/create_admin.py:41-143` |
| 上传边界：presign 上限 500 MiB、`/complete` 服务端复核 size/type/sha256、对象键形状校验 | `services/presign.py:36,233-327,500` |
| 外部抓取 SSRF 防护：精确 host 白名单 + 强制 https + `follow_redirects=False` + 6 次/300s 限流 | `services/external_article_service.py:49,116,123-125,525-526` |
| 富文本 sanitize：bleach 白名单、协议限 http/https/data、禁 `image/svg+xml`、强制 `rel=noopener`；Page Builder 另拒 raw script/iframe/on* | `core/sanitize.py:32-111`、`page_builder/registry.py:6-19,54` |
| worker 只收 JSON（无 pickle 面）；MCP 静态 Bearer token + 自带配额、Redis 不可用只更严 | `worker/main.py:71-73`、`apps/mcp-server/src/mcp_server/server.py:58,70-78`、`ratelimit.py:1-30` |
| 容器加固：`cap_drop: ALL` + `no-new-privileges` 且应用服务全继承；发布端口一律绑 `127.0.0.1` | `docker-compose.yml:24-30`、`scripts/check-supply-chain.sh:29` |
| 备份/恢复/回滚：6 桶强制哈希、`.complete` 标记、隔离演练；`upgrade.sh` 失败自动回滚；19 条 Prometheus 告警 | `deploy/scripts/backup.sh`、`verify-restore.sh`、`deploy/scripts/upgrade.sh:265-269,332,341`、`infra/monitoring/` |
| 仓库已有生产安全缺口台账（含若干已完成项） | `docs/ops/production-security-checklist.md:144-208`（G-1..G-7） |
| 供应链：Trivy / SBOM / cosign / digest 引用 | `scripts/build-release-image.sh`、`release-contract.golden.sh` |
| 限流实现 | `core/ratelimit.py`（`login_rate_limiter`，登录 10r/60s + 预览限流） |
| 审计声明骨架已存在（metadata-only，自述供 A-19 守卫消费） | `core/audit_policy.py:declares_audit`（当前仅 `admin.py` 6 处使用） |
| 双站点产物隔离校验脚本 | `scripts/check_site_artifact_isolation.py`、`verify-site-variant-artifacts.sh`、`verify-vue-site-variant-artifacts.sh` |

### 1.5 计划体系现状

`docs/dev/` 下同时存在：`optimization-master-plan.md`(459 行)、`optimization-plan.md`、`performance-optimization-plan.md`、`platform-optimization-plan.md`(1145 行)、`content-template-plan.md`、`desktop-client-plan.md`、`rust-rewrite-and-architecture-evaluation.md`，外加 `plan.md`(784 行) 与 `docs/agent-state/`、`.ai-memory/`。**v4.0 §5 的 Admin 体验升级（12 小节）与 plan.md Phase 5 完全重叠且无交叉引用**。

---

## 2. 缺口与风险清单

按"风险 × 价值 ÷ 成本"排序，全部标注证据。

| ID | 缺口 | 证据 | 风险 | 等级 |
| --- | --- | --- | --- | --- |
| G-01 | 无用户管理 ⇒ 无法禁用离职账号、无法审计"谁有权" | §1.3 | 安全 + 运维 | **高** |
| G-02 | 前端无角色感知 ⇒ 所有人看到同一套界面，按钮靠"点了才 403" | `auth-context.tsx:12-14` | 安全（体验差 → 绕过流程） | **高** |
| G-03 | 无 MFA ⇒ 后台仅口令一层 | `core/security.py` 无 TOTP 相关 | 安全 | **高** |
| G-04 | 审计可被物理删除且无防篡改 ⇒ 合规证据力弱 | `core/audit.py:48-65` | 安全 | 中高 |
| G-05 | 审计无强制力：`@declares_audit` 全仓仅 5 处（均在 `admin.py` release 链路），其余写操作靠手工 `log_action`；未写无告警 | `core/audit_policy.py:15-42`（docstring 自述 metadata-only）、`core/audit_inventory.py:32-55` | 正确性 / 合规 | 中高 |
| G-06 | 迁移期无守卫 ⇒ React/Vue 双栈无限拉长 | §1.2 | 工程 | 中高 |
| G-07 | 双真源规划 ⇒ 排期冲突、过期条目被当任务做 | §1.5 | 工程 | 中 |
| G-08 | 无会话治理 ⇒ 令牌泄露后只能等 15min/7d 自然过期 | `models/auth.py:170-221` | 安全 | 中 |
| G-09 | 权限判定不读 `Role.permissions` ⇒ JSONB 是装饰 | `security.py:160-170` | 设计债 | 中 |
| G-10 | 无危险操作二次确认/四眼 ⇒ 误发布、误回滚 | `admin.py` 发布链路 | 数据 | 中 |
| G-11 | 旧代码/垃圾产物混在仓库（untracked 目录、转储文件） | §1.1、`dump.rdb`、`eslint_out.txt`、`tsc_out.txt` | 工程 | 中 |
| G-12 | 新主线 `apps/web-vue` 无 `public/`、无 `_headers`、无 CSP；且 **GitHub Pages 不读 `_headers`** ⇒ gh-pages 路径零安全头（`apps/web/public/_headers:5-8` 已自述） | §D3 | 安全 | 中高 |
| G-13 | 98 个 admin 端点**无 router-level 依赖**，授权靠 15 个模块各自手工调 `_require_admin`（漏调即静默放开） | `api/v1/admin*.py`（对照 `seeds.py:61`、`tracks.py:85` 用 `dependencies=` 的正面例子） | 授权正确性 | **高** |
| G-14 | `auditor` / `curator` / `data_manager` / `blast_manager` 四个角色**零接线**（只活在 grant 表）；审计端点全要 `administrator`，只读审计员不可行 | `RoleName` 使用计数；`admin.py:295,331,423,448,552` | 权限设计 | 中高 |
| G-15 | 审计保留清理**无调用方**（`cleanup_old_audit_logs` 仅单测引用）⇒ 表只增不减 | `core/audit.py:48-65,132`、`tests/test_audit_retention.py` | 运维 | 中 |
| G-16 | 公开注册无应用层限流，且注册开关 `feature_registration_enabled` **无任何引用**（关不掉） | `api/v1/auth.py:88-141`、`core/config.py:304` | 安全 | 中 |
| G-17 | 失败登录不写审计；审计导出本身不写审计 | `api/v1/auth.py`（仅成功登录 :202-211） | 合规 | 中 |
| G-18 | `/api/v1/admin/*` 无 IP 限制（仅 admin 静态站有 nginx allowlist）；XFF 信任不一致（analytics 用白名单，conda 启动脚本 `--forwarded-allow-ips=*`） | `infra/nginx/conf.d/default.conf:89-95`、`api/v1/analytics.py:69-76`、`deploy/conda/conda-services.sh:66` | 安全 | 中 |
| G-19 | 双站点**端到端未实现**：`e2e/playwright.config.ts` 无 `projects:`（单目标打公网），而契约要求 external 匿名 + internal 已认证两条链 | `docs/dev/database-core-contract.md:283-286`、`e2e/playwright.config.ts:24-44` | 验证缺口 | 中高 |
| G-20 | 制品层隔离只有"单哨兵字节扫描"，无 `internal_id` 值级负向用例；API 层有真负向测试（`test_search_database_integration.py:354,366`） | 同上 | 验证缺口 | 中 |
| G-21 | SW 缓存名不含站点变体（`soymutdb-static-v*` / `soymutdb-runtime`）⇒ 同源多路径部署时两变体可能命中同名 cache | `apps/web/public/sw.js:26-28`、`scripts/gen-sw.js:57-59` | 缓存正确性 | 中 |
| G-22 | `scripts/smoke.sh`（含隔离单测）**没有任何流水线调用** | `scripts/smoke.sh:112`；`.cnb.yml:472` 的 smoke 是夜间 Playwright | 验证缺口 | 中 |
| G-23 | `nginx:1.27-alpine` 系镜像（web/admin/jbrowse）无 `USER`，PID1 为 root；API/worker/migrate 已用 uid 1000 ✅ | `infra/docker/Dockerfile.web:56-75`、`Dockerfile.admin:51-75`、`apps/jbrowse/Dockerfile:29` | 容器安全 | 中 |
| G-24 | 基础镜像只用 tag、不用 digest（python/nginx/node/uv）；Trivy 只扫 `vuln`（不扫 misconfig/secret）；`.trivyignore` 38 条无逐条理由与到期日 | `scripts/build-release-image.sh:179-195`、`.trivyignore` | 供应链 | 中 |
| G-25 | 无 secret 扫描器（pre-commit 仅 `detect-private-key`，CI 无 gitleaks/trufflehog） | `.pre-commit-config.yaml:74` | 供应链 | 中 |
| G-26 | 无鉴权失败 / 异常登录告警（Prometheus 19 条告警中无） | `infra/monitoring/` | 可观测 | 中 |
| G-27 | 悬空文档引用：`docs/ops/static-hosting-security.md` 被 4 处引用但文件不存在 | `apps/web/public/_headers:6`、`infra/nginx/conf.d/security-headers.inc:35` | 文档 | 低 |
| G-28 | 生产 fail-closed 仅在 `app_env == "prod"` 触发，**staging 不校验**；`app_env` 默认 `dev` | `core/config.py:344-446,85` | 安全 | 低中 |
| G-29 | `.cnb.yml` release 管道 `imports:` 引外部仓库**可变分支** main 的 env 文件 | `.cnb.yml:397,575,916` | 供应链 | 低 |
| G-30 | React 双变体**共用同一 API/JBrowse origin**（`buildVariant` 未注入逐变体 `VITE_API_BASE_URL`/`VITE_JBROWSE_BASE_URL`），隔离扫描只给 1 个哨兵 ⇒ origin 串味扫不出来（Vue 侧已逐变体注入 ✅） | `apps/web/scripts/build-sites.ts:60-67` vs `verify-vue-site-variant-artifacts.sh:19-25` | 隔离正确性 | 中高 |
| G-31 | 内部搜索**每次请求写一条 AuditLog 并 commit**（读操作放大写） | `api/v1/search.py:262-269` | 性能 | 中 |
| G-32 | `declares_audit` 声明与"真的写了审计"之间无校验 | `core/audit_policy.py:1-12` | 合规 | 中 |
| G-33 | MCP 令牌用 `==` 比对（非常量时间）；BLAST 任务归属靠客户端自报 `submitter_token` | `apps/mcp-server/src/mcp_server/server.py:70-78,283-306` | 安全 | 低 |
| G-34 | HSTS 取值两套（nginx 含 `includeSubDomains; preload`，Pages 仅 `max-age`）；API 响应无 HSTS | `infra/nginx/nginx.conf:112-115` vs `apps/web/public/_headers:31` | 一致性 | 低 |
| G-35 | JBrowse 无鉴权（自托管仅绑回环） | `docker-compose.yml:567-570` | 设计决策 | 低 |

---

## 3. 设计 A · 架构收敛

### A1 主线裁决与冻结边界（**先做，成本 0.5 天**）

- A1-1 `apps/web-vue` 为唯一门户主线；`apps/web` 进入 **FREEZE**：只修 bug、只做 Phase 3 未完成的平移，不再加新功能。
- A1-2 `apps/admin` 同样 FREEZE 于"结构"，但**允许新增治理面功能**（§C）——因为 Vue Admin（Phase 5）依赖 Phase 3/4 完成，等待窗口内不能空转。
- A1-3 冻结写进代码而非只写文档：
  - `eslint.config.js` 增加 `no-restricted-imports`：`apps/web-vue` 不得 import `apps/web` 源码（只能走 `packages/*`）。
  - 新增 `scripts/check-frontend-freeze.mjs`：扫描新提交 diff，若 `apps/web/**` 有新增文件则告警（可配豁免），若是 `apps/admin/**` 新增 React 组件则允许。

### A2 共享层边界表（写死，用守卫执行）

| 包 | 允许消费者 | 禁止 |
| --- | --- | --- |
| `packages/api-client` | web / web-vue / admin / e2e | 内含 React/Vue 组件 |
| `packages/query-keys` | web-vue / admin | — |
| `packages/i18n-core`、`packages/i18n` | 全部前端 | — |
| `packages/shared` | api / worker / 前端（契约） | 内含 DOM 代码 |
| `packages/ui-vue` | web-vue、未来 Vue Admin | 被 React 应用 import |
| `packages/motion` | web / admin（React 期） | 迁 Vue 后由 motion 决策（复用或重写） |

守卫：扩展 `scripts/check-architecture.py`（v4.0 §2.7 已提出该脚本，纳入同一批）。

### A3 后端"横切管线化"（增量，复用 v4.0 §2.2 设计）

现状：分页、审计、缓存、权限在各路由里手工重复（`admin_*.py` 里 `_require_admin(current_user)` 出现 30+ 次，见 §1.3 证据）。

改为声明式：

```python
@router.post("/releases/{id}/publish", dependencies=[Admin, Audit("release.publish", "release")])
```

四件事：`Page`（统一分页契约）、`@Audited`（声明式审计）、`@cached`、`Permission`（见 §C3）。

**安全价值**：声明式依赖让"漏写鉴权/漏写审计"变成可测试的矩阵问题（§D2），而不是靠人肉 review。

### A4 计划治理

- A4-1 新建 `docs/design/plan-registry.md`，登记 v1–v8 与 `plan.md`，逐条标注 active / superseded / archived。
- A4-2 `docs/dev/README.md` 顶部加"两个入口"：执行入口 `plan.md`，登记入口 `plan-registry.md`。
- A4-3 一次性把 v4.0 §5（Admin 体验）与 `plan.md` Phase 5 的重复项对账，重复项以"实施在 React 期，Vue 期平移"处理，避免做两遍。

---

## 4. 设计 B · 旧代码退役与归档

### B1 分类矩阵

| 类别 | 定义 | 处置 | 前置证据 |
| --- | --- | --- | --- |
| **D 死代码** | 无任何 import / 构建 / CI / 文档引用 | 直接删（单独 commit） | `knip` + `rg` 引用计数 = 0 |
| **F 冻结待退役** | 仍被引用，但已被替代物覆盖 | 打 tag + 归档说明 → 等替代验证完成后删 | E2E/视觉对账通过 |
| **K 保留** | 有独立生命周期或历史价值 | 不动，或移入 archive | 明确写出保留理由 |

**判定工具与它的坑（重要）**：`knip.json` 存在，但 knip **不在任何 package.json、也不在 `pnpm-lock.yaml`**——只能 `pnpm dlx`（命令硬编码在 `dependency-governance.json:5-19`，已接 CI job）。两个前置：①需联网；②必须 `export VITE_API_BASE_URL` 等，否则 `apps/web/src/lib/deployment.ts:87` 在配置导入期抛错，knip 以 `analyzer_exit_nonzero` **假报 unused**。更关键：`knip.json` 的 `ignore` 含 `apps/*/src/components/**`、`exclude` 含 `files/exports/types`、另有约 30 条 `ignoreDependencies`，所以**它不会把 components 目录报成死代码** ⇒ 不得作为 D/B 类判定的唯一依据，必须配 `rg` 入站引用扫描。

### B2 退役四阶段（每阶段可独立回滚）

```text
FREEZE   冻结：禁止新增 import，写入 eslint 守卫 + 文档
   ↓
ARCHIVE  归档：git tag（retire/<name>-frozen）+ docs/archive/<name>.md（为什么、替代物、回滚法）
   ↓
DELETE   删除：单独 commit，附删除清单与体积；CI 全绿
   ↓
VERIFY   验收：至少跨 1 个发布周期无回滚请求 → 删除 tags 外的残留配置/脚本/依赖
```

硬规则（沿用 `docs/dev/architecture-and-deployment.md:98-102` 的既有纪律 + `upgrade-2026-08.md:45-49` 的 `packages/ui` 先例）：

- 删除前必须确认"无生产或测试引用"；
- 一次 commit 只删一类，不混合重构；
- 删包必须同时删：`package.json` 依赖、turbo/pipeline 引用、lockfile 条目、eslint/tsconfig 路径映射、CI job、文档引用；
- 历史文档/ADR **不删**，进 `docs/archive/`。

### B3 批次建议（由外向内，先低风险）

| 批次 | 内容 | 前置 | 风险 |
| --- | --- | --- | --- |
| **B0 仓库卫生** | A 类（已 ignored、删了不进 diff）：`dump.rdb`（152 M）、`.deploy/`（3.8 G）、`.turbo/`（284 M）、`pages-dist/`（36 M，**是 Pages 上传输入**，删后需重建）、`artifacts/`、`.validation/`、`.mamba-root/`、`.pnpm-state/`、`appendonlydir/`、`eslint_out.txt`、`tsc_out.txt` | 确认可再生成 | 低 |
| **B0.5 真丢风险** | `.slim/deepwork/full-stack-upgrade.md` 先 `git add -f`（唯一未入库且不可恢复的候选） | — | 低 |
| **B1 已死文件** | ⓐ `apps/web/src/lib/*` 已删未提交的 8 文件落 commit；ⓑ tracked 但零消费者：`packages/motion`（任何 package.json 的 deps 均无）、`docs/agent-state/`（零入站引用）、`ui-r/`、`recreations/`、根 `tests/`（仅 Makefile 引用，而 Makefile 不被 CI 调）；`web-ui.tsx` 与 `packages/ui` 已删 ✅ | `rg` 引用 = 0 | 低 |
| **B2 包级** | 剩余项：`packages/motion` 的归属裁决（零消费者，但可能与 React 期动效绑定） | 引用 = 0 | 中 |
| **B3 应用级** | `apps/web`（React 门户）整体退役 → 保留 tag | Phase 3 完成 + 双站点 E2E 对账 + Phase 7 | **高** |
| **B4 应用级** | `apps/admin`（React 后台）退役；同时删 AntD-React、React Router/Query 适配、ECharts | Phase 5 + 治理面已迁 Vue | **高** |
| **B5 配置/脚本** | 旧死配置、`dev:web`/`build:web`/`build:ssg`/`build:admin` 等 root script、已无消费者的 manualChunks、可选 ECharts CDN 分支 | B3/B4 完成 | 中 |

**删除前必须改的调用点（已扫描，避免"删了才发现"）**

- 删 `apps/web` 前，按顺序处理：`scripts/check_web_query_keys.py:10-14`（硬编码 5 条 web 路由文件）→ `check_artifact_headers.py:115` → `build-pages-artifact.sh:46,62` → `verify-frontend-artifacts.sh:53` → `build-static-apps.sh:35` → `check-bundle-size.sh:22` → `smoke.sh:168,262` → `start-cloud-dev.sh:456` → 根 `package.json` 的 4 条 web script（root 内 `rg vue package.json` 为空）→ `README.md:11`。
- 删 `apps/admin` 前：`build-static-apps.sh:36`、`check_artifact_headers.py:109`、`check_admin_content_architecture.py:9`、`test_platform_delivery_contracts.py:199,262`、`test_ci_job_contracts.py:928+`。
- **闸门**：`docs/dev/pi-agent-refactor-prompt-2026-09-23.md:55,69` 明确 G1–G4 完成前禁止"删除 React/ECharts"，与 Phase 7 一致。
- **归档惯例可直接复用**：分支名 `archive/<主题>-<日期>-<sha>`（已存在 `origin/archive/pre-vue-refactor-2026-09-22-bef6db6`）。现有 tag 只有 `0.1.2`/`v2.0.0`，ADR 0001–0007 无 supersede 约定，仓库无 `archive/` 目录 ⇒ 随 A-02 补一条归档约定进 ADR。
- **快照前提**：212 处未提交改动横跨 api/mcp-server/web-vue/admin，`plan.md`、`pnpm-lock.yaml` 均当日被改；只给 HEAD 打 tag 会丢 ⇒ 归档前必须先落 commit。

**B3/B4 的硬闸门**：`apps/web` 删除必须晚于"Vue 门户 E2E 全量对账 + 双站点产物隔离门禁通过 + 一个发布周期无回滚"；`apps/admin` 同理。**不允许"边迁边删"**。

---

## 5. 设计 C · Admin 全权治理台

目标不是"给 admin 加几个页面"，而是让它成为**平台治理面**：账号、权限、会话、审计、危险操作全部可在此闭环，且每个动作都有审计与二次确认。

### C0 目标能力矩阵

| 域 | 现状 | 目标 |
| --- | --- | --- |
| 内容 / 发布 / 导入 / 媒体 / 设置 | ✅ 已有 | 保持，接声明式审计 |
| 用户 | ❌ | 全生命周期：邀请/创建、改资料、禁用/启用、锁定/解锁、重置口令、软删/恢复、角色变更 |
| 角色权限 | ⚠️ 模型有、界面无 | 角色列表、权限矩阵（只读可见）、授予/回收、变更预览与审计 |
| 会话凭据 | ⚠️ 表有、无管理 | 在线会话列表、单条撤销、强制登出、全部登出（token generation） |
| 审计 | ⚠️ 只读查询 | 覆盖矩阵、完整性校验、导出、保留策略配置、异常检测视图 |
| 危险操作 | ⚠️ 直接执行 | 影响预览 + 二次确认 + 可选四眼 + 撤销入口 |
| 平台状态 | ⚠️ 部分 | 依赖健康、迁移版本、feature flag 集中开关（已有 features/plugins API） |

### C1 数据模型增量（Alembic，均可逆）

- `users`：补 `password_changed_at`、`must_change_password`、`disabled_reason`、`token_generation`(int，用于全端登出)、`mfa_secret`/`mfa_enabled`/`mfa_recovery_codes`（加密或哈希存储）。
- 新表 `user_invitations`（token_hash、email、role_id、expires_at、created_by、accepted_at）。
- 新表 `user_sessions`（或直接以 `refresh_tokens` 聚合视图呈现，避免第二真源）——**裁决：以 `refresh_tokens` 为准，加 `user_agent`/`ip`/`last_seen_at` 三列**。
- `api_tokens`（可选，见 C4）。
- `audit_logs`：补 `prev_hash`/`entry_hash`（链式防篡改）、`request_id`、`actor_roles` 快照。

### C2 用户生命周期（API + 页面）

```
邀请 → 待激活 → 激活 → 正常 ─┬→ 锁定（失败/管理员）
                              ├→ 禁用（管理员，含原因）
                              └→ 软删（保留审计与作者归属）
```

规则：

- **管理员创建 ≠ 公开注册**：`POST /admin/users`（直接设初始口令 + 强制改密）与 `POST /admin/users/invite`（一次性链接）。现状是公开自助注册且**角色被服务端固定为 viewer**（`api/v1/auth.py:115-136`），而配置项 `feature_registration_enabled`（`core/config.py:304`）**无任何引用、关不掉** —— C-01 需一并接线。
- **自我保护**：不能禁用/降级自己；最后一个 administrator 不可降级（服务端断言 + 测试）。
- 禁用立即生效（`get_current_user` 已回库校验 `is_active`，无需等 token 过期）；同时 `token_generation += 1` 使 refresh family 全失效。
- 重置口令：管理员触发 → 生成一次性 token（`password_reset_tokens`）或直接设临时口令 + `must_change_password`。
- 一切变更写审计，含 old/new 值（复用 `log_action` 的 `old_value`/`new_value`）。

### C3 角色与权限模型

保留 10 个角色（`core/security.py:122-137`）与现有显式授权矩阵，**不做角色爆炸**。增量：

- **C3-1 权限数据化**：把 `_ROLE_GRANTS` 从硬编码映射迁到 `roles.permissions`（JSONB）并加缓存；迁移后 `has_role` 读表，`Role.permissions` 从装饰变成真源。
- **C3-2 命名空间化权限键**：`content.write`、`import.submit`、`release.publish`、`release.rollback`、`user.manage`、`role.manage`、`session.revoke`、`audit.read`、`settings.write`、`dangerzone.*`。
- **C3-3 默认 fail-closed**：新 admin 端点默认需要 `administrator`，显式降级为细分权限；用测试断言"每个 admin 路由都有权限声明"。
- **C3-4 前端角色感知**：`/auth/me` 返回 `roles` + 有效 `permissions`；`AuthUser` 增加这两项；侧栏/按钮据此渲染；**要点：前端只做可见性，服务端仍是权威**。
- **C3-5 危险权限分离**：`release.publish`/`release.rollback`/`user.manage` 单列，允许"内容编辑者不能发布生产"这类最小权限组合落地。

### C4 会话与凭据治理

- 在线会话页：按用户列出 refresh family（创建时间、最近使用、UA、IP、是否撤销）→ 单条撤销 / 该用户全部撤销。
- 强制登出：置 `token_generation`，`get_current_user` 比对 token 内 `gen` 声明，不匹配即 401（改动小、语义清晰）。
- 可选 `api_tokens`：面向 MCP / 脚本调用（当前 MCP 与脚本的认证方式需在实施前核实），仅存哈希、可设 scope 与过期。

### C5 审计强化（安全与合规的关键）

- **C5-1 声明式覆盖**：复用已存在的 `core/audit_policy.py:declares_audit`（当前只是元数据、只被 `admin.py` 消费），补运行时接线使其真正落库，并由守卫断言"写路由必有声明"；配覆盖矩阵表 `端点 × 是否审计`，无遗漏才算过。
- **C5-2 防篡改**：`audit_logs` 追加 `prev_hash`/`entry_hash`（`hash(prev_hash + 规范化内容)`）+ 数据库层禁止 UPDATE/DELETE（触发器或权限收回）；`cleanup_old_audit_logs` 改为"按分区/归档"而非直接 delete。
- **C5-3 可观测**：审计异常视图——同账号短时间多 IP、非工作时间高权限操作、批量删除、连续失败登录。
- **C5-4 导出与留存**：已有 export/export-excel（`admin.py:432,530`），补"导出也写审计"与保留期配置（默认从 180 天提升为可配，安全类事件永久）。

### C6 危险操作防护

| 操作 | 防护 |
| --- | --- |
| 发布 / 回滚 release | 影响预览（数据集、记录数、当前 active）+ 输入 release 名确认 + 审计；回滚给出一键撤销 |
| 删除 / 归档 media、page、news | 引用计数检查（已有）+ 明确"归档而非硬删"语义 |
| 批量导入 / 重建索引 | 预估耗时与影响范围 + 可取消 |
| 用户禁用 / 降级 | 影响预览（是否最后管理员）+ 二次确认 |
| 设置变更 | 修订历史 + diff + 回滚（`system_setting_revisions` 已有） |

四眼（可选开关）：`release.publish` 与 `user.manage` 支持"提交 → 他人批准"；不默认开启，先保证单人路径顺畅。

### C7 后台自身防护

- 独立 origin（已具备） + Cloudflare Access / 内网 ACL（nginx 已有私网 allowlist）→ 文档化为"三选一"部署档位。
- Admin 站点 CSP：`default-src 'self'`、`connect-src` 精确列举 API origin（构建期注入，参照 `apps/admin/vite.config.ts` 已有的 headers artifact 机制）。
- 会话策略：空闲超时（前端）+ 绝对超时（refresh 7 天）；并发会话上限可配。
- 登录策略：失败锁定（已有）+ 管理员可见"近期失败登录"。

### C8 落地路线（关键裁决）

**矛盾**：治理面功能越早越好（G-01/G-02 高风险），但 Vue Admin（`plan.md` Phase 5）依赖 Phase 3/4 完成，等待窗口以月计。若等 Vue 再补用户管理，等于把高风险敞口拖到迁移末尾。

裁决：

- **后端 API 先在现阶段实现**（与前端框架无关，一次投入长期复用）：`/admin/users`、`/admin/roles`、`/admin/sessions`、审计增强。
- **前端在 React Admin 落地最小集**，写法上遵守三条"可平移"纪律：① 全部数据访问走 `packages/api-client`；② query key 用 `packages/query-keys` 工厂；③ 页面只由"列表 + 表单 + 抽屉"构成，不引入 React 专有抽象。
- **不做 UI 大重构**：React 期的视觉/交互重构交给 v4.0 §5 与 Vue 迁移，治理页只求可用与可平移。
- Vue Admin 期（Phase 5）**平移而非重写**：先迁 shell 与治理页，再迁内容/导入等重页面。

分批：

| 批次 | 内容 | 时机 |
| --- | --- | --- |
| P0 | `/auth/me` 返回 roles/permissions + 前端按权限渲染；用户最小 CRUD（列表/创建/禁用/启用/重置口令/改角色）；会话撤销；声明式审计覆盖 | 立即可做 |
| P1 | 角色权限矩阵页、邀请流、审计 hash 链与异常视图、危险操作四眼、MFA | 与 Phase 2/3 并行 |
| P2 | 平移进 Vue Admin；Admin CSP、空闲超时、SSO 档位文档化 | Phase 5 起 |

---

## 6. 设计 D · 安全加固（分层）

原则：**已有资产不重做，只在缺口处加层**；每条改动都必须有可机器验证的负向测试，"配置正确"不算证据。

### D1 认证强度

| 项 | 设计 | 验收 |
| --- | --- | --- |
| MFA（TOTP） | `users.mfa_*` 字段 + `/auth/mfa/enroll|verify|disable`；管理员可强制 | 开启后仅口令登录失败；恢复码可用一次 |
| 口令策略 | 长度下限 8 → 12（新口令）、扩充弱口令表、可选泄露口令检查 | 单测 + 迁移期兼容策略 |
| 登录限流 | 账号维度锁定（已有）+ IP 维度 + 全局阈值；失败次数与锁定时间由设置项控制 | 并发爆破测试 |
| 会话策略 | 空闲超时（前端心跳）+ 绝对超时（refresh 7 天可配）+ 并发上限 | 超时后 refresh 失败 |
| 后续可选 | WebAuthn / SSO（Cloudflare Access 前置，不替换内部认证） | 文档化档位 |

### D2 授权正确性（比"加权限"更重要的部分）

- **D2-1 声明完整性测试**：遍历 `app.routes`，断言每个 `/admin/*` 路由都挂了权限依赖；新增未声明路由即 CI 失败。
- **D2-2 越权负向矩阵**：`角色(10) × admin 端点组` 的允许/拒绝表，逐格断言。当前 `_require_admin` 手工调用 30+ 次，靠人肉 review 已接近极限。
- **D2-3 数据化权限生效**：`has_role` 改读 `roles.permissions`（C3-1）后，补"权限变更立即生效"测试。
- **D2-4 `token_generation`**：强制登出后旧 access token 立即 401（而非等 15 分钟）。
- **D2-5 fail-closed 默认**：新端点不带权限声明默认按 `administrator` 处理，显式放宽才下调。

### D3 运行时（前端 / 边缘）

| 项 | 现状 | 动作 |
| --- | --- | --- |
| CSP（web / admin / jbrowse） | **比预想更成熟**：web 的 `_headers` 在构建期由 `finalize-csp.ts` 改写为逐页 sha256 并集（script-src 已无 `unsafe-inline`、生成器 fail-closed）；admin 为 `script-src 'self'`；仅 `style-src` 仍含 `unsafe-inline`；门禁 `check_nginx_security_headers.py` + `check_artifact_headers.py` 由 `verify-frontend-artifacts.sh:62,65` 执行 | ① 补齐 web-vue 的等价体系；② 收敛 `style-src`；③ 给 gh-pages 路径补头（Pages 不读 `_headers`） |
| **CSP（web-vue）** | **缺失**：无 `apps/web-vue/public/`、无 `_headers`、无 CSP 声明；`verify-vue-site-variant-artifacts.sh` 也不查安全头 | 平移 web 的 CSP 体系并纳入产物 gate |
| CSRF | `/auth/refresh`、`/auth/logout` 已校验 Origin（`core/csrf.py`） | 扩展到一切依赖 cookie 的状态变更端点；文档说明"Bearer 不受影响" |
| 限流 | `core/ratelimit.py` 存在（覆盖面待核实，见 §10） | 分级：登录 / 昂贵工具（BLAST、富集）/ 上传 / 导出 |
| 上传 | presign + `/complete` 服务端 `head_object` 复核 size/content-type/SHA-256（`services/presign.py:233-327`，上限 500 MiB）。⚠️ **`docs/dev/admin-architecture.md:100` 写的"文件魔数"在实现中不存在**：content-type 是客户端声明值做相等比对 | 补魔数嗅探 + "上传也写审计" |
| XSS | 后端 bleach/清洗（清洗链待核实） | 富文本渲染统一走单一 sanitize 入口 |

### D4 数据与站点隔离回归

`docs/dev/pi-agent-hard-constraints.md` H01–H12 是权威约束，本方案只加两条：

- **D4-1**：admin API 的 public 视图不得泄漏 `internal_id`（与 H02 同源的负向测试）。
- **D4-2**：internal 站点 API 的 `private, no-store` 与 401 边界（`architecture-and-deployment.md:109-114` 已有验收步骤）纳入 CI，而非只写在文档里。

### D5 供应链与秘密

- 已具备：Trivy、SBOM、cosign 签名、digest 引用、PR 不持发布凭据。
- 补：仓库级 secret 扫描（pre-commit + CI）、`.env.example` 每条标注"必须人工设置 / 有默认值 / 开发专用"、弱默认值启动告警（已有校验，补告警）。

### D6 安全门禁化（T9 落地）

把上述负向测试收进一个必需 CI job（`security-regression`）：

```
登录锁定 / CSRF 拒绝 / CORS 拒绝 / 越权矩阵 / token_generation /
泄漏扫描 / 上传校验 / CSP 头断言 / secret 扫描
```

`plan.md` T9 的定义不变，本方案只是把"有哪些用例"补全。

---

## 7. 任务总表

工作量单位：人日。**每条必须有验收证据，否则不计完成**（沿用 v6.0 §8 纪律）。

### A · 架构收敛

| ID | 任务 | 依赖 | 量 | 验收 |
| --- | --- | --- | --- | --- |
| A-01 | 冻结声明 + `no-restricted-imports` + 前端冻结守卫脚本 | — | 0.5 | 在 `apps/web` 新增文件时守卫告警/失败 |
| A-02 | `docs/design/plan-registry.md` + README 双入口 | — | 0.5 | 现有方案全部登记，状态无"未知" |
| A-03 | v4.0 §5 与 `plan.md` Phase 5 重复项对账 | A-02 | 0.5 | 对账表 + 裁决行 |
| A-04 | 声明式权限依赖（`Permission`） | — | 2 | D2-1 测试通过 |
| A-05 | `check-architecture.py` 扩展（import 方向、双栈、ORM 边界） | A-01 | 1.5 | 人为跨层 import → CI 失败 |

### B · 旧代码退役

| ID | 任务 | 依赖 | 量 | 验收 |
| --- | --- | --- | --- | --- |
| B-01 | 仓库卫生批次（`.slim`、`cache` 补 ignore；未跟踪归类） | — | 0.5 | `git status` 无意外文件 |
| B-02 | 已删未提交的 8 个 `apps/web/src/lib` 文件落 commit | — | 0.2 | 引用计数 0，构建通过 |
| B-03 | `web-ui.tsx` 收尾核查（**已确认不存在、引用 0，仅登记**） | — | 0.2 | `rg "lib/web-ui"` 0 命中 ✅ |
| B-04 | `packages/ui` 退役确认（**已不存在**）+ `packages/motion` React 适配层裁决 | — | 0.5 | 无残留引用 |
| B-05 | `apps/web` 退役（对应 Phase 7） | Phase 3 + 对账 | 2 | 双站点产物 diff、E2E 全绿 |
| B-06 | `apps/admin` + AntD-React + ECharts 退役 | Phase 5 | 3 | 同上 |
| B-07 | 归档约定进 ADR（`archive/<主题>-<日期>-<sha>` 分支 + tag 规则 + supersede 约定） | — | 0.5 | ADR 落地，B-05/B-06 依此执行 |
| B-08 | 归档前把工作区 212 处未提交改动分批落 commit | 需用户确认分批 | 1 | 归档 tag 覆盖全部有效工作 |

### C · Admin 治理台

| ID | 任务 | 依赖 | 量 | 验收 |
| --- | --- | --- | --- | --- |
| C-01 | `users` 模型增量迁移（可逆） | — | 1 | upgrade/downgrade 通过 |
| C-02 | `/admin/users` API（CRUD/禁用/解锁/重置/改角色） | C-01 | 3 | 正向 + 边界（最后管理员保护） |
| C-03 | `/auth/me` 返回 roles/permissions；前端按权限渲染 | A-04 | 1.5 | 不同角色登录侧栏差异可见；服务端仍拦截 |
| C-04 | 用户管理页（列表/详情/抽屉表单） | C-02 | 3 | 平移动清单已列 |
| C-05 | 会话治理 API + 页（撤销 / 强制登出）；可复用已有 `auth_service.revoke_all_user_tokens` | C-01 | 2 | 撤销后旧 token 立即 401 |
| C-06 | 角色权限矩阵（数据化 + 只读矩阵页） | A-04 | 3 | 权限变更即时生效测试 |
| C-07 | 审计：声明式覆盖 + 覆盖矩阵测试 | A-04 | 2.5 | 未审计端点为 0 |
| C-08 | 审计防篡改（hash 链 + 禁改 + 归档保留） | C-07 | 2 | 篡改一行即校验失败 |
| C-09 | 审计异常视图 + 导出即审计 | C-07 | 2 | 4 类异常可复现 |
| C-10 | 危险操作确认/影响预览/四眼 | C-02 | 2.5 | 每类危险操作有确认与审计 |
| C-11 | 邀请流 + 忘记口令 | C-02 | 2 | 一次性 token 过期/复用拒绝 |

### D · 安全加固

| ID | 任务 | 依赖 | 量 | 验收 |
| --- | --- | --- | --- | --- |
| D-01 | 越权负向矩阵测试（10 角色 × 端点组） | A-04 | 2 | 逐格断言 |
| D-02 | 声明完整性 + fail-closed 默认 | A-04 | 1 | 未声明路由 CI 失败 |
| D-03 | MFA（TOTP + 恢复码） | C-01 | 3 | 注册/校验/关闭/恢复码用例 |
| D-04 | 口令策略升级 + 弱口令表扩充 | — | 1 | 单测 + 兼容策略 |
| D-05 | 登录限流补 IP / 全局维度 | — | 1 | 爆破测试 |
| D-06 | web-vue CSP / `_headers` 接入产物 gate | — | 2 | 产物断言 + 头检查脚本 |
| D-07 | 收敛 `style-src` 的 `unsafe-inline`（script-src 已哈希化 ✅） | D-06 | 1.5 | 无 inline 样式被拦；E2E 通过 |
| D-08 | CSRF 覆盖扩展 + 限流分级 | — | 1.5 | 负向用例 |
| D-09 | secret 扫描入 CI + `.env.example` 标注 | — | 1 | 注入假 secret 即失败 |
| D-10 | `security-regression` CI job 汇总 | D-01…D-09 | 1 | job 必需、失败即红 |
| D-11 | **注册 `RateLimitMiddleware` 或显式删除**（消除"死限流"） | — | 0.5 | 全局限流生效或明确只剩两处 |
| D-12 | 审计清理进 `beat_schedule`（改分区/归档保留） | C-08 | 1 | 日任务可见、行数不再只增 |
| D-13 | React 双变体注入逐变体 origin + 哨兵扩到 4 个 | — | 1 | 注入错 origin 时门禁失败 |
| D-14 | gh-pages 路径安全头策略（Pages 不读 `_headers`） | — | 0.5 | 或代理注入、或限定用途并记录 |
| D-15 | 上传魔数嗅探（图片类）+ 分类体积上限 | — | 1 | 伪造 content-type 的样本被拒 |
| D-16 | Trivy 加 `misconfig,secret` 扫描；`.trivyignore` 逐条理由 + 复核日期 | — | 0.5 | 逐条有 owner/到期 |
| D-17 | 鉴权/限流告警（登录失败率、401/403 突增、限流触发） | — | 0.5 | 告警可触发 |

合计：A ≈ 5d、B ≈ 8d、C ≈ 24.5d、D ≈ 20d ⇒ **约 57.5 人日**（单人 ≈ 11–12 周；两人并行 ≈ 6 周）；其中 A-01/A-02/B-01/B-02/B-07/D-06/D-11/D-12 可立即并行开工。

---

## 8. 里程碑与验收

| 里程碑 | 内容 | 通过标准（机器可验证） |
| --- | --- | --- |
| **M0 · 止血**（第 1 周） | A-01、A-02、A-04、B-01、B-02、D-02 | 冻结守卫生效；权限声明完整性测试通过；`git status` 干净 |
| **M1 · 账号可管**（第 3–4 周） | C-01…C-05 | 能在后台完成"创建用户 → 给角色 → 禁用 → 强制登出"，每步可在审计中查到 |
| **M2 · 权限最小化**（第 6–8 周） | C-06、C-07、C-08、D-01 | 越权矩阵全绿；审计不可篡改验证通过 |
| **M3 · 安全加固**（第 8–12 周） | D-03…D-10 | `security-regression` 为必需 job 且全绿；MFA 可用 |
| **M4 · 退役收口** | B-03…B-06 | 删除后所有 gate + E2E 通过，且一个发布周期无回滚 |

**不做 / 延后**：把 Admin 立刻重写为 Vue（等 Phase 5）；引入外部 IdP 替换认证；Rust 化（保持 `plan.md` Phase R 门槛）。

---

## 9. 风险与回滚

| ID | 风险 | 影响 | 缓解 |
| --- | --- | --- | --- |
| R1 | 治理面在 React 上做，迁移时变"第二遍" | 返工 | C8 三条平移纪律 + 平移动清单（C-04 验收项） |
| R2 | 权限数据化触及全部鉴权路径 | 全线 403 / 误放行 | 先新旧双跑并断言一致，再切真源 |
| R3 | 审计 hash 链带来写入开销 | 写入变慢 | 只对安全关键动作强制，按事务批量计算 |
| R4 | 删 `apps/web` 时仍有隐藏引用（脚本 / MCP / E2E） | 构建碎 | "引用计数 = 0"证据 + grep 清单入 PR |
| R5 | MFA 开启后管理员自锁 | 无法登录 | 恢复码 + 应急关闭开关 |
| R6 | 126 个未提交改动与退役批次交叉 | 冲突 / 误删 | 退役批次独立 commit；删除前留 `git status` 快照 |
| R7 | web-vue CSP 与 SSG / inline 引导脚本冲突 | 白屏 | 先 report-only，再强制 |

回滚：每项改动独立 commit；迁移全部可逆（Alembic downgrade）；删除类保留 tag，回滚 = 恢复 tag + revert 单 commit。

---

## 10. 待核实清单（实施前必须补）

1. 昂贵端点（BLAST / 富集 / 导出 / 上传）是否已限流；全局 `rate_limit_per_minute` 取值与维度是否合理。
2. 前端 renderer 侧是否对富文本二次 sanitize（服务端 `core/sanitize.py` 已核）。
3. admin 前端 E2E / 视觉测试覆盖度（决定 §B5 删除的验证强度）。
4. `pnpm build`(turbo) 是否会实跑 web-vue 的 build（glob 与 script 都指向"会"，未实跑）；`pnpm-lock.yaml` 中 web-vue 依赖是否落盘。
5. `packages/motion`、`packages/genome-view-model` 在 Vue 主线下的复用/重写裁决。
6. 生产是否真的启用了 Cloudflare Access / 内网 ACL（部署文档中为可选）。
7. 是否已有 web↔vue 页面级对账清单（B-05 依赖）；`verify-vue-site-variant-artifacts.sh` 已核其存在与断言规模。
8. 审计查询/导出是否已含 `ip_address`、`actor_roles`（C5-4 需要）。
9. 每个 Alembic revision 是否都有 downgrade 用例（当前只见零散覆盖，未见强制门）。
10. ~~knip 是否可运行~~ → **已核实**：需 `pnpm dlx` + 联网 + 环境变量，且 `knip.json` 忽略 `apps/*/src/components/**`，只能作辅助判据。

---

## 附录 · 证据与文件地图

| 主题 | 文件 |
| --- | --- |
| 执行主线 | `plan.md`（Phase 1–7、T0–T11、subagent lane 规则） |
| 设计素材 | `docs/dev/optimization-master-plan.md`、`platform-optimization-plan.md`（§2.2 横切管线化、§5 Admin 体验） |
| 数据契约 | `docs/dev/database-core-contract.md`、`docs/dev/pi-agent-hard-constraints.md`（H01–H12） |
| Admin 现状 | `docs/dev/admin-architecture.md`、`apps/api/app/api/v1/admin*.py` |
| 认证授权 | `apps/api/app/core/security.py`、`csrf.py`、`config.py`、`api/v1/deps.py`、`api/v1/auth.py`、`models/auth.py` |
| 审计 | `apps/api/app/core/audit.py`、`audit_policy.py`、`audit_inventory.py` |
| 站点隔离 | `docs/dev/architecture-and-deployment.md:104-114`、`scripts/test_site_artifact_isolation.py` |
| 头 / CSP | `infra/nginx/conf.d/security-headers*.inc`、`scripts/check_nginx_security_headers.py`、`scripts/check_artifact_headers.py` |
| 供应链 | `scripts/build-release-image.sh`、`release-contract.golden.sh`、`.trivyignore` |

> 变更本方案时：同步更新 §7 任务表与 `docs/design/plan-registry.md`；若与 `plan.md` 冲突，以 `plan.md` 为准并回写。