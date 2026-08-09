# SoyMutDB Next 升级方案（2026-08）：AntD 迁移 · 信息架构重设计 · 新闻闭环 · MCP Server

范围：apps/web + apps/admin + apps/api（schema）+ 新增 apps/mcp-server。本文档只做方案，不改代码。
现状校准（与任务描述的差异，以仓库为准）：Vite 实际为 ^6.0.0 而非 7；web 路由为手动 TanStack Router（无文件路由插件）；SSG（scripts/ssg-build.ts）产出 widget 化静态壳 HTML，不是 React SSR；`NewsArticle` 模型与 /news 前端路由已存在但功能单薄；Primer3 引物设计完全未实现；HarmonyOS Sans SC 自托管于 public/fonts/harmonyos。
与 `docs/design/ui-simplify-2026-08.md` 的关系：该文是 shadcn/Tailwind 时代的简化方案，其"单一焦点、克制色彩"结论继续有效，但组件实现层整体转向 AntD，本文为其后续。

## 1. 调研对标（iSoybean / SoyBase / SoyOmics）

| 能力域 | 已有 | 已实现但可增强 | 未实现 |
|---|---|---|---|
| 基因组浏览 | JBrowse2 桥接（/browser，独立 jbrowse 应用） | 与搜索结果深链互跳（PPT 要求的"跳 Gbrowse"回环）、track 管理后台已有但门户侧 track 切换 UX 弱 | CMap 式比较图（SoyBase） |
| 搜索 | 基因 ID/关键字（/genes、suggest）、变异列表/区域查询 | 物理位置搜索缺独立表单入口（PPT Slide4）；多基因组版本切换下拉（PPT Slide2） | SoyBase Allele Search 等位基因级检索、DivBrowse 多样性浏览 |
| BLAST | blastn/blastp 提交+任务轮询+结果页（Job 状态机、独立 worker） | 结果页补 E 值/覆盖度列与"跳 Gbrowse/基因搜索"按钮（PPT Slide7） | SoyBase 的 blast 结果直接映射到 GlycineMine |
| 工具 | SeqFetch、GO/KEGG 富集、ExpPattern、fastp/scanpy 分析 | 工具发现性差（无统一目录页语义），需按 PPT"工具"一级重排 | Primer3 引物设计（PPT 明确列出）、easyGWAS（SoyOmics）、HapSnap/VersionMap |
| 数据下载 | downloads + MinIO 签名 URL、SRA 页 | 数据集页模板统一 | SoyOmics 7 snRNA + stereo-seq 级多组学数据集 |
| 种子/材料 | seed-request 表单 + admin Seeds 模块 | 与基因详情页联动（从突变体一键申请） | iSoybean 的库存实时状态 |
| 运营内容 | news/publications/guide/help 静态页 + admin Content | 新闻无状态机/排序/轮播（本方案 §4 解决） | 完整运营闭环 |
| 开放接口 | REST /api/v1 全量 | — | MCP Server（本方案 §5，三对标站均无，是差异化机会） |

结论：核心科研能力（浏览/搜索/BLAST/分析）已齐，短板在"搜索入口组织、结果互跳、运营内容、开放接口"，与本方案四个主题完全对应；不追求 CMap/easyGWAS 等重型未实现项，列入备选观察。

## 2. Ant Design 迁移策略

### 2.1 装包与引入方式
- 推荐：`pnpm --filter @soymutdb/web --filter @soymutdb/admin add antd @ant-design/icons`，直接 ESM 具名 import。antd v5 原生支持 tree-shaking，不需要 babel-plugin-import（那是 v4 方案，勿引入）。
- admin 另加 `@ant-design/pro-components`（ProLayout/ProTable/ProForm/ProDescriptions）。
- 备选：unplugin-antd 做按需样式合并——v5 cssinjs 运行时生成样式，无独立样式文件可合并，收益为零，不采用。
- dayjs 随 antd 进入；与现有日期处理无冲突。vite manualChunks 增加 `if (id.includes("antd") || id.includes("@ant-design") || id.includes("rc-")) return "antd"`，防止主 chunk 膨胀。

### 2.2 AntD 主题与 OKLCH / HarmonyOS Sans 共存
- 在 web/admin 各建 `src/theme/antd-theme.ts`，ConfigProvider token 映射：`fontFamily: '"HarmonyOS Sans SC", ui-sans-serif, system-ui, sans-serif'`（与 index.css `--font-sans` 同源）；`borderRadius: 10`（对齐 --radius-md 0.625rem）；motion 时长对齐现有 --anim-duration 300ms。
- colorPrimary 推荐填现有科学绿的 hex 等价值（如 #2f7d4f，落地时从 index.css OKLCH 值转换取色），不直接喂 oklch() 字符串：antd 用 @ctrl/tinycolor 从 colorPrimary 派生 1-10 色阶，oklch 输入会导致调色板生成失败。OKLCH token 继续留给 Tailwind 层，两套色值以"同一绿、两种表达"对齐，设计验收时用取色器比对。
- 暗色：沿用现有 `.dark` class 策略；ConfigProvider `theme.algorithm` 在 dark 时切 `theme.darkAlgorithm`，由现有 pre-paint 主题脚本驱动，避免闪烁。antd locale 按 i18n 语言切 `zh_CN`/`en_US`。
- 删除/停止扩展 packages/ui styles.css 里的 shadcn 色板对外语义，但迁移期保留（见 2.5）。

### 2.3 与 Tailwind 4 的共存约定（关键）
- 冲突本质：Tailwind v4 把样式放进 `@layer`，而 antd cssinjs 默认注入无层样式，CSS 规则"无层优先于有层"，antd 会压过 Tailwind 工具类。
- 推荐方案：ConfigProvider `theme={{ layer: true }}`，antd 样式进入名为 `antd` 的层；在 index.css 顶部声明 `@layer antd, theme, base, components, utilities;`，保证 Tailwind utilities 层优先级最高，局部微调仍可用工具类覆盖 antd。
- preflight：保留 Tailwind preflight 但置于 antd 层之后声明顺序靠前的 base 层；若试点页发现 antd 组件被 preflight 误伤（button/input 重置），备选是 v4 细粒度导入（只引 theme/components/utilities，跳过 preflight，由 antd 承担 reset）。试点页验收后再定，不提前改。
- 分工约定：布局、间距、自定义区块（hero、统计条、footer）继续用 Tailwind；表单、表格、弹窗、导航、反馈类组件一律 antd。禁止同一组件内混用两套组件库。

### 2.4 动效层保留
packages/motion 不动：Lenis 平滑滚动、GSAP/ScrollTrigger 入场、View Transition、`prefers-reduced-motion` 降级（index.css 742 行已有）全部保留。约定：antd 组件自带动效不再叠加自定义动画；自定义动效只作用于 Tailwind 区块层。Carousel 轮播若 antd Carousel（react-slick）与 Lenis 滚动手势冲突，备选自研 60 行 CSS scroll-snap 轮播。

### 2.5 packages/ui 退役（推荐：原地冻结，不建 ui-next）
1. 即刻冻结：新增页面禁止 import `@soymutdb/ui`，eslint `no-restricted-imports` 拦截。
2. 迁移期保留源码与 46 个测试作参考（DataTable 列模型、FilterBar 交互、状态组件文案是 ProTable 封装的需求输入）。
3. 每迁完一个路由即删该路由对 ui 的引用；全部迁完后删包、删 index.css 的 `@import "@soymutdb/ui/styles.css"` 与 @theme 再导出。
4. 备选"新建 packages/ui-next 双轨"被否：两套共享库 + 两套测试会显著拉长双系统并存期，收益为零。

### 2.6 web vs admin 差异
web = AntD 基础组件 + Tailwind 区块 + motion 动效，走品牌化视觉；admin = ProLayout（侧栏+面包屑）+ ProTable/ProForm，走 AntD Pro 标准信息密度，不做品牌动效（保留 reduced-motion），桌面 Tauri 构建不受影响。

## 3. 信息架构与 UI 设计（PPT 为骨架，视觉重设计）

### 3.1 一级导航最终结构
| 最终项 | 来源取舍 | 说明 |
|---|---|---|
| 主页 | PPT | / |
| 搜索 | PPT 二级结构升为一级 | /search 下 6 个子页，见 3.3 |
| 基因组浏览器 | 保留现有 /browser | PPT 把 Gbrowse 放搜索下，但它是独立应用级体验，升为一级更合理 |
| 工具 | PPT + 现有 Tools | 见 3.4 |
| 数据 | 保留现有 Data 分组 | downloads/sra/analytics 收拢于此 |
| 最新动态 | PPT | /news，见 §4 |
| 关于 | 合并现有 guide/help + PPT"联系我们" | /about 下子页：指南、帮助、联系我们 |

现有 Explore/Resources 命名废弃（与 PPT 一级冲突且语义含糊）；publications 归入"关于"或"数据"二级（落地时二选一，推荐"关于"）。

### 3.2 首页布局（自上而下）
1. Hero：保留现有"一句话定位 + 大搜索框 + 示例 chips"极简结构（ui-simplify 方案成果），AntD Input.Search 替换自绘输入框，搜索框成为 hero 唯一焦点。
2. 三任务入口：浏览器 / BLAST / 基因搜索，AntD Card 扁平样式，hover 仅边框变色（延续现有克制原则）。
3. 照片轮播：3-6 张运营图，antd Carousel，autoplay 5s + 手动箭头/圆点，每张可配外链；reduced-motion 下关闭 autoplay；图片由 Admin 轮播管理维护。
4. 最新动态摘要：5 条（标题+日期+分类 Tag），点击进 /news/{slug}；数据来自 featured 接口。
5. 统计条：保留现有单行弱化样式。
动效：仅 hero 入场渐显（motion 包现有能力）+ 区块滚动揭示，不加视差/3D。布局采用非对称 7:5 分栏承载"新闻+轮播"并排（桌面），移动端纵向堆叠。

### 3.3 搜索二级结构（推荐：独立路由 + 页内 Tabs 双导航）
/search 页顶部 antd Tabs 切换子搜索，每个子页同时有独立 URL（可分享、可被结果页按钮深链），Tabs 与路由双向同步。
| 子页 | 路由 | 布局要点 |
|---|---|---|
| 基因 ID | /search/gene | 基因组版本 Select（assemblies 接口）+ 基因 ID 输入；结果 ProTable：染色体/突变特征 Tag/位点/基因 ID，操作列两个按钮：跳 /browser 定位、跳基因详情 |
| 物理位置 | /search/region | 输入格式 `染色体:起始-终止`（Input + 格式校验 + 示例占位）；结果表同上 |
| BLAST | /search/blast | 与 /blast 同页（路由别名）：类型 Radio(blastn/blastp) + 序列 TextArea + 数据库 Select |
| BLAST 结果 | /blast/jobs/:id | 现有结果页增强：E 值/覆盖度列、行操作跳浏览器/基因搜索 |
| 引物设计 | /search/primer | 新功能：基因 ID 或序列输入 → 调 Primer3 服务（后端新增，备选先外链第三方） |
| 高级检索 | /search/advanced | 现有 genes/variants 过滤能力的统一入口（收编 FilterBar 逻辑） |
PPT 的"Gbrowse"项不作为搜索子页，由一级导航"基因组浏览器"承担，搜索页内放跳转链接。

### 3.4 工具集组织
/tools 改为目录页：卡片式工具索引（SeqFetch / GO-KEGG 富集 / ExpPattern / 引物设计 / 分析流程 fastp·scanpy），每卡含一句话描述+入口；子路由保持 /tools/seqfetch 等不变。分析类（有任务状态）归入"分析"子分组，与即时工具视觉区分。现有 /tools/api 页（API 文档）移入页脚与"关于"。

### 3.5 联系我们
/about/contact：AntD Form（姓名/邮箱/主题/正文，zod 校验保留），提交走现有 API（无则新增 POST /api/v1/contact，备选 mailto 降级）；文案进 packages/i18n en/zh 双语；附实验室地址/邮箱静态块。

### 3.6 最新动态页
/news：左侧分类菜单（5 个可编辑分类，Admin 维护排序）+ 右侧列表（AntD List，分页 10/页，关键字搜索）；/news/{slug} 详情页（正文富文本渲染沿用 dompurify 管线）。分类体系：数据发布 / 数据库更新 / 研究进展 / 社区活动 / 公告（Admin 可改名）。

### 3.7 暗色 / 移动端 / 无障碍
暗色：darkAlgorithm + 现有 .dark 双轨同步，轮播图加暗色蒙层保证文字对比；移动端：导航收为 antd Drawer 汉堡菜单，表格在 <768px 切 List 卡片视图（沿用 responsive-data-view 的断点策略）；无障碍：焦点环统一用 antd 默认 + Tailwind focus-visible，轮播/自动内容遵循 reduced-motion，全部交互元素有 aria-label（i18n 提供）。

### 3.8 数据页统一模板
genes/variants/gene-detail/blast-results 统一为：ProTable（列设置/密度切换/受控分页，替换 packages/ui DataTable）+ ProDescriptions（详情页）+ 统一 Empty/Error/Loading 态封装（放 apps/web/src/components/data/，需求来自 packages/ui 现有状态组件测试）。每页遵守同一骨架：PageHeader（标题+描述+操作）→ FilterBar（ProForm inline）→ ProTable。

## 4. 新闻运营闭环（端到端）

### 4.1 后端 schema（NewsArticle 扩展，Alembic 单次迁移）
| 新增字段 | 类型 | 说明 |
|---|---|---|
| summary_en / summary_zh | varchar(512) | 列表摘要 |
| cover_image | varchar(1024) nullable | 封面（MinIO URL） |
| external_url | varchar(1024) nullable | 外链型新闻（有则卡片跳外链） |
| status | varchar(16) default 'draft' | draft/published/archived，替代 is_published（保留 is_published 为生成列兼容旧查询，过渡后删） |
| visible_from / visible_to | timestamptz nullable | 定时上下架 |
| featured_sort | int nullable | 首页 5 条首推序（null=不上首推） |
| carousel_group | varchar(32) nullable + carousel_sort | int nullable | 轮播图分组（'home'）与顺序 |
分类 category 从自由字符串收敛为枚举表或受控字典（Admin Settings 维护，5 个、可排序改名）。备选：轮播独立建表 CarouselSlide——被否，字段方案运营改一篇新闻即改轮播，操作路径最短。

### 4.2 Admin Content 模块（AntD Pro）
- 新闻列表 ProTable：状态筛选/关键字/分类过滤，行操作 编辑/预览/发布/归档/删除。
- 编辑 DrawerForm：双语字段（en/zh 并排或 Tab 切换）、封面上传（MinIO 直传沿用）、定时发布、分类 Select。
- 首推排序：独立"首页推荐"面板，5 条内 dnd-kit 拖拽（admin 已有依赖）写 featured_sort。
- 轮播管理：同一列表的"轮播"Tab，管理 carousel_group/sort 与图片，预览即首页同款 Carousel。
- 预览：草稿态生成带签名 preview token 的 /news/{slug}?preview=… 链接，Web 端校验 token 后渲染（未发布内容不泄漏）。
- 状态机：draft → published（可设 visible_from 未来时间=定时）→ archived；published 可回 draft（下架）。操作全部进 Audit 日志（现有 audit 模块）。

### 4.3 Web 端
首页轮播（carousel_group='home'，3-6 张，取 carousel_sort 序）+ 首页 5 条摘要（featured_sort 序，fallback 最新 published）；/news 列表（分类过滤+搜索+分页，仅 status=published 且在可见窗口内）；/news/{slug} 详情。全部走 React Query 缓存，列表页 SSG 壳可静态化（fallback 数据机制沿用）。

### 4.4 API 契约
| 端点 | 说明 |
|---|---|
| GET /api/v1/news?page&size&category&q | 分页列表 → {items,total} |
| GET /api/v1/news/{slug} | 详情（preview token 查询参数可选） |
| GET /api/v1/news/featured?limit=5 | 首页摘要 |
| GET /api/v1/news/carousel?group=home | 轮播 |
| POST/PUT/DELETE /api/v1/admin/content/news[/{id}] | CRUD（现有 admin_content 路由风格扩展） |
| POST /api/v1/admin/content/news/{id}/publish · /archive | 状态流转 |
| PUT /api/v1/admin/content/news/featured-sort · /carousel-sort | 批量排序 |

### 4.5 与现有富页面的取舍
analytics/compare/sra 等重型页面保留但从一级视野降级：收进"数据"二级，首页不再出现图表区（ui-simplify 已删，维持）。新闻承担"首页活性"，数据页承担"深度"，互不抢位。

## 5. MCP Server 设计

### 5.1 技术选型
推荐：Python 官方 SDK（`mcp` 包的 FastMCP），新建 apps/mcp-server。理由：后端已是 FastAPI Python，可直接复用 apps/api 的 schemas/服务层（或经内网 HTTP 调 api 服务），类型与字段单源；团队已具备 Python 工具链。备选：TS @modelcontextprotocol/sdk——仅当需要与前端同仓共享 TS 类型时才有优势，但它要求 MCP 以 HTTP 客户端方式重复调用 REST，多一层无收益，不采用。
实现模式推荐"HTTP 代理型"：MCP server 作为独立进程调用 http://api:8000/api/v1/*，与 REST 行为 1:1 对齐、可独立重启；备选"in-process 直连 DB"性能更好但耦合部署，否。

### 5.2 工具清单（对齐现有 API）
| 工具 | 对应端点 | 鉴权 |
|---|---|---|
| assemblies_list | GET /genes/assemblies | 免 |
| gene_by_id / gene_search | GET /genes/{id} · /genes?keyword | 免 |
| variant_by_region / variant_by_id | GET /variants/region · /{id} | 免 |
| blast_submit | POST /blast → 返回 job_id | token |
| blast_job_status / blast_results | GET /blast/jobs/{id}[·/results]，hits 截断 20 条 | 免（job_id 即凭据） |
| seqfetch | POST /tools/seqfetch | token |
| news_list / stats_summary | GET /news · /stats/dashboard | 免 |
异步约定：blast_submit 立即返回 job_id + 轮询指引文本，LLM 客户端用 blast_job_status 轮询；结果分页游标化，避免超长上下文。enrichment/exppattern 二期再加。

### 5.3 健康检查与限流
GET /mcp/health（透传 api health）；只读工具免鉴权但限流（按 IP 60 req/min），写工具需 `Authorization: Bearer <admin token>`（复用现有 admin token 体系）；进程内信号量限并发 8；blast_submit 每 token 每小时 ≤10 次，防 LLM 客户端刷任务。

### 5.4 部署
docker-compose 新增 `mcp` 服务（python slim 镜像），nginx 增加 `/mcp/` location 反代（Streamable HTTP transport），与现有单证书共存，gh-pages 部署完全不受影响。备选子域名 mcp.* 需要新证书与 DNS，否。

### 5.5 文档与发现
FastMCP 自动生成工具 schema；另暴露 GET /mcp/manifest.json（服务名/版本/工具摘要/示例客户端配置片段，含 Claude Desktop 与 OpenCode 两段示例），版本号随 monorepo 2.x 走，工具增删在 CHANGELOG 记录。README 增"MCP 接入"章节。

## 6. 风险点与分期路线图（8-12 周）

| 阶段 | 周 | 内容 | 验收（DoD） | 回滚 |
|---|---|---|---|---|
| 0 基线 | 1 | antd 装包+layer 主题+试点页（/help） | CI 全绿、构建产物体积报告、试点页双主题走查 | revert 分支 |
| 1 IA+首页+搜索+新闻前端 | 2-4 | 导航重构、首页、/search 六子页、/news | 设计走查+移动端+reduced-motion 检查单 | 分支隔离，旧导航 feature flag 切回 |
| 2 数据页 | 5-6 | genes/variants/gene-detail/blast 迁 ProTable 模板 | 与旧页数据一致性对比脚本 | 路由级双版本切换 |
| 3 admin | 6-8 | ProLayout + 新闻运营闭环（含后端 schema 迁移，第 2 周即启动后端，避免阻塞） | 运营演练：起草→预览→发布→排序→轮播全流程 | Alembic downgrade |
| 4 MCP | 8-10 | apps/mcp-server + compose + manifest | MCP Inspector 全工具冒烟 + 限流压测 | compose 摘除服务即回滚 |
| 5 收尾 | 10-12 | 删 packages/ui、清 Tailwind 冗余 token、文档 | ui 包删除后 CI 全绿 | git revert |

显列风险：① antd cssinjs 与 Tailwind 层级冲突（layer:true 方案试点验证，2.3）；② Vite 兼容——保持 Vite 6 不动，Vite 7 升级单独立项（plugin-react 需同步升，勿与迁移混做）；③ @ant-design/pro-components 对 React 19 的 peer 支持需装包前验证，不行则 pnpm overrides 或 admin 暂缓 React 版本；④ 双系统并存期拉长（冻结令+逐路由删除对抗）；⑤ 构建产物膨胀（manualChunks+体积报告门禁）；⑥ 新闻后端迁移阻塞前端（第 2 周提前启动）；⑦ SSG 壳与 antd 无交集，但若未来 SSG 渲染 React 组件需引入 @ant-design/cssinjs extractStaticStyle，现段不投入。

## 7. 自审（三个最可能出问题的点）

1. 样式优先级与主题闪烁是集成中最脆的一环。layer:true 方案在"Tailwind preflight × antd reset × 暗色算法"三方叠加下仍可能出现个别组件 mis-style，且暗色切换时 antd cssinjs 重新注入会有可感知延迟。对策：试点页（阶段 0）必须覆盖表单/表格/弹窗/暗色四场景并留截图基线，问题在阶段 0 暴露而不是阶段 2。
2. 范围过宽、并行过多。8-12 周内同时推进导航重构、6 个搜索子页、新闻全闭环（含后端迁移）、admin 换骨架、MCP 新服务，任何一项延误都会让"双设计系统并存"拖过临界点，士气与一致性双输。对策：阶段 3 的 admin 与阶段 4 的 MCP 允许顺延出 12 周（新闻闭环与数据页是不可让渡的核心，MCP 是可裁剪的增量），且后端 schema 必须第 2 周落地。
3. MCP 的异步任务语义对 LLM 客户端不友好。BLAST 任务分钟级，LLM 客户端可能反复轮询直到超时，或被子进程无限等待；blast_submit 若无强限流会被自动化客户端刷穿 worker 队列。对策：job 返回中带明确的"建议轮询间隔与最大等待"文本、结果工具支持 since/cursor、token 级硬配额，并在 manifest 中明示异步契约；上线前用 MCP Inspector + 脚本化压测双验证。

（完）
