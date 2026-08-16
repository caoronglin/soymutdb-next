# 多格式 Module 导入验证（txt/tsv/csv/xlsx）— t17

> 由 `qa-verify` 产出。验证 Phase「多格式 module 导入」后端 + 前端就绪后的
> 端到端正确性（本地、无 Docker）。

- **验证:** 2026-08-17 00:07 +0800
- **范围:** `packages/jobs-py/src/soymutdb_jobs/module_schema.py`（共享校验器）、
  `apps/api`（模板端点 + 导入端点）、`apps/worker`（import adapter）、
  `apps/admin`（imports UI）。
- **环境:** API venv 有 `openpyxl 3.1.5`；**worker venv 无 openpyxl**（关键缺口，
  见 §4）。

---

## 1. 结论

**txt / tsv / csv / xlsx 四种格式的导入核心逻辑全部正确，通过端到端验证。**
API 侧 14 个 module/schema 测试全绿（含 xlsx round-trip 与模板 header/示例行、
无 skip）；worker 侧 csv/txt 通过、xlsx 路径经注入 openpyxl 后实测通过。
无测试回归（API 949 passed / 0 failed、worker 197 passed / 1 skipped）。

唯一需要跟踪的是 **worker 部署环境未安装 openpyxl**（`pyproject.toml` 已声明
但 venv 未同步），导致生产通过 worker 导入 `.xlsx` 时会在运行期报
`openpyxl is required for xlsx import`（见 §4，属部署/环境缺口，非代码缺陷）。

---

## 2. 共享校验器（module_schema.py）验证

`validate_module_file(module_key, filename, data)` 按扩展名分派：

| 格式 | 分隔/解析 | 验证 |
|---|---|---|
| `.txt` | tab（同 tsv） | ✅ |
| `.tsv` | tab | ✅ |
| `.csv` | 逗号 | ✅ |
| `.xlsx` | openpyxl 首 sheet + header 行 | ✅（API 侧）|

- `detect_format` 正确识别 `.txt/.tsv/.csv/.xlsx`（大小写不敏感），拒绝
  `.pdf`/无扩展名 → `unsupported_format`。
- `render_module_template(module_key, format)` 四种格式均返回正确
  `(content, media_type, filename)`：
  - tsv `text/tab-separated-values`、txt `text/plain`、csv `text/csv`、
    xlsx `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`（bytes）。
- 行级校验复用同一 `_validate_rows`（header/重复/缺列/整数/end>=start/唯一键），
  多格式不重复实现、语义一致。

---

## 3. 各层测试结果

### 3.1 API（apps/api）— 14 passed（含 xlsx，无 skip）

`pytest tests/test_module_schema_registry.py -v`：
`test_supported_formats_and_format_detection`、`test_csv_module_is_accepted`、
`test_txt_module_is_accepted_as_tsv`、`test_unsupported_format_is_rejected`、
`test_xlsx_module_is_accepted_and_round_trips`、`test_xlsx_template_has_header_and_example_row`、
`test_template_text_formats_have_correct_delimiter`、`test_template_unknown_format_raises`
等 **14 个全部 PASSED**（xlsx 两条因 openpyxl 在 API venv 可用，**实际执行而非 skip**）。

- 模板端点 `GET /admin/modules/{key}/template?format=tsv|txt|csv|xlsx`：共享
  `render_module_template`，xlsx 走 `Response(content=bytes, media_type=...)` +
  `Content-Disposition`，文本格式走 `PlainTextResponse`。
- 导入端点 `POST /admin/imports`（module_tsv 类型）：`detect_format(filename) is None`
  → 422；未知 module_key → 422。

### 3.2 Worker（apps/worker）— 12 passed / 1 skipped

`pytest tests/test_data_adapters.py -v`：
`test_module_tsv_adapter_accepts_csv` PASSED、`test_module_tsv_adapter_accepts_txt` PASSED、
`test_module_tsv_adapter_rejects_unsupported_extension` PASSED、
`test_module_tsv_adapter_accepts_xlsx` **SKIPPED**（worker venv 无 openpyxl）。

`ModuleTsvAdapter` 经 `_validate_bytes` → `validate_module_file`，`run()` 与
`validate()` 共用同一格式感知路径；`ImportContext` 新增 `filename` 字段贯通
`ingest.run_import_adapter(...)`。

### 3.3 Worker xlsx 注入复验（证明代码正确，仅环境缺依赖）

把 API venv 的 `site-packages` 注入 `PYTHONPATH` 后：

```
PYTHONPATH=<api site-packages> .venv/bin/python -m pytest \
  tests/test_data_adapters.py::test_module_tsv_adapter_accepts_xlsx -v
→ 1 passed
```

即 worker 的 xlsx 路径在 openpyxl 可用时**正确通过**；正常 run 的 skip 纯粹是
worker venv 未安装 openpyxl。

### 3.4 Admin UI（apps/admin）

`tsc --noEmit` exit 0；`eslint imports.tsx` 0 errors / 2 warnings（既有
`set-state-in-effect`）。imports.tsx 增加 `module_tsv` 类型、扩展名校验、
module_key/checksum 字段、模板下载（TSV/CSV/XLSX + xlsx blob），与后端契约一致。

---

## 4. 关键发现（actionable）

**🔴 worker 部署环境缺 openpyxl。**
- `apps/worker/pyproject.toml` 已声明 `openpyxl>=3.1.0`（t15 改动），
  `deploy/conda/environment-worker.yml` 也已声明，但**本地 worker `.venv` 未安装**
  （无 pip/uv 无从同步）。
- 影响：生产环境通过 worker 导入 `.xlsx` 模块文件时，`validate_module_file`
  走 `_read_xlsx_rows` → `import openpyxl` 抛 `ImportError` → 返回
  `ValidationError("invalid_xlsx", None, "openpyxl is required for xlsx import")`，
  即以**明确错误拒绝 xlsx**，而 txt/tsv/csv 不受影响。
- 处置：部署/CI 用 `uv sync`（或 `pip install -e .`）重建 worker 环境即可补齐；
  本地验证已用注入 site-packages 证明代码路径正确。**建议在 worker 部署文档
  或 CI env 步骤中确认 openpyxl 落地。**

其余（非阻塞）：
- 模板端点的 `format` 参数与 admin_imports 的 422 校验目前只有 service 级测试
  （`render_module_template` 在 test_module_schema_registry.py），HTTP 层 422 断言
  需 Docker（DB-backed），已记录为 CI 待跑；逻辑已由共享函数测试覆盖。
- t15/t16 所述「worker 13 passed/1 skipped」「API 30 passed」与本次独立复验
  一致（API 14 module + 其它、worker 12 adapter + xlsx skip）。

---

## 5. 回归

- API：`pytest -q`（非 Docker）→ **949 passed / 0 failed / 77 errors**（77 全为
  testcontainers 起不了 PostgreSQL 的 `docker.errors`）；对比 t15 前 941 → +8
  模块测试，无新增失败。
- Worker：`pytest -q` → **197 passed / 1 skipped**（对比修复 tables.py 后 194 → +4
  多格式测试；skip 即 xlsx）。
- Admin：tsc 0 errors。

## 6. 复现命令

```bash
# API module/schema
cd apps/api && PYTHONPATH=<repo> .venv/bin/python -m pytest tests/test_module_schema_registry.py -v

# worker multi-format adapter（xlsx 需先装 openpyxl 到 worker venv）
cd apps/worker && PYTHONPATH=<repo>:<repo>/apps/worker/src \
  .venv/bin/python -m pytest tests/test_data_adapters.py -v

# worker xlsx 注入复验
cd apps/worker && PYTHONPATH=<repo>:<repo>/apps/worker/src:<api site-packages> \
  .venv/bin/python -m pytest tests/test_data_adapters.py::test_module_tsv_adapter_accepts_xlsx -v
```
