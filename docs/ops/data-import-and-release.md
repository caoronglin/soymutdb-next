# 数据导入、Release 与恢复

本文描述目标操作流程，不将目标行为表述为已经完成的生产验证。实现变动时，以 Admin、OpenAPI 和
部署配置为准。

## 通用上传流程

浏览器通过 MinIO 分片直传，API 只签发预签名会话并登记对象。每次导入建立一个数据集和 `import_task`，
使用 `idempotency_key`（如 `import:{id}`）避免重复 dispatch。

```text
uploading → validating → ingesting → ready → published → rolled_back
                         ↘ failed（可重试）
```

校验失败不得 ingest；失败任务保留错误详情和进度。上传、校验、入库、审批、发布和回滚均写审计。

## 七类导入

| 类型 | 输入与校验重点 | 结果 |
|---|---|---|
| FASTA | 完整性、assembly、染色体命名、checksum | assembly/chromosome 与索引对象 |
| GFF3 | 语法、ID/Parent、与 FASTA 一致 | genes、transcripts、exons、aliases |
| VCF | header、样本、坐标、Release/assembly | ClickHouse `variant_facts`，Replacing 去重 |
| BLAST DB | FASTA、参数、`makeblastdb` 产物 | 派生索引并登记 `blast_databases` |
| Seed | 请求字段、物种/品系、库存引用 | seed 请求与库存表 |
| Expression | 样本、组织、量纲、重复键 | expression 表，冲突去重 |
| Homolog | 来源、物种、Gene ID、关系字段 | homolog 表，冲突去重 |

每个适配器更新进度和状态，记录工具版本、来源和 checksum。GWAS 对象使用 `gwas` bucket；fastp/scanpy
等分析对象使用 `analyses` bucket，由 `worker-analyses` 消费 `analyses` 队列。

## Module 数据导入（多格式）

Module（如 `genes`）数据按服务端 schema 做严格行级校验，写入 release-scoped `module_data_rows`。输入文件
支持四种格式，同一份 schema 校验逻辑由 API 与 worker 共享（`soymutdb_jobs.module_schema`）：

| 扩展名 | 分隔/结构 | 说明 |
|---|---|---|
| `.txt` / `.tsv` | 制表符 | 首行表头，原有 TSV 路径 |
| `.csv` | 逗号 | 首行表头 |
| `.xlsx` | Excel 首个 worksheet | 首行为表头；worker 需 `openpyxl` |

未知扩展名在 Admin 创建导入时返回 422（`unsupported_format`）。模板下载端点
`GET /api/v1/admin/modules/{module_key}/template?format=<tsv|csv|txt|xlsx>`（默认 `tsv`）返回对应
media type 与 `Content-Disposition` 文件：

```bash
# TSV（默认）
curl -H "Authorization: Bearer $TOKEN" \
  "http://<HOST>:8080/api/v1/admin/modules/genes/template?format=tsv" -o genes.tsv
# CSV
curl -H "Authorization: Bearer $TOKEN" \
  "http://<HOST>:8080/api/v1/admin/modules/genes/template?format=csv" -o genes.csv
# XLSX（二进制，需 worker 端 openpyxl 才能导入 .xlsx）
curl -H "Authorization: Bearer $TOKEN" \
  "http://<HOST>:8080/api/v1/admin/modules/genes/template?format=xlsx" -o genes.xlsx
```

Admin「Data Imports」页在创建 Module Data 导入时校验扩展名（`.tsv`/`.txt`/`.csv`/`.xlsx`），并提供
模板下载入口（Module Key + TSV/CSV/XLSX 格式选择）直接拉取对应模板。

## Release 组装、发布与回滚

1. 创建 draft Release，指定 name、assembly 和理由。
2. 组合七类数据集，确认全部为 `ready`，生成包含版本、来源、工具、checksum 和引用的 manifest。
3. 确认 BLAST/JBrowse/下载对象可用且无失败任务，进入 ready。
4. 单管理员确认理由；事务内切换 PostgreSQL `active_release` 指针并写 release/audit。
5. 提交后触发 JBrowse bundle 构建和 smoke；门户搜索、API、JBrowse、BLAST、下载使用同一 active release。

状态为 `draft → validated → ready → published → rolled_back`。发布加行锁阻止并发切换；任一组件未 ready
不得发布。回滚切回上一 active release，记录 `rolled_back_at`、理由和审计。ClickHouse schema 迁移可能
不可逆；遇到此类故障停止自动回滚，转人工恢复并使用完整备份。

## 静态发布（不可变多目标）

Release 就绪后，静态门户可发布到三目标之一（`local` / `github_pages` / `cloudflare_pages`）。发布是一条
不可变制品 + 目标状态记录，状态 `requested → building → validating → deploying → published`，失败进入
`failed`，被更新请求覆盖进入 `superseded`，发布后可 `rolled_back`。

1. 在 Admin 发布面板选择目标并发起请求（`POST /api/v1/admin/publication/request`），传入 `release_id`
   与可选 `page_definition_version`；服务端分配目标作用域单调 `publication_id` 并派发构建任务。
2. worker 生成全新制品树 `dist/releases/<release-id>/<digest>/`，写 `manifest.json`（逐文件 SHA-256），
   校验摘要与静态树（`validate-static-tree.ts`）后调用目标适配器 stage → verify → promote。
3. 晋升前校验该 `publication_id` 是否仍是目标最新请求；过期则标记 `superseded`，绝不覆盖新指针。
4. 回滚 `POST /api/v1/admin/publication/{id}/rollback` 恢复上一条已发布制品（按 `remote_id` 与不可变 artifact）。

失败/陈旧发布不改变当前发布指针；发布与回滚写结构化审计。凭据只从 env 读取，不落库、不进 API 响应。
GitHub Pages 目标借助 `.github/workflows/pages.yml` 的 `workflow_dispatch`（输入 `publication_id` /
`artifact_url` / `manifest_digest`）完成下载→摘要校验→烟雾→单次提交→更新 ref。

## 备份、恢复与验证

默认 bucket 至少为 `genomic-data user-tracks blast-dbs exports gwas`。`analyses` 若按保留策略认定为可重建
临时数据，可不纳入默认集合，但必须在脚本注释和运维记录中明确，不得静默遗漏。备份生成 manifest、对象
清单、policy 和 SHA-256。

```bash
bash deploy/scripts/backup.sh
TARGET=drill bash deploy/scripts/restore.sh /opt/soymutdb/backups/<backup>.tar.gz
bash deploy/scripts/verify-restore.sh /opt/soymutdb/backups/<backup>.tar.gz
```

恢复顺序为 PostgreSQL → ClickHouse → S3；S3 按 manifest 动态恢复，`gwas` 使用 overwrite/remove。Redis
为可重建状态，不作为权威备份。验证未全部通过前不得宣布恢复完成。

## 升级与故障排查

```bash
docker compose --env-file deploy/.env.example config
sudo bash deploy/scripts/upgrade.sh
docker compose ps
docker compose logs --tail 100 api worker-analyses mcp-server
bash deploy/scripts/healthcheck.sh
```

升级前应检查 API、worker、MCP 的显式 tag manifest。回滚服务集合覆盖
`api migrate worker-default worker-analyses worker-blast worker-ingest beat mcp-server nginx`。

| 症状 | 处理 |
|---|---|
| validating 卡住 | 查 `error_detail`、checksum 和适配器日志；修正输入后重试，不跳过校验。 |
| analyses 积压 | 查 broker、路由、`worker-analyses` 健康和 `analyses` bucket 权限。 |
| gwas 对象缺失 | 核对 `S3_GWAS_BUCKET=gwas`、manifest 和 policy，勿指向 `analyses`。 |
| Release 不能 ready | 检查七类数据集、assembly、manifest、派生对象和失败任务。 |
| 恢复验证失败 | 保留原备份和输出，重新核对 manifest、对象 checksum 与数据库快照。 |
