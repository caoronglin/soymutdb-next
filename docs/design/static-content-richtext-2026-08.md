# 静态内容页 + 富文本编辑器方案 v2（2026-08）

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 状态：**已修订**（吸收 oracle 审查意见 R1-R7；待用户确认后执行）
> v1 → v2 变更：非 hydration 模式明确化、快照契约冻结、API 写入侧清洗、SSG 所有权与构建顺序修正、guide/help 剥离、marked 版本策略、SW 策略修正、CF _redirects 处理

---

## 1. 目标

1. **内容页静态化**：新闻（列表/详情）、关于我们（新增 /about）在**构建期生成真实 HTML**（gh-pages 直接服务，SEO + 无 JS 可用 + 首屏性能），运行时 CSR 接管并预填当前页数据（防闪烁）。
2. **富文本发布**：Admin 新闻/关于我们编辑升级为 **TipTap v3** 富文本编辑器，支持 markdown（导入/导出/显式应用）、**docx 导入**（mammoth）、图片上传（D4 组件 + 服务端校验）。

## 2. 现状关键事实（已侦查 + oracle 复核）

| 项 | 事实 |
|---|---|
| 渲染模式 | `main.tsx` 用 `createRoot().render()`（**CSR，非 hydrateRoot**）；SSG 页是手工 HTML 壳，与 React 无 DOM 对应——**不存在 hydration** |
| 部署路径 | gh-pages 子路径 `soymutdb-next/`；`base-template.ts` 现生成**根绝对路径** `/assets/*`（既有问题 R1，本方案沿用现有 SSG 路径策略保持一致，**base 修正单独立项**） |
| 内容存储 | `news_articles.content_en/zh`（Text，textarea 编辑，门户 DOMPurify 渲染）；`static_pages` 表（guide 走 markdown 自定义渲染 `guide.tsx:63-352`；**help 是硬编码 FAQ 不读表**）；`system_settings` 存 `about.*`（D4 已加 `GET /site/about`） |
| 写入侧 | `admin_news.py`/`admin_content.py`/`admin_settings.py` **原样入库无清洗**（oracle 🔴） |
| SSG | `ssg-build.ts` 已生成固定页（**含 about/guide/help legacy fallback**）；构建链 `vite build → ssg-build → generate-samples → gzip → gen-sw`；`generate-samples` 会重写 sitemap |
| SW | `sw.js` 对 `data/*` 走 stale-while-revalidate（**与快照过期语义冲突，需改 network-first**） |
| CI | `pages.yml` 仅 main push/dispatch 发布，**无 CONTENT_SNAPSHOT_URL**；Admin 保存内容不触发重建 |
| 依赖 | web：`marked@^18.0.9`、`mammoth`、`DOMPurify`；**admin 未声明 marked/mammoth**；`@tiptap/markdown` 需 `marked@^17`——**dedupe 前提不成立** |

## 3. 富文本编辑器（TipTap v3，oracle 有条件通过）

### 3.1 选型
AntD 5 无官方富文本（仅 Input.TextArea；pro-components 无）。**TipTap v3**（3.29.x，React 19 显式 peer `^17||^18||^19`，MIT，活跃）；备选 Lexical（自建 toolbar 成本高）。

### 3.2 集成约束（吸收审查）
1. **依赖**：admin 显式声明 `@tiptap/*`（同版本精确锁定，不用分散 caret）+ `mammoth` + `marked@^17`（TipTap 用）；**web 保持 marked@^18 不动**（并存，不做全局 override，不伪造 dedupe）
2. **组件契约**：`RichEditor` 对 ProForm 只暴露 `value: string`（HTML）+ `onChange(html: string)`；**父层不回写**（避免光标跳动/undo 丢失）；markdown 仅内部临时状态
3. **Markdown 为导入/导出/显式应用**：编辑区 Tabs「富文本 | Markdown」切换时明确提示"将用 Markdown 覆盖现有富文本结构"；不承诺 HTML↔MD 无损双向
4. **粘贴 markdown**：不做 transformPasted 异步弹窗；提供工具栏"粘贴为 Markdown"按钮（读取剪贴板 → marked → 显式 setContent）
5. 去掉 FloatingMenu（无明确价值）；保留 Toolbar + BubbleMenu
6. `immediatelyRender: false` + onCreate/onUpdate 幂等（React 19 StrictMode 规避）
7. **图片上传**：复用 D4 file-upload + 服务端校验（见 §4.3）

### 3.3 组件文件
`apps/admin/src/components/rich-editor/`：`RichEditor.tsx`（lazy+Suspense）、`tiptap-editor.tsx`（useEditor + extensions）、`toolbar.tsx`（AntD Button/Tooltip/Divider + BubbleMenu）、`docx-import.ts`（mammoth→DOMPurify→setContent）、`markdown-mode.tsx`（源码 textarea + marked 预览）、`rich-editor.css`（`.rl-editor-content` 用 `var(--ant-color-*)` + HarmonyOS + OKLCH）

## 4. 快照 + SSG（oracle：需重写契约与生命周期）

### 4.1 快照契约（冻结）
`GET /content/snapshot`（公开）：
```jsonc
{
  "schema_version": 1,
  "generated_at": "ISO8601",
  "news": {
    "source_total": 128,            // 数据库公开可见总数
    "included_total": 128,          // 快照实际包含数（≤500）
    "truncated": false,             // 超限标记
    "items": [ /* 公开可见 NewsSummary，含 updated_at，发布时间降序 */ ]
  },
  "news_detail": { "<slug>": { /* 公开可见详情 HTML */ } },
  "about": { title_en, title_zh, summary_en, summary_zh, content_en, content_zh }
}
```
- **可见性规则与公开端点完全一致**（status=published + is_published + 可见窗口内，复用 news_service 查询逻辑）
- **截断语义**：`source_total > 500` 时 `included_total=500`、`truncated=true`，静态列表只渲染快照内条目并显示"更多内容在线获取"；历史详情回退 API
- **可见窗口文章（visible_from/to）**：快照**包含**（窗口内才可见）；但**不为其生成静态详情**（避免撤稿后文件残留公开）——`news_detail` 对窗口文章置 null，详情页运行时走 API
- 端点：短 TTL 缓存（Redis 60s，复用 cache.py）+ `ETag/If-None-Match` + gzip

### 4.2 构建期（oracle 🔴 修正）
- `apps/web/scripts/fetch-content-snapshot.ts`：`CONTENT_SNAPSHOT_URL`（CI/生产必配）→ `dist/data/content.json`；本地无 URL → 从 `apps/web/content-snapshot/`（可选仓库快照）→ 仍无 → **跳过内容页生成并告警（仅本地）**；**生产构建 fail-fast**（CI 未配 URL 或拉取失败 → 构建失败）
- `apps/web/scripts/ssg-content.ts`（**在 gzip 之前、generate-samples 之后**执行，且重写 sitemap 的逻辑需在内容页生成后重跑——构建链调整：`vite build → ssg-build → generate-samples → **ssg-content** → gzip → gen-sw`，sitemap 由 ssg-content 追加新闻 URL）
- 生成范围（第一阶段）：
  - `/news/index.html`：首屏列表（快照内全部条目渲染 + "更多在线获取"当 truncated）
  - `/news/{slug}.html`：**仅快照窗口内文章**（≤200 条，避免构建体积爆炸）；每页内嵌 bootstrap JSON（`<script type="application/json" id="rl-bootstrap">`：当前页数据 + generated_at）
  - `/about.html`：about 内容（新增 /about 路由 + SSG 双轨）
  - **guide/help 本阶段不生成**（现状是 markdown 渲染/硬编码，剥离为后续 E5）
- 每页：`<title>`/meta description/OG（纯文本截断）+ JSON-LD（script-safe 序列化）+ 正文 HTML（构建端 bleach 清洗，双保险）
- **SSG 所有权**：`ssg-build.ts` 的 about/guide/help 条目**保持原样**（legacy fallback）；`ssg-content.ts` 输出到**同路径覆盖**（有快照时覆盖为内容版，无快照时保留 legacy——唯一真相由"有无快照"决定，写入注释）

### 4.3 服务端清洗（oracle 🔴）
- 新增 `apps/api/app/core/sanitize.py`：bleach（API 已有依赖）allowlist 清洗——标签白名单（p/br/strong/em/u/s/h1-6/ul/ol/li/a/img/table/thead/tbody/tr/th/td/pre/code/blockquote/hr）+ 属性白名单（href/src/alt/title/target/colspan/rowspan/style 禁）+ URL 协议（http/https/data:image）+ `target="_blank"` 强制 `rel="noopener noreferrer"`
- 写入边界接入：`admin_news.py`（create/update）、`admin_content.py`（static page）、`admin_settings.py`（about.* 的 content 键）
- 图片上传服务端校验（`admin_uploads.py`）：purpose 白名单 + 扩展名/MIME 白名单（jpg/png/webp/gif/svg 禁）+ ≤10MB + content-type 嗅探
- 三端一致策略（服务端 bleach + 门户 DOMPurify + SSG bleach）

### 4.4 内容生命周期（oracle 🔴）
- **事实**：Admin 保存不触发 gh-pages 重建；`visible_to` 过期文章静态详情会残留
- **本阶段措施**：①窗口文章不生成静态详情（§4.1）；②CI 每次 main push 重建（现状）；③文档定义发布 SLA：内容发布后需重新部署（或配置后续 webhook/定时任务——列为 E6 backlog）
- SW：`data/content.json` 改 **network-first**（`sw.js` fetch 策略修订，激活时清理旧快照缓存）

### 4.5 Cloudflare _redirects（oracle 🔴）
- `_redirects` 的 `/* /index.html 200` 与真实文件优先级在 CF **不可靠**：移除 catch-all 行（依赖 CF 默认 SPA fallback）或保留并加注释"SSG 文件需 Preview 回归验证"——**执行时先移除**，gh-pages 不受影响

## 5. 前端 CSR 接管（oracle：非 hydration，明确模式）

- **模式**：静态 HTML 服务无 JS/爬虫首屏 → React CSR 启动 → 读取页面内嵌 `#rl-bootstrap` JSON（当前页数据）预填 TanStack Query cache（`queryClient.setQueryData` + `initialDataUpdatedAt = generated_at`）→ 渲染替换静态壳（root 清空重挂，页面自身负责先渲染 bootstrap 数据再 API 刷新）
- **QueryKey 对齐**（oracle 🟡）：列表 `["news-list", category, page]`、详情 `["news-detail", slug, preview, exp]`——bootstrap 只预填**无 preview/exp 的公开详情**和列表首屏；preview 永远走 API
- **URL 语义**：新闻列表 `category/page` 移入 TanStack Router search 参数（静态页链接与 SPA 同语义；SPA 接管后 URL 一致）
- 静态壳隐藏时机：React 根渲染完成后（首帧数据就绪）移除静态正文容器，防重复
- 无快照时（本地/跳过构建）：行为与现状完全一致（纯 API）

## 6. Admin 编辑增强（Part C）

- `news-form.tsx`：ProFormTextArea → `RichEditor`（value/onChange HTML）+ docx 导入按钮 + markdown 模式 Tabs + 图片上传（file-upload 组件）
- `settings.tsx` About 区：content 字段 → RichEditor
- `news/$id.tsx` 回填：HTML 直接注入（TipTap 解析）
- `news-preview-modal` 不变（门户渲染已兼容）

## 7. 执行分包（v2 调整）

| 包 | 内容 | 依赖 |
|---|---|---|
| **E1 编辑器** | admin 依赖声明（tiptap 精确版 + mammoth + marked@17）+ RichEditor 组件（lazy/toolbar/docx/markdown 显式应用）+ news-form/settings 接入 + i18n | 独立 |
| **E2 快照+SSG** | `/content/snapshot` 端点（缓存/ETag/bleach 清洗）+ 服务端清洗（sanitize.py + 写入边界 + 上传校验）+ fetch/ssg-content 脚本 + 构建链调整（gzip/sitemap 顺序）+ SW network-first + CI fail-fast 配置 + 移除 CF catch-all | 独立 |
| **E3 前端接管** | bootstrap JSON 预填 + news 列表/详情改造（search 参数化、queryKey 对齐、窗口文章 API 回退）+ /about 路由（header/footer/i18n/routeTree 脚本注册）+ 快照无时回退 | E2 契约冻结后 |
| **E5（后续）** | guide/help 迁移（markdown→HTML 统一） | 后续 |
| **E6（后续）** | 内容发布触发重建（webhook/定时）+ base 路径修正（gh-pages 子路径资源路径） | 后续 |

**执行顺序**：E1 ∥ E2 并行 → E3（E2 后）→ 综合验证提交。

## 8. 验证与验收

1. **E1**：admin build + typecheck 0 错误；TipTap 不在主 chunk（grep=0）；富文本（表格/图片/代码块）发布 → 门户 DOMPurify 渲染正确；docx 导入端到端（mammoth mock）
2. **E2**：快照端点测试（可见性规则/截断/ETag/清洗）；`GET /content/snapshot` 聚合正确；有快照构建：`dist/news/index.html` + 窗口内 `{slug}.html` + `dist/about.html` 生成且含内容；**无快照本地构建不失败**；服务端清洗测试（script/style/事件属性剥除）
3. **E3**：build + typecheck 0 错误；G2 PASS；SSG 页 curl grep 关键内容；bootstrap 预填生效（无 API 时页面显示快照数据）；列表 search 参数化后导航/分页正常
4. **回归**：API 全量非容器测试无新增失败；worker 无回归；新闻 CRUD 闭环测试

## 9. 风险与决策记录

| 决策点 | 结论 |
|---|---|
| marked 版本 | web 18 / admin+TipTap 17 并存（不做全局 override） |
| guide/help | 剥离本阶段（E5 后续迁移） |
| 可见窗口文章 | 不生成静态详情（防残留），运行时 API |
| base 路径既有问题 | 不在本批（E6），新 SSG 沿用现有路径策略 |
| CF catch-all | 本批移除 |
| 快照截断 | ≤500，truncated 标记，静态列表显示"更多在线获取" |
| 生产 CI | 需配 CONTENT_SNAPSHOT_URL，fail-fast |

**风险**：TipTap React 19 open issue（StrictMode/NodeView）——immediatelyRender:false + 不引入 NodeView 扩展；SSG 内容过期——bootstrap 仅首屏 + 30s staleTime 自动刷新 + 发布 SLA 文档化；快照体积——≤500 条窗口详情 + gzip。

---

*v1 → v2 修订对照：R1 非 hydration 模式化（§5）/ R2 快照契约冻结+截断语义（§4.1）/ R3 生命周期与 CI（§4.4）/ R4 写入侧清洗（§4.3）/ R5 SSG 所有权与构建顺序（§4.2）/ R6 marked 版本并存（§3.2）/ R7 CF _redirects（§4.5）；guide/help 剥离（E5）；SW network-first（§4.4）；上传服务端校验（§4.3）。*

---

## 10. 执行记录（E1/E2/E3 已完成，2026-08-09）

| 包 | 状态 | 关键交付 |
|---|---|---|
| E1 | ✅ | admin `components/rich-editor/`（TipTap 3.29.2 精确锁定 + toolbar/BubbleMenu/docx 导入/markdown 显式应用/懒加载 tiptap chunk）；news-form/settings 接入；admin 声明 mammoth+marked@17（web 18 并存） |
| E2 | ✅ | `/content/snapshot` 端点（60s Redis 缓存 + ETag/304）；`sanitize.py`（bleach 白名单）接入 news_service/admin_content/admin_settings 写入边界；uploads presign 服务端校验（purpose 白名单 + 扩展名 + size≤10MB + MIME）；`fetch-content-snapshot.ts`（URL→fixture→跳过；CI 配 URL 失败 fail-fast、未配 URL 跳过不破坏现有发布）+ `ssg-content.ts`（news 列表/窗口详情/about + rl-bootstrap + JSON-LD + DOMPurify 二次清洗）；构建链 `fetch→ssg-content` 位于 gzip 之前；SW data/content.json network-first；`_redirects` 移除 catch-all（R7）；pages.yml 加 CONTENT_SNAPSHOT_URL secret 输入 |
| E3 | ✅ | `lib/content-snapshot.ts`（readBootstrap/loadSnapshotJson/prefillQueryData）；news 列表 search 参数化（category/page）+ 快照预填 + staleTime 30s 刷新；详情仅公开无 preview 预填；`/about` 新路由（bootstrap→快照→API）；header/footer 链接 |

**发布 SLA（oracle R3 文档化）**：Admin 保存内容后，静态内容页在**下次 CI 部署**（main push/手动 dispatch）时随快照重建。可见窗口文章不生成静态详情（§4.1），撤稿后静态页残留问题仅影响无窗口文章——重新部署即移除。webhook 触发重建列为 E6 backlog。

**CI 配置**：生产 Pages 项目需设置 secret `CONTENT_SNAPSHOT_URL`（指向生产 API `/api/v1/content/snapshot`）；未配置时构建跳过内容页（不破坏现有发布），配置后拉取失败即 fail-fast。

**遗留**：guide/help 迁移（E5）；base 路径修正（E6）；内容发布 webhook（E6）；sitemap 由 ssg-content 追加新闻 URL 的实现（当前 sitemap 由 generate-samples 维护，新闻 URL 未入 sitemap——已记录）。
