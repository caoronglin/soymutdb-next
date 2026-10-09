# 2026-10-09 CI/E2E 与 Release carry 定向执行合同

> 关联设计：[CI/E2E 与 ClickHouse 导入性能](../../superpowers/specs/2026-10-09-ci-e2e-import-performance-design.md)
>
> 基线：`main@2c5f0f15`；实施分支：`fix/audit-20261009-ci-carry-perf`。
> **仅限工作分支 PR，默认 No-Go；本文件不是新 global plan owner。**

## 0. 执行顺序与验收表

| 任务 | 范围 owner | 必须有的验收 | 当前状态 |
| --- | --- | --- | --- |
| T0 现状和 API 调用链 | 本设计/本执行文件 | HEAD、3 个失败 Job 的原始日志、真实 API 层入口与官方文档链接 | 已检查，文档归档 |
| T1 baseline artifact gate | `.github/workflows/baseline-validation.yml` | 构建 demo 时三处 artifact 扫描通过；注入占位 origin 时确实失败；不得禁用生产门禁 | 已修改，待 CI |
| T2 Online/Local 分离 | `e2e/tests/*smoke* / local-preview*`、Playwright 配置 | `--list` 中在线恰有 10 route tests，不出现本地测试；部署态运行无 127.0.0.1 请求；独立 local suite 仍可发现 | 已修改，待浏览器/CI |
| T3 ClickHouse carry 性能 | `variant_finalize.py` 与对应 pytest | 同一 Release 跨 chromosome/assembly 完整保留；1 次 carry INSERT；回归幂等/汇总/SQL 注入 | 已修改，待 chdb CI |
| T4 合并/性能放行 | PR reviewer/CI | CI 全绿、基线恢复、真实 ClickHouse HTTP 资格、资源对照实验；审查通过后再讨论合并 | 未完成，禁止自动合并 |
| T5 发布原子性 | 独立后续设计 PR | 未启用 VCF；规划原子投影和发布指针切换、并发、宕机和恢复 | 未执行，不在本 PR |

## 1. 分阶段实施：按 PR 每步可检查

### Phase A — CI 真实性

1. 将 baseline CI 中全文搜索 `VITE_API_BASE_URL` 替换为仓库已有 `check-production-artifact.sh`，Demo 仅在明确标记下允许。不得删除生产扫描器。
2. 将线上 `online-smoke.spec.ts` 对 `127.0.0.1:5173` 的依赖移到独立的本地 suite；部署态导航一律相对 `SMOKE_BASE_URL`。
3. 维持原有 `workflow_run` 安全条件和 `contents: read` 权限；不增加新的外部 Actions/Secrets/发布操作。
4. 检查 `e2e/README.md` 与当前 Playwright 配置一致，必须区分 Demo、Local、Production。

**验证命令**（在安装正确依赖并构建后）：

```bash
# 项目根目录
bash scripts/build-static-apps.sh
bash scripts/check-production-artifact.sh apps/web/dist/external --allow-demo
bash scripts/check-production-artifact.sh apps/web/dist/internal --allow-demo
bash scripts/check-production-artifact.sh apps/admin/dist --allow-demo

cd e2e
npm ci
npx playwright test --list
npx playwright test -c playwright-local-preview.config.ts --list
npx playwright test                # 网络可用时访问真实部署的 Demo
```

所有运行结果分别注明 PASS/FAIL/BLOCKED。只有 `--list` 成功**不代表浏览器端到端通过**。

### Phase B — ClickHouse carry

1. 不调整 `BASE_COLUMNS`、Release/assembly ID 定义、MV、表结构或任何公开 API。
2. 原语义：旧 Release 的 touched chromosomes 内仅剔除此次导入的 assemblies；所有其他事实复制入 staging，保留 v4/v5 同染色体及不触及染色体。
3. 改成一次 `INSERT INTO staging SELECT ... FROM base WHERE release_key=? AND NOT(touched AND imported)`。构造数量有界的 SQL 占位符；取值严格绑定，不能用户插值。
4. 保持 `conflicting_variant_ids`、`_purge_release_summaries`、`_drop_release_partitions`、`_rebuild_base_from_staging` 的既有行为；这不是发布协议重写。
5. 新增真实 chdb 回归，断言唯一 carry 命令、完整数据、正确汇总；原有测试仍验重试、冲突、跨 Release、恶意输入。

**验证命令**（需 Python 3.14、uv、chdb 和隔离环境；若不可用记录 BLOCKED）：

```bash
cd apps/worker
uv run --locked --extra dev pytest tests/test_variant_finalize.py -q
uv run --locked --extra dev pytest tests/test_vcf_import.py -q
uv run --locked --extra dev ruff check src/soymutdb_worker/tasks/variant_finalize.py tests/test_variant_finalize.py
```

### Phase C — 完整集成与性能测量（不得虚报已完成）

- GitHub PR 完整 CI：API/worker 真实 PostgreSQL、ClickHouse migration fixture、frontend/产物检查、dependency-governance、Pages smoke。按失败 Job 与日志判断：环境故障如镜像 Registry 502 与代码问题分别记录。
- 真 HTTP ClickHouse：使用隔离数据、生产同版本协议、同规格机器重复执行旧/新 carry，测 3–5 次冷/热对照，单独列吞吐、p50/p95、命令数和峰值资源。必须对拍行 ID、release/assembly、明细/汇总和注释来源。
- 在模拟中断点（purge 之后、partition drop 之后、rebuild 中）验证恢复前公开查询不可观察损坏；若当前协议无法保证，明确 **No-Go**，立项新发布架构设计，而不是放行现有 VCF。
- 整个 PR 不启用 `SOYMUTDB_ENABLE_VCF_IMPORT`，不在生产环境操作数据或进行自动发版。

## 2. 硬性约束

| ID | 约束 |
| --- | --- |
| H01 | 首先读 `AGENTS.md`、根 `plan.md`、当前 `docs/dev/project-status.md`、ADR-0005、真实代码，再开展实施；旧计划与代码冲突以经过验证的代码/门禁为事实基础。 |
| H02 | 保留基线与未知用户工作区文件，不执行 reset/force push，不修改现有 draft PR #2–#4，不合并或触发生产操作。 |
| H03 | 不破坏原 release/assembly/public_id、授权/CORS/CSRF、外内双站、缓存、来源标识、无假数据等科研契约。 |
| H04 | 任何性能改动先断言功能等价和负例，再测量；命令数降低不能视为 p95 降低。 |
| H05 | SQL 标识符固定、数据值绑定。禁止 user-provided SQL、静默冲突解决、跳过失败 mutation。 |
| H06 | CI 不能通过删测试、改 assert、宽泛 except/skip 或替换成假数据修绿；区分外部 Registry/GitHub 故障。 |
| H07 | 无法运行的测试写 `BLOCKED: <具体依赖>`；每轮记录命令、退出码、SHA、证据链接和可执行恢复方式，不抄写旧通过数。 |
| H08 | 从一份 Git commit 构建到发布，不能在发布阶段重新构建；生产变更独立审批和可执行回滚。 |
| H09 | docs 只有本次设计/执行子文档，根 `plan.md` 仍是唯一全局计划；不创建另一份竞争 `PLAN.MD`。 |
| H10 | 限定路径和最小变更，避免依赖大规模升级；新增外部 API 必须附精确的官方版本/URL 与兼容性测试。 |

## 3. 最终证据要求与回滚

需要在 PR 里附：最终 HEAD、changed-files、每条真实命令与退出码、GitHub Actions 链接、对应源码路径、未完成项和复现方法；GitHub Actions 是线上证据，不能被本地断言替代。

回滚：对本 PR 的独立提交使用常规 `git revert`，保留历史，不强推；已发数据需依据不可变备份和发布指针的独立恢复合同操作，**不能靠 revert 源码恢复 CH 数据**。

本次提交阶段的诚实结论：源码与静态关系已核对、最小修复已经写入 review 分支；完整 chdb、在线 Playwright、真实 ClickHouse 和发布端到端的退出码尚待远端工作流验证。因此当前为 **No-Go**。


## 4. 第二轮 CI 复查与依赖更新（2026-10-09，按审计报告）

本阶段实际证据：
- PR #5 历史运行 `37896418357` 基线 **success**（Web/Admin、OpenAPI、Ubuntu PG、Windows 安装器）。
- 历史运行 `37896418481` 主 CI：Frontend、API + Worker（包含 chdb）、DB A/B、MCP、ClickHouse fixture 各自 PASS；`Dependency graphs + governance` FAIL，镜像/Kubernetes/发布 Job 因门禁中断 SKIP，不能宣称成功。
- 审计制品 `dependency-governance-bfebeb0c908fbbfd8ad4a505ff0db70b04c7c762` 的 `summary.json` 及各报告已经逐项检查。之前概括为 `analyzer_exit_nonzero` 的项都存在报告，**不能解释为临时网络中断**。
- PR 上对旧 GitHub Pages 的 E2E 返回 6 个 404：`gh-pages` 仍是 **2026-08-25** 产物。本轮改成 PR 自己的静态制品离线 E2E，线上 Nightly/Post-Deploy Smoke 继续检查真实部署，404 不作豁免。

### 精确的安全升级矩阵（先修改锁，再提交审核）

| 生态 | 现有受影响版本 | 安全候选 / 后续 | 报告证据 |
| --- | --- | --- | --- |
| Python API/Worker | `urllib3 2.7.0` | `2.8.0`（PyPI 已发布） | `PYSEC-2026-4175/4176/4177` |
| Python API | `multidict 6.7.1` | `6.9.1`（保持 6.x 避免无需求的 major 跃迁） | `GHSA-54p9-h82j-f925` |
| Python API/MCP | `PyJWT 2.13.0` | `2.15.1`（官方最新，须复验 claim/algorithm/token 测试；`PYSEC-2026-4146` 报告暂未列修复版本，绝不自动豁免） | `PYSEC-2026-4140…4152` / `4183` |
| pnpm workspace | `axios 0.33.0` override | `>=0.34.0`，确认 0.x 升级行为并固定可兼容版本 | `GHSA-x97p-jq2g-jp4f` |
| pnpm workspace | `source-map-js <1.2.2` | `>=1.2.2` | `GHSA-68fv-2mgg-jv7q` |
| pnpm workspace | `tinypool <2.1.2` | `>=2.1.2`，校验 Vitest 执行池行为 | `GHSA-5gmw-xhrv-c9v3`, `GHSA-85c8-ppgw-ccpr` |
| pnpm workspace | `braces <=3.0.3` | **当前审计器未报告修复版本**；确认入口路径/曝露面，保持阻断，不增 GHSA ignore | `GHSA-vfj7-8cjw-p6xm` |
| pnpm lock | 不同 Vite/Vitest peer variant 和 `hash-base` 可以去重 | 在锁升级验证中执行 `pnpm dedupe`，检查修改是否符合目录/构建约束 | `pnpm dedupe --check` |
| knip | 87 个候选文件，30 个 issue files | 依据实际 Umi entry、静态路由、CI 脚本和独立 e2e 入口审查；不可直接批量删除、不能全面 ignore | `knip.json` |

**受限环境结论**：本轮可以查阅锁定版本与安全报告，但当前执行环境不能访问 npm/PyPI Registry 完成可重复的解析。因此本 PR **不直接修改** `uv.lock`、`pnpm-lock.yaml` 或依赖 specifier（避免 `--locked` / `--frozen-lockfile` 变红及伪造 lock 哈希）；新增 Dependabot 对 `uv` 子项目及 Actions 的每周候选 PR，只有合并到默认分支后才会运行。pnpm 12 锁不假定获得 Dependabot 支持；手动使用固定 pnpm 12.5.1 重算。

可在有网络的隔离工作区重算，**每一组改动独立提交**：

```bash
cd apps/api
uv lock --upgrade-package 'urllib3==2.8.0' --upgrade-package 'multidict==6.9.1' --upgrade-package 'PyJWT==2.15.1'
uv lock --check
cd ../worker
uv lock --upgrade-package 'urllib3==2.8.0'
uv lock --check
cd ../mcp-server
uv lock --upgrade-package 'PyJWT==2.15.1'
uv lock --check
cd ../..
# pnpm-workspace.yaml 中的受影响 overrides 和相应 peer/依赖范围须先评估并更新；
# 然后运行固定版本 12.5.1 的 pnpm 更新锁，而不是手动拼凑 YAML：
pnpm install --lockfile-only
pnpm dedupe
pnpm install --frozen-lockfile
pnpm deps:audit
bash scripts/acceptance.sh --profile contracts
```

对 `PyJWT` 强制补 JWT alg allow-list、JWT 签名/时序边界、refresh 旋转和吊销等测试；对 `axios` 重点比对拦截器、取消、错误转换、CSRF；对 `tinypool` 重点运行 Vitest/Playwright 混合链。任何 override 只能在成功解析+真实测试后进入 main。

### 第二轮代码/API 修复

- `HttpClickHouseEngine.execute`：ClickHouse Connect 文档指出服务端 `{name:Type}` 仅对 SELECT 查询提供支持。DML `INSERT/ALTER` 将固定的 `{name:String}` 占位符转成驱动的客户端 `%(name)s`，仍通过 `parameters` 进行转义；`scalar/query_rows` 不改。
- 增加含特殊引号的 HTTP Adapter mock 测试，并要求真实 HTTP ClickHouse 验收；先前仅 chdb 的 SELECT/INSERT 不足以证明生产兼容。
- `dependency_governance.py` 输出明确的 npm/Python GHSA、受影响版本、修复范围、knip 候选数量和 dedupe 提示；runner 返回码仍按原审计器决定。
- `e2e-smoke.yml`：pull_request 用受测分支构建 + 离线浏览器测试；schedule/workflow_dispatch/workflow_run 保留线上的旧站检查，真实缺陷不会被 PR 阶段掩盖。
- Node24 action deprecation warning：当前 Actions pin 是旧 Node20 runtime。候选迁移 `actions/checkout`、`setup-node`、`setup-python`、`upload-artifact` 新大版本前应按官方 runner 最低版本和 SHA pin 审查，避免直接替换造成供应链漂移。

参考官方：[uv 精准升级](https://docs.astral.sh/uv/concepts/projects/sync/#upgrading-locked-package-versions)，[ClickHouse Connect 绑定](https://clickhouse.com/docs/integrations/language-clients/python/driver-api)，[Knip monorepo 入口](https://knip.dev/reference/configuration)，[GitHub Dependabot uv](https://docs.astral.sh/uv/guides/integration/dependabot/)，[GitHub Dependabot 生态/版本支持](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)，[GitHub Actions workflow_run](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)。

### 第二轮验收门禁

- 运行 PR 当前 HEAD 的全量 CI、baseline、PR 自制品 Playwright。三者必须以**同一提交**关联，不拼接不同提交的 PASS。
- 为 Live Pages 另行记录部署 digest+日期以及线上 E2E 的 404；只有经 main 完整 CI 的已验证 artifact 才允许更新 pages。
- 安全通告未修复时仍为 **No-Go**；不允许使用 `continue-on-error` / `pnpm audit --ignore-registry-errors` / `pip-audit --ignore-vuln` 来称作全绿。
