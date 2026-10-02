# SoyMutDB 内容管理与模板生成优化方案

> **已归档（2026-10-01）**：一次性任务笔记与旧状态视图（结论已进入现状视图与计划）。继任：docs/dev/project-status.md；任务级进度见 `docs/aegis/plans/`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> **版本**：v5.0
> **日期**：2026-08-29
> **范围**：`apps/admin`（内容管理界面）· `apps/web/scripts`（SSG 与模板生成）· `apps/api/app/page_builder`（服务端注册表）· `packages/shared`（契约）
> **定位**：本方案是 SoyMutDB 优化系列的第五份，与其余四份互补，不重叠。

> **2026-09-26 校正（历史文档）**：文中 `packages/i18n` 已移除（现为 `packages/i18n-core`）；
> Page Builder/Widgets 管理面按 ADR-0009 有意退役，内容页现由 `/content`、`/content/legacy` 承担。

| 文档 | 主题 |
| --- | --- |
| `optimization-plan.md`（v1.0） | 工程化改造 |
| `performance-optimization-plan.md`（v2.0） | 性能与动效 |
| `desktop-client-plan.md`（v3.0） | Tauri 桌面客户端 |
| `platform-optimization-plan.md`（v4.0） | 后端架构 · 查询性能 · 前端架构 · 管理后台 |
| **`content-template-plan.md`（v5.0）** | **内容管理 · 模板生成 · SSG 管线** |

---

## §0 结论摘要

内容管理与模板生成这两块的现状可以概括为一句话：**能力已经建好了，但没有接上**。

已经建好的部分相当扎实——服务端组件注册表有 19 个组件、每个都有独立的 Pydantic 配置模型、递归校验、危险字符串拦截、富文本消毒、插件启动器校验；PageDefinition 有完整的状态机（draft → preview → requested → published）、乐观锁、outbox 发布流；SSG 管线有 9 个串行的构建步骤、双语渲染、sitemap 追加、CSP 注入。

但接线的地方断了三处：

| # | 断层 | 后果 |
| --- | --- | --- |
| **G1** | `StaticPage` 不进 SSG、不进快照 | 管理员在 Content → Pages 建的页面，除一个硬编码的 `guide.tsx` 外，**公共站根本看不到** |
| **G2** | `EMBED_ROUTES` 硬编码只含 `/` | Page Builder 建的页面只有首页享受 SSG 嵌入，其余运行时拉 API |
| **G3** | 模板硬编码在前端 TS 里 | 加一个模板要改代码 + 发版；管理员无法自定义；模板不走服务端预校验 |

此外还有两个契约层面的隐患：

| # | 隐患 | 后果 |
| --- | --- | --- |
| **G4** | 组件清单存在**三份真相** | 后端删除某组件后，前端测试依然全绿，提交时才 422 |
| **G5** | `allowed_children` 是死字段且暴露给前端 | 编辑器拿不到真实的嵌套规则（真正生效的 `_LAYOUT_CONTAINERS` 没暴露） |

**优先级建议**：G1 > G3 > G4 > G2 > G5。

G1 排第一，因为它不是"体验不好"，是"功能不生效"——用户在管理后台做了操作，结果在公共站没有任何反映，而且没有任何提示告诉他这一点。这类问题对信任的伤害远大于界面难用。

---

## §1 现状盘点

### §1.1 三套内容源并存（核心矛盾）

仓库里同时存在三套彼此独立的内容存储，各有各的编辑入口、各有各的公共 API，互不相通：

| 维度 | A. `SystemSetting.about.*` | B. `StaticPage` | C. `PageDefinition` |
| --- | --- | --- | --- |
| 存储 | `system_settings` 表 `about.*` 键 | `static_pages` 表 | `page_definitions` + `page_definition_versions` |
| 内容形态 | 6 个纯文本字段（en/zh） | `content_en/zh` 富文本 HTML | JSON 组件树（19 种组件） |
| 管理入口 | Settings 页 | Content → Pages tab | Page Builder（独立路由） |
| 管理 API | `/admin/settings` | `/admin/content/pages` | `/admin/page-builder/pages` |
| 公共 API | 无（只在快照里） | `/content/pages[/{slug}]` | `/page-definitions/{route}` |
| 导航分组 | Administration | **Tools** | **Presentation** |
| 版本历史 | 无 | 有 | 有（含乐观锁） |
| 发布流程 | 直接生效 | `publish` / `unpublish` 直接生效 | `publish-request` → outbox 审批 |
| **进快照** | ✅ `_load_about()` | ❌ | ❌ |
| **进 SSG** | ✅ `renderAbout()` | ❌ | ⚠️ 仅 `/` |
| 双语 | 字段级 en/zh | 字段级 en/zh | 组件 props 内（不统一） |

三套体系分属两个不同的导航分组（Tools 与 Presentation），管理员没有任何线索能意识到 `/content` 和 `/page-builder` 是同一件事的两种做法。

### §1.2 G1：`StaticPage` 是一条死路

`StaticPage` 拥有完整的功能实现：

```
apps/api/app/api/v1/admin_content.py   prefix="/admin/content"
  :109  GET    /pages                     列表（分页 + status/category 过滤）
  :156  GET    /pages/{page_id}           详情
  :178  POST   /pages                     创建
  :243  PUT    /pages/{page_id}           更新
  :310  DELETE /pages/{page_id}           删除
  :334  POST   /pages/{page_id}/publish   发布
  :363  POST   /pages/{page_id}/unpublish 下线
  :390  GET    /pages/{page_id}/versions  版本列表
  :422  GET    ...                        版本详情
  :454  POST   ...                        版本回滚
```

前端 `content.tsx` 也相应地实现了完整交互：`PagesTab`（200–547）、`PageFormDialog`（548–757）、`VersionHistoryDialog`（758–950）、`VersionDetail`（951–1035）。

**但是没有任何一条路径把这些数据送到公共站。**

证据一，快照服务不含 StaticPage：

```python
# apps/api/app/services/content_snapshot_service.py:129
snapshot: dict[str, object] = {
    "schema_version": 1,
    "generated_at": now.isoformat(),
    "news": {...},
    "news_detail": news_detail,
    "about": await self._load_about(db),        # ← 来自 SystemSetting，不是 StaticPage
    "publications": await self._load_publications(db),
}
```

证据二，SSG 内容生成只渲染 news / about / publications 三类：

```ts
// apps/web/scripts/ssg-content.ts
:148  renderNewsList(snapshot)      → dist/news/index.html
:197  renderNewsDetail(slug, ...)   → dist/news/{slug}/index.html
:240  renderAbout(snapshot)         → dist/about/index.html
:267  renderPublications(snapshot)  → dist/publications/index.html
```

证据三，整个 web 端对 StaticPage 的消费点只有一个，而且是硬编码 slug：

```ts
// apps/web/src/routes/guide.tsx:355
queryFn: () => http.get<StaticPage>(`/content/pages/${GUIDE_SLUG}`),
```

**净结果**：管理员可以在 Content → Pages 里创建、编辑、发布、版本回滚任意多个页面，投入的全部工作量在公共站上的产出是零。而界面上没有任何提示说明这一点——发布按钮照常返回成功，`status` 照常变成 `published`。

这是本方案里唯一一个"功能不生效"级别的问题，也是排 P0 第一位的理由。

### §1.3 G2：PageDefinition 的 SSG 只覆盖首页

```ts
// apps/web/scripts/embed-page-definitions.ts:24-27
/** Routes we embed bootstrap for (the SPA home + generic hub pages). */
const EMBED_ROUTES: ReadonlyArray<{ route: string; file: string }> = [
  { route: "/", file: "index.html" },
];
```

注释里写着 "the SPA home + **generic hub pages**"，但数组里只有一个元素。**多数的复数形式与单元素的实现不符，说明这是写完骨架后没有继续补的。**

后果：管理员用 Page Builder 建一个 `/about-us` 页面并发布后，该路由在 SSG 产物里没有 bootstrap 脚本，公共端访问时走 `apps/web/src/page-builder/loader.ts` 的运行时 fetch 分支。首屏多一次网络往返，SEO 拿不到预渲染内容，离线/降级场景直接落到 seed fallback。

好消息是机制本身是通用的——`fetchDefinition(route)` 接受任意 route，`inject(html, bootstrap)` 也是通用的。缺的只是**路由清单的来源**：现在是硬编码常量，应该是从服务端拉已发布路由列表。

### §1.4 G3：模板硬编码在前端

```ts
// apps/admin/src/lib/page-builder-templates.ts:3
export type PageBuilderTemplateId = "blank" | "research" | "dataExplorer" | "helpCenter";
```

4 个模板（blank / research / dataExplorer / helpCenter）以 TS 字面量的形式写死在前端，共 169 行。创建页面时直接把这个对象 POST 给后端：

```ts
// apps/admin/src/routes/page-builder/index.tsx:34-40
const createMutation = useMutation({
  mutationFn: () =>
    pageBuilderApi.create({
      route,
      title_key: titleKey,
      definition: getPageBuilderTemplateDefinition(templateId),
    }),
  ...
```

这带来四个问题：

1. **加模板要发版**。管理员想加一个"物种专页"模板，只能找开发改 TS、走 CI、重新部署。
2. **模板无法自定义**。管理员不能基于现有页面另存为模板，也不能编辑内置模板。
3. **后端没有模板概念**。服务端有 `COMPONENT_REGISTRY`，却没有模板注册表，模板完全是前端的私有概念。
4. **模板内容硬编码英文**。模板里的文案是英文字符串字面量：

```ts
// page-builder-templates.ts:37
props: { content: "<h1>New page</h1><p>Start with a clear purpose and one primary action.</p>" },
```

   而这是一个中英双语站点。模板实例化后，管理员必须手工把每个 `rich_text` 的英文改写成双语，否则新建的页面在中文语境下是英文的。

### §1.5 G4：组件清单存在三份真相

同一个"有哪些组件"的事实，在仓库里被写了三遍：

| # | 位置 | 数量 | 权威性 |
| --- | --- | --- | --- |
| 1 | `apps/api/app/page_builder/registry.py:335` `_COMPONENTS` | 19 | ✅ 权威 |
| 2 | `packages/shared/src/page-builder.ts:17` `PageComponentType` | 19 | 手写同步 |
| 3 | `apps/admin/src/lib/page-builder-templates.test.ts` allowlist | 12 | 手写副本 |

第 2 份的文件头注释已经意识到这个问题：

```ts
// packages/shared/src/page-builder.ts:6-7
 * Keep ``renderer_key`` values in
 * exact sync with `apps/api/app/page_builder/registry.py`.
```

但"保持同步"只是一条靠自觉的注释，CI 里没有校验。

第 3 份更危险。测试里手工列了 12 个组件类型：

```ts
// apps/admin/src/lib/page-builder-templates.test.ts
it("keeps templates inside the server component allowlist", () => {
    const allowed = new Set([
      "columns", "rich_text", "notice", "resource_cards", "news_list",
      "divider", "tool_entries", "assembly_select", "gene_search_form",
      "location_search_form", "data_table", "tabs",
    ]);
    ...
});
```

这个测试的断言方向是**单向**的：它只检查"模板里用到的类型 ⊆ allowlist"，不检查"allowlist == registry"。因此：

- 后端下线了某个组件 → 前端测试依然全绿（因为 allowlist 是手写的，没人同步删）
- 模板里用了 allowlist 之外的组件 → 测试报错（这是唯一能挡住的情况）
- **模板用了后端已经不存在的组件 → 测试全绿，直到用户点"创建"才 422**

第三点的失败时机太晚了。用户在表单里填完 route 和 title_key，点创建，才被告知模板有问题——而他什么都没做错。

### §1.6 G5：`allowed_children` 是死字段

后端定义：

```python
# apps/api/app/page_builder/registry.py:320-331
@dataclass(frozen=True)
class ComponentDefinition:
    renderer_key: str
    label: str
    config_model: type[BaseModel]
    allowed_children: frozenset[str] = field(default_factory=frozenset)
```

19 个组件在 `_COMPONENTS` 里**没有一个传过 `allowed_children`**，全部是默认的空 frozenset。唯一一处显式传值的是：

```python
# registry.py:355-357
ComponentDefinition(
    "columns", "Columns", ColumnsConfig, frozenset({}),
),
```

传的仍然是空集合。

真正决定嵌套规则的是另一个常量：

```python
# registry.py:364
_LAYOUT_CONTAINERS = {"columns", "tabs"}
```

校验逻辑先判 `_LAYOUT_CONTAINERS`，落在其中的组件跳过 `allowed_children` 检查：

```python
# registry.py:464-469
if node_type not in _LAYOUT_CONTAINERS:
    # Non-layout components are leaves in the reference tree; enforce
    # the declared allowed_children set (empty => no children).
    if children and not entry.allowed_children:
        raise ValidationError(
            f"Component {node_type!r} does not accept children"
        )
```

所以后端行为是**正确**的——`columns` 和 `tabs` 能嵌套，其余是叶子节点。

问题在于对外暴露的接口：

```python
# apps/api/app/api/v1/admin_page_builder.py:80-88
components = [
    ComponentDescriptor(
        renderer_key=entry.renderer_key,
        label=entry.label,
        config_schema=entry.config_schema,
        allowed_children=sorted(entry.allowed_children),   # ← 永远是 []
    )
    for entry in COMPONENT_REGISTRY.values()
]
```

前端通过 `/admin/page-builder/registry` 拿到的 `allowed_children` **永远是空数组**，而真正生效的 `_LAYOUT_CONTAINERS` 从未暴露。编辑器因此无法从服务端得知"哪些组件可以放进 `columns` 里"，只能在前端自行推断。

### §1.7 已成熟、不应改动的部分

以下几处做得好，本方案**不建议重构**，只做增量接线：

- **`registry.py` 的纵深防御**（414–495）：先 `_reject_dangerous` 危险字符串，再 `model_validate` schema，再按字段校验 URL，最后对 `rich_text` 做 `sanitize_rich_html`。`rich_text` 的 `content` 字段被有意豁免前置拦截（因为它是需要消毒的 HTML），这个例外处理是正确的。
- **插件启动器校验**（594–713）：`_LAUNCHER_PLUGIN_REQUIREMENTS` + `_validate_plugin_launcher_node`，JBrowse / BLAST 启动器会检查插件是否启用、origin 是否 https。这是一个容易漏掉的安全面。
- **乐观锁**：`update_draft` 接收 `base_version`，多人同时编辑同一页面不会静默覆盖。
- **publish-request → outbox**：`admin_page_builder.py:235` 发出 `PublishRequestResponse` 含 `event_id`，异步发布不是直接改状态。
- **组件面板服务端驱动**：`component-palette.tsx` 渲染的是 `components: ComponentDescriptor[]`（来自 `/registry`），不是硬编码列表。这一处的设计是对的，模板应当对齐这个模式。
- **SSG 双语与消毒**：`ssg-content.ts` 用 jsdom + DOMPurify 消毒（112–117），`ALLOWED_URL_PROTOCOLS` 白名单（311），`validateSlug` 防路径穿越（329）。
- **`base-template.ts` 的 CSP 与主题初始化**（276、131）：构建期注入，避免首屏闪烁。

---

## §2 P0-1 · 打通 StaticPage → SSG（止血）

**目标**：让管理员在 Content → Pages 里发布的内容，能在公共站上被看到。

### §2.1 方案选型

三个选项：

| 选项 | 做法 | 工作量 | 评价 |
| --- | --- | --- | --- |
| A | StaticPage 进快照 + SSG 生成独立 HTML | 中 | ✅ 推荐。止血最快，不动现有数据模型 |
| B | 一次性迁移 StaticPage → PageDefinition，删除旧体系 | 大 | 正确方向但周期长，且迁移期内容会中断 |
| C | 在管理界面标注"此内容不会公开" | 极小 | 诚实但不解决问题 |

**推荐 A，并把 B 作为 P1 的收尾**（见 §5.3）。先让存量内容生效，再择机收敛体系。

### §2.2 后端：快照新增 `static_pages`

```python
# apps/api/app/services/content_snapshot_service.py

#: Hard cap on the number of static pages included in a snapshot.
SNAPSHOT_MAX_PAGES = 200


async def _load_static_pages(self, db: AsyncSession) -> list[dict[str, object]]:
    """Return published static pages (slug-sorted) as dicts.

    Only ``published`` pages reach the static site.  Unpublished pages are
    deliberately absent rather than present-but-null: the SSG has no runtime
    fallback for them, so emitting nothing avoids serving stale HTML after an
    unpublish.
    """
    stmt = (
        select(StaticPage)
        .where(StaticPage.status == "published")
        .order_by(StaticPage.sort_order.asc(), StaticPage.slug.asc())
        .limit(SNAPSHOT_MAX_PAGES)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        StaticPageResponse.model_validate(row).model_dump(mode="json")
        for row in rows
    ]
```

挂进 `build_snapshot`：

```python
snapshot: dict[str, object] = {
    "schema_version": 2,          # ← 1 → 2，新增字段
    "generated_at": now.isoformat(),
    "news": {...},
    "news_detail": news_detail,
    "about": await self._load_about(db),
    "publications": await self._load_publications(db),
    "static_pages": await self._load_static_pages(db),   # ← 新增
}
```

**`schema_version` 必须升到 2。** 快照是 SSG 与 API 之间的契约，`fetch-content-snapshot.ts` 落盘成 `dist/data/content.json`，前端有 `fallback-data.ts`（30KB）作为兜底。加字段属于破坏性变更，需要一个版本号让消费方能判断。

同时在文件头的 docstring 里补上 `static_pages` 的说明——那段 docstring 写得很好，是这份契约的唯一文档，应当跟着更新。

### §2.3 SSG：新增静态页渲染

```ts
// apps/web/scripts/ssg-content.ts

interface StaticPage {
  id: string;
  slug: string;
  title_en: string;
  title_zh: string | null;
  content_en: string;
  content_zh: string | null;
  summary: string | null;
  category: string | null;
  updated_at: string;
}

function renderStaticPage(page: StaticPage, snapshot: Snapshot): string | null {
  const slug = validateSlug(page.slug);
  if (!slug) {
    // Never write a file whose name we did not validate.
    console.warn(`[ssg-content] skipping static page with unsafe slug: ${page.slug}`);
    return null;
  }

  // Bilingual pairing follows the existing news_detail strategy: the Chinese
  // body replaces the English one when present, they are not concatenated.
  const title = page.title_zh || page.title_en;
  const body = sanitizeHtml(page.content_zh || page.content_en);
  ...
  return renderBaseTemplate({ /* ... */ });
}
```

三个要点：

1. **必须复用 `validateSlug`**（ssg-content.ts:329）。`StaticPage.slug` 来自用户输入，`SLUG_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/` 这道校验是防止路径穿越的唯一屏障，不能绕过。
2. **必须复用 `sanitizeHtml`**（:112）。`content_en/zh` 是管理员通过富文本编辑器写入的 HTML，属于不可信输入。后端在入库时是否消毒需另行确认，SSG 侧必须独立消毒（纵深防御）。
3. **双语策略与 `renderNewsDetail` 保持一致**——看现有实现是"中文存在则替换"还是"并排展示"，新的渲染函数照抄同一套，不要发明第三种。

在 `main()` 里挂上：

```ts
// apps/web/scripts/ssg-content.ts:337 main()
for (const page of snapshot.static_pages ?? []) {
  const html = renderStaticPage(page, snapshot);
  if (!html) continue;
  const outDir = join(DIST_DIR, "pages", page.slug);
  writeHtml(join(outDir, "index.html"), html);
}
appendStaticPagesToSitemap(snapshot);   // 对称于 :390 appendNewsToSitemap
```

### §2.4 URL 冲突：必须先解决

`/content/pages/{slug}` 是现有的公共 API 路径。SSG 生成的静态页如果也放在 `/pages/{slug}`，两者会打架。

**建议**：静态页落到 `/pages/{slug}/index.html`。nginx 侧照 `infra/nginx/conf.d/default.conf:124` 已有的 `/samples/` 写法新增：

```nginx
# /pages/ — SSG-generated static pages (StaticPage content)
# ^~ prevents regex asset locations from intercepting /pages/* paths
location ^~ /pages/ {
    proxy_pass http://web_frontend/pages/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    ...
}
```

`^~` 前缀匹配**不能省**。它会阻止资源类正则 location 抢走这些路径——`:100-102` 的 `/admin/` 与 `:124` 的 `/samples/` 用的都是这个手法，配置注释里也写明了用意。用普通前缀匹配会被资源正则覆盖。

另外 v1.0 P3-4.1 有"nginx 安全头补全"任务，改的是同一个文件，**两处改动应同批提交**，避免 nginx 全量回归做两次。

**验收**：
- 在管理后台新建一个 slug 为 `test-ssg-page` 的 StaticPage 并发布
- 重新跑 SSG
- `dist/pages/test-ssg-page/index.html` 存在且含正文
- 取消发布后重新 SSG，该文件消失

---

## §3 P0-2 · 模板数据化

**目标**：模板从前端 TS 常量变成服务端数据，管理员可查看、可扩展，加模板不需要发版。

### §3.1 数据模型

新增 `page_templates` 表：

```python
# apps/api/app/models/page_builder.py

class PageTemplate(Base, UUIDMixin, TimestampMixin):
    """A reusable starting point for page definitions.

    Templates are server-owned data, not client constants: the Admin editor
    lists them from the API so adding a template never requires a frontend
    release.  ``builtin`` templates are seeded by migration and are read-only
    through the API.
    """

    __tablename__ = "page_templates"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    definition: Mapped[dict] = mapped_column(JSONB)
    preview_image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
```

几个设计决定：

- **`key` 而非自增 ID 作业务主键**：内置模板需要稳定的标识，迁移和 seed 脚本要能幂等地 upsert。
- **`builtin` 标志**：内置模板不允许通过 API 删除或修改，只允许"克隆为用户模板"。避免管理员改坏了内置模板后无法恢复。
- **`preview_image_id` 外键到 `media_assets`**：模板选择是个视觉决策，纯文字下拉很难选。复用已有的媒体库（admin 已有 `media.tsx` 和 `media-picker.tsx`，不要新建）。
- **`definition` 用 JSONB**：与 `page_definition_versions.definition` 保持同一类型。

### §3.2 迁移与种子数据

仓库已有 `apps/api/app/scripts/seed_page_builder.py`，扩展它即可，不要新建脚本。

```python
# apps/api/app/scripts/seed_page_builder.py

BUILTIN_TEMPLATES: list[dict] = [
    {
        "key": "blank",
        "label": "Blank page",
        "category": "general",
        "definition": {...},
    },
    {
        "key": "research",
        "label": "Research overview",
        "category": "research",
        "definition": {...},   # 从 page-builder-templates.ts 搬运
    },
    # dataExplorer / helpCenter ...
]

async def seed_templates(db: AsyncSession) -> int:
    """Upsert builtin templates. Safe to run repeatedly."""
    for spec in BUILTIN_TEMPLATES:
        definition = validate_definition(spec["definition"])   # ← 关键
        await db.execute(
            insert(PageTemplate)
            .values(key=spec["key"], builtin=True, definition=definition, ...)
            .on_conflict_do_update(
                index_elements=["key"],
                set_={"definition": definition, "label": spec["label"], ...},
                where=PageTemplate.builtin.is_(True),   # 不覆盖用户克隆件
            )
        )
```

**`validate_definition` 这一行是重点。** 种子数据必须经过与运行时提交完全相同的校验路径。否则会出现"内置模板实际上不合法"的荒谬情况——管理员选了内置模板，点创建，后端 422。

### §3.3 模板实例化时的双语占位

现有模板的文案是英文硬编码（§1.4）。数据化之后，把文案改成 i18n key 引用：

```python
{
  "type": "rich_text",
  "props": {
    "content_key": "page_template.research.intro",   # ← 替代硬编码 HTML
    "content": "<h1>Research overview</h1>...",       # 保留为 fallback
  },
}
```

`RichTextConfig` 增加一个可选的 `content_key` 字段，渲染时优先查 i18n，查不到回落到 `content`。

这样新建页面的默认文案会跟随界面语言，管理员不必手工翻译模板样板文字，只需替换真正的正文。

> 这一步依赖 i18n 包现有的 key 组织方式（`packages/i18n`）。实施前先确认该包的加载机制是否支持运行时新增 key 前缀，若不支持则降级为"模板携带双语字面量"，但仍要把英文硬编码从 TS 里挪出去。

### §3.4 API

```
GET    /admin/page-builder/templates                 模板列表（含 builtin）
GET    /admin/page-builder/templates/{key}           模板详情
POST   /admin/page-builder/templates                 从现有页面另存为模板
PUT    /admin/page-builder/templates/{id}            编辑用户模板（builtin 拒绝）
DELETE /admin/page-builder/templates/{id}            删除用户模板（builtin 拒绝）
POST   /admin/page-builder/templates/{key}/validate   校验模板合法性（不落库）
```

新增 `/validate` 端点的用途：前端在模板选择下拉里，可以预先知道哪些模板当前不可用（比如用到的组件所依赖的插件被禁用了）。参考 `page_definitions.py:62` 已有的 `FeatureFlagService.is_enabled(db, "page_builder")` 模式。

"另存为模板"的实现直接复用 `get_version` + `validate_definition`：

```python
@router.post("/templates", response_model=PageTemplateResponse)
async def create_template(payload: PageTemplateCreate, ...):
    _require_admin(current_user)
    # Source can be an existing page version or a raw definition.
    if payload.source_version_id:
        version = await page_service.get_version(db, payload.source_version_id)
        definition = version.definition
    else:
        definition = payload.definition
    validated = validate_definition(definition)      # 复用同一校验
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())
    validate_plugin_launchers(validated, plugin_states)   # 复用插件校验
    ...
```

### §3.5 前端改造

`page-builder-templates.ts` 从"常量定义"变成"API 客户端"：

```ts
// apps/admin/src/lib/page-builder-templates.ts（改造后）
export interface PageTemplateSummary {
  id: string;
  key: string;
  label: string;
  description: string | null;
  category: string;
  builtin: boolean;
  preview_url: string | null;
}

// 模板列表改为查询，内置常量降级为"API 不可用时的兜底"
export function usePageTemplates() {
  return useQuery({
    queryKey: ["page-builder", "templates"],
    queryFn: () => pageBuilderApi.listTemplates(),
    placeholderData: { items: FALLBACK_TEMPLATES },
  });
}
```

保留一份精简的兜底常量（blank + research 两个即可），保证 API 不可达时页面仍能创建——镜像 `embed-page-definitions.ts:83-87` 已有的"生产构建不可达则告警不失败"策略。

创建页从下拉选择改为**可视化模板选择器**：分类标签页 + 每个模板一张预览卡片（缩略图 + 名称 + 描述 + 组件构成摘要）。19 个组件的可组合空间很大，纯文字下拉对管理员的信息量不够。

---

## §4 P0-3 · 契约单一真相

**目标**：消灭 §1.5 的三份真相，让"有哪些组件、谁能嵌套谁"只有一个来源。

### §4.1 运行时常量驱动类型（消除第 2 份）

改 `packages/shared/src/page-builder.ts`，让 TS 类型从运行时数组推导：

```ts
// packages/shared/src/page-builder.ts

/** Canonical component renderer keys. Keep in sync with the server registry —
 *  enforced by `pnpm check:page-registry` in CI. */
export const PAGE_COMPONENT_TYPES = [
  "navigation",
  "news_list",
  "media_carousel",
  "resource_cards",
  "rich_text",
  "tool_entries",
  "assembly_select",
  "gene_search_form",
  "location_search_form",
  "data_table",
  "button",
  "link",
  "notice",
  "divider",
  "tabs",
  "columns",
  "jbrowse_launcher",
  "blast_launcher",
  "ontology_relationship_graph",
] as const;

export type PageComponentType = (typeof PAGE_COMPONENT_TYPES)[number];

/** Layout containers that accept arbitrary registered children.
 *  Mirrors `_LAYOUT_CONTAINERS` in `registry.py`. */
export const PAGE_LAYOUT_CONTAINERS = ["columns", "tabs"] as const;

export function isLayoutContainer(type: PageComponentType): boolean {
  return (PAGE_LAYOUT_CONTAINERS as readonly string[]).includes(type);
}
```

数组在前、类型在后，CI 就能直接比对数组，不必解析类型定义。

### §4.2 CI 校验脚本

项目已有 `packages/api-client/scripts/check-contract.sh` 做 OpenAPI 契约校验（v4.0 §2 记录过），照同样的模式加一条：

```bash
#!/usr/bin/env bash
# scripts/check-page-registry.sh
set -euo pipefail

# 1. Dump the authoritative component list from the Python registry.
SERVER_KEYS=$(cd apps/api && python -c "
import json
from app.page_builder.registry import COMPONENT_REGISTRY, _LAYOUT_CONTAINERS
print(json.dumps({'components': sorted(COMPONENT_REGISTRY), 'layouts': sorted(_LAYOUT_CONTAINERS)}))
")

# 2. Dump the client-side list.
CLIENT_KEYS=$(node -e "
const m = require('@soymutdb/shared');
console.log(JSON.stringify({'components': [...m.PAGE_COMPONENT_TYPES].sort(), 'layouts': [...m.PAGE_LAYOUT_CONTAINERS].sort()}));
")

# 3. Compare.
if [ "$SERVER_KEYS" != "$CLIENT_KEYS" ]; then
  echo "✗ page-builder registry drift detected"
  echo "  server: $SERVER_KEYS"
  echo "  client: $CLIENT_KEYS"
  echo "→ update packages/shared/src/page-builder.ts"
  exit 1
fi
echo "✓ page-builder registry in sync"
```

挂到 Turbo 的 `check` 任务里，与 `check:contract` 并列。

### §4.3 删掉测试里的手写 allowlist

```ts
// apps/admin/src/lib/page-builder-templates.test.ts（改造后）
import { PAGE_COMPONENT_TYPES } from "@soymutdb/shared";

it("keeps templates inside the server component allowlist", () => {
  // The allowlist comes from the shared contract, which CI verifies against
  // the server registry — never hand-maintain it here.
  const allowed = new Set<string>(PAGE_COMPONENT_TYPES);
  for (const template of PAGE_BUILDER_TEMPLATES) walk(template.definition.root);
});
```

这一改动把"后端删除组件后前端测试仍绿"的可能性彻底消除。

### §4.4 暴露真实的嵌套规则（消除 G5）

后端 `/registry` 补一个字段：

```python
# apps/api/app/page_builder/schemas.py
class ComponentDescriptor(BaseModel):
    renderer_key: str
    label: str
    config_schema: dict[str, Any]
    allowed_children: list[str] = Field(default_factory=list)
    is_layout_container: bool = False          # ← 新增
    max_children: int | None = None            # ← 新增（可选，用于 columns 的 columns 上限）
```

```python
# apps/api/app/api/v1/admin_page_builder.py:80-88
components = [
    ComponentDescriptor(
        renderer_key=entry.renderer_key,
        label=entry.label,
        config_schema=entry.config_schema,
        allowed_children=sorted(entry.allowed_children),
        is_layout_container=entry.renderer_key in _LAYOUT_CONTAINERS,   # ← 新增
    )
    for entry in COMPONENT_REGISTRY.values()
]
```

同时更新 `packages/shared/src/page-builder.ts` 的 `ComponentDescriptor` 接口与 `admin_page_builder.py` 的 OpenAPI 描述——注意这条链路有 `check:contract` 守着，改了 schema 就必须重新生成 api-client，CI 会强制。

关于 `allowed_children` 本身：目前全空且实际未启用。有两个选择：

| 选择 | 做法 |
| --- | --- |
| 保守 | 保留字段但文档注明"当前所有组件均为叶子或布局容器，细粒度白名单未启用" |
| 彻底 | 启用它，为每个组件声明真实的 allowed_children，替换 `_LAYOUT_CONTAINERS` 的隐式约定 |

**建议保守**。当前 19 个组件的嵌套语义就是"两类：容器和叶子"，`_LAYOUT_CONTAINERS` 足够表达。引入细粒度白名单会增加 schema 维护成本，却没有对应的需求。但字段既然暴露给了前端，就必须在文档里说清楚它当前是空的，否则后来者会以为是 bug。

---

## §5 P1 · 内容管理统一入口

### §5.1 导航重构

现状：`/content` 在 **Tools** 组，`/page-builder` 在 **Presentation** 组（`admin-sidebar.tsx:42`、`:55`）。两者是同一件事的两种实现，却分属不同的心智分类。

改为统一的 **Content** 分组：

```
Content
  ├─ Pages              /content/pages          （PageDefinition 列表，主入口）
  ├─ Legacy Pages       /content/legacy         （StaticPage，标注"只读 · 待迁移"）
  ├─ News               /news
  ├─ Publications       /publications
  └─ Media Library      /media

Presentation
  ├─ Page Templates     /page-builder/templates （新增，模板管理）
  ├─ Widgets            /widgets
  ├─ Layout Editor      /layout
  └─ ...
```

关键点：**PageDefinition 的列表进 `/content/pages`，成为"页面"的主入口**；Page Builder 的编辑器仍留在 `/page-builder/$pageId`（它是编辑态，不是列表态）。这与 `news` 的组织方式一致——`news/index.tsx` 是列表，`news/$id.tsx` 是编辑。

### §5.2 content.tsx 拆分

1,248 行拆成 6 个文件，按当前的行边界切，不动逻辑：

```
apps/admin/src/routes/content/
  ├─ index.tsx                    容器 + tab（原 159–194）
  ├─ pages-tab.tsx                （原 200–547，348 行）
  ├─ page-form-dialog.tsx         （原 548–757，210 行）
  ├─ version-history-dialog.tsx   （原 758–950，193 行）
  ├─ version-detail.tsx           （原 951–1035，85 行）
  └─ news-publication-tab.tsx     （原 1036–1248，213 行）
```

拆分时顺手做三件事（都是低风险纯机械改动）：

1. **抽 query key 工厂**。现在散落着 `["admin-pages", page, statusFilter, categoryFilter]`（:214）、`["page-builder", "pages", page]`（page-builder/index.tsx:29）两处裸数组。v4.0 §4.2 已给出 `queryKeys` 工厂模式，这里对齐：

```ts
export const contentKeys = {
  all: ["content"] as const,
  pages: (params: { page: number; status?: string; category?: string }) =>
    ["content", "pages", params] as const,
  pageVersions: (id: string) => ["content", "pages", id, "versions"] as const,
  news: (params: ...) => ["content", "news", params] as const,
};
```

   现在 `invalidateQueries({ queryKey: ["admin-pages"] })` 出现在 5 个 mutation 的 `onSuccess` 里（231、241、250、259、267），是重复的重灾区。

2. **抽 mutation 工厂**。`createMutation` / `updateMutation` 的 `onSuccess` 完全一样（231–234 与 240–243），`publishMutation` / `unpublishMutation` 的也一样（255–261 与 263–269）。四个可以合成两个：

```ts
const invalidatePages = () => queryClient.invalidateQueries({ queryKey: contentKeys.all });

const upsertMutation = useMutation({
  mutationFn: (p: { id?: string; payload: StaticPageCreate | StaticPageUpdate }) =>
    p.id ? http.put(`/admin/content/pages/${p.id}`, { json: p.payload })
         : http.post("/admin/content/pages", { json: p.payload }),
  onSuccess: () => { invalidatePages(); setFormOpen(false); setEditing(null); },
});

const publishStateMutation = useMutation({
  mutationFn: (p: { id: string; published: boolean }) =>
    http.post(`/admin/content/pages/${p.id}/${p.published ? "publish" : "unpublish"}`),
  onSuccess: invalidatePages,
});
```

   `handleSubmit`（285–313）里那个 `editing ? update : create` 的分支也随之消失。

3. **URL 承载筛选状态**。v4.0 §4.3 立的铁律——`page` / `statusFilter` / `categoryFilter` 三个 `useState`（203–205）应当移到 URL search params。理由：管理员筛到"已发布 · 教程类 · 第 3 页"后想把这个视图发给同事，现在做不到；刷新也会丢失。

### §5.3 StaticPage 迁移器（P1 收尾）

P0 阶段让 StaticPage 生效之后，P1 提供向 PageDefinition 的迁移路径：

```python
# apps/api/app/services/static_page_migration_service.py

def convert_to_definition(page: StaticPage) -> dict:
    """Convert a legacy StaticPage into a PageDefinition v2 payload.

    The bilingual body becomes a single ``rich_text`` node per language
    wrapped in a ``columns`` root, matching the shape produced by the
    ``blank`` template so migrated pages behave like any other page.
    """
    root = {
        "type": "columns",
        "props": {"columns": 1},
        "children": [{
            "type": "rich_text",
            "props": {
                "content": page.content_en,
                "content_zh": page.content_zh,     # 若 RichTextConfig 支持
            },
        }],
    }
    return validate_definition({
        "schema_version": 2,
        "title_key": f"page.{page.slug}.title",
        "root": root,
        "data_sources": [],
        "theme_id": "scientific-light",
        "layouts": {"desktop": {}, "tablet": {}, "mobile": {}},
    })
```

迁移是**单向且保留原记录**的：生成新的 PageDefinition（draft 状态），StaticPage 本身不删除，管理员确认新页面无误后自行归档。不要在迁移里做破坏性操作，也不要自动发布——发布有审批流，跳过它就是绕过治理。

前端在 Legacy Pages 列表上加一个「迁移到 Page Builder」的批量操作，迁移后给出跳转链接。

---

## §6 P1 · 编辑器能力补齐

### §6.1 现状

`page-builder-editor.tsx`（19.5KB / 537 行）已有的能力：

- 组件树选择：`getNode`（:55）、`setNodeProps`（:66）、`updateChildren`（:81）
- 顺序调整：`arrayMove`（:530）
- 响应式分档：`LAYOUT_DEVICES = ["desktop", "tablet", "mobile"]`（:49）
- 撤销栈：`history` + `page-builder-history.ts`
- 草稿覆盖：`draftOverride`（:99）
- 预览：`previewMutation`（:190）
- 发布：`publishMutation`（:204）

缺失的能力：**拖拽**。组件只能通过"添加 + 上移/下移"操作，无法拖动到目标位置，也无法拖进 `columns` 的子节点。

### §6.2 引入 dnd-kit

```bash
pnpm --filter @soymutdb/admin add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

选择 dnd-kit 而非 react-dnd 的理由：无外部依赖、体积约 30KB、内置键盘可达性（`KeyboardSensor`），与 antd 无冲突。

核心是把组件树映射为可排序的容器：

```tsx
function SortableNode({ node, path, registry }: SortableNodeProps) {
  const { attributes, listeners, setNodeRef, transform, transition } =
    useSortable({ id: path.join(".") });

  const container = registry.find((c) => c.renderer_key === node.type);
  const canNest = container?.is_layout_container ?? false;   // ← 用 §4.4 的新字段

  return (
    <div ref={setNodeRef} style={{ transform: CSS.Translate.toString(transform), transition }}>
      <NodeHeader {...attributes} {...listeners} type={node.type} />
      {canNest && node.children?.length ? (
        <SortableContext items={node.children.map((_, i) => [...path, i].join("."))}>
          {node.children.map((child, i) => (
            <SortableNode key={i} node={child} path={[...path, i]} registry={registry} />
          ))}
        </SortableContext>
      ) : null}
    </div>
  );
}
```

`canNest` 直接读 §4.4 新增的 `is_layout_container`——这就是把 G5 修好之后才顺理成章能做的事。在 §4.4 之前，前端只能硬编码 `["columns", "tabs"]`，又把第三份真相换了个地方。

### §6.3 保留降级路径

`arrayMove`（:530）不要删。它对应的是键盘操作与无障碍路径——dnd-kit 的 `KeyboardSensor` 需要一个程序化的 move 实现。同时保留"上移/下移"按钮，供不使用鼠标的场景。

验收项：只用键盘（Tab 聚焦 + Space 抓取 + 方向键移动 + Space 放下）应能完成一次组件重排。

### §6.4 模板预览

`preview_image_id`（§3.1）在模板选择器里渲染缩略图。图片来自已有的媒体库，复用 `media-picker.tsx` 做选择，不要新建上传组件。

---

## §7 P2 · 发布治理与可观测

### §7.1 SSG 路由清单动态化（消除 G2）

改 `embed-page-definitions.ts`，从硬编码常量改为拉取已发布路由：

```ts
// apps/web/scripts/embed-page-definitions.ts

interface PublishedRoute {
  route: string;
  version: number;
  status: string;
  definition: { title_key?: string; root: unknown };
}

async function fetchPublishedRoutes(): Promise<PublishedRoute[]> {
  const url = `${API_BASE}/api/v1/page-definitions/published-routes`;
  try {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (!res.ok) return [];
    return (await res.json()) as PublishedRoute[];
  } catch {
    return [];
  }
}
```

后端补一个端点：

```python
# apps/api/app/api/v1/page_definitions.py

@router.get("/published-routes", response_model=list[PublishedRouteSummary])
async def list_published_routes(db: AsyncSession = Depends(get_db)) -> list[...]:
    """Routes with a published definition, for the SSG embed step.

    Deliberately public (no auth): the SSG build runs in CI where credentials
    are unavailable, and this only exposes already-public content.
    """
    if not await FeatureFlagService.is_enabled(db, "page_builder"):
        return []
    ...
```

**要不要鉴权**：不加。SSG 在 CI 里跑，配置凭据会增加密钥分发面；而这个端点暴露的都是已经公开的已发布内容，没有新增信息泄露。对于 `internal` variant（`build-sites.ts` 有 external/internal 两个变体），如果内部站的页面定义不应外泄，则需要加一个简单的构建令牌——实施时按实际部署形态决定。

路由到文件路径的映射：

```ts
function routeToFile(route: string): string | null {
  if (route === "/") return "index.html";
  const slug = validateRouteSegment(route);   // 复用 SLUG_RE 思路，允许 /
  return slug ? join(slug, "index.html") : null;
}
```

保留原有的"无已发布定义则 warn 不 fail"策略（:65-70、:83-87），保证 API 不可达时构建仍能产出一个可用的 SPA。

### §7.2 发布前校验可视化

`page-builder/index.tsx` 的 `AdminUsageGuide`（:60-76）已经列出了 4 步工作流和涉及的 API、数据表，这个引导做得好。可以在编辑器里补一条实时的**发布就绪检查**：

```
✓ 所有组件通过 schema 校验
✓ 响应式布局已在三档下预览
⚠ 页面包含 BLAST 启动器，但 BLAST 插件当前未启用
✗ 存在未保存的草稿变更
```

前三项都能从现有数据算出来：schema 校验调 `preview`（:190 已有）、布局预览调 `LAYOUT_DEVICES` 切换（:49 已有）、插件状态从 `publishMutation` 的错误里能拿到（`_LAUNCHER_PLUGIN_REQUIREMENTS` 已在后端校验）。

### §7.3 构建产物校验

已有 `apps/web/scripts/validate-static-tree.ts`（4.7KB）和 `smoke-pages.ts`（9KB）。补两条断言：

1. `dist/pages/*/index.html` 的文件数量 == 快照里 `static_pages` 的数量（防止 SSG 静默跳过）
2. PageDefinition 路由的 HTML 里 `#rl-page-definition` bootstrap 存在且 `status === "published"`

第 1 条尤其重要——§2 的整个 P0 工作如果 SSG 侧某个 slug 校验失败被 `continue` 掉，构建依然会成功，只有这一条断言能发现。

---

## §8 路线图

| 阶段 | 任务 | 依赖 | 工作量 | 风险 |
| --- | --- | --- | --- | --- |
| **P0** | **P0-1** StaticPage 进快照 + SSG | 确认 `/pages/*` 路由归属 | 2–3d | 中（URL 冲突） |
| | **P0-2** 模板数据化（模型 + seed + API + 前端） | — | 4–5d | 低 |
| | **P0-3** 契约单一真相 + CI 校验 | — | 1–2d | 低 |
| **P1** | P1-1 导航重构（统一 Content 分组） | P0-2 | 1d | 低 |
| | P1-2 content.tsx 拆分 + query key 工厂 | — | 1–2d | 低 |
| | P1-3 StaticPage 迁移器 | P0-1、P0-2 | 3d | 中（数据转换） |
| | P1-4 编辑器 dnd-kit | P0-3 | 3d | 低 |
| **P2** | P2-1 SSG 路由清单动态化 | P0-1 | 2d | 低 |
| | P2-2 发布就绪检查 | P0-2 | 2d | 低 |
| | P2-3 构建产物校验断言 | P0-1 | 1d | 低 |

**关键路径**：P0-3（契约）→ P1-4（编辑器拖拽）。因为拖拽的嵌套判断依赖 §4.4 新增的 `is_layout_container` 字段。

**可并行的**：P0-1（SSG 止血）与 P0-2（模板数据化）互不依赖，两个人可以同时做。

---

## §9 风险

| # | 风险 | 影响 | 缓解 |
| --- | --- | --- | --- |
| R1 | `/pages/*` 被资源类正则 location 抢先匹配 | 静态页 404 | 必须照 `default.conf:124` 用 `location ^~ /pages/`；与 v1.0 P3-4.1（nginx 安全头）同批提交，见 §2.4 |
| R2 | `schema_version` 1 → 2 破坏旧快照消费方 | 旧版前端读新快照异常 | 快照消费方只有 `fetch-content-snapshot.ts` 一处，同步升级即可；`fallback-data.ts` 需检查是否含 `schema_version` |
| R3 | 模板数据化后内置模板与前端兜底常量不一致 | API 不可达时创建出过期模板 | 兜底只保留 blank + research 两个最简模板，降低不一致面 |
| R4 | StaticPage 迁移丢失富文本格式 | 迁移后页面样式异常 | 迁移生成 draft 不自动发布，管理员肉眼确认后才发布；原记录保留 |
| R5 | `content_key` 的 i18n 方案与 `packages/i18n` 加载机制不兼容 | 双语占位无法生效 | 先做技术验证；不兼容则降级为模板携带双语字面量 |
| R6 | dnd-kit 与 antd 的拖拽/弹层冲突 | 拖拽时弹层错位 | dnd-kit 无全局 portal 依赖；`property-panel.tsx` 若用 Modal 需设 `getContainer={false}` |

---

## 附录 A · 文件索引

### 后端

| 文件 | 行数 | 关键位置 |
| --- | --- | --- |
| `apps/api/app/page_builder/registry.py` | 715 | `:42` RESERVED_ROUTES · `:61` _APPROVED_ACTIONS · `:281` _PAGE_THEMES · `:292` _CONFIG_MODELS(19) · `:320` ComponentDefinition · `:327` allowed_children · `:335` _COMPONENTS(19) · `:364` _LAYOUT_CONTAINERS · `:414` _validate_node · `:464` 嵌套判定 · `:496` validate_route · `:514` validate_definition · `:594` 插件启动器要求 · `:687` validate_plugin_launchers |
| `apps/api/app/page_builder/schemas.py` | 130 | `:108` allowed_children |
| `apps/api/app/page_builder/service.py` | 374 | `:36` list_pages · `:62` get_latest_versions · `:120` create_page · `:159` update_draft(乐观锁) · `:211` preview · `:243` get_versions · `:271` publish_request · `:329` publish_version · `:336` get_published |
| `apps/api/app/api/v1/admin_page_builder.py` | 252 | `:74` GET /registry · `:85` allowed_children(死字段) · `:92` GET /pages · `:112` POST /pages · `:163` PUT /draft · `:185` POST /preview · `:222` POST /publish-request |
| `apps/api/app/api/v1/page_definitions.py` | 84 | `:56` GET /{route:path} · `:62` FeatureFlag |
| `apps/api/app/api/v1/admin_content.py` | — | prefix `/admin/content`，StaticPage 全套 CRUD + 版本 |
| `apps/api/app/api/v1/content.py` | — | `:172` GET /pages · `:185` GET /pages/{slug} |
| `apps/api/app/services/content_snapshot_service.py` | 154 | `:45` SNAPSHOT_MAX_ARTICLES=500 · `:51` _ABOUT_KEYS · `:71` build_snapshot · `:129` snapshot 结构 · `:154` _load_about · `:164` _load_publications |
| `apps/api/app/models/page_builder.py` | 125 | PageDefinition / PageDefinitionVersion |
| `apps/api/app/scripts/seed_page_builder.py` | — | 内置模板种子（待扩展） |

### 前端 Admin

| 文件 | 规模 | 关键位置 |
| --- | --- | --- |
| `apps/admin/src/routes/content.tsx` | 1,248 行 | `:159` ContentPage · `:200` PagesTab(348) · `:548` PageFormDialog(210) · `:758` VersionHistoryDialog(193) · `:951` VersionDetail(85) · `:1036` NewsPublicationTab(213) |
| `apps/admin/src/routes/page-builder/index.tsx` | 131 行 | `:28` useQuery · `:34` createMutation · `:47` hash 跳转 · `:60` AdminUsageGuide |
| `apps/admin/src/routes/page-builder/$pageId.tsx` | 379B | 薄壳，转发到 PageBuilderEditor |
| `apps/admin/src/components/page-builder/page-builder-editor.tsx` | 537 行 | `:41` PAGE_THEMES · `:49` LAYOUT_DEVICES · `:55` getNode · `:99` draftOverride · `:106` history · `:169` save · `:190` preview · `:204` publish · `:530` arrayMove |
| `apps/admin/src/components/page-builder/component-palette.tsx` | 2.0KB | 服务端驱动 ✅ |
| `apps/admin/src/components/page-builder/component-tree.tsx` | 6.1KB | 组件树 |
| `apps/admin/src/components/page-builder/property-panel.tsx` | 9.1KB | 属性面板 |
| `apps/admin/src/lib/page-builder-templates.ts` | 169 行 | `:3` 4 个模板 ID · `:26` PAGE_BUILDER_TEMPLATES |
| `apps/admin/src/lib/page-builder-templates.test.ts` | — | 手写 12 项 allowlist ⚠️ |
| `apps/admin/src/lib/page-builder-api.ts` | 129 行 | API 客户端 |
| `apps/admin/src/components/admin-sidebar.tsx` | — | `:42` /content(Tools) · `:55` /page-builder(Presentation) |
| `apps/admin/src/components/rich-editor/` | — | docx-import · markdown-mode · tiptap-editor · toolbar |

### 前端 Web / SSG

| 文件 | 行数 | 关键位置 |
| --- | --- | --- |
| `apps/web/scripts/base-template.ts` | 492 | `:51` discoverAssets · `:131` THEME_INIT_SCRIPT · `:148` WIDGET_LOADER · `:276` CSP · `:310` REDUCED_MOTION · `:326` renderBaseTemplate · `:449` renderRedirectTemplate |
| `apps/web/scripts/ssg-content.ts` | 421 | `:112` sanitizeHtml · `:148` renderNewsList · `:197` renderNewsDetail · `:240` renderAbout · `:267` renderPublications · `:311` URL 协议白名单 · `:329` validateSlug · `:390` appendNewsToSitemap |
| `apps/web/scripts/embed-page-definitions.ts` | 94 | `:25` EMBED_ROUTES（仅 `/`）⚠️ · `:42` fetchDefinition |
| `apps/web/scripts/build-sites.ts` | — | 9 步串行 · external/internal 双变体 |
| `apps/web/scripts/ssg-build.ts` | 323 | 路由树生成 |
| `apps/web/scripts/fetch-content-snapshot.ts` | — | 快照落盘 `dist/data/content.json` |
| `apps/web/scripts/validate-static-tree.ts` | — | 产物校验 |
| `apps/web/scripts/smoke-pages.ts` | — | 冒烟 |
| `apps/web/src/page-builder/loader.ts` | — | `:60` pageDefinitionKey · bootstrap 水合 |
| `apps/web/src/routes/guide.tsx` | — | `:355` 唯一 StaticPage 消费点 |

### 共享契约

| 文件 | 规模 | 关键位置 |
| --- | --- | --- |
| `packages/shared/src/page-builder.ts` | 5.3KB / 194 行 | `:17` PageComponentType(19) · `:87` PAGE_THEMES · `:122` normalizePageDefinition · `:184` ComponentDescriptor · `:191` RegistryResponse |

---

## 附录 B · 与其余四份方案的边界

| 主题 | 归属 |
| --- | --- |
| content.tsx 的巨型页拆分（通用方法论） | v4.0 §5 |
| **content.tsx 拆分的具体行边界与 StaticPage 语义** | **本方案 §5.2** |
| admin 端补 ErrorBoundary | v4.0 §5 |
| 查询性能（trigram / keyset / 物化视图） | v4.0 §3 |
| 横切管线化（`@cached` / 声明式审计） | v4.0 §2 |
| 桌面客户端 / Tauri | v3.0 |
| 首屏体积 / 动效分级 | v2.0 |
| 工程化改造（Vite chunk、CI Turbo 缓存、CSRF 统一、antd-theme 去重、nginx 安全头等） | v1.0 |
| `hash_ip` 盐外置（`analytics_service.py:32`） | v6.0 附录 A-16 |
| **SSG 管线 / 模板 / Page Builder / 快照契约** | **本方案** |

**冲突处理**：本方案 §2 的 `/pages/*` 路由与 v1.0 P3-4.1（nginx 安全头补全）改的是同一个文件 `infra/nginx/conf.d/default.conf`，**必须同批提交**。

**勘误**：早期版本曾称"v1.0 记录了 nginx server 级正则误路由 admin/jbrowse 的问题"——该说法不成立。该文件的 `/admin/`（`:100-102`）与 `/samples/`（`:124`）已正确使用 `location ^~` 规避正则拦截，注释里也写明了用意，是**应当照抄的范例**而非待修的 bug。同理，"导入只计数不落库"亦不成立。详见 v6.0 §1 勘误表。
