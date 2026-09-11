# 生物信息学数据库核心契约与测试流程

> 状态：目标行为契约（normative target），不是当前实现完成声明。
> 适用范围：突变体、基因、变异、搜索、数据发布，以及 `external` / `internal` 两套站点。

## 1. Proposal

- **Intent**：让 SoyMutDB 始终以“可检索、可追溯、版本明确的生物信息学数据库”为核心，而不是以内容展示为核心。
- **In scope**：数据库型信息架构、突变体双 ID、v4/v5 基因组版本、跨版本映射、内外站数据边界、搜索契约和测试门禁。
- **Out of scope**：本文件不指定 ID 编码格式，不直接决定迁移 DDL 或具体 API 路径，也不声称下述缺口已经实现。
- **Approach**：以 PostgreSQL 中的权威实体和发布状态为源，通过显式 assembly/release/site-variant 上下文形成 API、搜索索引、缓存、静态制品和端到端测试的一条契约链。

## 2. 术语和不变量

| 术语 | 规范含义 |
| --- | --- |
| `public_id` | 面向研究者的稳定公开编号；用于外部站点的搜索、URL、下载和引用。发布后不可随数据库迁移或主键变化而变化。 |
| `internal_id` | 仅供内部运营、关联和审计使用的持久化身份；可以是现有数据库 `id`，但不得进入外部契约。 |
| assembly | 具体参考基因组及注释坐标命名空间，例如 v4、v5；不同 assembly 的同名坐标或基因 ID 不能默认等价。 |
| release | 一次可发布的数据快照/版本；与 assembly 是两个独立维度。 |
| site variant | 构建和部署边界，只允许 `external` 或 `internal`。 |
| search source | 搜索来源，例如 SoyMutDB、NCBI、UniProt；不得与 site variant 混为一谈。 |

数据权威边界：

- PostgreSQL 保存实体身份、关系、assembly、release、权限和工作流状态。
- ClickHouse 保存批量变异事实的分析投影，不负责签发公开身份或决定可见性。
- MinIO 保存对象；Redis 只保存可丢弃的缓存/队列状态。
- 任何一个搜索结果都必须可以追溯到权威实体、release、assembly（适用时）和来源。

## 3. 当前实现基线与差距

以下是 2026-09-06 的代码基线，用于防止把目标契约误认为现状：

| 能力 | 当前状态 | 结论 |
| --- | --- | --- |
| 双站点 | Web 已用 `VITE_SITE_VARIANT` 构建 `dist/external` 和 `dist/internal`；内部内容 API 已要求认证并使用 `private, no-store` | 已有基础，生物数据 API 仍需应用同一边界 |
| 突变体身份 | `MutantLine.id` 是自增主键；公开路由、响应和搜索结果仍直接使用该数值 | **缺失**独立 `public_id`，当前行为不满足本契约 |
| 基因版本 | `Assembly` 已有 `name` / `version`，基因列表支持 `assembly_id`，前端会保留 assembly 深链和 JBrowse 上下文 | 部分满足 |
| 全局搜索 | 公共 JSON 搜索已绑定 `external`、active published release 和 assembly 缓存上下文；基因查询按 release/assembly 过滤；在 `public_id` 缺失期间，公开全局搜索 fail closed，不返回突变体主键 | 部分满足；突变体公开 ID 搜索、internal 授权搜索、无 assembly 歧义处理和跨版本映射仍是 **P0 差距** |
| 跨版本关系 | 基因有 assembly 和 alias，但未见显式的 v4↔v5 crosswalk 契约 | **缺失**；不得用字符串相似度替代 |

在完成迁移、API、索引、前端和测试前，相关任务必须标记为“未完成”或“部分完成”。
在 external 部署接入该全局搜索前，必须先关闭上述 P0 差距并通过 ID-01～ID-05 与 CTX-01～CTX-03。

## 4. Requirements 与验收 Scenario

### Requirement DB-CORE-1：数据库优先体验

系统 MUST 在主要入口提供突变体、基因和变异的标识符搜索，并在结果和详情中显示公开编号、实体类型、数据来源、release，以及适用的 assembly/version。

#### Scenario：研究者从首页进入数据库记录

- GIVEN 研究者访问 external 站点
- WHEN 输入一个已发布突变体 `public_id` 或某 assembly 下的基因 ID
- THEN 首个交互直接进入结构化结果列表或实体详情
- AND 页面显示可复制的稳定 ID、assembly/release、来源和相关实体链接

### Requirement DB-CORE-2：突变体双 ID

系统 MUST 为突变体区分稳定的 `public_id` 与私有 `internal_id`。已发布记录的 `public_id` MUST 唯一且非空；外部接口、URL、下载和静态制品 MUST NOT 暴露或接受 `internal_id` 作为公开身份。

#### Scenario：外部用户按公开 ID 搜索

- GIVEN 一个已发布突变体同时具有 `public_id` 和 `internal_id`
- WHEN 匿名用户在 external 站点按 `public_id` 搜索并打开详情
- THEN 返回且只返回公开记录
- AND 响应、URL、页面和下载中不包含 `internal_id`

#### Scenario：外部用户尝试内部 ID

- GIVEN 一个存在的突变体 `internal_id`
- WHEN 匿名用户将其提交给 external 搜索或详情入口
- THEN 返回空结果或 404 风格的统一响应
- AND 响应不得透露该内部 ID 是否存在

#### Scenario：授权内部用户按任一 ID 搜索

- GIVEN 用户已通过 internal 站点的服务端授权
- WHEN 用户按 `public_id` 或 `internal_id` 搜索
- THEN 两种输入都定位到同一突变体
- AND 内部结果明确标注匹配字段及两种 ID
- AND 查询行为进入结构化审计，但日志不记录凭证或不必要的敏感字段

### Requirement DB-CORE-3：v4/v5 版本化搜索

系统 MUST 把 v4 和 v5 作为独立 assembly 命名空间。查询执行与结果 MUST 显式绑定 assembly；接口 MAY 接受未指定 assembly 的发现型查询，但每个命中仍 MUST 包含 assembly 标识与版本，且必须执行下述歧义处理。

#### Scenario：在指定版本中搜索基因

- GIVEN v4 与 v5 都已加载并包含可检索基因
- WHEN 用户选择 v4 并搜索 v4 基因 ID
- THEN 只在 v4 命名空间执行精确查询
- AND 结果和下游 JBrowse/序列/变异链接保持 v4 上下文

#### Scenario：无版本查询出现歧义

- GIVEN 同一查询在 v4 和 v5 都有命中
- WHEN 用户未指定 assembly
- THEN 系统按 assembly 清晰分组并要求用户选择，或返回可判定的歧义错误
- AND 不得静默选默认版本并隐藏其他命中

### Requirement DB-CORE-4：显式跨版本映射

系统 SHALL 通过有来源和证据的 crosswalk/alias 关系连接 v4 与 v5 基因。映射 MUST 保存源 assembly、源基因、目标 assembly、目标基因、关系类型和 provenance；搜索结果 MUST 区分 exact、alias 和 cross-version 命中。

#### Scenario：从 v4 发现 v5 对应记录

- GIVEN 一个 v4 基因具有已审核的 v5 crosswalk
- WHEN 用户精确搜索该 v4 ID
- THEN v4 记录作为 exact 命中返回
- AND v5 对应记录作为明确标注的 cross-version 结果或关联项返回
- AND 不改变任一版本的坐标、ID 或 provenance

#### Scenario：没有可信映射

- GIVEN 两个不同版本的基因只有字符串相似或坐标接近
- WHEN 搜索其中一个基因
- THEN 系统不得自动宣称二者等价

### Requirement DB-CORE-5：内外站数据隔离

external 站点 MUST 只读取已发布且可公开的数据；internal 站点 MAY 搜索未发布记录和内部 ID，但 MUST 由 API 服务端授权。两套站点 MUST 使用独立制品、origin、缓存和 Service Worker 命名空间。

#### Scenario：未发布数据不进入外部制品

- GIVEN 测试数据中存在带唯一哨兵值的未发布突变体
- WHEN 构建 external 和 internal 两套静态制品
- THEN 哨兵值只允许出现在受保护的 internal 流程
- AND `dist/external` 的 HTML、JSON、manifest、source map 和 Service Worker 均不得包含哨兵值或 `internal_id`

### Requirement DB-CORE-6：搜索和缓存上下文完整

搜索索引、查询和缓存键 MUST 包含影响结果集合的上下文：site variant、release、assembly、实体类型、query、filters 和分页/cursor。内部结果 MUST 使用私有缓存策略，且不得被 external 请求命中。

#### Scenario：同一查询跨上下文不串数据

- GIVEN external/internal、v4/v5 或两个 release 使用相同查询词
- WHEN 依次执行查询
- THEN 每次只返回对应上下文的数据
- AND 缓存命中不能改变可见性、assembly 或 release

## 5. 目标领域契约

这是一组语义要求，不是对迁移字段名或路由形状的预先决定：

### 突变体

- 私有持久化键可继续作为关系主键，但只能在内部适配层表现为 `internal_id`。
- `public_id` 必须有唯一约束；记录进入公开 release 前必须存在。
- 公开 URL、导出、引用和搜索结果以 `public_id` 为 canonical identity。
- 公开 ID 变更必须采用保留旧 ID 的 alias/redirect 策略，并有审计和回滚方案。

### 基因与 assembly

- 逻辑查找键至少包含 `(assembly, gene accession)`；不得假定 `gene_id` 跨 assembly 全局唯一。
- API 结果必须同时返回机器可用 assembly identity 和人可读 name/version。
- 变异坐标、基因区间、序列提取和 JBrowse 链接必须共享同一 assembly 上下文。
- v4↔v5 关系是显式数据，不能由前端拼接或按名称猜测。

### 搜索结果

每个生物实体搜索结果 SHOULD 提供：

- `entity_type`
- canonical public identifier（公开结果）
- display label
- `match_type`（exact / alias / cross-version / text）
- release
- assembly id/name/version（适用时）
- provenance/source
- canonical URL

外部响应不得为了内部调试而添加 private persistence key。若现有通用 schema 的 `id` 无法表达语义，先演进 schema/client，再迁移调用方；不要继续扩大歧义。

## 6. 强制测试数据集

测试 fixture 必须最少包含：

1. 一个已发布突变体：同时有不同值的 `public_id` 与 `internal_id`。
2. 一个未发布/内部突变体：含唯一且易扫描的泄漏哨兵值。
3. 一个 v4 基因和一个 v5 基因，并有已审核 crosswalk。
4. 一对在 v4/v5 名称相同但并非同一实体的基因，用于阻止字符串猜测映射。
5. 两个 release 中相同 query 的不同结果，用于验证 release 和缓存隔离。
6. 至少一个 literal `%` / `_` 查询，确保用户输入不会变成 SQL LIKE 通配程序。

fixture 必须是合成数据，不使用生产 ID、未公开研究数据或真实凭证。

## 7. 测试矩阵

| ID | 层级 | 站点/权限 | 查询 | 预期结果 | 合并级别 |
| --- | --- | --- | --- | --- | --- |
| ID-01 | API + PostgreSQL | external anonymous | published `public_id` | 命中；响应无 `internal_id` | P0 |
| ID-02 | API + PostgreSQL | external anonymous | existing `internal_id` | 空/404；不确认存在性 | P0 |
| ID-03 | API + PostgreSQL | internal unauthorized | any internal query | 401/403；无数据 | P0 |
| ID-04 | API + PostgreSQL | internal authorized | `public_id` / `internal_id` | 同一实体；匹配类型正确 | P0 |
| ID-05 | artifact scan | external build | internal sentinel | 所有 external 文件零命中 | P0 |
| ASM-01 | API + PostgreSQL | allowed user | v4 gene + v4 assembly | 仅 v4 exact hit | P0 |
| ASM-02 | API + PostgreSQL | allowed user | v5 gene + v5 assembly | 仅 v5 exact hit | P0 |
| ASM-03 | API | allowed user | ambiguous unscoped ID | 分组或显式歧义，不静默默认 | P0 |
| ASM-04 | API + UI | allowed user | v4 exact with crosswalk | v4 exact + 明示的 v5 关联 | P1 |
| ASM-05 | API | allowed user | similar but unmapped gene | 不生成 cross-version 关系 | P0 |
| CTX-01 | cache integration | external/internal | same query | 缓存不跨 site variant | P0 |
| CTX-02 | cache integration | release A/B | same query | 缓存不跨 release | P0 |
| CTX-03 | cache integration | v4/v5 | same query | 缓存不跨 assembly | P0 |
| UI-01 | Vitest | external | mutant result/detail | 只显示 public ID | P0 |
| UI-02 | Vitest | internal authorized | mutant result/detail | 可区分并复制两种 ID | P1 |
| E2E-01 | Playwright | external anonymous | search→detail→JBrowse | ID、assembly、release 全程一致 | P0 |
| E2E-02 | Playwright | internal login | internal-ID search | 鉴权、审计和详情路径成功 | P0 |

P0 场景不得通过 skip/xfail 绕过。若实现尚未到位，PR/计划必须将其列为阻断项而不是把门禁降级。

## 8. 分层测试流程

### Gate 0：环境与变更范围

```bash
node --version
pnpm --version
python3.14 --version
apps/api/.venv/bin/python --version
git diff --name-only
```

期望 Node 为 24.x、pnpm 为 11.21.0、系统 Python 和 API 虚拟环境均不低于 3.14。先确认变更是否触及模型、迁移、OpenAPI、客户端生成物、搜索缓存、Web 路由、构建脚本或部署配置。

### Gate 1：最窄单元/契约测试

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_mutants.py tests/test_genes.py tests/test_gene_service.py tests/test_search_contract.py tests/test_site_home.py -q
```

```bash
pnpm --filter @soymutdb/web exec vitest run \
  src/routes/__tests__/mutants-discovery.test.tsx \
  src/routes/__tests__/genes-assembly-context.test.tsx
```

实现双 ID 和跨版本搜索时，应在这些模块旁新增矩阵对应测试；不得只修改旧断言以适配新响应。

### Gate 2：PostgreSQL 与迁移集成

```bash
cd apps/api
.venv/bin/python -m pytest tests/test_search_database_integration.py tests/test_migrations.py -q
```

包含 schema 变更时必须补充并验证：

- upgrade 后已发布突变体 `public_id` 唯一且非空；重复 ID 写入失败。
- downgrade 或文档化的前滚恢复路径不会丢失 ID 映射。
- v4/v5 数据可同时存在，查找键不会跨 assembly 冲突。
- crosswalk 外键、唯一性、provenance 和孤儿记录处理符合设计。
- 查询计划使用预期索引；性能声明必须记录数据量与 EXPLAIN/耗时基线。

### Gate 3：OpenAPI、客户端和前端

```bash
pnpm --filter @soymutdb/api-client check:contract
pnpm lint
pnpm typecheck
pnpm test
```

API 字段变化还必须确认 Web、Admin、MCP 或其他调用方没有继续依赖歧义 `id`。前端测试必须断言 assembly 标签可见，而不仅是请求中带了参数。

### Gate 4：双制品与泄漏扫描

```bash
pnpm --filter @soymutdb/web build:sites
python3 -m unittest scripts.test_site_artifact_isolation -v
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel "$UNRELEASED_SENTINEL"
```

构建后由自动化测试递归检查 `apps/web/dist/external` 和 `apps/web/dist/internal`：

- external 不含内部泄漏哨兵、`internal_id` 值、未发布标题或内部 API origin。
- internal 含 `noindex`，但测试不得把 `noindex` 当访问控制。
- 两套 manifest、hashed assets、Service Worker namespace 和内容快照互不复用。
- internal API 响应为 `private, no-store` 并按 `Authorization` 隔离；external 仅缓存公开响应。

### Gate 5：端到端验收

```bash
cd e2e
npx playwright test
```

端到端测试至少跑两个独立项目/环境：external anonymous 与 internal authenticated。每个场景从搜索输入开始，经过列表、详情、相关变异/基因和 JBrowse 链接，断言 ID、assembly、release 在全链路不漂移。

### Gate 6：交付记录

PR 必须附：

- Requirement/Scenario → 测试文件映射。
- 实际命令、测试数、通过数和失败/跳过清单。
- 模型/迁移/API/client/UI/artifact/E2E 的覆盖状态。
- 外部泄漏扫描结果。
- 数据迁移回滚或前滚恢复路径。
- 未验证项；任何 P0 未验证即为 No-Go。

## 9. 推荐实施顺序

1. 冻结语义：确认 `public_id` 编码/分配规则、内部角色和歧义查询 UX。
2. 设计 PostgreSQL 迁移与回滚：双 ID、唯一性、crosswalk、索引和现有数据回填。
3. 先写 P0 API/数据库失败测试，再实现模型、服务和搜索缓存上下文。
4. 演进 OpenAPI 与共享客户端，迁移 Web/Admin/MCP 调用方。
5. 实现 external/internal UI 差异，并加入静态制品泄漏扫描。
6. 跑完整 Gate 0–6；只有全部 P0 通过才可宣称该核心能力完成。

## 10. 未决业务输入

进入 schema/API 实现前仍需产品负责人确定：

- `public_id` 的格式、签发时点、是否允许废止，以及旧 ID 的 redirect/alias 保留期。
- 哪些内部角色可以查看或按 `internal_id` 搜索，以及审计保留期。
- 无 assembly 的查询采用“多版本分组”还是“要求先选版本”。
- v4↔v5 一对多、多对一和无映射时的展示规则及证据等级。

这些输入会改变数据模型和外部契约；未定案前可以完成测试骨架和技术验证，但不得执行生产数据回填或发布兼容性迁移。
