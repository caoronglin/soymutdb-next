# Project Memory

## Decision Record: 生产控制面保留 PostgreSQL

**日期**: 2026-08-19
**问题**: PostgreSQL 是否可由 SQLite 替代。

### 选项分析

| 选项 | 优势 | 劣势 | 复杂度 |
| --- | --- | --- | --- |
| 保留 PostgreSQL | 保留行锁、`SKIP LOCKED`、advisory lock、PG 类型、迁移与现有灾备 | 需要独立数据库运维 | 低 |
| 增加 SQLite 轻量 profile | 单机演示部署简单 | 必须单进程并禁用或重写 outbox、发布、导入及并发任务；另建 schema/测试 | 中高 |
| 全面替换 SQLite | 单文件存储 | 重写并发协议、迁移、类型、容器、监控和灾备，无法维持当前多 writer 拓扑 | 高 |

### 决策

**选择**: 生产与完整开发栈继续使用 PostgreSQL；只有明确需要离线单机演示时，才评估独立、功能受限的 SQLite profile。
**理由**: 当前 API/Worker 依赖 PostgreSQL 行锁、`FOR UPDATE SKIP LOCKED`、session advisory lock、JSONB/UUID/INET、原生 enum 和 PostgreSQL Alembic 链；生产同时运行多 API worker 与多个 Celery writer。
**Trade-offs**: 接受 PostgreSQL 的部署和备份运维成本；若目标只是降低运维，优先采用托管 PostgreSQL，而不是更换数据库语义。

### 影响范围

- `apps/api` 数据模型、事务、迁移和 outbox。
- `apps/worker` 导入锁与数据库驱动。
- `docker-compose.yml`、`deploy/scripts`、监控及灾备流程。

### 撤销条件

产品明确收缩为单机、单用户、单写进程，且不需要 Celery 并发、发布/回滚、outbox、导入互斥或生产高可用；同时 SQLite schema、并发反例、备份恢复和完整声明功能集均通过独立验证。

## Project Convention: 生物信息学数据库核心与身份边界

**类型**: 架构约束 / 命名规范 / 测试规范
**适用范围**: 突变体、基因、变异、搜索、数据发布，以及 external/internal 站点

### 规范内容

- SoyMutDB 的主产品形态是可检索、可追溯且版本明确的生物信息学数据库；内容页面不能取代标识符搜索、结果列表和实体详情。
- 突变体的稳定公开身份使用 `public_id`；数据库私有身份使用 `internal_id` 语义。外部契约不得暴露或接受内部身份，内部搜索两种 ID 必须由服务端授权。
- v4/v5 是不同 assembly 命名空间；基因、变异、坐标和跨版本映射必须显式绑定 assembly。跨版本等价关系只能来自带 provenance 的 crosswalk/alias 数据。
- external/internal 是独立构建和部署边界。缓存必须至少按 site variant、release、assembly、query 和 filters 隔离。
- 上述变更按 `docs/dev/database-core-contract.md` 的 P0/P1 矩阵执行；隐私、身份和 assembly 隔离的 P0 测试不得 skip/xfail。

### 示例

**正确**:
`external mutant URL -> public_id; authorized internal search -> public_id or internal_id; gene hit -> assembly + release`

**错误**:
`external mutant URL -> numeric database id; v4/v5 hits silently collapsed; cache key -> query only`

### 发现来源

2026-09-06 用户确认的项目核心功能与双版本需求；落地文件为 `AGENTS.md` 和 `docs/dev/database-core-contract.md`。

## Implementation Record: 公开搜索 fail-closed 基线

**日期**: 2026-09-06
**状态**: 部分实现，不能替代双 ID 迁移

- 未认证的 SoyMutDB 全局 JSON 搜索固定使用 `external` 上下文；缓存参数包含 site variant、release、assembly、query、types 和 cursor/limit。
- 基因命中只来自 active published release，并按明确 assembly 进一步过滤；结果携带 release/assembly ID，前端链接保留 assembly 查询参数。
- 现有 `MutantLine` 尚无 `public_id`，因此公开全局搜索暂不返回突变体命中，避免把数值主键包装成公开身份。内部突变体查询分支虽有 release/public/deleted 过滤，但只能由未来的服务端鉴权 internal 路由接入。
- `scripts/check_site_artifact_isolation.py` 递归扫描 external 制品中的调用方哨兵，拒绝重叠根目录与符号链接，并对诊断路径脱敏；其标准库测试入口为 `python3 -m unittest scripts.test_site_artifact_isolation -v`。

## Glossary Entry: public_id

**规范名称**: `public_id`
**别名/变体**: 对外 ID、公开 ID、public ID
**定义**: 面向研究者、URL、导出和引用的稳定公开编号，不随持久化主键变化。
**适用范围**: 突变体公开 API、搜索、页面、下载和发布制品
**禁止使用**: 用裸 `id` 指代公开身份；由 `internal_id` 推导公开编号
**来源**: 2026-09-06 用户需求与 `docs/dev/database-core-contract.md`

## Glossary Entry: internal_id

**规范名称**: `internal_id`
**别名/变体**: 对内 ID、内部 ID、数据库 ID、persistence key
**定义**: 仅供内部关联、运营和审计使用的持久化身份；现有存储字段可以名为 `id`，但对外不得暴露。
**适用范围**: PostgreSQL 关系、授权后的内部 API/搜索和审计
**禁止使用**: public ID；匿名查询键；external URL 或静态制品字段
**来源**: 2026-09-06 用户需求与 `docs/dev/database-core-contract.md`

## Glossary Entry: assembly

**规范名称**: assembly
**别名/变体**: 基因版本、基因组版本、v4、v5
**定义**: 一套明确的参考基因组与注释坐标/标识符命名空间；它与数据 release 是独立维度。
**适用范围**: 基因、转录本、变异、坐标、序列、JBrowse 和搜索缓存
**禁止使用**: 用 release 代替 assembly；静默混合 v4/v5
**来源**: 2026-09-06 用户需求与现有 `Assembly` 模型

## Glossary Entry: site variant

**规范名称**: site variant
**别名/变体**: 站点版本、对外版、对内版、external/internal site
**定义**: 只允许 external/internal 的显式构建与部署安全边界，不是搜索数据来源。
**适用范围**: Web 制品、origin、API 授权、CORS、缓存和 Service Worker
**禁止使用**: federated search source；按 host/IP/cookie/user-agent 推断的访客分类
**来源**: 2026-09-06 用户需求与现有 `SiteVariant` 契约


## Delivery Architecture: CNB 主链路 + GitHub 镜像

**日期**: 2026-09-11
**状态**: IMPLEMENTED_UNVERIFIED（CNB 真实构建待平台触发）

### 决策

交付链路改为 **`.cnb.yml` 为单一事实来源**，GitHub Actions 保留为镜像。关键不是
"翻译 YAML"，而是先把构建/测试/扫描/签名逻辑从 YAML 里抽成脚本，再让两个
provider 引用同一批脚本。

### 理由

- 原 `ci.yml` 有 1189 行内联逻辑；迁移到 CNB 若重写一份，之后必然双向漂移。
- 内联逻辑无法本地复现，任何失败只能推远端等 CI。
- 抽成脚本后 GitHub 侧可先回归验证，等价性可证，而非凭信心重写。

### 落地文件

- `.cnb.yml`、`.cnb/pipelines/*`、`.cnb/web_trigger.yml`、`.cnb/env/*`
- `scripts/ci-job-steps.sh`、`verify-frontend-artifacts.sh`、`verify-backend-tests.sh`、
  `build-release-image.sh`、`release-contract.golden.sh`、`build-pages-artifact.sh`、
  `verify-pages-artifact.sh`、`mcp-transport-smoke.sh`、`smoke.sh`
- `scripts/test_ci_job_contracts.py`（18 用例，防逻辑回流 YAML）

### 不可违反的规则

1. **逻辑不得内联回 workflow/流水线**：契约测试会失败。
2. **镜像校验与发布分离**：校验 pipeline 无 registry 凭据且不 push；发布 pipeline
   不做 `docker build`。发出去的字节必然等于验过的字节。
3. **PR 事件不得持有发布凭据**：CNB 的 PR `CNB_TOKEN` 权限受限。
4. **冒烟不得伪通过**：前置条件缺失必须 `SKIPPED` + 原因，且不计入通过数。
5. **工具链固定一致**：Node 24.19.0 / pnpm 11.21.0 / Python 3.14 / uv 0.11.33。

### 有意保留在 GitHub

Kind/Kubernetes 运行时冒烟（依赖嵌套 docker 与 `helm/kind-action`）、Windows 安装器
dry-run、受保护环境 staging/production dry-run、CycloneDX baseline SBOM。这些
workflow 顶部均有 MIRROR NOTICE。

### 验证证据（2026-09-11 本机）

- `scripts/test_ci_job_contracts.py` → 18 passed
- `bash scripts/smoke.sh --profile contracts` → 134 passed，SMOKE PASS
- CNB 校验器（YAML + 语义 + Schema）→ 三项通过
- `pnpm install --frozen-lockfile` + `pnpm build:web` → 成功；`--profile static` PASS
- 一次性 PostgreSQL 15（55432）+ Python 3.14：
  migrations 0035 全链 → live ok → ready postgres healthy → `/search` 503 空库
  fail-closed → `--profile runtime` PASS
- 后端回归对照：改动前后同为 **33 failed / 1445 passed**，零影响

### 未验证

CNB 真实构建、Docker 镜像构建/Trivy/SBOM（本机无 daemon）、Playwright E2E、ClickHouse 迁移。

### 撤销条件

若 CNB 平台不可用或团队决定回落 GitHub-only：`git revert` 本次提交即可；所有 GitHub
workflow 保留完整可用路径，未删除任何 job。

## Implementation Record: 公开 mutant 入口 release 边界与内部 ID 检索

**日期**: 2026-09-26
**状态**: IMPLEMENTED_VERIFIED（PG-backed 1276 passed + contracts smoke 232 passed）；生产发布仍 No-Go

- 公开 `/mutants` 列表/详情/phenotypes 统一依赖 `get_release_context`，可见条件为 `is_deleted=false AND is_public=true AND public_id IS NOT NULL AND release_id = <active published release>`；无 active release 时 503 fail-closed。draft、其他 published-but-inactive release、`release_id IS NULL` 的记录对公开面统一 404/不可见。
- `/search/suggest` 不再把 `resolve_release_context` 失败降级为 `release_id=None`；无 active release 返回空列表（fail-closed），因此草稿 assembly 的 accession 永不进入匿名建议。
- 授权 internal search 支持按 internal persistence key（纯十进制、int4 范围内）精确命中，响应 `matched_field="internal_id"`；external 搜索路径不含该匹配，匿名输入内部编号不泄漏。
- 后续 Wave（P0-03/P1-01/02/03 assembly 与 VCF、P1-04/05 站点、P1-06/07 管理端、P0-06/P1-08 双 CI）见 `.ai-memory/handoff.md`。

## Implementation Record: assembly 身份、危险歧义与 VCF 正确性

**日期**: 2026-09-26
**状态**: IMPLEMENTED_VERIFIED（PG-backed 1277 passed；worker 337 passed；chdb 跨 assembly 用例通过）

- `compute_variant_id` 现为 `sha256(release|assembly|chr|pos|ref|alt)`；worker 与 `scripts/seed_release_data.py` 同步，v4/v5 同 locus 生成不同 id。
- `finalize_release` 的 carry 保留「同染色体但非本次导入 assembly」的旧行，避免单 assembly 重导入删除另一 assembly；分区键仍为 (release, chromosome)，无需 DDL 变更。
- VCF zygosity 读取被选中样本的 gt_type，而非固定 `gt_types[0]`。
- 生产 ClickHouse DDL（`init.sql` 与升级脚本）新增 `variant_facts_staging`，并由 `infra/clickhouse/test_schema_contract.py` 与 fixture 漂移守卫约束。
- 无 assembly 搜索的 `by_assembly/ambiguous` 按 release 全集分组；前端 SearchView 分组显示版本/release/来源，VariantsView 在 All assemblies 时显示人可读版本列；variant 查询键纳入 cursor。

## Implementation Record: 管理后台外壳原生化 + 登录页 Pro 分栏 + 251 个缺失 i18n 键

**日期**: 2026-10-10
**状态**: IMPLEMENTED_VERIFIED（tsc 干净 / admin vitest 62 / pytest scripts 380 passed / 浏览器实测 18 页）
**详细记录**: `docs/dev/admin-console-overhaul-20261010.md`

- **根因不是配色**：`@ant-design/pro-layout@7.22.7` 的 peer 是 `antd ^4.24.15 || ^5.11.2`，而仓库锁 `antd 6.6.5`，pnpm 于是额外装了一份 `antd@4.24.16` 专喂 ProLayout。**两份 antd 共享同一 DOM**，各自独立 CSS-in-JS 缓存与 ConfigProvider 上下文 → 主题 token / locale / 动效 / 暗色**传不进侧边栏**。改配色永远够不着。
- 侧边栏分组是被 `NAV_SECTIONS.flatMap(...)` **展平丢弃**的（4 组 → 19 项平铺）。原注释显示嵌套菜单曾试过并因"看起来像空白栏"回退——问题被绕开而非解决。
- 外壳换原生 antd 6 `Layout`/`Sider`/`Menu`（`type: "group"`）。`PageContainer`/`ProCard` **239 处不动**（不依赖布局上下文，渲染正常），pro-layout 仍在依赖图但已不在渲染路径。
- 登录页按官方 Pro 左右分栏重写（品牌面板 + 480px 表单面板）。品牌面板 `aria-hidden`（内容在右侧已重复）。**不加"忘记密码"**——无重置流程，死链比缺省更糟。
- **251 个键在源码被引用但两个 bundle 都没有**，于是每个 `t(key, {defaultValue})` 静默渲染英文默认值。这就是登录页在中文界面仍全英文的原因——键不存在，上一轮双语标签修复够不着。
- `admin.news.trash` / `admin.uploads` 在 bundle 里是**标签字符串**，代码却当命名空间用；无人按标签读，故以命名空间为准。
- 新守卫 `test_every_translated_key_exists_in_the_bundle`：`test_both_locales_define_the_same_keys` **结构上看不见"两边都缺"**。守卫限定 `apps/admin`——门户仍有 127 个同类键，长期红灯的守卫等于没有守卫。
- 提交 `e5f9a6f34` + `166f76bda`，均未推送；CNB 最后绿线仍是 `821fa7b4d`。

## 2026-10-15 全栈收尾（进行中）

- 当前真实状态以 `docs/dev/fullstack-validation-20261015.md` 为准，保留历史记录但不得将早期通过当成本轮证据。
- API Python 3.15 更新 FastAPI 0.143.1/Uvicorn 0.54.0：2326 passed、3 历史 ClickHouse 驱动测试 skipped；MCP 66 passed，备份恢复 45 passed，部署契约 99 passed + 5 subtests。真实本机 PostgreSQL 为 16.15。
- Worker科学依赖正从源码编译，pysam/h5py/cyvcf2/matplotlib/statsmodels 等已有315构建产物；完整安装与测试未完成，不能宣称已迁移验收。
- 门户371 tests、charts84 tests、双站及隔离通过；剩余类型检查/管理端视觉及最终汇总还在收尾。
- 已清理完成测试现场41项约2.30GiB，详情 `docs/dev/task-cleanup-20261015.json`。保留当前venvs与PG数据，不重建、不删pid来解锁。

## 2026-10-16 最终本机验证更新

- API / Worker / MCP 正式候选 venv 全部 Python 3.15，已全量升级兼容锁文件。
- API 2326 passed + 3 历史驱动 skipped；Worker 原生默认 657 passed 0 skipped（PG18.6/真实DIAMOND/2M）；MCP66 passed。
- chdb-core26.9缺315非限定API shim，会exit1；已从Workerdev移除。五个历史模块在314强制迁移CI共享脚本中执行，更新依赖后33 passed。
- 科学栈实际计算/读写/JIT检查通过；真实隔离Redis8.10.1与Celery315消息/结果往返通过。不要将此写成API outbox/S3业务链已验收。
- Admin146 / charts84 passed，AntCLI两站0问题；双站与Admin共4份headers通过；ECharts/zrender已彻底清单/catalog/lock移除，冻结安装0下载成功。
- 统一contracts297 +5subtests，额外环境10 passed；root lint/typecheck25/25。
- 本机没有Docker，完整镜像/Compose E2E、真实生产回填/切换/S3灾备未执行。记录docs/dev/fullstack-validation-20261015.md与admin-final-validation-20261016.md。

- 冻结安装后再次全工作区 lint/typecheck/test：36/36 tasks、1071 tests 通过；日志 /tmp/workspace-final-20261016.log。临时Celery validation1016 与Redis56389已停止，日志保留。

## 2026-10-17 非 Docker 真实验收追加

- 手写 API client 契约债务归零；baseline={}，fresh OpenAPI check通过；client184，根36/36任务1083 tests。
- 真实 API ASGI HTTP→PG outbox→Redis8.10.1→Celery315独立Worker→MinIO S3导出通过，私有/其他assembly/draft排除，重复poll0。
- 修复Celery成功/失败sender Task对象触发TypeError；指标/配置/惰性导入/发布回归44通过，真实export指标递增。
- 增加backup/restore/verify显式native runtime与--no-repo-env，原生缺工具不fallbackDocker，保留quiescence/隔离/生产确认门禁。真实DR77表6桶9对象，独立115PASS0FAIL0SKIP；策略篡改负例拒绝并还原，逐字节一致。
- 真实MinIO无策略导出{}，恢复需anonymous set none而非set-json；verify新增目标实际策略核对。82运维回归通过。
- 当前证据 docs/dev/native-validation-20261017.md 及同名目录JSON；生产回填/切换无目标信息，未执行；Docker按用户范围排除。本轮临时 Worker/Redis/两个MinIO/历史CH/PG服务均已定向干净停止，验收数据和证据保留。

- 历史回填原生真实演练完成：CH26.9.1.147→PG18.6，Py315；26列DDL，5目标facts/v4+v5，另release排除；dryrun0writes、apply1receipt、cutover ready、repeat摘要不变、3拒绝PG不变。证据native-validation-20261017/backfill-rehearsal.json。

## Implementation Record: 多 subagent 修复与性能轮（2026-10-17 夜 / 10-18 凌晨）

**状态**: 已验收本机门禁；未提交、未推送。工作树仍含上一波未提交改动。

### 修掉的真实缺陷（全部有失败→通过证据）

1. `releases.version` / `releases.description` 两个 i18n 键在 zh/en bundle 都缺失（admin releases 详情）→ 补键。
2. 门户图表硬编码 `Total` 与 tool-chart 6 处英文文案 → 迁入 `charts.*`（9 键）。
3. Admin `motion-preference.ts` 读取从不写入且跨源的 localStorage 键 → 删除读取，仅保留 OS reduced-motion。
4. `apps/jbrowse/Dockerfile`、`infra/docker/Dockerfile.{web,admin}` 仍安装 pnpm 12.5.1（仓库/CI/锁文件为 12.11.2）→ 升到 12.11.2；`scripts/check-toolchain-pins.py` 新增运行时镜像扫描（含负例）。
5. conda `environment-{api,worker,baseline}.yml` 与 `deploy/conda/verify-baseline.sh` 仍是 Python 3.14（pyproject 要求 >=3.15）→ 统一 3.15；legacy ClickHouse 通道仍保持 3.14。
6. 运行时 ClickHouse 残留命名/导入：`stats.py`/`admin.py` 的 `ch_service` 实际是 `PostgresVariantService`，`popgen_service` 文档仍称 ClickHouse，`clickhouse_service` 顶层 import 会在无 `clickhouse-connect` 的原生环境连带 API router 导入失败 → 统一改名 `variant_service`；`clickhouse_service` 改延迟导入并明确标注为 legacy migration/test surface（**不删除**：`infra/clickhouse/test_schema_contract.py` 与 4 个 API 测试引用它；删除需连同 infra 契约与 legacy lane 一起退役）。
7. 测试 i18n 替身只返回 key：图表/搜索 i18n 化后测试看不到真实英文。资源从 `lib/i18n.ts` 抽到无 i18next 依赖的 `lib/i18n-resources.ts`，`test/mocks.ts` 按 catalog+portal/tools/home 深合并解析真实英文；4 个测试改为断言真实文案。

### 性能决策

- 自托管 HarmonyOS Sans SC 用 **GB2312 一级+二级 + zh/en locale + apps/*/src 字符集 + ASCII** 子集化：每应用 13.07 MB → 2.81 MB（-78.4%）。完整字体保留在 git 历史；稀有字回退系统字体。
- 新增 `scripts/subset-portal-fonts.py`（fontTools+brotli，`--check`/`--dry-run`）与 `scripts/test_portal_font_subset.py`（无 fontTools 依赖的覆盖+体积守卫，已接入 contracts smoke）；两个 app 的 Umi config 只对 Regular 加 `links` preload（CORS 属性必须与 font fetch 匹配），构建产物 `dist/{external,internal,admin}` 的 index.html 已核实。
- 未做 RUM/LCP/INP 实测（无生产流量）；前端 bundle 仍受现有 370 KiB 图表闭包与 Umi bundle 预算门约束。

### 本轮证据（本机）

- API **2325 passed / 4 skipped**（PG16.15，59.70 s）；Worker **659 passed / 8 skipped**（原生/静态测试库注入，8 项为 DIAMOND/2M opt-in）；`pytest scripts` **492 passed / 1 skipped / 14 subtests**。
- 工作区 `lint typecheck test` **36/36**（1043 Vitest + 40 JBrowse）。
- contracts smoke **338 passed + 5 subtests**、环境套件 10 passed、SMOKE PASS；static smoke PASS。
- web external+internal 与 admin 构建成功；artifact headers / production scan / 双站隔离 / chart closure（331144 B ≤ 370 KiB）/ bundle size 全 PASS；真实浏览器 a11y+布局 **10/10**。
- 环境限制：jbrowse 构建因 webpack Terser 的 esbuild 多进程 spawn `EAGAIN`（沙箱进程配额，同树 web/admin 构建成功）；MCP 3 项 loopback 传输用例沙箱内起不了本地服务；Docker 镜像与生产回填/切换未验收。

## Implementation Record: 2026-10-18 第二轮（subagent 审计 + 孤儿功能退役 + 契约修正）

**状态**: 已验收本机门禁；仍未提交。

### 本轮修掉（均有失败/审计证据）

- 导入 Studio 状态机与服务端不一致（validated 仍可编辑、draft 可 commit）、成功提示被 refetch 清掉、Resume 链接丢 BASE_URL → UI 门控与反馈修复，新增 14 个 admin 回归测试。
- 公开 `GET /capabilities` 仍声明 `analytics: "clickhouse"` → 改为 `"postgresql"`，重生成 OpenAPI/client（生成产物 ClickHouse 描述归零）；`stats.py` 日志事件不再命名退役存储。
- 孤儿 CDN 设置（`cdn.enabled/url`，无消费者）→ registry/config/legacy UI/domains/i18n 全链路退役；`data.enableClickhouse` 同样退役。
- ⌘K 命令面板的 `/widgets`、`/page-builder`（ADR-0009 已退役）与 `/resource-catalog`（不可用页）死目的地 → 移除。
- web `lib/i18n.ts` Vue 兼容死导出（`t`/`setLanguage`/`currentLanguage`）删除；workspace 10 个 eslint warning 清零。
- `build-pages-artifact.sh` 的无消费者 `VITE_CDN_ENABLED=false` 删除，并修正 4 份部署文档中已不存在的"CDN 构建开关"说明。
- 文档真实性核对（subagent）：master-plan A-04/A-09/A-12/A-13/A-17/A-19、project-status 历史红灯、handoff checkpoint、native-cutover、README、aegis INDEX。

### 决策/边界

- `clickhouse_service.py` 仍保留为 legacy migration/test surface（infra 契约引用）；`SettingKind.URL`/`allowed_url_hosts` 通用校验保留（CDN 只是其唯一注册消费者，删除会改变泛型 settings 契约）。
- 导入 Studio 的 `/imports/new` 仍走旧上传对话框，四步向导组件无消费者——这是 A-09 的剩余产品接线，不在本轮擅自删除或接线。
- 未提交：工作树仍含整波改动；提交策略留待用户确认。

### 本轮门禁

- API **2324 passed / 4 skipped**（60.31 s）；Worker **659 passed / 8 skipped**（fresh `soymutdb_worker_round1`，DIAMOND/2M opt-in）；`pytest scripts` **492 passed / 1 skipped / 14 subtests**
- 工作区 lint/typecheck/test **36/36**（1043 Vitest + 40 JBrowse）
- admin **21 files / 160 tests**；api-client **184**；web **371**
- 合同/静态 smoke、web 双站 + admin 构建、artifact/预算/双站隔离、浏览器 a11y 10/10（见 docs/dev/project-status.md 2026-10-18 节）
- 环境限制：jbrowse 制品构建（esbuild 进程配额 EAGAIN）、MCP loopback、Docker/生产回填未验收。

## Implementation Record: 2026-10-18 第三轮（mm provider subagents：安全/性能/前端/架构/技术栈）

**状态**: 已验收本机门禁；未提交。用户指示：subagent 使用 mm 提供商模型，覆盖 BUG/安全/前端/架构/后端优化/技术栈更新，Lead 决策。

### 修复
- 安全：login 未校验软删除账号（可登录拿 token/审计）→ 拒绝且与 inactive 同文案；sanitize `rel=noopener` 重写两个缺陷（作者 rel="opener" 绕过、属性值含 `>` 时注入畸形 HTML）→ quote-aware 匹配。新增 105 个负例测试。
- 性能：基因搜索 alias EXISTS 在 OR 中使 0046 trigram 索引全失效（seq scan）→ UNION ALL + 迁移 0048 `lower(alias)` 索引；实测 global_search 1609→164ms、gene page 769→9ms。首页统计 7→2 条 SQL。
- 前端：移除 `/resource-catalog` 死导航链（侧栏+仪表盘 CTA）、命令面板 100% i18n 化 + 焦点恢复、4 张图表 tooltipFormatter memo 化、删 6 个死文件（AdminSidebar 渲染体、4 wizard step、settings/site.tsx）、修 section-page 硬编码；新增 guard（nav/palette 不得指向 unavailable）+ 9 测试。
- 架构：删除 2 个无消费者 env feature flag；删除退役 `search.external` flag；新增 retired-lane import 守卫 + deprecated-API ratchet 守卫（接入 backend gate）。
- 技术栈：react/react-dom 19.3.1、@tanstack/react-query 5.104.3、tiptap 3.32.0、turbo 2.11.8、eslint 10.13.0；@types 保持 19.3.0（未发布 19.3.1）；root `"type":"module"`；lockfile 重建 + frozen-lockfile 验证；平台契约/React smoke pin 同步。

### Lead 决策（下一轮执行）
1. 登录限流改为 username+IP 双维度（security agent 报告，未修）。
2. settings-registry ↔ portal content 漂移：19 注册键无消费者×3 与 26 个未注册 `get()` 键——先按「接线或删除」二选一定案，再加 baseline ratchet 守卫。
3. 17 个无消费者 env 设置逐个退役（保留 otel/smtp 预留项需标注）。
4. 恢复 knip `files`/`exports` 类别并清理（本轮死代码全靠人工发现，正是 knip 被配置排除的类别）。
5. NotificationBell `role="menu"` 无 menuitem/键盘支持（a11y 真 bug，需专属测试）。
6. Python patch 更新：fastapi 0.143.3、sqlalchemy 2.1.5、api dev extra 增 httpx2（uv lock + venv sync 后跑全量）。
7. 持有大版本：TS7、Vite8、Vitest5、zod4、pdfjs6、i18next26/react-i18next17、dnd-kit10、@gmod、redis8（单独 ADR/迁移）。
8. 安全公告：braces high 无补丁，已有签名接受至 2026-12-09；react-router moderate 在 Umi 树内（audit-level high 不阻塞）；pip-audit 0。

### 本轮门禁
API **2444 passed / 4 skipped**；Worker **659 / 8 skipped**；`pytest scripts` **512 / 1 skipped / 14 subtests**；工作区 36/36（1067 Vitest + 40 JBrowse，web 372 / admin 169 / api-client 184 / charts 84）；contracts smoke 338+5 PASS；web 双站 + admin 构建、artifact/预算/双站隔离、a11y 10/10。

## Implementation Record: 2026-10-18 第四轮（Python patch / 内容契约 / 登录限流 / 通知无障碍）

**状态**: 已验收本机门禁；未提交。本轮 mm 子代理连续失败（provider 不稳定），由 Lead 直接完成下述工作。

### 依赖更新（Lead 执行并验证）
- fastapi **0.143.3**、sqlalchemy **2.1.5**、api dev extra 增 **httpx2 2.13.1**；worker venv 对齐 pydantic-settings 2.16.0 / alembic 1.20.0 / ruff 0.17.1 / asyncpg 0.32.0；`apps/api/uv.lock`、`apps/worker/uv.lock` 已更新；API 全量 2447 passed / 4 skipped。

### 内容契约（Lead 决策：单向硬门禁 + 注册缺失键）
- 注册 27 个 portal 已读但未注册的 content 键（content defs 131→157，variant 镜像自动复制），Admin 现在可编辑；默认值取英文 UI 文案，中文仍走 i18n fallback（portal 只拉 overrides）。
- 新守卫 `scripts/check_content_key_contract.py`：每个字面 `get("<key>")` 必须已注册（69 个消费者 0 未注册）；反向不硬门禁（动态键会假阳性），提供 `--report`。守卫测试 5 个，接入 verify-frontend-artifacts.sh。

### 登录限流（安全）
- 新增 `login_ip_rate_limit_max`（默认 50/窗口）并双维度消费：保留 per-(username,IP) 对子预算，新增 per-IP 预算，阻断轮换用户名的撞库；错误文案不区分账号存在性。新增 3 测试（轮换用户名被 IP 拦截、IP 隔离、同名不同 IP 独立）。
- 决策：通用入站限流与 API 层 CSP/HSTS 仍不实现（由 nginx/制品头承担，现有守卫覆盖）。

### 通知面板（前端 a11y + 功能）
- `role="menu"`（无 menuitem）→ 带 aria-label 的 `role="dialog"`；`aria-haspopup/aria-controls`；打开聚焦面板、Escape 关闭并把焦点还给铃铛；未读项新增“标记已读”（`POST /notifications/read {ids}`，API 早已支持但 UI 未接）。
- admin Vitest 增加 `esbuild.jsx = "automatic"`（tsconfig jsx preserve 导致仅 type-import React 的组件测试 `React is not defined`）。新增 3 个测试；admin 23 files/172 tests。

### 本轮门禁
API **2447 / 4 skipped**；Worker **659 / 8 skipped**；`pytest scripts` **517 / 1 skipped / 14 subtests**；工作区 36/36（1080+ Vitest + 40 JBrowse）；contracts/static smoke、web 双站+admin 构建、artifact/预算/双站隔离、a11y 10/10（见 project-status 2026-10-18 凌晨 III）。

### 仍待下一轮
- knip `files`/`exports` 恢复与死代码清理（本轮 mm 子代理两次失败，未执行）
- 17 个无消费者 env 设置退役、settings content 反向（注册未读）清理决策
- 大版本升级（TS7/Vite8/Vitest5/zod4/pdfjs6/i18next 等）单独 ADR
- Playwright 全量 E2E 需要 `/soymutdb-next` base 的专用构建

### 2026-10-18 第四轮追加（Lead 直接执行；mm 子代理 provider 不稳定）
- knip `files`/`exports` 类别恢复并清零：删除 query-options.ts 26 个死工厂（534→90 行）、format/site-variant/antd-theme/route-motion/deep-link/api-client client 聚合 default/tools api/news-carousel(仅留 NEWS_FEATURED_KEY)/status-badge canTransition/deployment 两个 helper/jbrowse buildAssembly/charts createProbeChart/csp APP_DIR 等；knip 配置加 entry + g2-runtime ignore（动态 import namespace 不可见）并在 `docs/ops/dependency-governance.md` 记录。knip exit 0；web 372 / admin 172 / api-client 184 / charts 84 / jbrowse 40 全绿。
- API Settings 删除 16 个零消费者字段（ClickHouse execution time、max_sync_rows、blast_max_sequences/bin_dir/cache_dir、gwas_max_attempts、otel_*、整套 API 侧 SMTP——邮件由 worker 直读 env）；deploy env 注释与 multi-genome-blast 文档同步。
- content registry 反向清理：删除 37 个无读取方注册键（157→120），portal fallback map 同步；content 守卫仍 0 未注册。
- 决策：`types` 类别暂不恢复（公共类型审计需单独一轮）；deploy 文档化的保留字段不动（api_workers/graceful/s3_export_bucket）。

### 2026-10-18 第五轮（E2E 恢复 + knip types）
- Playwright 公共套件首次在 React 制品跑通：专用 `/soymutdb-next` base 构建 → 31 passed/1 skipped；修复 genes.spec 陈旧中文列头断言（i18n 迁移后 en catalog + 钉 en-US locale）。
- internal 套件重写（旧 spec 是 Vue 时代 testids，不可能通过）：root base/唯一 robots meta/deny robots.txt/登录表单/登录重定向 internal /search → 3 passed。
- 修复制品缺陷：internal index.html 两个 robots meta（config + static-routes 双注入）→ injectPageHead 升级已有标签 + 单测；重建制品确认唯一。
- primer 套件按 React 页面重写（Submit primer design、antd measure row、JBrowse 2 按钮）→ 4 passed；entity-detail 3 skipped（需已部署栈，按设计）。
- knip types 类别恢复：仅排除 unlisted/binaries；删除/内联 3 个死协议类型；knip exit 0。
- 环境备注：E2E 需 PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright；Playwright 二进制在 e2e/node_modules/.bin；公共套件必须用 SOYMUTDB_EXTERNAL_BASE_URL=/soymutdb-next/ 的专用 external 构建（标准制品 base 为 /）。

### 2026-10-18 第六轮（文档真实性 + 技术栈 ADR + wiki 去 Vue/ClickHouse 化）
- wiki（声称只写当前事实）重写/订正：architecture.md、applications.md 整页重写为 React 19/Umi Max 4 + PG 唯一权威 + ClickHouse legacy-migration-only；api-and-ports.md 删除 ClickHouse 端口行、修正 Vite 措辞、补 API 分组；deployment-and-ops.md 修正本地构建命令（build-sites 双站）、就绪探针（PG baseline / extended Redis）、备份与迁移版本；multi-instance/README 同步；ADR-0009 加历史注记。
- 路径错误修复：search-static-performance-design.md、production-build.md 的 build-sites 路径；service-worker.md 的 gen-sw.js 路径；deployment-architecture/antd6 设计文档标注 Umi 前路径为历史。
- visible-i18n-baseline.json 删除已不存在的 Vue 文件条目（React/Vue 扫描器共享）。
- ADR-0010 记录本轮持有的大版本与升级顺序（TS7/Vite8/Vitest5/zod4/pdfjs6/i18next26/dnd-kit/jbrowse/redis-py8）。
- 依赖治理：pnpm audit 1 high braces（已签名接受至 2026-12-09）/7 moderate/1 low；deps:graphs passed；完整 deps:audit 受沙箱 uvx 工具目录只读 + 进程配额限制，需 CI runner 复核（knip 已单独 exit 0）。
- 教训：mm 子代理本轮 3 次均 provider 失败，Lead 直接完成；后续优先 Lead 执行关键路径，mm 子代理仅在可用时并行。

### 2026-10-18 第七轮（Vitest 5 + Vite 8 升级，ADR-0011）
- catalog: vitest 3.2.7→5.0.5、vite 6.4.3→8.3.4；5 个脱离 catalog 的包改 catalog:。
- Vitest 5 迁移：10 个 vitest.config 的 poolOptions→pool forks + maxWorkers:1；**必须保留 isolate 默认 true**（isolate:false 会让 vi.mock/globalThis 跨文件泄漏，command-palette 与 module-import-upload 失败）。
- Vite 8/Oxc 拒绝 tsconfig jsx:preserve → JSX 项目加 `oxc: { jsx: { runtime: "automatic" } }`；admin 弃用 esbuild 选项移除。
- pnpm 严格解析暴露缺失 @types/node：shared/genome-view/api-client 补 devDependency。
- 平台契约 pin 更新；ADR-0010 标注部分被 ADR-0011 取代。
- 证据：turbo test 11/11（1071 tests 全绿）；lint+typecheck 25/25；frozen-lockfile 通过。后续 ADR-0011 顺序下一项：i18next 26 + react-i18next 17。

### 2026-10-18 第八轮（i18next 26 + react-i18next 17，ADR-0012）
- 版本：i18next 24.2→26.4.7、react-i18next 15.4→17.0.21（web/admin/jbrowse + packages/i18n）。
- 破坏性变更处理：i18next 26 移除 initImmediate → buildBaseI18nOptions 改 initAsync:false；interpolation.format/console notice 未使用无需改；react-i18next 17 要求 i18next>=26.2、TS ^5 均满足。
- pnpm supply-chain 因 17.0.21 发布很新，自动加入 minimumReleaseAgeExclude（精确版本，沿用既有豁免模式）。
- 证据：turbo lint+typecheck 25/25；turbo test 11/11（1071 全绿）；i18n 守卫全绿；frozen-lockfile 通过；web双站+admin 构建、artifact/static/contracts/a11y 全绿；E2E 结果见 project-status。
- 下一项按 ADR-0010 顺序：zod 4 / pdfjs 6（表单校验与文件查看器）。

### 2026-10-18 第九轮（zod 4 升级；pdfjs 6 评估后暂缓，ADR-0013）
- zod：apps/web 唯一消费点 BLAST schema，3.24→4.6.7 零代码改动通过 tsc/373 tests/build。
- pdfjs-dist：v6 API 迁移已实现（destroy→loadingTask.destroy、RenderParameters.canvas 必填）但制品验证发现 (a) `?url` worker 不被 Umi/webpack 支持、无 worker asset；(b) pdfjs 用 `new URL(".", import.meta.url)` 导致构建机绝对路径（file:///mnt/...）进入 dist async chunk——v4 已有该缺陷。决定保持 4.10.38，ADR-0013 记录正确修法（worker 静态资产 + webpack-native Worker + CSP + 绝对路径守卫）。
- 下一轮优先：修 pdfjs worker/绝对路径制品缺陷（构建层），再考虑 pdfjs 6；之后 dnd-kit/jbrowse/TS7/redis-py8。

### 2026-10-18 第十轮（pdfjs worker + 构建路径缺陷修复；pdfjs 6 落地，ADR-0014）
- worker：apps/web/scripts/sync-pdf-worker.mjs 复制 worker→public（gitignore），build-sites 构建前/ dev 链式调用；viewer workerSrc = BASE_URL + pdf.worker.min.mjs；删除 ?url。
- 绝对路径：Umi define `import.meta.url`→"" 消除 pdf.js Node 分支的 file:/// 构建路径；新增 scripts/check_artifact_build_paths.py(+5 tests) 接入 frontend gate。
- MIME：容器 web nginx `.mjs`→application/javascript（1h cache），e2e/dev server 的 MIME 同步。
- pdfjs 6：loadingTask.destroy + render({canvas,viewport})；浏览器实测 worker 200 text/javascript 1.26MB 正常启动；双站制品均含 worker，build-path guard OK。
- 顺序：ADR-0013 的 pdfjs 暂缓被 ADR-0014 解决；剩余持有项 dnd-kit/jbrowse/TS7/redis-py8。

### 2026-10-18 第十一轮（dnd-kit sortable 10 + jsdom 30；ADR-0015 记录剩余阻塞）
- @dnd-kit/sortable 8→10（core/utilities 已最新，peer 满足；usage 标准）；jsdom 29→30（web/admin/charts dev DOM）。
- 阻塞证据：redis-py 8 被 kombu 5.6.2 `<6.5` 限制（当前 6.4.0 已顶格）且 RESP3 默认需单独评审；TS7 被 typescript-eslint 8.71.2 peer `<6.1` 阻止；jbrowse/@jbrowse/@gmod/mobx/lucide 需 CI jbrowse artifact lane 验证（沙箱无法构建）。
- ADR：0015；ADR-0010 更新交叉引用。

### 2026-10-18 第十二轮（治理审计深入 + dedupe + deptry 豁免）
- 完整 `pnpm deps:audit` 在本机可跑到大部分检查：pnpm-audit、pip-audit-api/mcp、licenses、circular deps、knip 等；发现并处理：
  - `pnpm dedupe --check` 真实失败（dompurify 3.4.16/3.4.17、@umijs/bundler-utils 4.7.20/4.7.24 等）→ `pnpm dedupe` 修复，`--check` 通过。
  - deptry DEP001：clickhouse_connect/chdb 仅存在于 Python 3.14 legacy-migration 镜像，不应进 3.15 元数据 → governance 配置按精确模块豁免（worker 用 `|` 分隔多模块），api/worker deptry 均 Success。
  - worker 的 pip-audit / python-licenses 失败为沙箱环境（numcodecs/h5py 构建缺编译器/HDF5），非代码；CI runner 上复核。
  - knip 曾因我临时目录 `apps/web/dist-root-pocket` 报 33 unused files（已删除，非真实）。
- 文档：docs/ops/dependency-governance.md 增加 legacy-lane 豁免与 dedupe 门禁说明。
- 下一轮：字体 latin/CJK 拆分（initial 字体 908KB→~50KB 的可行优化，需改 subset 脚本/CSS/guard）。

### 2026-10-18 第十三轮（字体性能：portal 去死重 + admin latin/CJK 拆分）
- 发现 portal CSS 无 HarmonyOS @font-face（系统 CJK 栈为刻意设计），但 config 仍 preload 旧 929KB 字体、public 有 2.8MB 死资产、两个 STYLE.CSS 未被 import → 删除 portal 字体+preload+两个死 CSS（portal 制品 -2.8MB）。
- admin 字体按 unicode-range 拆 latin(~15KB,仅 Regular preload)/cjk(~900KB 按需)：subset 脚本改 admin-only、manifest 加 parts/role/missing（role-scoped）、CSS 6 个 face、绝对 /fonts 引用避免 hashed 资产重复；guard 重写（5 tests，含 portal 不得回退字体策略）。
- 验证：font --check/guard OK、perf E2E 1 passed、visual 15 passed、admin 制品字体单份。
- 环境教训：并发跑 turbo(workspace tests)+scripts+visual 会触发沙箱 fork/spawn EAGAIN（admin vitest worker、backup sort panic）→ 最终门禁需串行/小批次。

### 2026-10-18 第十四轮（全路由冒烟 + 真实渲染崩溃修复）
- 新增 e2e/tests/route-smoke.spec.ts：36 条门户路由 × en/zh，断言无 pageerror/异常 console/空 #root/error boundary；public+internal 两套 config 均纳入。
- 真 bug：/genes/:geneId 在错误/离线 API 下整页崩（undefined.toLocaleString）。根因：static-server 基因 mock 把详情路径当搜索列表返回 {items:[]}；应用信任生成类型无运行时校验。修复：server 详情 404 + 新 lib api-contract-guards.isGeneDetailRecord + gene 详情页守卫（形状不符渲染空态），4 单测。
- 验证：public E2E 33/1 skipped（含 route smoke）、internal 5 passed（含 route smoke）、perf 1、visual 15、workspace 1075 tests、scripts 523/1/14、artifact/static/contracts(339+5)/a11y 10/10 全绿。
- 后续：把实体详情页的运行时形状守卫推广（mutant/variant/news 等）；jbrowse 13MB 字体随其 CI lane subset。

### 2026-10-18 第十五轮（运行时形状守卫推广：mutant/news）
- api-contract-guards 增 isMutantLineDetailRecord / isNewsDetailRecord；接入 /mutants/:id、/news/:slug，形状不符渲染 not-found/error（同 gene 守卫模式）；守卫单测 8 个。
- 门禁：workspace 25/25 lint+typecheck、1079 tests、scripts 523/1/14、frozen lock、双站+admin 构建、artifact 全绿、public E2E 33/1 skip、internal 5、perf 1、visual 15、contracts 339+5、a11y 10/10。
- 教训：E2E 专用构建（dist/e2e-external）会覆盖 .build/chart-closure/web-external.json；测完必须重跑标准 build:sites 再做制品门禁，否则 chart closure JS set mismatch。
- 下一轮：variants/出版物等其余数据页的运行时守卫（如适用）；部署栈 E2E；jbrowse CI lane；提交决策。

### 2026-10-18 第十六轮（API 形状弹性 E2E）
- e2e/tests/api-shape-resilience.spec.ts：page.route 拦截 genes/mutants/news 详情返回错误形状 200，断言降级态（empty/not-found/error）+ 无 error boundary + 无 toLocaleString 控制台错误；接入 public 套件（36 passed/1 skipped）。
- 踩坑：相对 page.goto 必须 new URL(path.replace(/^\//,""), baseURL)，否则丢 /soymutdb-next 前缀；antd Empty 的隐藏 title 使 getByText 误命中，断言用 body.innerText。
- 流程：E2E 专用构建后再重跑标准 build:sites 才能过 chart-closure 制品门禁（已再次验证）。

### 2026-10-18 第十六轮（依赖安全 floor）
- pnpm-workspace overrides 增 postcss-selector-parser@<7.1.6→7.1.6、pbkdf2→3.1.7、sprintf-js→1.1.3；audit 7→5（1 high/3 moderate/1 low），frozen+dedupe check 通过。
- 剩余无修复项写入 docs/ops/dependency-governance.md「Accepted residual advisories」；braces high 已有签名接受（security/advisory-acceptances.json，2026-12-09 到期），用 evaluate_advisory_report 验证 0 unaccepted/1 accepted。
- 复验：workspace 1079 tests（907 non-admin + 172 admin threads pool）、scripts 523/1/14、双站+admin 构建、artifact 全绿、perf 1、visual 15。
- 沙箱 admin vitest forks EAGAIN workaround：pnpm exec vitest run --pool=threads --maxWorkers=1（23 files/172 tests 通过）。

### 2026-10-18 第十七轮（admin 制品 E2E 复活 + 登录页响应式 BUG）
- admin production 门禁此前全红且是死配置：spec 假设英文文案（admin 固定 zh）、testid 不存在、无 data-app-ready。修复：login.tsx 加 3 个 testid、react-app.tsx 加 AppReadySignal、spec locale 无关。
- 真 UI BUG：390px 下 admin 登录页横向溢出 240px（装饰面板 flex 1 1 55% + 固定 480px 表单）→ index.css @media(max-width:767px) 隐藏 hero、表单全宽。
- 新增字体契约 E2E：admin 制品只提供 split faces、preload=Regular-latin、字体响应 200 font/woff2。
- 证据：admin production E2E 4 passed、workspace 1079 tests、artifact 全套、static smoke 全绿。
- jbrowse 构建沙箱仍 EAGAIN（esbuild/Terser 阶段），其 13MB 字体 subset 留给 CI artifact lane。

### 2026-10-18 第十九轮（E2E 门禁盘点 + 修复）
- 审计 13 个 Playwright 配置：只有 2 个 CI-wired；发现 primer/public 两条 CRITICAL（webServer 目标/挂载前缀与 base-/ 制品不匹配）、admin-console 全红 testid、local-preview 无 skip、browser-open-new-tab 缺失、4175 端口三配置共用、.cnb.yml 夜间 smoke 指向 example.com 占位符。
- 已修：static-server root-baked artifact 子路径兜底；primer 服务 dist/external@/ + BASE="" + en-US locale；internal reuseExistingServer=false、visual 4177、perf 4178；.cnb.yml SMOKE_BASE_URL=gh-pages 真源。
- 待 subagent 修：admin-console spec/testid、local-preview skip、browser-open-new-tab testid、genes 死断言。
- 环境：宿主线程/pid 配额仍紧张，`pnpm exec` 会 `spawn pacquet runtime thread EAGAIN`；构建需等配额。

### 2026-10-18 第十九轮续（E2E 修复落地 + 两个真 bug）
- static-server PREFIX 归一化 bug：root 挂载传 "/" 时 mock 拼成 "//api/v1" 全 404；改为 PREFIX_RAW="/"→""，mock/剥离/日志统一。这是 public 套件早期全红与 primer 同源 404 的根因之一。
- primer genome 根因：helper 伪造 /releases/active 200 → reload 后 assemblies 不再解析（独立探针复现）；去掉该 mock 后稳定。真实部署 release 形状待部署栈 E2E 验证。
- 健壮性：primer 用例补 waitForAppReady（否则填 SSG 惰性表单）、config reducedMotion reduce。
- 结果：public 36/1 skip、internal 5、admin-prod 4、visual 15、perf 1、primer 4（单跑）、workspace 25/25 + 907 tests、scripts 523/1/14、artifact 全绿。

### 2026-10-18 第二十轮（release 切换销毁在途查询 BUG 修复）
- 真 bug：ReleaseScopeProvider 用 removeQueries 处理 release pin 变化 → Query#destroy 静默 cancel 在途请求，query 永停 pending、observer 孤儿，详情页 200 不渲染（subagent 6/6 隔离矩阵证明；未固定 release 制品每次加载触发，部署 tab 发布时中招）。
- 修复：改就地 invalidateQueries({predicate isReleaseScopedKey, refetchType:"active"})；删除 dropReleaseScopedQueries 死代码；新增 mid-flight 回归单测（release-scope 7 tests）。
- 解锁 entity-detail 离线门禁：移除两条 skip + 修 4 个断言缺陷（gene wrapper 假绿、back-link 选择器、JBrowse locus 参数/格式）→ 3 passed。
- 验证：public 36/1 skip、internal 5、admin-prod 4、visual 15、perf 1、entity-detail 3、workspace 25/25 + 907 tests、scripts 523/1/14、artifact 全 PASS。

### 2026-10-18 第二十一轮（jbrowse 字体拆分，制品 31MB→8MB）
- 沙箱恢复后第一次成功 build jbrowse；发现字体双份（public 13MB + hashed assets 13MB）。
- subset 脚本扩到 admin+jbrowse；jbrowse 3 full woff2 → 6 split（latin ~15KB/cjk ~900KB），CSS 6 faces + unicode-range + 根绝对 /fonts 引用（jbrowse 自身 origin root），删 full 源文件（仓库 -10MB）。
- 验证：jbrowse dist 31MB→8.0MB、6 个字体文件无哈希副本、本地 200 font/woff2（14608/915452 B）、jbrowse node tests 40 passed、字体守卫 5 passed（覆盖 admin+jbrowse 且禁止 portal 回退）、build-path/app-shell PASS、scripts 523/1/14。

### 2026-10-18 第二十二轮（jbrowse 白屏 BUG + artifact 门禁 + defer 守卫）
- 真 bug：jbrowse Umi 构建入口脚本在 <head> 且无 defer → React #299 "Target container is not a DOM element"，制品部署即白屏；此前无 jbrowse 浏览器门禁。
- 修复：build-artifact.ts 给外部入口脚本补 defer（async/module 跳过、inline 保持以维持 CSP hash）；jbrowse react-app 加 AppReadySignal。
- 新增离线门禁 playwright-jbrowse-artifact.config.ts + spec：shell 交接、无 pageerror、jbrowse-unavailable 降级、split 字体 200 font/woff2；1 passed。
- check_app_shell_assets.py 新增 blocking entry script 检查 + 自测；验证：jbrowse build、40 node tests、lint/typecheck 25/25、scripts 523/1/14、app-shell/build-path PASS。

### 2026-10-18 第二十三轮（离线 E2E 一键化）
- scripts/verify-artifact-e2e.sh：8 个离线 artifact 门禁单一入口（结果表、fail-closed exit 1/2、ARTIFACT_E2E_RETRIES、ARTIFACT_E2E_LOG_DIR），package.json 加 verify:artifact-e2e。
- scripts/test_artifact_e2e_gate.py（3 tests）守卫清单/配置/fail-closed/包装，防漂移；docs/dev/e2e-gates.md 记录 13 配置分类、端口、覆盖、static-server 约定。
- 验证：8/8 全绿 196s；pytest scripts 526 passed/1 skipped/14 subtests。

### 2026-10-18 第二十四轮（compare provenance 补齐）
- compare 页新增 Assembly/Release provenance 行：Assembly 来自 assembliesQueryOptions（默认/首个），Release 来自 getReleaseId() 或 "not pinned"；行 testid compare-row-assembly/release（+ value）。
- i18n 新增 compare.curated.fields.assembly/release/releaseUnpinned/assemblyUnknown（en+zh parity 通过）。
- 测试：compare.test.tsx 加 QueryClientProvider + provenance 断言（5 passed）；entity-detail E2E 断言 Assembly 行 Wm82.a4.v1 + Release 行存在 → 3 passed。
- 验证：web 重建、lint/typecheck 25/25、workspace 908 tests、scripts 526/1/14、artifact sweep 8/8（201s）。
- 仍未做：compare 可选集仍为精选 fixture；release-pinned live comparison 需后端证据 API。

### 2026-10-18 第二十五轮（离线 artifact E2E 接入 CI）
- 新脚本 build-all-static-apps.sh（四套制品 demo 构建 + fail-closed）、ci-nightly-artifact-gate.sh（setup→build→8 门禁 sweep，默认 retries=1）；verify-artifact-e2e.sh 加 --build。
- 修复自引入 CI 漂移：GitHub pr-artifact 原用 /soymutdb-next 单变体构建 + 只跑 public config，与已改为标准 base-/ 制品的 public 门禁不匹配 → 改共享构建 + 全 8 门禁。
- 双 provider 接线：GH PR 作业、GH schedule/deploy 作业、CNB 夜间 crontab 都调用共享脚本；CNB 失败上传 .cache/artifact-e2e。
- 验证：build-all 实跑 rc0；sweep 8/8（200s）；pytest scripts 526/1/14（CI 契约 71 passed）。

### 2026-10-18 第二十六轮（admin shell 离线门禁 + CI 复审修复）
- 新门禁 playwright-admin-shell（4189，apps/admin/dist）：真实登录表单 + static-server mock auth（/auth/login 同时接受 email/username 载荷）→ 认证后 shell-header 挂载、离开 /login、无 pageerror；1 passed。
- subagent 只读复审发现并修复：CNB 夜间浏览器不跨 stage（改为 gate 脚本内 npm ci + playwright install --with-deps，删误导 stage、online smoke 自带安装）；SMOKE_BASE_URL 泄漏使 entity-detail 测线上（移除）；PR 上传全门禁证据；test_artifact_e2e_gate.py 入 smoke contracts；verify-artifact-e2e.sh 入 shared-script 清单；GH 夜间 pnpm cache+timeout45；契约测试扫描 crontab pipeline；CNB 加 pnpm-store volume 与 CI=1；文档 15 configs/9 gates。
- 验证：admin-shell 1 passed、sweep 9/9（204s）、契约+守卫 74 passed/5 subtests、pytest scripts 526/1/14。

### 2026-10-18 第二十七轮（JBrowse 线性视图离线门禁）
- jbrowse-artifact 门禁新增真实视图用例：helpers.mockJbrowseApis（CORS）mock assemblies + /tracks/jbrowse-config；assembly 用 FromConfigSequenceAdapter 内联 4kb 参考序列 → createViewState 成功，无需 /jbrowse-data；jbrowse-data 快速 404。
- 断言 jbrowse-view[data-view-ready=true]、无 unavailable、assembly 名称、无 pageerror → 2 passed。
- 边界：证明配置→createViewState→挂载主链；真实轨道数据仍需部署栈。
- 验证：sweep 9/9（205s）。

### 2026-10-18 第二十八轮（seed-request 写路径离线门禁）
- 新 e2e/tests/seed-request.spec.ts（public 套件，mock CORS API）：① deep-link 预填 → 提交 → 成功态 + 校验 POST /seed-requests 的 JSON body（name/email/institution/country/gene_ids）与 content-type；② 201 个 gene id 客户端拒绝且不发请求。
- 补 testid：seed-request-form/submit/success/error-banner。
- 验证：2 passed、sweep 9/9（207s）、lint/typecheck 25/25。

### 2026-10-18 第二十九轮（downloads 目录/预览/下载安全门禁）
- downloads.spec.ts（public 套件，mock CORS API）3 用例：目录分组渲染、下载 URL scheme 守卫（正常 https 打开 / javascript 双 URL 均拒绝，window.open 调用数不增）、预览 Modal（标题文件名+VCF tag）。
- 下载表格加 onRow testid download-row-${id}（类型断言）。
- 验证：3 passed、sweep 9/9（212s）、lint/typecheck 25/25。

### 2026-10-18 第三十轮（tools/seqfetch 门禁）
- seqfetch.spec.ts（public 套件，mock CORS API）4 用例：genes 模式 payload+FASTA+count+missing；region 模式 region 字符串 payload；大结果 download_url 无 inline preview；客户端空列表/>200 拒绝且零请求。
- 技巧：assembly Select 仅在 region tab 渲染，共享状态 → 先进 region 等预选再切回 genes；断言用可见标签而非 antd 6 类名。
- 验证：4 passed、sweep 9/9（217s）。

### 2026-10-18 第三十一轮（exppattern 门禁 + 插值 BUG 修复）
- exppattern.spec.ts（public 套件）2 用例：payload {assembly_id,genes,cluster_rows,scale}、summary/missing/matrix（role=columnheader/cell）、canvas aria 名称；空/>50 客户端拒绝零请求。
- 真实 BUG：exppattern.tsx summaryDesc 传 `conds`（文案占位符 `{{conditions}}`）→ 页面显示原文 `{{conditions}}`；heatmapAria label 未传插值。修复为 conditions，label+description 都传值。toastDoneDesc 一并修正。
- 插值审计（apps/web+admin 全量 t() 调用 vs en/zh 占位符，排除 shorthand/count/defaultValue）：修复后 0 缺失。
- 验证：2 passed、sweep 9/9（219s）、workspace 908、lint/typecheck 25/25。

### 2026-10-18 第三十二轮（i18n 插值守卫）
- scripts/check_i18n_interpolation.py：扫描 web/admin/jbrowse 的 t("key",{...}) 调用，对照 en/zh 模板占位符（含复数后缀）；支持 shorthand/多行，跳过 spread 与 defaultValue，count 豁免；报告 options+missing。
- scripts/test_i18n_interpolation_guard.py 6 tests（含复现 conds vs conditions 真实 BUG 形状）。
- 接线：verify-frontend-artifacts.sh 新步骤；smoke.sh contracts 加 self-test。
- 验证：仓库 0 findings；frontend gate PASS；pytest scripts 532/1/14。

### 2026-10-18 第三十三轮（enrichment 门禁 + P 值 step BUG）
- enrichment.spec.ts（public 套件）3 用例：ORA/GSEA payload、summary/tags/terms 表、GSEA 键盘切 KEGG、空列表/越界 P 验证（原生约束拦下零请求）。
- 真实 BUG：en-p 输入 min=0.000001 + step=0.01 → 默认 0.05 stepMismatch，原生 constraint validation 阻止表单提交（点击无反应、无错误），整个 enrichment 工具不可用；修复 step="any" + checkValidity 回归断言。排查同类输入正常。
- 验证：3 passed、sweep 9/9（224s）、workspace 908、lint/typecheck 25/25。

### 2026-10-18 第三十四轮（BLAST 提交流程离线化）
- 原 skip 的 live 用例改为离线可执行：stubBlastApis + 真实登录表单（mock /auth/login）；用例 1 断言 POST payload（program/database/query_sequence/parameters evalue+max_target_seqs）；用例 2 jobs 列表(completed+running) → View results → hits 表 98.5%/1.00e-20/基因 accession、JBrowse 深链 /browser?assembly=...&locus=Glyma.01G000100%3A1000-2000、基因按钮跳 /search/genes?q=..&run=true、无 pageerror。
- 注意：登录需显式 mock（通配路由会拦）；/jobs/events 204 触发轮询回退；subject_id 同时用于基因列与 locus。
- 验证：blast 5 passed、sweep 9/9（228s）。

### 2026-10-18 第三十五轮（admin 认证后路由 sweep）
- admin-shell 门禁新增 24 路由 sweep：stubAdminApi mock login/refresh/me，其余 JSON 404（诚实错误态）；逐路由直达断言 shell-header、不回 /login、无 pageerror。
- 路由清单必须来自 apps/admin/src/App.tsx 手工 route 树（不是文件名；usage-guide 实为 /guide，初次运行即暴露）。
- 验证：admin-shell 2 passed、sweep 9/9（242s）。

### 2026-10-18 第三十六轮（portal⇄JBrowse bridge 离线门禁）
- browser-bridge.spec.ts（public 套件）3 用例：同源 harness 替换 iframe；握手（iframe data-bridge-status=ready、iframe 内收到 init payload、locus-change 同步 URL+输入框）、error envelope 可恢复态、缺 assembly/release 的 missing-context 态（无 iframe）。
- 事实：/browser 需 assembly+release 才渲染；iframe URL 可能是绝对 JBrowse origin 或同源 /jbrowse，路由需覆盖两种。
- 验证：3 passed、sweep 9/9（246s）。

### 2026-10-18 第三十七轮（analyses 门禁 + 匿名个人请求 BUG）
- analyses.spec.ts（public 套件）3 用例：匿名门禁零个人请求、researcher 服务端列表+行→job 页、列表 404 时 localStorage 回退经 GET /analyses/{id} 解析。
- 真实 BUG：jobsQuery 在 ResearcherGate 外层 → 匿名访客先发 GET /api/v1/analyses?limit=50（401+refresh）再显示门禁；修复为 AnalysesJobList 子组件置于 gate 内。
- 验证：3 passed（匿名 0 请求）、sweep 9/9（251s）、workspace 908、web eslint 通过。
