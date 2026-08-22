# SoyMutDB Next 升级执行方案（2026-08 定稿）

> 已审查整合：designer 方案 + oracle 审查 + librarian 功能差距矩阵 + 用户拍板决策。
> 分支 `feature/upgrade-antd-mcp-mcp`，6 个并行执行包。

## 已定决策

1. **全站换 Ant Design 5**（Web+Admin AntD Pro），保留 HarmonyOS Sans SC 字体 + 现有动效 + reduced-motion
2. **PPT 仅取信息架构骨架**（UX 完全重做，PPT 视觉无关——observer 确认 PPT 内嵌图是 LUMATE 广告平台）
3. **MCP Server**：项目自带，Python FastMCP + Streamable HTTP
4. **新闻运营闭环**：后端 schema 扩展 + Admin CRUD/排序/预览 + Web 首页轮播+列表+详情
5. **P0 科研功能并行**：多基因组 BLAST 索引 + easyGWAS + LD/多样性/AlleleFreq 三件套
6. **跳过阶段 0 试点**，直接进阶段 1+2（UI 重做+新闻+搜索数据页），但门禁 G1/G2/G3 首批 PR 必带

## 一、信息架构（基于 PPT 骨架重新设计）

一级导航：**主页 / 搜索 / 工具 / 关于 / 最新动态**

搜索下分 6 子页（独立路由 + Tabs 双导航）：
- 基因 ID 搜索（基因组版本下拉 + 基因 ID 输入 → 结果表：染色体/突变特征/Gbrowse/基因ID/位点，按钮跳 Gbrowse 和基因号搜索）
- 物理位置搜索（染色体:起始-结束 → 结果表同上）
- Gbrowse（跳 JBrowse）
- 引物设计（Primer3 包装，新工具）
- BLAST（blastn/blastp 下拉 + 序列输入 → 结果含 E 值/覆盖度，按钮跳 Gbrowse 和基因搜索）
- 搜索工具（统一搜索页）

首页：hero（标题+一句定位+大搜索框+3 任务入口）+ 轮播照片（3-6 张，autoplay+链接）+ 5 新闻摘要卡（标题+时间+分类，跳 /news/{slug}）+ 统计条

关于：guide + help + 联系我们（合并）

最新动态：Admin 可编辑排序 5 个一级目录 + 新闻列表（分类/搜索/分页）+ 详情页

## 二、Ant Design 迁移策略

### 装包与共存
- AntD v5 ESM 直接 import（无需 babel-plugin-import）
- `@ant-design/pro-components` for Admin（ProTable/ProForm/ProLayout）
- `@ant-design/icons` + `@ant-design/cssinjs`（runtime theme）
- Vite 6（不升 Vite，单独立项）+ `@ant-design/vite-plugin`（按需）

### 样式层级（oracle R1 修正）
```css
/* index.css 顶部（所有 @import 之后） */
@layer antd, theme, design, base, components, utilities;
```
**必须含 `design` 层**（原方案遗漏会导致 widget/header 样式被 antd 压住）

### OKLCH 主题（oracle 修正）
- `colorPrimary` seed 喂 hex `#2f6f4f`（让 tinycolor 生成链不报错）
- Button/Tag/Menu 选中态等"用户可见高频 token"用 `theme.components[*].colorPrimary` 覆盖为 `oklch(0.46 0.13 152)`
- 暗色 ConfigProvider 单独覆盖 oklch
- 验收：ΔE < 1（取色器比对 AntD Button 与 Tailwind bg-primary）

### reduced-motion（oracle R2 修正）
ConfigProvider 检测 `matchMedia('(prefers-reduced-motion: reduce)')` 命中时设 `motion: false` + `motionDurationMid/Slow/Fast = 0`

### 字体
`theme.token.fontFamily = '"HarmonyOS Sans SC", ui-sans-serif, system-ui, sans-serif'`
display/h1/h2 仍用 Tailwind（不引 AntD Typography），或显式映射 `fontSizeHeading1=2.5rem` 等

### i18n locale（oracle 遗漏 #1）
按 i18next `languageChanged` 事件驱动 ConfigProvider `locale` prop（zh_CN/en_US 按需 import，约 8KB，路由级懒加载）

### packages/ui 退役
- **原地冻结**（不删，逐路由迁移时删除引用）
- eslint `no-restricted-imports '@soymutdb/ui'` 在**新文件**生效
- 每周统计剩余 `@soymutdb/ui` import 数（>20 触发告警）

### pro-components × React 19（oracle R5）
- 装包前验证 peer；若不过用 `pnpm overrides` 强注入 React 19，**不降 admin React 版本**（共享包类型冲突更难处理）

## 三、新闻运营闭环

### 后端 schema（oracle 两步迁移修正）
扩展现有 `NewsArticle` 表：
- 新增字段：`category` / `cover_url` / `featured_sort` / `carousel_group` / `carousel_sort` / `status`(draft/published/archived) / `visible_from` / `visible_to` / `slug`
- **迁移 0010**：加 status 列 + 双写（is_published 与 status 并存）
- **迁移 0011**（观察一周后）：切查询到 status，删 is_published
- downgrade 只回退到第一步（避免丢已发布状态）

### 新端点
- `GET /api/v1/news?category=&page=&limit=`（列表，published only）
- `GET /api/v1/news/{slug}`（详情）
- `GET /api/v1/news/featured`（5 条首推 + 轮播组）
- Admin：`POST/PUT/DELETE /api/v1/admin/news`（CRUD + 排序 + 预览 token）

### Admin
Content 模块：起草/预览（HMAC 短时 token，非 JWT，15min `/news/{slug}?preview=<token>&exp=<ts>`）/发布/排序拖拽/轮播图管理

### Web
首页 hero 下方轮播（3-6 张 autoplay+链接）+ 5 新闻摘要卡；/news 列表（分类/搜索/分页）；/news/{slug} 详情
SSG fallback 补 carousel/featured 占位

## 四、MCP Server

### 语言与部署
Python FastMCP + Streamable HTTP，apps/mcp-server 新增，docker-compose 新增服务

### 工具清单
| 工具 | 类型 | 说明 |
|---|---|---|
| gene_by_id | 只读 | 按 gene_id 查基因 |
| variant_by_region | 只读 | 按区间查变异 |
| news_list | 只读 | 新闻列表 |
| stats_summary | 只读 | 首页统计 |
| seqfetch | 只读 | 序列提取 |
| blast_submit | 写 | 异步提交+轮询契约 |
| analyses_query | 写 | 分析任务状态查询 |

### 鉴权与安全（oracle 修正）
- 写工具 bearer token + 60/min 限流
- 读工具 job 绑定 submitter_token 防 IDOR
- manifest 带 `X-MCP-Key`（transport 层可选 API key）
- nginx /mcp/ 反代：**`proxy_buffering off; proxy_cache off; proxy_read_timeout 600s; proxy_http_version 1.1;`**（oracle R3，否则 SSE 被缓冲截断）

## 五、P0 科研功能

### 多基因组 BLAST
- worker 配置 `SOYMUTDB_BLAST_DATABASE_PATHS` JSON 映射
- 前端 BLAST 页加数据库下拉（已有 W2-D 后端）

### easyGWAS
- Celery task 接 EMMAX/GEMMA（复用 Job/Outbox）
- 前端 GWAS 工具页（Manhattan/QQ plotly 图）

### 群体遗传三件套
- LD heatmap / Nucleotide Diversity / AlleleFreq
- 复用 variants 数据 + ClickHouse 聚合

## 六、6 个执行包

| 包 | 范围 | 依赖 |
|---|---|---|
| **B1** | 后端基础：News schema+端点 + MCP server 骨架 | 先行 |
| **B2** | Web AntD 迁移+信息架构+首页+搜索子页+数据页 | G1/G2 门禁 |
| **B3** | Admin AntD Pro 迁移+新闻 CRUD | 依赖 B1 |
| **B4** | MCP Server 工具实现 | 依赖 B1 |
| **B5** | P0 科研后端+前端工具页 | 并行 |
| **B6** | 新闻前端（/news+轮播+摘要卡） | 依赖 B1 |

## 七、三大门禁（首批 PR 必带）

- **G1**：Playwright 截图基线 4 场景（表单/表格/弹窗/暗色）+ `@layer` 顺序验证
- **G2**：体积分块预算（antd≤320KB / pro≤180KB / 主入口≤200KB gzip，依据 2026-08-21 实测与 ADR 0002 调整为 320KB），vite.config manualChunks + CI 脚本
- **G3**：MCP 限流压测（429+异步配额）+ SSE 反代冒烟 + IDOR 拒绝 — ✅ 已实现：`scripts/g3-mcp-stress.sh`（4 项检查，`--dry-run` 支持）+ `apps/mcp-server/src/mcp_server/ratelimit.py` Redis 双后端（`SOYMUTDB_MCP_REDIS_URL`，无 Redis 回退内存）

## 八、执行顺序

第一批（并行）：B1 后端基础 + B5 科研后端 + B2 前端 AntD 基础（装包+主题+门禁+试点页）
第二批：B2 页面迁移 + B6 新闻前端 + B4 MCP 工具
第三批：B3 Admin AntD Pro + B5 前端工具页

每包独立 CI 验证、可回滚。
