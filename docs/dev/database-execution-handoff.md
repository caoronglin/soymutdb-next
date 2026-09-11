# SoyMutDB 数据库核心能力执行交接

更新：2026-09-08。用途：交给其他智能体执行；本次交付仅整理方案，不代表功能已完成或允许生产发布。

## 1. 执行入口与效力

用户已撤销此前提供的 AGENTS.md 指令。本文件不自动恢复旧指令，也不要求覆盖现有 AGENTS.md。
本方案以用户确认的产品目标为依据，并明确区分产品要求、建议设计和待确认业务规则。
接手者先核验当前分支、未提交改动和相关文件，再按本文件执行；保留用户及其他智能体的修改。

阅读顺序：本文件 → `database-core-contract.md` 的需求与测试矩阵 → `architecture-and-deployment.md` → 任务涉及的代码。
旧契约中的“当前实现”是历史基线；当前状态以代码和可复现测试为准。既有优化总纲中与本任务无关的性能、桌面端、CMS 工作不并入本轮。

需要重新建立 AGENTS.md 时，由总控基于本文件维护简短入口和工程约束，保留无关有效内容；不得原样恢复已撤销文本。

## 2. 产品目标与执行约束

1. 数据库是核心：搜索、结构化列表、筛选、分页、详情、稳定链接及数据来源应构成主要使用路径；首页增加卡片本身不算完成。
2. 同一突变体具有对外编号和对内编号。外站按公开编号检索；获得内部权限的用户可按两种编号定位同一实体，并看清匹配字段。
3. v4 和 v5 都可检索。assembly 与 release 是独立维度；不得以活动 release 的默认 assembly 代替多版本检索。
4. 基因身份、坐标、序列、变异、表达与 JBrowse 链路必须使用相同 assembly 上下文。URL 带参数但查询忽略它不合格。
5. 外站只返回已发布且允许公开的记录。内部编号、未公开数据不得进入外站响应、链接、导出或静态制品；存在和不存在的内部编号不应产生可区分的存在性提示。
6. 内站权限在 API 服务端执行。站点配置、前端隐藏、noindex 和用户提交的 site_variant 均不能替代授权。
7. 跨版本对应关系只能来自可追溯的映射数据。没有证据时显示无映射，不按名称相似或坐标相近推断等价。
8. 延续现有 PostgreSQL 权威模型；ClickHouse 为分析投影，Redis 为缓存，MinIO 为对象存储。本任务不引入替代数据库或新的框架。
9. API、OpenAPI、共享客户端和调用方一起演进。公开突变体契约明确使用 public_id，内部契约明确使用 internal_id，避免新增含义不明的 id。
10. 所有测试使用合成数据与隔离数据库。生产回填、破坏性迁移和部署需单独授权；本交接允许编写实现、迁移和测试，不授权执行生产操作。

## 3. 当前状态：可复用基础与实际缺口

下表为 2026-09-08 的定点文件核验，不是全仓审计或运行验收。

| 范围 | 已有基础 | 接手必须补齐 |
| --- | --- | --- |
| 突变体模型 | `apps/api/app/models/variant.py` 有数值主键、public/deleted/release 相关字段 | 未见 public_id；需核实对内业务编号是否另有字段，不能直接假定就是主键 |
| 基因模型 | `apps/api/app/models/genomic.py` 有 assembly_id | Gene.id 仍为全局字符串主键；需支持同一 accession 在不同 assembly 共存并迁移下游外键 |
| 全局搜索 | `search_service.py` 带 site/release/assembly 缓存参数；基因按 release/assembly 过滤 | 仍固定活动 release，未指定 assembly 时默认选择；缺少跨版本发现和明确歧义处理 |
| 公开突变体搜索 | 缺 public_id 时暂不返回突变体命中 | 这是防泄漏的临时保护，不能作为“公开 ID 可搜索”的交付结果 |
| 内部搜索 | 服务层有 INTERNAL 分支 | 分支不等于鉴权接口；还需角色、数据范围、审计和私有缓存策略 |
| 基因详情 | `apps/web/src/routes/genes/$geneId.tsx` 接收 assembly 查询参数 | 详情、表达、同源查询仍仅按 geneId；不能证明完整链路版本正确 |
| 制品扫描 | `scripts/check_site_artifact_isolation.py` 与标准库测试存在 | 只扫描指定哨兵并检查部分文件系统条件；不能证明鉴权、缓存或完整双站隔离 |
| 工程版本 | package.json 指定 Node 24、pnpm 11.21.0；API 要求 Python >=3.14 | 检查实际运行环境和虚拟环境，不能仅依据版本声明报告通过 |

本次任务此前还产生了首页数据库入口、搜索客户端 q→query 修正、OpenAPI 快照及测试改动。接手者应核对 diff 和实际调用链后复用，不重复覆盖。
此前 API pytest 曾因虚拟环境 encodings 错误无法启动，前端测试/类型检查曾受 SMB 依赖访问影响；这些是历史阻碍，需重试确认是否仍存在。
此前的语法检查与扫描器单元测试结果不能替代当前分支的完整验收。OpenAPI 快照曾手工同步，需重新生成并检查一致性。

## 4. 先统一的契约与业务决策

总控先形成一个明确的契约版本，交给所有执行者使用。不得由三个智能体各自决定 ID、返回结构或迁移方式。

| 决策 | 建议方案 | 执行边界 |
| --- | --- | --- |
| 对内编号含义 | 先核对现有数据、导入字段及开发文档，区分实验室业务编号与数据库主键 | 缺证据时向负责人确认；不能把技术主键自动当作业务编号 |
| 公开编号签发 | 优先使用已有权威编号；如需新签发，采用独立、稳定、唯一且不暴露内部编号的规则 | 格式、历史编号保留及真实数据回填规则需负责人确定；可先做合成 fixture 和迁移设计 |
| 内部权限 | 复用现有 RBAC，显式赋予内部检索及数据范围权限 | 具体角色和审计保留期需确定；禁止以“已登录”代替内部权限 |
| 未指定版本搜索 | 建议按 assembly 分组展示可访问命中；精确详情要求明确 assembly | 接手可据此形成设计稿与测试；若采用强制先选版本，必须在 UI/API 一致说明 |
| 多 release 与 assembly | 显式选择或解析可访问的已发布 release；v4/v5 可能属于不同 release | 必须测试两个版本同时可发现；不能只新增 assembly 参数而保持全局活动 release 限制 |
| 基因持久化身份 | 评估独立内部键 + assembly/accession 唯一约束，并清点所有引用 | 不先定 DDL；需给出外键、导入、投影和历史链接迁移影响清单 |
| 跨版本映射 | 保存源/目标 assembly、基因、关系类型、来源、证据及版本 | 明确一对多、多对一、无映射；先提供准确的独立版本搜索，不能伪造映射数据 |

跨版本关联展示可在核心搜索之后实施，但全量需求交付仍需验收该项；不得因旧矩阵标注 P1 就将其标记为完成。
业务输入未确定时继续不依赖它的测试、接口设计和隔离检查；不要擅自把建议写成已批准决定。

## 5. 任务拆分与依赖

推荐三个执行者，模型可使用用户指定的 gpt-5.6-luna；本交接不自动启动新智能体。
一个总控负责契约、迁移顺序、共享文件和最终验收。共享目录不提供写隔离，执行者只能修改分配范围。

| 任务 | 负责人及范围 | 输入依赖 | 交付与验收 |
| --- | --- | --- | --- |
| T0 基线与契约 | 总控；文档、接口清单、数据关系图、测试状态 | 无 | 核验已有改动；记录业务决策、API 字段、权限和迁移方案；形成统一契约版本 |
| T1 身份与版本模型 | A；API 模型/迁移/导入适配及对应测试 | T0 | 双 ID、assembly-scoped gene、引用迁移、映射结构；隔离 PostgreSQL 中升级与恢复验证 |
| T2 搜索与访问边界 | A；搜索/详情/相关查询 API、服务、schema | T1；可先基于 T0 写失败测试 | 公共/内部搜索、鉴权、可见性、suggest、导出和相关查询一致；版本与 release 选择正确 |
| T3 客户端与数据库界面 | B；packages/api-client、Web、必要 Admin/MCP 调用方 | T0 可做 UI 测试；真实集成等 T2 契约 | 生成客户端、数据库入口、可筛选列表、双 ID 展示、版本分组、详情及 JBrowse 全链路 |
| T4 隔离与回归 | C；scripts、e2e、CI 测试接入 | T0 可写 fixture 和隔离测试；最终运行等 T2/T3 | 双制品、泄漏负例、授权/缓存交叉访问、端到端验收与证据报告 |
| T5 总集成 | 总控；文档状态与共享冲突收口 | T1–T4 | 复查契约、生成差异、迁移顺序和完整测试，列出未通过项 |

实施波次：T0 → T1；B/C 同时准备基于冻结契约的 UI 测试和隔离场景 → T2 → T3 集成 → T4 完整验证 → T5。
API schema 由 A 唯一写入，生成客户端由 B 唯一生成；同一迁移链由 A 管理。总控负责变更契约通知，禁止并发修改同一共享文件。

各任务提交交接信息：变更文件、契约版本、行为变化、测试命令与计数、失败原因、剩余依赖。没有运行结果就写“未验证”。

## 6. 各执行者的具体要求

### A：数据与 API

- 检索模型、迁移、导入、worker/jobs、ClickHouse 投影和外键消费者；不能只改 Gene 或 MutantLine 单表。
- 公开编号唯一、发布时必填、稳定；迁移可重复执行或明确幂等边界；重复编号/孤儿映射应拒绝并报告。
- 将外部与内部响应分别序列化，外站不依赖前端删字段。内部查询按授权范围检索，不能沿用仅 is_public 的过滤而遗漏有权限的未公开记录。
- 覆盖全局搜索、自动补全、实体列表/详情、关联查询、导出、MCP 等实际暴露面；只修一个搜索接口不算完成隔离。
- 搜索区分 exact、alias、cross-version、text；版本标签来自响应数据，不能由 UI 猜测。
- 缓存包含 query、类型/筛选、分页、assembly、release 和站点上下文；内部缓存还须按授权数据范围隔离，或先禁用。site_variant 单字段不足以隔离不同权限用户。
- 分页保持稳定；cursor 必须绑定上下文，release/assembly 切换时不能复用旧分页状态。

### B：客户端与界面

- 以正式 OpenAPI 生成客户端；手改生成文件不能作为最终交付方式。
- 首页搜索可真正到达数据库命中；列表提供类型/版本及业务筛选、排序分页、空态、错误态和可分享链接。
- external 只展示公开身份；internal 明确展示两种编号及匹配字段，并处理无权限状态。
- assembly/release 贯穿请求、结果标签、详情、表达、关联变异、序列和 JBrowse；查询缓存键与服务端上下文一致。
- 无版本搜索能发现 v4/v5；已有深链不静默回落到默认版本；未知或不匹配版本返回可理解的错误。
- 不增加无数据支撑的统计值，不以演示数据伪装后端成功；沿用现有组件体系与多语言约定。

### C：隔离、测试与 CI

- 合成 fixture 包含公开/内部双 ID、未发布哨兵、无权限用户、两个不同内部权限范围、v4/v5 同名 accession、两个 release 和多种映射关系。
- 真实 PostgreSQL 验证过滤、唯一约束和外键；SQL 字符串断言只是补充。
- 在同一测试运行中交替请求外站、内站及不同权限用户，验证缓存不会扩大可见范围。
- 构建 external/internal 两套制品；检查 HTML、JSON、manifest、source map、Service Worker 和导出中的具体保护值，并验证测试数据实际进入过构建输入。
- 扫描器绿色不代表双站安全完成；另外检查 internal 访问控制、private/no-store、origin/CORS 和 Service Worker 隔离。
- 先运行窄测试，再运行相关质量门禁和端到端流程；记录真实计数，不用 skip/xfail 或仅语法解析替代关键场景。

## 7. 验收流程与完成标准

先核验 package.json、服务 pyproject 和脚本入口。当前声明版本为 Node 24、pnpm 11.21.0、Python >=3.14。
在原生可用工作区执行；SMB 下虚拟环境和依赖链接若失效，应修复隔离开发环境，不反复把无法启动当测试失败或通过。

推荐入口（各代码块注明工作目录；新增测试须一起纳入）：

```bash
# 仓库根目录
node --version
pnpm --version
python3 --version
git status --short
pnpm --filter @soymutdb/api-client check:contract
pnpm --filter @soymutdb/api-client exec vitest run src/search.test.ts
pnpm --filter @soymutdb/web exec vitest run src/routes/__tests__/genes-assembly-context.test.tsx src/components/home/__tests__/antd-home-database-entrypoints.test.tsx
python3 -m unittest scripts.test_site_artifact_isolation -v
```

```bash
# apps/api 目录；只使用隔离的测试 PostgreSQL，先核实 fixture 的建库/清理行为
.venv/bin/python -m pytest tests/test_search.py tests/test_search_contract.py tests/test_search_database_integration.py tests/test_mutants.py tests/test_genes.py tests/test_migrations.py -q
```

```bash
# 仓库根目录；窄测试通过后
pnpm lint
pnpm typecheck
pnpm test
pnpm --filter @soymutdb/web build:sites
python3 scripts/check_site_artifact_isolation.py --external-root apps/web/dist/external --internal-root apps/web/dist/internal --sentinel "$UNRELEASED_SENTINEL"
```

UNRELEASED_SENTINEL 必须与本次合成构建 fixture 的值一致且非空；禁止用不曾进入输入的随机字符串获得空扫描结果。
在 e2e 目录运行 Playwright 的 external anonymous 与 internal authenticated 测试项目；接手者先核实配置中的实际项目名。

必须满足以下结果，才可交付相应核心能力：

| 验收 | 必须证明 |
| --- | --- |
| 双 ID | 外站公开 ID 命中；内部 ID 不泄漏；内站授权后两种编号定位同一实体 |
| 权限 | 匿名/普通登录用户不能使用内部检索；内部用户不能读取权限范围外的数据 |
| 双版本 | v4/v5 同名 accession 可共存、独立精确检索；无版本查询不隐藏其中一个版本 |
| 上下文 | 搜索→详情→相关数据→JBrowse 的 assembly/release 一致，跨上下文缓存及分页不串数据 |
| 映射 | exact 与 cross-version 清晰区分；一对多、多对一和无映射行为可验证且有来源 |
| 发布边界 | 私有、删除、未发布记录不进入外站各入口、导出和制品 |
| 工程 | PostgreSQL 迁移/恢复、OpenAPI 生成一致性、前端类型检查、构建及 E2E 有运行证据 |

关键能力未实现、测试未运行或因环境跳过时，结论为“部分完成，不能发布”，并准确列明原因。
交接文档完成与产品实现完成分开记录，不使用无依据的整体完成百分比。

## 8. 可直接交给执行智能体的指令

> 先阅读 docs/dev/database-execution-handoff.md，再核验当前仓库及已有改动。按分配给你的 T 任务执行，使用总控冻结的身份、assembly/release、权限和 API 契约。不得自行变更其他任务的共享接口或覆盖未归属自己的修改。已有保护措施不能替代功能验收；双 ID、v4/v5 和内外站隔离必须通过真实流程测试。每次交付列出文件、行为、测试命令与计数、未验证项及依赖。生产迁移、回填与发布不在本交接授权范围内。

总控首轮输出应是 T0 核验记录与具体契约，而不是直接要求三个执行者各自重构。
