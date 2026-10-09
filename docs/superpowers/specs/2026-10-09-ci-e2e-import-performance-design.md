# CI/E2E 与 ClickHouse 导入性能：定向修复设计

- 日期：2026-10-09
- 基线：`main@2c5f0f15e4e344e33f9d616d4226610aa43f6ff9`
- 状态：**代码部分实施，集成/部署验收待 GitHub CI 证明；不是生产发布许可**
- 执行 owner：[本次执行合同](../../aegis/plans/2026-10-09-ci-e2e-import-performance-execution.md)
- 总状态 owner：仓库根 `plan.md`；不建立第二份全局计划

## 1. 问题与决策

| 诊断 | 本次实施 | 不在本次范围 |
| --- | --- | --- |
| `e2e-smoke.yml` 在 Actions 没有启动本地服务，但原 `online-smoke.spec.ts` 打开 `127.0.0.1:5173`，运行 #37880204038 连接被拒 | 线上 Smoke 改测部署站点 10 条路由；原本地测试保存为显式运行的 `local-preview.spec.ts` | 不用公网 Demo 验证 API 真正写入或科研结论 |
| `baseline-validation.yml` 直接 grep 全部 JS/CSS 文本的 `VITE_API_BASE_URL`，构建中出现变量名字就失败，运行 #37773096209 | 改用已有 `scripts/check-production-artifact.sh` 对三套构建目录按 Demo 模式扫描 | 不取消生产严格扫描，不把 Demo 等同 Prod |
| `_carry_untouched_partitions` 对每个已有 chromosome 做一次 SQL 搬运，轮次多且重复查询 release 染色体 | 合成一条带绑定参数的 `INSERT … SELECT`，保持替换范围 `touched chromosomes × imported assemblies` | 不对外启用 `imports.vcf`，不改 ClickHouse schema/分区/发布指针 |

## 2. 已核实的组件/API 责任边界

```text
Public Web (external/internal React) -> packages/api-client
 -> apps/api/app/api/v1/{genes,variants,search}.py
 -> services/release_context.py -> PostgreSQL published/active Release
 -> services/clickhouse_service.py -> variant_facts WHERE release_key + requested assembly

Admin -> app/api/v1/admin_imports.py (role and feature checks)
 -> PostgreSQL ImportTask / Outbox -> task_dispatch / shared jobs contract
 -> Celery run_import_adapter -> data_adapters.VcfAdapter (OFF by default)
 -> ingest.import_vcf -> import_manifest_repo (PostgreSQL fingerprint, advisory lock)
 -> ClickHouseEngine (HttpClickHouseEngine production / ChdbEngine acceptance)
 -> staging -> verify -> finalize_release -> manifest PUBLISHED
```

核对位置：
- `apps/api/app/api/v1/admin_imports.py`：导入创建、启用状态、权限与任务更新；
- `apps/api/app/core/features.py`：七类科学导入默认关闭，`imports.vcf=False`；
- `apps/api/app/core/task_contract.py` + `packages/jobs-py`：API/Worker 共享 Celery task 名称；
- `apps/worker/src/soymutdb_worker/tasks/ingest.py`：开关、源 SHA256、fingerprint、PG 串行锁、manifest lifecycle 与数据批次；
- `apps/worker/src/soymutdb_worker/tasks/import_manifest_repo.py`：PostgreSQL manifest 约束，专用连接持有 advisory lock；
- `apps/worker/src/soymutdb_worker/tasks/variant_finalize.py`：CH staging、去重、冲突判定与完整 Release 重建；
- `apps/api/app/services/clickhouse_service.py`：已发布 Release 的读侧查询，按 release_key 过滤；
- `apps/api/app/services/release_context.py`：公开 Release 上下文与发布状态。

注意：读侧以 Release 上下文筛选 `release_key`，**并不保证 ClickHouse 中同一已发布 release 的物理重建原子可见**。本次只优化 staging carry，不将现有 finalize 解释为安全原子发布。

### ClickHouse carry 前后 SQL

旧实现：先查 Release 的 DISTINCT chromosome，之后对每条 chromosome 发一条
`INSERT INTO staging SELECT … FROM variant_facts WHERE release_key=… AND chromosome=…`；
其中 touched 染色体额外排除本次导入的 assembly。

新实现：**恰好一次**：

```sql
INSERT INTO variant_facts_staging (<已存在的固定 BASE_COLUMNS>, import_id, batch_id)
SELECT <相同 BASE_COLUMNS>, {import_id:String}, {batch_id:String}
FROM variant_facts
WHERE release_key = {release_key:String}
  AND NOT (
    chromosome IN ({chromosome_0:String}, ...)
    AND assembly_key IN ({assembly_0:String}, ...)
  )
```

只有 touched 与 imported_assemblies 均非空时才添加排除表达式。字段/表名是代码固定白名单，所有用户或数据派生取值通过 `{name:String}` 绑定，不接受文本插值。合并后省去随染色体数量增长的 N 次命令往返，但服务器侧处理的数据量仍与 Release 大小相关，**尚未取得端到端延迟、CPU 或内存改善数据**。

必须验证：`v4/v5` 同染色体互不删除、未触及染色体保留、摘要只累计一次、重复导入不增量重复、不同 release 隔离、恶意输入不改变 SQL 结构、单次 carry。使用现有 `test_variant_finalize.py` 的 chdb 引擎，加上新的单命令回归。

## 3. E2E 与产物检查设计

- Online Demo Smoke：`.github/workflows/e2e-smoke.yml` 在 Pages 成功后和夜间运行 `e2e/playwright.config.ts`。**所有导航相对于带尾斜杠的 baseURL**，检查文档状态、非空 main、10 个核心路由、同源 JS/CSS 失败及非预期 JS/console 错误；保留 per-route JSON 与 Playwright trace。
- Local Preview：`playwright-local-preview.config.ts` 显式使用独立 `local-preview.spec.ts`，前置条件是真实启动 `8010` API 和 `5173` UI，运行前不由线上工作流伪造本地服务。
- Production E2E：保留 `playwright-production.config.ts` 的真实 API/非 Demo 数据严格门禁，Demo 控制台警告白名单**不能**流入此配置。
- Artifact：`check-production-artifact.sh --allow-demo` 允许 demo records，仍禁止占位 origin 等泄漏；生产构建不得添加 `--allow-demo`。不要使用对所有压缩 JS 的原始 `grep VITE_API_BASE_URL`。
- CI 安全：`workflow_run` 的事件来源/成功与主分支校验不得删除；独立 Smoke 不授予写权限、不运行用户可控制的凭据操作。

## 4. 不变约束 / 退出标准

1. PostgreSQL 是身份、Release、权限、manifest 和 workflow 权威；ClickHouse 是投影。MinIO 存对象，Redis 仅缓存/队列。
2. `release_key` / `assembly_key` / `public_id` 隔离及数据来源一致性必须保留；对同名基因跨 assembly 不做静默合并。
3. `SOYMUTDB_ENABLE_VCF_IMPORT` 和 `imports.vcf` 保持默认 OFF，未通过真实 HTTP ClickHouse、并发/恢复、Admin→导入→发布和回滚验收前不得翻转。
4. 不允许更改生产数据库数据、公开 release 指针、运行中服务、秘钥、域名、真实内容；提交仅在 review 分支，禁止自动合并/发布。
5. 不以 skip、xfail、禁用审计器或扩大误报白名单伪装通过；所有未运行测试明确记为 BLOCKED/未验收。
6. 科研数值/统计功能只接受真实有来源数据的单元与集成验证；不生成伪造的生物学性能结论。
7. 仅在相同 ClickHouse 版本/硬件/数据规模/并发下比较前后计时，报告 p50/p95、query_count、读写行数、峰值 RSS 与离散程度。**减少 SQL 数量不是等价于实测提速**。
8. 发生结果漂移或数据库破坏风险即停止优化，回滚本代码提交；不得通过重建现有公开库来修复测试。

## 5. 官方 API/行为依据（2026-10-09 核对）

- Playwright `baseURL` 与相对导航：<https://playwright.dev/docs/api/class-testoptions#base-url>。
- Playwright 测试本地服务的 `webServer`：<https://playwright.dev/docs/test-webserver>，仅供本地独立测试参考；本次没有假装本地 API 已启动。
- ClickHouse Python `client.command` / `client.insert`：<https://clickhouse.com/integrations/python>。
- ClickHouse 查询参数与 `{name:String}`：<https://clickhouse.com/blog/whats-new-in-clickhouse-21-12>。
- ClickHouse MVs 是 insert triggers；DROP PARTITION/DELETE 不会自动反向修正汇总：<https://clickhouse.com/blog/common-getting-started-issues-with-clickhouse>。
- GitHub `workflow_run` 触发语义：<https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows>；安全边界：<https://docs.github.com/en/actions/reference/security/secure-use>。

本轮不声称已在生产 HTTP ClickHouse、Docker 镜像或公开域名完成验证；相应内容见执行文档的门禁状态。


## 6. 官方 API 兼容性更正与部署态测试分离（2026-10-09）

原第一轮设计展示的 `INSERT … SELECT … {name:String}` SQL 是**逻辑模板**，不可作为 ClickHouse HTTP `client.command` 的服务端参数 SQL 直接发送；官方 Python Client 文档规定 server-side `{name:Type}` binding 仅适用于 SELECT。生产 `HttpClickHouseEngine.execute` 在调用客户端前改为 `%(name)s` 占位符，让 `clickhouse-connect` 实现客户端绑定、转义；ChdbEngine 保持 `{name:Type}`。两端对拍需要验证引号、空字符串和 Unicode 的值绑定，且不得手写插入数据取值到 SQL。

PR 浏览器测试与线上部署检查严格隔离：`pull_request` 构建 PR 本提交静态制品，启动离线 Playwright server 做路由和交互；Nightly/Post-Deploy 在线 Smoke 检查现有 GitHub Pages 实际 404。根因不是测试的断言太严格，而是公共部署提交 `gh-pages@11f2e23c` 仍停留在 2026-08-25；治理未过，不得绕过 `main` CI 发布未经验证的产物。

依赖审查升级策略与版本矩阵见[执行合同 §4](../../aegis/plans/2026-10-09-ci-e2e-import-performance-execution.md#4-第二轮-ci-复查与依赖更新2026-10-09按审计报告)。本轮新增 `.github/dependabot.yml` 仅对 GitHub Actions 与三个 `uv` 子项目创建候选 PR；pnpm 12.5.1 不在 GitHub Dependabot 当前官方兼容列表里，故不冒然打开 npm ecosystem 的自动改锁。
