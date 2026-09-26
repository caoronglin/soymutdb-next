# SoyMutDB 消融审计与执行任务书（交 PI-AGENT）

> 审计日期：2026-09-26。对象是当前工作树，不是旧版验收文档中的历史快照。
> 本文只给出已审计事实、执行顺序和验收门禁；本轮没有修复产品代码或改动生产数据。
> 当前判定：**生产发布 No-Go**。公开数据边界、assembly 搜索和真实数据写入仍有阻断项。

## 1. 任务边界与证据口径

PI-AGENT 的目标是逐项关闭本文的已确认缺陷与未完成能力，并留下可复核的失败前、修复后证据。不得把“契约文档定义了目标”“脚本存在”“测试被跳过”写成已经交付。

审计开始时 `HEAD=7bf002a29`，工作树已有约 149 个受跟踪文件的未提交改动及多项未跟踪文件。它们是现有工作，不属于本审计可清理的临时物。每个执行 Wave 开始前重新运行 `git status --short`、`git diff --stat` 并登记归属；禁止 reset、覆盖或顺手提交无关文件。

证据等级：

| 等级 | 可以据此声称 | 不能据此声称 |
| --- | --- | --- |
| E1 当前代码的真实行为对照 | 指定输入和环境下的复现结果 | 未运行环境、真实部署也必然相同 |
| E2 当前源码与配置追踪 | 调用链、缺失分支、门禁接线状态 | UI/HTTP 实际可用或数据库兼容性已验证 |
| E3 历史文档/既有测试记录 | 以前的目标、已知差距和测试设计 | 当前工作树已通过同一门禁 |

本轮 API SQL 逻辑实验用了**一次性 SQLite 内存表**，仅辅助验证当前 SQLAlchemy 条件；它不能代替仓库要求的 PostgreSQL 集成测试。浏览器 CSS 消融使用本机构建产物；它证明阻断 CSS 的后果，不证明正式部署正在丢失 CSS。

## 2. 消融实验与当前基线

| 因素（只改一项） | 对照 / 消融结果 | 证据级别与解释 |
| --- | --- | --- |
| 变异列表查询键中的 `cursor` | 当前键不含 cursor：首屏与游标页键相同，查询函数调用 1 次，游标页读到 `first-page`；控制键加入 cursor：键不同、调用 2 次，游标页读到 `cursor-page` | E1：当前 `queryKeys.variants.list` 和真实 Vue Query `QueryClient` 内存缓存；见 `apps/web/src/lib/query-options.ts:382-412`、`packages/query-keys/src/index.ts:160` |
| 突变体的 release 约束 | `is_public=True` 且 `release_id=NULL` 的合成行进入公开 `/mutants` 列表 | E1（SQL 逻辑）+ E2：`apps/api/app/api/v1/mutants.py:24-50`；PostgreSQL HTTP 验证未做 |
| 无 assembly 查询的分页 | 同一 accession 分别属于 v4/v5；`limit=1` 时返回一个版本，却给出 `ambiguous=False`、`by_assembly={'1':1}`、`has_more=True` | E1（SQL 逻辑）+ E2：`apps/api/app/services/search_service.py:487-515`，分组和歧义在截断后计算 |
| 内部编号检索 | 以公开 ID 查询命中同一合成突变体；以现存内部编号 `41` 查询无结果 | E1（SQL 逻辑）+ E2：`apps/api/app/services/search_service.py:922-960` 没有按内部主键匹配 |
| 无 active release 的 autocomplete | 指定 release 时只返回该版本建议；传 `None` 时还返回草稿版本建议 | E1（SQL 逻辑）+ E2：`apps/api/app/api/v1/search.py:213-231`、`apps/api/app/services/search_service.py:1099-1130` |
| VCF 双样本基因型 | `[control=0, mutant-a=1]` 选择 `mutant-a`，却读取 `gt_types[0]` 得到 `homozygous_ref`；按所选样本读取则为 `heterozygous` | E1：从当前 `ingest.py` 抽取真实函数，在 `/tmp` 合成输入运行；见 `apps/worker/src/soymutdb_worker/tasks/ingest.py:598-607` |
| VCF assembly 身份 | 同 release、染色体、位置、REF/ALT 的 v4 与 v5 得到同一个 `variant_id`；将 assembly 纳入对照散列后不同 | E1：当前 `compute_variant_id` 对照；见 `apps/worker/src/soymutdb_worker/tasks/ingest.py:313-329` |
| ClickHouse 汇总清理 | 保留 `finalize_release` 的 summary purge：facts=2、summary=2；只去掉 purge：facts=2、summary=4 | E1：嵌入式 chdb 合成数据。**这是现有保护措施有效的证据，不是当前 BUG**；见 `apps/worker/src/soymutdb_worker/tasks/variant_finalize.py` |
| 管理端选中实例 | 从 local 改选 `peer-cn`，News 视图仍不读取实例上下文，创建请求仍固定 `/admin/news` | E2：源码依赖对照，未执行真实登录后写入；见 `apps/admin/src/views/NewsAdminView.vue:1-80`、`packages/api-client/src/admin-news.ts:206` |
| CSS 请求 | 相同静态页面和浏览器、禁 API 与 SW，仅阻断 CSS：390px 公共站入口 `grid→block`；1440px 管理端表单 `352→1424px` | E1：本机 web/admin 静态产物的 Chromium 对照。页面仍 hydrate，无 pageerror；不能据此声称线上有 CSS 故障 |
| Pages 制品完整性 | 临时目录含 Web/JBrowse 入口和校验和时 `verify-pages-artifact.sh` exit 0；仅删除 JBrowse 入口时 exit 1 | E1：验证器对缺少浏览器入口能拦截；见 `scripts/verify-pages-artifact.sh:49-52` |

已运行 `PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS='-p no:cacheprovider' bash scripts/smoke.sh --profile contracts`：**232 项 contract 测试和 10 项 environment-bound 检查通过，0 失败、0 跳过**。`git diff --check` 通过。这两个结果不替代 PostgreSQL、ClickHouse 生产 DDL、双站制品、实际部署和完整浏览器流程。

## 3. 按优先级执行的问题清单

### P0：公开边界与发布门禁

| ID | 当前事实 | PI-AGENT 的完成判据 |
| --- | --- | --- |
| P0-01 公开突变体 release 漏检 | `/mutants` 列表、详情、phenotypes 共用的可见性条件只有 `is_deleted`、`is_public`、`public_id`，未限制 active published release；模型允许 `release_id=NULL`。来源：`apps/api/app/api/v1/mutants.py:24-105`、`apps/api/app/models/variant.py:138-169`。 | PostgreSQL fixture 同时含已发布、草稿、空 release、内部 ID；三个公开入口只返回当前已发布记录，统一 404 不形成存在性 oracle；响应、URL、日志和 external 产物零私有编号。 |
| P0-02 suggest 失去 release 时扩大可见范围 | `resolve_release_context` 失败被降级为 `release_id=None`，service 因此不加 release 条件。来源：`apps/api/app/api/v1/search.py:213-231`、`apps/api/app/services/search_service.py:1099-1130`。 | 无公开 release 时 fail closed 或返回明示不可用；草稿 assembly 的 accession 不出现在匿名建议；缓存键与响应策略纳入回归。 |
| P0-03 无版本搜索歧义会被分页隐藏 | `hits[:limit]` 之后才汇总 `by_assembly/ambiguous`；`limit=1` 可把 v4/v5 重名结果标成不歧义。客户端 `SearchResponse` 又没有 `by_assembly/ambiguous`，页面未显示每条 assembly/release/source。来源：`apps/api/app/services/search_service.py:487-525`、`packages/api-client/src/search.ts:17`、`apps/web/src/views/SearchView.vue:122-221`。 | ASM-01～ASM-05：未指定 assembly 时先按全集判断歧义，明确分组或要求选择；指定版本只命中该版本；网页能显示版本、release 和来源，深链/JBrowse 保持上下文。 |
| P0-04 内部 ID 检索契约不闭环 | 已授权内部查询只按 name/public ID，不能按 `MutantLine.id` 查找；现有名为 “either id” 的测试只测 public ID 与 lab name。来源：`apps/api/app/services/search_service.py:922-960`、`apps/api/tests/test_search_database_integration.py:395-415`。 | 授权内部用户按 public ID 和 internal ID 指向同一记录，标明 matched_field 并审计；未授权为 401/403，外部匿名输入内部 ID 不泄漏。 |
| P0-05 首版真实数据门禁 | `scripts/seed_release_data.py:492-536` 即使打开 `SOYMUTDB_SEED_ENABLED=1` 仍拒绝 PG/CH 写入；`docs/ops/acceptance-current-state.md:21-50` 把 G10/G12 判 No-Go。 | 先冻结权威来源/版本/许可与样本映射、确认 ClickHouse canonical schema，再在隔离环境完成写入/幂等/回滚与 `validate-release-data.sh`；没有真实 release 的 D/C/P 验证不得发布。 |
| P0-06 两套 CI 的发布前置条件不等价 | GitHub frontend job 执行双站制品隔离检查，CNB 对应验证不执行；GitHub 镜像发布依赖 `kubernetes-kind`，CNB 发布只等待架构镜像包。来源：`.github/workflows/ci.yml:158-162,479-482`、`.cnb.yml:125-142,392-421`。 | 将双站和 Kind 共同门禁接入共享脚本与两个 provider；契约测试断言实际依赖等价。故意制造隔离失败/Kind 失败时，CNB 与 GitHub 都不得发布；验证器与发布器继续分权。 |

### P1：数据正确性、工作流与交付一致性

| ID | 当前事实 | PI-AGENT 的完成判据 |
| --- | --- | --- |
| P1-01 VCF assembly 隔离 | `compute_variant_id` 不含 assembly；finalize 触及的分区按 release/chromosome 清理，跨 assembly 相同染色体可能互相覆盖。来源：`apps/worker/src/soymutdb_worker/tasks/ingest.py:313-329`、`apps/worker/src/soymutdb_worker/tasks/variant_finalize.py:263`。 | 同 release 的 v4/v5 相同 locus 生成不同身份；重跑单一 assembly 不改动另一 assembly 的 facts 或汇总；ClickHouse 集成测试覆盖两版本。 |
| P1-02 VCF 样本错配 | mutant line 选首个非参考样本，zygosity 固定取 `gt_types[0]`。来源：`apps/worker/src/soymutdb_worker/tasks/ingest.py:598-607`。 | 两样本顺序互换、多 ALT、缺失 GT 的行级测试对照选中样本与 genotype；结果写入与读取一致。 |
| P1-03 VCF 导入管线未闭环 | VCF capability 默认关闭；启用后走 staging/finalize，但 `variant_facts_staging` 只在测试 fixture 中建表，`infra/clickhouse` 生产 DDL 无此表。来源：`apps/worker/src/soymutdb_worker/tasks/ingest.py:72,505,719-753`、`apps/worker/tests/fixtures/variant_facts_schema.sql:24`。 | 建立带升级/降级验证的生产 staging schema；在真实 ClickHouse 空库和升级库中跑导入→重试→发布；完成前继续 fail closed，不把 flag 开启视作功能完成。 |
| P1-04 变异游标缓存撞键 | 请求发送 cursor，查询键只含页码；从带 cursor 的 URL 重挂时页码可回到 1。来源：`apps/web/src/lib/query-options.ts:382-412`、`apps/web/src/views/VariantsView.vue:117`、`packages/query-keys/src/index.ts:160`。 | cache key 含 release、site variant、assembly、filters、cursor/分页位置；首屏→Next→Back→Forward 和直接打开游标 URL 都显示正确页，命中/未命中路径均测试。 |
| P1-05 搜索和变异结果不完整 | Search 有 `next_cursor/has_more` 却无可见翻页；Variants 可选 All assemblies 但行无 assembly 字段/列。来源：`apps/web/src/views/SearchView.vue:28,192-221`、`apps/web/src/views/VariantsView.vue:217,297`、`packages/api-client/src/variants.ts:3`。 | 有可键盘操作的前后页；All assemblies 的每行显示机器可用 ID 和人可读 name/version，或禁止无版本混合查询。 |
| P1-06 管理端迁移缺口 | 当前 Dashboard 只读 release 摘要；Imports 仅有列表/筛选/分页；19 条旧深链落到明确的 `LegacyUnavailableView`。来源：`apps/admin/src/views/DashboardView.vue:19`、`apps/admin/src/views/ImportsView.vue:38`、`apps/admin/src/router/index.ts:51-69`。 | 先恢复导入创建/上传/校验/提交/取消/重试/详情，再恢复真实 Dashboard 指标；旧深链逐条可用或明确留在能力矩阵中，不把“未恢复”算作完成。 |
| P1-07 远端实例目标提示 | 选中远端只改变界面上下文；News 创建仍固定本地 API。全局 badge 有 registration-only 标签，但编辑表单旁没有实际写入目标说明。来源：`apps/admin/src/components/InstanceContextBadge.vue:19-57`、`apps/admin/src/views/NewsAdminView.vue:1-80`。 | 在隔离双实例环境选远端后实测按钮、请求目标和写入落点；远端写保持关闭，所有本地写表单明确显示本地 API/实例，避免把远端 badge 当写入目标。 |
| P1-08 生产门禁覆盖不全 | 默认 Playwright 配置只匹配 online smoke；Admin 套件只测登录页；JBrowse 生产 gate 找不到 frame 时可能只凭标题通过。来源：`e2e/playwright.config.ts:22`、`e2e/tests/admin-production-login.spec.ts:14`、`e2e/tests/production-gate.spec.ts:113`。 | 明确把 public、admin、JBrowse 关键 E2E 接入共享 CI job；JBrowse frame 缺失即失败；认证后真实工作流、部署 CSP/缓存/SW/子路径都在目标环境实测。 |

### P2：后续能力与维护成本

- News 当前只提交英文字段，双语正文、预览/排序尚未恢复；`/news/trash` 已转 archived 筛选，不应误写为完全缺失。来源：`apps/admin/src/views/NewsAdminView.vue:71`。
- 品牌设置只接受 URL，媒体页未提供选择并应用 READY 图标的闭环；管理端外壳仍用静态标题/favicon。来源：`apps/admin/src/views/SiteBrandSettingsView.vue:173`、`apps/admin/src/views/MediaView.vue:23`、`apps/admin/index.html:15`。
- React 旧 `/table-views` 缺少到当前 `/table-templates` 的别名。来源：`apps/admin/src/router/index.ts:32-70`。
- 多类 FASTA/GFF3/BLAST DB/通用 CSV adapter 仍明确拒绝；不得用导入任务 ID 或列表外观宣称已写入门户数据。来源：`apps/worker/src/soymutdb_worker/tasks/data_adapters.py:121-199`。
- VCF 成功路径保留 staging 行，生产 schema 建立后须决定删除/TTL 与重试保留期限；先量化空间增长，再改清理策略。来源：`apps/worker/src/soymutdb_worker/tasks/ingest.py:719,773`。
- Web 性能测试把总传输量覆盖成首屏 JS+CSS，3 MB 门禁未计 fonts/favicon/SW；报告使用字面量 `\\n` 且只断言文件存在，不解析 JSON。应在新构建产物上修正测量与报告校验。来源：`e2e/tests/web-artifact-performance.spec.ts:93,139,153`。本机 index 引用的未压缩首屏资源约 952 KB（Web）/565 KB（Admin），**不是线上网络传输量或性能结论**。
- 基线 staging/production workflow 目前只做配置检查和安装 dry-run，明确未执行远端部署；不能把这些 job 的绿色状态称为生产部署完成。来源：`.github/workflows/baseline-validation.yml:308,333`。
- `.github/workflows/baseline-validation.yml` 尚有内联测试/部署逻辑，与 `AGENTS.md` 的“workflow 只调用共享脚本”规则不符；需要判断是否为旧流程并迁入相同 job body，再由 CI 契约测试守护。
- `AGENTS.md:58,90` 仍写 pnpm `11.21.0`，当前 `package.json:6-9`、锁文件、CI 和 pin guard 均为 `12.5.1`；应统一指引，不能擅自把当前仓库降级。`docs/dev/vue-migration-recovery-status.md:154` 的 8000 旧状态已被同文件第二轮 8010 记录取代，阅读时以现行源码为准。

## 4. PI-AGENT 的执行顺序与每 Wave 出口

| Wave | 范围与依赖 | 必交证据 / 出口 |
| --- | --- | --- |
| 0 保全与基线 | 固定当前差异、工具链、测试环境；确定可复制的 ext4 运行时和一次性 PostgreSQL/ClickHouse；保留用户未提交改动。 | `git status`、当前 pin、可运行/不可运行命令及原因；每个问题的失败前合成 fixture；不得先大规模改码。 |
| 1 公开边界 | 修 P0-01/02/04，API、模型/迁移、OpenAPI/client、缓存和审计成对演进。 | PostgreSQL 支持的 external/internal × public/internal ID × released/draft/NULL release 负例；响应、URL、日志、external 制品泄漏扫描；迁移升级/降级。 |
| 2 assembly 与 VCF | 在 Wave 1 契约稳定后修 P0-03、P1-01/02/03；先确定 assembly 与 release 在 PG/CH 的键。 | v4/v5 同名但不同实体、显式 crosswalk、同位点变异、双样本 genotype；ClickHouse 实际 DDL、重跑和汇总不重数；无跨版本静默合并。 |
| 3 公共站 | 对齐 typed client、查询键和页面；修 P1-04/05。 | external/internal 双构建；搜索→结果→详情→JBrowse 深链；cursor 直接访问/前进后退；中文/英文、空/错/加载、窄屏和键盘路径；无 internal ID/未发布哨兵。 |
| 4 管理端 | 恢复导入和 Dashboard；对远端选择做隔离实验，补 News/品牌与旧路由矩阵。 | 带认证真实浏览器和隔离测试记录：导入→验证→发布→审计；远端被选中时本地写入目标明确、远端写拒绝；旧深链逐项确认。 |
| 5 双 CI 与发布 | 修 P0-06/P1-08；统一 CNB/GitHub 的 job body、Kind/双站前置依赖，补生产数据链和部署验证。 | 两 provider 同一脚本字节、同一前置 gate；故障注入均阻断发布；双站制品扫描、Pages 字节验证、runtime/health、PRR 六维；G10/G12 未过则维持 No-Go。 |

Wave 不等于一次提交。每项改动要有独立失败前证据、最窄回归、相关根质量门禁和回滚点。可并行的只读调查可以分派；修改同一契约的任务应指定唯一集成者。

## 5. `dev-expert` 强制执行约束（PI-AGENT 不得省略）

以下约束从用户指定的 `dev-expert` 技能提取，并结合本仓库的 `AGENTS.md`、`docs/dev/database-core-contract.md` 落为验收门禁；不依赖 PI-AGENT 是否安装同一技能。

1. **六步闭环**：分析→方案→执行→验证→交付→复盘。审计与修复分离；本文属于审计/方案，不是修复完成声明。每个 BUG 先复现、列假设、只修根因，失败用例转为回归测试。
2. **PLAN-GATE 三池**：动码前逐项登记 A 池 10 项：需求→步骤、每步出口、数据/外部依赖、风险缓解、证据类型、回滚、批量范围、安全触发面、人工修改遍历、中断恢复；B 池按数据库迁移、新依赖、并发/幂等、性能、外部接口、测试、批处理、不可逆操作、多文件依赖、脚本参数、回读逐项写通过或 N/A 理由；≥5 文件/≥10 修改点每 5 文件留 CHECKPOINT，跨 Wave 留 handoff。方案不得残留未定义占位符，引用的函数/字段/配置须回源码确认。
3. **实码与影响面**：修改前读目标文件、搜索所有引用、检查与现有未提交改动冲突。跨模块先查依赖两跳并用 `rg` 复核；API/OpenAPI/client、写入/读取、缓存 set/get、外站/内站、v4/v5 是成对契约，不能只修一端。
4. **证据分级与 L0 真实入口**：静态/lint/单元测试不能替代真实 UI/HTTP 操作。用户可达页面必须有真实浏览器或 HTTP 入口→操作→DOM/行为/响应断言；纯库函数也要走真实调用路径。每个结论附命令、退出码、关键输出或截图；无法验证则标未验证。P0 身份、隐私、assembly 和隔离场景不得 skip/xfail 充数。
5. **覆盖完整性**：枚举对称操作、空/单条/边界/非法/大数据形态、所有调用方和成功/失败分支；迁移后 grep 确认无新旧范式混用。查询键与实际请求参数须同源；命中和未命中缓存两态都测。已通过的单个样本不得外推整个矩阵。
6. **安全闸门**：生产配置、DB 写入、权限、凭据、隐私及不可回滚操作先给影响范围、回滚和验证路径，缺业务授权时不得执行。PI-AGENT 和子代理不得写生产库、擅开 VCF/seed flag、提交 secret 或把内部 ID 带到外站。PostgreSQL 是权威；ClickHouse 为投影，Redis 为可丢缓存，不得新增 SQLite 权威路径。
7. **批量修改与收敛**：同操作 ≥3 文件或 ≥10 处时先预检、3–5 文件试点、备份、逐文件日志、后检、差异校验、回读；失败批次回退。单 Wave 默认最多 3 轮、上限 6 轮，每轮不超过 3 个改动点；同一 BUG 2 轮未修须记限制与下一方案，不可碰运气扩大范围。
8. **子代理边界**：检索/审查代理只报文件行号、实验和问题清单；执行代理由主代理限定目标、边界、验收后才落码。主代理复核子代理结论，不得直接把未复核报告当完成。子代理不得越权操作 DB、生产配置、权限或凭据。
9. **PRR 与发布**：发布前逐项通过可观测、可靠性、容量、安全、数据、流程六维；阻断项未闭环不得发布。镜像验证与发布分离，PR 不持有发布凭据；渐进式发布要预写回滚条件和发布后观测。`scripts/smoke.sh` 的 SKIPPED 只说明缺前置条件，不算 PASS。
10. **交付和复盘**：每 Wave 记录“已完成及证据/相关文件/未完成/阻塞”四字段检查点；最终按需求逐条映射代码与测试，列已知限制和剩余风险，不得报“全部通过”掩盖 PostgreSQL、双站、浏览器或真实部署缺口。性能优化必须有前后耗时/内存/吞吐基线，静态嫌疑只列为待测。

项目特有硬约束继续以 `AGENTS.md` 和 `docs/dev/database-core-contract.md` 为准：公开 mutant 只用 `public_id`；外站只读已发布记录；v4/v5 分 namespace；跨版本只认有 provenance 的显式关系；site variant 必须在构建/部署中显式选择，缓存键包含 variant、release、assembly、query、filters、分页；内部响应 `private, no-store`。若 PI-AGENT 发现本文与现行源码或上位契约冲突，先记录证据并修正文档，不能静默选择一方。

## 6. 发布判定和待补实证

PI-AGENT 在以下证据齐备前不能把本任务或生产发布标为完成：

- PostgreSQL-backed 的 ID-01～ID-05、ASM-01～ASM-05、CTX-01～CTX-03，含未发布哨兵的响应/URL/日志/`dist/external` 零泄漏。
- v4/v5、同 accession 不同实体与显式 crosswalk 的真实查询、变异/VCF/ClickHouse 导入和重算；生产 staging DDL 的升级/降级。
- external/internal 两套制品、不同 origin/CORS/CSP/SW/cache 策略及浏览器访问；Admin 认证后真实导入和目标实例路径。
- CNB/GitHub 相同的验证与发布依赖、完整 CI 绿灯；实际 staging/production 健康、备份恢复和 PRR。G10/G12 仍是明确 No-Go，除非真实数据来源与写入/校验门禁实测通过。

本轮受本机环境限制，PostgreSQL 55432 未监听，仓库 SMB 上 API/Worker `.venv/bin/python` 无执行位，当前 shell Node 为 26.8.1（仓库 pin 24.19.0），前端工作区安装依赖不完整。本机 `dist` 的 HTML/CSP 使用 localhost 与根路径，且本地静态服务没有应用 `_headers`；它不能替代正式 Pages 子路径产物和部署响应头。后续应在隔离 ext4 运行时和匹配工具链下补测，不要在共享 SMB 文件上改执行位后把环境修复当代码修复。

## 7. 资料来源

- `AGENTS.md`：架构不变量、交付脚本、身份/assembly/站点边界与 P0 测试矩阵；pnpm 数字需按 §3 的当前文件漂移处理。
- `docs/dev/database-core-contract.md`：DB-CORE-1～6、ID/ASM/CTX/UI/E2E 强制场景；其 §3 是 2026-09-06 旧基线，不是当前实现结论。
- `docs/dev/vue-migration-recovery-plan.md`、`docs/dev/vue-migration-recovery-status.md`：Vue 迁移前 React commit、已知旧路由及本机验证历史；以较新轮次和现行源码复核。
- `docs/ops/acceptance-current-state.md`、`docs/ops/route-b-seed-data-design.md`：真实数据和 G10/G12 No-Go。
- 用户指定的 `dev-expert/SKILL.md` 及 `references/execution-safety.md`、`references/delivery-assurance.md`、`references/doc-generation.md`：§5 的执行纪律与证据门禁。
