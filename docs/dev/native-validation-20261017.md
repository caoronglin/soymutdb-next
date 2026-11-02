# 非 Docker 追加验收（2026-10-17）

## 客户端与前端

删除没有调用方且后端未实现的轨道写接口和独立 release provenance 调用；保留已有轨道读取和 Admin 版本管理。修正轨道列表为真实的数组响应，过滤参数使用 `assembly_id` / `category_id`。清空旧路由白名单，防止回归被历史例外放行。

- API client：184 tests，新增 12 项；fresh OpenAPI 类型与手写路由核验通过，三类 drift 均为 0。
- 工作区 `lint typecheck test --concurrency=1`：36/36 任务，1083 tests，46.233 秒（1043 Vitest + 40 JBrowse Node tests）。
- Celery 信号修复：成功/失败信号接收的是 Task 对象，先提取名称再做队列匹配；覆盖对象、字符串、未知和空 sender。指标、配置、延迟导入及发布传输回归 44 passed。
- 静态发布任务说明已与实际 `build_artifact_url` 传输实现一致。

## 真实导出业务链

隔离 PostgreSQL 18.6 + Redis 8.10.1 + Python 3.15 Worker + 原生 MinIO。FastAPI 使用进程内 ASGI HTTP transport；没有依赖替换，数据库、broker、独立 Worker 和 S3 均为真实服务。此项不包含反向代理或浏览器网络验收。

`POST /variants/export`：匿名 401；researcher 202；outbox 持久化 pending；真实 dispatcher 发送后为 sent；Worker SUCCESS；S3 回读 2 行 / 429 B。公开文件排除了私有突变体、其他 assembly 和草稿 release，未出现内部名称/关联键。第二次轮询处理 0 个事件，文件 ETag 不变。这证明正常轮询不重复分发，不等价于所有崩溃窗口的 exactly-once 保证。

- [脱敏业务链证据](native-validation-20261017/export-chain.json)
- [真实指标证据](native-validation-20261017/worker-metrics.json)：export 成功计数为 2。
- 可复现入口：`scripts/dev/verify-native-export-chain.py --evidence-out <path>`。脚本要求 dev、本机服务和专用 `soymutdb_chain_*` 数据库。

## S3 服务来源

官方社区二进制下载端点返回 410；使用校验过的官方 Go 1.27.2 工具链从固定源码编译到 `/tmp/soymutdb-native-bin`，只用于本次隔离验收：

- MinIO：`github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z`，提交 `9e49d5e7a648`。
- mc：实际解析版本 `v0.0.0-20251106162529-77f82e18b540`。
- 源 S3 端口 59000，恢复目标端口 59010；各有独立 `/tmp` 数据目录。未修改生产对象存储配置。

## 真实 PostgreSQL / S3 灾备

为现有三个运维脚本新增显式 `--runtime native` 和 `--no-repo-env`；共享路由集中在 `deploy/scripts/backup-runtime.sh`。原生模式要求主机 PG 工具与 mc，缺失直接失败。备份与恢复分别要求写入已停止确认，并检查活跃数据库会话；恢复仍需隔离目标声明与交互确认，生产恢复保留输入 `restore` 的门禁。

真实演练备份了 77 张表、六个必需桶的 9 个对象，再恢复到独立空库和第二个 MinIO 实例。恢复后独立校验 **115 PASS / 0 FAIL / 0 SKIP**，对象逐字节与源比较一致。临时篡改目标桶策略后校验确实失败；撤销篡改后重新全部通过。

实测修复：无公开策略的 MinIO 桶导出 `{}`，不能用 `set-json` 恢复；现在使用 `anonymous set none`。校验进一步读取目标的真实策略与归档比较，任何读取失败、JSON 无效或策略不匹配均失败。仅规范化两种空策略形式，其他字段完整保留。

- [脱敏备份恢复证据](native-validation-20261017/backup-restore.json)
- 备份恢复合同与原生运行回归：**82 passed，77.73 秒**（原 45 + 原生 28 + 策略 9）。ShellCheck 通过。
- 当前证明隔离本机恢复，未配置 offsite 上传，不代表跨机容灾或生产恢复演练。v3 只覆盖对象当前版本，不宣称覆盖历史版本或删除标记。
- 统一 `bash scripts/smoke.sh --profile contracts`：334 passed + 5 subtests；环境套件 10 passed，SMOKE PASS，无跳过层（87.69 秒）。
- 完整使用方式：[灾备运维指南](../ops/disaster-recovery.md)。

## 历史回填与切换门禁演练

使用本机 ClickHouse 26.9.1.147（仅作为历史迁移源）及新建 PostgreSQL 18.6 专用库，Worker/API 均为 Python 3.15.0。历史表 DDL 取自 `infra/clickhouse/init.sql` 的 26 列定义；演练数据含目标 release 的 v4/v5 共 5 行和另一 release 的 1 行。

- dry-run：源读取成功，PG 事实与 receipt 均保持 0。
- `--apply --source-frozen`：只传输目标 release 的 5 行，v4/v5 保持各自 assembly identity；生成 1 条摘要 receipt。
- `verify_native_cutover`：`native_cutover_ready=true`，faults 为空。
- 再次 apply：行数、摘要、receipt 均不变。
- 缺少冻结确认、合并 assembly namespace、错误 release version 均被拒绝，PG 快照不变。

[脱敏演练证据](native-validation-20261017/backfill-rehearsal.json)。复现脚本为 `scripts/dev/verify-native-backfill.py`，仅允许 dev、本机服务和 `soymutdb_backfill_*` 数据库。新脚本使用真实迁移 schema，未为 fixture 修改业务表约束。

此为迁移程序与门禁的真实服务演练，**没有操作生产历史记录或生产活动 release 指针**。

## 验收范围

已完成上述本机隔离演练。生产历史数据回填与切换需要明确的数据源、目标、release 和 assembly 映射；本机隔离证据不能替代生产验收。Docker 镜像与 Compose 运行验收按用户要求排除。

## 收尾

本轮启动的 Worker、Redis、两个 MinIO、历史 ClickHouse 和 PostgreSQL 集群均已干净停止。验收数据、备份和脱敏 JSON 保留，未提交、推送或部署。

## 复现命令与证据保存

以下命令从仓库根目录执行，使用 `.ai-memory/LOCAL-RUN-ENV.md` 中的本机环境。命令记录对应上述实跑结果，本次文档整理未重新启动服务或重跑应用测试。`API_PYTHON` 和 `WORKER_PYTHON` 应分别指向已安装锁定依赖的 Python 3.15 环境。

```bash
export API_PYTHON="$PWD/.mamba-root/envs/py315/venvs/api/bin/python"
export WORKER_PYTHON="$PWD/.mamba-root/envs/py315/venvs/worker/bin/python"

# 使用仓库固定的 Node / pnpm 环境
GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 \
  node node_modules/turbo/bin/turbo run lint typecheck test --concurrency=1
SOYMUTDB_API_PYTHON="$API_PYTHON" bash packages/api-client/scripts/check-contract.sh

PYTHONPATH=apps/worker/src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 "$WORKER_PYTHON" -m pytest \
  apps/worker/tests/test_task_signal_metrics.py \
  apps/worker/tests/test_celery_config.py apps/worker/tests/test_metrics.py \
  apps/worker/tests/test_lazy_task_registration.py \
  apps/worker/tests/test_static_publish.py \
  apps/worker/tests/test_ablation_publication_artifact_transport.py -q

PYTHONPATH=scripts "$API_PYTHON" -m pytest \
  scripts/test_backup_restore_contracts.py scripts/test_native_backup_runtime.py -q
bash scripts/smoke.sh --profile contracts
```

完整合同门禁完成后，恢复脚本的完成提示补齐了 runtime 与环境选项；该最后调整另有 **2 passed / 4.87 秒**窄回归，未据此宣称完整门禁在最后调整后再次运行。

真实服务演练入口为 [`verify-native-export-chain.py`](../../scripts/dev/verify-native-export-chain.py) 和 [`verify-native-backfill.py`](../../scripts/dev/verify-native-backfill.py)。应先阅读脚本参数与 dev/回环地址/专用数据库守卫，配置独立服务和环境变量，再执行；脚本会写入演练数据，不可直接指向生产。备份、恢复和独立验证的完整参数与确认流程以 [灾备指南](../ops/disaster-recovery.md) 为准。凭据仅通过环境或受限文件传入，不记录在本文。

| 实跑记录 | 本机临时日志 |
| --- | --- |
| 前端 36 任务 / 1083 tests | `/tmp/workspace-final-20261017.log` |
| Worker 44 项切片 | `/tmp/worker-signals-publication-20261016.log`（文件名沿用启动日期，验收归入本轮） |
| 灾备合同 82 项 | `/tmp/native-backup-contracts-20261017.log` |
| 统一合同与环境门禁 | `/tmp/contracts-final-20261017.log` |
| 真实备份 / 恢复 / 独立校验 | `/tmp/soymutdb-native-dr-{backup,restore,verify}-20261017.log` |
| 桶策略篡改拒绝 | `/tmp/soymutdb-native-dr-policy-negative-20261017.log` |
| 历史回填演练 | `/tmp/soymutdb-native-backfill-20261017.log` |

上述 `/tmp` 日志与备份是本机临时现场，不保证跨机器或清理后仍存在。长期记录使用本文链接的四份脱敏 JSON；原始 Worker 日志可能含临时预签名 URL，不纳入仓库证据。归档摘要及恢复对象统计见 `backup-restore.json`，生产执行前仍须重新核验实际归档及目标。
