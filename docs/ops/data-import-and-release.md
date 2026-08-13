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

## Release 组装、发布与回滚

1. 创建 draft Release，指定 name、assembly 和理由。
2. 组合七类数据集，确认全部为 `ready`，生成包含版本、来源、工具、checksum 和引用的 manifest。
3. 确认 BLAST/JBrowse/下载对象可用且无失败任务，进入 ready。
4. 单管理员确认理由；事务内切换 PostgreSQL `active_release` 指针并写 release/audit。
5. 提交后触发 JBrowse bundle 构建和 smoke；门户搜索、API、JBrowse、BLAST、下载使用同一 active release。

状态为 `draft → validated → ready → published → rolled_back`。发布加行锁阻止并发切换；任一组件未 ready
不得发布。回滚切回上一 active release，记录 `rolled_back_at`、理由和审计。ClickHouse schema 迁移可能
不可逆；遇到此类故障停止自动回滚，转人工恢复并使用完整备份。

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
