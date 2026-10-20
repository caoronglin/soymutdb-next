# SoyMutDB 项目状态（2026-10-17 追加验收）

## 当前状态（2026-10-17）

本节与 [非 Docker 追加验收](native-validation-20261017.md) 是本轮状态入口。下方 2026-10-05 及更早记录作为历史快照保留，其中版本、测试数字、环境缺口和“待执行”描述不作为当前结论；未重新核验的旧计划不自动结项。

| 范围 | 最近证据 |
| --- | --- |
| 工具链与数据主链 | Node 26.10.0 / pnpm 12.11.2 / Python 3.15；PostgreSQL 为权威库，ClickHouse 仅用于历史迁移 |
| 客户端与前端（10-17） | fresh OpenAPI 与手写路由三类 drift 均为 0；工作区 lint/typecheck/test 36/36 任务，1083 tests |
| 后端全量（10-16） | API 2326 passed / 3 历史驱动场景 skipped；Worker 657 passed / 0 skipped；MCP 66 passed / 0 skipped。历史驱动另在 Python 3.14 专用通道 33 passed；详见 [整体验收](fullstack-validation-20261015.md) |
| 本轮 Worker 回归（10-17） | 信号指标、配置、延迟导入和发布传输共 44 passed；这是切片，未冒充重新执行全量 |
| 原生服务业务链 | 真实 PG / Redis / 独立 Worker / S3 导出成功，公开文件不含私有记录、其他 assembly 或草稿 release；API 入口使用进程内 ASGI HTTP transport |
| 灾备 | PG 77 表 + 六桶 9 对象恢复到隔离实例；独立校验 115 PASS / 0 FAIL / 0 SKIP；策略篡改反向验证拒绝；合同回归 82 passed |
| 历史回填 | 隔离真实服务完成 dry-run、5 行 apply、摘要 receipt、重复执行及三类拒绝场景；未操作生产历史数据或生产活动 release 指针 |
| 统一合同门禁 | 334 passed + 5 subtests，环境套件 10 passed，无跳过层；最后恢复提示文字调整后另跑 2 项窄回归通过，未宣称其后重跑全量 |

生产历史回填与切换仍需目标环境、源信息、release/assembly 映射与冻结确认；异地上传和跨机灾备未配置或验收。Docker 镜像/Compose 运行按用户要求排除。全部本轮临时服务已停止，保留验收数据、备份和脱敏证据；未提交、推送或部署。

## 2026-10-17 夜：多 subagent 修复与性能轮

本轮先复核基线，再只修有失败证据的红色。基线：工作区 36/36 任务；API **2325 passed / 4 skipped**（Python 3.15 + 本机 PostgreSQL 16.15 专用库，59.70 s）；Worker 647 passed / 20 环境性 skipped；MCP 63 passed（3 项 loopback 传输用例在 DSH 沙箱内无法启动本地 HTTP 服务，属环境限制）；`pytest scripts` 出现 **1 项真实失败**（i18n 缺键），另有 1 项在全量并发构建时 15 s 超时（隔离重跑 2.15 s 通过，属本机负载偶发）。

### 修复的真实缺陷（失败→通过）

| # | 缺陷 | 失败证据 | 处理 |
| --- | --- | --- | --- |
| 1 | 管理端 Releases 详情引用 `releases.version` / `releases.description`，两个 bundle 都没有这两个键 | `test_locale_language_purity.py::test_every_translated_key_exists_in_the_bundle` FAILED | 补 zh/en 键 |
| 2 | 门户图表把 `Total` 及 tool-chart 的 6 处文案写死英文 | `check_visible_i18n_react.mjs` exit 1（baseline 0） | 迁入 `charts.*`（新增 9 键），守卫回到 0 文件 |
| 3 | Admin `motion-preference.ts` 读取一个从不写入的 localStorage 键；admin 与门户不同源，读到永远是 null，还触发架构守卫 | `check_admin_content_architecture.py` exit 1 | 删除该读取，只遵循 OS `prefers-reduced-motion`；守卫恢复通过 |
| 4 | 三个运行时前端镜像仍安装 pnpm **12.5.1**，而仓库/CI/锁文件是 **12.11.2**；`check-toolchain-pins.py` 不覆盖运行时镜像 | 负例注入后守卫原本仍 PASS | Dockerfile 全部升到 12.11.2；守卫新增运行时镜像扫描，负例现在 exit 1 |
| 5 | conda api/worker/baseline 环境与 `verify-baseline.sh` 仍是 Python **3.14**，而 pyproject 要求 >=3.15 | 实读 | 统一 3.15；legacy ClickHouse 的 3.14 通道按设计保留 |
| 6 | 运行时仍有 ClickHouse 命名/导入残留：`stats.py` / `admin.py` 的 `ch_service` 实际是 PostgreSQL 服务；`popgen_service` 文档声称 ClickHouse；`clickhouse_service` 顶层 import 在无 `clickhouse-connect` 的原生环境会连带 API router 导入失败 | 代码审计 + `check_architecture.py` | 统一改名为 `variant_service`；`clickhouse_service` 改延迟导入并标注 legacy/test surface（infra schema 契约仍引用它，故不删除）；API 全量仍 2325 passed |
| 7 | 测试 i18n 替身只返回 key，导致 i18n 化后的图表/搜索断言看不到真实英文；同时 `lib/i18n.ts` 把运行时资源与 i18next 运行时耦合，mock 引入会形成 `react-i18next` 循环 | 修复 #2 后 web 单测出现 3 项真实失败 | 资源抽到无 i18next 依赖的 `lib/i18n-resources.ts`，测试替身按真实 bundle（catalog + portal/tools/home）深合并解析；4 个测试改为断言真实英文文案。**这是测试保真度缺陷，不是产品缺陷**，但也掩盖了「键存在与否看不出来」 |

### 性能（可量化）

- 自托管 HarmonyOS Sans SC 字体：每个应用 **13.07 MB → 2.81 MB（-78.4%）**，仓库共减少约 20.4 MB；新增可复现脚本 `scripts/subset-portal-fonts.py`，以及不做构建依赖的覆盖/体积守卫 `scripts/test_portal_font_subset.py`（已接入 contracts smoke）。fontTools 独立核验：zh bundle 的全部 CJK 字 **0 缺字**（覆盖 6892 码位，GB2312 一级+二级 + UI 字符集）。
- 两个应用都只对 Regular（400）发 Umi `links` preload（`crossorigin="anonymous"`，与 `@font-face` 的 CORS 取字体匹配，避免二次下载）。
- 详见 [字体子集化](font-subsetting.md)。构建产物中 `dist/{external,internal}/fonts/harmonyos` 已核实为 2,814,168 B、`apps/admin/dist` 为 2,814,160 B，三份 `index.html` 均已含该 preload link。

### 本轮复核后的门禁

| 门禁 | 结果 |
| --- | --- |
| API 全量 | 2325 passed / 4 skipped（PG16.15，59.70 s） |
| Worker 全量 | **659 passed / 8 skipped**（原生/静态 PG 库已注入：`SOYMUTDB_NATIVE_TEST_DATABASE_URL` / `SOYMUTDB_STATIC_TEST_DATABASE_URL` 用 `postgresql+psycopg2://`；8 skip = DIAMOND 7 + 2M 性能档 1，均为显式 opt-in） |
| `pytest scripts` | **492 passed / 1 skipped / 14 subtests**（88.17 s；含新增字体守卫） |
| 工作区 lint/typecheck/test | **36/36 任务**；1043 项 Vitest + 40 项 JBrowse Node tests（web 371、admin 146、api-client 184、charts 84、genome-data 121、genome-view 43、shared 49、genome-view-model 23、i18n-core 11、query-keys 11） |
| 前端制品 | web external+internal 与 admin 构建成功；artifact headers、production scan、双站隔离、chart closure（331144 B ≤ 370 KiB）、bundle size、static smoke 全 PASS；真实浏览器 a11y/布局 **10/10** |
| 合同 smoke | **338 passed + 5 subtests；环境套件 10 passed；SMOKE PASS**（90.80 s；`check-toolchain-pins.py` 已含运行时镜像负例、字体守卫已入列） |
| 已知环境限制 | jbrowse 构建在 DSH 沙箱内因 webpack Terser 的 esbuild 多进程 spawn 触发 `EAGAIN`（同一棵树里 web/admin 构建成功，属进程配额而非代码）；MCP 3 项 loopback 传输用例；Docker 镜像未验收；生产回填/切换未执行 |

注：`scripts/verify-frontend-artifacts.sh` 的整脚本在沙箱内跑不完（12 包并行 build 的 jbrowse Terser 阶段进程配额耗尽），因此按脚本的步骤逐项执行：i18n parity、web 双站/admin 构建、制品与预算门、单元测试、lint、typecheck、页面/查询/Admin 架构守卫与 OpenAPI client 契约；未跳过任何门禁步骤，失败仅来自无法创建更多进程的 jbrowse 构建。

## 2026-10-18 凌晨：第二轮（多 subagent 审计 + 清理）

本轮由三个 subagent 分别审计导入 Studio、孤儿 CDN 设置、文档真实性，Lead 复核并补做原生分析契约、死代码与构建门禁。

### 修复（失败/审计证据 → 修复）

| # | 缺陷 | 证据 | 处理 |
| --- | --- | --- | --- |
| 1 | 导入 Studio 状态机与服务端不一致：`validated` 的 draft 仍显示保存 mapping/patches/validate，draft 也能 Commit；服务端分别 409/422 拒绝 | 服务端 `import_studio.py:100-111,509-524`；新增 UI 回归在旧代码上失败 | 按 `draft` / `validated\|ready` 门控并锁定提示；成功提示不再被自身 refetch 清掉；Resume 链接按 `BASE_URL` 生成 |
| 2 | 公开 `GET /capabilities` 仍声明 `analytics: "clickhouse"`（ClickHouse 已退役为仅历史迁移源） | `DatabaseCapabilitiesResponse.analytics`；生成 client 中 10+ 处 ClickHouse 描述 | 改为 `"postgresql"`，重生成 OpenAPI/client（生成产物 ClickHouse 提及归零）；`stats.py` 日志事件改为 `stats_variant_store_unavailable` |
| 3 | 孤儿 CDN 设置：`cdn.enabled`/`cdn.url` 无任何消费者（ECharts 退役遗留），legacy 设置页仍展示 "ECharts CDN URL" | 全仓 grep：仅有定义/UI/测试，无读取方 | 删除 registry 定义、未使用 config 字段、legacy 页 CDN 卡片、domains 的 cdn revision 段与 7 个 i18n 键；settings API 测试迁移到 live 设置 + retired-section 回归 |
| 4 | 孤儿 `data.enableClickhouse` 开关（仅 legacy 设置页展示，无消费者） | registry + legacy settings，全仓无读取 | 删除 registry 定义、legacy 开关、i18n 键；settings 测试迁移到 live 设置 |
| 5 | ⌘K 命令面板仍提供 `/widgets`、`/page-builder`（ADR-0009 已退役，落到 unavailable 页）与 `/resource-catalog`（无后端不可用页）三个死目的地 | `admin-command-palette.tsx` COMMANDS | 移除这三条命令及类型成员，仅保留可执行目的地 |
| 6 | web `lib/i18n.ts` 保留无调用方的 Vue 迁移兼容导出（`t`/`setLanguage`/`currentLanguage`） | 全仓 import 只有 `useI18n`/`initI18nOnce` | 删除死导出；修复 workspace 10 个 eslint warning（memo 化派生数组、测试 `any`、未用 import） |
| 7 | `build-pages-artifact.sh` 仍导出无消费者的 `VITE_CDN_ENABLED=false`，4 份部署文档据此描述已不存在的"CDN 构建开关" | 全仓 grep 仅构建脚本 + 文档 | 删除该导出并修正 cloudflare/production-readiness/deployment-architecture 文档 |

### 顺带校正的文档真实性（subagent，均带代码证据）

`docs/dev/optimization-master-plan.md` A-04（keyset 已实现）、A-09（mapping/validate/commit 已接线，剩余 `/imports/new` 旧上传对话框与无消费者的四步组件）、A-13（ADR-0009 已退役）、A-17/A-19（已完成）、A-12（审计端点数 5 而非 6）；`project-status` 历史红灯表加 2026-10-18 关闭注记；`.ai-memory/handoff.md` 顶部新增当前 checkpoint 并标记旧章节为历史；`native-postgres-cutover`、`a04-search-keyset-continuation`、`docs/dev/README.md`、`docs/aegis/INDEX.md` 同步。

### 本轮门禁

| 门禁 | 结果 |
| --- | --- |
| API 全量 | 2324 passed / 4 skipped（60.31 s；减少的 1 项是退役 CDN 白名单组合测试） |
| Worker 全量 | 659 passed / 8 skipped（DIAMOND/2M opt-in） |
| `pytest scripts` | 492 passed / 1 skipped / 14 subtests |
| 工作区 lint/typecheck/test | 36/36 任务；1043 Vitest + 40 JBrowse Node tests |
| 合同 smoke / static smoke | contracts **338 passed + 5 subtests**、环境套件 10 passed、SMOKE PASS；static SMOKE PASS |
| 前端制品 | web external+internal、admin 构建成功；artifact/预算/双站隔离门 PASS；浏览器 a11y 10/10 |
| 明确未验证 | Docker 镜像、生产回填/切换、jbrowse 制品（沙箱内 esbuild 进程配额 EAGAIN）、真实 RUM |

## 2026-10-18 凌晨 II：mm 子代理安全 / 性能 / 前端 / 架构 / 技术栈轮

按用户指示，4 个 subagent 改用 `mm/MiniMax-M3.1-Flash-Preview`，Lead 负责决策与最终门禁。

### 安全（2 个修复 + 105 个负例测试）

| 缺陷 | 证据 | 处理 |
| --- | --- | --- |
| `POST /auth/login` 只查 `is_active` 不查 `is_deleted`：软删除账号仍能拿到 access token、refresh cookie 并写 login 审计行（`get_current_user` 与 refresh 都拒绝同一行，login 是唯一 fail-open 路径） | 新测试修复前返回 200 + Set-Cookie + 审计行 | 拒绝软删除账号，返回与 inactive 相同的 "Account is inactive"（不泄露账号状态差异） |
| `core/sanitize.py` 的 `_REL_NOOPENER_RE` 有两个洞：① `(?![^>]*\brel=)` 使作者自带的 `rel="opener"` 永远不被重写（重新打开反向 tabnabbing）；② `[^>]*>` 在属性值含 `>` 时提前结束，把 `rel="noopener noreferrer">` 注入到属性值内部，产出畸形 HTML | 探针：`<a target="_blank" rel="opener">` 原样通过；`title="a>b"` 输出 `title="a rel="noopener noreferrer">b"` | quote-aware 标签匹配 + 属性 tokenizer |

审计通过（无缺陷）：RBAC（AST 扫描全部 `admin*.py`/`import_studio.py`，无 authn-without-authz）、JWT（alg:none/错密钥/过期/篡改 roles/access-refresh 混用）、CSRF（缺失 Origin/Referer 拒绝、精确匹配非后缀）、突变体 public/internal 与 release 边界、搜索缓存键、SSRF、SQLi、上传、分析隐私、错误/日志泄漏。
**Lead 决策**：登录限流目前只在 username 或 IP 单维度上计数（可跨账号撞库）→ 下轮修双维度；通用入站限流与 API 层 CSP/HSTS 记录为设计决策（CSP/HSTS 由 nginx/制品头承担，现有守卫全绿）。

### 后端性能（2 个修复，实测）

- **基因全局搜索每查询全表扫描 `genes`**：curated-alias 的 `EXISTS` 被 OR 进文本析取，PostgreSQL 无法把含 SubPlan 的 OR 转成 bitmap 条件，0046 的三个 trigram 索引全部失效。修复为 `UNION ALL` 两个可索引分支 + 迁移 **0048** `ix_gene_aliases_alias_lower`（`lower(alias)`，CONCURRENTLY，upgrade/downgrade 与 0027/0046 同形）。
  实测（同 seed、同查询、仅谓词形状不同）：gene page **769.5 ms → 9.2 ms**，assembly 聚合 **721.2 → 6.4 ms**，`global_search` 端点 **1609 → 164 ms**；负例测试保留“旧形状仍无法命中索引”的对照。
- **首页统计 7 条串行 SQL → 2 条**（5 个标量子查询 + 1 个 release 子查询合并；剩余 1 条是 `PostgresVariantService` 自身会话）。
- 复核已正确项：cache 键包含 site variant/release/assembly/query/filters、内部响应绕过共享缓存、worker 批处理/`SKIP LOCKED`、`Gene.transcripts` 已是 `selectin`。
- 延迟（有理由）：dashboard 3→2（缓存路径收益小且会破坏两个 pinned 测试）、analytics breakdowns 4 条 GROUP BY、`variant_facts` 的 `count(DISTINCT ...)` 覆盖索引（需先按真实规模 seed 再测）。

### 前端（7 项修复/清理）

- `/resource-catalog` 是 shipped dead end：侧栏有入口、仪表盘主 CTA 指向它，二者都落到 `LegacyUnavailablePage`（无后端 API）→ 移除侧栏项、CTA 改指 `/imports`，新增 guard 解析 `App.tsx` route→component，禁止 NAV/命令面板指向 unavailable 页。
- 命令面板 100% 未翻译（~20 个硬编码英文；bundle 里已有 4 个键无人读取）→ 全部走 `t()`（21 个新键）；关闭时恢复焦点（a11y）。
- 4 张门户图表的 `tooltipFormatter={formatX()` 内联在 JSX，`ChartCanvas` 把它列入更新 effect 依赖 → 每次 render 重建 G2 图表；memo 化。
- 死代码：`AdminSidebar` 组件从未被渲染（保留 `NAV_SECTIONS` 数据）、4 个 import wizard step 文件零消费者、`settings/site.tsx` 零引用、`section-page.tsx` 2 处硬编码英文 → 删除/修复。新增 9 个测试（web 372、admin 169）。

### 架构 + 技术栈

- 死模块 0（AST 可达性：API 222 / worker 54 / MCP 3 模块全部可达）。
- 真实发现与 Lead 决策：删除 2 个无消费者的 env feature flag（`feature_blast_enabled`/`feature_seed_requests_enabled`；`feature_registration_enabled` 实际被 `auth.py` 使用，保留）；删除永久退役的 `search.external` flag 并更新设计文档；17 个无消费者 env 设置清单与 settings-registry ↔ portal content 漂移（19 个注册键无消费者 ×3、26 个 `get()` 键未注册）**留待下一轮**专项收口。
- 新增 CI 守卫：`check_retired_lane_boundaries.py`（Python import 图证明 ClickHouse 只允许 legacy/test）、`check_deprecated_api_usage.py` ratchet（补偿 pytest 全量忽略 DeprecationWarning），均带自测并接入 `verify-backend-tests.sh`。
- **技术栈更新（Lead 执行）**：react/react-dom **19.3.1**、`@tanstack/react-query` **5.104.3**、tiptap **3.32.0**、turbo **2.11.8**、eslint **10.13.0**；`@types/react(-dom)` 保持 19.3.0（registry 未发布 19.3.1）；根 `package.json` 增加 `"type": "module"`（消除持续的 Node MODULE_TYPELESS 警告）；lockfile 重建并通过 `--frozen-lockfile`；平台契约测试同步新 pin。
- **持有（需单独 ADR/迁移）**：TypeScript 7、Vite 8、Vitest 5（含 path-traversal advisory）、zod 4、pdfjs 6、i18next 26/react-i18next 17、dnd-kit 10、@gmod 家族、redis 8；Python patch（fastapi 0.143.3 / sqlalchemy 2.1.5 / api dev extra 加 `httpx2`）需先 sync uv.lock 与 venv，下轮执行。
- 安全公告：`pnpm audit` 9 项（1 high `braces` 无补丁，已有签名 reachability 接受至 2026-12-09；react-router moderate 位于 Umi 树内，`--audit-level high` 不阻塞）；`pip-audit` 0。

### 本轮门禁

| 门禁 | 结果 |
| --- | --- |
| API 全量 | **2444 passed / 4 skipped**（69.50 s；含 105 个安全负例 + 16 个性能/迁移测试） |
| Worker 全量 | **659 passed / 8 skipped**（DIAMOND/2M opt-in） |
| `pytest scripts` | 512 passed / 1 skipped / 14 subtests（含新守卫自测） |
| 工作区 lint/typecheck/test | **36/36 任务**；1067 Vitest + 40 JBrowse Node tests（web 372、admin 169、charts 84、api-client 184 …） |
| 合同/静态 smoke、前端制品、a11y | contracts 338+5 SMOKE PASS；web 双站 + admin 构建成功；artifact/预算/双站隔离 PASS；浏览器 a11y 10/10 |
| 明确未验证 | Docker 镜像、生产回填/切换、jbrowse 制品（沙箱 esbuild 进程配额）、真实 RUM、Playwright 全量 E2E（现有 dist 用 `/` base，E2E 期望 `/soymutdb-next`，需专用构建） |

## 2026-10-18 凌晨 III：Python patch / 内容契约 / 登录限流 / 通知无障碍

### 依赖与技术栈（Lead）

- Python patch 更新并同步 lockfile + 本机 venv：`fastapi 0.143.1 → 0.143.3`、`sqlalchemy 2.1.4 → 2.1.5`、api dev extra 新增 `httpx2>=2.0.0`（消除 Starlette TestClient 弃用警告）；worker venv 与 API 对齐（`pydantic-settings 2.16.0`、`alembic 1.20.0`、`ruff 0.17.1`、`asyncpg 0.32.0`）。`apps/api/uv.lock` 与 `apps/worker/uv.lock` 已更新。
- 验证：API 全量 **2444 passed / 4 skipped**（安装后首跑）。

### 内容契约（settings registry ↔ portal）

- 发现：portal 通过 `useSiteContent().get("<key>")` 读取的 **27 个键从未注册**，所以 Admin 无法编辑、服务端覆盖永远不触发。已在 registry 注册（默认值取当前英文 UI 文案，site-variant 镜像自动复制）；content 定义 131 → **157**。
- 新增 CI 守卫 `scripts/check_content_key_contract.py`（严格校验“每个字面 `get("<key>")` 消费者必须已注册”）+ `scripts/test_content_key_contract_guard.py`（5 tests，含 parser 防退化与负例），接入 `scripts/verify-frontend-artifacts.sh`。反向（注册但无字面消费者）只提供 `--report` 报告、不硬门禁——因为消费者中存在 `get(\`tool.${key}.label\`)` 这类动态键，静态“未找到字面量”会产生假阳性（本轮已实测）。当前：69 个字面消费者 0 个未注册。
- 内容/设置回归：`test_settings_registry` + `test_opt4_site_content_overrides` + `test_admin_settings` + `test_content_snapshot` **62 passed**。

### 登录限流双维度（安全）

- 原实现按 `(username, IP)` 对计数：攻击者轮换 username 时每个对子都有新计数器，单一 IP 的撞库不受限。新增 `login_ip_rate_limit_max`（默认 50/窗口）并在 `enforce` 中先消费对子预算、再消费 **per-IP** 预算；错误文案不泄露账号是否不存在。
- 新增 3 个测试：同一 IP 轮换用户名会被 IP 预算拦截；不同源地址的 IP 预算隔离；同一用户名在不同 IP 上保持独立对子预算。`test_ratelimit` + `test_auth` + `test_auth_sessions` **64 passed**。

### 管理端通知无障碍 + 单条已读（前端）

- 通知面板原用 `role="menu"` 包一个纯 `<ul>`（读屏 announce 一个没有 menuitem 的菜单），打开后焦点不进入面板、关闭不归还；且无单条已读入口（API 已支持 `POST /notifications/read {ids}`）。
- 修复：改为带 `aria-label` 的 `role="dialog"`，按钮加 `aria-haspopup/aria-controls`；打开聚焦面板、Escape 关闭并把焦点还给铃铛；未读项增加“标记已读”按钮（禁用态/失败态沿用 mutation）。新增 `admin-header-notification-bell.test.tsx`（3 tests）。
- 顺带修复 admin Vitest 的 JSX 运行时：`tsconfig` 是 `"jsx": "preserve"`，Vitest 默认回落 classic，导致仅 type-import React 的组件测试时报 `React is not defined`；`vitest.config.ts` 显式设 `esbuild.jsx = "automatic"`。admin 测试 23 files / **172 passed**。

### 本轮门禁

| 门禁 | 结果 |
| --- | --- |
| API 全量 | **2447 passed / 4 skipped**（67.41 s；含新增 3 个限流测试） |
| Worker 全量 | **659 passed / 8 skipped** |
| `pytest scripts` | **517 passed / 1 skipped / 14 subtests**（含内容契约守卫 5 个测试） |
| 工作区 lint/typecheck/test | **36/36 任务**；1071 Vitest + 40 JBrowse Node tests（web 372、admin 172、api-client 184、charts 84） |
| Playwright E2E（本机新增覆盖） | 公共套件 **31 passed / 1 skipped**；internal 套件（重写）**3 passed**；primer 套件（重写）**4 passed**；entity-detail 3 skipped（需已部署栈，按设计） |
| 合同/静态 smoke、前端制品、a11y | contracts 338+5 SMOKE PASS；static SMOKE PASS；web 双站 + admin 构建成功；artifact/预算/双站隔离 PASS；浏览器 a11y 10/10 |
| 明确未验证 | Docker 镜像、生产回填/切换、jbrowse 制品（沙箱 esbuild 配额）、真实 RUM、Playwright 全量 E2E（需 `/soymutdb-next` base 专用构建） |

### 同轮追加：knip 死代码类别恢复 + 配置清理

- `knip.json` 恢复 `files`/`exports` 两个类别（此前被 `exclude`，这正是死代码只能靠人工审计发现的原因），并保留 `types`/`unlisted`/`binaries` 排除。
- 按 knip 报告清理：删除 `apps/web/src/lib/query-options.ts` 中 **26 个无消费者工厂/常量**（534 → 90 行）、`apps/web/src/lib/format.ts` 中 3 个已被 `@soymutdb/shared/genomics` 取代的重复 helper、`site-variant.ts` 两个未用标签表、`antd-theme.ts`（web 4 个/admin 1 个）未用 token、`route-motion.tsx` 的 `FadeIn`/`CountUp`、`deep-link.ts` 聚合 default、`api-client/client.ts` 聚合 default、`tools/api.ts` 的 `getAssemblies`、`news-carousel.tsx` 未挂载的轮播组件（仅保留 `NEWS_FEATURED_KEY`）、`status-badge.tsx` 的 `canTransition`/`RELEASE_TRANSITIONS`、`config.ts` 的 `buildAssembly`、`a1-runtime.ts` 的 `createProbeChart`、`use-browser-notifications.ts` 的未用 getter、`csp.ts` 的 `APP_DIR`。
- 配置修正：`scripts/scan-ant-design.mjs` 与 `scripts/webpack/chart-*.{ts,cjs}` 加入 entry（文档化工具/被 config 动态引用）；`packages/charts/src/g2-runtime.ts` 因动态 `import()` namespace 无法被 knip 5 追踪而进入 `ignore`（有说明，测试仍覆盖）；移除 knip 提示的 3 个 ignoreDependency 与 `playwright` ignoreBinary。
- 结果：knip 在 `files`+`exports` 开启下 **exit 0**；`test_dependency_governance_contracts` 20 passed；web 372 / admin 172 / api-client 184 / charts 84 / jbrowse 40 全绿；四包 lint + typecheck 全绿；静态守卫（entry graph/vue retirement/admin arch/visible i18n）全绿。文档见 `docs/ops/dependency-governance.md` §Dead-code categories。

### 同轮追加：配置清理

- 删除 API `Settings` 中 **16 个零消费者字段**：`clickhouse_max_execution_time`、`max_sync_rows`、`blast_max_sequences`、`blast_bin_dir`、`blast_cache_dir`、`gwas_max_attempts`、`otel_enabled`、`otel_service_name`，以及整套 API 侧 SMTP 配置（邮件实际由 worker 直接读 `SOYMUTDB_SMTP_*`，API 从不发信）；`deploy/.env.example` 的 SMTP 注释同步改为“worker 读取”，`docs/ops/multi-genome-blast.md` 删除失效的 `SOYMUTDB_GWAS_MAX_ATTEMPTS` 行。
- 保留并注明 `api_workers`/`api_graceful_shutdown_seconds`（容器入口消费的环境契约）与 `s3_export_bucket`（deploy env example 保留）。
- content registry 反向清理：删除 **37 个**已注册但无任何读取方的内容键（列标签/旧导航/guide 文案等），content 定义 157 → 120；portal fallback map 同步删除 37 条；content key 守卫保持 69 个消费者 0 未注册。

### 同轮追加：Playwright E2E 恢复（此前在 React 制品上从未跑通）

- **公共站点套件**：用 `SOYMUTDB_EXTERNAL_BASE_URL=/soymutdb-next/` 构建专用制品（配置期望的 Pages 子路径）后 **31 passed / 1 skipped**。修掉 `genes.spec.ts` 的陈旧断言：结果表前 8 个列头在 i18n 迁移后由英文 catalog 渲染，而旧断言写死中文；配置已显式钉 `locale: "en-US"`，断言随之为英文。
- **internal 站点套件**：旧 spec 全部基于已退役 Vue UI 的 testids（`login-form`/`search-input`/`search-internal-row`/`mutant-detail`）与 `v-model` 交互模型，React 制品上不可能通过，且不在 CI lane → 重写为 3 个可离线运行的真实断言（root base、唯一 robots meta + deny-all robots.txt、root `/login` 表单、登录后重定向 internal `/search` 且不含公共前缀），**3 passed**。
- **顺带修复真实制品缺陷**：internal 文档同时存在 config 注入与 static-routes 注入的两个 `meta[name=robots]`（非法 head 标记，严格模式测试直接崩溃）→ `injectPageHead` 改为升级已有标签而不是追加，新增单测；internal 制品重建后确认唯一标签。
- **primer 套件**：旧 spec 按 Vue 文案（`design primers`、旧结果表、`gbrowse` 按钮）→ 按 React 页面重写（"Submit primer design"、过滤 antd measure row、`JBrowse 2` actions 按钮），**4 passed**。
- entity-detail：3 skipped（按设计需要显式 `PORTAL_BASE_URL` 的已部署栈，离线不伪造通过）。

### 同轮追加：knip `types` 类别恢复

- `knip.json` 现在只排除 `unlisted`/`binaries`，`files`+`exports`+`types` 全部报告并 **exit 0**。
- 清理 3 个无引用导出类型：jbrowse bridge 的 `LocusChangePayload`/`ErrorPayload` 改为模块内类型，web bridge 的死 `ErrorPayload` 直接删除。
- 说明见 `docs/ops/dependency-governance.md`。

### 同轮追加：文档真实性审计 + 技术栈决策 ADR

- **wiki 页面重写/订正**（`docs/wiki/` 声称只写当前事实，但内容仍停留在 Vue/ClickHouse 时代）：
  - `architecture.md` 重写：React 19 + Umi Max 4 三端、PostgreSQL 唯一运行时权威、ClickHouse 降级为 `docker-compose.legacy-clickhouse.yml` 的 `legacy-migration` 历史迁移源、Redis/MinIO 职责、共享包清单与隔离边界。
  - `applications.md` 重写：公共站/管理端按当前 React 路由分组列状态，删除 Vue 路由/`*View.vue` 引用，前端技术栈改为 Umi/webpack 生产构建 + Vitest/Playwright（Vite 仅测试工具）。
  - `api-and-ports.md`：删除 ClickHouse 运行时端口行、修正“各 Vite 配置”措辞、补全 `/gwas`、`/jobs`、`/popgen`、`/notifications`、`/seeds`、`/ontology` 等路由分组。
  - `deployment-and-ops.md`：本地无 Docker 构建命令改为 `build-sites.ts` 双站（`SOYMUTDB_EXTERNAL_*`/`SOYMUTDB_INTERNAL_*`）、preview server 指向 `dist/external`/`dist/internal`；就绪探针说明改为 PG baseline + extended Redis；备份不含 ClickHouse；迁移版本不再写死 0042。
  - `multi-instance.md`、`README.md` 同步去 Vue/ClickHouse 化；ADR-0009 加“Vue 表述为历史，决策不变”注记。
- **路径类错误修复**：`docs/dev/search-static-performance-design.md`、`docs/ops/production-build.md` 的 `scripts/build-sites.ts` → `apps/web/scripts/build-sites.ts`；`docs/design/service-worker.md` 的 `scripts/gen-sw.js` 路径；`deployment-architecture.md`/`antd6-design-system.md` 标注 Umi 迁移前路径为历史（不篡改历史文档结论）。
- **可见文案基线清理**：`scripts/visible-i18n-baseline.json` 删除已不存在的 `apps/admin/src/views/TableTemplatesView.vue` 条目（React 扫描器与遗留 Vue 扫描器共享该文件）。
- **ADR-0010（技术栈决策）**：显式记录本轮**不做**的大版本升级及原因与后续顺序：TypeScript 7（原生编译器预览）、Vite 8（生产构建实际走 Umi/webpack）、Vitest 5（1071 单测基座）、zod 4、pdfjs 6、i18next 26/react-i18next 17、dnd-kit 更大版本、jbrowse major、redis-py 8；每项给出验收门禁与升级顺序，patch/minor 继续按原流程。

### 依赖治理复核（本机）

- `pnpm audit`：1 high（`braces`，无补丁，已有签名 reachability 接受至 2026-12-09）、7 moderate、1 low——与既有接受/策略一致，无新增 high/critical。
- `pnpm deps:graphs`：**passed**（依赖图生成成功）。
- 完整 `pnpm deps:audit` 在本沙箱不可运行：uvx 分析器需要写 `~/.local/share/uv/tools`（只读），重定向 `UV_TOOL_DIR` 后仍在沙箱进程配额下中断；knip 已单独验证 exit 0、pip-audit 历史结论为 0、npm 审计如上。此项需在 CI runner 上复核。

### 同轮追加：Vitest 5 + Vite 8 升级（ADR-0011，执行 ADR-0010 第一项）

- `pnpm-workspace.yaml` catalog：`vitest 3.2.7 → 5.0.5`、`vite 6.4.3 → 8.3.4`；原先脱离 catalog 的 5 个包（api-client、genome-view-model、i18n-core、query-keys、shared）统一改为 `catalog:`。
- Vitest 5 移除 `poolOptions`：10 个 `vitest.config.ts` 全部迁移为 `pool: "forks", maxWorkers: 1`，**保留默认 per-file isolation**（首轮改成 `isolate: false` 后全局 mock/`globalThis.React` 在文件间泄漏，导致 command-palette 与 module-import-upload 套件失败；已回退该细节）。
- Vite 8 用 Oxc 取代 esbuild，拒绝 tsconfig 的 `"jsx": "preserve"` → JSX 相关项目配置增加 `oxc: { jsx: { runtime: "automatic" } }`；admin 配置里已弃用的 `esbuild` 选项同步移除。
- 连带修复 pnpm 严格解析暴露的缺失依赖：`packages/shared`、`packages/genome-view`、`packages/api-client` 补 `@types/node`（此前靠根提升偶然可用，升级后 `node:crypto`/`NodeJS.Timeout` 类型报错）。
- 平台契约 `scripts/test_platform_delivery_contracts.py` 的 catalog pin 同步 `vite 8.3.4`/`vitest 5.0.5`；历史验收文档中已移除的 `--poolOptions.forks.singleFork` 命令改为 `--maxWorkers=1`。
- ADR：新增 `docs/adr/0011-vitest5-vite8-upgrade.md`；ADR-0010 标注"vitest5+vite8 一行已被 ADR-0011 取代，其余继续持有"。

**证据**：`turbo run test` 11/11 任务 **1071 tests**（web 373、admin 172、api-client 184、genome-data 121、charts 84、shared 49、genome-view 43、genome-view-model 23、i18n-core 11、query-keys 11）；`turbo run lint typecheck` **25/25**；`pnpm install --frozen-lockfile` 通过；`pytest scripts` **517 passed / 1 skipped / 14 subtests**。生产构建链路（Umi/webpack）不变，Vite 仅测试/开发工具依赖；`pnpm peers check` 的 11 项均为既有 Umi/webpack peer 缺口，无 vite/vitest 相关。

### 同轮追加：i18next 26 + react-i18next 17 升级（ADR-0012，执行 ADR-0011 顺序下一项）

- 版本：`i18next ^24.2.0 → ^26.4.7`、`react-i18next ^15.4.0 → ^17.0.21`（web/admin/jbrowse + `packages/i18n` 四处）。
- i18next 26 移除 `initImmediate`（v24 起改名 `initAsync`）→ `packages/i18n-core` 的 `buildBaseI18nOptions()` 改用 `initAsync: false`；legacy `interpolation.format`、console support notice 两项破坏性变更本仓库从未使用，无需改动。
- react-i18next 17 peer 要求 i18next ≥26.2 与 TS ^5（均满足）；pnpm 12 supply-chain 对新鲜发布的 `react-i18next@17.0.21` 自动要求显式豁免，`pnpm-workspace.yaml` 的 `minimumReleaseAgeExclude` 按既有 ProComponents/AntD 模式加入该精确版本（非范围）。
- ADR：新增 `docs/adr/0012-i18next26-reacti18next17-upgrade.md`。

**证据**：`turbo run lint typecheck` 25/25；`turbo run test` 11/11（**1071 tests** 全绿）；i18n 守卫（locale key parity、语言纯度 5 passed、React 可见文案 0 违规）全绿；`pnpm install --frozen-lockfile` 通过（supply-chain 策略校验 1889 entries）；web 双站 + admin 构建、artifact 全套、static smoke、contracts 338+5、a11y 10/10 全绿；Playwright E2E：公共 **31 passed/1 skipped**、internal **3 passed**、primer **4 passed**（i18next 升级后重跑，用 `/soymutdb-next` 专用构建 + internal 标准制品）。`pnpm audit`：1 high（braces，既有签名接受）、5 moderate、1 low，无新增 high。

### 同轮追加：zod 4 升级 + pdfjs 6 评估（ADR-0013）

- **zod 3.24 → 4.6.7（已升级）**：全仓库唯一消费点是 `apps/web` 的 BLAST 表单 schema（`z.object`/`.min(msg)`/`.int().min().max().default()`/`safeParse`/`error.issues`），v4 行为不变；`tsc`、web 44 files/373 tests、构建均通过，无代码改动。
- **pdfjs-dist 6 暂缓（决定保持 4.10.38）**：v6 API 迁移本身很小（`PDFDocumentProxy.destroy()` 移除 → 用 loading task 销毁；`RenderParameters.canvas` 变必填），已实现并通过类型检查，但制品级验证发现两个阻塞项：
  1. worker 加载方式 `import("pdfjs-dist/build/pdf.worker.min.mjs?url")` 是 Vite 约定，Umi/webpack 不支持——worker 未作为静态 asset 产出，生产 PDF 预览会拿不到 worker；
  2. pdfjs（4.10.38 与 6.4.299 都存在）用 `new URL(".", import.meta.url)` 解析模块 URL，Umi 的非 ESM webpack 输出把 `import.meta.url` 内联成 `file:///…` **构建机绝对路径**进入 `dist/*/assets/*.async.js`（实测 v4 制品同样存在，属既有缺陷）。
  - 结论：v6 升级不会修复该缺陷且会叠加坏 worker，故回滚到 4.10.38；ADR-0013 记录正确修法（复制 worker 到 public / webpack-native `new Worker(new URL(...))`、`workerSrc` 指向运行时 base、CSP `worker-src`、并加"制品不得含构建机绝对路径"守卫），与 Umi/webpack 构建配置一起做。
  - **已知缺陷（下一轮修）**：PDF 异步 chunk 含 `file:///…` 构建路径字符串（不可利用，但不得进入发布制品）。
- ADR：新增 `docs/adr/0013-zod4-pdfjs6.md`；ADR-0010 更新“已完成/仍持有”矩阵。

**证据**：`turbo run lint typecheck test` **36/36**（**1071 tests** 全绿）；`pytest scripts` **517 passed / 1 skipped / 14 subtests**；`pnpm install --frozen-lockfile` 通过；web 双站 + admin 构建、artifact 全套（headers/production scan/双站隔离/chart/bundle）PASS；static smoke PASS；contracts **338+5 SMOKE PASS**；浏览器 a11y **10/10**；`pnpm audit` 1 high（braces，已签名接受）、5 moderate、1 low，无新增。

### 同轮追加：pdfjs worker/构建路径缺陷修复 + pdfjs 6 落地（ADR-0014）

- **worker 静态资产化**：新增 `apps/web/scripts/sync-pdf-worker.mjs`（把已安装的 `pdfjs-dist/build/pdf.worker.min.mjs` 复制到 `apps/web/public/`，生成物 gitignore）；`build-sites.ts` 在双站构建前调用、`pnpm dev` 显式链式调用；viewer 改为 `GlobalWorkerOptions.workerSrc = ${import.meta.env.BASE_URL}pdf.worker.min.mjs`，删除失效的 `?url` 动态 import 与其 ambient 声明。
- **构建机绝对路径泄漏修复**：Umi `define` 增加 `import.meta.url` 空值定义（pdf.js 的 Node-only 分支不再把 `file:///home/<builder>/…` 内联进 bundle）；新增守卫 `scripts/check_artifact_build_paths.py` + 5 个单测（扫描 repo 根、`file:///` 主机路径、`/mnt/`、`/home/<user>/`、`/Users/`、`C:\\`），接入 `verify-frontend-artifacts.sh`。
- **module worker MIME**：容器 web nginx 显式把 `.mjs` 映射为 `application/javascript`（发行版 mime.types 只映射 `.js`；module worker 对 MIME 严格），并设 1h 缓存（worker 文件名无 content hash）；E2E static server / dev preview server 同步支持 `.mjs`。
- **pdfjs-dist 4.10.38 → 6.4.299 落地**：`PDFDocumentProxy.destroy()` → loading task 销毁；`page.render({ canvas, viewport })`（v6 要求 canvas 元素）。浏览器实测：worker 以 `text/javascript` 返回（1 264 143 bytes）、module worker 正常启动、无额外 page error。ADR：新增 `docs/adr/0014-pdfjs6-after-worker-pipeline.md`，ADR-0013/0010 交叉引用更新。

**证据**：`turbo run lint typecheck test` **36/36**（**1071 tests** 全绿）；`pytest scripts` **522 passed / 1 skipped / 14 subtests**（含新增 5 个 build-path 守卫测试）；`pnpm install --frozen-lockfile` 通过；web 双站 + admin 构建（双站均含 `pdf.worker.min.mjs`）；新 artifact build-path 守卫 **OK**；headers/production scan/双站隔离/chart/bundle 全 PASS；static smoke PASS；contracts **338+5 SMOKE PASS**；内部站 E2E **3 passed**；浏览器 a11y **10/10**。

### 同轮追加：dnd-kit sortable 10 + jsdom 30；剩余持有项阻塞证据（ADR-0015）

- **`@dnd-kit/sortable` 8.0.0 → 10.0.0**（core 6.3.1 / utilities 3.2.2 已是最新，sortable 10 peer `@dnd-kit/core ^6.3.0` 满足）；唯一消费点 admin 新闻排序弹窗使用标准 API，admin tsc/eslint/172 tests 通过。
- **jsdom 29.1.1 → 30.1.3**（web/admin/charts 的 Vitest DOM 环境，dev-only 大版本）；三套件全绿（web 373、admin 172、charts 84）。
- **剩余持有项阻塞证据（ADR-0015）**：
  - `redis-py` 6.4 → 8：Kombu 最新稳定版 5.6.2（Celery 5.6.3 依赖）声明 `redis>=4.5.2,<6.5`，当前 6.4.0 已在上限；且 redis-py 8 默认切 RESP3（响应形状变化），需等 Kombu 放宽并单独评审 RESP 协议。
  - TypeScript 5.9 → 7.0：`@typescript-eslint/parser` 8.71.2 peer `typescript >=4.8.4 <6.1.0`，TS7/TS6 beta 均不被 lint 工具链接受；`@umijs/max` 4.7.24 工具链亦锁 5.9 线。
  - jbrowse major（含 @jbrowse 2.18→3.1、@gmod 家族、mobx 6→7、mobx-react 9→10、lucide-react 1.x）：jbrowse 是独立构建/部署边界，制品构建在 DSH 沙箱内无法运行，必须在 CI 的 jbrowse artifact lane 上验证。
- ADR：新增 `docs/adr/0015-dndkit-sortable10-and-remaining-blockers.md`；ADR-0010 交叉引用更新。

**证据**：`turbo run lint typecheck test` **36/36**（**1071 tests** 全绿）；`pytest scripts` **522 passed / 1 skipped / 14 subtests**；`pnpm install --frozen-lockfile` 通过；web 双站 + admin 构建成功；artifact headers/build-path/production scan/双站隔离 全 PASS；web bundle 预算与三处 chart closure PASS；static smoke PASS；contracts **338+5 SMOKE PASS**；浏览器 a11y **10/10**。（admin 的 bundle-size 脚本不属于 CI 门禁——CI 只对 web external 跑该脚本；admin 由 chart closure 预算覆盖，本轮额外手动调用它因 admin 不产出 react/router/ui/query 命名缓存组而报缺失，非回归。）

### 同轮追加：性能/视觉 E2E 车道修复 + 治理审计深入

- **web-performance 车道可运行并给出证据**：`playwright-web-performance.config.ts` 此前仍指向已退役的单一 `apps/web/dist`（构建现在写 `dist/external`+`dist/internal`）→ 改为显式服务 external 树；spec 内 artifact root 同步；修复报告生成 bug（`JSON.stringify(...)+"\\n"` 写入字面 `\n` 导致 `performance-report.json` **不是合法 JSON**，改为真实换行）。结果 **1 passed**：initial JS transfer **531 225 B**（预算 1.2 MB）、DOMContentLoaded **66.6 ms**、load **346 ms**（本地静态服务，非 RUM）。
- **visual-layout 车道可运行**：配置改为服务 `dist/external` 于根路径；**15 passed**（home / gene-search / location-search / jbrowse / blast × desktop/tablet/mobile，截图+几何断言）。
- **性能观察（下一轮优化项）**：Regular CJK 字体 929 760 B 被每页无条件 preload；计划按 unicode-range 拆 latin/CJK 子集、只 preload latin（英文页面可省 ~900 KB 首屏字节）。
- **依赖治理审计深入**（`pnpm deps:audit` 在本机跑到 17 项）：15 passed。真实修复：`pnpm dedupe --check` 报 dompurify 3.4.16/3.4.17、@umijs/bundler-utils 4.7.20/4.7.24 等重复 → `pnpm dedupe` 后 **--check 通过**；deptry DEP001 的 `clickhouse_connect`/`chdb` 仅存在于 Python 3.14 legacy-migration 镜像（不能进 3.15 元数据）→ governance 配置按精确模块豁免（worker 多模块 `|` 分隔），api/worker deptry 均 **Success**。未能通过的两项均为沙箱环境限制：worker 的 pip-audit 与 python-licenses（numcodecs/h5py 构建需编译器/HDF5），需 CI runner 复核。文档见 `docs/ops/dependency-governance.md`。

**证据**：`turbo run lint typecheck test` **36/36**（**1071 tests** 全绿）；`pytest scripts` **522 passed / 1 skipped / 14 subtests**；`pnpm install --frozen-lockfile` 通过；web 双站 + admin 构建成功；artifact headers/build-path/production scan/双站隔离/chart/bundle 全 PASS；static smoke PASS；contracts **338+5 SMOKE PASS**；浏览器 a11y **10/10**；web-performance E2E **1 passed**；visual-layout E2E **15 passed**；`pnpm deps:audit` 17 项中 **15 passed**（2 项为沙箱 worker 科学计算依赖构建限制）。

### 同轮追加：字体性能优化（portal 去死重 + admin latin/CJK 拆分）

- **发现**：公共门户 CSS（`apps/web/src/index.css`，唯一被 import 的样式入口）**没有任何 HarmonyOS `@font-face`**，按注释是刻意使用系统 CJK 栈首屏；但 `apps/web/config/config.ts` 仍在 `links` 里 preload `HarmonyOS-Sans-SC-Regular.woff2`（旧单文件 929 KB）——每个页面下载一个页面从不使用的字体；同时 `apps/web/public/fonts/` 2.8 MB 全量进制品，`apps/{web,admin}/src/style.css` 是未被 import 的死样式文件（各 700–1100 行）。
- **处理**：删除 portal 字体资产与 preload（`links: []`），删除两个未引用的 `style.css`；web artfacts 因此减少 **2.8 MB**（dist/external 9.0 MB → 6.2 MB）。admin 真正使用 HarmonyOS。
- **admin 字体按 unicode-range 拆分**（`scripts/subset-portal-fonts.py` 重写为 admin-only）：每个字重产出 `-latin`（ASCII+西文符号，约 **15–16 KB**，仅 Regular preloaded）与 `-cjk`（GB2312 hanzi + CJK/全角标点，约 **895–930 KB**，仅渲染 CJK 时按 unicode-range 按需下载）；总载荷仍 2.82 MB，但英文后台首屏从 ~908 KB 降到 ~15 KB。manifest 升级为：全量 charset + `parts` + 每文件 weight/role/bytes/sha256/role-scoped `missing_codepoints`/budgets。
- **守卫重写** `scripts/test_portal_font_subset.py`（5 tests，直接从生成器 import charset 防漂移）：校验 manifest 与文件一致性/角色预算、admin CSS 的 6 个 split face 与 latin preload、fontTools 可用时逐角色 cmap 覆盖；并**禁止 portal 重新引入 HarmonyOS 字体文件/@font-face/preload**。文档 `docs/dev/font-subsetting.md` 重写。
- 验证：font `--check` OK、guard 5 passed、admin 制品仅 `dist/fonts/harmonyos` 一份（原先 CSS 相对路径导致 hashed 资产重复，已改绝对 `/fonts/...` 引用）、portal 制品无 fonts 目录且 CSS 无 HarmonyOS；web-performance E2E **1 passed**（首屏资源不再含字体）、visual-layout **15 passed**。
- **门禁证据**：workspace lint/typecheck **25/25**、tests **11/11（1071）**；`pytest scripts` **523 passed / 1 skipped / 14 subtests**；frozen-lockfile 通过；web 双站 + admin 构建；artifact headers/build-path/production scan/双站隔离/app-shell/字体守卫全 PASS；web bundle 与三处 chart closure PASS；static SMOKE PASS；contracts **339+5 SMOKE PASS**；浏览器 a11y **10/10**。

### 同轮追加：全路由冒烟（36 路由 × en/zh）+ 真实渲染崩溃修复

- 新增 `e2e/tests/route-smoke.spec.ts`：在构建制品上遍历公共门户全部 **36 条路由**（en + zh 各一遍），断言无 `pageerror`、无非预期 console error、`#root` 非空、未落入 React error boundary；接入 public 与 internal 两套 E2E（`playwright-public/internal.config.ts` testMatch）。
- **发现并修复真实 BUG**：`/genes/:geneId` 在离线/错误 API 环境下整页崩溃（`TypeError: Cannot read properties of undefined (reading 'toLocaleString')`）。根因两层：
  1. `e2e/static-server.mjs` 的基因 mock 把 **基因详情路径** 也当成搜索列表返回 `{items: []}` 信封，页面把列表信封当 `GeneDetail` 使用；
  2. 应用层信任生成类型、没有运行时形状校验 → `GeneGenomeView` 对 `gene.start_pos` 调 `toLocaleString()` 抛错，React error boundary 接管整页。
  修复：static-server 对基因详情返回诚实 404；新增 `apps/web/src/lib/api-contract-guards.ts#isGeneDetailRecord`（校验 `gene_id`/`chromosome`/有限且 `end>=start` 的坐标）并在 gene 详情页使用——形状不符时渲染空态而非崩溃；新增 4 个单测。此类"生成类型 ≠ 运行时契约"的防护同样适用于其他实体详情页（下轮可推广）。
- 验证：公共 E2E **33 passed / 1 skipped**（含 2 条 route-smoke）、internal E2E **5 passed**（含 2 条 route-smoke）；web-performance **1 passed**、visual-layout **15 passed**。

### 同轮追加：运行时形状守卫推广（mutant / news 详情）

- 在 `apps/web/src/lib/api-contract-guards.ts` 增加 `isMutantLineDetailRecord`（`public_id`/`name`/`species`）与 `isNewsDetailRecord`（`slug`/`title_en`/`content_en`），并接入 `/mutants/:id` 与 `/news/:slug` 详情页：形状不符（列表信封、代理错误体、错误 200）时渲染 not-found/error 状态，而不是对 `undefined` 字段取值崩溃。
- 单测扩至 **8 个**（gene + mutant + news，含用搜索列表信封构造的回归用例）。
- 验证：workspace lint/typecheck 25/25、tests 11/11（**1079**）、scripts 523/1/14、frozen-lockfile、双站+admin 构建、artifact 全套、public E2E **33/1 skipped**、internal E2E **5 passed**、perf 1、visual 15、contracts 339+5、a11y 10/10。
- 运维注意：`SOYMUTDB_DIST_DIR=dist/e2e-external` 的 E2E 专用构建会重写 `.build/chart-closure/web-external.json`，若之后再跑 artifact 门禁会报 JS set mismatch；**必须先重跑标准 `build:sites` 再跑制品门禁**（本轮已记录）。

### 同轮追加：API 形状弹性 E2E（形状守卫的端到端证明）

- 新增 `e2e/tests/api-shape-resilience.spec.ts`（接入 public 套件）：用 `page.route` 拦截三个实体详情的 API，返回**错误形状的 200**（genes 返回搜索列表信封；mutants/news 返回 `{items: []}`），断言页面进入 empty/not-found/error 降级态、`#root` 非空、无 `Something went wrong` error boundary、无 `toLocaleString`/`Cannot read properties of undefined` 控制台错误——即第 14–15 轮形状守卫的运行时契约被浏览器层证明。
- 实现要点（避免踩坑）：① 相对 URL 导航必须基于 `baseURL` 去掉前导 `/`，否则丢掉 `/soymutdb-next/` 前缀打到静态服务器 404；② 断言降级文案用 `document.body.innerText`，因为 antd Empty 的 `<img title="No data">` 会让 `getByText` 命中隐藏元素。
- 验证：public E2E **36 passed / 1 skipped**（+3 shape 用例）；随后重跑标准 `build:sites` + admin 构建，artifact headers/build-path/production scan/双站隔离/chart closure/bundle 全部 PASS。

### 同轮追加：依赖安全 floor（pnpm audit 7 → 5，且治理门禁仍通过）

- `pnpm-workspace.yaml` overrides 新增三个兼容 floor：`postcss-selector-parser@<7.1.6 → 7.1.6`（GHSA-rj75-hqrm-r3gf ReDoS）、`pbkdf2 → 3.1.7`（GHSA-477h-4r7f-fvrx）、`sprintf-js → 1.1.3`（GHSA-hp3w-g68c-fv3c，**上游暂无修复版**，1.1.3 为当前最新）。`pnpm audit` 由 **7**（1 high/5 moderate/1 low）降到 **5**（1 high/3 moderate/1 low）；frozen-lockfile 与 `pnpm dedupe --check` 均通过。
- 剩余 5 项**无可用修复**，已在 `docs/ops/dependency-governance.md` 新增 "Accepted residual advisories" 表逐条记录可达性：braces（high，Umi→chokidar 构建期，3.0.3 为最新且已有签名接受 `security/advisory-acceptances.json`，到期 2026-12-09）、react-router 6.30.6 ×2（仅 7.18.0 修复而 Umi 4 锁 v6；制品用 TanStack Router）、sprintf-js（最新版仍在 advisory 范围）、elliptic（low，bundler shim）。
- 治理校验：用 `dependency_governance.evaluate_advisory_report` 对当前 audit 报告评估 → **0 unaccepted findings、1 accepted（braces，未过期）**，即 `pnpm deps:audit` 的 pnpm-audit 项仍为通过；其余项沿用 r12 已知环境限制（worker pip-audit/licenses 需 CI runner）。
- 依赖图变化后的复验：workspace lint/typecheck 25/25、tests **907（非 admin）+ 172（admin）= 1079 全绿**、scripts 523/1/14、web 双站+admin 构建、artifact 全套 PASS、web-performance **1 passed**、visual-layout **15 passed**、frozen-lockfile + dedupe-check 通过。
- 环境注记：沙箱内 admin vitest 的 `forks` worker 会因进程配额 `EAGAIN` 偶发失败（测试本身 16/16 文件、119 用例已跑过才报 spawn 错误）；本轮用 `--pool=threads --maxWorkers=1` 复跑通过 **23 文件 / 172 用例**，该 workaround 已记入本机运行笔记。

### 同轮追加：admin 制品 E2E 复活 + 登录页真实响应式 BUG 修复

- `playwright-admin-production.config.ts` 这条 **admin 制品门禁此前是"死"的且全红**：spec 断言英文标题/文案，但 admin 以 `initI18n("zh")` 中文优先；它依赖的 `admin-identifier` / `admin-password` / `admin-login-submit` testid 在组件里并不存在；admin 也从未发出 `data-app-ready` 交接信号。
- 修复（均属真实缺陷，不是改测试迁就实现）：
  1. admin `login.tsx` 三个控件补稳定 `data-testid`；
  2. admin `react-app.tsx` 增加与门户一致的 `AppReadySignal`（`<html data-app-ready>`）；
  3. spec 改为 locale 无关断言（testid + app-ready + 无 pageerror）。
- **发现并修复真实 UI BUG**：390px 视口下 admin 登录页出现 **240px 横向滚动条**——装饰性身份面板 `flex: 1 1 55%` + 固定 480px 表单面板在手机上必然溢出。`index.css` 增加 `@media (max-width: 767px)`：隐藏 `aria-hidden` 的装饰面板、表单面板改为全宽（页面在手机上首次可用）。
- 新增 1 条字体契约用例：断言 admin 制品只提供 **split** 的 `-latin`/`-cjk` 字体、preload 指向小体积 `Regular-latin`、所有字体请求 200 且 `font/woff2`——把第 13 轮字体拆分做了端到端验证。
- 证据：admin production E2E **4 passed**（修复前 3 failed + 1 缺失用例）；workspace lint/typecheck 25/25、tests **1079 全绿**（907 non-admin + 172 admin）、scripts 523/1/14（沿用）、双站+admin 构建、artifact 全套 PASS、static SMOKE PASS。
- 说明：jbrowse 构建在本沙箱仍因 esbuild 进程配额 `EAGAIN` 失败（Terser 阶段），因此 jbrowse 的 13 MB 全量字体 subset 仍留给其 CI artifact lane，未做未经验证的改动。

### 同轮追加（续）：PREFIX 归一化缺陷 + primer 契约根因

- **static-server `PREFIX` 归一化缺陷（真实 bug）**：`node static-server.mjs <root> 4173 /` 时 `PREFIX="/"`，所有 mock 路径被拼成 `//api/v1/...` → 全部 404。改为 `PREFIX_RAW === "/" ? "" : 去尾斜杠`，mock/前缀剥离/日志统一；验证 `login=401`、`assemblies=200`、`index=200`、子路径制品资源 `=200`。这也解释了 public 套件早期的大面积失败。
- **primer genome 模式的真正根因**：helper 曾伪造 `GET /releases/active → 200 {release_id:"7"}`。**页面 reload 后**该伪造 release 会改变部署上下文，导致 assemblies 查询不再解析、Genome version 下拉永远停留在占位符（用独立 Playwright 探针可复现：带伪造 release 时 reload 后 `HAS_WM82=false`，去掉后为 true）。改为不 mock `releases/active`（维持 static-server 的 404 基线）后 genome 用例稳定通过。**注意**：真实部署返回的 release 形状是否满足该上下文未在本沙箱验证，已列入部署栈 E2E 待验证项。
- 其他测试健壮性修复：primer 用例补 `waitForAppReady`（否则填充的是 SSG 惰性表单，React 状态为空）；config 增加 `reducedMotion: "reduce"`（antd Select portal 定位在揭示动画期间不稳定）。
- 最终验证：public **36 passed / 1 skipped**、internal **5 passed**、admin production **4 passed**、visual **15 passed**、web-performance **1 passed**、primer **4 passed**（单跑稳定；整套偶发浏览器启动类 flake，串行单跑可过）；workspace lint/typecheck 25/25、tests 907（+admin 172）、scripts 523/1/14、artifact 全套 PASS。

### 同轮追加：E2E 门禁全量盘点（13 个配置）与修复

用 subagent 对 `e2e/` 下全部 Playwright 配置做只读审计，结论（按严重度）：

| 级别 | 缺陷 | 修复 |
| --- | --- | --- |
| CRITICAL | `playwright-primer.config.ts` 的 webServer 无 root 参数 → 服务 `apps/web/dist` 根（无 index.html）→ ENOENT、30s 超时 | 改为服务 `dist/external` 于根路径、spec `BASE=""`、补 `locale: en-US` |
| CRITICAL | `playwright-public.config.ts` 用 `/soymutdb-next/` 挂载 base-`/` 的 `dist/external` → 文档 200 但所有 `/assets/*` 404，SPA 永不启动 | `static-server.mjs` 增加"root-baked artifact 挂在子路径下"兜底：root 绝对资源存在则按 ROOT 解析，未知路径仍 404 |
| CRITICAL | `playwright-admin-console.config.ts` 的 5 个 anchor + `admin-sidebar` testid 在 admin 源码中不存在（该门禁需部署栈+storage state，长期无人跑而腐烂） | 交 subagent 修 spec 并补最小 testid 契约（进行中） |
| HIGH | `local-preview` spec 无任何 skip guard、默认 127.0.0.1:5173 | 交 subagent 加 skip guard（进行中） |
| HIGH | `browser-open-new-tab` testid 不存在（portal-embed / JBrowse 套件） | 交 subagent 在 `browser.tsx` 补 testid（进行中） |
| MEDIUM | internal/visual/web-performance 共用 4175 且 reuseExistingServer 不一致 → 可能静默测错 variant | internal 改 `reuseExistingServer:false`；visual→4177、perf→4178 |
| MEDIUM | `.cnb.yml` 夜间 smoke 指向 `https://soymutdb.example.com`（RFC 2606 占位符，永不解析） | 改为真实发布源 `https://caoronglin.github.io/soymutdb-next/` |
| LOW | primer 未 pin locale；genes spec 有永不失败的 `configurable-row` 断言 | locale 已补；死断言交 subagent 修 |

验证：静态服务器兜底已手工验证（`/soymutdb-next/` 200、root 绝对 `/assets/*` 200、未知深路径 404）；primer/public 套件待端口/宿主资源释放后跑。

### 同轮追加：门禁审计后的实际修复与一条审计纠错

- **审计纠错（D3 为假阳性）**：subagent 报告称 `playwright-admin-console` 的 5 个 anchor 与 `admin-sidebar` 均不存在；逐条用模板字面量核对后确认 **spec 契约本身是对的**——`brand-variant-${option}`（brand.tsx:103）、`content-tab-${typeKey}`（content.tsx:70）等是运行时拼出的 testid，`dashboard-stats*`、`imports-*`、`settings-domains`、`news-*`、`pages-*`、`shell-header` 全部存在，spec 也早已使用 `shell-header`。**该门禁不需要按审计建议动手术**，只缺一次部署栈实跑。
- **已修并验证**：`playwright-primer` 目标改为 `dist/external@/` + `BASE=""` + `locale:en-US`；因为制品烘焙的是**绝对 API origin**，静态服务器的同源 mock 永远收不到 `/tools/seqfetch`，新增 `helpers.mockPrimerApis()`（CORS-aware，仅 fulfill assemblies/chromosomes/seqfetch/releases，其余 404）→ **primer 套件 4 passed**。
- **已修待实跑**：`playwright-public` 改为根路径服务（8 处 `BASE` 常量去掉 `/soymutdb-next` 前缀 + login 重定向正则），静态服务器增加 root-baked artifact 兜底（已手工 curl 验证：`/soymutdb-next/` 200、root 绝对 `/assets/*` 200、未知深路径 404）。**完整 public 套件本轮未取得绿色证据**：宿主线程配额耗尽导致 Chromium `pthread_create EAGAIN`/`spawn bwrap EAGAIN`，36 项失败全部是浏览器启动失败而非断言失败。
- 其他已修：internal `reuseExistingServer:false`、visual→4177、perf→4178、`.cnb.yml` 夜间 smoke 指向真实 gh-pages 源；subagent 修好 `browser-open-new-tab` testid（主按钮 + 两个 overlay 用后缀 id，避免 DOM 重复）、`local-preview` skip guard、`genes.spec.ts` 死断言（改用真实 `search-genes-table`/`gene-row`）。
- 环境遗留：本轮一次失败的 `build:sites` 在 `max build` 之后、`generate-static-routes`/CSP/sw 之前被宿主线程配额打断，`dist/external` 可能处于**半成品状态**；环境恢复后必须先重新 `pnpm --filter @soymutdb/web build:sites` 再跑 visual/perf/artifact 门禁。

### 同轮追加：真实产品 BUG 修复——release 切换销毁在途查询（entity-detail 门禁解锁）

- **缺陷（subagent 用 6/6 隔离矩阵证明）**：`ReleaseScopeProvider` 在 `/releases/active` 首次探测把 release pin 从 null 翻成真实 id 时，调用 `dropReleaseScopedQueries()`（即 `removeQueries()`）。query-core 5.104.3 的 `Query#destroy()` 会 `retryer.cancel({silent:true})`：**在途请求被静默取消、查询永远停在 pending**；缓存条目被删且 `QueryObserver` 没有 onQueryRemoved 钩子，observer 变成孤儿，之后的 `refetchQueries` 面对已清空的缓存也救不回来。结果：详情页 200 响应落在一个没人监听的 query 上，路由永久停在骨架屏。未固定 release 的制品每次加载都会触发；已部署 tab 在 operator 发布新 release 且恰有读取在途时同样会中招。
- **修复**（`apps/web/src/lib/release-scope.tsx`）：把 `removeQueries + refetchQueries` 改为就地 `invalidateQueries({ predicate: isReleaseScopedKey, refetchType: "active" })`——保留 release 隔离（不会读到旧 release 的条目），但不销毁被观察的查询；删除不再使用的 `dropReleaseScopedQueries` 死代码；模块头注释记录该回归。新增单测 `keeps a release-scoped read alive when the switch lands mid-flight`（切换发生在读取在途时，release-2 仍能渲染、query 状态 success/idle），release-scope 单测 7 passed。
- **门禁解锁**：entity-detail 离线两条 skip 删除，并修掉 skip 掩盖的 4 个断言缺陷（gene 用路由 wrapper 当渲染证据、两个 back-link `$=` 选择器、JBrowse 参数是 `locus` 且格式 `chr:start-end`）→ **entity-detail 3 passed**（mutant / compare / gene，含 reload）。
- 最终验证：public **36/1 skipped**、internal **5**、admin production **4**、visual **15**、web-performance **1**、entity-detail **3**；workspace lint/typecheck **25/25**、tests **907（+admin 172）**、`pytest scripts` **523/1/14**、artifact 全套 PASS。

### 同轮追加：jbrowse 字体拆分（制品 31 MB → 8 MB）

- 沙箱环境恢复后首次成功构建 `apps/jbrowse`（此前 Terser/esbuild 阶段 `EAGAIN`）。构建证实 jbrowse 制品里字体被**双份**携带：`dist/fonts` 公共副本 13 MB + webpack 哈希资源副本 13 MB。
- 处理：`scripts/subset-portal-fonts.py` 扩展为 admin + jbrowse 两个 app；jbrowse 三个 full woff2（~4.2 MB/字重）替换为 split 的 latin(~15 KB)/cjk(~900 KB)，CSS 改为 6 个带 unicode-range 的 face、根绝对 `/fonts/harmonyos/...`（jbrowse 总是从自身 origin root 提供服务，故不再产生哈希副本）；删除 full 源文件（仓库 -10 MB）。
- 验证：jbrowse 构建成功，`dist` **31 MB → 8.0 MB**（字体 26 MB → 2.8 MB，`find dist -name 'HarmonyOS*'` 恰好 6 个、无哈希副本）；本地静态服务实测 latin 14,608 B / cjk 915,452 B 均 200 `font/woff2`；jbrowse node 测试 **40 passed**；字体守卫 5 passed（已覆盖 admin+jbrowse，并继续禁止 portal 回退字体）；artifact build-path（含 jbrowse）与 app-shell 门禁 PASS；`pytest scripts` **523/1/14**。

### 同轮追加：jbrowse 制品崩溃 BUG + 新的离线 artifact 门禁

- **真实 BUG（部署即白屏）**：jbrowse 的 Umi 构建把入口脚本输出在 `<head>` 且**没有 `defer`**（门户/admin 构建有）。阻塞脚本在 `<body><div id="root">` 解析前执行，React 直接抛 `Minified React error #299 (Target container is not a DOM element)`，应用永不挂载——即 jbrowse 制品在浏览器里是白屏。此前没有任何浏览器门禁覆盖 jbrowse 制品，所以一直没被发现。
- 修复：`apps/jbrowse/scripts/build-artifact.ts` 在产物 HTML 后处理阶段给所有外部入口脚本补 `defer`（已有 async/module 的跳过，inline 脚本保持原位以维持 CSP hash）；同时给 jbrowse `react-app.tsx` 加 `AppReadySignal`（`<html data-app-ready>`），让浏览器门禁能区分"已挂载"与"惰性文档"。
- 新增离线 artifact 门禁 `e2e/playwright-jbrowse-artifact.config.ts` + `tests/jbrowse-artifact.spec.ts`（服务 `apps/jbrowse/dist` 于 origin root）：断言 shell 完成 React 交接、无 pageerror、API 不可用时渲染 `jbrowse-unavailable` 降级态而非崩溃、CSS 声明的 split 字体全部 200 `font/woff2` 且为 latin/cjk split 命名。**1 passed**。
- 守卫加固：`scripts/check_app_shell_assets.py` 现在检查每个内置 shell 的 `index.html` 是否存在"无 defer/async/module 的外部入口脚本"，负例自测覆盖 blocking/defer/module 三种形态。
- 验证：jbrowse 构建成功（<script ... defer> 已生效）、jbrowse node 测试 **40 passed**、jbrowse artifact 门禁 **1 passed**、workspace lint/typecheck **25/25**、`pytest scripts` **523/1/14**、app-shell/build-path 门禁 PASS。

### 同轮追加：离线 E2E 一键化（`pnpm verify:artifact-e2e`）

- 审计结论指出 13 个 Playwright 配置里只有 2 个进了 CI，其余长期无人运行而腐烂。本轮把 **8 个离线 artifact 门禁**收进单一入口：`scripts/verify-artifact-e2e.sh`（按顺序跑 public / internal / admin-production / entity-detail / visual / web-performance / primer / jbrowse-artifact，逐门禁计时与结果表、失败退出非零、缺制品/未知门禁退出 2、可 `ARTIFACT_E2E_RETRIES=1` 吸收宿主浏览器启动抖动）。`package.json` 增加 `verify:artifact-e2e`；新增 `scripts/test_artifact_e2e_gate.py`（3 tests）守卫门禁清单/配置存在性/fail-closed/包装脚本，防止清单与配置漂移。
- 新增文档 `docs/dev/e2e-gates.md`：13 个配置的离线/部署分类、端口、覆盖契约、静态服务器约定（PREFIX 归一化、root-baked artifact 兜底、不要伪造 `/releases/active`）。
- 验证：**8/8 门禁全绿**（196 s；public 87 s / internal 50 s / entity-detail 7 s / admin-production 5 s / visual 32 s / perf 3 s / primer 9 s / jbrowse 3 s）；`pytest scripts` **526 passed / 1 skipped / 14 subtests**。

### 同轮追加：compare 页 provenance 补齐（Assembly / Release 显式化）

- 已知差距"`/compare` 使用固定精选数据集、缺 Assembly/Release provenance"本轮部分收口：页面新增 **Assembly** 行（来自部署的 assemblies 查询，取默认/首个 assembly）与 **Release** 行（当前 release pin；未固定时如实显示 "not pinned"），并加行级 testid（`compare-row-assembly` / `compare-row-release` 及其 value）。这样"精选数据"不会被误读成"按发布版本固定的数据"；页面原有的 reference-note 仍保留说明这是固定精选集。
- i18n：新增 `compare.curated.fields.assembly/release/releaseUnpinned/assemblyUnknown`（en+zh，locale parity 守卫通过）。
- 测试：`compare.test.tsx` 加 QueryClientProvider 包装 + 1 条 provenance 行断言（5 passed）；`entity-detail` E2E 增加 Assembly 行值断言（离线 mock assemblies = Wm82.a4.v1）与 Release 行存在断言 → **3 passed**。
- 验证：web 重建 + lint/typecheck 25/25；workspace tests **908**（+admin 172）；`pytest scripts` **526/1/14**；**artifact E2E 全量 sweep 8/8 passed（201 s）**（public 89s / internal 52s / admin-prod 6s / entity-detail 7s / visual 32s / perf 3s / primer 9s / jbrowse 3s）。
- 仍未做（诚实记录）：compare 页的可选变异仍来自 `compare-data.ts` 精选集，**按 release 固定的实时对比**仍需后端证据 API；provenance 行让当前状态可见但不等于实时数据。

### 同轮追加：离线 artifact E2E 接入 CI（双 provider）

- 新增共享脚本：`scripts/build-all-static-apps.sh`（web external/internal + admin + jbrowse 四套制品，demo env 默认值，缺任一 index.html fail-closed）与 `scripts/ci-nightly-artifact-gate.sh`（setup-workspace → 构建 → 8 门禁 sweep，默认 1 次重试吸收宿主浏览器启动抖动）；`verify-artifact-e2e.sh` 增加 `--build`。
- **修复一处我们自己引入的 CI 漂移**：GitHub `pr-artifact` 作业原来用 `VITE_BASE_URL=/soymutdb-next/` 构建单变体、只跑 `playwright-public.config.ts`；当 public 门禁改为服务标准 base-`/` 制品后该作业与自己的配置不再匹配。现改为调用共享构建脚本（标准制品）并跑 **全部 8 个门禁**。
- CNB 夜间（`crontab: 0 2 * * *`）与 GitHub schedule/deploy 作业都调用同一个 `ci-nightly-artifact-gate.sh`；CNB 失败时额外上传 `.cache/artifact-e2e` 日志。双 provider 不再各自维护逻辑。
- 验证：`python scripts/build-all-static-apps.sh` 实跑成功（四套制品齐全）；随后全量 sweep **8/8 passed（200 s）**；`pytest scripts` **526/1/14**（含 CI 契约 71 passed）。

### 同轮追加：admin 认证后 shell 离线门禁 + CI 接线复审修复

- 新增第 9 个离线门禁 `playwright-admin-shell.config.ts` + `admin-shell.spec.ts`（端口 4189，服务 `apps/admin/dist`）：用真实登录表单 + static-server 的 mock auth（`/auth/login` 现在同时接受门户 `{email}` 与 admin `{username}` 两种载荷）走通登录，断言认证后 `shell-header` 挂载、离开 `/login`、无 pageerror。此前"登录之后的 admin shell"没有任何离线浏览器覆盖（部署态门禁需要 storage state，从未运行）。
- 用 subagent 对新 CI 接线做只读复审，发现并修复：① **CNB 夜间浏览器安装不跨 stage 存活**（每个 stage 是新容器）→ 改为 `ci-nightly-artifact-gate.sh` 自己 `npm ci` + `playwright install --with-deps chromium`，删除会误导的独立安装 stage，在线 smoke stage 也自带安装；② **`SMOKE_BASE_URL` 泄漏**进 entity-detail（该 config 把它当部署栈 override）→ 从夜间 env 移除，两个 provider 现在跑同一组离线断言；③ PR 上传证据从 2 个门禁扩到 `e2e/playwright-report-*` / `test-results-*` 全量 + `.cache/artifact-e2e`；④ `test_artifact_e2e_gate.py` 加入 `smoke.sh contracts` 层，真正在 CI 执行；⑤ `verify-artifact-e2e.sh` 进入 shared-script 契约清单；⑥ GH 夜间 job 增加 pnpm cache + timeout 45；⑦ 契约测试新增对 **crontab pipeline** 的 container-state 扫描，防止同容器状态假设回归；⑧ CNB 夜间增加 `/cache/pnpm-store` volume 与 `CI=1`；⑨ 文档计数/门禁表更新（15 configs / 9 gates，admin-shell 行）。
- 验证：admin-shell 门禁 **1 passed**；全量 sweep **9/9 passed（204 s）**；CI 契约 + sweep 守卫 **74 passed / 5 subtests**；`pytest scripts` **526/1/14**。

### 同轮追加：JBrowse 线性视图离线门禁（不再只测降级态）

- `playwright-jbrowse-artifact` 从"只证明 shell 启动 + 降级态"升级为**真正挂载线性基因组视图**：新增 `helpers.mockJbrowseApis()`（CORS-aware）mock `/genes/assemblies` 与 `/tracks/jbrowse-config`，assembly 使用 JBrowse 的 `FromConfigSequenceAdapter`（4 kb 内联参考序列），因此无需仓库不存在的 `/jbrowse-data` 文件即可让 `createViewState()` 成功；`/jbrowse-data/*` 显式快速 404 避免适配器挂起。
- 断言：`[data-testid="jbrowse-view"][data-view-ready="true"]` 可见、`jbrowse-unavailable` 为 0、assembly 摘要显示 `Wm82.a4.v1`、无 pageerror → **2 passed**（原 1 passed）。
- 诚实边界：内联参考序列证明的是"配置 → createViewState → 视图挂载"这条主链；真实 BAM/VCF/GFF 轨道仍需要部署栈 + `/jbrowse-data`，未在本轮伪造。
- 验证：全量 sweep **9/9 passed（205 s）**（jbrowse 门禁 5 s，含新增用例）。

### 同轮追加：seed-request 公网写路径离线门禁

- `/seed-request` 是**公开写路径**（gene 详情页 deep link 预填 → 表单 → `POST /api/v1/seed-requests`），此前没有任何浏览器证据。本轮加 `seed-request.spec.ts`（public 套件，mock CORS API）：
  - 用例 1：`?genes=Glyma.01G000100` 预填校验 → 填 Full name / Email / Institution / Country → 提交 → 断言成功态出现，并校验实际 POST 路径、`content-type: application/json` 与 body `{name,email,institution,country,gene_ids:["Glyma.01G000100"]}`，全程无未容忍 console error；
  - 用例 2：粘贴 201 个 gene id → 客户端上限报错，且**一个请求都不发**（`submitted` 为空）。
- 为稳定断言补 testid：`seed-request-form`、`seed-request-submit`、`seed-request-success`、`seed-request-error-banner`。
- 验证：seed-request 两个用例 **2 passed**；全量 sweep **9/9 passed（207 s）**；workspace lint/typecheck **25/25**。

### 同轮追加：downloads 目录/预览/下载安全门禁

- `/downloads` 之前只有类型检查：本轮加 `downloads.spec.ts`（public 套件，mock CORS API）3 个用例：
  1. **目录渲染**：API 文件列表按 category 分组、文件名/格式列可见、每行 Preview 按钮存在；
  2. **下载 URL scheme 守卫（安全）**：正常行 → `getDownloadUrl` 返回的 https 签名 URL 经 `window.open` 打开；投毒行 → 签名 URL 与 `file_url` 都是 `javascript:`，断言 `window.open` 调用数不增加、且没有任何 `javascript:` 被打开（验证 `safeExternalUrl` 的端到端行为）；
  3. **预览弹窗**：点 Preview → antd Modal 打开，标题含文件名与 `VCF` 格式标签。
- 为稳定断言给下载表格加行级 testid `download-row-${id}`（onRow + 类型断言）。
- 验证：downloads **3 passed**；全量 sweep **9/9 passed（212 s）**；workspace lint/typecheck **25/25**。

### 同轮追加：tools/seqfetch 表单→FASTA 链路门禁

- `/tools/seqfetch` 的两种模式此前只有类型检查；本轮加 `seqfetch.spec.ts`（public 套件，mock CORS API）4 个用例：
  1. **按基因 ID**：切到 region tab 等 assemblies 查询解析并预选默认 assembly → 切回 genes tab 填两个 ID → 断言 FASTA preview（`seqfetch-fasta-preview`）内容、`2 sequences` 计数、Missing genes 标签，并校验实际 POST body `{assembly:"Wm82.a4.v1", genes:[...]}`；
  2. **按区域**：region tab 填 `chr01/100/400` → 校验 POST body `{assembly, region:"chr01:100-400"}` 与 FASTA 渲染；
  3. **大结果**：响应只给 `download_url`（无 inline sequence）→ 断言 "Large result" 状态 + Download FASTA 链接 href，且不出现内联 preview；
  4. **客户端校验**：空基因列表与 >200 基因分别显示错误文案，且 `captured` 为 0（一个请求都不发）。
- 注意点（已写入 spec 注释）：assembly Select 只在 region tab 渲染，但选中的 assembly 是两种模式共享状态，因此用"先进 region tab 等待预选、再切回 genes"的确定性流程。
- 验证：seqfetch **4 passed**；全量 sweep **9/9 passed（217 s）**。

### 同轮追加：exppattern 门禁 + 真实 i18n 插值 BUG 修复

- `/tools/exppattern` 加 `exppattern.spec.ts`（public 套件，mock CORS API）2 用例：① 断言 POST payload `{assembly_id:1, genes:[...], cluster_rows:false, scale:"zscore"}`，并校验 summary 计数、`Hierarchical clustering`/`z-score` 标签、Missing genes 提示、矩阵表（role=columnheader 的 root/leaf、role=cell 的基因与数值）、canvas 的可访问名称；② 空基因列表与 >50 基因分别报错且零请求。
- **写用例过程中发现并修复一个真实产品 BUG**：`exppattern.tsx` 传给 `summaryDesc` 的插值参数名是 `conds`，而文案占位符是 `{{conditions}}`，导致页面直接显示未替换的原文 `"2 genes × {{conditions}} conditions."`；同一 bug 也让热力图 canvas 的 aria-label 显示 `{{genes}} genes × {{conditions}} conditions`（当时 `heatmapAria` 的 label 甚至没传插值参数）。修复：`summaryDesc`/`toastDoneDesc` 改用 `conditions`，`label` 与 `description` 都传 `{genes, conditions}`。
- 顺带做了一次 **插值一致性审计**（脚本扫描 apps/web 与 apps/admin 全部 `t("key", {...})` 调用，对比 en/zh 文案占位符，排除 shorthand 属性、`count`、`defaultValue`）：修复后 **web/admin 均 0 处缺失插值**；同类 bug 只剩本次修复的 exppattern。
- 验证：exppattern **2 passed**；全量 sweep **9/9 passed（219 s）**；workspace tests **908**；lint/typecheck **25/25**。

### 同轮追加：i18n 插值守卫（防 `conds` vs `{{conditions}}` 类回归）

- 新增 `scripts/check_i18n_interpolation.py`：扫描 `apps/{web,admin,jbrowse}/src` 全部字面量键 `t("a.b.c", {...})`，对照 en/zh 文案（含 i18next 复数后缀 `_one/_other/...`）的 `{{placeholder}}`，要求调用点对象字面量提供全部参数；支持 shorthand（`{ message }`）、多行对象、跳过 `...spread`（静态不可知）与 `defaultValue`（调用点自持文案），`count` 豁免；报告同时打印"已提供的 options"与缺失项，便于一眼看出 `conds` vs `conditions`。
- 新增 `scripts/test_i18n_interpolation_guard.py`（6 tests）：合法调用（含 shorthand/多行/plural count/defaultValue/spread/未知键跳过）、缺参失败并定位 file:line、zh-only 占位符同样强制、以及**复现本次真实 BUG 形状**（`{genes, conds}` vs `{{genes}} {{conditions}}`）必须失败。
- 接线：`scripts/verify-frontend-artifacts.sh` 增加 "i18n interpolation guard" 步骤（PR frontend gate 直接执行）；`scripts/smoke.sh --profile contracts` 增加 self-test（CNB/GitHub smoke-contracts 层执行）。
- 验证：guard 在仓库上 **0 findings**；前端 gate **PASS**（含新步骤；首次因宿主 `EAGAIN` 线程耗尽失败，串行重试通过）；`pytest scripts` **532 passed / 1 skipped / 14 subtests**。

### 同轮追加：enrichment 门禁 + 真实 BUG（P 值输入阻断表单提交）

- `/tools/enrichment` 加 `enrichment.spec.ts`（public 套件，mock CORS API）3 用例：① ORA 断言完整 payload（assembly_id/genes/mode/ontology/p_threshold/max_terms/min_genes）、summary 计数、GO/ORA/`1 terms` 标签、terms 表（role=cell 的 p/q 值）；② GSEA 通过键盘切换 KEGG ontology，断言 payload 含 `values:[2.31,-1.2]`、summary、GSEA tag 与 `+0.420` ES；③ 空基因列表报错且零请求，越界 P 值被**原生 number 约束**拦下（不发请求）。
- **写用例过程中发现并修复一个真实产品 BUG**：P 值阈值输入框 `min=0.000001` + `step="0.01"`，浏览器把默认值 `0.05` 判为 **stepMismatch**，原生约束校验直接阻止表单提交——用户点"Run analysis"毫无反应、也无报错，整个 ORA/GSEA 工具实际不可用。修复：`step="any"`（校验仍由 onSubmit 负责），并在用例中加入 `checkValidity()` 回归断言。排查同类：seqfetch/scanpy/fastp/blast/admin 的数字输入均无此问题（整数或 min 与 step 对齐）。
- 验证：enrichment **3 passed**；全量 sweep **9/9 passed（224 s）**；workspace tests **908**；lint/typecheck **25/25**。

### 同轮追加：BLAST 提交流程离线化（原 skip 的 live 用例转为可执行门禁）

- `blast.spec.ts` 原先的 "completed job exposes JBrowse 2 + gene-search cross links" 是 `test.skip`（需要真实后端）。本轮改为 `stubBlastApis()` + 真实登录表单（static-server mock auth 返回 access_token）的**离线可执行**流程，新增 2 用例：
  1. **提交**：登录跳转 `/blast` → 默认数据库自动选中（`assembly_is_default`）→ 填 FASTA → 提交，断言 POST payload `{program:"blastp", database:"Wm82_v4_protein", query_sequence, parameters:{evalue:1e-5, max_target_seqs:50}}`；
  2. **结果与交叉链接**：mock jobs 列表（completed + running）→ 点 "View results" → 断言 hits 表的 `98.5%`、`1.00e-20`、基因 accession；JBrowse 深链为 `/browser?assembly=Wm82.a4.v1&locus=Glyma.01G000100%3A1000-2000`；点基因按钮后 SPA 跳到 `/search/genes?q=Glyma.01G000100&run=true`；无 pageerror。
- mock 注意点（已写入 spec 注释/代码）：登录也在 `/api/v1/` 通配路由内，需显式 mock `/auth/login`；EventSource `/jobs/events` 用 204 让页面回退轮询；hits 的 `subject_id` 同时用于基因列与 JBrowse locus，因此用基因 accession。
- 验证：blast spec **5 passed**（3 个表单/路由用例 + 2 个新流程用例）；全量 sweep **9/9 passed（228 s）**。

### 同轮追加：admin 认证后全部路由的 shell 挂载门禁

- `admin-shell` 门禁从"登录后只验证 shell"扩展到 **24 个已注册 console 路由**：`stubAdminApi()` mock `/auth/login` `/auth/refresh` `/auth/me`，其余数据端点一律返回 JSON 404（诚实的 error/empty 态）；每条路由逐一直达并断言 `shell-header` 可见、不弹回 `/login`、且整轮无 pageerror。
- 路由清单来自 `apps/admin/src/App.tsx` 的手工 route 树（文件式路由不适用；例如 `routes/usage-guide.tsx` 注册路径是 `/guide`）。初次运行就抓出清单错误（`/usage-guide` 显示 "Not Found"），修正后 24/24 通过——这正是"页面被重命名/路由未注册导致不可达"那类腐烂的早期报警。
- 验证：admin-shell 门禁 **2 passed**（登录 + 路由 sweep）；全量 sweep **9/9 passed（242 s，admin-shell 17 s）**。

### 同轮追加：portal ⇄ JBrowse postMessage 桥接离线门禁

- 新增 `browser-bridge.spec.ts`（public 套件）3 用例，用**同源 harness** 替换 iframe 文档，离线验证桥接契约（此前只有需要真实 JBrowse 部署的 `portal-embed` 门禁）：
  1. **握手**：`/browser?assembly=Wm82.a4.v1&locus=chr01:1000-2000&tracks=gene_models&release=R7` → iframe `data-bridge-status=ready`；在 iframe 内断言收到 portal 的 `init`（source=`soymutdb-browser`、version=1、payload assembly/locus/tracks）；随后 harness 发 `locus-change` → 断言 URL `locus` 与输入框同步为 `chr02:500-900`；
  2. **错误态**：harness 发 `error` envelope → `data-bridge-status=error`、`browser-error` 显示消息、`browser-open-new-tab-error` 存在（可恢复，不静默卡死）；
  3. **无上下文**：只有 `locus` 没有 assembly/release → `browser-missing-context` 且不渲染 iframe（不会静默替换默认 assembly）。
- 过程中确认两条构建事实（写进 spec 注释）：`/browser` 需要 **assembly + release 同时存在** 才渲染 iframe；iframe 文档 URL 可能是配置的绝对 JBrowse origin，也可能是构建未注入时的同源 `/jbrowse`，harness 路由必须同时覆盖两种形态。
- 验证：bridge **3 passed**；全量 sweep **9/9 passed（246 s）**。

### 同轮追加：analyses 模块门禁 + 真实 BUG（匿名访客发出个人请求）

- 新增 `analyses.spec.ts`（public 套件，mock auth + analyses API）3 用例：① 匿名访客只看到 "Research access required" 且 **零** 个人 `/analyses` API 请求；② researcher 会话走服务端列表（fastp/scanpy、running/succeeded 标签），点行进入 `/analyses/<job>` 并渲染 job 页；③ 列表端点 404 时回退到 localStorage `recent_jobs` 并通过 `GET /analyses/{id}` 解析出记录。
- **用例初跑即抓到一个真实 BUG**：jobs 查询挂在 `ResearcherGate` **外层**，匿名访客访问 `/analyses` 会先发出 `GET /api/v1/analyses?limit=50`（401 + refresh 尝试）再渲染门禁态——违反模块"匿名访客零个人请求"的约定（K-1 同类问题）。修复：把 job 列表拆成 `AnalysesJobList` 子组件放在 `ResearcherGate` 内部，匿名时不再挂载查询。
- 验证：analyses **3 passed**（修复后匿名请求为 0）；全量 sweep **9/9 passed（251 s）**；workspace tests **908**；web eslint 通过。

### 本轮未完成 / 下轮

- knip `types` 类别恢复与剩余公共 API 类型审计。
- 大版本升级（TS7/Vite8/Vitest5/zod4/pdfjs6/i18next26/react-i18next17 等）单独 ADR。
- Playwright 全量 E2E 需 `/soymutdb-next` base 专用构建。


## 历史快照（2026-10-05 及更早）

> **本段是历史快照，不是现状。** 当前状态见页首「当前状态（2026-10-17）」；下方版本、测试数字、环境缺口和“待执行”描述均按原日期保留，未重新核验的旧计划不自动结项。
>
> 单一状态视图。执行日志见 `.ai-memory/`，逐项设计与计划见 `docs/superpowers/specs/` 与 `docs/aegis/plans/`，
> 整合视图见 `docs/3.9升级优化文档.md`。本页在当时只回答「现在是什么状态」，且每一条都带本机实跑证据。
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

> **2026-10-02 实施轮：可做范围已完成**（证据见
> [`aegis/baseline/2026-10-02-w0-rebaseline.md`](../aegis/baseline/2026-10-02-w0-rebaseline.md) §8–§9）
>
> - W0–W3 完成，W4 可做范围完成，W6 框架就位；自 `9b63ddd41` 起共 6 个提交，均已推 `origin/main`（`cnb` 远端仍待凭据）。
> - **本页红灯已清 4 项**：`check:contract`、可见文案守卫（39 → **0** 文件）、
>   admin 架构守卫误报、query-key 守卫假绿。
> - **更正一条错误结论**：此前记为「无浏览器，窄屏与焦点无法验证」——**浏览器全程可用**
>   （playwright + chromium），现已实跑 10/10 通过，消融翻转 10/10 → 9/10。
> - **仍受阻**：无 psql/pgcli/Docker（数据库实测未跑）、无 `ant` CLI、无真实后端、
>   企业微信与部署目标未确认。**未取得任何性能结论，未做过任何生产变更。**

## 一句话

技术栈迁移与 Vue 退役已完成并可复跑；**真实缺口只剩两处**——管理后台的 Pro 业务组件体系
（8 个页面仍是裸 antd `Table`、`ProDescriptions`/`ProCard` 全仓 0 处），以及后端若干 mock 测试未跟上 release fail-closed 契约。
本机质量门禁 2026-10-05 复核**全绿**（前端逐包 + `scripts` 契约 350 项 + API 消融 149 项 + 可见文案守卫 0 文件）；
后端全量 pytest 在本机会被 OOM kill，没有可信的全量数字 —— 这本身就是一条待办。

## 技术栈现状（2026-10-05 实跑）

| 应用 | 框架 | 单测 | typecheck |
| --- | --- | --- | --- |
| `apps/web` | React 19 + Umi Max 4 + antd 6 | **29 files / 156 tests** | exit 0 |
| `apps/admin` | 同上 + ProLayout | **7 files / 43 tests** | exit 0 |
| `apps/jbrowse` | React + JBrowse 2 | 40 pass | exit 0 |
| `packages/api-client` | — | 28 files / 153 tests；`check:contract` **exit 0** | — |
| 其他包 | genome-view 43 · genome-data 121 · genome-view-model 23 · shared 49 · charts 5 · query-keys 11 · i18n-core 11 | 全绿 | — |
| `scripts`（Python 契约） | — | **350 passed / 1 skipped** | — |
| `apps/api` 消融 | — | 16 files / 149 passed / 0 failed | — |
| `apps/api` 新增端点 | `test_me_capabilities` + `test_active_release_endpoint` | **27 passed**（Docker-free，真实 HTTP） | — |
| `apps/api` 全量 | — | **无法在本机跑完**：约 47% 处被 OOM kill（EXIT=137） | — |
| `apps/worker` | — | 本机 `multiprocessing` spawn 失败，未取得数字 | — |

环境：`Node 24.19.0`（符合 pin）、`pnpm 12.5.1`、`Python 3.14.6`；本机 cgroup 受限，任何构建/测试都必须
`GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`，
否则 turbo/vitest/rayon 因线程耗尽直接崩溃。

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

> **2026-10-18 复核注记（历史红灯的当前状态）**：本表保留 2026-10-05 原文；逐项复核后，9 行均已关闭或已更正，**没有任何一行仍是当前红灯**。现状入口是页首「当前状态（2026-10-17）」。
>
> | 原行 | 当前状态与证据 |
> | --- | --- |
> | #1 可见文案守卫 39 文件 | 已关闭：`node scripts/check_visible_i18n_react.mjs` 目标 0 文件；该守卫仍由 `scripts/verify-frontend-artifacts.sh:88-90` 执行 |
> | #2 8 个裸 antd `Table` | 已关闭：`grep -rlE '<Table\b' apps/admin/src/routes --include=*.tsx` 0 命中；`apps/admin/src/components/data-table.tsx:2` 使用 `ProTable`，`apps/admin/src/regression/pro-table-migration.test.ts` 硬门禁 |
> | #3 ProLayout `<a href>` | 已关闭，且 ProLayout 已整体移除（`apps/admin/src/components/admin-shell.tsx:16-19` 记录替换原因）；导航由 `navigation-render.test.tsx` 覆盖 |
> | #4 API 全量 pytest OOM | 已关闭：2026-10-17 全量 API **2325 passed / 4 skipped**（页首 10-17 节）；Worker **659 passed / 8 skipped** |
> | #5 `Makefile` lint 路径 | 已关闭：`Makefile:199` 现为 `cd $(API_DIR) && ruff check app/` |
> | #6 pnpm pin 漂移 | 已关闭（原表已标注 2026-10-02 修复）；现行 pin 为 pnpm 12.11.2 |
> | #7 testcontainers 计数错账 | 已更正（原表已标注 2026-10-05）；不是红灯 |
> | #8 动效测试缺失 | 已关闭：`apps/web/src/lib/motion/ticker.test.ts`（419 行）与 `apps/web/src/lib/motion-prefs.test.ts` 已存在 |
> | #9 无浏览器 | 已关闭：真实浏览器 a11y/布局 **10/10**（页首 10-17 节） |
>
> 本表以下内容不再改动，仅作历史审计。

| # | 红灯 | 证据 | 归属 |
| --- | --- | --- | --- |
| 1 | ~~可见文案守卫 exit 1，39 个文件~~ | `node scripts/check_visible_i18n_react.mjs` | ✅ **2026-10-02 已修**：**exit 0，0 个文件**；R-12 关闭。同时修了守卫一处缺陷（React key 前缀被误判为文案），补 6 tests 防回归 |
| 2 | **8 个** admin 页面仍是裸 antd `Table`；`ProDescriptions` 0 处、`ProCard` 0 处 | `grep -rlE '<Table\b' apps/admin/src/routes --include=*.tsx` → `releases` `preview-test-data` `instances` `audit` `news/index` `news/trash` `table-views`（2 处）`content/static-page-migration-report` | 同上 A2/A3。**复核陷阱**：用 `<Table[ />]` 扫只命中 2 个——JSX 多写成 `<Table\n  columns=…`，同行匹配会漏；必须用 `<Table\b`。`ProTable` 目前只存在于门面 `components/data-table.tsx` |
| 3 | ~~`ProLayout.menuItemRender` 用 `<a href>`，侧栏点击整页刷新~~ | `apps/admin/src/routes/__root.tsx` | ✅ **2026-10-02 已修**：改用 TanStack `<Link>`（该规范 §3.1 早已批准），`navigation-render.test.tsx` 组件级覆盖 + 消融翻转 |
| 4 | API 全量 pytest OOM（EXIT=137 @ ~47%） | 实跑 | 新增待办：分片或降内存跑法需写进 `scripts/verify-backend-tests.sh` |
| 5 | `Makefile:197` lint 目标指向不存在的 `apps/api/src`（代码在 `apps/api/app`） | 实读 | 工具链缺陷，等修 |
| 6 | ~~`AGENTS.md:58,90` 写 pnpm `11.21.0`，仓库实际 `12.5.1`~~ | 实读 | ✅ **2026-10-02 已修**：改为 `12.5.1` |
| 7 | ~~「15 个 API 测试依赖 testcontainers，无 Docker 必然 SKIPPED」~~ | `grep -rlE '^\s*(import\|from)\s+testcontainers' apps/api/tests` | ✅ **2026-10-05 更正为错账**：真正 import testcontainers 的只有 `tests/conftest.py` **1 个**文件；其余 14 处 grep 命中是注释里的**否定句**（`no docker / no testcontainers`）。「SKIPPED ≠ PASS」的告诫仍成立，但受影响面远小于原记 |
| 8 | 随 Vue 退役丢失的契约覆盖：admin 会话、web 动效可访问性、页面定义 href 安全校验 | 对比 Vue 树被删的三个测试文件 | **已补两项**（导航可达性、门面导出）；W3 补 admin/web 会话（`lib/session.test.ts` 11 tests + `session-context.tsx`）；href 安全已有 `regression/url-safety.test.ts`（scheme 校验）。**仅剩动效**：`lib/motion/` 只有 `ticker.ts`、**0 个测试**，`motion-policy.ts`/`motion-prefs.ts` 亦无 |
| 9 | ~~「无浏览器，窄屏/焦点无法验证」~~ | `node e2e/verify-a11y-and-layout.mjs` | ✅ **2026-10-02 更正并完成**：playwright + chromium 实测可用，10/10 通过（skip link 为首个 tab stop、焦点指示可见、390px 无横向溢出、移动菜单可键盘打开）；消融翻转 10/10→9/10 |

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
- **可写隔离 Admin 环境缺失**：截图视觉验收、Admin save→公共渲染 E2E 仍 pending。
  （「响应式运行时检查」一项已由 `e2e/verify-a11y-and-layout.mjs` 在真实浏览器上完成，见「已知红灯」第 9 条。）
- **BLAS 线程数必须显式压到 1**：`check:contract` 会导入后端 FastAPI → SciPy → OpenBLAS，OpenBLAS 默认开 64 线程，
  在本机 cgroup 下 `pthread_create failed for thread 50 of 64`，脚本以 exit 1 结束。
  **这不是契约漂移**：补 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` 后同一命令 exit 0 / PASS。照本页旧的三变量 export 抄命令会得到假红灯。

## 待决策（不自行拍板）

见 `docs/3.9升级优化文档.md` §11：`public_id` 正式格式、internal 检索角色名单、无 assembly 查询的 UX、
v4↔v5 映射展示规则、生产对象存储选择、主导航口径、Gene ID 单行 vs 批量、页脚导航初始 bounds 等。

## 复现

```bash
# 前端（逐包；本机比 turbo 稳）。五个变量缺一不可，见「环境阻碍」的 BLAS 说明。
export GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
for p in @soymutdb/api-client @soymutdb/charts @soymutdb/genome-data @soymutdb/genome-view \
         @soymutdb/genome-view-model @soymutdb/i18n-core @soymutdb/query-keys @soymutdb/shared \
         @soymutdb/web @soymutdb/admin @soymutdb/jbrowse; do
  pnpm --filter "$p" run lint && pnpm --filter "$p" run typecheck && pnpm --filter "$p" run test
done

# 交付与平台契约（2026-10-05 实跑：全绿）
python3 -m pytest scripts -q                                        # 350 passed / 1 skipped
node scripts/check-react-entry-graph.mjs                            # exit 0
node scripts/check-vue-retirement.mjs                               # exit 0
bash scripts/check-dockerfile-copy.sh                               # exit 0
node scripts/check_visible_i18n_react.mjs                           # exit 0，0 个文件
pnpm --filter @soymutdb/api-client run check:contract                # exit 0 / PASS（务必带 BLAS 变量）

# antd CLI（需要 HOME 可写）
HOME=$PWD/.validation/home ./node_modules/.bin/antd lint apps/admin/src
HOME=$PWD/.validation/home ./node_modules/.bin/antd info Table

# 后端。两个变量缺一不可，2026-10-05 实测：
#  (1) PYTHONPATH 必须是**仓库根绝对路径**。不设时 tests/a0 报 ModuleNotFoundError: tools
#      并中断整个 collect（1851 collected / 1 error）；设对后 1896 collected / 0 error。
#      相对路径 "$PWD/.." 与不设**完全等价**，无效。门禁 verify-backend-tests.sh:76 本来就设了。
#  (2) 跑 DB 相关用例要 SOYMUTDB_TEST_DATABASE_URL；缺它时消融 20 个用例报连接错误。
cd apps/api
export PYTHONPATH="/mnt/data02/T25ronglin/code/web"
export SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb'
.venv/bin/python -m pytest tests --collect-only -q          # 1896 collected, 0 error
.venv/bin/python -m pytest tests/test_ablation_*.py -q     # 149 passed
.venv/bin/python -m pytest tests/test_me_capabilities.py \
                  tests/test_active_release_endpoint.py -q  # 27 passed，无需 DB
# 全量在本机 OOM（EXIT=137 @ ~47%），需分片或降内存跑法，见「已知红灯」第 4 条
```
