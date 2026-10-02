# 多格式表格导入生产完善计划（TXT / TSV / CSV / XLSX）

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 日期：2026-08-17
> 状态：待执行的生产加固方案
> 当前基线：txt/tsv/csv/xlsx 已贯通共享解析器、API、Worker、Admin UI、模板下载与 OpenAPI；本地验证通过。

---

## 1. 当前完成状态

### 已完成

- `.txt` / `.tsv`：UTF-8 + Tab 分隔。
- `.csv`：UTF-8 + 逗号分隔，支持标准 CSV 引号。
- `.xlsx`：openpyxl `read_only=True`，读取首个 worksheet，首行作为表头。
- 共享校验器：`packages/jobs-py/src/soymutdb_jobs/module_schema.py`。
- 模板下载：`GET /api/v1/admin/modules/{module_key}/template?format=...`。
- Admin 表单：`module_tsv` 类型、扩展名校验、module_key/checksum、模板格式选择。
- Worker：格式感知解析、release-scoped `module_data_rows` 写入、DataSet evidence/manifest。
- API 14 个格式测试通过；Worker 本地补 openpyxl 后 14 个 adapter 测试通过。

### 仍不够生产级的地方

1. 解析器把全部行加载到内存；`max_rows=2,000,000` 与当前实现不匹配。
2. Worker 逐行 `INSERT`，大文件性能和事务时间不可接受。
3. Admin 仍要求用户先给 S3 URI，没有完整“选择本地文件 → multipart 直传 → 预览 → 导入”体验。
4. 行级诊断只在校验结果内短暂存在，未形成可下载、可审计的错误报告。
5. XLSX 只读首个 worksheet，无 sheet 选择、隐藏 sheet/公式/合并单元格策略。
6. CSV/TXT 未做 BOM、分号方言、编码探测；扩展名与 MIME/文件签名未交叉校验。
7. `seed_data/expression_csv/homolog_csv` 仍有 count-only `CsvUpsertAdapter` 路径，未统一到 schema-driven 实际写库链。
8. DB-backed 导入/回滚仍需 CI testcontainers 或真实 conda 数据层验证。

---

## 2. 总体目标

```text
本地选择文件
  → 格式/MIME/大小/压缩比预检
  → multipart 直传 MinIO
  → 预览表头/worksheet/前 100 行
  → 严格 schema 校验（流式、行级诊断）
  → release-scoped staging + COPY/批量写入
  → referential/count/checksum 门禁
  → DataSet ready + evidence + error report
  → static_publish_requested
  → 不可变构建/发布
```

原则：

- API v1 继续保留 `type=module_tsv`，避免破坏兼容；其语义升级为“schema-driven tabular module import”。
- 默认支持 `.txt/.tsv/.csv/.xlsx`；明确拒绝 `.xls/.xlsm`（旧二进制/宏安全风险）。
- 任何失败不暴露部分公开数据，不改变 active release。
- 原始对象、checksum、schema version、解析参数与诊断报告必须可追溯。

---

## 3. Phase A：运行环境与安全预检（P0）

### A1. Worker 依赖可用性门禁

**修改：**
- `apps/worker/src/soymutdb_worker/main.py` 或新建 `startup_checks.py`
- `apps/worker/tests/test_startup.py`
- `deploy/conda/README.md`

**任务：**
- Worker 启动时检查 `openpyxl`；缺失时：
  - `.xlsx` capability 标为 unavailable；
  - 健康/诊断输出明确提示；
  - txt/tsv/csv worker 仍可启动。
- CI/构建镜像断言 `python -c "import openpyxl"`。

### A2. 文件类型安全验证

**修改：**
- `soymutdb_jobs/module_schema.py`
- `admin_imports.py`

**细节：**
- 同时校验：扩展名、MIME、magic/signature。
- XLSX 必须为 ZIP/OOXML；禁止 `.xlsm`、宏、外部链接。
- 限制：总文件大小、解压后大小、ZIP 压缩比、worksheet 数量。
- 拒绝 NUL、超长 header、空 header、重复 header、控制字符。

**验收：**
- 伪造 `evil.csv` 实际为 ZIP、伪造 `evil.xlsx` 非 ZIP 均 422。
- zip-bomb fixture 被拒绝。

---

## 4. Phase B：流式解析、批量写入与事务隔离（P0）

### B1. Reader 协议

新建共享接口：

```python
class ModuleFileReader(Protocol):
    metadata: FileMetadata
    def iter_rows(self) -> Iterator[ParsedRow]: ...
```

实现：
- `DelimitedTextReader`：txt/tsv/csv。
- `XlsxReader`：openpyxl `read_only=True` + worksheet selector。

避免：
- `list(csv.DictReader(...))`
- `rl_grid` 全量列表
- `ValidationResult.rows` 容纳百万行

### B2. 两阶段校验

1. **结构预检**：格式、表头、schema version、worksheet。
2. **流式行校验**：类型、范围、唯一键、引用。

输出：
- `ValidationSummary`
- 最大 200 条 inline diagnostics
- 完整错误报告对象（CSV/XLSX）存 MinIO

### B3. 批量写入

**修改：**
- `module_import_service.py`
- Worker adapter/repository

**实现：**
- PostgreSQL COPY 或 `insert(...), batch_size=5_000–20_000`。
- 不逐行执行 `session.execute()`。
- staging transaction_id / dataset_id 隔离；失败只清理当前 staging。
- 同 checksum 重试直接返回原 DataSet；不同 checksum 的同 release/module 明确 conflict。

**性能门：**
- 100k 行：解析+写入 < 60s（目标机基准）。
- 常驻内存 < 512MB。
- 2M 行不发生 OOM。

---

## 5. Phase C：XLSX 与 CSV 细节完善（P1）

### C1. Worksheet 策略

新增请求字段：

```json
{
  "sheet_name": "genes",
  "header_row": 1
}
```

规则：
- 单 worksheet：自动选择。
- 多个非空 worksheet：要求显式选择或使用 schema 同名 sheet。
- 隐藏 worksheet 默认不可选。
- 合并 header 单元格拒绝。
- 公式默认读取 `data_only=True`；无缓存值时报 `formula_without_cached_value`。

### C2. 文本方言

- UTF-8 / UTF-8 BOM (`utf-8-sig`)。
- CRLF/LF。
- CSV `,`；可选 `;`，但必须由显式参数或可靠 sniff 决定。
- TXT 默认 Tab，不做“盲猜任意分隔符”。
- 防 Excel/CSV formula injection：导出诊断/模板时前缀处理 `=,+,-,@`。

### C3. 模板增强

XLSX 模板：
- 冻结首行。
- 必填列着色/批注。
- 第二 sheet `README`：schema version、类型、空值规则、示例。
- 不添加宏/公式。

---

## 6. Phase D：Admin 上传、预览与诊断 UX（P1）

### D1. 直传流程

替换“仅填写 S3 URI”为：

```text
选择文件 → multipart presign → 浏览器直传 → complete → validate preview → submit import
```

保留高级模式：管理员可输入已存在的 S3 URI。

### D2. 预览 API

新增：

```text
POST /api/v1/admin/modules/{module_key}/validate
GET  /api/v1/admin/imports/{id}/diagnostics
GET  /api/v1/admin/imports/{id}/diagnostics/download?format=csv|xlsx
```

预览返回：
- format / sheet / delimiter / encoding
- headers
- 前 100 行（经过脱敏与长度限制）
- row_count estimate
- validation summary / sample errors

### D3. Admin UI

- 拖拽/文件选择，`accept=.txt,.tsv,.csv,.xlsx`。
- Sheet 选择器（仅 xlsx）。
- 表头预览和 required/unknown 标记。
- 行级错误表：row / column / code / message。
- 下载完整诊断 CSV/XLSX。
- 任务详情展示 validation_evidence、源 checksum、schema version、解析参数。

---

## 7. Phase E：统一其它表格导入（P1）

目标：移除“计数即成功”的通用 `CsvUpsertAdapter`。

逐个迁移：

| 现有类型 | 目标 schema key | 持久化 |
|---|---|---|
| `seed_data` | `seed_inventory` | PostgreSQL upsert |
| `expression_csv` | `expression` | PostgreSQL/COPY |
| `homolog_csv` | `homolog` | PostgreSQL/COPY |

要求：
- 每类拥有明确列定义、唯一键、引用检查、版本。
- 支持同样的 txt/tsv/csv/xlsx 输入能力。
- 删除/禁用 count-only 成功路径。

---

## 8. Phase F：可观测性、审计与发布一致性（P2）

### Metrics

- `module_import_rows_total{module,format,status}`
- `module_import_duration_seconds{stage,format}`
- `module_import_errors_total{code}`
- `module_import_rows_per_second`

### Evidence

DataSet / ImportTask 保存：

```json
{
  "format": "xlsx",
  "sheet_name": "genes",
  "encoding": null,
  "delimiter": null,
  "schema_key": "genes",
  "schema_version": 1,
  "source_sha256": "...",
  "source_size": 123456,
  "rows_seen": 100000,
  "rows_inserted": 100000,
  "error_report_object": null,
  "parser_version": "1"
}
```

审计事件：upload complete / validate / ingest / ready / fail / retry / publish。

---

## 9. 测试矩阵

### 单元/属性测试

- 四格式相同数据得到相同 typed rows。
- UTF-8 BOM、引号、逗号内嵌、CRLF、空单元格。
- XLSX 多 sheet、隐藏 sheet、公式、合并 header。
- 大小写扩展名。
- 非法 MIME/signature、zip bomb。
- 重复键跨 chunk 仍被发现（磁盘/DB 临时唯一表，不能只用内存 set）。

### 集成测试

- API multipart → worker → PG module_data_rows → DataSet ready。
- 失败不留下 staging rows。
- checksum 幂等重试。
- static_publish_requested payload 正确。

### E2E

- Admin 下载 TSV/CSV/XLSX 模板。
- 上传四格式并预览。
- 非法文件展示 row diagnostics。
- 完成后页面发布并绑定同一 release。

---

## 10. 同步修改清单

每次新增格式/字段必须同步：

- `packages/jobs-py/module_schema.py`
- `apps/api` service/router/schema/tests
- `apps/worker` adapter/task/dependency/tests
- `apps/admin` imports UI/i18n/tests
- `packages/api-client` OpenAPI + generated types
- `deploy/conda/environment-worker.yml`
- Worker Docker/CI dependency installation
- `README.md`、`docs/user`、`docs/ops`
- backup/restore manifest（原始文件与诊断对象）
- observability dashboards/alerts

---

## 11. 推荐实施顺序与工期

| 阶段 | 内容 | 预计 |
|---|---|---|
| A | 依赖门禁 + 文件安全预检 | 1–2 天 |
| B | 流式 reader + 批量写入 + staging | 3–4 天 |
| C | XLSX/CSV 细节 | 2 天 |
| D | Admin 直传/预览/诊断 | 3–4 天 |
| E | expression/homolog/seed 统一 | 3–5 天 |
| F | metrics/audit/e2e/docs | 2–3 天 |

优先级：**A+B（安全与可扩展性并行） > D（真实用户闭环） > E（清除 count-only） > C/F**。
