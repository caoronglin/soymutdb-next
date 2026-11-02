# 原生 PostgreSQL 迁移与验收

> 2026-10-15：更新后环境、回归计数和剩余部署验收统一见 [全栈收尾验收](fullstack-validation-20261015.md)。早期通过记录保留其原始版本与运行范围；生产数据切换尚未执行。

> 2026-10-17：已完成真实 ClickHouse → PostgreSQL 隔离回填、摘要 receipt、幂等重跑与切换门禁演练；见 [追加验收](native-validation-20261017.md)。生产源与目标仍需明确，未执行生产切换。

## 当前实现

0047 为 PostgreSQL 增加变异事实、私有导入暂存、匿名事件和 Web Vitals 表。
发布与组装均使用真实外键，变异标识使用 NUMERIC(20,0)，保留完整 UInt64。
普通 VCF 导入分批暂存，在同一事务中发布事实并完成 manifest。
已经发布的版本不可通过普通导入修改；不同组装的数据不相互替换。

API 变异查询、统计、群体遗传查询、健康检查及匿名分析已经使用 PostgreSQL。
Worker 变异导入、统计、公开导出使用 PostgreSQL。公开导出排除未公开突变体，
输出 public_id，不输出内部名称。导出采用数据库游标，避免整份结果驻留内存。

每小时执行 native_retention.cleanup：事件保留两个日历年，Vitals 保留 90 天。
已发布 manifest 的暂存行可以删除；未完成或失败任务的暂存不会被该任务删除。
每批 2000 行，每次每类最多 10 批，使用 SKIP LOCKED；每批独立提交。
这不是表分区方案，生产规模的查询耗时与维护成本仍需实测。

## 历史数据迁移工具

使用 Worker 环境执行 `python -m soymutdb_worker.native_backfill`。
连接信息必须显式提供，工具不采用开发默认值：

- BACKFILL_POSTGRES_URL：同步 SQLAlchemy PostgreSQL DSN。
- BACKFILL_CLICKHOUSE_URL / DATABASE / USER / PASSWORD：历史源的完整 HTTP 地址、库名与
  凭据，缺任意一项即报错，不提供开发默认值。
- BACKFILL_CLICKHOUSE_TIMEOUT：可选，请求超时秒数。

历史源按 HTTP 接口只读访问，实现只使用标准库，不安装 ClickHouse 驱动；
`apps/worker/pyproject.toml` 里的 `clickhouse-connect` 只存在于可选 extra
`legacy-clickhouse`，并限定在 `python_version < '3.15'`。
地址必须使用 HTTPS（验证系统信任链），或明确的 `http://127.0.0.1` / `http://[::1]`
本地历史源。不会跟随重定向或使用环境代理；凭据仅通过请求头发送。
请求超时必须为有限正数，逐行读取设有 1 MiB 上限。
Python 3.15 下的 HTTP 传输、类型与配置测试为 59 passed；生产级历史源全量传输仍未执行（2026-10-17 已在隔离真实源完成 5 行演练，见 [追加验收](native-validation-20261017.md)）。

默认只读预演：

```sh
python -m soymutdb_worker.native_backfill \
  --release-id 42 --source-version release-version \
  --assembly-map '{"v4":4,"v5":5}'
```

组装映射必须匹配数据库中该组装的 name 或 version；禁止将不同标签映射到
同一组装。版本字符串必须匹配指定 PostgreSQL release，不能猜测或派生身份。

在运维人员停止全部旧端写入后，加 `--apply --source-frozen` 执行迁移。
工具以只读 HTTP 流逐批读取历史源，完整字段摘要包含 release_id 与 assembly_id。
PostgreSQL 中已有行不会覆盖；目标摘要、行数和第二次源摘要必须一致才提交。
冲突、重复标识、缺失映射、源端变化或校验失败会回滚该版本的全部新写入。
校验凭据写入 PostgreSQL `native_variant_backfills`，与事实同一事务提交。
同一版本已有凭据不能被不同摘要覆盖；原始版本、组装映射、行数和摘要保留。
应保存每个版本输出的 JSON 摘要，并在切换前验证所有已发布版本。
这里允许迁移已经发布的历史版本，是一次性运维迁移能力，不是应用写入接口。

## 尚未完成的部署边界

默认生产、开发、预览配置不再启动 ClickHouse，也不再让 API/Worker 依赖它。
历史源端和旧 schema migrator 移至 `docker-compose.legacy-clickhouse.yml`，
必须显式加载该文件并选择 `legacy-migration` profile；已有 Docker 卷不会被配置修改删除。
升级先运行 PostgreSQL migration，再执行 `app.scripts.verify_native_cutover`，
已知含变异的公开版本必须有一致的原生计数及回填凭据或原生 published import。
校验失败时不会启动新应用。该门禁不能发现旧元数据把变异数量错误记为零的历史版本，
所以仍必须先完成完整源端清单和逐版本回填核验。

默认运行时依赖的应用镜像族是五个：`api`、`worker`、`migrate`、`mcp`、`jbrowse`。
`migrate-clickhouse` 是历史遗留镜像，只在显式加载历史 overlay 时才需要，
`upgrade.sh` 已不再引用它。

生产源数据转移与生产镜像切换尚未实际执行。2026-10-17 已在隔离真实 ClickHouse 源上完成 5 行 `--apply --source-frozen` 回填演练与切换门禁校验，但那是演练数据，不等同生产全量回填（[追加验收](native-validation-20261017.md)）。
迁移工具已通过真实 PostgreSQL 的预演、幂等重试、源端变化及冲突回滚测试；
尚未对真实历史 ClickHouse 全量数据执行。不能据此宣称生产替代已完成。
`clickhouse-connect` 已从默认依赖降为 `apps/worker/pyproject.toml` 的可选 extra
`legacy-clickhouse`；剩余工作包括整理历史交付镜像，
以及实际生产回填和镜像验收。

备份与恢复已按原生架构改造：`backup.sh` 默认只备份 PostgreSQL 与 S3 对象
（备份格式 v3），不再包含 ClickHouse 组件；历史 v2 包只有在显式
`--allow-legacy-v2` 且目标 compose 显式提供 ClickHouse 服务时才能恢复或校验，
缺失组件不会被报告为已校验。

Python 3.15 迁移已完成本机验收（[全栈收尾验收 2026-10-15](fullstack-validation-20261015.md)）：
API 2326 passed / 3 历史驱动专用 skipped、Worker 657 passed / 0 skipped、MCP 66 passed / 0 skipped，
均为 Python 3.15 解释器与真实 PostgreSQL 下的原生进程结果。尚未验证的是 Docker 镜像内的
同一套依赖与服务（本机无 Docker daemon），因此不把镜像层记为已完成。

## 2026-10-14 验收记录

本节只记录在本机环境跑出的结果，不代表生产验收：

- API 全套：2332 passed。运行环境是 Python 3.15 与本机 PostgreSQL 16，
  不是生产镜像，也不是生产数据库。
- Worker 全套：623 passed / 7 skipped，仍在 Python 3.14 上运行。
  跳过项是本机缺少 DIAMOND 可执行程序的外部程序测试，不能当作通过。
- Admin 官方 CLI 扫描：命令面板残留 37 → 0，Web 侧 19 → 0。
  这只是对源码的静态扫描结果，不等于视觉验收，也不等于完整的浏览器回归。

此前在本文档登记、本次没有重新复跑的结果（保留供对照，不代表当前状态）：

- 版本状态约束补充回归 17 passed；Worker 原生仓储、保留期与历史回填子集 9 passed。
- API 客户端 172 passed，含主动取消、超时、重试与清理边界。
- Admin 图表完整依赖闭包 331135 gzip 字节，小于 370 KiB。

未完成且不得据此宣称完成的事项：Docker 镜像验收、真实历史 ClickHouse 全量回填、生产镜像切换。
（Python 3.15 原生进程验收已完成，见上方说明与 [全栈收尾验收](fullstack-validation-20261015.md)。）

## 分页索引实测

原有 region 索引在不限定染色体时不能直接提供 `(position, variant_id)` 顺序。
新增 `(release_id, position, variant_id)` 与
`(release_id, assembly_key, position, variant_id)` 两个索引覆盖普通与组装范围分页。

可复现脚本：`scripts/benchmark_native_variant_pagination.py`，使用 API Python 环境，
显式设置 `SOYMUTDB_BENCHMARK_DATABASE_URL` 指向一次性 PostgreSQL 数据库。
脚本只创建、填充和删除自己随机命名的 schema，不操作已有业务表。
完整查询计划和耗时见 `native-variant-pagination-benchmark.json`。

首次本机 PostgreSQL 16.15 / 20 万条合成记录 / 每个场景 25 次暖查询的实测值，
直接取自 `native-variant-pagination-benchmark.json`：

| 场景 | 索引前 P95 | 索引后 P95 |
| --- | --- | --- |
| `assembly_first` | 29.90 ms | 0.24 ms |
| `assembly_deep` | 29.57 ms | 0.23 ms |
| `release_first` | 26.16 ms | 0.22 ms |
| `region` | 0.40 ms | 0.23 ms |

前三项是缺少 `(release_id, position, variant_id)` 顺序索引的分页形态；
区域查询原本已有索引，改善很小。
这些数字来自脚本自述的合成 200000 行 / 本地暖查询范围，不含 HTTP、真实生产数据、
冷缓存与并发负载，不能替代生产性能验收。
