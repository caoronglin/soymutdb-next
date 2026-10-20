# 全栈收尾验收（2026-10-15，10-16 更新）

> 2026-10-17 追加：手写客户端路由欠账已清零；真实 API → outbox → Redis/Celery → S3 导出链与隐私负例通过。详见 [非 Docker 追加验收](native-validation-20261017.md)。下文较早计数和待办保留原始时间范围。

## 已完成的新一轮验证

- API：Python 3.15.0，FastAPI 0.143.1，Uvicorn 0.54.0；原生环境不安装 clickhouse-connect。
- API 全套：2326 passed、3 skipped（历史 ClickHouse 驱动专用用例），60.81 秒。命令见下。
- 真实 PostgreSQL 原生迁移、公开权限、搜索索引与切换门禁独立验证：21 passed，零跳过（PG16.15）。
- 新增隔离 PostgreSQL 18.6 实例，API 全套同样 2326 passed、3 历史驱动专用 skipped，66.69 秒；目标数据库版本已有本机运行证据。此为原生进程验收，不等价于 Docker 镜像验收。
- 根工作区 `pnpm exec turbo run lint typecheck --concurrency=1`：25/25 任务通过；修复 ui-react 缺失的 Vitest 开发依赖及图表测试类型错误。
- 备份恢复：45 passed，32.27 秒；覆盖 v3 默认与显式 v2 历史恢复。此为脚本测试，不代表生产灾备演练。
- 修复迁移测试隔离：降级后的表不存在断言限定到独立 schema，避免 search_path 回落至 public 同名表。

## 其他已通过验证

- MCP：Python 3.15.0 更新后的全部工具与认证测试 66 passed、零跳过，6.02 秒；Uvicorn 0.54.0，测试依赖已显式声明。
- API OpenAPI/客户端：更新依赖后重新导出并生成临时类型，check-contract 通过，生成类型无差异；手写路由可见性检查保留 7 项已有白名单债务，无新增债务。生成与核验脚本支持 `SOYMUTDB_API_PYTHON` 指定候选解释器。
- 部署/CI 窄契约：99 passed、5 subtests passed，4.85 秒。
- 统一 `bash scripts/smoke.sh --profile contracts` 最终重跑：SMOKE PASS，主套件 **297 passed + 5 subtests**，环境报告套件 **10 passed**，无跳过层，42.59 秒。
- Python 3.15 共享 jobs/import-protocol：110 passed；合并执行使用 `--import-mode=importlib`，避免两个目录中的同名 test_contract 模块相撞。
- 门户：371 项单元测试；图表：84 项；内外站产物与隔离门禁通过；完整图表依赖 331144 B，小于 370 KiB。图表测试类型错误已修正，根工作区类型检查通过。
- 无旧驱动的 Python 3.15 HTTP 历史数据源测试：59 passed，0.24 秒；使用 API 候选解释器和 Worker 源码路径执行，不等价于 Worker 完整环境验收。

## 10-16 新增完成的验收

- API 全量更新兼容依赖后再次验证：**2326 passed、3 历史驱动专用 skipped，61.64 秒**；Pydantic 2.14.1、SQLAlchemy 2.1.4、asyncpg 0.32.0、Alembic 1.20.0，FastAPI 0.143.1、Uvicorn 0.54.0。更新后 OpenAPI 重新生成核对通过，路由可见性 PASS，保留 7 项既有白名单债务。
- MCP 全量更新兼容依赖后再次验证：**66 passed、零跳过，5.78 秒**。仅第三方 beartype 的未来 Python 3.20 Protocol 弃用提示。
- 最新根 `lint typecheck`：**25/25 任务通过**（53.132 秒）；随后冻结锁文件安装成功，73 包复用、0 下载。安装后再跑 `turbo run lint typecheck test --concurrency=1`：**36/36 任务通过，1071 项单元测试通过**，41.574 秒。默认 test 不输出 coverage，Turbo 给出缺失 coverage 输出提示，不构成失败。

- Worker：Python 3.15.0 最新锁文件完整安装；NumPy 2.5.4、PyArrow 26.0.0、Matplotlib 3.11.2、Scanpy 1.12.4、Numba 0.68.0、llvmlite 0.50.0、SciPy 1.18.1、Polars 2.0.0、scikit-learn 1.9.1、SQLAlchemy 2.1.4。
- 原生 Worker 默认全套：**657 passed、零跳过，31.28 秒**。独立 PostgreSQL 18.6 数据库，启用 PostgreSQL 集成、真实 DIAMOND 2.2.8 和两百万行导入层。输出 `/tmp/worker315-native-final-20261016-r2.log`。
- 科学计算能力检查：Parquet 五种压缩编码读写、CSV/dataset/compute、pandas Parquet、HDF5、Matplotlib PNG、SciPy sparse、Polars、Scanpy normalize、Leiden、Numba JIT 全部通过。CRC32C 使用 C 实现。此为本机 Python 环境运行证据，Docker 镜像尚未实测。
- 严格惰性加载回归：任务注册不导入科学依赖；监控/惰性加载窄测 6 passed。监控测试显式绑定动态端口，修复导入顺序导致占用默认端口的问题。
- 历史引擎：chdb 的 abi3 包缺少 Python 3.15 专用非限定 API 动态库，故从原生 dev 依赖移除，五个历史模块转入既有 Python 3.14 `clickhouse-migration` 强制通道；本机按新依赖清单安装后再次验收 **33 passed，6.05 秒**。新增路由合同防止漏跑，新通道用 `scripts/legacy-worker-test-requirements.txt` 明确依赖。
- Redis 8.10.1 / Celery：独立 loopback Redis，无持久化；Python 3.15 Worker 完成定向 ping、真实任务投递和结果回传（SUCCESS）。测试任务无业务写入；这不代表 API outbox 到 S3 的完整业务链验收。
- Admin：19 文件、146 tests 全通过；最终构建成功；375/768/1024/1440 实际浏览器布局、抽屉导航、会话恢复及版本管理检查已通过（API mock，权限边界另由真实 PG API 测试覆盖）。见 [Admin 验收](admin-final-validation-20261016.md)。
- 最新官方 Ant CLI 6.6.6 扫描：Admin 161 文件、73 facade imports；门户 205 文件、66 imports；均零 lint 问题、零配置失败。报告见 `ant-design-scan-20261015/summary.json`。
- ECharts/zrender 已从所有生产清单、catalog 和 pnpm lock 中移除；仅保留 AntV。正常 pnpm 更新锁文件通过。图表重跑 84 passed。
- 安全头最终检查：`python3 scripts/check_artifact_headers.py --require-dual`，4 文件通过；Admin CSP 使用本次显式预览 API origin，不再含 localhost 占位。
- 工具链：Node 26.10.0、pnpm 12.11.2、Python 3.15、uv 0.13.1，pins guard 通过。Docker 取消已过时的 Arrow 25 C++ 编译阶段，使用锁定 cp315 PyArrow wheel；Numcodecs 编译显式采用同版 NumPy 头文件。

## 尚无运行证据的部署事项

- 本机无 Docker daemon，镜像构建、镜像内健康检查与完整 Compose/E2E 未实际执行；配置/静态合同不能替代镜像验收。
- 生产历史数据回填、生产切换未执行。2026-10-17 已完成隔离真实 PostgreSQL / 六 S3 桶恢复及 115 项独立核验，不能据本机隔离记录宣称生产已上线或已完成异地容灾。
- 2026-10-17 已解决原 7 项手写路由债务，并清空陈旧白名单；重新导出 OpenAPI 检查 PASS，drift / baseline_debt / new_drift 均为 0。

## API 全套命令

```sh
cd apps/api
PYTHONPATH=../..:$PWD OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_c2 \
SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_c2 \
../../.mamba-root/envs/py315/venvs/api/bin/python -m pytest tests -q
```

## 备份恢复命令

```sh
PYTHONPATH=scripts python3 -m pytest scripts/test_backup_restore_contracts.py -q
```

完整输出暂存 `/tmp/api315-full-updated-final.log`、`/tmp/native-backup-final-20261015.log`。本记录随本次剩余验证更新。

## 最终日志索引（临时本机证据）

- API：`/tmp/api315-latest-full-20261016.log` / `api315-latest-contract-20261016.log`。
- Worker：`/tmp/worker315-native-final-20261016-r2.log` / `worker315-capability-final-20261016.log`。
- 历史引擎：`/tmp/worker314-legacy-final-20261016.log`。
- MCP：`/tmp/mcp315-latest-tests-20261016.log`。
- 队列：`/tmp/celery315-roundtrip-20261016.log`；只验证隔离 Redis/Celery，不验证 API outbox/S3 业务链。
- 前端/合同：`/tmp/turbo-final-20261016.log` / `full-contracts-final-20261016.log` / `pnpm-final-install-20261016.log` / `workspace-final-20261016.log`。

原生 Worker 复现需设置三个 PostgreSQL URL（`SOYMUTDB_TEST_DATABASE_URL` 用 asyncpg，
`SOYMUTDB_NATIVE_TEST_DATABASE_URL` / `SOYMUTDB_STATIC_TEST_DATABASE_URL` 用 psycopg2），
指向新的隔离测试库；开启 `SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`、
`SOYMUTDB_RUN_2M_IMPORT_PERF=1`，设置真实 `SOYMUTDB_TEST_DIAMOND_BIN`，
再用 Worker 3.15 venv 执行 `python -m pytest tests -q`。
历史测试用 `SOYMUTDB_LEGACY_TEST_PYTHON=<3.14 interpreter>` 与隔离 PG URL，
运行 `bash scripts/verify-legacy-worker-tests.sh`，已有依赖环境可设置
`SOYMUTDB_LEGACY_TEST_INSTALL=0` 避免重复安装。
