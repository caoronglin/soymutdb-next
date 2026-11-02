# 搜索与静态页面性能设计

日期：2026-10-13。状态：设计提案；本文中的性能数字是验收目标，尚未实测。

## 1. 当前代码与选型

- `apps/api/app/services/search_service.py` 已实现按来源分别推进的签名游标，并绑定查询、站点、release 与 assembly；同一 AsyncSession 内顺序执行查询。外站缓存隔离上述维度，内站绕过共享缓存。
- 全局搜索实际执行 gene、mutant_line、publication 三类查询；variant、phenotype 的枚举存在不代表这些来源已实现。
- migrations 0024、0027 已提供部分文本字段的 pg_trgm GIN 索引；先检查执行计划及实际部署索引，避免重复建设。
- `apps/web/scripts/generate-static-routes.ts` 当前复制应用壳、注入 head、生成路由和 sitemap；跳过动态实体路由，因此不能视为正文 SSG。
- `build-sites.ts` 已隔离两个站点的构建；保留 CSP、压缩、SW、release manifest 和 publication-time 字节校验流程。
- worker `tasks/static_pages.py` 已有独立的基因正文 HTML/JSON 生成；它未接入上述 web 构建链。当前先全量读取 genes，再按 1000 条切片，且 release_id 仅用于对象路径，未约束查询；必须先修复范围与内存，再推广公开详情生成。
- API 内容快照和前端 bootstrap 消费仍存在，但旧设计提到的 fetch-content-snapshot/ssg-content 构建脚本在当前树中缺失。worker 发布状态机和产物摘要已有实现，应补齐调用链与增量复用，不能另造一套发布机制。

可选方案：全动态查询实现成本低，但增加首屏和数据库负载；全量静态搜索索引使构建及客户端下载随数据增长；推荐 PostgreSQL 在线搜索＋公开正文增量静态生成。暂不新增搜索引擎，也不以 Redis 作为性能达标前提。

## 2. 搜索执行路径

### 查询分类

1. 完整公共标识符：精确 accession/public_id/curated alias 查询，使用 release、assembly 范围内的 B-tree。按实际谓词设计 lower 表达式索引；不能假设普通索引支持 lower 或任意 ILIKE。
2. 标识符补全：规范化字段的前缀匹配＋适合排序规则的索引；默认返回 8 条，硬上限 20，不查询长正文。客户端防抖 150 ms，取消过期请求并防止旧响应覆盖新响应。
3. 描述与文献：有界 pg_trgm 检索；短输入仅走精确/前缀，避免短词的 contains 全表匹配。全文 tsvector 作为独立评测候选，明确语言及中文检索质量后再启用，不能无评测替换原有召回。
4. 染色体区间：独立查询接口，必带 assembly 和 release。变异点位按 (release, assembly, chromosome, position, variant_id) 查询；基因区间重叠视计划采用 range/GiST。不能用字符串全文搜索代替坐标查询。
5. BLAST、远程来源和分析：独立异步任务/面板，不阻塞本地搜索首屏；远程失败与本地结果分开呈现。

精确 > 明确别名 > 前缀 > 文本，排序及 tie-breaker 固定。crosswalk 只使用有来源的关系。当前三个来源各取 limit+1 后归并，游标只推进实际输出的数据；保留兼容性。新版游标应显式绑定查询模式和排序版本，避免优化后解释旧游标时跳行。

默认每页 20、上限 100。结果给出 has_more；现有 total_count 是当前页计数，先保留旧契约，新版本用 returned_count 明确表达。全局精确总数/分面采用独立接口或预计算，不在每次翻页同步 COUNT 全表。不得删除现有 assembly 歧义提示；可改为各 assembly 有界存在性查询，精确计数按需获取。

以一个 READ ONLY REPEATABLE READ 事务内的 UNION ALL/分阶段查询为优化候选，让三类结果共享快照；现有顺序方案作为基线。禁止在一个 AsyncSession 上 gather。多个独立会话并行会增加连接占用及快照一致性成本，实测获益前不启用。

### 缓存与负载

公开响应缓存键必须包含：site、release、assembly、规范化查询、来源集合、模式、过滤、排序版本、游标、limit。只缓存经过外站 DTO 序列化的数据；内站鉴权后查询，private/no-store。

先以数据库索引达标，再评估有总字节上限的进程内 LRU/TTL；不同 worker 缓存允许不同命中率，正确性不能依赖它。发布通过新 release 键隔离，撤回通过 publication epoch 失效，并清理静态源及 CDN（若部署存在）。缓存不得让已撤回记录继续公开。

搜索、导出、构建采用独立并发预算。初始搜索 statement timeout 1 s、完整请求预算 2 s；超时返回明确错误，不伪装为零结果。日志只记录查询分类、耗时、行数和作用域，不记录原始查询及私有标识。

## 3. 静态页面分层

| 类型 | 生成方式 | 数据策略 |
| --- | --- | --- |
| 首页、帮助、发布说明、公开内容 | 生成有正文的 HTML | 绑定公开发布快照 |
| 公开基因、突变体、文献详情 | 分批生成 HTML＋最小页面 JSON | 优先重要实体，逐步覆盖；公共身份、assembly、release、provenance 可直接读到 |
| 搜索和筛选列表 | 预生成界面，结果 API 查询 | 任意搜索参数不生成页面，不索引组合 URL |
| 变异详情长尾、超大表、JBrowse | 按需查询，延迟加载 | 不预生成每条变异、不内嵌完整基因组文件 |
| 内站、管理、个人任务 | 公共代码壳＋鉴权 API | 不生成私有正文或私有 hydration 数据 |

已生成详情必须无 JS 可读核心事实、有效链接与 release/assembly；后续 React 对同一个初始 DOM hydrate。实现优先复用纯展示组件和构建数据 DTO；浏览器相关组件隔离。仅 head 注入或 noscript 提示不能计为正文生成成功。

公开详情以 release＋assembly＋公共标识形成无歧义链接。具体路径延续现有路由契约，用显式参数或版本化路径；不能擅自改旧 URL。稳定当前链接由发布指针解析，必要时走审计过的 redirect/alias。未生成的真实实体仍可通过既有 API 访问；未知实体应返回真实 404，不能全部回退为 200 壳。无正文实体不进入 sitemap。

## 4. 增量构建与发布

1. 数据发布生成只含公开字段的快照清单、实体摘要及依赖图。摘要输入包括 DTO、模板版本、公共配置、资源摘要、locale、release、assembly。
2. 一次构建固定一个不可变快照；按稳定 keyset 批量导出，每批初始 500 条，最多 2 个导出任务。避免逐实体 HTTP 请求及逐实体数据库查询。
3. 根据内容摘要重用未变 HTML/JSON，仅重建变更实体及依赖它的目录、发布统计。跨 release 重用仍必须摘要完全一致，不能复用旧 release 标签。
4. 默认最多 4 个渲染任务；队列有界、分批写盘，内存不随总实体数增长。模板变更可触发全量，但不要求重新读取不变的快照数据。
5. 在全新输出目录构建并移除删除项；验证缺失、重复、路径碰撞、内部字段泄漏、链接、CSP 和字节摘要后原子切换发布指针。失败继续服务上一份完整产物。
6. 保留现有最终处理顺序约束：所有 HTML/数据生成完成后更新 CSP，之后压缩/SW，再计算最终 release manifest；校验和必须覆盖最终发布字节。

正文页面不依赖图表或 JBrowse 的 JS。图表、编辑器、分析组件继续动态导入；所有真实图表依赖仍遵循 370 KiB 全依赖预算。SW 不预缓存全部实体页面/基因组文件，仅缓存有界公开资源，并按站点＋发布命名空间隔离；内站响应不进入共享缓存。

带内容 hash 的不可变 JS/JSON 可长期缓存；当前别名 HTML 必须再验证；版本化 HTML 只有确认不可变及撤回路径可立即失效时才采用长期缓存。sitemap 分片，robots 不替代权限控制。

## 5. 性能目标及实施验收

初始评测模型：同一台 8 核/32 GiB/NVMe 主机，100 万基因、10 万突变体、10 万文献、1 亿变异（含多个 release/assembly），50 个并发搜索连接。此模型是待准备的压测基准，不能假称仓库已有这些数据或已达标。

| 项目 | 初始目标 |
| --- | --- |
| 补全 / 精确查询 API P95 | ≤100 / 150 ms |
| 文本首屏 / 第 100 页 keyset P95 | ≤300 / 300 ms |
| 区间第一页 P95 | ≤300 ms，受范围及返回上限限制 |
| 静态正文同机 TTFB P95 | ≤100 ms，不含公网 RTT |
| 代表性详情移动端 LCP P75 | ≤2.5 s，注明网络与设备条件 |
| 1,000 个变更页面增量渲染 | ≤60 s，不含应用编译与全量校验 |
| 100,000 页面全量渲染 | ≤15 min，构建峰值 RSS ≤2 GiB |

分别报告冷/热缓存、并发、数据库连接峰值、CPU、I/O、索引大小、构建页数、读取行数、产物大小、阶段耗时。用 EXPLAIN (ANALYZE, BUFFERS) 评估真实 SQL；不以小样本 mock 或缓存命中掩盖慢查询。不把以上目标当成现有性能结论。

后续实施验收覆盖游标无重复遗漏、旧游标兼容、v4/v5 隔离、外站不可访问内部标识/未发布记录、搜索排序与召回、无 JS 正文、增量删除、撤回、崩溃保留旧版本、双站产物及缓存隔离。已执行的测试见下方证据；生产规模性能基准仍未执行。

实施顺序：先记录基线和验证索引；优化精确/补全及分页查询；落地公开快照与一个详情模板；扩展增量生成和原子发布；按真实瓶颈决定进一步缓存、分区及预聚合。搜索与 SSG 不以 S3、Redis 移除完成为前置条件。

官方依据：
- https://www.postgresql.org/docs/current/indexes-types.html
- https://www.postgresql.org/docs/current/pgtrgm.html
- https://www.postgresql.org/docs/current/using-explain.html

## 6. 执行证据

2026-10-13：隔离 PostgreSQL 16.15（127.0.0.1:55432/soymutdb_c2），Python 3.15.0，运行：

```sh
cd apps/api
SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_c2 \
PYTHONPATH=/mnt/data02/T25ronglin/code/web \
/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/api/bin/python \
  -m pytest tests/test_search.py tests/test_search_keyset.py \
  tests/test_search_contract.py tests/test_search_database_integration.py \
  tests/test_search_internal_http.py -q -p no:cacheprovider --tb=short
```

结果：51 passed，1 条开发安全配置 warning，2.95 s，exit 0。包含真实 PostgreSQL 查询与 HTTP 契约；不是生产规模压测，也不代表 PostgreSQL 18 容器验收。首次未提供测试数据库 URL 时走 Docker fixture，11 项 setup error；配置隔离数据库后全部实际执行，没有跳过。

同日：worker `_upload_gzipped` 改为 `gzip.compress(data, mtime=0)`，使相同输入的压缩字节可复现。主 Agent 已检查 diff，并运行 `.venv/bin/python -m pytest tests/test_static_page_compression.py tests/test_static_page_object_keys.py -q`：12 passed，0.37 s，exit 0。此结果仅证明压缩与对象键契约；HTML/JSON 内的 built_at 仍随构建变化，摘要复用及跳过上传尚未实现，不能据此声称整个增量构建已完成。

### 主 Agent 接手后的补充验收（2026-10-13）

- API 搜索索引：Python 3.15.0，隔离 PostgreSQL 16.15，
  `SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55433/trgm_migration_test`
  配合候选 API Python 运行 `pytest tests/test_search_identity_indexes.py -q -p no:cacheprovider`，
  **6 passed，1 条开发配置 warning，2.08 s**。覆盖离线 SQL、真实并发索引升级、重跑与降级。
  这证明索引有效及迁移可执行，不代表查询 P95 已达标。
- Worker：现有 `.venv` 运行 `pytest tests/test_static_page_scope.py tests/test_static_page_compression.py tests/test_static_page_object_keys.py -q -p no:cacheprovider`，
  **38 passed，0.43 s**。Python 3.15 worker 候选环境缺 pytest，未将它记为通过。
- Worker 真实 PostgreSQL：`SOYMUTDB_STATIC_TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:55432/soymutdb_c2`
  配合现有 `.venv` 运行 `pytest tests/test_static_page_postgres.py -q -p no:cacheprovider`，
  **3 passed，0.44 s**。每项使用独立 schema 并清理；证明发布版本筛选、同名不同 assembly 保留、
  空筛选、keyset 批次及只读 repeatable-read 快照内独立写入。不是整个构建的一致快照或原子发布。
- Web：现有 Vitest 执行 `src/lib/content-snapshot-build.test.ts`，**29 passed，0 skipped**。
  新增实际 `readBootstrap()` 验证：React 根节点清空后，根节点外的初始化数据仍可读取；
  缺少挂载节点的 shell 拒绝构建。正文仍由 createRoot 替换，尚未完成 React hydration。
- Charts：完整包测试 **84 passed**。真实 Chromium 使用新建 ChartFigure 探针，
  六类图表均实际绘制、数据更新改变像素、tooltip 返回原始值、卸载清除全部画布、重新挂载成功；
  无 pageerror、资产加载失败或 HTTP 错误。浏览器仍记录 CSP meta 的 frame-ancestors 警告，
  此次不等于部署响应头验收。修复包括字段编码、缩放 API、热图 palette 和气泡半径进入 size channel。
- 探针生产构建完整图表依赖为 **331585 B gzip**，370 KiB 门槛 **通过**，余量 47295 B。
  `scripts/chart_closure_budget.py` 按 manifest 校验 10 个实际 JS 文件的 SHA256，
  691 个依赖闭包模块、475 个引擎模块均归入产物。此为探针产物；最终双站正常路由产物仍需复验。
- Web `tsc --noEmit` 通过；worker 三个修改文件的 Ruff 检查通过。

剩余交付包含正常双站静态构建、增量删除/撤回与原子发布、生产规模搜索性能、
ClickHouse 全链路替换、MCP 最新依赖验收和 Python 3.15 完整运行/交付环境迁移。

### 正常双站产物验收（2026-10-13，后续执行）

正式 `apps/web/scripts/build-sites.ts` 使用 `/tmp/ssg-acceptance-snapshot.json` 公开测试快照，
`VITE_DEPLOYMENT_MODE=demo`、`SOYMUTDB_RELEASE_ID=1`、`SOYMUTDB_EMIT_GZ=1`，
构建 `dist/external` 与 `dist/internal`，exit 0。这是正常路由的验收产物，不是生产数据发布。

本次修复：

- 生成文件清单记录此步骤拥有的页面；文章从下份快照完全消失时，删除旧 HTML 及 gzip 副本。
  清单含非法路径时，在写入任何新页面前失败；不递归删除不属于此步骤的目录内容。
- 新闻链接携带部署前缀，在 `/news` 与 `/news/` 上解析一致；动态详情加入最终 sitemap，
  canonical 与 sitemap 保留部署前缀。可见窗口详情仍不生成。
- Webpack 图表清单仅将独立复制的 `sw.js` 模板留给后续生成步骤；若 `sw.js` 是编译 chunk，
  仍记录并强制匹配 SHA256。新增两项回归测试，未修改预算或编译资产防篡改规则。

验收结果：

- `python3 -m unittest scripts.test_chart_closure_budget -q`：**38 passed**。
- Web `vitest run src/lib/static-routes.test.ts src/lib/content-snapshot-build.test.ts`：
  **43 passed**（11 + 32），没有跳过；`tsc --noEmit` 通过。
- `bash scripts/check-bundle-size.sh apps/web/dist/external/assets`：**通过**；初始 JS 合计 166 KiB。
  内站独立 `chart_closure_budget.py --dist apps/web/dist/internal` 亦通过。
  两站完整图表依赖均 **331144 B gzip**，低于 378880 B，32 个编译 JS 均校验 SHA256。
- `SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh`：**通过**。
  额外私有字段测试值 `PRIVATE_SSG_SENTINEL_20261013` 未进入外站；内站没有公开快照文件。
- Chromium 无 JavaScript 访问 about、新闻详情和 publications，均看到真实 `<main>` 正文。
  新闻列表点击可到达详情；开启 JavaScript 后，模拟 API 返回 503，about 快照正文仍在
  React 组件中保留，初始化 JSON 位于根节点外，没有 pageerror。此为 React 接管，仍非 hydration。
- 外站 64 个、内站 61 个 gzip 副本逐个解压，与最终原始字节一致；动态新闻详情在 sitemap 中。
- 使用既有 `check_portal_variant` 逐个检查两份正常产物的 CSP/脚本 hash：**通过**。
  全目录检查首次报告 3 个失败，均来自历史探针留下的
  `apps/web/dist/index.html` 与根 `_headers`（未 finalize）。这两个旧生成文件已可逆备份到
  `/tmp/soymutdb-legacy-probe-m8ss0zdg`，不再混入正常双站输出；
  重跑 `check_artifact_headers.py --require-dual`：**4 个 header 文件检查通过，exit 0**。
- 本次静态构建相关 ESLint：0 error，4 个 build-script `console.log` warning。

尚未完成原子发布、生产规模性能基准、ClickHouse 替换或全栈依赖/Python 迁移。
