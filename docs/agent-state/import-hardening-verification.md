# 多格式导入生产加固验证

日期：2026-08-17

## 结果

Phase A/B/D 的本地可验证部分通过：

- API schema/OpenAPI：33 passed（17 module schema + 16 contract）
- Worker adapter/ingest：17 passed
- Admin tsc：0 errors
- Admin Vite build：成功
- Python compile/ruff：通过

## 已验证能力

- txt/tsv/csv/xlsx 四格式仍可解析。
- UTF-8 BOM 可处理，控制字符、非法 signature、legacy OLE/宏格式可拒绝。
- xlsx 首 worksheet、worksheet 数量/可见性、openpyxl 缺失错误可处理。
- streaming reader 提供 `iter_module_rows` / `validate_module_file_streaming`，不保留全部 typed rows。
- Worker module adapter 使用 10,000 行批量 INSERT，失败在同一事务内回滚，evidence 记录 rows_seen/inserted/skipped。
- Admin 本地文件模式使用 multipart 直传；S3 URI 模式保留；preview 未实现时明确显示 unavailable，不伪造结果。

## 未在本机完成

- 真实 PostgreSQL COPY/批量写入集成测试：本机无 Docker/PG。
- 大文件性能基准（100k/2M 行）。
- Worker 独立全量重建环境：openpyxl 已写入 pyproject/conda 声明，本地 venv 已补齐验证。
- 真实 MinIO multipart + Celery broker 链路。

CI 必须补跑：Alembic 0015-0017、DB-backed import/page/publication tests、真实 worker xlsx 环境。
