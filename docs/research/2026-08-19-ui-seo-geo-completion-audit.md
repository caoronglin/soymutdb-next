# SoyMutDB UI 完成度与 SEO/GEO 升级计划

> 日期：2026-08-19
> 范围：`apps/web`、`apps/admin`、`apps/jbrowse`、前端构建与浏览器门禁。SEO/GEO 本轮只制定计划，不实施配置。
> 方法：四个子智能体静态审计、主控复核、生产构建产物检查，以及 Playwright 桌面/移动端验证。

## 1. 执行结论

当前 UI **不满足生产完成验收**。Public Web 可渲染且已有基础 E2E，但存在认证、assembly 上下文、占位内容和错误态问题；Admin 的最新 production bundle 首屏空白；JBrowse 外壳可渲染，但非默认 assembly 的 fallback 可能错误映射到 Wm82 v4 数据。任何平均分都不能抵消这些 P0。

数据库路线不变：PostgreSQL 是生产控制面的权威数据库。SQLite 只适合作为未来独立、单进程、功能受限的演示 profile；不得暗示支持并发 outbox、发布切换、导入互斥或 Celery 多写者。

## 2. 评分口径与结果

每项按 0–10 计分；“完整=1、部分=0.5、缺失或危险=0”。生产可运行性使用 JS 启动、首屏、核心数据、控制台健康四项。分数是排期工具，不是发布许可。

| 应用 | 功能 | 状态 | 直接 UI 测试 | i18n/a11y | 响应式/视觉 | 生产运行 | 综合 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Public Web | 6.4 | 8.0 | 1.8 | 6.0 | 6.0 | 5.0 | **5.5** |
| Admin | 5.0 | 3.2 | 0.5 | 3.3 | 0.0 | 0.0 | **2.0** |
| JBrowse | 5.0 | 3.3 | 0.0 | 3.8 | 7.5 | 5.0 | **4.1** |

Public Web 的 34 个路由中，13 个完整、15 个部分完成、4 个为占位/非生产数据，2 个无法静态判定。Admin 的 19 个路由中，4 个完整、11 个部分完成、2 个有破坏性缺陷、2 个为文档/占位。54 个 UI surface 中，仅 6 个具有功能旅程级 Playwright 源码，部署前浏览器门禁为 0。

## 3. 浏览器证据

目标流程：应用加载 → 首个有效页面渲染 → 导航或输入产生可见状态 → 无错误层和相关控制台错误。

| 检查 | Public Web | Admin | JBrowse |
| --- | --- | --- | --- |
| 页面身份/非空/无框架错误层 | 通过 | **非空失败** | 通过 |
| 1440×900 与 375×812 | 均渲染，无横向溢出 | 均为空白 | 均渲染，无横向溢出 |
| 交互 | 首页进入 Gene ID 并恢复输入成功 | 登录控件不存在，失败 | locus 输入执行；无参考数据时无法解析 |
| 控制台/资源 | 离线 API 503、widget 404；无 page error | **`Cannot access 'xn' before initialization`** | API/FASTA 离线失败、JetBrains 字体 404、JBrowse 弃用警告 |

仓库 Public Playwright 套件实跑结果为 **24 passed、2 skipped**。跳过项依赖真实后端，不能作为生产旅程证据。Admin 重新构建成功但报告 `Circular chunk: antd -> rc -> antd`，随后 production bundle 稳定复现空白；该循环分包是高度相关原因，精确符号根因仍需 sourcemap/最小分包实验确认。JBrowse 的 `.fai` 404 只证明本次无数据静态环境不能完成核心浏览，生产反向代理和真实数据状态仍为 UNKNOWN；字体路径缺失则由构建警告和产物共同确认。

## 4. P0 发布阻断项

1. **Admin production bundle 空白。** 先移除 `antd`/`rc` 的循环手工分包，建立“构建最终产物→静态服务→登录页非空→零 page error”的 pre-deploy smoke。
2. **Admin 存在破坏性保存路径。** Settings 未先读取真实配置即可提交默认值，失败后仍可能显示成功；Layout 加载失败会降级为空布局且允许保存。加载成功前必须禁止编辑/保存，并区分 error、not-found 和 empty。
3. **科学上下文可能错配。** Public Gene 深链可能查询 assembly A、标记并跳转 assembly B；JBrowse 非默认 assembly 在 API 未返回时会复用 Wm82 v4 URL。统一 resolved assembly，并对非默认 assembly fail closed。
4. **Public 登录是假流程。** 当前只延迟导航，不建立会话；应接入真实认证，或移除该入口并跳转到受支持的身份提供方。
5. **公开内容真实性冲突。** Publications 含仓库测试认定“未验证”的 DOI。在维护者核验前移除或明确标记示例，避免被搜索和生成式答案放大。
6. **发布证明链不闭合。** standard SSG 依赖未由 CI 提供的 API，Pages 先部署后 E2E，static smoke 在快照缺失时成功跳过。最终制品必须先通过封闭 fixture build、manifest/static-tree 校验和 Chromium smoke，再部署相同字节。

## 5. 分阶段 UI 升级计划

| 阶段 | 负责人边界 | 主要交付 | 退出条件 |
| --- | --- | --- | --- |
| Wave 0：发布止血（1–3 天） | Build/UI | 修复 Admin 空白；拆分 online/public/primer E2E；隐藏假登录、pilot、未核验出版物；危险保存 fail closed | 三应用最终产物首屏非空、零 page error；P0 回归测试通过 |
| Wave 1：功能闭环（1 个 Sprint） | Web/Admin/JBrowse | 接通 Export、Details、Preview、PageDefinition action；错误与空数据分离；修复游标、版本基线、RBAC/capability、locus 坐标和 bridge source | 每个可见 action 有导航、请求或明确 disabled 原因；500/403 不再显示成功或空数据 |
| Wave 2：关键旅程门禁（1 个 Sprint） | QA/Platform | 登录保护、Search→Gene、BLAST、Analysis 上传→结果、Portal→JBrowse 五条 mocked-contract E2E；最终 Pages 制品 pre-deploy Chromium smoke | PR 阻断门禁稳定；无 silent skip/zero-test；路由级 UI 覆盖优先达到 80% 核心路由 |
| Wave 3：体验与性能（1–2 个 Sprint） | Design/UI | 菜单/抽屉焦点模型、44px 触控区、skip link、对比度、三应用 i18n；修复字体；按路由延迟加载 ECharts/Tiptap/JBrowse | axe 关键页无 serious/critical；320–1440px 无溢出；语言资源等价；bundle budget 通过 |
| Wave 4：真实集成验收 | Platform/Data | PostgreSQL、MinIO、Celery、真实 release 与 JBrowse 数据下跑上传、SSE、下载、deep link、发布/回滚 | 环境级旅程通过，数据 release/assembly 身份可追踪，恢复演练完成 |

## 6. SEO 与 GEO 计划

GEO 指面向生成式搜索/答案引擎的可发现性和可引用性。它不能保证排名，也不能替代技术 SEO、真实内容与外部权威引用。

### 当前基线（CONFIRMED）

| 能力 | 当前状态 |
| --- | --- |
| title/description | 9 个基础 SSG 页面具备；多数 SPA 路由没有 route-level head |
| canonical | 基础 SSG 硬编码 `soymutdb.org`；Pages sitemap 使用部署环境 URL；News SSG 未传 canonical |
| hreflang | 不存在；语言由 localStorage/browser 决定，没有稳定语言 URL |
| robots/sitemap | 多个脚本分别写入；基础列表与真实 SSG 路由不一致，sample 最多 200 条，`lastmod` 使用构建日 |
| Structured Data | 仅 sample `Dataset` 和 News `Article`，缺 release、license、author/publisher、distribution 等关键字段 |
| OG/Twitter | 有基础 title/description/type/card，缺 `og:url`、图片和完整 Twitter fallback |
| HTTP/404 | SSG 输出平铺 `.html`；Pages 把首页复制成 `404.html`，仓库 E2E 文档已记录多个合法路由直接访问返回 404 |
| 内容发布 | Pages 未提供 `CONTENT_SNAPSHOT_URL`；缺 snapshot 时 News SSG 静默跳过 |
| 性能 | 只检查三个 JS chunk，没有 Lighthouse/CWV、CSS、字体和图片预算 |
| GEO | 无 `llms.txt`，也没有按训练/检索用途区分的 AI crawler policy |

上述为仓库与本地产物事实；正式域名所有权、线上 HTTP 状态、索引量、Rich Results、CWV 和 AI 引用率仍为 UNKNOWN。

### P0：索引边界与事实可信度

- 新增统一 `seo-route-policy.ts`，明确 index、noindex、dynamic entity 和 private；SSG 为 clean URL 输出 `route/index.html`。合法索引路由必须直接返回 200，未知 URL 使用独立 `404.html` 返回 404 + `noindex,follow`，停止复制首页充当 404。
- 建立单一 `public-url.ts` 管理 site origin/base path，构建时生成绝对 canonical；删除 SSG 脚本中的硬编码域名。任何 release 制品出现 `localhost`、测试域名、重复 canonical，或 canonical 与 sitemap 不同 origin/path 即失败。
- 在全部 SSG 完成后由单一 `generate-seo-artifacts.ts` 生成 robots 和 sitemap。只收录返回 200 的权威页面；Admin、登录、分析 job、站内搜索结果、参数化 JBrowse、pilot/占位页使用 `noindex` 或移除。不要用 robots 隐藏敏感信息，也不要阻断 CSS/JS。
- 先清理未验证 DOI、示例数据和伪功能。为数据集、release、论文和新闻记录负责人、审核日期、来源、许可、版本与稳定标识符。
- release 构建必须提供 release-pinned content snapshot；缺失、release/checksum 不一致或静态实体数与 manifest 不一致时失败。News detail 与后续 Gene detail 生成真正的 release-scoped HTML，取消隐式 200 条截断。
- GitHub project Pages 无法单独控制 origin 根级 `/robots.txt`；生产应使用自定义域名或由 owner Pages 管理根 robots，并在 Search Console 显式提交 sitemap。demo/preview 全部 HTML 使用 `noindex,follow`，不发布 demo sitemap。

### P1：元数据与结构化数据

- 每个可索引模板提供唯一 title、description、canonical、Open Graph、Twitter Card；动态 news/gene/release 页面由可信数据生成并进行长度/转义校验。
- 全局输出 `Organization`、`WebSite`；内容页按类型输出 `BreadcrumbList`、`NewsArticle`/`ScholarlyArticle`；数据页输出 Schema.org/Bioschemas `DataCatalog`、`Dataset` 和 `DataDownload`，包含 identifier、version、dateModified、license、citation、distribution、checksum 与 provenance。
- 只有在中英文拥有独立、可抓取且 canonical 自洽的 URL 时才添加 `hreflang`；纯客户端语言切换不可伪装成多语言 URL。
- 为每个 release 建立稳定引用页，提供推荐 citation、机器可读 citation/RO-Crate、变更记录和下载清单；DOI/DataCite 仅在元数据审核流程成熟后启用。

### P1：GEO 可引用内容

- 以“答案摘要→方法→证据→版本/更新时间→引用/下载”组织核心数据集和帮助页；保持稳定标题、表格字段、术语定义和可直接引用的短段落。
- 可选发布 `llms.txt`，列出权威入口、数据范围、引用方式和许可。它是实验性辅助文件，不替代 sitemap、JSON-LD 或访问控制。
- 明确 AI crawler 策略并经过数据治理批准；按 crawler 身份和用途决定允许/拒绝，保留日志。禁止把私有/Admin/API 写端点暴露给抓取器。
- 建立 20–30 个领域基准问题，记录答案正确率、版本引用、来源链接和错误陈述，按月在主要答案引擎人工抽样；不使用无法复现的“GEO 分数”。

### P2：性能、监测与持续治理

- 接入 Google Search Console、Bing Webmaster、结构化数据校验和日志级 crawler 监测；跟踪有效索引页、soft-404、重复 canonical、抓取失败、富结果错误和自然/AI referral。
- 以 p75 LCP < 2.5s、INP < 200ms、CLS < 0.1、Lighthouse SEO ≥ 95 为初始预算；三方 JBrowse 与 Admin 不拖累 Public Web 首屏。
- 在 CI 验证：所有 sitemap URL 返回 200；无 private/placeholder 路由；canonical 唯一；JSON-LD 可解析且关键字段完整；静态 HTML 在禁用 JS 时仍包含标题、摘要和主体事实。

建议新增 `scripts/check-seo-artifact.ts` 与 `seo-contracts.test.ts`，把 HTTP 200/404、canonical/sitemap 一致性、noindex 边界、JSON-LD 解析、脚本注入逃逸和 `llms.txt` 链接状态固化为构建后门禁。

## 7. 验收门禁

建议形成单一发布命令，依次执行 frozen install、lint/typecheck/unit、三应用 build、静态制品验证、关键 Playwright 和环境集成测试。最低发布条件：

- Admin/Web/JBrowse 最终制品均非空、无框架层和未解释的 page error；
- 关键页面桌面与 375px 无横向溢出，纯键盘可完成主要路径；
- 公开页面的 Error 与 Empty 可区分，危险 mutation 仅在成功基线后启用；
- standard/release SSG 使用受控 fixture 或真实 release，并部署已验证的同一 digest；
- SEO/GEO 检查不含未验证事实、private URL、测试主机或无效结构化数据；
- PostgreSQL/MinIO/Celery/JBrowse 真实集成证据与恢复演练归档。

## 8. 仍为 UNKNOWN

- 23 个 Docker/Testcontainers PostgreSQL 用例；真实 PostgreSQL/ClickHouse/MinIO/Celery 恢复演练；
- production release-data Web build，以及线上 Pages 当前字节与本地已验证制品是否一致；
- 浏览器到 MinIO multipart/checksum、真实登录/RBAC、BLAST/Analysis 完整状态机；
- 线上 JBrowse 数据代理、track 完整性、portal iframe bridge 与非默认 assembly 数据；
- 搜索引擎实际索引状态、历史流量、外部反向链接、AI crawler 日志与生成式答案引用基线；
- Firefox/WebKit、读屏器、200% 缩放和真实移动设备。
