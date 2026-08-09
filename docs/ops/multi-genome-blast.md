# 多基因组 BLAST 与 GWAS 运维说明

> 归属：B5（P0 科研功能）。本文档是**运维侧**的操作手册：代码侧已就绪的
> 多基因组 BLAST 索引白名单（worker `BLAST_DATABASE_PATHS`）与 GWAS
> 引擎执行（`emmax` / `gemma` 二进制），数据准备与二进制安装都在**部署侧**
> 完成。前端/后端代码无需随新组装改动。

## 1. 多基因组 BLAST（worker 侧）

### 1.1 配置：`SOYMUTDB_BLAST_DATABASE_PATHS`

worker 读取 `SOYMUTDB_BLAST_DATABASE_PATHS`（JSON 对象，`数据库名 → 本地
索引基名`）。配置后它是**唯一白名单**：不在其中的数据库名（含路径穿越
payload）在触碰文件系统/S3 之前就被拒绝。

```bash
# docker-compose / worker 环境变量示例
SOYMUTDB_BLAST_DATABASE_PATHS='{
  "wm82.a2.v1": "/data/genomes/wm82.a2.v1/wm82.a2.v1",
  "zh13.a1.v1": "/data/genomes/zh13.a1.v1/zh13.a1.v1",
  "w05.a1.v1":  "/data/genomes/w05.a1.v1/w05.a1.v1"
}'
```

- 值是 `makeblastdb` 输出的**索引基名**（`-db` 参数），不是 `.fasta` 文件
  路径（支持 `{assembly}/{assembly}.fasta` 布局）。
- 不配置（留空 `{}`）时回退到旧的单基因组模式：`blast_databases` 表中
  `file_path` 对应的缓存 + S3 下载（`blast-dbs/` 前缀）。
- API 侧 `blast_databases` 表需先有与键同名的行（`GET /api/v1/blast/databases`
  列表来自该表，`assembly_id` 关联 `assemblies`）。默认库可用
  `SOYMUTDB_BLAST_DEFAULT_DB` 指定。

### 1.2 新组装接入流程（checklist）

1. 将组装 fasta 放到 worker 宿主机的固定目录（如 `/data/genomes/`）。
2. 建索引：

   ```bash
   cd /data/genomes/wm82.a2.v1
   makeblastdb -in wm82.a2.v1.fasta -dbtype nucl -out wm82.a2.v1 \
     -title "Glycine max Wm82.a2.v1"
   ```

   （蛋白数据库用 `-dbtype prot`，供 blastp/tblastn。）
3. 确认索引文件与 worker 进程同机可读，worker 用户对目录有 `r-x`。
4. 在 API 的 `blast_databases` 表插入一行：

   ```sql
   INSERT INTO blast_databases (name, db_type, assembly_id, file_path, is_active)
   VALUES ('wm82.a2.v1', 'nucl', <assembly_id>, '/data/genomes/wm82.a2.v1/wm82.a2.v1', true);
   ```

5. 在 worker 环境变量中加入 `SOYMUTDB_BLAST_DATABASE_PATHS` 对应条目，
   重启 worker。
6. 验证：`GET /api/v1/blast/databases` 出现新库；提交一个 blastn job 命中
   该库（`database_id` 或 `database` 名称）。

## 2. GWAS（EMMAX / GEMMA）——worker 侧

### 2.1 二进制安装（运维必须）

**EMMAX / GEMMA 二进制不随 worker 镜像分发**，worker 假定它们在
`PATH` 或 `SOYMUTDB_GWAS_BIN_DIR`（默认 `/usr/local/bin`）中。缺失时任务
以清晰错误失败（job 状态 → failed），不会静默。

```bash
# GEMMA（Linux x86_64，官方 release 解压即可）
wget https://github.com/genetics-statistics/GEMMA/releases/download/v0.98.5/gemma-0.98.5-linux-static
install -m 0755 gemma-0.98.5-linux-static /usr/local/bin/gemma
gemma -h   # 验证

# EMMAX（源码编译，需要 gfortran + BLAS/LAPACK）
git clone https://github.com/tanghaibao/emmax.git /opt/emmax
cd /opt/emmax && make
install -m 0755 emmax /usr/local/bin/emmax
emmax -v -h  # 验证
```

验证：在 worker 容器/主机执行 `gemma -h`、`emmax -v` 有输出且退出码为 0。

### 2.2 worker 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `SOYMUTDB_GWAS_BIN_DIR` | `/usr/local/bin` | 引擎二进制目录 |
| `SOYMUTDB_GWAS_MAX_RUNTIME` | `3600` | 引擎子进程墙钟超时（秒） |
| `SOYMUTDB_GWAS_MAX_MEMORY_MB` | `8192` | 引擎子进程内存上限（MB） |
| `SOYMUTDB_GWAS_MAX_INPUT_SIZE` | `524288000` | 单输入文件上限（字节） |
| `SOYMUTDB_GWAS_MAX_OUTPUT_SIZE` | `536870912` | 单输出文件上限（字节） |
| `SOYMUTDB_S3_GWAS_BUCKET` | `gwas` | MinIO 桶（输入 `gwas/{job}/input/`，输出 `gwas/{job}/output/`） |
| `SOYMUTDB_GWAS_MAX_ATTEMPTS` | `3` | API 侧投递重试上限 |

MinIO 桶需预创建（`mc mb gwas` 或 compose 初始化脚本），API 与 worker
共享同一 S3 配置。

### 2.3 输入格式（API 上传 → worker 执行）

- 表型文件：单列/两列（样本 ID + 表型），扩展名 `.pheno/.trait/.txt/.tsv/.csv`。
- 基因型文件：可选；EMMAX 用 TPED（`-t`），GEMMA 支持 `-t`/`-bfile`。
- 亲缘矩阵（`.kin/.cXX.txt/.rel`）与协变量（`.cov`）：可选，GEMMA 提供
  亲缘时自动走 LMM（`-lmm 4`）。
- 表型/基因型文件**格式校验在 worker 解析阶段完成**（含输入大小上限），
  API 侧只做扩展名白名单 + 键命名空间校验。

### 2.4 结果产物（MinIO `gwas/{job_id}/output/`）

| 对象 | 内容 |
|---|---|
| `manhattan.json` | 染色体分桶的 -log10(p) 点数据（`chromosomes/points/thresholds`） |
| `qq.json` | 期望 vs 观测 -log10(p) + `lambda_gc` |
| `Manhattan_QQ.html` | 自包含 Plotly 报告（CDN） |
| `assoc.{method}.tsv` | 解析后的关联结果（snp/chr/pos/p/beta/se/af） |

API `GET /api/v1/gwas/{job_id}/results` 返回上述对象的 presigned URL
（1 小时有效）。

### 2.5 注意

- 引擎任务路由到 `analyses` 队列（`soymutdb_worker.tasks.gwas.*`），
  部署时需有消费该队列的 worker 进程（与 fastp/scanpy 同一队列）。
- 结果保留策略沿用 outbox/结果 TTL 约定；`gwas/` 桶内过期对象由
  `cleanup` 任务按需清理（当前依赖 S3 生命周期策略或手动清理）。
