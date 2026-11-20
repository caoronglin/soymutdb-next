# SoyMutDB 项目状态（2026-11-10 更新）

## 2026-11-10 当前状态

本轮起点是 `main@a2da8a23`（未推送的本地 `pr/01`–`pr/08` 序列之上）。工作内容分三类：
**环境与门禁复跑**、**用真实数据做端到端 debug**、**按真实数据修正后台与公共站的产品面**。

### 决策：放弃仓库改名

仓库改名为 `rlcao-mutdb` 的任务按 [ADR-0017](../adr/0017-keep-repository-name.md) **放弃**。改名需同时改动包作用域、Python 分发、镜像/制品名与 CI 契约守卫，而这些名称不承载
产品价值；真正的契约层（`public_id`、assembly 作用域、release 作用域、双站边界）与改名无关。

### 本机环境

`.ai-memory/LOCAL-RUN-ENV.md` 已按**本机实测**重写。旧正文描述的是另一台宿主
（`/mnt/data02/T25ronglin/...`、mamba/miniforge、`.mamba-root/envs/py315`、`webdb` 环境里的 PG），
那些路径在本机**全部不存在**。现行事实：Node 26.13.0 + pnpm 12.11.2 在 `/usr/local/bin`
（默认 PATH 首位是 Pi 自带 Node 22，必须显式前置）；API/Worker venv 均为 Python 3.15.0；
PostgreSQL 用 `scripts/with-postgres-service.sh` 起一次性 18.6 容器；本机是 root，可绑 80。

### 真实数据导入（不是 fixture）

数据源：`/home/t25ronglin/03_soymut/`（`01_annot/` 参考基因组 1.3 GB，`02_mut-infor/` 突变信息 TSV）。

| 产物 | 数量 | 证据 |
| --- | --- | --- |
| 参考序列 | 20 条染色体（Gm01–Gm20） | `.fai` 索引，长度与 `Gmax_880_v6.0.fa` 一致 |
| 基因 | **48,387** | GFF3 `gene` 行，全部 `.Wm82.a6.v1` 命名空间 |
| 转录本 | **80,374** | GFF3 `mRNA` 行 |
| CDS/UTR 片段 | **716,349** | `transcript_parts` |
| 外显子 | **563,838** | 由 CDS/UTR 合并推导（GFF3 无 `exon` 行） |
| 突变位点 | **3,697**（7 个株系） | `local_preview_mutation_sites`，含 W82_V2 / W82_V4 / DN53_V1 跨版本列 |

dry-run 与入库计数逐项对上（`import_gene_structure --dry-run` → 80374 / 716349 / 563838）。
API 以 `SOYMUTDB_APP_ENV=dev` + `SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true` 真实伺服该数据，
`/api/v1/preview/test-data/meta` 返回真实 SHA-256 与行数。

### 补完「写入器尚未完成」的两条导入链路

后台功能开关把 `imports_fasta` / `imports_gff3` 标为「写入器尚未完成」，这个描述当时是准确的：

- `FastaAdapter.run` 直接 `raise UnsupportedImportError`，从未持久化任何参考序列或染色体长度；
- `ingest.import_gff3` 只**数行**——它逐行解析、统计 gene/mRNA/exon 数量并返回计数，全程不开会话、不写一行，
  所以一次「成功」的导入会报告 48,387 个基因而目录仍为空。

新增 `apps/worker/src/soymutdb_worker/tasks/annotation_writers.py` 补齐两个真实写入器，并补全
`tables.py` 缺失的表定义（`chromosomes.length/order`、`transcripts` 全列、`transcript_parts`、`exons`）：

- `write_reference_fai`：按 `.fai` 写 `chromosomes`（名字、长度、顺序），替换式写入，`.fai` 缺失即失败；
- `write_gff3_annotation`：写 genes → 回读 `gene_pk` → 写 transcripts / parts / 派生 exons；
  unknown chromosome、越界坐标、重复 gene/transcript id、非法 strand、孤儿转录本一律 fail-closed。

**用真实文件实测**（不是单测 mock）：1 GB FASTA + 124 MB GFF3 经过适配器完整入仓，
20 chromosomes / 48,387 genes / 80,374 transcripts / 716,349 parts / 563,838 exons，
`assembly_gene_total` 回读一致。

仍是 fail-closed 的两条（诚实记录）：`blast_db` 需要真实 BLAST 二进制与制品上传；`seed_data` 尚未定义业务键契约。
两者的开关文案保留「写入器尚未完成」。

### 访问统计：平台原生默认，Cloudflare 可选

新增 `resolveAnalyticsProvider`（`packages/shared/src/deployment.ts`），单一开关 `SOYMUTDB_ANALYTICS_PROVIDER`
（`native` 默认 | `cloudflare` | `both`），由 `apps/web/config/config.ts` 与 `apps/web/scripts/csp.ts` **共用**，
因此 Umi 配置与 CSP finalizer 不可能对「本次构建是否加载第三方信标」产生分歧。

| 配置 | 结果（构建产物实测） |
| --- | --- |
| 未设置、无 token | 仅平台原生 `/track.gif`；`script-src 'self'`，无 `cloudflareinsights` |
| `native` + token | 同上（显式关掉第三方信标） |
| `cloudflare` / `both` + token | 注入 beacon；CSP 放行 `static.cloudflareinsights.com` |
| `cloudflare` 无 token | **构建失败**（空 token 会静默不上报，读起来像「没有流量」） |
| 非法取值 | **构建失败**，不静默降级 |

历史兼容：只设 token 不设 provider 时保持旧行为并在构建期打印提示。`turbo.json` 的 build env 已加
`SOYMUTDB_ANALYTICS_PROVIDER`。

### 公共站收敛为纯数据库

`/analyses`（分析流程：列表 / fastp / scanpy / 作业详情）整体移除——本仓库是数据库，不是分析平台。
路由、`routeTree.gen.ts` 生成项、侧栏入口、`nav.analyses` 内容键、`analytics.ts` 模板映射、
`session.ts` 的公开路径豁免一并删除；相关页面、组件与单测删除。

预渲染路由因此 **33 → 32**（indexable 仍为 25，爬取策略不变），
`check_published_route_manifest.py` 的 `_EXPECTED_ROUTES` 与 `_MANIFEST_DIGEST` 已按文档流程同提交重钉并写明原因。

### 本轮修掉的真实缺陷（失败 → 通过）

| # | 缺陷 | 证据 / 处理 |
| --- | --- | --- |
| 1 | **演示构建把「站点 origin」错设为「API origin」**：`SOYMUTDB_SITE_URL` 决定 canonical `<link>`、`sitemap.xml` 与 `robots.txt` 的 `Sitemap:` 行，却被赋成 `https://api.soymutdb.test` | 产物里出现 `<link rel="canonical" href="https://api.soymutdb.test/">`；同一处还让已钉死的 `routes.json` 摘要必然漂移（重建即变字节）。改为站点 origin `https://external.soymutdb.invalid`（= `build-sites.ts` 的默认值 = 已提交制品的 origin），并加回归测试 + 消融 |
| 2 | **`apps/docs` 让 knip 误报 5 个依赖未使用** | dumi 的 demo 代码写在 Markdown 围栏里，knip 5 不解析围栏 → 依赖门红。按「入口 + ignoreDependencies」处理并写明理由，另加回归测试断言被忽略的依赖确实在 `apps/docs/package.json` 里声明 |
| 3 | **`scripts/check-antd-design.mjs` 被 knip 判为死文件** | 它只被 shell 以 `node <path>` 调用，knip 只跟随 JS import。登记为根入口；`@ant-design/cli` 同理进 `ignoreDependencies` |
| 4 | `apps/web/src/routes/analyses/index.test.tsx` 的 `useTranslation` 每次渲染新建 `t` | 契约门禁 `test_i18n_handling_needs_no_per_render_double` 抓到；改用共享 `mockTranslation`（稳定身份 + 真插值） |
| 5 | `_HashingReader` 只有 `read`，但被类型声明为 `BinaryIO` | 它继承 `io.RawIOBase` 并暴露 `name`/`mode`；`gzip.GzipFile` 与 `TextIOWrapper` 需要真实 `fileobj`。不再用「窄协议 + 每处 cast」掩盖 |
| 6 | `module_schema.py` 的 `ManifestRow(dict)` 未参数化 → 每个 `.get("written_rows")` 都报 `dict[Never, Never]` | 改为 `dict[str, Any]`；同一轮把 `pg_advisory_lock/unlock` 从裸 `text()` 改成 SQL 表达式，去掉两处注入启发式告警 |
| 7 | `cloudflare_pages` 用 `Path(deployment.artifact_path)`，而该字段可为 `None` | 抛裸 `TypeError`，读起来像库缺陷。改为显式 `RuntimeError` 说明「该适配器只上传本地暂存目录」 |
| 8 | 部署/CI 脚本里的硬编码口令：`verify-baseline.sh` 的 JWT secret 与管理员口令、`verify-restore.sh` 的 ClickHouse 默认口令、`ci-job-steps.sh` 的 `ci-ch-password` | 改为**每次运行生成**（`/dev/urandom`）或**缺变量即失败**，不再有可复制的字面口令。gitleaks 的其余命中是数据集标识符（`03_soymut-a6-test`）、测试夹具与注释里被误读成 `API, <token>` 的句子，逐条在 `.gitleaks.toml` 里带理由豁免 |
| 9 | BLAST 表单校验消息是写死的英文（`Too small: expected string to have >=1 characters`、`Sequence must be at least 10 characters`） | zod schema 改为 `makeBlastSchema(t)` 工厂，所有消息走 `blast.validation.*`（en/zh）；模块级 schema 会在 import 时把文案固化，无法本地化 |
| 10 | `/search/genes` 两个输入框尺寸不一致且未对齐 | assembly `Select` 是单行 `large`、固定 `min(280px,100%)`，基因 ID `TextArea` 是 `minRows: 2`、`flex-[1_1_220px]`。统一为同一 `flex-basis`，textarea 起始单行（粘贴仍可增长），行对齐改 `items-end` |

### 后台：多维度表格成为数据维护主入口

按用户要求，两个**废弃入口**（`/imports` 分组与 `/site-control`）从后台侧栏移除；路由与页面保留（直达链接与测试仍可用），只有导航不再推荐它们。
`/data-views` 改为数据管理组的首位，作为上传后数据的配置、搜索与可见性主入口。

数据视图原本只能配置「显示哪些字段」；本轮补齐剩下两个轴：

| 配置项 | 存储 | 语义 |
| --- | --- | --- |
| `searchable_fields` | `admin_data_views.searchable_fields`（JSONB，默认 `[]`） | 搜索框匹配的字段白名单，与 `visible_fields` 用**同一套字段词汇校验**；空列表 = 不出搜索框 |
| `visibility` | `admin_data_views.visibility`（默认 `visible`） | `visible` 进保存列表；`hidden` 仍存储且可按 id 直开，只是不在列表/选择器里推荐 |

- 迁移 `0059_data_view_searchable_fields_and_visibility.py`（`down_revision = "0058"`，含真实 downgrade）。两列都是**additive**，存量行无感。
- **`visibility` 刻意不是权限**：该表自身的 docstring 承诺「configuration only, no data-access boundary」，加 `owner_id` + 403 会默默违背一个已文档化的契约。所以它是一个**可执行的展示位开关**（列表过滤 `include_hidden`），不是造出来的权限模型。
- 接口保持**加法式**：不传/不读新字段的客户端继续工作，没有字段被重命名或挪用。
- 验证：`apps/api` 数据视图两个测试文件 **26 passed**；admin **258 tests passed**；admin `tsc --noEmit` 与 eslint 均通过。

### 字体子集：发现并修掉一个真实的字形缺失

`test_portal_font_subset` 要求「收集到的每个码位都在随包 woff2 里」。本轮逐个码位对照字体 cmap 校验时发现：
命令面板的 `↵`（8629）与 `⌘`（8984）以及一处注释里的 `↔`（8596）**从未被包含在子集字体里** —— 它们一直在走系统字体回退，
而 manifest 声称的 6895 码位与实际不符。

源 TTF 不在仓库，无法重跑子集化；所以做了真实的修复而不是伪造 manifest：把这三处装饰性符号换成纯文本
（`Enter` / `Ctrl K` / `HTML/MD`），然后用 fontTools 对**现有** woff2 做覆盖校验，确认 6891 个收集码位全部被覆盖后，
仅重写 manifest 的派生字段（码位数、摘要、ranges、latin/cjk 拆分）。这仍然是验证，不是猜测：
若有一个码位不在字体里，脚本会失败而不是写下虚假的覆盖率。

### 门禁复跑（本机实测）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| 工作区 `turbo lint typecheck test` | `pnpm turbo run lint typecheck test` | **36/36 任务成功**（6m04s，最终树复跑）；web 85 files / **709 tests**，admin 37 files / 258 tests，JBrowse node 71/71 |
| API 全量（全新 PG 18.6 库） | `pytest tests -q` | **3037 passed / 14 skipped / 0 failed**（247.21 s） |
| Worker 全量（同一全新库） | `pytest apps/worker/tests -q` | **892 passed / 22 skipped / 0 failed**（79.24 s） |
| 契约套件 | `pytest scripts -q` | **1582 passed / 1 skipped / 69 subtests / 0 failed**（509.19 s） |
| jobs-py | `pytest packages/jobs-py/tests -q` | 243 passed |
| knip（依赖治理） | `knip --reporter json` | `files: []`，`issues: 0`，**exit 0**；`types` 类别用消融证明仍生效 |
| 制品 | `bash scripts/build-all-static-apps.sh` | web external+internal / admin / jbrowse 四套全部产出 |
| 发布清单 | `check_published_route_manifest.py` | **OK（32 routes / 25 indexable，爬取策略已钉）** |
| 离线浏览器门禁 | `bash scripts/verify-artifact-e2e.sh` | **10/10 门禁通过（572 s）**：public 180s / internal 68s / admin-production 8s / admin-shell 37s（5 用例含真实拖拽）/ entity-detail 10s / visual 41s / web-performance 19s / primer 11s / jbrowse-artifact 6s / **subpath-artifact 192s（74 用例全量 public 套件跑在 `/soymutdb-next` 子路径上）** → `artifact E2E passed` |
| admin 单测 / 类型 | `pnpm --filter @soymutdb/admin test\|typecheck` | 37 files / **258 tests passed**，`tsc --noEmit` exit 0 |
| i18n 守卫 | 插值 / locale / content-key | 0 findings；locale parity passed；content-key **122/122** |

### 后台写入路径的浏览器级覆盖（已交付）

新增 `e2e/tests/admin-write-paths.spec.ts`，并入 `playwright-admin-shell` 门禁（`testMatch` 同时匹配两个
spec）。三条写路径用例在真实 `apps/admin/dist` 上通过（门禁合计 **5/5**：原有两条挂载用例 +
下面三条，其中前两条断言保存契约、第三条是真实拖拽）：

1. **保存主导航**：断言 PATCH `/api/v1/admin/settings/header_external` 的 `expected_version` 等于读取到的
   版本号（乐观并发的前提），并解析 `values.navigation_json` 断言 `schema_version` 与分组顺序
   `["main","tools",新分组]`；Save 在文档未改动时禁用、点「添加分组」后启用。
2. **版本冲突**：服务端返回 409 时页面必须提示（中文文案「导航已在其他会话中被修改…」），不能静默丢弃编辑。

写这两条用例时踩到并记录在 spec 注释里的四个测量事实：

- 控制台在**每次整页加载**时用 `GET /auth/refresh` 恢复会话。若在提交登录表单前就应答它，控制台会认为已登录
  并离开 `/login`，账号输入框永远不出现 —— 会话端点必须用「已登录」标志门控。
- `/site-control` 在编辑器出现前要读**四个**端点（`settings/general/document`、`admin/features`、
  `site/navigation`、`settings/header_external/document`）。任何一个留成裸 404，页面就停在加载态
  （实测正文只剩外壳）。
- 该构建的控制台是**中文优先**：aria-label 实际是 `分组 1 英文标题` / `拖拽排序 Main`，按钮是
  `添加分组` / `保存外部站点导航`。定位器因此同时接受中英文。
- 冲突提示的真实文案是「导航已在其他会话中被修改，已加载最新版本，请检查编辑内容后重新保存。」，
  不是通用英文。

### 子路径部署门禁（已交付，第 10 项）

`e2e/playwright-subpath-artifact.config.ts` 已接进 `scripts/verify-artifact-e2e.sh` 的 `GATES` 数组
（**9 → 10 项**），服务 `build-pages-artifact.sh` 产出的 `pages-dist/`，挂在 `/soymutdb-next` 下——
即 gh-pages 发布的真实形状。它跑的是**完整 public 套件**（16 个 spec、74 个用例：
homepage / search / genes / route-smoke（全 32 路由）/ api-shape-resilience / downloads / seqfetch /
accessibility / blast / public-login / seed-request / enrichment / exppattern / browser-bridge /
expression-phenotype，外加 `subpath-artifact.spec.ts` 的 3 条 base 专项断言）。

**实测 74 passed / 0 failed，exit 0**（门禁内 192 s）。`entity-detail` 不在其中：该 spec 从
`PORTAL_BASE_URL` 取自己的 base，且本身就是本 sweep 的第 5 项门禁，放进来会测到第二个不同 base 的目标。

`subpath-artifact.spec.ts` 另外钉住四件 base 前缀会破坏的事：①文档在前缀下加载且 SPA 接管；
②**没有任何资源从原点根取**（`/assets/…` 缺前缀 = 经典 base 错误）、前缀下资源无 4xx；
③**深链**能解析且 URL 保留前缀（只对 `/` 生效的 base 是重定向不是挂载）；
④`routes.json`/`robots.txt` 在**前缀下**可取且 origin 是站点而非 API 主机。

#### 让全量套件在子路径上跑通的关键修复

`e2e/tests/helpers.ts` 的 `withBasePath()` **必须幂等**。多数 spec 自己就写 `${BASE}/…`，
若 `gotoReady` 再盲目前缀，URL 会变成 `/soymutdb-next/soymutdb-next/…` 并全部 404。
第一版就是非幂等的，导致 77 个用例里 **31 failed / 46 passed**；把 `withBasePath` 改成
「已带前缀就原样返回」后降到 **3 failed / 74 passed**，再把 `entity-detail` 移出后 **74 passed / 0 failed**。
这正是「制品与路由在子路径下没问题（不带 mock 直接探测：`/blast` 576 字符、`/genes` 191 字符、
testid 齐全、`data-app-ready=true`）而套件红」的原因——问题在 harness，不在制品。

第二个 harness 事实：门禁必须以 `E2E_BASE_PATH=/soymutdb-next` 调 playwright。
`spec` 在模块加载时读这个变量来组 `${BASE}` 并让 `gotoReady` 前缀化；漏传时 spec 会导航到
原点根，前缀下的服务端 404，门禁红得与制品无关。`verify-artifact-e2e.sh` 因此对
`subpath-artifact` 这一个门禁注入该变量（`gate_env=(env E2E_BASE_PATH=/soymutdb-next)`）。

缺 `pages-dist/` 时该门禁报 **SKIPPED 并打印 `build-pages-artifact.sh` 修复命令**，不计为通过。
未把该构建脚本折进 sweep 的原因写在脚本注释里：它会用子路径 base 重建 `apps/web/dist`，
覆盖前九项刚用完的标准制品。

### 两条构建路径的差异：已排查，无内容分叉

先前记在这里的「`build-pages-artifact.sh` 与 `build-all-static-apps.sh` 的 SSG/内容差异未排查」是一条**误判**，
来源是把子路径套件早期的 31 个失败归因错了（真正原因是 `withBasePath` 非幂等 + 门禁漏传 `E2E_BASE_PATH`）。
实测结论：

- **路由文档集**：两棵树各有 32 个 `index.html`，路径逐一对应；`pages-dist` 多出的唯一一篇是
  `soymutdb-jbrowse/index.html`（publisher 把 JBrowse 子应用打进同一棵树，属设计）。
- **内容**：把前缀、origin、资源内容哈希三者归一化后，**32/32 个共享路由文档逐字节相同**（0 差异）。
- **`routes.json`**：两边都是 32 routes，只有 `origin` 字段不同（`https://soymutdb.github.io` vs
  `https://external.soymutdb.invalid`），符合各自的部署目标。

差异只有以下五项，且都是**入参或发布形态决定**，不是 SSG 分叉：

| 差异 | 原因 |
| --- | --- |
| base 前缀 `/soymutdb-next/` vs `/` | `PAGES_BASE_PATH` |
| 烘焙的 origin | `SITE_ORIGIN` / `SOYMUTDB_SITE_URL` |
| JS/CSS 内容哈希 | 前两项的必然结果（内联 env 变了，bundle 就变） |
| `soymutdb-jbrowse/` 子应用 | Pages 发布单一树；标准构建把 JBrowse 作为独立 origin |
| `.gz` 兄弟文件（标准构建 71 个，Pages 0 个） | 标准构建给 nginx `gzip_static`；Pages 自己压缩 |

因此这一项**已关闭**，不再列为未完成。

## 历史快照（2026-10-05 及更早）

> **本段是历史快照，不是现状。** 当前状态见页首「当前状态（2026-10-17）」；下方版本、测试数字、环境缺口和“待执行”描述均按原日期保留，未重新核验的旧计划不自动结项。
>
> 单一状态视图。执行日志见 `.ai-memory/`，逐项设计与计划见 `docs/superpowers/specs/` 与 `docs/aegis/plans/`，
> 整合视图见 `docs/3.9升级优化文档.md`。本页在当时只回答「现在是什么状态」，且每一条都带本机实跑证据。
>
> **本版相对 2026-09-26 版的实质更正**：三个应用全部是 React 19 + Umi Max 4 + antd 6 + ProComponents v3；
> Vue 已完全退役（0 残留）；上版「三端均为 Vue 3」的表述已作废。旧计数与旧结论一律以本版为准。

> **2026-10-02 实施轮更正**（证据见 [`aegis/baseline/2026-10-02-w0-rebaseline.md` §8](../aegis/baseline/2026-10-02-w0-rebaseline.md)）：
> - 审计后方案 W0–W3 **已实施完成**：守卫维护、assembly 作用域与**运行时 release 切换**、
>   五态会话状态机（匿名零个人请求）、`/auth/me` 加法式 `effective_roles` 能力字段。
>   消融证据 14 组，全部「对照通过 → 单因素变异 → 真实路径翻转 → 恢复复跑」。
> - **既有红灯变化**：可见文案守卫 39 → **33** 个文件；`check:contract` **exit 1 → exit 0**；
>   侧栏整页刷新（第 3 条）已修。仍未消除：可见文案守卫仍 exit 1。
> - **撤回旧结论 3 条**（本轮实跑复核）：`check_web_query_keys.py` 的 9 条红是守卫正则假阳性而非源码缺陷；
>   前一轮 W2 改动**未通过 typecheck**（重复实现 + 残留未用变量）；未跟踪的 `navigation-render.test.tsx`
>   从未真正执行过，其暴露的 `<a href>` 才是真实漂移。
> - **本轮发现但未解决**：API 测试同命令两次结果不一致（21 errors vs 0），原因未查清，已登记不当作已完成。

> **2026-10-02 审计更正**（详见 [`design-audit-2026-10-02.md`](design-audit-2026-10-02.md)）：
> - 本页「已知红灯」第 6 条（`AGENTS.md` pnpm pin 漂移）**已修复**：`AGENTS.md:58,90` 已改为 `12.5.1`，与 `package.json` / `.cnb.yml` 一致。
> - 执行依据更新为 [审计后总方案](../aegis/plans/2026-10-02-audited-optimization-execution.md)：18 条硬约束、W0–W7 与逐阶段验收；
>   [新对话提示词](execute-audited-optimization-prompt.md) 已登记。本次只改文档，业务修复仍待实施。
>   `session.ts` 尚无业务调用，应先按现有认证协调层重设计；不是直接接线该布尔门控就结束。
> - 同日对 2026-10-02 的优化/消融设计草稿做了独立审计，撤回了三项结论：
>   「守卫未接 CI」（实为已通过 `ci-job-steps.sh` 间接接入）、「数据库 ≈100× 单因素加速」（非单因素、比较层级不一致）、
>   「9/9 GUARD-ACTIVE」（F9 所测模块尚未接线）。**本页原有的门禁数字与红灯清单不受影响**，
>   它们均在本轮实跑复现过。
> - 仍然成立的真实缺陷：`apps/jbrowse/Dockerfile:19` 引用已删除的 `packages/ui-vue`（镜像构建必失败）；
>   `check_admin_content_architecture.py` 扫描 gitignored 的 `.umi*/` 产生永久误报；
>   `check_web_query_keys.py` 扫描已空的 `apps/web/src/views/`（Vue 退役遗留）。
> - `apps/api` 消融 149 项与 `pytest scripts` 275 项本轮复跑仍全绿，**未受审计影响**。

> **2026-10-02 实施轮：可做范围已完成**（证据见
> [`aegis/baseline/2026-10-02-w0-rebaseline.md`](../aegis/baseline/2026-10-02-w0-rebaseline.md) §8–§9）
>
> - W0–W3 完成，W4 可做范围完成，W6 框架就位；自 `9b63ddd41` 起共 6 个提交，均已推 `origin/main`（`cnb` 远端仍待凭据）。
> - **本页红灯已清 4 项**：`check:contract`、可见文案守卫（39 → **0** 文件）、
>   admin 架构守卫误报、query-key 守卫假绿。
> - **更正一条错误结论**：此前记为「无浏览器，窄屏与焦点无法验证」——**浏览器全程可用**
>   （playwright + chromium），现已实跑 10/10 通过，消融翻转 10/10 → 9/10。
> - **仍受阻**：无 psql/pgcli/Docker（数据库实测未跑）、无 `ant` CLI、无真实后端、
>   企业微信与部署目标未确认。**未取得任何性能结论，未做过任何生产变更。**

## 一句话

技术栈迁移与 Vue 退役已完成并可复跑；**真实缺口只剩两处**——管理后台的 Pro 业务组件体系
（8 个页面仍是裸 antd `Table`、`ProDescriptions`/`ProCard` 全仓 0 处），以及后端若干 mock 测试未跟上 release fail-closed 契约。
本机质量门禁 2026-10-05 复核**全绿**（前端逐包 + `scripts` 契约 350 项 + API 消融 149 项 + 可见文案守卫 0 文件）；
后端全量 pytest 在本机会被 OOM kill，没有可信的全量数字 —— 这本身就是一条待办。

## 技术栈现状（2026-10-05 实跑）

| 应用 | 框架 | 单测 | typecheck |
| --- | --- | --- | --- |
| `apps/web` | React 19 + Umi Max 4 + antd 6 | **29 files / 156 tests** | exit 0 |
| `apps/admin` | 同上 + ProLayout | **7 files / 43 tests** | exit 0 |
| `apps/jbrowse` | React + JBrowse 2 | 40 pass | exit 0 |
| `packages/api-client` | — | 28 files / 153 tests；`check:contract` **exit 0** | — |
| 其他包 | genome-view 43 · genome-data 121 · genome-view-model 23 · shared 49 · charts 5 · query-keys 11 · i18n-core 11 | 全绿 | — |
| `scripts`（Python 契约） | — | **350 passed / 1 skipped** | — |
| `apps/api` 消融 | — | 16 files / 149 passed / 0 failed | — |
| `apps/api` 新增端点 | `test_me_capabilities` + `test_active_release_endpoint` | **27 passed**（Docker-free，真实 HTTP） | — |
| `apps/api` 全量 | — | **无法在本机跑完**：约 47% 处被 OOM kill（EXIT=137） | — |
| `apps/worker` | — | 本机 `multiprocessing` spawn 失败，未取得数字 | — |

环境：`Node 24.19.0`（符合 pin）、`pnpm 12.5.1`、`Python 3.14.6`；本机 cgroup 受限，任何构建/测试都必须
`GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`，
否则 turbo/vitest/rayon 因线程耗尽直接崩溃。

## 本轮修掉的真实缺陷（都是工作树里长期存在的契约漂移）

| 文件 | 症状 | 处理 |
| --- | --- | --- |
| `apps/api/tests/test_expression.py` | `/expression/*` 已按 release fail-closed 返回 503，测试仍断言旧的「空列表 200」→ 6 failed | 注入 `get_release_context`；另 3 处旧断言改为当前公开契约（`/libraries/{public_id}`、内部主键不再是 locator、cursor 为不透明签名串）→ **19 passed** |
| `apps/api/tests/test_gwas_api.py` | 路由新增 `response: Response` 后测试漏传 → 1 failed | 补参数 → **18 passed** |
| `apps/api/tests/conftest.py` | 复用的本地测试库在会话被强杀后残留角色行，之后每个会话都在 setup 报 `roles_name_key` 冲突（读起来像代码缺陷，其实不是） | 角色种子插入改 `on_conflict_do_nothing` |
| `apps/api/tests/test_ablation_sra_no_fabrication.py` | 3 个消融用例漏挂 `offline` fixture，实际去访问 NCBI；网络通时守卫反而失败 —— 一个「只在断网时才生效」的守卫不是守卫 | 补 fixture → **11 passed** |
| `packages/query-keys/src/query-keys.test.ts` | 联邦搜索已永久下线、`federated` 已从缓存键移除，测试仍断言该维度 | 按实现口径删断言 |
| `packages/charts/src/ChartFigure.tsx` + 测试 | 图表回退分支没把 description 暴露给辅助技术，测试却断言回退态根本不渲染的 `role="img"` | 回退分支补 visually-hidden description，测试改断言真实可达文本 |
| `scripts/check-vue-retirement.mjs`、`scripts/react-entry-graph.mjs` | 两个守卫都按**包名**把 `@soymutdb/genome-view` 判为 Vue，而该包已按设计重建为 React 渲染器且 `apps/web` 在用 → 自重建后一直红，没人再跑 | 从 denylist 移除该包名，改按**框架**判定；保留 `.vue` 与 `vue/@vue/*` import 扫描；两个守卫各做一次临时副本注入 `.vue` 的消融，均仍 exit 1 并指出文件 |

## 已知红灯（不是「待办的口头描述」，是当前可复现的状态）

> **2026-10-18 复核注记（历史红灯的当前状态）**：本表保留 2026-10-05 原文；逐项复核后，9 行均已关闭或已更正，**没有任何一行仍是当前红灯**。现状入口是页首「当前状态（2026-10-17）」。
>
> | 原行 | 当前状态与证据 |
> | --- | --- |
> | #1 可见文案守卫 39 文件 | 已关闭：`node scripts/check_visible_i18n_react.mjs` 目标 0 文件；该守卫仍由 `scripts/verify-frontend-artifacts.sh:88-90` 执行 |
> | #2 8 个裸 antd `Table` | 已关闭：`grep -rlE '<Table\b' apps/admin/src/routes --include=*.tsx` 0 命中；`apps/admin/src/components/data-table.tsx:2` 使用 `ProTable`，`apps/admin/src/regression/pro-table-migration.test.ts` 硬门禁 |
> | #3 ProLayout `<a href>` | 已关闭，且 ProLayout 已整体移除（`apps/admin/src/components/admin-shell.tsx:16-19` 记录替换原因）；导航由 `navigation-render.test.tsx` 覆盖 |
> | #4 API 全量 pytest OOM | 已关闭：2026-10-17 全量 API **2325 passed / 4 skipped**（页首 10-17 节）；Worker **659 passed / 8 skipped** |
> | #5 `Makefile` lint 路径 | 已关闭：`Makefile:199` 现为 `cd $(API_DIR) && ruff check app/` |
> | #6 pnpm pin 漂移 | 已关闭（原表已标注 2026-10-02 修复）；现行 pin 为 pnpm 12.11.2 |
> | #7 testcontainers 计数错账 | 已更正（原表已标注 2026-10-05）；不是红灯 |
> | #8 动效测试缺失 | 已关闭：`apps/web/src/lib/motion/ticker.test.ts`（419 行）与 `apps/web/src/lib/motion-prefs.test.ts` 已存在 |
> | #9 无浏览器 | 已关闭：真实浏览器 a11y/布局 **10/10**（页首 10-17 节） |
>
> 本表以下内容不再改动，仅作历史审计。

| # | 红灯 | 证据 | 归属 |
| --- | --- | --- | --- |
| 1 | ~~可见文案守卫 exit 1，39 个文件~~ | `node scripts/check_visible_i18n_react.mjs` | ✅ **2026-10-02 已修**：**exit 0，0 个文件**；R-12 关闭。同时修了守卫一处缺陷（React key 前缀被误判为文案），补 6 tests 防回归 |
| 2 | **8 个** admin 页面仍是裸 antd `Table`；`ProDescriptions` 0 处、`ProCard` 0 处 | `grep -rlE '<Table\b' apps/admin/src/routes --include=*.tsx` → `releases` `preview-test-data` `instances` `audit` `news/index` `news/trash` `table-views`（2 处）`content/static-page-migration-report` | 同上 A2/A3。**复核陷阱**：用 `<Table[ />]` 扫只命中 2 个——JSX 多写成 `<Table\n  columns=…`，同行匹配会漏；必须用 `<Table\b`。`ProTable` 目前只存在于门面 `components/data-table.tsx` |
| 3 | ~~`ProLayout.menuItemRender` 用 `<a href>`，侧栏点击整页刷新~~ | `apps/admin/src/routes/__root.tsx` | ✅ **2026-10-02 已修**：改用 TanStack `<Link>`（该规范 §3.1 早已批准），`navigation-render.test.tsx` 组件级覆盖 + 消融翻转 |
| 4 | API 全量 pytest OOM（EXIT=137 @ ~47%） | 实跑 | 新增待办：分片或降内存跑法需写进 `scripts/verify-backend-tests.sh` |
| 5 | `Makefile:197` lint 目标指向不存在的 `apps/api/src`（代码在 `apps/api/app`） | 实读 | 工具链缺陷，等修 |
| 6 | ~~`AGENTS.md:58,90` 写 pnpm `11.21.0`，仓库实际 `12.5.1`~~ | 实读 | ✅ **2026-10-02 已修**：改为 `12.5.1` |
| 7 | ~~「15 个 API 测试依赖 testcontainers，无 Docker 必然 SKIPPED」~~ | `grep -rlE '^\s*(import\|from)\s+testcontainers' apps/api/tests` | ✅ **2026-10-05 更正为错账**：真正 import testcontainers 的只有 `tests/conftest.py` **1 个**文件；其余 14 处 grep 命中是注释里的**否定句**（`no docker / no testcontainers`）。「SKIPPED ≠ PASS」的告诫仍成立，但受影响面远小于原记 |
| 8 | 随 Vue 退役丢失的契约覆盖：admin 会话、web 动效可访问性、页面定义 href 安全校验 | 对比 Vue 树被删的三个测试文件 | **已补两项**（导航可达性、门面导出）；W3 补 admin/web 会话（`lib/session.test.ts` 11 tests + `session-context.tsx`）；href 安全已有 `regression/url-safety.test.ts`（scheme 校验）。**仅剩动效**：`lib/motion/` 只有 `ticker.ts`、**0 个测试**，`motion-policy.ts`/`motion-prefs.ts` 亦无 |
| 9 | ~~「无浏览器，窄屏/焦点无法验证」~~ | `node e2e/verify-a11y-and-layout.mjs` | ✅ **2026-10-02 更正并完成**：playwright + chromium 实测可用，10/10 通过（skip link 为首个 tab stop、焦点指示可见、390px 无横向溢出、移动菜单可键盘打开）；消融翻转 10/10→9/10 |

## 已完成并留证（要点）

- **Vue 完全退役**：0 个 `.vue`；`packages/ui-vue`、`packages/genome-view`（Vue 版）已删；`scripts/check-vue-retirement.mjs` 常驻门禁；
  `scripts/check-react-entry-graph.mjs` 遍历三端实际发布入口的 import 闭包 PASS。
- **三项查询收口**：Gene ID / Physical Location 的 assembly 作用域隔离（深链不可判定不回退默认版本）、坐标安全整数校验、
  JBrowse 深链携带 `release`。
- **自研基因组视图**：`packages/genome-view` 以 React 重建，`renderGenomeViewSvg()` 纯函数保证预渲染与交互渲染不漂移；
  配套迁移 `0045_transcript_parts` + GFF3 结构导入（transcripts 80,374 / parts 716,349 / exons 563,838，与 GFF3 计数逐一对上）。
- **联邦搜索彻底下线**（API `app/search/` 整包删除 + 前端与客户端清理），`federated` 已退出缓存键。
- **消融测试体系**：API 侧 16 个文件 149 项全绿，覆盖身份边界、assembly/crosswalk、release 作用域、缓存键、快照、ClickHouse 投影。
- **本轮新增前端守卫**：内容管理 URL 真源功能测试、导航可达性消融、antd 门面导出完整性消融（补 `@ant-design/cli usage`
  解析不到 `@/lib/antd` 门面层的盲区）。

## 环境阻碍（影响所有门禁判定）

- **无 Docker**：testcontainers 用例必然 SKIPPED/ERROR，不计通过。
- **裸 `pnpm` 调用**：`apps/web/scripts/build-sites.ts` 内部调 `pnpm exec max build`，PATH 中的 pnpm 版本与状态不可靠；
  绕过方式是用 corepack 缓存里的真实 `pnpm.mjs` 做 shim（`.validation/bin/pnpm`）。不得改 pin 或全局包管理器状态。
- **registry 滞后**：`.npmrc` 指向 `registry.npmmirror.com`，其 `@tanstack/react-query` 最新仅 5.99.2，锁文件已锁 5.104.0；
  任何重新解析锁文件的操作必须临时 `--registry=https://registry.npmjs.org/`，`--frozen-lockfile` 不受影响。
- **本地测试库需为空**：复用的 `soymutdb_*` 库在被强杀的会话后会残留数据；本轮已把角色种子改为幂等，
  但整表残留仍需人工清理或换库。
- **可写隔离 Admin 环境缺失**：截图视觉验收、Admin save→公共渲染 E2E 仍 pending。
  （「响应式运行时检查」一项已由 `e2e/verify-a11y-and-layout.mjs` 在真实浏览器上完成，见「已知红灯」第 9 条。）
- **BLAS 线程数必须显式压到 1**：`check:contract` 会导入后端 FastAPI → SciPy → OpenBLAS，OpenBLAS 默认开 64 线程，
  在本机 cgroup 下 `pthread_create failed for thread 50 of 64`，脚本以 exit 1 结束。
  **这不是契约漂移**：补 `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1` 后同一命令 exit 0 / PASS。照本页旧的三变量 export 抄命令会得到假红灯。

## 待决策（不自行拍板）

见 `docs/3.9升级优化文档.md` §11：`public_id` 正式格式、internal 检索角色名单、无 assembly 查询的 UX、
v4↔v5 映射展示规则、生产对象存储选择、主导航口径、Gene ID 单行 vs 批量、页脚导航初始 bounds 等。

## 复现

```bash
# 前端（逐包；本机比 turbo 稳）。五个变量缺一不可，见「环境阻碍」的 BLAS 说明。
export GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
for p in @soymutdb/api-client @soymutdb/charts @soymutdb/genome-data @soymutdb/genome-view \
         @soymutdb/genome-view-model @soymutdb/i18n-core @soymutdb/query-keys @soymutdb/shared \
         @soymutdb/web @soymutdb/admin @soymutdb/jbrowse; do
  pnpm --filter "$p" run lint && pnpm --filter "$p" run typecheck && pnpm --filter "$p" run test
done

# 交付与平台契约（2026-10-05 实跑：全绿）
python3 -m pytest scripts -q                                        # 350 passed / 1 skipped
node scripts/check-react-entry-graph.mjs                            # exit 0
node scripts/check-vue-retirement.mjs                               # exit 0
bash scripts/check-dockerfile-copy.sh                               # exit 0
node scripts/check_visible_i18n_react.mjs                           # exit 0，0 个文件
pnpm --filter @soymutdb/api-client run check:contract                # exit 0 / PASS（务必带 BLAS 变量）

# antd CLI（需要 HOME 可写）
HOME=$PWD/.validation/home ./node_modules/.bin/antd lint apps/admin/src
HOME=$PWD/.validation/home ./node_modules/.bin/antd info Table

# 后端。两个变量缺一不可，2026-10-05 实测：
#  (1) PYTHONPATH 必须是**仓库根绝对路径**。不设时 tests/a0 报 ModuleNotFoundError: tools
#      并中断整个 collect（1851 collected / 1 error）；设对后 1896 collected / 0 error。
#      相对路径 "$PWD/.." 与不设**完全等价**，无效。门禁 verify-backend-tests.sh:76 本来就设了。
#  (2) 跑 DB 相关用例要 SOYMUTDB_TEST_DATABASE_URL；缺它时消融 20 个用例报连接错误。
cd apps/api
export PYTHONPATH="/mnt/data02/T25ronglin/code/web"
export SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb'
.venv/bin/python -m pytest tests --collect-only -q          # 1896 collected, 0 error
.venv/bin/python -m pytest tests/test_ablation_*.py -q     # 149 passed
.venv/bin/python -m pytest tests/test_me_capabilities.py \
                  tests/test_active_release_endpoint.py -q  # 27 passed，无需 DB
# 全量在本机 OOM（EXIT=137 @ ~47%），需分片或降内存跑法，见「已知红灯」第 4 条
```

## 2026-11-08：死代码/孤儿配置清理（任务 #5）

**设置注册表审计**：`SystemSetting` 的全部运行时读取均经由 `registered_keys_for_section`（settings API）、`FeatureFlagService`（`feature.<key>`）、`PluginService`（`plugin.<key>.enabled`）或固定已注册键（`general.siteName`、`about.*`）；无未注册的 `get()` 键。`content.*` 反向守卫与 admin i18n 守卫保持全绿。

**已删除的零消费者配置**（逐项全仓 grep 确认无代码/测试/流水线读取）：

| 项 | 证据 | 处置 |
|---|---|---|
| `Settings.cache_ttl_seconds` | 无读取方；生效的是 `redis_cache_default_ttl`（`app/services/cache.py`） | 删除字段；`apps/api/.env.example` 的过期 `SOYMUTDB_CACHE_TTL_SECONDS=3600` 改为 `SOYMUTDB_REDIS_CACHE_DEFAULT_TTL=300` |
| `Settings.publication_artifact_bucket` | `publication_targets.py` 只消费 `publication_local_root`/`github_pages_*`/`cloudflare_pages_*` | 删除字段；`deploy/.env.example`、`deploy/conda/env.example` 删除「待决策」注释块；`docs/ops/production-security-checklist.md` 删除过期声明 |
| 孤儿 `# ---- GWAS` 与 `# ---- OpenTelemetry` 注释段 | 段内已无任何字段 | 删除注释；`.env.example` 同步删除 `SOYMUTDB_OTEL_*` 块 |

历史研究/计划文档（`docs/research/2026-08-17-*`、`docs/superpowers/plans/2026-07-19-*`）中的同名锚点按规则保留，未改。

**i18n 键审计（结论：不删，转交待建任务）**：`packages/i18n-core/src/locales/{en,zh}/common.json` 各 3309 键；动态前缀扫描（`t("a."+)`、模板字符串、`labelKey`/`i18nKey`）识别 23 个前缀后，仍有 920 键无任何字面或前缀引用。抽样证明这些不是「删除后无影响的腐化键」，而是**待建 UI 的前置目录**：`admin.importStudio.*` 零引用，因为 Import Studio 路由（`apps/admin/src/routes/imports/*`）正是任务 #6；`search.*`/`variants.*`/`genes.*` 缺口对应任务 #9/#10；`nav.*`/`home.*` 多数由 `apps/web/src/lib/site-content-react.tsx` 的 `SITE_CONTENT_DEFAULTS`（可编辑 `content.*`）承载。因此本轮**不删除**任何目录键，删除动作归属 #6/#9/#10/#16，避免把待建功能的文案目录当死代码清掉。

**验证**（本轮实跑）：

```bash
python3 scripts/check_content_key_contract.py     # OK (72 literal portal get() keys, 125 registered content keys)
node scripts/check-admin-i18n-keys.mjs            # OK (2297 literal keys, 23 dynamic prefixes, 3434 keys per catalog)
node packages/i18n/check-locale-keys.mjs          # Locale key check passed
cd apps/api && .venv/bin/ruff check app/core/config.py          # All checks passed
cd apps/api && SOYMUTDB_DATABASE_URL=... .venv/bin/python -m pytest tests/test_config_security.py -q   # 27 passed
```

## 2026-11-08：内容键双向契约收敛（任务 #11）

**守卫升级**：`scripts/check_content_key_contract.py` 不再只检查「portal 读了未注册的键」，而是双向门禁：注册键无消费者同样失败；动态读取族（`tool.${tool.key}.*`、`help.faq${i + 1}.*`、`site-header.tsx` 的 `labelKey`）从静态源列表展开，未知模板直接 fail-closed。`labelKey` 仅在真正调用 `get(...labelKey...)` 的文件中计为消费者，避免把纯 i18n 常量误报为内容键。

**漂移修复**：

- 真实接线缺陷 4 处：`search.location.colGbrowse` 误读为 `search.genes.colGbrowse`；BLAST 结果表的 `blast.hitProteinCoords`、表单的 `blast.eValue`/`blast.maxHits` 未走 `get()`。
- 导航文案：`tools/index.tsx`、`tools/sequence.tsx` 面包屑与 `sra.tsx` 标题改走 `get("nav.home")`/`get("nav.sra")`。
- 删除 11 个无消费者旧键：`tool.primer.{label,desc,image}`、`blast.input`、`blast.inputSequence`、`common.{loading,retry,submit,clear,reset,error}`；`SITE_CONTENT_DEFAULTS` 同步删除。
- 补齐 9 个经 `get()` 读取但未注册的头部标签：`nav.comparative`/`nav.expression`/`nav.phenotypes`、`search.tabGenes`/`search.tabLocation`/`search.tabGbrowse`、`tools.{seqfetch,enrichment,exppattern}.title`。

**回归测试**：`scripts/test_content_key_contract_guard.py` 重写为 10 个用例，覆盖双向漂移、动态族展开、`labelKey` 作用域与未建模模板 fail-closed。

**验证**（本轮实跑）：

```bash
python3 scripts/check_content_key_contract.py                  # OK (123 consumers, 123 registered)
python3 -m unittest scripts.test_content_key_contract_guard -v  # 10 passed
cd apps/api && .venv/bin/python -m pytest tests/test_settings_registry.py \
    tests/test_opt4_site_content_overrides.py -q                # 25 passed
pnpm --filter @soymutdb/web exec vitest run <blast|sra|sequence|location>  # 4 files / 33 passed
pnpm --filter @soymutdb/web typecheck                           # passed
pnpm --filter @soymutdb/web exec eslint <changed files>         # passed
```

## 2026-11-08：前端性能测量与优化（任务 #12）

**测量对象**：真实双变体产物 `apps/web/dist/external`，由 `apps/web/scripts/build-sites.ts` 完整构建（CSP finalize、service worker、release manifest 全链路），不是 dev server，也不冒充生产 RUM。

| 指标 | 移动端 390×844 | 桌面 1440×900 | reduced-motion |
|---|---|---|---|
| FCP | 36 ms | 72 ms | 236 ms |
| LCP | 1388 ms | 952 ms | 1388 ms |
| CLS | 0.0059 | 0 | 0.0063 |
| RAF / 秒（稳态） | 56 | 72 | 0 |
| 横向溢出 | 无（390 = 390） | — | — |

**产物预算**（gzip，真实文件）：

- HTML 直接引用的首屏 JS：163.0 KB（5 个文件），目标 <700 KB。
- 图表依赖闭包：331,914 B ≤ 378,880 B（370 KiB），余量 46,966 B；首屏闭包仅 4,553 B。
- 字体：JetBrains Mono 400/500 的 woff2 + woff 合计约 100 KB，目标 <500 KB；实际浏览器只取 woff2，且 `font-display: swap`。
- Umi 单 chunk 上限 600 KB：最大 `umi-entry` 240 KB；`ui` 197 KB、`charts` 232 KB，均通过。

**测量驱动的修复 1：静态壳占位块造成 0.09 CLS**。`soymutdb-shell-fallback` 以普通块级元素紧随 `#root`，React 挂载后根节点从 0 扩展到整页，把占位块推离视口；同时 UA 默认 `body` margin 在应用样式到达前生效。三连冷启动稳定复现 CLS 0.2084（0.107 文档位移 + 0.0936 占位块 + 0.0076 局部列高）。修复：`injectPageHead` 在带壳回退的文档 head 注入内联样式——`html,body{margin:0;padding:0}`；占位块改为 `position:absolute`，并以 `body:has(#root > *)` 在应用挂载后隐藏。修复后 CLS 降至 0.0059/0/0.0063。内联样式受现有 `style-src 'unsafe-inline'` 允许，不改变脚本 CSP 哈希策略。

**测量驱动的修复 2：reduced-motion 下轮播仍在走**。`FluidGradient` 在 `reduced` 时只画静态帧且不订阅 ticker（实测 RAF=0），但首页 `Carousel autoplay` 仍由 Ant 的 CSS/定时器每 5.2s 切换。现改为 `autoplay={!reduced}`，并在 e2e 中等待 5.6s 断言 `slick-active` 幻灯片文本不变（`slideStable: true`），避免仅凭 RAF 计数误判。

**验证**（本轮实跑）：

```bash
cd apps/web && pnpm build:sites        # external + internal 均成功（含 chart-closure / CSP / SW）
cd e2e && npx playwright test -c playwright-web-performance.config.ts  # 2 passed
cd apps/web && npx vitest run           # 78 files / 661 passed
cd apps/web && pnpm lint && npx tsc --noEmit                           # passed
bash scripts/check-bundle-size.sh apps/web/dist/external/assets        # OK；闭包 331914B/378880B
```

复测报告：`e2e/test-results-web-performance/vitals-report.json`（生成物，不提交）。移动端 LCP 余量约 1.1 s，首屏 JS 余量约 537 KB；未发现需要继续拆包的证据，后续优化应以真实用户 RUM 或网络限速测量再启动。

## 2026-11-09：多维表格后端/前端/验收（任务 #31–#33）

**后端（#31）**：新增 `admin_data_views` 表（迁移 `apps/api/migrations/versions/0058_admin_data_views.py`，含 upgrade/downgrade 与 PostgreSQL 覆盖），以 release 为作用域保存「来源 + 视图类型 + 展示配置」。来源限定 `genes` / `variants` / `mutant_lines`，视图类型 `grid` / `kanban` / `gallery`；读取仍走既有公开发布记录查询（`searchGenes`、`searchVariants`、`listMutantLines`），多维表格只保存呈现配置，不引入第二份权威数据，也不复制内部标识。管理端 CRUD 位于 `/api/v1/admin/data-views`，鉴权与现有 admin 路由一致。

**前端（#32）**：`packages/api-client` 重新生成 `openapi.d.ts` 并提供 data-view 客户端方法；`apps/admin` 新增 `/data-views` 页面（表格列表 + 新建/编辑对话框 + 视图类型切换）。来源字段与视图配置均按服务端枚举渲染，未知值 fail-closed，不推断。

**验收（#33）— OpenAPI 固定点再钉（同日，随产物一起提交）**：

- 契约快照与生成客户端：`openapi.json` blob `de867c3f…`，`openapi.d.ts` blob `a9ca8de9…`。此前会话已重钉 11 个守卫；本轮补齐三处仍停留在旧值的守卫及其回归套件：
  - `check_openapi_auth_surface.py`：新增可选鉴权端点 `GET /site/navigation`、`GET /site/profile`（`get_optional_user` 会发布 `security`），非 admin protected floor 48→50，projection 170→178，requirement rows 268→276，两个 digest 同步更新。
  - `test_openapi_behavior_contracts.py`：扩展键面 183→189 行、`x-idempotent` 182→188，`_EXTENSION_SURFACE_DIGEST` 重钉。
  - `test_openapi_operation_id_floor.py`：路径数 238→244、生成成员数 268→276。
- `scripts/test_openapi_auth_surface_floor.py` 的期望字面量同步为 50 / 178 / 276。
- `scripts/check_openapi_baseline_sync.py` 语义门通过；历史门按设计只有在「固定点 + 产物同提交」时才可能变绿，本地未提交树无法通过，未做规避。

**顺带修复的回归**：`scripts.test_ci_job_contracts` 的 i18n 门禁发现 `page-definition-renderer.test.tsx` 与 `login.test.tsx` 仍以每次渲染新建 `t` 的方式 mock `useTranslation`；两处改用共享的 `test/mocks.ts` `mockTranslation`（`stableT`），避免翻译函数身份在渲染间变化。

**i18n 补齐**：`packages/i18n-core/src/locales/{en,zh}/common.json` 增加 admin 站点控制/页面构建器、公共站点错误页与 `pageBuilder`、`ui` 资源，以及 `common.refresh`。两份 JSON 均通过 `json.loads`，双语 key 集合一致；`check-locale-keys.mjs` 通过。

**验证**（本轮实跑）：

```bash
python3 -m unittest scripts.test_ci_job_contracts                 # 106 OK
for f in scripts/check_openapi_*.py scripts/test_openapi_*.py; do python3 "$f"; done
# 除 check/test_openapi_baseline_sync 的历史门外全部 OK（13 个静态守卫 + 回归套件）
python3 -m unittest discover -s scripts -p 'test_openapi_*.py'    # 36 OK
apps/api/.venv/bin/python -m pytest scripts/test_locale_language_purity.py -q  # 5 passed
cd packages/i18n-core && pnpm test                                # 11 passed
node packages/i18n-core/check-locale-keys.mjs                     # passed
PATH="$PWD/apps/api/.venv/bin:$PATH" bash scripts/smoke.sh --profile contracts
# 1332 passed, 5 failed —— 5 个失败全部是未提交产物的历史门级联：
#   test_openapi_baseline_sync.py::test_an_unchanged_literal_needs_no_artifact_move
#   test_contracts_self_test_teeth.py 的 4 个 committed-tree/aux-total 用例
pnpm --filter @soymutdb/web test                                   # 87 files / 716 passed
pnpm --filter @soymutdb/admin test                                 # 36 files / 247 passed
pnpm typecheck                                                     # 13 tasks OK
pnpm lint                                                          # 12 tasks OK
```

本轮变更与固定点、重新生成的产物由同一次提交携带；历史门及其 5 个级联用例随该提交转绿。这不是代码缺陷，本地不提交就无法、也不应伪造该门通过。

### 同轮追加：后台卡片间距根因修复 + 分析设置页去除 Vite 时代残留（ADR-0016）

- **卡片重叠/相连的根因**：antd 6 在运行时把组件 CSS-in-JS 以**未分层** `<style>` 注入，未分层样式优先于任意 `@layer`（包括 Tailwind 的 `utilities`），因此 antd 组件根上的 `margin: 0` 会压掉 `space-y-*`。修复在 `apps/admin/src/index.css` 用 `[class~="space-y-N"] > :not(:last-child)`（specificity 0,2,0）未分层重述 8 个在用间距值，压过 antd 的 (0,1,0) 重置且不使用 `!important`；影响 `__root.tsx`、dashboard/monitor、content/pages 等所有页面级栈布局。
- **内容页筛选栏换行**：antd `Input` 的未分层 `width: 100%` 使 Tailwind 宽度类在 shrink-to-fit flex 行内失效 → 在 `pages-tab.tsx` 用 `w-64` 包裹层定宽、Input 仅保留 `h-9`。浏览器实测筛选栏回到单行（450×36），12 条 admin 路由 sweep 无 overlap/横向溢出。
- **分析设置页的 VITE 残留**：页面显示的 `VITE_CLOUDFLARE_ANALYTICS_TOKEN` 是 Vite 时代遗留的**真实构建期变量名**（构建已迁 Umi Max，前缀不再代表构建器），并非打包残留。按 ADR-0016 新增规范名 `SOYMUTDB_CLOUDFLARE_ANALYTICS_TOKEN`：`apps/web/config/config.ts` 与 `apps/web/scripts/csp.ts` 均按“新名优先、旧名兼容”读取；admin 页面与 zh/en 文案只展示新名；`turbo.json` 环境白名单、`deploy/cloudflare.md`、`deploy/.env.example` 同步；新增 ADR-0016 并更新 `docs/design/deployment-architecture.md` §4.4/§4.5（原“未实现”表述已过时）与 `docs/ops/production-security-checklist.md` 前缀约定。
- **保留旧名的原因**：Cloudflare Pages 项目的环境变量属于外部部署状态，直接删除旧名会让已部署站点静默失去统计；待各部署迁移完成后再单独发布移除说明。

**证据（2026-11-09）**：admin `tsc --noEmit` 通过；admin 构建成功；Playwright 登录后访问 `http://127.0.0.1:8001/analytics-settings`，body 文本 `hasVite=false`、`hasNewName=true`，截图见 `/tmp/soymutdb-run/analytics-settings-after.png`；此前间距修复轮 admin Vitest **37 files / 254 tests passed**、ESLint 通过；浏览器几何验证 monitor 与 content/pages 相邻卡片间距均为 16px、筛选栏单行。admin 单测与门户 typecheck 在本轮文档编辑后未再重复执行（文档与文案值变更不影响逻辑）。
