# 多基因组蛋白比对与 GWAS 运维说明

> 归属：B5（P0 科研功能）。本文档是**运维侧**的操作手册：代码侧已就绪的
> 多基因组 BLAST 索引白名单（worker `BLAST_DATABASE_PATHS`）与 GWAS
> 引擎执行（`emmax` / `gemma` 二进制），数据准备与二进制安装都在**部署侧**
> 完成。前端/后端代码无需随新组装改动。

## 1. 多基因组蛋白比对（worker 侧）

> 本部署**只有一个引擎和一个程序**：DIAMOND `blastp`（蛋白查询 vs 蛋白库）。
> NCBI BLAST 已从代码、镜像与 conda 环境中移除，不再有引擎选择、回退或按程序
> 路由。核酸比对（`blastn` / `tblastx` / `tblastx`）与蛋白对核酸的 `tblastn`
> 均不可提交。`word_size` / `dust` / `soft_masking` 是已退役的 NCBI 选项，
> 显式传入会被拒绝而不是被静默忽略。

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

- 值是 `diamond makedb` 输出的 `.dmnd` **索引基名**（去掉后缀），不是
  `.fasta` 文件路径（支持 `{assembly}/{assembly}.fasta` 布局）。
- 必须是 `.dmnd` 且非空。`makeblastdb` 的产物（`.pin/.phr/.psq`）**不是**
  DIAMOND 索引，worker 会以 `DatabaseIndexUnavailable` 拒绝。
- 不配置（或显式 `{}`）时使用 legacy 模式：按数据库名称解析本地缓存和
  S3 的 `blast-dbs/` 前缀，只接受精确的 `blast-dbs/<name>.dmnd`。当前 Worker
  不直接读取表内 `file_path`；API 表记录与 Worker 名称映射需由部署保持一致。
  错误 JSON 或非字符串路径会使启动失败，不会悄悄取消白名单。
- API 侧 `blast_databases` 表需先有与键同名的行（`GET /api/v1/blast/databases`
  列表来自该表，`assembly_id` 关联 `assemblies`）。`db_type` 必须是 `prot`。
  默认库可用 `SOYMUTDB_BLAST_DEFAULT_DB` 指定。

### 1.2 新组装接入流程（checklist）

1. 将**蛋白** fasta 放到 worker 宿主机的固定目录（如 `/data/genomes/`）。
2. 建索引：

   ```bash
   cd /data/genomes/wm82.a2.v1
   diamond makedb -p 4 --in wm82.a2.v1.fasta \
     --db wm82.a2.v1.dmnd -v
   ```

   `-p` 是建索引并行度。核酸序列不适用：DIAMOND `blastp` 不翻译核酸库。
3. 确认 `wm82.a2.v1.dmnd` 存在、非空、可读，worker 用户对目录有 `r-x`。
4. 在 API 的 `blast_databases` 表插入一行（`db_type` 固定 `prot`）：

   ```sql
   INSERT INTO blast_databases (name, db_type, assembly_id, file_path, is_active)
   VALUES ('wm82.a2.v1', 'prot', <assembly_id>, '/data/genomes/wm82.a2.v1/wm82.a2.v1', true);
   ```

5. 在 worker 环境变量中加入 `SOYMUTDB_BLAST_DATABASE_PATHS` 对应条目，
   重启 worker。
6. 验证：`GET /api/v1/blast/databases` 出现新库；提交一个 `blastp` job 命中
   该库（`database_id` 或 `database` 名称）。

### 1.3 DIAMOND 二进制

Docker worker 的 apt 工具链包含 `diamond-aligner`；Conda worker 环境包含
`diamond`。部署后仍需在实际运行环境核对二进制版本和执行权限：

```bash
diamond version
command -v diamond
# apt 默认 /usr/bin/diamond；Conda 使用对应环境 PATH。
# 仅当需要覆盖 PATH 检测时设置：
export SOYMUTDB_DIAMOND_BIN=/usr/bin/diamond
```

DIAMOND 缺失、不可执行或指向目录时，任务以清晰错误失败，**不会**换用任何
其他引擎。相关环境变量：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SOYMUTDB_DIAMOND_BIN` | `diamond`（PATH） | DIAMOND 可执行文件路径 |
| `SOYMUTDB_BLAST_MAX_THREADS` | `4` | 部署级线程数上限 |

复现用户参数：

```bash
diamond makedb -p 4 --in TAraport11_pep_20220914-longest.fa \
  --db TAraport11_pep_20220914-longest.dmnd
diamond blastp --query G126-cat-merge-utr_prot_logst.fa \
  --db TAraport11_pep_20220914-longest.dmnd \
  --out G126--blast-tair11.txt -e 1e-10 --outfmt 6 \
  --max-target-seqs 1 --quiet --id 30 --threads 4 --bin 1
```

`--max-target-seqs 1` 只控制报告目标数，不证明唯一正交基因。

映射可指向共享索引基名（旁边保留 `.dmnd`），也可显式指向 `.dmnd`。带点的
版本名可通过 API 的 `database_id` 使用；直接 `database` 别名仍按其既有
字母/数字/下划线/短横线约束，不把表中名称与 API 别名混为一谈。

legacy S3 使用 `blast-dbs/<name>.dmnd`（或 `blast-dbs/<name>/<name>.dmnd`）。
下载按名称与所选目录过滤，写临时文件后逐文件原子替换；这不是多文件数据库
升级的事务协议。已有非空但损坏的索引仍由 DIAMOND 加载报错，应由运维重建并
保留原版，而非把格式存在性检查当作内容校验。

Worker 对 DIAMOND 显式请求 12 个标准 tabular 列（`--outfmt 6` 加列名），
扩展名 `.txt`。`quiet` 为无值布尔开关；Worker 内部 `id` 为 0–100 的输出
身份比例阈值，不改变 API 客户端 `percent_identity` 的语义。

资源预算沿用 4 GiB 默认虚拟内存上限，线程数由任务预算统一持有：参数字典
只能调低线程数，且受 `SOYMUTDB_BLAST_MAX_THREADS` 限制。DIAMOND 2.1.14 的
命中缓冲按 bin 预留约 1 GiB，默认临时存储初始化在小样本实测失败；Worker
固定 `--bin 1`。缩小 block-size 并未解决该初始化问题；单 bin 也不保证任意
大库都能适配该预算。实际数据库需单独验证吞吐、峰值 RSS 与敏感性，不宣称
固定倍数提速。

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
