# SEO/GEO Wave 0 实施设计

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 状态：待域名与数据治理决策后实施。范围是 Public Web 的发布输入、URL、索引边界和验证门禁；不改变 Admin/API 的访问控制语义。本设计不宣称任何域名已获所有权。

## 目标与先决决策

Wave 0 先消除软 404、重复/错误 canonical 和可变数据构建，再谈富结果或 GEO。以下决策未确认时，制品只能按 preview/demo 输出 `noindex,nofollow`，不得生成 sitemap 或声明正式 canonical。

| 决策 | 需要负责人确认 | 结果 |
| --- | --- | --- |
| D1：正式站点 | HTTPS canonical origin、DNS/Pages/反向代理的控制权、是否根路径部署 | 自定义域名且 `VITE_BASE_URL=/` 是首选；若正式站点确为 GitHub Project Pages，则 canonical 必须是 `https://<owner>.github.io/<repo>/`，并接受项目页无法独立控制 origin 根 `/robots.txt` 的限制。 |
| D2：发布数据治理 | `publication_release_id`、内容负责人、撤稿 SLA、许可证/引用/来源字段 | `Release.id`/active alias 不能替代门户 `publication_release_id`；没有不可变 PublicationManifest 的实体一律不索引。 |
| D3：GEO 授权 | 是否允许检索、训练、缓存及日志保留；发布者/组织身份 | 决定后才生成 AI crawler 规则、`Organization` 和 `llms.txt`；robots 不是访问控制。 |

## 单一 URL 与路由策略

唯一输入为 `SOYMUTDB_SITE_URL`（仅 HTTPS origin）和 `VITE_BASE_URL`（规范化挂载路径）；`siteUrl = origin + basePath`。新增的 `public-url.ts` 只允许 `rl_publicUrl(path)` 生成绝对 canonical、OG URL、sitemap URL 与 robots 的 sitemap URL。移除 `soymutdb.org`、`SITE_BASE_URL` 和脚本各自拼接 URL 的默认值；release 模式拒绝 localhost、测试主机、查询串或 fragment。`SOYMUTDB_PUBLICATION_MODE=release|preview|demo` 与现有 UI deployment mode 分离，并纳入 Turbo 环境哈希。

| policy | 当前路由/模式 | 输出与抓取规则 |
| --- | --- | --- |
| `index` | `/`、`/about/`、`/guide/`、`/help/`、`/downloads/`、`/publications/`；合格的 `/news/`、`/news/:slug/`、`/samples/`、`/samples/:id/` | 仅 release snapshot 完整、页面实际生成且有审核事实时输出 `route/index.html`、`index,follow`、canonical 和 sitemap。 |
| `dynamic-eligible` | 后续 gene/release/entity 页面及上述 News/sample 详情 | 必须有稳定标识、所属 `publication_release_id`、标题/摘要、许可、来源/更新时间和 manifest 条目；否则不生成、不进 sitemap。 |
| `noindex` | `/browser/`（含参数）、`/search/**`、`/blast/`、`/compare/`、`/sra/`、`/tools/**`、`/analytics/`、`/seed-request/`、未审核的 `/genes/`、`/variants/` | 已知固定入口可生成 noindex 静态壳以保持 HTTP 200；不得进入 sitemap。 |
| `private` | `/login/`、`/analyses/**`、Admin、写 API | `noindex,nofollow` 且仍由认证/授权保护；不靠 robots 隐藏数据。 |
| `redirect` / `retired` | `/browse/`、历史 `*.html`、`/antd-pilot/` | 前两者 canonical 指向新 URL，平台支持时 301；GitHub Pages 仅保留 noindex 兼容页。pilot 不发布。 |
| `not-found` | 未列出的路径、已撤销且无兼容映射的实体 | 独立 `404.html`，HTTP 404、`noindex,follow`、无 SPA fallback。 |

根路径仍为 `dist/index.html`；其余 clean URL 一律为 `dist/<route>/index.html`，canonical 使用尾斜杠。旧 `.html` 仅作临时 noindex 跳转，内部链接和 sitemap 不再引用它。GitHub Pages 的 demo 不能据此成为正式索引站；未知 URL 必须由独立 `404.html` 返回 404，不能复制首页。

## 不可变发布输入

当前 `/content/snapshot?release_id=` 已能传入 release，但 snapshot 的缺省 active alias、`generate-samples.ts` 的 live `limit=200` 查询、以及缺失 `CONTENT_SNAPSHOT_URL` 时的跳过都不能作为 release SEO 输入。release 构建须消费 PublicationManifest 指定的不可变 snapshot，并校验：`publication_release_id`、引用的 dataset release、page-definition 版本、内容修订摘要、snapshot SHA-256、每类实体的完整计数/路由清单和构建 commit。

News 仅在快照声明列表完整、详情为当前可公开版本且输出数/摘要匹配时生成；有可见窗口或撤稿风险的条目不生成静态详情、不进 sitemap。样本和未来实体同理，禁止以隐式 200 条截断或“最新 API”补齐。快照/manifest 任一缺失或不匹配即 fail closed，不可降级为 active 数据或 fixture。

## 可拆票工作包

### W0-1：URL 契约与单一路由 policy（依赖 D1）

**文件。** 新增 `apps/web/src/lib/public-url.ts`、`apps/web/src/lib/seo-route-policy.ts`、`apps/web/src/lib/__tests__/public-url.test.ts`、`apps/web/src/lib/__tests__/seo-route-policy.test.ts`；修改 `apps/web/scripts/base-template.ts`、`apps/web/scripts/ssg-build.ts`、`apps/web/scripts/generate-samples.ts`、`apps/web/scripts/ssg-content.ts`、`turbo.json`。

**RED → GREEN。** 先写用例证明现有硬编码 canonical、base-path 丢失、release 接受测试 host、以及未分类路由都会失败；实现后断言每个 policy 有唯一 canonical/robots 行为，release URL 不含 `localhost`、`example`、query 或 fragment。

**验收。** `pnpm --filter @soymutdb/web exec vitest run src/lib/__tests__/public-url.test.ts src/lib/__tests__/seo-route-policy.test.ts`。

**回滚。** 未提升制品时撤销此包；已提升时通过 StaticPublication 回滚到上一份已验证 manifest，不手改 `gh-pages`，并保留旧 URL 的兼容映射。

### W0-2：clean URL、真实 404 与单一 SEO 产物管线（依赖 W0-1）

**文件。** 新增 `apps/web/scripts/generate-seo-artifacts.ts`、`apps/web/scripts/check-seo-artifact.ts`、`apps/web/scripts/__tests__/seo-contracts.test.ts`；修改 `apps/web/package.json`（顺序为 snapshot/各页面生成后再统一生成 SEO 产物）、`apps/web/scripts/base-template.ts`、`ssg-build.ts`、`generate-samples.ts`、`ssg-content.ts`、`apps/web/public/_redirects`、`.github/workflows/pages.yml`、`e2e/static-server.mjs`、`e2e/playwright-public.config.ts`；新增 `e2e/tests/seo-static.spec.ts`。

生成器是 `robots.txt`、`sitemap.xml`、`404.html` 和临时 legacy redirect 的唯一写入者；页面生成器只交 route manifest。检查器对每个 sitemap URL 读取本地制品并检查 200 对应文件、唯一 canonical、robots/noindex 边界、无测试 host、404 不含首页/SPA entry。Pages 发布直接使用生成的 `404.html`，删除现有 `cp index.html ./404.html`。

**RED → GREEN。** 以 flat `.html`、重复 sitemap、demo sitemap、未知路径返回首页、私有 URL 入 sitemap 的 fixture 先失败；clean `index.html` 树和独立 404 通过。**验收。** `pnpm --filter @soymutdb/web exec vitest run scripts/__tests__/seo-contracts.test.ts`，随后在已批准 release 环境运行 `pnpm --filter @soymutdb/web build`、`pnpm --filter @soymutdb/web exec tsx scripts/check-seo-artifact.ts`、`pnpm --dir e2e exec playwright test -c playwright-public.config.ts seo-static.spec.ts`。部署预览还须对一个 canonical URL 断言 200、未知 URL 断言 404。

**回滚。** 校验失败不 promote；线上异常回滚至上一 immutable artifact。不得恢复“首页充当 404”的行为。

### W0-3：release-pinned snapshot 与 News/entity 条件（依赖 D2）

**文件。** 修改 `apps/api/app/api/v1/content.py`、`apps/api/app/services/content_snapshot_service.py`、`apps/api/app/models/publication.py`、`apps/api/app/schemas/publication.py`、`apps/api/app/services/publication_service.py`、`apps/api/tests/test_content_snapshot.py`、`apps/api/tests/test_static_publications.py`；修改 `apps/web/scripts/fetch-content-snapshot.ts`、`apps/web/scripts/ssg-content.ts`、`apps/web/scripts/generate-samples.ts`、`apps/web/scripts/embed-page-definitions.ts`；新增 `apps/web/scripts/__tests__/snapshot-release-contract.test.ts`。通过现有 StaticPublication manifest 建模，不把 `Release.id` 改名冒充 publication id。

**RED → GREEN。** 用例先覆盖：缺 publication manifest、active-alias 回退、SHA/计数不一致、窗口 News、超出清单的 entity 都阻断；通过后只允许 manifest 中的 release-pinned 页面进入 route manifest。**验收。** `cd apps/api && .venv/bin/python -m pytest tests/test_content_snapshot.py -q` 与 `pnpm --filter @soymutdb/web exec vitest run scripts/__tests__/snapshot-release-contract.test.ts`，再运行 W0-2 的 build/check 命令。

**回滚。** 仅重新提升前一 PublicationManifest/制品；绝不以当前 active release 重新生成同一 canonical 页面。

### W0-4：发布门禁与 demo 隔离（依赖 W0-2、W0-3）

**文件。** 修改 `.github/workflows/ci.yml`、`.github/workflows/pages.yml`、`turbo.json`、`apps/web/scripts/check-seo-artifact.ts`；必要时更新 `docs/dev/architecture-and-deployment.md` 的发布命令说明。Project Pages 继续作为 demo 时明确设置 `SOYMUTDB_PUBLICATION_MODE=demo`，所有 HTML noindex 且不发布 sitemap；release 目标只能部署已校验的同一 artifact，不能“验摘要后再重建另一份”。

**RED → GREEN。** release job 缺 D1/D2 输入、demo 输出 sitemap、manifest 与静态树不一致、或 deploy 重建字节均失败；受保护的 release 环境只在检查器通过后 promote。**验收。** 运行 W0-2/3 命令，加 `git diff --check`；发布后保存 HTTP 200/404、canonical、robots 和 sitemap URL 清单作为 manifest 证据。

**回滚。** 调用已有 publication rollback，指向前一验证过的 artifact；不要 force-push 手工修补的页面树。

## JSON-LD、OG 与 GEO 的顺序

1. 完成 W0-1 至 W0-4 和事实治理后，模板先统一 title、description、canonical、`og:url`、Twitter fallback；OG image 仅使用获授权且稳定的资源。
2. 之后才增加可验证的 JSON-LD：全站 `WebSite`，经 D3 批准后的 `Organization`，再到 News 的 `NewsArticle` 和具备许可证、provenance、checksum、distribution 的 Dataset/DataDownload。`hreflang` 等待独立可抓取的语言 URL。
3. 最后由 `generate-seo-artifacts.ts` 在 release 制品写入 `llms.txt`（仅权威入口、版本、许可、引用方式）。它不是 ranking 或访问控制机制；demo/preview 不写。
4. AI crawler 规则最后落入经 D3 批准的 origin 根 `robots.txt` 和审计日志策略，按检索与训练用途分别决策。GitHub Project Pages 子路径无法单独提供 origin 根规则，因此未获正式 host 控制权前不承诺该策略生效。

以上顺序避免在错误 URL、可变数据或未授权内容上发布可被搜索/答案引擎引用的声明。
