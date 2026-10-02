# SoyMutDB Next 系统问题、技术路线未决项与扩展审计

> **已归档（2026-10-01）**：早期调研笔记（结论已进入基线与设计）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §1.1 需求来源。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

> 日期：2026-08-17
> 方法：本地代码/测试/文档静态审计 + 仓库已有同类项目研究 + 通用行业标准知识。
> 限制：当前执行环境无法访问互联网，本文不声称完成实时全网检索；需要核验版本、许可证、活跃度的项目集中列在第 8 节。

---

## 1. 执行结论

SoyMutDB 的总体架构方向正确：FastAPI 模块化单体、PostgreSQL 权威状态、ClickHouse 科学事实、Redis 非权威协调、MinIO 不可变制品、Celery/outbox、静态优先门户、PageDefinition 控制面。这些边界不需要推翻。

当前主要风险不是“缺技术栈”，而是以下七类闭环仍不完整：

1. **真实数据层验证不足**：Alembic 0015–0017、DB-backed PageBuilder/Publication/Import 测试仍依赖 CI testcontainers，本机无真实 PG/CH/MinIO/Celery 验证。
2. **导入仍不是真正的大文件流式**：共享 reader 按行 yield，但入口先 `_read_module_bytes()` / `file.arrayBuffer()`，文件仍整体进内存；跨 chunk 唯一键仍用内存 `set`。
3. **内部/外部搜索路由仍耦合**：`/api/v1/search` 通过 Accept/format 在内部 JSON 与外部 federated HTML/JSON 间切换，违背已批准的“物理和语义隔离”方向。
4. **三个表格适配器仍是 count-only**：`seed_data/expression_csv/homolog_csv` 仍映射 `CsvUpsertAdapter`，文件读完计数即可成功，不是可靠入库证据。
5. **Admin 上传预览缺后端契约**：本地 multipart 直传已实现，但 `fetchModulePreview()` 明确返回 unavailable；没有预检表头/前 100 行/行级诊断 API。
6. **科研互操作与 FAIR 层尚未产品化**：DataCite/DOI、RO-Crate、PROV-O、Bioschemas、GA4GH/BrAPI 均停留在设计/评估阶段。
7. **MCP 状态与实现口径不清**：README 仍称 B1 skeleton/placeholder，但代码已有 rate-limit/manifest/error shaping；需要一次真实 contract/security audit，而不是继续叠功能。

---

## 2. P0：正式生产前必须解决

### 2.1 数据库/发布/恢复的真实演练

**代码事实**：CI 有 testcontainers job；本地验收仍有 77 个 Docker unavailable errors。

必须完成：
- PostgreSQL 空库 `alembic upgrade head`，确认 0015→0016→0017。
- 对可逆迁移执行 upgrade→downgrade→upgrade。
- PageBuilder、module import、StaticPublication DB-backed 测试。
- MinIO 原始对象/manifest/error report/静态制品实际写入。
- Redis broker + Celery outbox 投递/重试/幂等。
- ClickHouse facts 与 release_id 的查询/写入一致性。
- 备份→恢复→指针回滚演练。

### 2.2 导入“伪流式”问题

当前 Phase B 已有 `iter_module_rows` 与 10k 批量 INSERT，但仍存在：
- Worker `_read_module_bytes()` 整体读取本地/S3 文件。
- Admin `file.arrayBuffer()` 整体读取以计算 SHA-256。
- `DelimitedTextReader` 使用 `io.StringIO(text)`，文本整体解码在内存。
- `XlsxReader` 接受完整 bytes；openpyxl 为 read_only，但 ZIP 已整体读入。
- `seen_keys: set[str]` 随行数无界增长。

**明确技术路线**：
- S3 流/本地 file handle 作为 reader 输入，而非 bytes。
- 前端 SHA-256 用分块 Web Worker/增量哈希，或服务端完成对象 checksum 后返回可信 digest。
- 文本用 `TextIOWrapper` + `csv.reader` 流式读取。
- XLSX 先落临时文件，openpyxl read_only 从文件读取。
- 重复键检测使用 staging 唯一约束/临时表，而非内存 set。
- COPY/批量写入后统一事务 finalize。

### 2.3 count-only 适配器必须移除

证据：`apps/worker/src/soymutdb_worker/tasks/data_adapters.py` 中：
- `seed_data → CsvUpsertAdapter`
- `expression_csv → CsvUpsertAdapter`
- `homolog_csv → CsvUpsertAdapter`

路线：为三类定义 schema key、唯一键、引用检查、真实 PostgreSQL writer、幂等/回滚证据；禁止“rows=len(file) 即 ready”。

### 2.4 搜索 API 分离

现状：`apps/api/app/api/v1/search.py` 同一路由根据 `Accept`/`format` 决定内部 DB JSON 或外部 federated 结果。

建议：

```text
GET /api/v1/search/internal   # release-pinned local facts/static index
GET /api/v1/search/external   # NCBI/UniProt/Ensembl/EBI adapters
```

兼容期保留 `/search` adapter，但前端与新客户端迁到两个显式 endpoint。缓存、超时、cursor、provenance、错误语义分别定义。

### 2.5 发布制品桶与远程发布实测

未决：`SOYMUTDB_PUBLICATION_ARTIFACT_BUCKET` 存在于 config/env，但三 adapter 未消费。

需要 ADR 二选一：
- **S3 artifact bucket 为统一 staging authority**：local/GitHub/Cloudflare 都从同一 digest artifact 拉取；推荐。
- **adapter 各自 stage**：删除无消费者字段，避免假配置。

并完成 GitHub/Cloudflare sandbox 实际 dispatch/upload/promote/rollback。

---

## 3. P1：技术路线尚不明确

### 3.1 Schema 治理：Python registry 还是通用 schema-as-code

当前：Python dataclass/Pydantic registry，适合近期快速演进。

未决：第二物种、外部数据提供方和几十种 module 增长后，是否引入：
- JSON Schema（交换/表单/验证）
- LinkML（生物数据 schema、文档/代码生成）
- Frictionless Data Table Schema（表格资源包）

建议：先保持 Python authority，同时生成只读 JSON Schema；只有外部协作需求明确后再做 LinkML ADR，避免双权威。

### 3.2 高体量事实边界

未决问题：哪些数据进入 PostgreSQL、ClickHouse、Parquet/S3？

建议边界：
- PostgreSQL：治理、身份、release、mapping、审计、摘要、少量规范对象。
- ClickHouse：高体量变异/表达聚合与分析事实，必须带 dataset/release scope。
- Parquet/S3：下载、离线分析、不可变快照；可用 DuckDB/Polars 生成，不成为权威写库。

需建立按物种/assembly/release 的容量模型和查询基准后再调整。

### 3.3 PageBuilder 的单一真相

已对齐 shared DTO，但仍有两份 renderer registry：后端安全 registry 与前端 React renderer map。

建议：
- 构建期生成 `registry-contract.json`，包含 component key/config schema/renderer key/hash。
- 前端 build 检查 published component key 完整覆盖。
- PageDefinition 记录 `registry_version/config_hash`。
- Admin 增加版本 diff、审批、回滚影响预览、未使用组件清理。

### 3.4 工作流执行层

当前 Celery + outbox 足够，不需引入 Temporal/Prefect/Airflow。

触发重新评估的证据：
- 跨日/人工步骤工作流大量增加；
- compensation 复杂；
- Celery 状态恢复/可视化无法满足 SLO；
- 需要可重放的确定性 orchestration。

无证据前继续 Celery/outbox。

### 3.5 部署路线

当前 Compose 主路径 + conda 备选可继续。

Kubernetes/Nomad 只有在以下出现时评估：多节点调度、自动扩缩、隔离 GPU/高内存 worker、多租户、明确 HA SLO。否则 systemd/Compose 成本更低。

---

## 4. P1：科研标准与产品扩展

### 4.1 GA4GH 互操作试点

可扩展：
- **refget**：按 digest 获取参考序列，改善 assembly/reference identity。
- **htsget**：大规模序列/变异切片传输。
- **Beacon v2**：标准化 variant/genomic discovery 接口。

建议先做只读 adapter/proof-of-concept，不替代现有 REST。

### 4.2 BrAPI

对种质、表型、试验、育种材料有价值。当前 seed request/inventory 较轻，若项目进入种质资源/田间表型合作，BrAPI v2 adapter 比自定义 API 更可扩展。

### 4.3 FAIR 与引用

需要落地：
- release CITATION 与机器可读 citation JSON。
- DataCite metadata/DOI（可选；无 DOI 使用稳定 release URL）。
- RO-Crate 描述原始输入、工具、参数、生成制品、许可、人员/机构。
- W3C PROV-O 或简化 PROV JSON 映射。
- Bioschemas Dataset/DataCatalog JSON-LD。
- SPDX/LicenseRef 许可 inventory；组合下载许可冲突门禁。

### 4.4 第二物种 walking skeleton

当前多物种主要是架构承诺。应选一个真实第二物种，以最小数据跑通：Taxonomy→assembly→gene/annotation→module import→search→JBrowse→manifest→citation→rollback。否则多物种抽象仍未被证实。

### 4.5 模块插件化

可把 module 定义扩展为：
- schema/config
- importer/validator
- API query provider
- PageBuilder renderer/data binding
- publication/export manifest contributor

但插件只能由服务端注册/签名包安装，不能让 Admin 上传任意代码。

---

## 5. UI/Admin/体验问题

### 5.1 导入预览仍缺失

Admin 已有 multipart 本地直传，但 `fetchModulePreview()` 明确返回 unavailable。

应实现：
- `POST /admin/modules/{key}/validate`
- 表头、sheet、前 100 行、格式/编码、sample diagnostics
- 完整错误报告 CSV/XLSX 下载
- `validation_evidence` 在任务详情可见

### 5.2 大数据表性能

仓库已有 `@tanstack/react-virtual`，但需核查基因/变异/审计/Admin 大表是否实际启用。建议建立 >10k 行浏览基准、服务端 cursor、虚拟化、列固定/隐藏、导出异步化。

### 5.3 PageBuilder 操作治理

缺少或需增强：
- 可视化版本 diff
- requester/approver 分离 UI
- 预览 URL/截图证据
- 未发布草稿恢复
- dependency impact（删组件会影响哪些 route）
- registry/schema 版本不兼容提示

### 5.4 i18n 与可访问性

已有 en/zh 和 WCAG 基础；需补：
- 翻译 key 完整性 CI
- 管理端关键文案去硬编码
- WCAG 2.2 AA live axe（非仅 static server）
- 图表表格的文本替代、下载版数据
- locale lazy-load TODO 收敛

### 5.5 设计系统

不建议再引入第二套 React 组件库或通用兼容层。推荐只做 CSS/design-token 层统一：AntD token ↔ Tailwind variables ↔ charts；第三方设计规范只能作为参考或 token 输入。

---

## 6. 质量、安全、治理问题

### 6.1 测试缺口

- 77 个 DB/testcontainers 错误需 CI 跑通。
- e2e 仍有 2 个 live API skip（BLAST 完成结果/JBrowse deep link）。
- 缺少 property-based/fuzz：CSV quoting、Unicode、XLSX ZIP、schema boundary。
- 缺少 load：100k/2M 导入、search P95、publication concurrent promotion。
- 缺少 chaos：Redis/Celery/MinIO/ClickHouse 短暂故障、CAS 后 smoke 失败。

### 6.2 导入安全

已有限制，但仍需：
- 真实 ZIP 解压总量/压缩比门禁（不能只检查 magic）。
- XLSX external links、公式缓存、merged header 策略。
- CSV formula injection 仅在输出/下载报告时处理。
- S3 presign key/Content-Type/size 与 complete 后 HEAD 再校验。
- 临时文件权限、清理、病毒扫描策略（ClamAV 仅在风险/运营要求明确时引入）。

### 6.3 MCP

README 与代码状态不一致，应冻结 MCP v1 contract：
- read/write tool scopes
- user/job ownership绑定
- audit event
- response size/timeout/cursor
- tool schema version
- Redis limiter failure模式
- prompt/tool injection 与 SSRF边界

MCP 只是 API adapter，不能形成第二领域层。

### 6.4 供应链

建议 CI 强制：
- Python/Node lock 完整性
- SBOM（CycloneDX/SPDX）
- 镜像签名与 provenance（SLSA/in-toto 方向）
- secret scan、license scan
- GitHub Actions SHA pin
- release artifact checksum/signature

---

## 7. 90 天建议路线

### 0–30 天（生产证据）

1. CI 跑通 0015–0017 + 所有 DB-backed 测试。
2. 真实 MinIO/Redis/Celery/ClickHouse 集成和备份恢复。
3. 把导入改成文件句柄级真流式；staging unique constraint 去掉内存 set。
4. 实现导入 preview/diagnostics API。
5. 分离 internal/external search endpoints。
6. 决策并接入/删除 publication artifact bucket。
7. 冻结 MCP v1 contract 或明确下线未完成写工具。

### 31–60 天（科研治理与性能）

1. 移除三类 count-only adapter。
2. 第二物种 walking skeleton。
3. Citation/License/RO-Crate 最小实现。
4. 大表 cursor/virtualization 和容量基准。
5. PageBuilder diff/approval/impact preview。
6. import/publication/search metrics + alert。

### 61–90 天（互操作与平台扩展）

1. GA4GH refget/Beacon 只读 PoC。
2. BrAPI 种质/表型 adapter 可行性验证。
3. Parquet/RO-Crate release package。
4. 根据 SLO 决定是否需要 K8s/工作流引擎/搜索引擎 ADR。

---

## 8. 需要实时联网核验的清单

当前环境无法核验以下项目的最新版本、许可证、活跃度与安全公告；应在网络环境中逐项查官方源：

### 科研标准/项目
- GA4GH Beacon v2、refget、htsget 当前规范与 conformance tests
- BrAPI v2 当前版本与客户端生态
- RO-Crate specification/current profiles
- DataCite Metadata Schema/current DOI API
- Bioschemas Dataset/DataCatalog profiles
- W3C PROV-O 最新 recommendation/implementation notes
- LinkML、Frictionless Data 当前版本/许可证
- LegumeInfo datastore specifications、SoyBase/Gramene/Alliance 当前发布架构
- JBrowse 2 当前 LTS/安全公告

### 工程/安全
- SLSA current level/spec、in-toto、Sigstore/Cosign
- CycloneDX/SPDX tooling
- Syft/Grype/Trivy 当前支持与许可证
- OpenTelemetry Python/JS/Celery instrumentations
- Temporal/Prefect/Airflow 当前版本（仅触发 ADR 时比较）
- MiniSearch/FlexSearch/Lunr 当前维护状态（仅 Internal Search ADR）

核验输出必须记录：官方 URL、检索日期、版本、许可证、最近 release、维护活跃度、CVEs、与本项目的明确适配/不适配结论。

---

## 9. 最高价值的下一步

若只选三项：

1. **真实数据层/恢复演练**：决定是否可生产。
2. **真流式导入 + preview/diagnostics**：决定数据规模和管理员可用性。
3. **内部/外部搜索拆路由 + 第二物种 walking skeleton**：验证产品架构而不是只验证代码结构。
