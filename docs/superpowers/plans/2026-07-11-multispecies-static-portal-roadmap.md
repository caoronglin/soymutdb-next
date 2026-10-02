# 多物种静态科研门户升级改善计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SoyMutDB Next 演进为管理员可治理、发布可回滚、面向多物种、以静态站点与浏览器端搜索为主的科研数据门户。

**Architecture:** 保持现有 React/Vite SSG、FastAPI、Celery、PostgreSQL/Redis/ClickHouse 与可选 Rust 热路径的分层，不提前拆分微服务。新增受严格治理的管理控制面，将内容、模块、物种与发布配置固化为不可变 `release_id` 快照；公开端只服务同一快照构建出的 HTML、数据包和搜索索引。

**Tech Stack:** React 19、Vite、TanStack Router、Web Worker、FastAPI、SQLAlchemy/Alembic、PostgreSQL、Redis、Celery、Nginx/CDN、pnpm/Turbo、Playwright、`@alibaba-group/open-code-review`。

---

## 0. 已验证基线与范围

- 公开端入口为 `apps/web/src/main.tsx`，其产物通过 `apps/web/scripts/ssg-build.ts` 等脚本生成静态站点；公开页面不得直连数据库。
- 管理端是 `apps/admin` 的 React/Tauri 应用，必须保持 localhost / 内网限制；API 已有 `/admin/*` 边界。
- API 已存在 `Release`、`StaticPage`、`ContentVersion`，并已有 Widget 与 PageLayout 设计基础；它们可作为版本化发布和内容管理的起点，而不是另建平行系统。
- Web 已有 `apps/web/src/workers/search.worker.ts`，适合承载静态索引的离线过滤与排序；当前 `/search` 仍应保留外部来源结果的明确分区。
- 现有公开 UI 含大豆硬编码语义（如物种、组装、染色体）；本计划不将其他物种复制为另一套前端，而是先提取物种无关模型。
- 本文仅定义架构、路线、质量门与验收标准；不授权直接实施、迁移数据或变更生产配置。

## 1. 目标架构

```text
管理员控制面
  身份与权限 ─ 内容/导航/模块 ─ 物种/组装/数据集 ─ 技术情报审核
                         │
                         ▼
版本化领域与发布层
  Schema 校验 → 预览 → 审核 → release_id 快照 → 静态构建/索引 → 原子发布
                         │
                         ▼
公开静态数据面
  CDN/Nginx 静态 HTML + 版本化数据包 + JS/Web Worker 分片搜索索引
```

### 1.1 强制边界

1. **控制面与公开面分离**：管理员只能编辑结构化草稿并触发“预览 → 审核 → 发布”；不可直接改生产静态文件、数据库记录或 CDN 路径。
2. **发布原子性**：页面、导航、站点地图、下载清单、实体页与搜索索引必须共享一个 `release_id`；回滚指向历史不可变快照，而不是重新构建旧版本。
3. **物种无关内核**：`Species → Assembly → DatasetRelease → Gene / Variant / Line / Annotation / Evidence`。坐标、缓存键、URL、下载和索引分片必须带物种与组装范围。
4. **受约束配置**：管理员只能配置注册模块、JSON Schema 参数、顺序、范围与状态；禁止任意 JavaScript、模板表达式、未经净化的 HTML 或 CSS 注入。
5. **渐进增强**：静态页面、物种目录、站点地图和基础导航不依赖 JavaScript；Worker、远程检索或动态模块失效时给出明确降级状态。

### 1.2 管理员“全权限”的安全解释

管理员应拥有完整的业务控制能力，而不是绕过审计与发布流程的服务器权限。建议职责：

| 角色 | 能力 |
|---|---|
| Platform Owner | 管理管理员、权限策略、发布策略和密钥引用 |
| Data Steward | 管理物种、组装、数据集、导入验证与发布候选 |
| Content Editor | 编辑页面、导航、SEO、公告、模块配置和多语言内容 |
| Reviewer | 审核内容、数据与技术情报 |
| Publisher | 执行生产发布和回滚 |
| Auditor | 只读审计、发布和质量记录 |

高风险操作（权限提升、批量删除、生产发布、回滚）要求重新认证；审计记录追加保存且管理员不可篡改。若业务确需单一管理员，可将上述职责赋予同一受控账号，但不能跳过审计、预览与发布确认。

### 1.3 内容、模块与可见性模型

```text
PublicationManifest (release_id, schema_version, built_at)
 ├─ Site / NavigationPolicy
 ├─ Species / Assembly / DatasetRelease
 ├─ Page (route, locale, SEO, ordered ModuleInstance[])
 ├─ ModuleDefinition (registered type, config schema, accessibility contract)
 ├─ ModuleAvailability (scope, state, schedule, fallback copy)
 ├─ SearchManifest (shard URLs, content hashes, record counts)
 └─ Provenance / audit references
```

- `ModuleAvailability` 取代单一 `is_active`：范围为全局、物种、组装、数据发布或语言；状态为 Draft、Preview、Published、Hidden、Deprecated。
- 显隐规则仅支持声明式条件：范围、语言、发布状态、时间窗口、依赖数据是否可用；关闭模块时同时计算导航、首页入口、站点地图、搜索筛选和深链的影响。
- 每次编辑都显示生效方式：**即时运行时模块**、**需要重建搜索索引**、或**需要静态发布**；对 SSG 内容不得虚假承诺“保存即全站生效”。

### 1.4 静态 JavaScript 搜索

```text
发布数据快照 → Search Document Builder → 按物种/实体类型分片
 → 带 release_id、schema、hash 的压缩索引 → CDN
 → 浏览器按需下载 → Web Worker 查询 → 静态实体页
```

- 文档只保留公开展示与跳转所需字段，索引生成前执行字段白名单与敏感数据扫描。
- 首次只加载当前物种和当前语言的索引；跨物种搜索按需加载。优先级：精确 ID、前缀、别名、标题/描述。
- 结果始终显示物种、组装、数据发布版本、对象类型和搜索范围；将 NCBI/UniProt 等 API 结果放入单独的“外部来源”区，不与本地静态结果混淆。
- 当索引超过已定义的移动端下载、内存或延迟预算时，才以实际指标为依据引入只读搜索服务；在此之前不服务化。

### 1.5 UI/UX 信息架构

公共站点的永久上下文是“物种 + 组装 + 数据发布版本”，而非大豆默认值：

```text
/species
/species/:speciesId
/species/:speciesId/genes/:geneId
/species/:speciesId/variants/:variantId
/species/:speciesId/lines
/species/:speciesId/browser
/species/:speciesId/downloads
/search?scope=all|species&species=:speciesId&q=...
```

- 页头下设置 `SpeciesContextBar`；小屏压缩为可访问的展开控件。详情、下载和浏览器链接必须显式携带 `speciesId`、`assemblyId` 与发布版本。
- 主导航由已发布 `NavigationPolicy` 派生，而不再由 `apps/web/src/components/site-header.tsx` 的常量维护；模块无数据、未发布或下线时显示可解释状态，而非空白或死链。
- 管理端将现有分散的 Content、Widgets、Layout、Preview、Releases 工作流组织为两条主线：**Data Publishing** 与 **Public Experience**，并增加发布队列、影响预览、审计和回滚入口。
- 保留科学数据的密度与精确性：基因 ID / 坐标使用等宽字，物种徽章配合学名和文本状态；颜色不能作为唯一语义。移动端将宽表转为关键字段卡片并保留筛选、导出与详情能力。

### 1.6 技术栈情报域

```text
可信来源清单 → 定时采集适配器 → 原始证据隔离
 → 解析/去重/分类 → 候选条目 → 人工审核 → 技术雷达/规划建议
```

- 优先官方文档、官方 Release、标准组织、同行评议论文和官方仓库；知乎 skill 的检索结果可作为发现线索，但不能成为唯一技术决策依据。
- 每条候选保存来源 URL、发布时间、采集时间、内容哈希、解析器版本、适用范围、置信度、审核意见和最终状态。
- 外部数据是非可信输入：遵守 robots、许可和频率限制；净化 HTML，防范提示注入；不得自动升级依赖、修改配置、部署或公开发布。
- 当前仓库 `skills/` 未发现知乎/zhihu命名 skill；计划执行前必须在仓库技能目录显式声明实际使用的 skill。若需要知乎检索能力而本地 skill 缺失，应如实记录该缺口并改用已授权可信来源，不得伪称已经使用。

## 2. 分阶段路线与强制质量门

### 阶段 0：基线、治理与目标冻结

- [ ] 盘点大豆专属硬编码、现有页面/路由、数据源、搜索行为、管理员能力、数据许可与责任人。
- [ ] 固化术语表、权限矩阵、威胁模型、性能/可访问性基线，以及首个第二物种试点的选择标准。
- [ ] 在仓库技能目录中列出本阶段实际使用的规划、架构、UX、测试和技术情报 skill；记录知乎 skill 可用性。
- [ ] 使用 `ocr scan --path apps` 进行架构基线审查，并以 `ocr llm test` 验证审查环境；阻断级与高风险问题关闭后才进入阶段 1。

**完成标准：** 现状清单和 ADR 已评审；无新增大豆专属耦合；风险、责任人和基线指标可追溯。

### 阶段 1：版本化发布骨架

- [ ] 定义 `PublicationManifest`、`release_id`、预览、原子切换与基于历史快照的回滚策略。
- [ ] 保持现有页面行为不变，仅让内容、数据和构建产物能指向同一发布快照。
- [ ] 建立预览构建、完整性校验、发布审计、监控与回滚演练；公开站点不能依赖管理 API 可用性。
- [ ] 按第 3 节的固定 diff 命令运行 `ocr review`，并提供本计划作为审查背景，重点审查发布流水线、权限边界和供应链配置；配合 lint、typecheck、test、SSG build 与人工安全评审。

**完成标准：** 同一输入可重复生成等价静态输出；页面/索引/数据版本可自动验证一致；回滚达到事先定义的恢复目标。

### 阶段 2：内容与模块控制面

- [ ] 将导航、公告、SEO、首页区块、物种入口与模块显隐迁移到受 Schema 约束的配置，复用 `StaticPage` / `ContentVersion` 的版本化基础。
- [ ] 提供草稿、影响预览、审核、发布和审计；拒绝任意模板、脚本和未净化富文本。
- [ ] 使模块禁用同步影响导航、首页、站点地图、搜索筛选、深链与空状态；同时提供发布失败不替换当前版本的保障。
- [ ] 强制 `ocr review` 检查配置验证、授权、富文本净化和发布逻辑；再执行 XSS、越权、审计完整性、WCAG、SEO 和静态回归测试。

**完成标准：** 未审核配置不能上生产；任何模块状态在同一 `release_id` 下全站一致；管理员可说明一次变更何时生效及如何回滚。

### 阶段 3：多物种公开体验与静态搜索

- [ ] 将公共路由、标题、导航、筛选、详情、下载和浏览器链接改为显式物种/组装/发布版本上下文；短路由仅作为兼容入口。
- [ ] 先为 Gene、Variant、Line、Download、Guide 等高价值实体生成按物种/类型分片的静态索引；接入现有 Worker，并保留 Worker 不可用时的正确降级。
- [ ] 在公共端加入物种切换器、组装标签、模块可用性守卫、科学面包屑、搜索范围提示和外部来源隔离。
- [ ] 强制 `ocr review` 审查搜索索引生成、浏览器资源控制、数据泄露面与跨版本 URL；执行移动性能、离线、跨浏览器、键盘与屏幕阅读器验收。

**完成标准：** 用户可在两分钟内按指定物种找到目标基因或变异；搜索结果不会混淆本地与外部数据；小屏无主线程明显阻塞；静态索引无未公开字段。

### 阶段 4：物种无关数据核心与第二物种试点

- [ ] 提取 `Species`、`Assembly`、`DatasetRelease` 及核心实体关系；外部 ID 使用带命名空间的别名，坐标永远绑定物种和组装。
- [ ] 将大豆作为第一个适配器，以双读与自动差异比对证明现有关键页面、统计和搜索不退化。
- [ ] 接入一个许可清晰、规模可控的第二物种，验证无需复制页面、搜索或核心业务代码。
- [ ] 强制 `ocr review` 审查领域模型、迁移兼容性、数据隔离与缓存/索引命名；进行科学数据质量、来源/许可和跨物种隔离人工评审。

**完成标准：** 两个物种均在同一门户配置模型中运行；大豆结果不存在未解释差异；第二物种不产生平行前端实现。

### 阶段 5：技术情报闭环与证据驱动演进

- [ ] 从少量高可信来源建立采集器、原始证据保留、去重、审核队列和内部技术雷达。
- [ ] 将技术情报转换为候选架构决策和升级提示词，而不是自动变更；每条结论引用原始证据及人工审核状态。
- [ ] 在每次计划升级前，显式写出“最新技术栈检索来源、使用的仓库 skill、适用性、风险、迁移成本、仓库清理步骤”。
- [ ] 强制 `ocr review` 审查采集器安全、外部输入净化、凭据、速率限制和供应链链接；进行许可与提示注入专项人工检查。

**完成标准：** 任何技术选型均可追溯到来源和审核记录；采集失败不影响公开站点；无情报可自动触发升级、部署或发布。

### 阶段 6：按证据扩展

- [ ] 只有当索引体积、构建时间、发布频率、可靠性或组织边界的量化指标超出预算，才评估只读搜索服务、增量索引、对象存储清单、额外队列或服务拆分。
- [ ] 每项扩展先写 ADR，对比“优化现有模块化单体”和“新增服务”的成本、故障面、运维责任与回滚方案。
- [ ] 每个架构变更在合并前运行 `ocr review`；较大模块或迁移在发布前对实际变更边界运行 `ocr scan --path apps/api`、`ocr scan --path apps/web`、`ocr scan --path apps/admin` 或 `ocr scan --path infra`。

**完成标准：** 不因预测性扩张引入服务；每一项新增运行时组件均有量化触发理由、SLO、责任人和退出策略。

## 3. Alibaba Open Code Review 强制规则

1. 使用官方包 `@alibaba-group/open-code-review`，先运行 `ocr llm test` 验证 Provider；CI 凭据必须来自密钥管理，禁止提交 API Key。
2. 每个阶段的设计实现分支，在合并前必须运行：

   ```bash
   ocr review --from origin/main --to "$HEAD_SHA" --format json --audience agent
   ```

   CI checkout 必须具备完整 Git 历史（`fetch-depth: 0`），以保证 merge-base 可用。
3. 阶段 0、跨边界迁移、发布流水线、认证授权、搜索索引和外部采集器变更，除 diff review 外必须按受影响边界运行 `ocr scan --path apps/api`、`ocr scan --path apps/web`、`ocr scan --path apps/admin` 或 `ocr scan --path infra`。
4. OCR 报告必须与 lint、typecheck、单元/集成/E2E、构建、依赖/安全检查以及人工科研领域审查共同构成门禁；OCR 不能替代这些确定性验证。
5. 阻断级和高风险问题必须关闭；中风险问题必须有负责人、期限和正式风险接受记录。保留 JSON 结果、审查版本、模型和评审上下文，不保留密钥。
6. CI 若发布 PR 评论，采用官方示例的 `--from` / commit SHA 模式、失败重试与无法定位行号时的普通评论降级；不要让不可信 PR 代码在有密钥的环境中执行。

## 4. 全局验收清单

- [ ] 每个公开链接、下载、搜索结果和实体页均能标识物种、组装、数据发布版本、来源与引用信息。
- [ ] 管理员可在不写代码的情况下配置内容、导航、已注册模块的显示/隐藏、范围和排序，并能预览、审核、发布、回滚及审计。
- [ ] 静态门户在任一发布快照内不存在导航、页面、站点地图、数据包和搜索索引版本错配。
- [ ] JavaScript 搜索仅暴露公开字段；静态结果、远程结果、离线状态、范围和索引版本均清晰可见。
- [ ] 页面在键盘、屏幕阅读器、缩放、低带宽、移动端和 reduced-motion 偏好下保持核心发现与浏览能力。
- [ ] 多物种能力来自共享领域模型、配置和组件，而非复制 Soybean 页面；跨物种比较有明确同源与证据边界。
- [ ] 所有技术栈更新建议包含可信来源、仓库内所用 skill、适用性判断、风险/成本、实施前质量门和 `pnpm clean` / Makefile 清理检查。
- [ ] 每一阶段均留存 Alibaba Open Code Review、测试、构建、预览、发布和回滚证据。

## 5. 规划期仓库清理约束

在任何实际升级前后，检查并清理过期 `dist/`、`build/`、`target/`、coverage、缓存、临时审查报告和无引用索引产物；不得提交 `.env`、密钥或默认被 `.gitignore` 排除的本地 `skills/` 内容。优先使用现有 `pnpm clean`、Makefile `clean` / `clean-all`，并在删除前确认目标列表和当前发布版本不受影响。
