# SoyMutDB Next 完成方案：从现有基线到“TSV 导入 → 页面构建 → 静态发布 → 布局渲染”全链路

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 创建日期：2026-08-16
> 状态：方案草案（待审核）
> 依据：
> - `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md`
> - `docs/superpowers/plans/2026-08-14-phase-1-module-tsv-import-foundation.md`
> - `docs/superpowers/plans/2026-08-14-phase-2-admin-page-builder.md`
> - `docs/superpowers/plans/2026-08-14-phase-3-static-multitarget-publication.md`
> - `docs/superpowers/plans/2026-08-14-phase-4-public-web-layout-renderer.md`
> - `docs/design/full-stack-upgrade-2026-08.md`、`docs/design/multispecies-portal-product-architecture-design.md`

---

## 0. 执行进度（2026-08-16）

- [x] Phase 0：outbox 任务契约（`enqueue_task_event` + dispatcher malformed 校验 + `release_pointer_changed` 可执行任务）
- [x] Phase 0：Widget 契约对齐（API list/health shape、Admin 枚举）
- [x] Phase 0：Admin content/publication 调用修复（新增 `/admin/publications` CRUD，News tab 改用 `/admin/news`）
- [~] Phase 1：已建 `module_data` 模型、`0015` 迁移、共享 TSV schema registry、`module_import_service`、`admin_modules`、Admin 导入字段、`ModuleTsvAdapter`、worker 状态回写与 `static_publish` 占位任务
- [ ] Phase 2/3/4/5：未开始

> 注意：`module_import_service.py`、migration 0015 尚未在真实 PostgreSQL/testcontainer 环境验证（本机无 Docker）；`apps/web` typecheck 存在历史基线错误，与本次改动无关。

## 1. 项目当前设计（已确认基线）

SoyMutDB Next 是“管理控制台 → 静态资源生成中心 → 内部/外部搜索 API → 科研门户”的多物种突变数据库。

```text
GitHub Pages / Nginx 静态层
    ├─ apps/web       公共 SSG 门户（React 19 + Vite + TanStack Router/Query + AntD）
    ├─ apps/admin     Admin 控制台（Web 本地受限 / Tauri 桌面）
    └─ apps/jbrowse   JBrowse 2 基因组浏览器静态资源

apps/api                FastAPI：/api/v1/* REST + Admin + widget + content/snapshot
apps/worker             Celery：ingest/blast/gwas/analyses/export/stats/email 等任务
PostgreSQL              权威业务状态：users、releases、data_sets、import_tasks、
                        active_release、provenance、outbox、audit、内容/新闻/通知
ClickHouse              可重建分析事实（variant_facts、analytics）
Redis×2                 缓存 与 Celery broker/result（隔离）
MinIO/S3                源文件、导出、分析产物
```

### 1.1 关键架构决策

- **事务性 outbox**：业务状态与 `outbox_events` 同事务写入，后台 dispatcher 以 `task_id=event_id` 投递 Celery，实现至少一次投递；worker 幂等。
- **Release 权威状态机**：`draft → validated → ready → published → rolled_back`；`active_release` 指针在行锁保护的事务内切换，切换事务不做构建/网络调用。
- **导入状态机**：`uploading → validating → ingesting → ready → published/rolled_back`，失败可重试；API 只签发 MinIO multipart 预签名，大文件浏览器直传，不读入 FastAPI。
- **安全边界**：公开页静态化 + 动态数据走 API；Admin 仅 localhost/intranet；外部内容经 Jinja2/bleach/DOMPurify/Trusted Types 多层清洗；页面构建器只接受服务端注册的固定组件，禁止任意 HTML/JS/模板。
- **发布模型**：每次发布选择单一目标 `local | github_pages | cloudflare_pages`；制品不可变、manifest 可校验、可回滚；页面定义与 TSV 文件不能携带凭据。

### 1.2 已完成的部分（2026-08 基线）

- 迁移已到 `0014_data_publishing_release_core.py`：`data_sets`、`release_data_sets`、`active_release`、`provenance` 已建模。
- Release/导入状态机与 Admin Release 生命周期端点已有实现（`release_service.py`、`import_state_machine.py`、`admin.py`）。
- MinIO multipart 预签名、对象登记、`create_import_command` 幂等创建已存在。
- 七类导入适配器骨架存在；VCF 解析（cyvcf2 + ClickHouse Replacing）与 FASTA/GFF3/BLAST DB 适配器有实际逻辑。
- 公共内容 snapshot（news/about）、SSG 内容页、sitemap/404、gzip、service worker、widget 系统、引物设计、SRA、比较、搜索页等均已上线。
- 前端已有 AntD 迁移、i18n、深色模式、动画策略、可访问性基础。

---

## 2. 未完成功能清单（代码证据核查结果）

### 2.1 阻断性基础修复（Phase 1 计划覆盖）

| 缺口 | 现状证据 | 影响 |
|---|---|---|
| outbox 缺少强类型任务契约 | `outbox_service.py` 没有 `enqueue_task_event()`；`create_import_command()` 的 payload 没有 `task_name/kwargs`；`outbox_dispatcher.py` 对缺失 `task_name` 只回退空串并继续投递 | 事件可能以空任务名/错误 payload 投递；失败事件不落 `last_error` |
| `module_tsv` 导入类型未建模 | `ImportTaskType` 无 `MODULE_TSV`；`module_data.py`、迁移 `0015` 不存在 | 新模块 TSV 无法入库 |
| TSV 严格校验缺失 | `module_schema_registry.py`、`module_import_service.py`、`admin_modules.py` 均不存在 | 无法保证表头/类型/唯一键/上限与行级诊断 |
| CSV 适配器只计数不写库 | `data_adapters.py` 的 `CsvUpsertAdapter` 仅 `len(rows)` 并标记 100% 成功 | 会把“只读过文件”误报为导入成功 |
| worker 不持久化状态 | `ingest.py: update_import_progress()` 只 `logger.info`，`ImportTask` 状态/进度/错误不回写 PG | 导入状态机无法闭环 |
| Admin 导入契约缺字段 | `ImportCreateRequest` 无 `module_key/schema_version/release_id/checksum`；route 未校验未知 schema | 无法通过 API 创建 module 导入 |

### 2.2 Admin 契约错位（Phase 2 Task 1 前置）

| 缺口 | 现状证据 |
|---|---|
| Widget 分类不一致 | Admin `widget-api.ts`：`stats/chart/table/list/search/navigation/content/custom`；API schema：`hero/navigation/search/data_table/detail/visualization/stats/external/layout/custom` |
| Widget 权限不一致 | Admin：`public/user/editor/admin`；API：`public/authenticated/admin` |
| 列表/健康契约不一致 | Admin 期望 `{items,total}` 与 `health.widgets[].p50/p95/cache_hit_rate/history`；API `GET /admin/widgets` 实际返回 `list[WidgetResponse]`，`/admin/widgets/health` 返回 `total_widgets/active_widgets/...` 聚合形态 |
| Admin content/publication 调用断裂 | Admin `content.tsx` 的 publication tab 调 `GET /admin/content?type=publication`；`admin_content.py` 只有 `/admin/content/pages*`，没有 `/admin/content` 通用入口，也没有 publication CRUD |
| 公开快照未按 release 隔离 | `content_snapshot_service.py` 与 `/content/snapshot` 无 `release_id` 参数；快照无 release/checksum 元数据 |

### 2.3 页面构建器（Phase 2 主体，完全未开始）

- 无 `page_builder` 模型/迁移 `0016`、组件注册表、service、Admin/公开 API。
- 无共享 DTO（`packages/shared/src/page-builder.ts`）、Admin 三栏编辑器、schema 属性面板、预览 token 端点。
- 五个固定导航与参考页面 seed 未实现。

### 2.4 不可变多目标静态发布（Phase 3 主体，完全未开始）

- 无 `StaticPublication` 模型/迁移 `0017`、发布服务、adapter 协议及 local/github/cloudflare 适配器。
- 无 `static_publish` worker、`build-manifest.ts`、`validate-static-tree.ts`。
- SSG 仍按“active 内容”构建到 `dist/`，非 release 固定、非 fresh-tree、无逐文件 hash manifest。
- `ssg-content.ts` 存在直接 `cover_url`/slug 插值，缺少统一属性转义与 URL 白名单（按 Phase 3 Task 3 修复）。
- Pages workflow 与发布 API 无 `publication_id/artifact_url/manifest_digest` 入参、无可验证单次 commit 的发布适配器。
- 动态请求未携带 `X-SoyMutDB-Release` / `release_id`，静态页切到新 release 后可能静默查询新数据。

### 2.5 公共 Web 布局渲染与七页对齐（Phase 4 主体，完全未开始）

- 无 `apps/web/src/page-builder/` 渲染器与组件适配器。
- 首页仍是 PPTX V2 布局：`HomeHero` + `HomeStatsBar` + 3 个工具卡，而批准规格要求“新闻 2:3 网格 + 五个任务入口 + CMS 内容”，且导航顺序为 Home/Search/Tools/Latest News/Contact。
- 现有导航顺序是 Home/Search/Tools/Contact(实际 `/help`)/News，与规格不符。
- Gene ID 搜索：仅 `?q=` 深度链接，无 `assembly/run` URL 状态；提交不开新 tab；列顺序为 Gene/Assembly/Chromosome/Mutation/GBrowse/Position，与规格的 Assembly/Chromosome/Position/Mutation/Gene/JBrowse 不符。
- Physical Location 搜索：无 URL 参数恢复；提交不开新 tab；列顺序同样不符。
- BLAST 入口 `/search/blast` 是中间卡片，规格要求直接进入完整 `/blast` 表单。
- 大量 `Gbrowse/GBrowse` 文案、注释与 action 标签未改为 JBrowse 2（`genes.tsx`、`location.tsx`、`blast.tsx`、`primer.tsx`、`gbrowse.tsx`、i18n）。
- 无 builder definition 的 bootstrap/hydration 与静态 fallback。

### 2.6 工作区未提交改动

`git status` 显示以下修改尚未提交，且部分与已提交文档存在冲突，必须先决策：

- `.github/workflows/pages.yml`：改为“demo 部署”，删除 admin 构建与 `API_BASE_URL/JBROWSE_URL/CONTENT_SNAPSHOT_URL` secrets。
- `apps/jbrowse/vite.config.ts`：支持 `VITE_BASE_URL`。
- `apps/web/index.html`：入口 script 从 `%BASE_URL%` 改为 `/src/main.tsx`。
- `scripts/test_deployment_workflows.py`：为上述 demo 行为新增断言。

注意：`docs/dev/architecture-and-deployment.md` 仍写 Pages 会同时发布 web/admin/jbrowse 三个 index；`README.md` 也仍按“web、Admin、JBrowse 三面一次发布”描述。二者必须以最终决策为准同步更新。

---

## 3. 方案目标与范围

### 3.1 目标

1. 修好 outbox/导入/worker 状态闭环，让 **module TSV 真正写入 release-scoped PostgreSQL**，只有全链路成功才算发布成功。
2. 让管理员用**服务端注册的安全组件**配置七页公开站点（BLAST/JBrowse 2 除外），草稿可预览、发布不可变。
3. 一次构建产生**一个不可变静态制品 + manifest**，经校验后发布到 **local / GitHub Pages / Cloudflare Pages 三选一**，支持 stale-job 防护与回滚。
4. 公开站点按批准规格重排首页、导航、五个任务入口、搜索表单与结果列，保留现有视觉系统、i18n、深色模式与无障碍。
5. 静态页固定查询其生成时的 release，动态请求显式带 release 上下文。

### 3.2 明确不做

- 不替换 JBrowse 2 / BLAST 执行基础设施。
- 不允许管理员提交任意 HTML/JavaScript/Jinja/第三方模板。
- 不做多目标并行发布；每次发布单目标。
- 不保证第三方 CDN 的跨区域事务可见性（仅平台能力内的原子切换）。
- 不因本项目重做 MCP、分析任务或 Primer 内部流程。
- 不复制线框图颜色/紫色标注；以现有品牌视觉为准。

---

## 4. 执行阶段与依赖关系

```text
Phase 0  基础修复与契约对齐（阻断项）
   │
   ├──► Phase 1  Module TSV 导入地基
   │         │
   ├──► Phase 2  安全 Admin 页面构建器（后端 + Admin UI）
   │         │
   └──► Phase 3  不可变多目标静态发布
             │
             ▼
        Phase 4  公共 Web 布局渲染器与七页对齐
             │
             ▼
        Phase 5  端到端验收、回滚演练与文档收敛
```

建议执行顺序：**Phase 0 → Phase 1 → Phase 2 与 Phase 3 可部分并行 → Phase 4 → Phase 5**。
Phase 2 的 Admin 编辑器可依赖 Phase 2 后端先行；Phase 4 依赖 Phase 2 的 PageDefinition API 与 Phase 3 的 release bootstrap/manifest。

每个阶段的详细任务清单以对应 4 份 phase plan 为准；本方案只列决策、增补任务与验收门。

---

## 5. Phase 0：基础修复与契约对齐（先做，约 1 天）

### 5.1 决策未提交工作区改动

- [ ] 评审 `.github/workflows/pages.yml` 等 4 个未提交修改：若“demo Pages”是临时产物，**回退**；若要长期保留，补齐 `scripts/test_deployment_workflows.py` 与文档一致性，并提交。
- [ ] 统一 README / `docs/dev/architecture-and-deployment.md` / `docs/design/deployment-architecture.md` 对 Pages 单次发布内容的描述（web+admin+jbrowse vs web+jbrowse demo）。
- [ ] 将 5 份未提交的 2026-08-14 spec/plan 文档纳入版本控制（它们是后续工作的批准基线）。

### 5.2 修复 outbox 任务契约（Phase 1 Task 1，但必须先做）

- [ ] 新增 `enqueue_task_event()`（校验 `task_name` 非空，payload 固定 `{task_name, kwargs}`）。
- [ ] 迁移 import/release 事件生产者使用新 helper；`create_import_command` payload 增加 `task_name=soymutdb_worker.tasks.ingest.run_import_adapter` 与 `kwargs`。
- [ ] `outbox_dispatcher.py`：malformed event（缺 `task_name` / `kwargs`）标记 `failed` 且 `last_error="missing task_name"`，**不得投递 Celery**。
- [ ] `release_service.py` 的 `release_pointer_changed` 事件要么改为可执行任务，要么从 dispatcher 跳过并显式分类（否则会被当作空任务投递）。
- [ ] 测试：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_outbox.py apps/api/tests/test_task_dispatch.py -q`

### 5.3 对齐 Widget 契约（Phase 2 Task 1 提前）

- [ ] 以 `apps/api/app/widgets/schemas.py` 为唯一契约源：Admin `widget-api.ts` 的 `WidgetCategory`/`WidgetPermission` 改为与 API 完全一致。
- [ ] 统一 list 响应为 `{items,total}`；health 二选一：改为 Admin 需要的逐 widget `p50/p95/cache_hit_rate/error_count/request_count/history`（推荐），或简化 Admin UI 到聚合形态。两处必须同一 shape。
- [ ] 修复 Admin `layout.tsx`/`widgets.tsx`/`widget-health.tsx` 对旧字段的消费。
- [ ] 测试：`pnpm --filter @soymutdb/admin typecheck` 与 `apps/api/.venv/bin/python -m pytest apps/api/tests/test_widget_registry.py apps/api/tests/test_openapi_contract.py -q`

### 5.4 修复 Admin content/publication 调用

- [ ] 新增显式 publication 管理端点（推荐 `GET/POST /api/v1/admin/publications` 与 `PUT/DELETE /api/v1/admin/publications/{id}`），或把 Admin publication tab 明确改为 Release 管理入口；不得继续调用不存在的 `/admin/content?type=publication`。
- [ ] 保留现有 `/admin/content/pages*` 静态页 CRUD/版本/发布能力，补齐 OpenAPI 契约测试。
- [ ] 测试：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_admin_uploads.py apps/api/tests/test_openapi_contract.py -q`

### 5.5 基线验证

- [ ] `git status` 干净（或仅含已决策的提交）。
- [ ] 后端：`apps/api/.venv/bin/python -m pytest apps/api/tests/test_release_service.py apps/api/tests/test_import_state_machine.py apps/api/tests/test_task_dispatch.py -q` 全绿。
- [ ] 前端：`pnpm --filter @soymutdb/admin typecheck`、`pnpm --filter @soymutdb/web typecheck` 通过。

---

## 6. Phase 1：Module TSV 导入地基

> 执行 `docs/superpowers/plans/2026-08-14-phase-1-module-tsv-import-foundation.md`。
> Phase 0 完成后，该计划的 Task 1 可视为已完成/合并，仍保留其测试。

- [ ] 创建 `apps/api/app/models/module_data.py`（`ModuleSchema`、`ModuleDataRow`、release-scoped 唯一约束）。
- [ ] 迁移 `0015_module_tsv_imports.py`：新表 + `ImportTaskType.MODULE_TSV` 枚举扩展；upgrade/downgrade 可逆。
- [ ] 实现 `module_schema_registry.py`：`genes` 等不可变 schema；`validate_tsv()` 校验 UTF-8/NUL/分隔符/表头/类型/唯一键/`end>=start`/行上限，返回有行号的诊断。
- [ ] 实现 `module_import_service.py`：事务性 staging + 幂等 checksum + 失败零泄漏 + 成功 enqueue `static_publish_requested`。
- [ ] `admin_modules.py`：`GET /admin/modules/{key}/template` 下载 schema 模板。
- [ ] `data_adapters.py`：新增 `ModuleTsvAdapter`，从 `CsvUpsertAdapter` 映射移除 `module_tsv`；不保留“计数即成功”路径。
- [ ] `ingest.py`：把 `update_import_progress` 从日志 stub 改为真实 `ImportTask` 状态/进度/错误/审计回写，所有转换走 `ImportStateMachine`。
- [ ] `admin_imports.py`：请求 schema 支持 `module_key/schema_version/release_id/object_key/checksum/idempotency_key`；未知 schema 422、非 admin 403；ImportTask + DataSet + outbox 同一事务。
- [ ] 验收：
  - [ ] `apps/api/.venv/bin/python -m pytest apps/api/tests/test_module_schema_registry.py apps/api/tests/test_module_import_service.py apps/api/tests/test_outbox.py apps/api/tests/test_task_dispatch.py -q`
  - [ ] `apps/api/.venv/bin/python -m pytest apps/worker/tests/test_data_adapters.py apps/worker/tests/test_ingest.py -q`
  - [ ] 一个故意非法的 TSV 不得改变 active release 或公开行。

---

## 7. Phase 2：安全 Admin 页面构建器

> 执行 `docs/superpowers/plans/2026-08-14-phase-2-admin-page-builder.md`。
> 其中 Task 1 已提前到 Phase 0。

- [ ] 迁移 `0016_page_builder.py`：`page_definitions` + `page_definition_versions`（唯一 `(page_id, version)`；published 版本不可变）。
- [ ] 组件注册表 `apps/api/app/page_builder/registry.py`：初始 allowlist `navigation/news_list/media_carousel/rich_text/tool_entries/assembly_select/gene_search_form/location_search_form/data_table/button/link/notice/divider/tabs/columns/jbrowse_launcher/blast_launcher`；每个条目只暴露 `config_model/allowed_children/data_binding_model/renderer_key`。
- [ ] 安全校验：未知组件/未知 props/`javascript:` URL/内联事件/raw script/任意模板名全部拒绝；rich_text 走现有服务端 sanitizer；链接仅 `http/https/内部路由白名单`。
- [ ] API：Admin CRUD + draft + preview + version list + `publish-request`（校验后发 `static_publish_requested` outbox，不直接改公开文件）；公开 `GET /page-definitions/{route:path}?version=...`。
- [ ] 共享 DTO：`packages/shared/src/page-builder.ts`；生成 client 契约后接入 Admin。
- [ ] Admin 三栏编辑器：组件 palette / 有序树 / schema 属性面板（只渲染 registry 声明的 text/translated text/boolean/number/select/safe link/module binding/action 控件）；预览用同 DTO + iframe/token，不注入可编辑脚本。
- [ ] 编辑器内嵌 Phase 1 的 schema 模板下载与 TSV 上传，显示行级诊断。
- [ ] Seed：五个导航项 + 七页初始 published definition（幂等）。
- [ ] 验收：
  - [ ] `apps/api/.venv/bin/python -m pytest apps/api/tests/test_page_builder_registry.py apps/api/tests/test_admin_page_builder.py apps/api/tests/test_page_definition_public.py -q`
  - [ ] `pnpm --filter @soymutdb/admin test -- --run`、`pnpm --filter @soymutdb/admin typecheck`、`pnpm --filter @soymutdb/admin lint`

---

## 8. Phase 3：不可变多目标静态发布

> 执行 `docs/superpowers/plans/2026-08-14-phase-3-static-multitarget-publication.md`。

- [ ] 迁移 `0017_static_publications.py`：`StaticPublication` 状态机 `requested/building/validating/deploying/published/failed/rolled_back`；target-scoped 单调 publication id；previous/rollback 关系；凭据只存环境/secret。
- [ ] Admin 端点：列目标、按请求选单一目标、查看 evidence、请求回滚。
- [ ] Snapshot release-aware：`GET /content/snapshot?release_id=...`（或 build API）；cache key 含 release + page-definition version；snapshot 内嵌 release_id/page version/source checksum/generated_at。
- [ ] SSG fresh-tree：构建到 `dist/releases/<release-id>/<manifest-digest>/`；`manifest.json` 记录每个相对路径 SHA-256 + release/page/app 元数据。
- [ ] `validate-static-tree.ts`：拒绝缺路由、多余文件、unsafe markup、断链、hash mismatch。
- [ ] 修复 `ssg-content.ts` 的 `cover_url`/slug 插值：统一转义 helper + URL 协议/主机白名单 + JSON script 转义 + slug 校验。
- [ ] 并发保护：target lease/行锁；晋升前比较 `publication_id` 与 target 最新请求，stale 任务标记 superseded；失败不改当前指针。
- [ ] `PublicationAdapter` 协议：`stage/verify/promote/rollback`；local 用新版本目录 + `os.replace` 切换 `current` symlink（fsync + manifest 校验）。
- [ ] GitHub Pages：`workflow_dispatch` 入参 `publication_id/artifact_url/manifest_digest`；下载 → 校验 digest → smoke → 单次完整 `gh-pages` commit → 更新 ref；API 轮询 run/deployment 并记录 commit/run id；生产构建必须有真实 HTTPS API origin。
- [ ] Cloudflare Pages：上传制品 → 轮询 deployment → 校验 URL+manifest → promote；account/project 与 token 分离，永不接受 TSV/页面定义输入。
- [ ] 静态/动态 release 绑定：生成页嵌入 release 元数据；`packages/api-client` 自动带 `X-SoyMutDB-Release`（或 `release_id` 查询参数）；API 校验并采用。
- [ ] 验收：
  - [ ] `apps/api/.venv/bin/python -m pytest apps/api/tests/test_content_snapshot.py apps/api/tests/test_release_service.py apps/api/tests/test_static_publications.py -q`
  - [ ] `apps/api/.venv/bin/python -m pytest apps/worker/tests/test_static_publish.py apps/worker/tests/test_publication_adapters.py -q`
  - [ ] `apps/api/.venv/bin/python scripts/test_deployment_workflows.py`
  - [ ] `pnpm --filter @soymutdb/web build`
  - [ ] 三目标产物 manifest 等价；失败/陈旧发布不换指针；回滚恢复既有验证产物。

---

## 9. Phase 4：公共 Web 布局渲染器与七页对齐

> 执行 `docs/superpowers/plans/2026-08-14-phase-4-public-web-layout-renderer.md`。

- [ ] `apps/web/src/page-builder/registry.tsx`：`COMPONENT_RENDERERS` 穷举映射 Phase 2 的判别联合类型；未知 key 开发态 error boundary、生产构建前拒绝。
- [ ] 导航由 PageDefinition 驱动：`SiteHeader` 移除硬编码 `NAV_ITEMS`；固定顺序 Home/Search/Tools/Latest News/Contact；保留不可变五项 fallback、active 态、键盘、移动抽屉、语言/主题/动画控制与 command palette。
- [ ] 全站 `Gbrowse/GBrowse` 文案改为 `JBrowse 2`；内部兼容路由名可保留。
- [ ] 首页重排：删除 `HomeHero`/`HomeStatsBar` 渲染（保留可复用 API client）；顶部 `lg:grid-cols-[2fr_3fr]`（左新闻 ≤5 / 右轮播 3–6）；五个任务入口顺序 Gene ID → Physical Location → JBrowse 2 → BLAST → Primer Design；底部 CMS sanitized 内容。
- [ ] Gene ID 搜索：route search 支持 `q/assembly/run`；URL 直达恢复并只执行一次；submit `window.open(..., "_blank", "noopener")`；列顺序 Assembly/Chromosome/Position/Mutation Feature/Gene ID/JBrowse 2；JBrowse 2 链接使用 base-aware helper。
- [ ] Location 搜索：route search 支持 `assembly/chromosome/start/end/run`；表单校验缺字段/`start<1`/`end<start`；新 tab 参数化提交；同六列顺序与 JBrowse 2 action。
- [ ] BLAST：默认/工具入口直达 `/blast` 完整表单；`/search/blast` 兼容重定向；结果列 assembly/query ID/coverage/e-value/Gene ID search action/JBrowse 2 action；跨链接 `noopener`。
- [ ] JBrowse 2 transfer 页与 Primer 保留专项逻辑；链接用 `import.meta.env.BASE_URL`/deployment helper 适配 GitHub Pages/Cloudflare 子路径。
- [ ] 连接 builder：SSG bootstrap 携带 release-pinned PageDefinition；版本匹配则免 refetch；动态刷新失败保留已校验的嵌入定义；新装 seed PDF 布局。
- [ ] 响应式/无障碍：桌面 1440、平板 900、移动 390 覆盖；单列顺序、焦点可见、键盘可用、表格横向滚动、无页面级横向溢出；axe 扫描 home/genes/location/blast/jbrowse。
- [ ] 验收：
  - [ ] `pnpm --filter @soymutdb/web test -- --run`
  - [ ] `pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint && pnpm --filter @soymutdb/web build`
  - [ ] `pnpm exec playwright test --config tests/e2e/playwright.config.ts tests/e2e/homepage.spec.ts tests/e2e/search.spec.ts tests/e2e/genes.spec.ts tests/e2e/accessibility.spec.ts`

---

## 10. Phase 5：端到端验收、回滚演练与收敛

- [ ] 端到端剧本：Admin 上传非法 TSV（应失败且零泄漏）→ 上传合法 `genes` TSV → import ready → page-builder 编辑并 publish-request → worker 构建制品 → validator 通过 → 发布到本地 symlink → Playwright smoke → 发布第二个版本 → 回滚到第一版。
- [ ] 并发剧本：同一 target 两个 publication 乱序完成，后请求者必须胜出，旧任务 superseded。
- [ ] 三目标验证：local/GitHub Pages/Cloudflare Pages 得到同一 manifest digest；各 adapter 的回滚路径分别演练（Cloudflare 用 mock）。
- [ ] 契约收敛：`pnpm --filter @soymutdb/api-client check:contract` 或等价 OpenAPI 生成更新；Admin/Web 无手写漂移。
- [ ] 文档收敛：更新 `README.md`、`docs/dev/architecture-and-deployment.md`、`docs/ops/data-import-and-release.md`、`docs/user/README.md`，写清新的导入→构建→发布→回滚路径与 Pages 决策。
- [ ] 清理：删除/标记 count-only CSV 适配器旧行为、遗留 `search.html`/Cloudflare `_headers`（按 `docs/dev` 清理范围）、统一 JBrowse 2 术语。
- [ ] 最终门：
  - [ ] `pnpm lint && pnpm typecheck && pnpm test`
  - [ ] `apps/api/.venv/bin/python -m pytest apps/api/tests apps/worker/tests -q`
  - [ ] `pnpm review`
  - [ ] `pnpm build:web && pnpm build:admin && pnpm build:ssg`

---

## 11. 风险与注意事项

1. **空 `task_name` 投递**：当前 dispatcher 会把缺失任务的 release/import 事件投成空任务，Phase 0 必须先修，否则所有后续 outbox 事件都不可信。
2. **迁移编号冲突**：现有 head 为 `0014`；新增必须顺延 `0015/0016/0017`，禁止重编号。
3. **Pages demo 改动未提交**：它删除了 Admin 的 Pages 发布，与 README/运维文档冲突；在 Phase 3 设计 GitHub Pages adapter 前必须冻结决策，避免“demo workflow”与“发布 adapter workflow”双轨漂移。
4. **Widget 契约双 shape**：如不先统一，页面构建器会继承错误契约并被 OpenAPI 门禁阻断。
5. **release-aware snapshot 是发布正确性的前提**：没有它，静态页“release 固定”目标无法验证。
6. **第三方平台最终一致性**：只承诺各平台能力内的原子切换；记录确认 deployment/commit id 与时间。
7. **现有测试基线**：若存在与本方案无关的历史失败，单独报告，不隐藏、不放宽。

---

## 12. 建议的第一周排期

| 日 | 工作 |
|---|---|
| D1 | Phase 0：提交/回退决策、outbox 修复、Widget/Admin 契约对齐、基线测试 |
| D2 | Phase 1：模型+迁移 0015、schema registry、TSV 校验测试 |
| D3 | Phase 1：事务导入服务、ModuleTsvAdapter、worker 状态回写、Admin 契约 |
| D4 | Phase 2 后端：迁移 0016、组件 registry、page-builder API、共享 DTO |
| D5 | Phase 2 Admin：三栏编辑器、预览、TSV 上传控件、seed；Phase 3 启动 publication 模型 0017 |
| D6–D10 | Phase 3：release-aware snapshot、fresh-tree SSG、manifest/validator、三 adapter、release 绑定 |
| D11–D15 | Phase 4：renderer、导航/首页、gene/location/blast/JBrowse 2 对齐、Playwright |
| D16+ | Phase 5：端到端、回滚演练、契约与文档收敛 |
