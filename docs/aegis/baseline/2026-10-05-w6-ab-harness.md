# W6 — 性能 A/B 实测：驱动补齐与判据缺陷

日期：2026-10-05
范围：`scripts/run_db_ab_experiment.py`（新增）+ `scripts/db_ab_experiment.py`（未改，见「判据缺陷」）

## 起因

W6 的方法论框架 `scripts/db_ab_experiment.py`（385 行，37 个单测）早已入库，但**没有任何调用方**。
文件头明确写着它刻意不 import 数据库驱动，`execute` 由调用方注入：

> the caller supplies a ``execute`` callable. That keeps it importable (and testable)

结果是：实验可以被规划、可以被审，却**无法被运行**。这不是「没跑」，是「跑不了」。

另一处佐证：`db_ab_experiment.py:103` 的报错文案让读者去看 `scripts/db_experiment.py --init`，
而该文件**不存在**——一个死引用。说明「造数据 + 执行」的另一半从未落地。

## 交付

新增 `scripts/run_db_ab_experiment.py`。它只做一件事：把既有 harness 接到真实连接上。
不重新实现任何测量、统计或拒绝逻辑。

驱动必须解决的一个实质问题：

**两臂共享同一个库，所以 treatment 建出的索引对 control 可见。**
若不处理，第二轮 control 就会去测它本应被对比的索引，两臂会因为错误的理由而一致。
解法是 control 臂的 `analyse` 里带 `DROP INDEX IF EXISTS`，由 harness 在该臂每次测量前执行。
两臂的 `ANALYZE` 仍然完全对称——这是审计要求的那个不变量。

隔离面（H-09）：

- 目标库必须匹配 `^soymutdb_abtest_[a-z0-9_]+$`，复用 harness 自己的 `assert_isolated_target`
- 驱动只发 `CREATE DATABASE` / `CREATE TABLE` / `CREATE INDEX IF NOT EXISTS` /
  `DROP INDEX IF EXISTS` / `ANALYZE` / `INSERT` / `SELECT`
- 从 `SOYMUTDB_TEST_DATABASE_URL` 继承连接参数，但**替换库名**
- 实测拒绝 `soymutdb`、`postgres`、`soymutdb_abtest2`（缺下划线），放行 `soymutdb_abtest_w6`

数据由 `generate_series` 生成，两臂行级完全一致，因此 `Comparison.same_rows` 是实测出来的，
不是假设出来的。

## 判据缺陷（已修复）：`same_plan` 让索引实验永远无法 decisive

`Comparison.is_decisive` 原先要求 `same_plan`，即两臂计划形状**集合相等**。
但索引实验的定义就是形状改变。实测：

| 臂 | 轮内形状种类 | 形状 | 返回行数 |
| --- | --- | --- | --- |
| control | 1（稳定） | `Seq Scan:gene_fact_probe` | 1 |
| treatment | 1（稳定） | `Bitmap Heap Scan \| Bitmap Index Scan` | 1 |

两臂**各自轮内完全稳定**，基数也相同——这才是可比性的真正判据。
但因为跨臂形状不等，旧判据下 `is_decisive=False`，Speedup 行只能标 n/a。

这与审计 D-08 的初衷并不冲突：D-08 拒绝的是「拿 Seq Scan 的子节点时间去比
Nested Loop 的总时间」这种**层级错配**，由 `extract_run` 只取根层数字来防。
它从未要求「索引实验的两臂必须长得一样」。

**已实施**（2026-10-05，经确认）：`is_decisive` 改用新增的 `stable_shape`——
每臂必须在自己所有轮次内保持**唯一**形状。`same_plan` 降级为报告中的信息项。
真正的故障（某臂中途换形状）与预期结果（两臂本就不同）从此可区分。

消融验证：把 `is_decisive` 的 `stable_shape` 改回 `same_plan`，
`test_an_index_experiment_is_decisive_although_its_arms_differ` 转红（exit 1），
恢复后 md5 校验通过、40 passed。覆盖用例由 37 增至 40。

改判据后重跑，实验 `is_decisive=True`、脚本 exit 0。

## 实测（本机 PostgreSQL 16.15 @ 127.0.0.1:55432，200000 行，5 轮交替 + 1 轮预热）

| 轮次 | control 中位数 | treatment 中位数 | 比值 |
| --- | --- | --- | --- |
| 1 | 11.176 ms | 0.051 ms | 219.1x |
| 2 | 11.230 ms | 0.038 ms | 295.5x |
| 3 | 10.999 ms | 0.041 ms | 268.3x |
| 4 | 11.027 ms | 0.041 ms | 269.0x |
| 5 | 10.762 ms | 0.033 ms | 326.1x |

**以上数字仍不得引用**，`is_decisive=True` 只解除了一道比较性闸门，不代表数字可信。理由：

1. **比值波动 49%**（219.1 → 326.1），同配置同机器。分母只有 0.033–0.041 ms，
   测量噪声在比值里被放大到几十个百分点。
2. **合成数据**：`generate_series` 造的均匀分布，不是真实变异事实表。
   真实表的基因 id 分布、选择性、聚簇度都不同，Bitmap Index Scan 未必仍被优化器选中。
3. **全内存**：200000 行的表只有几 MB，整表常驻 buffer pool，
   Seq Scan 走的是 `Shared Hit Blocks`。真实表 GB 级时大部分是 `Shared Read`。
4. **端到端无关**：写入、迁移、索引维护成本、存储开销都不在测量范围内。

`render_report` 现在每次都会输出稳定性告诫，因为这不是一次性的教训。
这与审计当初撤回「≈100×」属于同类问题：数字看着醒目，但方法撑不住它。

## 复现

```bash
cd /mnt/data02/T25ronglin/code/web
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
apps/api/.venv/bin/python scripts/run_db_ab_experiment.py \
  --url 'postgresql://soymutdb@127.0.0.1:55432/postgres' \
  --database soymutdb_abtest_w6 --rows 200000 --rounds 5
# exit 1：诊断走 stderr，说明是 same_plan 判据而非测量故障
```

CNB 侧：`.cnb.yml` 已有 `services: - docker`，`scripts/with-postgres-service.sh`
会导出 `SOYMUTDB_TEST_DATABASE_URL`，正是本驱动需要的变量形式。
但**尚未接入 CI job**——在 `same_plan` 判据拍板前接入，只会让流水线稳定红。
本机验证只证明驱动逻辑正确，**性能结论必须以真实数据副本上的运行为准**。

## 同批清理的 Python lint 债

修好 `Makefile` 的路径（`apps/api/src` → `app/`）后暴露 335 个存量问题，本次全部清零：

| 项 | 前 | 后 | 说明 |
| --- | --- | --- | --- |
| `apps/api` | 335 | 0 | 241 个 `--fix` 自动；22 个 UP042 手工；22 个 E501 手工 |
| `apps/worker` | 7 | 0 | 6 个 `--fix`；1 个 `yield for` → `yield from` |

要点：

- **UP042 有行为变更**。`class X(str, enum.Enum)` → `StrEnum` 后，
  `str(ReleaseStatus.DRAFT)` 由 `'ReleaseStatus.DRAFT'` 变为 `'draft'`。
  `.value` 与 `==` 行为不变，OpenAPI 描述与词序列校验通过，但日志/字符串拼接会变。
  ruff 自身把它标为 unsafe fix。
- **兼容层被证伪**。`app/core/compat.py` 的 StrEnum backport 是为 Python < 3.11 存在的，
  而 `requires-python = ">=3.14"`——UP036 报的版本判断是永不执行的死代码。
  已简化为 stdlib re-export，11 个 schema 模块的 import 路径保持不变。
- **E501 全部是括号内换行**，22 处涉及 `Enum(...)` 与 `mapped_column(...)` 调用参数。
  8 个文件用 AST dump md5 前后对比证明**语义完全相同**（指纹逐个一致）。
  `app/main.py:49` 是 OpenAPI 描述里的一行散文，按 markdown 软换行拆分，词序列不变。
- **预存失败（非本轮引入）**：干净 HEAD 上 `test_opt2_release_scope.py` 两例与
  `test_mutants.py` 一例即失败。根因是 `app/api/v1/search.py:50-57` 的 `release_id`
  查询参数从未被使用，实际 scope 由 `Depends(get_release_context)` 决定，
  而该依赖按其 docstring 拒绝未发布 release → 404。
  这与 AGENTS.md 的公开边界（外部不暴露 draft）一致，**很可能是测试过时**，
  但改它属于安全边界决策，未擅动。

## 消融矩阵的硬前置（本机实测踩到）

消融测试在**未设** `SOYMUTDB_TEST_DATABASE_URL` 时走 Testcontainers 起容器。
本机没有 docker，于是 20 个需要库的用例在 fixture 阶段报
`docker.errors.DockerException … FileNotFoundError: [Errno 2]`，结果是
`129 passed / 20 errors`——**不是代码缺陷，也不是并发干扰**。

```bash
export SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb'
apps/api/.venv/bin/python -m pytest apps/api/tests/test_ablation_*.py -q   # 149 passed
```

按 AGENTS.md「Skipped or xfailed privacy, identity, or assembly-isolation
scenarios do not satisfy the merge gate」，此处 **error 而非 skip 是正确
行为**：门禁必须红。改成 skip 才是缺陷。

曾把这次 `20 errors` 误判为「子代理并发改文件」并据此排查两轮；真实触发
条件就是少了这个环境变量。

## 遗留

- 库 `soymutdb_abtest_w6` 仍在本机 55432 上。按 H-09 驱动不发 `DROP DATABASE`，
  清理需人工执行，或随容器销毁（CNB 侧天然一次性）。
- `db_ab_experiment.py:103` 指向 `scripts/db_experiment.py` 的死引用仍在，未改。
