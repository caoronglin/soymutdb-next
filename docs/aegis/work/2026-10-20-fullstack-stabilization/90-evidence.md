# 当前已验证证据

## 2026-10-29 续作轮：门禁复跑与修复后的证据

全部命令由本轮亲跑，日志在 `.cache/gates/`；分支/HEAD 未变（`fix/fullstack-stabilization-20261020` /
`01fc163a4`），**未提交、未 push、未合并**。

| 门禁 | 精确命令 | 结果 |
| --- | --- | --- |
| 契约层 | `bash scripts/smoke.sh --profile contracts` | **SMOKE PASS**（349 passed + 5 subtests），exit 0，`.cache/gates/contracts-run-20261026.log` |
| API 全量 | `cd apps/api && ../../.mamba-root/envs/py315/venvs/api/bin/python -m pytest tests -q`（`SOYMUTDB_TEST_DATABASE_URL` 指向本轮**全新**隔离库） | **2612 passed / 8 skipped**，exit 0，`.cache/gates/api-full2.log` |
| Worker 全量 | `.mamba-root/envs/py315/venvs/worker/bin/python -m pytest apps/worker/tests -q` | **672 passed / 35 skipped**，exit 0，`.cache/gates/worker-full2.log` |
| jobs-py | `.mamba-root/envs/py315/venvs/api/bin/python -m pytest packages/jobs-py/tests -q` | **107 passed**，exit 0（后端门禁代理记录，`.cache/api-gates/`） |
| 门户 lint | `pnpm --filter @soymutdb/web lint` | exit 0，`.cache/gates/web-lint2.log` |
| 门户 typecheck | `pnpm --filter @soymutdb/web typecheck` | exit 0，`.cache/gates/web-typecheck2.log` |
| 门户 Vitest | `apps/web` → `vitest run --pool=threads --maxWorkers=1` | 56 files / **503 tests**，exit 0；工作区 turbo `test` 合计 **1274**（11/11 包），`.cache/gates/turbo-final2.log` |
| OpenAPI 契约 | `pnpm --filter @soymutdb/api-client generate:api-client` + `check:contract` | exit 0，route visibility `status: PASS`，`.cache/gates/openapi-gen.log`、`.cache/gates/contract-check.log` |
| 内容键契约 | `.mamba-root/envs/py315/venvs/api/bin/python scripts/check_content_key_contract.py` | `content-key contract OK (70 literal portal get() keys, 121 registered content keys)`，exit 0 |
| 本轮定向回归 | `pytest apps/api/tests/test_variant_exports.py`（23）、`test_export_assembly_scope.py`（18）、`test_mutant_line_search.py`（12）、`test_release_bound_queries.py`（17） | 各 exit 0 |
| 本轮定向回归 | `pytest apps/worker/tests/test_export_query.py` / `test_export_public_artifact.py` / `test_export_lifecycle.py` / `test_worker_database_url.py` | 各 exit 0（新增 8 例） |
| 本轮定向回归 | `vitest run src/routes/variants src/routes/downloads.test.tsx src/lib/use-variant-export.test.tsx` | 5+3+2 例全绿 |
| frontend 门禁 | `bash scripts/verify-frontend-artifacts.sh` | **21 步全过 → `frontend verification passed`，exit 0**，`.cache/gates/frontend-gate5.log`；双站隔离 exit 0，`.cache/gates/site-variants2.log` |
| workspace lint/typecheck | `pnpm turbo run lint typecheck --concurrency=1` | **36/36 tasks**，exit 0，`.cache/gates/turbo-final2.log` |

### 环境限制的可复现证据（非代码缺陷）

- `os.cpus().length = 256` ⇒ webpack 自带 `TerserPlugin` 默认 `parallel: true` ⇒ 255 个压缩 worker；
  本机沙箱拒绝该规模的线程创建（`EAGAIN` / `newosproc`）。
  **对照实验**：同一棵树在把可见 CPU 数降到 4 之后 **12.98s 编译成功**
  （`.cache/gates/jbrowse-build-retry4.log`，其中含 `Webpack: Compiled successfully in 12.98s`）。
- 同一配额也导致 `pnpm turbo run test`（默认并发 10 个包）在本机 `EAGAIN`：
  pnpm 自身报 `spawn the pacquet runtime thread: WouldBlock`，
  vitest 报 `OS can't spawn worker thread: Resource temporarily unavailable`。
  这类失败**没有任何断言失败**，且 CI 镜像核数少、不会触发。
- 绕过方法与结论已写入 `.ai-memory/LOCAL-RUN-ENV.md`（仅本机，不改仓库构建配置）。

### 仍未验证（不得据此宣称完成）

真实浏览器 E2E、真实 broker/S3 的导出整链、Docker 作业（compose-acceptance / image-build /
release / clickhouse-migration / mcp-e2e）、依赖治理里需要联网的 `pnpm audit` 与 `npm ci --prefix e2e`、
`install_python_workspace.py` 的联网安装、PG 18 迁移、生产发布。
## 2026-10-25 后续直接验证：以此段更新“未重建/旧解释器”状态，不替代浏览器或 DB 验收

授权验证根目录与完整命令：[integration-verification-20261025/SUMMARY.md](../../../../.cache/integration-verification-20261025/SUMMARY.md)。本轮不改业务源码，不安装、连 DB、起服务或 Git 写。

| 本轮亲跑，Node 26.10.0 / pnpm 12.11.2 / Python 3.15.0 | 结果 | 根目录下日志 |
| --- | --- | --- |
| 门户相关 / 管理端相关 / 客户端相关 | **100 / 28 / 23 passed**，各 exit 0 | web-related / admin-related / client-related.log |
| JBrowse Node 契约 | **71 passed，0 failed** | jbrowse-contract-tests.log |
| 客户端 OpenAPI 同步 + 路由可见性 / typecheck | **各 exit 0，PASS** | client-contract / client-typecheck.log |
| 门户双站 / admin / JBrowse 标准构建 | **各 exit 0**，门户各 28 HTML | web-build-sites / admin-build / jbrowse-build.log |
| 双站 sentinel 隔离 / 头部 / 路径 / 壳资源 / bundle+图表预算 | **各 exit 0** | site-isolation、artifact-*、app-shell-assets、*-budget.log |
| 三应用 lint/typecheck，locale、插值、可见文案、query-key/admin 架构 | **各最终 exit 0** | 对应独立 log/exit；JBrowse 首次 lint 命令 exit 127 后按 workspace binary 正确调用通过 |
| 接受项 3 契约 + per-render 翻译 mock 契约 | **3 passed / 1 failed**，当前 **10 个文件**不合规 | policy-and-i18n-contracts.log（未改 guard） |

同一份前一恢复阶段 audit JSON 的固定 Python 3.15 策略 readback：`policy-readback-315.json` = passed=true、0 接受项；没有重新抓 feed。新制品逐文件 SHA256 在 `artifact-sha256.json`（external 72 files、internal 71、admin 68、JBrowse 143）。这不是旧构建的追溯证明，也不证明真实读屏/390px/Tab 或 API 行为。

未跑 full shared frontend verifier、全仓测试和 CI；未操作损坏 PG、未做 PG18 迁移/DB 隔离验收。HEAD/baseline 未变，dirty 路径 104→104。当前红灯及范围边界未关闭，**不可宣称整仓通过/可合并**。

## 2026-10-25 Lead 直接最小恢复（用户明确授权；不是全仓验收）

证据根目录 [direct-recovery-20261025](../../../../.cache/direct-recovery-20261025/SUMMARY.md)，含精确命令、TaskStart 副本、所有失败尝试与偏差。下方历史“仍红/测试待修/等待批准”仅描述当时时点，以本节更新为准，不删除历史证据。

| 本轮亲跑 | 结果 | 根目录下日志 |
| --- | --- | --- |
| 新搜索计数回归，修前/修后 | 1 failed + 27 passed → **28 passed，exit 0** | search-red-pinned.log / search-green.log |
| E2E search+genes 类型，修前/修后 | TS2322/TS2367 → **exit 0** | e2e-types-bundler-before.log / e2e-types-after.log |
| Playwright public config --list | **15 项，exit 0；未执行** | e2e-public-list-after.log |
| ESLint 3 个改动文件 / apps/web tsc | **各 exit 0** | recovery-eslint.log / web-types-after.log |
| npm registry 全严重度审计 | **exit 1：0 high/critical、2 moderate、1 low** | audit-full.json / audit.exit |
| 同一报告经未改的仓库策略+真实空接受清单 | **passed=true，findings=[]，accepted=[]** | gate-evaluation.json |

策略 readback 使用 Python **3.14.9**，不是项目 3.15 pin，不作 Python CI 同等结论。未新增/续签接受项。root workspace/lock 本轮未改；前一中断批次 frozen=0、dedupe=0、peer=1 的证据位于 `.cache/new-advisory-implementation/logs/`，不是本轮新跑。

过程披露：首次 `pnpm --dir e2e exec ... --list` 自动安装隔离 E2E 环境 5 个包后因默认 online-smoke 配置未找到用例而 exit 1；改直接调用已安装执行文件及 public 配置后只做列举。另一次 NodeNext resolution 与一次错误 env 相对路径失败已分日志保留。**不得把本轮写成“未安装”、不得把 list 当浏览器通过。** 未改数据库/服务，未 git 写/清理；HEAD `01fc163a4`，dirty 103→104，baseline 仍祖先。

接受项 fixture 修复与独立 3 项通过见 `.cache/acceptance-fixture-review/REVIEW.md`；实施代理突破窄测指令跑 68/69 项整模块、把当时 body-parser high 误写 vite high 均是已核实的过程/报告偏差。S1/S2/S3/S4 历史实测与独立覆盖范围见 `20-checkpoint.md` 顶部；全仓/CI、健康 PG18/迁移、broker/S3、浏览器、双站新制品仍未验，**整体不完成**。

## 2026-10-24 晚间：注销已失效的 `braces` 风险接受项（用户经确认工具明确授权；本切片亲跑；治理门禁**仍 FAIL**）

**本节动作与边界（执行者=本切片实施子代理，全部命令由其亲跑）**：**只审计 + 一次窄文件编辑 + 工作记录追加**。**未安装、未改 lock、未起服务、未连数据库、未做 Git 写**（HEAD 仍 `01fc163a4c6488f97fe44ecf8f587b145cf989aa`；`git reflog` 末条仍是 2026-10-20 的设计提交）；**未写治理 doc**（`docs/ops/dependency-governance.md` 不动）；**未新增/续签任何风险接受**；**未读 `.npmrc` / `.env`**，未用任何 config 命令提取秘密。写入面**只有 3 个文件**：`security/advisory-acceptances.json`、本目录 `20-checkpoint.md`、本目录 `90-evidence.md`。

### 0. 本切片亲跑的锚点

| 对象 | 实测值 | 命令 / 留存物 |
| --- | --- | --- |
| 分支 / HEAD | `fix/fullstack-stabilization-20261020` / `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（**未变**） | `git rev-parse` |
| dirty 规模 | **94 → 95**，增量 **+1** = 唯一那条被修改的 tracked 文件 `security/advisory-acceptances.json`；工作记录位于**原本就 untracked** 的 `docs/aegis/work/2026-10-20-fullstack-stabilization/` 内，**不新增** status 条目 | `git status --porcelain=v1 \| wc -l` |
| **新鲜全严重度 audit** | **exit 1**；**8 条** = **1 high**（`body-parser` `GHSA-27r3-jxmh-p828`）+ **4 moderate**（`fast-uri` ×2、`react-router` ×2）+ **3 low**（`elliptic`、`fast-uri` ×2）；**`braces` 0 条** | `pnpm audit --registry https://registry.npmjs.org/ --json`；`out/audit-fresh-full.json`、`logs/01-fresh-audit.exit.txt` |
| 包集口径 | totalDependencies **1895** / deps 1559 / dev 155 / optional 198 —— 与前次留存**一致** ⇒ 3 → 8 的差额**全部来自新发布的 advisory** | `out/audit-fresh-full.json` 的 `metadata` |
| 锁 / manifest 未动 | `pnpm-lock.yaml`、`pnpm-workspace.yaml`、`package.json` 切片前后 **sha256 校验 OK** | `sha256sum -c out/lock-snapshot-before.sha256.txt` |
| 删除前门禁 | **exit 1（FAIL）**，未接受项 **2** | `out/gate-before.json`、`logs/02-gate-before.exit.txt` |
| 删除后门禁 | **exit 1（FAIL）**，未接受项 **1** | `out/gate-after.json`、`logs/03-gate-after.exit.txt` |
| 前后同一份报告 | `audit-fresh-full.json` sha256 `8e17f2c2…` **前后完全一致** | 两份 `gate-*.json` 的 `report_sha256` |

### 1. `braces` 为何不再出现 —— 上游事实（本切片实测，非转述）

| 证据源 | 事实 |
| --- | --- |
| GitHub 官方 advisory API `GET /advisories/GHSA-vfj7-8cjw-p6xm` | 标题现为 **"Withdrawn Advisory: braces vulnerable to stack-exhaustion denial of service through deeply nested patterns"**；`published_at 2026-09-18T18:31:41Z`；**`withdrawn_at 2026-10-23T12:53:02Z`**；`cve_id CVE-2026-93687`；severity high（记录保留，结论已撤回） |
| OSV `GET /v1/vulns/GHSA-vfj7-8cjw-p6xm` | `withdrawn: 2026-10-23T12:53:02Z`；`modified: 2026-10-23T13:00:05Z` |
| 本仓锁文件 | **`braces@3.0.3` 与 `sprintf-js@1.1.3` 仍在锁内**（`pnpm-lock.yaml` 仍可 grep 到）⇒ **被撤回 ≠ 已修复；feed 不再报 ≠ 包安全** |
| 新 advisory 的发布时间线 | `body-parser` `GHSA-27r3-jxmh-p828` published **2026-10-23T20:53:11Z**；`fast-uri` 四条 published **2026-10-23T21:36–21:41Z** ⇒ 均**晚于**前次留存 audit（2026-10-23T16:58Z），解释了 3 → 8 |

留存物：`out/github-advisory-braces.json`、`out/osv/*.json`、`out/osv-timeline.txt`。

### 2. 删除前后同一份报告的门禁判定（仓库自带判定，非重实现）

判定脚本 `.cache/stale-braces-retirement/scripts/40-gate-eval.py` 直接调用仓库自带的 `scripts/dependency_governance.py` 的 `load_advisory_acceptances` + `evaluate_advisory_report`，**只读**接受文件。

| 阶段 | 退出码 | 未接受项（逐字） | 接受项 |
| --- | --- | --- | --- |
| **删除前** | **1（FAIL）** | ① `body-parser: high GHSA-27r3-jxmh-p828; vulnerable=<1.20.9 fixed=>=1.20.9` ② `braces: acceptance for GHSA-vfj7-8cjw-p6xm matches no reported finding; delete it — a stale acceptance is not a record of a live risk` | 1 条（陈旧，未被消费） |
| **删除后** | **1（FAIL）** | ① `body-parser: high GHSA-27r3-jxmh-p828; vulnerable=<1.20.9 fixed=>=1.20.9` | **0 条** |

⇒ **门禁依旧红**，但红的原因**换了**：陈旧接受项这条噪声被清掉，剩下的是**本次 feed 新出现的、可修的** `body-parser@1.20.8` high（`patched >=1.20.9`）。**本次删除没有、也不打算让门禁变绿**；`body-parser` **未**签署接受项（明确禁止新增/续签）。

### 3. 文件范围（唯一实质改动）

`security/advisory-acceptances.json`：**+1 / −20**，仅删除 `GHSA-vfj7-8cjw-p6xm` / `braces` 一条 entry，`"acceptances": []`；`schema_version` 与 13 行 `_comment` **逐字节不变**；**无其它接受项**（原文件仅此 1 条，故"其它接受项字节语义不变"为**空集，vacuous**）；**未改** `accepted_by` / `expires_on` / 任何字段（整条已删）。留存物：`out/acceptances-removal.diff`、`out/advisory-acceptances.{before,after}.json`。

### 4. 连带代价（如实带出，不淡化）

`scripts/test_ci_job_contracts.py::test_advisory_acceptance_is_narrow_expiring_and_signed` **由绿转红**。根因：该测试读取**真实**接受文件并断言 `assertTrue(entries)`（line 810），且后续 `payload["acceptances"][0]`（line 858 / 873 / 886 / 896）**结构上要求文件里至少 1 条 entry**。**基线对照已实测**（临时还原 HEAD 内容、未做任何 Git 写）：

| 接受文件内容 | 套件结果 |
| --- | --- |
| HEAD 内容（切片前） | **68 tests / 1 failure** —— 仅 `test_i18n_handling_needs_no_per_render_double`（**脏树既有问题**，与本切片无关） |
| 本切片后（注销） | **68 tests / 2 failures** —— 新增即上述接受项测试（`AssertionError: [] is not true`） |

**本切片不修改该测试**（授权写入面只有 3 个文件），且**无法**靠"补一条接受项"绕过 —— 那正是被明令禁止的新增/续签风险接受。**最小修复方向（留待授权）**：改为使用**临时目录内的合成 acceptance fixture**，不再依赖真实文件非空。

### 5. 未做的动作与未关闭的欠账

- **未写治理 doc**：`docs/ops/dependency-governance.md` 仍写着旧的 stale 接受项口径（其 L175 / L345），**本切片不动** ⇒ **待办欠账**。
- **未签署 `body-parser` 接受项** ⇒ 治理 `pnpm-audit` gate **仍 FAIL**；`body-parser@1.20.8 → >=1.20.9` 是**可修**的，属独立受审后续（非本次范围）。
- **前端口径已同步**：用户**已批准**前端改 MiniMax **双评审**，A/B **只读评审已启动**；工作记录里"未获批准 / 双评审未完成"的**等待状态已结束**（原文保留，仅加 〔订正〕 标注）；**双评审结论尚未回收** ⇒ 前端工作**仍未完成**。
- 既有欠账**全部不变**：CI 计费、损坏 PG 禁止再操作、PG18 迁移、真实 broker/S3/浏览器端到端、全仓回归、`vite` 运行时未证、admin/jbrowse 未重建。

**效力边界**：本节是**一次窄切片的事实与证据记录**，**不是**验收、**不是**合并批准。注销动作本身**可接受**；**整体不可合并、未提交、未 push**，**依赖治理目标未完成**。

## 2026-10-24 文档订正 + vite 正式切片落地（只读复核与文档订正；切片 accept-with-gaps；整体仍不可合并）

**本节动作**：**只读复核 + 文档/证据口径订正**。**未跑任何测试、未安装、未联网、未连数据库、未起服务、未做 Git 写**（`git status --porcelain` 订正前后同为 **94**；HEAD 仍 `01fc163a4c6488f97fe44ecf8f587b145cf989aa`；`git reflog` 无新增；`security/advisory-acceptances.json` 逐字节未动）。**未改代码 / 依赖 / lock / 风险接受**；写入面仅限 `docs/ops/dependency-governance.md`、本目录两份工作记录、`.cache/vite-targeted-implementation/SUMMARY.md`，以及 `.cache/vite-targeted-implementation/out/correction/`（**追加，不覆写任何原件**）。

**执行者分级（全文严格遵守；不得把他人亲跑写成本人亲跑）**：

| 标记 | 含义 | 留存物 |
| --- | --- | --- |
| **【本次订正会话亲跑·只读】** | 本节所有重新计算的值，由本次会话**亲自**从仓库字节重新计算 | 本节 §0 表、`.cache/vite-targeted-implementation/out/correction/*.md` |
| **【vite 实施代理亲跑】** | 正式 vite 切片的实施子代理执行 | `.cache/vite-targeted-implementation/logs/`、`out/` |
| **【vite 独立复核代理亲跑/复算】** | 另一受派子代理严格只读复核 | 复核结论 **accept-with-gaps** |
| **【D1 / F1b 既有留存，本次未重跑】** | 更早批次的留存证据 | `.cache/d1-implementation/`、`.cache/f1b-review/` |

### 0. 本次会话亲自只读核实的锚点【本次订正会话亲跑·只读】

| 对象 | 实测值 | 命令 |
| --- | --- | --- |
| 工作树条目数 | **94**（订正前后相同） | `git status --porcelain \| wc -l` |
| HEAD | `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（**未变**） | `git rev-parse HEAD` |
| 治理 doc vs `HEAD` 行增量（**订正前快照**） | **+287 / −0** | `git diff --numstat HEAD -- docs/ops/dependency-governance.md` |
| D1 批次在该 doc 的份额 | **+108** | `.cache/d1-implementation/13-final-scope-check.log:145` |
| 本切片的份额（**行数**口径） | **+179** | 287 − 108 |
| `out/final-governance-doc.diff` 的**文件行数** | **316**（**不是**新增行数） | `wc -l` |
| D1 基线锁副本 | `sha256 667a7f3d…` **等于** `out/source-files.sha256.txt` 记录的**前置**锁哈希 ⇒ 65 行锁 patch **是**真正的单切片 diff | `sha256sum out/pnpm-lock.baseline.yaml pnpm-lock.yaml` |
| 包图 `vite` 解析边 | **4 条**，本切片**动 2 条**（bundler 直接依赖、plugin-react peer 上下文 → **7.3.7**）；`vitest` 与 `@vitest/mocker` → **8.3.4** 未动；3 条 peer **范围**声明逐字节未改；3 条 importer 级直接 devDependency（web/admin/charts → catalog 8.3.4）未动 | `out/correction/02-vite-edge-inventory.md` |
| 全严重度 audit | **3 条** = **2 moderate**（`react-router` 6.30.6 ×2）+ **1 low**（`elliptic` 6.6.1），**high 0** | `out/audit-full.json`（实施侧留存；本次只读复核，未重跑 audit） |
| 治理门禁 | **仍 FAIL**；唯一未接受项 = **既有** stale `braces`（`GHSA-vfj7-8cjw-p6xm`，expires 2026-12-09，accepted_by caoronglin） | `out/governance-gate.json` |
| `apps/admin/dist` | 目录 mtime **2026-10-18 19:54**（**旧产物**，本轮未重建） | `ls -ld` |
| `apps/jbrowse/dist` | **不存在** | `ls -ld` |
| web 产物当前读取清单 | **143** 个文件（external **72** + internal **71**），sha256 已生成 | `out/correction/web-dist-current-read.sha256.txt` |

### 1. 本次订正改了哪些口径（原件一律保留，不覆写）

| # | 原口径（错） | 订正后 | 留存物 |
| --- | --- | --- | --- |
| A1 | "只有 3 条 `vite` 边""本切片只动了其中 1 条" | **4 条边、动了 2 条** | `out/correction/02-vite-edge-inventory.md` |
| A2 | "`@vitest/mocker` 在本锁图中没有独立的 vite 边" | **不成立**：它有 `optionalDependencies: vite: 8.3.4(...)`；旧试验的"4 条边"计数反而正确 | 同上 |
| A3 | 治理 doc "+316"、SUMMARY "+281" | **+316 是 diff 文件行数**；**+281 不对**；实测 **+287**（含 D1 **+108**）⇒ 本切片 **+179** | `out/correction/01-doc-diff-accounting.md` |
| A4 | 暗示存在"本切片单切片"的 doc diff | **无字节级前置副本 ⇒ 无法生成，且未伪造**；`final-governance-doc.diff` 标注为 **vs HEAD（不同基线）** | 同上 |
| A5 | `out/artefact-hashes.sha256.txt` 被当作产物哈希 | 实为**源文件**哈希；**未改名 / 未移动 / 未删除**；另加准确命名的 **source-only** 副本 `out/correction/source-only.post-correction.sha256.txt` | `out/correction/03-artifact-hashes-source-only.md` |
| A6 | "四项产物检查全过" | **web 侧**检查；admin 是 **2026-10-18** 旧产物、jbrowse **无 dist** ⇒ **不等于新三 app 构建全绿** | `out/correction/04-artifact-build-scope.md` |
| A7 | "`effective minimumReleaseAge=undefined` ⇒ release-age 策略未生效" | **错误推断**：`undefined` **不排除**默认值；**同一份试验日志**随后即打印 `✓ Lockfile passes supply-chain policies (1880 entries)` ⇒ 策略校验**在跑且通过**；**具体窗口仍 unknown**（不可读的 `.npmrc`） | `.cache/vite-targeted-trial/logs/02-trial-lockfile-only.log` |
| A8 | registry 不同源 ⇒ 审计结果被削弱/不可比 | 安装**镜像**与**官方审计 registry 用途不同**，**不足以否定审计**；正式切片的 audit 即以 `--registry https://registry.npmjs.org/` 执行 | `logs/10-audit.log`、`logs/11-audit-full.log` |
| A9 | 旧试验 "17.8 天满足 30 天 release-age" | 该**日历推算本身错误**（17.8 < 30），**记为订正**；正式切片**只采用 pnpm 自己的策略校验结果**，未豁免任何策略、未加 `minimumReleaseAgeExclude` | `logs/02-install-lockfile-only.log` |

### 2. 未关闭的欠账（本次未动，原样保留）

1. **治理 `pnpm-audit` gate 仍 FAIL** —— 唯一未接受项是**既有的** stale `braces` 接受项。按仓库自有 `load_advisory_acceptances` / `evaluate_advisory_report` 的语义，**删除它属于"注销"**（清掉一条不再匹配任何 finding 的记录），**不是**新增一次风险许可；但它仍是**签署记录**，**注销 / 续签 / 改范围待签署人决定**，本次**未做任何处置**，`acceptance` **未改**。**〔2026-10-24 晚间订正〕** 该 stale `braces` 接受项**已按用户经确认工具的明确授权注销**（上游 GitHub/OSV 记 `GHSA-vfj7-8cjw-p6xm` `withdrawn_at = 2026-10-23T12:53:02Z`，标题已变为 "Withdrawn Advisory"）。**注销 ≠ 包已安全**：`braces@3.0.3` / `sprintf-js@1.1.3` **仍在锁内**，feed 不再报**不等于**安全；**接受项已归零 ⇒ 将来再报 high 将无接受项可匹配、门禁自动失败**。注销后**门禁仍 FAIL**，剩余唯一未接受项是**新出现的** `body-parser` high `GHSA-27r3-jxmh-p828`（`body-parser@1.20.8`，可修 `>=1.20.9`），**未**为其新增/续签任何接受项。
2. **vite 7.3.7 运行时未证** —— 双站构建走 Umi 的 **webpack** bundler（`[webpackbar] ℹ Compiling Webpack`），`@umijs/bundler-vite` 在本仓不被使用 ⇒ 构建只证明"锁变更未扰动已发布的双站产物管线"。
3. **未跑**：workspace 全量 Vitest / lint / typecheck、`scripts/verify-frontend-artifacts.sh` 全量、**admin 与 jbrowse 重建**、CI、E2E、PostgreSQL、迁移、服务。
4. **F1b 欠账（不得记作已解决）**：release 默认词表 vs facts 词表对齐；未知 assembly → 成功空制品；**3 项 DB 回归未跑**；`0049` 迁移往返仍 skip。**18 项无库测试**依旧是 **F1b 独立复核代理亲跑的 18 passed**（`.cache/f1b-review/02-test-export-assembly-scope-reviewer.log`）；本次**未重跑**，**不得**改记为他人亲跑或本次亲跑。
5. **前端**：用户只批准 nwafu 改 amd；**前端改 MiniMax 未获用户批准**；前端**双评审未完成**。**〔2026-10-24 晚间订正〕** 用户**已批准**前端改 MiniMax 的**双评审**，A/B **只读评审已启动**（不再是"未获批准"）；**双评审结论尚未回收** ⇒ 前端**仍未完成**、不能计入验收。
6. **全局欠账不变**：CI 账户计费、损坏 PG 禁止再操作、PG18 迁移、真实 broker/S3/浏览器端到端、全仓回归。

### 3. 本节的效力边界

本节是**记录与口径订正**，**不是**验收、**不是**合并批准。正式 vite 切片的独立复核结论是 **accept-with-gaps**：**该切片本身**可接受；**整体不可合并、未提交、未 push、未合并**，**依赖目标未完成**，不得据此宣称工程完成。

## 2026-10-24 记录补齐：F1b（assembly 长度上限 + 422 契约）与 D1（依赖安全批次）——两切片均 accept-with-gaps，整体仍不可合并

**本节只补工作记录。** 本轮（记录者）**未改代码/配置/依赖/数据库，未跑任何测试、未安装、未起服务、未做 Git 写、未连接任何数据库**。本轮实际动作仅为只读：`git rev-parse --abbrev-ref HEAD` / `git rev-parse HEAD` / `git status --porcelain` / `git reflog` / `git diff --stat`、目录 `ls`、以及读取既有日志与文档。

**执行者分级（全文严格遵守；不得把他人亲跑写成本人亲跑）**：

| 标记 | 含义 | 留存物 |
| --- | --- | --- |
| **【记录者本轮亲跑·只读】** | 本轮记录补齐会话亲自执行的只读命令 | 本文件 §0 表 |
| **【F1b 实施代理亲跑】** | F1b 实施子代理亲自执行 | `.cache/f1b/`（22 个日志） |
| **【F1b 独立复核代理亲跑】** | F1b 独立复核子代理亲自执行 | `.cache/f1b-review/`（7 个日志 + `openapi-fresh-reviewer.json`） |
| **【D1 实施代理亲跑】** | D1 实施子代理亲自执行 | `.cache/d1-implementation/`、`.cache/d1/`（OSV advisory JSON） |
| **【D1 独立复核代理亲跑/复算】** | D1 独立复核子代理亲自复算/复跑（严格只读） | 复核会话 `d7d1dc5a-a524-4c79-b0ca-39af378d1d6d` 的结论 |
| **【代理报告，无留存日志】** | 只有叙述、无可复核产物 | 见各节"不可复核"标注 |

### 0. 本轮亲自只读核实的锚点【记录者本轮亲跑·只读】

| 对象 | 本轮实测值 | 命令 |
| --- | --- | --- |
| 当前分支 | `fix/fullstack-stabilization-20261020` | `git rev-parse --abbrev-ref HEAD` |
| 当前 HEAD | `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（**未变**） | `git rev-parse HEAD` |
| 工作树 | **94 项** dirty = **67 已跟踪修改 + 27 未跟踪**；**全部保留、未提交、未 push、未合并** | `git status --porcelain` |
| 依赖三文件状态 | `M docs/ops/dependency-governance.md`、`M pnpm-lock.yaml`、`M pnpm-workspace.yaml` | `git status --porcelain <paths>` |
| 无新 Git 写 | `git reflog` 末条 = `01fc163a4 HEAD@{0}: commit: docs(plan): define incremental full-stack stabilization scope`；前一条是 `57e2bcdee` 的 checkout | `git reflog -3` |
| F1b 文件 diffstat | `apps/api/app/api/v1/variants.py` +200/-、`apps/api/app/schemas/variant.py` +80/-、`packages/api-client/openapi.json`、`packages/api-client/src/generated/openapi.d.ts` | `git diff --stat -- <4 paths>` |
| F1b 新增测试 | `?? apps/api/tests/test_export_assembly_scope.py`（未跟踪） | `git status --porcelain` |
| vite 定向试验目录 | 第一次核对（00:41-00:45）**不存在**；**00:46 起由 vite 试验代理建立并推进到 00:50** ⇒ 该试验**有中间产物但仍无正式应用结论**（详见本文件顶部同名节） | `ls` |
| 前端失败报告 | **仍无**：`.validation/` 最新为 2026-10-23 21:59 隐私日志；`.cache/` 最新为 00:50 的 `vite-targeted-trial/`（依赖试验，非前端产物）⇒ nwafu/amd 失败**无有效报告** | `ls -lat` |
| 本记录目录状态 | `docs/aegis/work/2026-10-20-fullstack-stabilization/` 整体为**未跟踪**目录（`??`），本节写入不改变任何已跟踪文件 | `git status --porcelain <dir>` |

**dirty 增量归因（90 → 94）**：+3 已跟踪 = `pnpm-workspace.yaml`、`pnpm-lock.yaml`、`docs/ops/dependency-governance.md`（D1）；+1 未跟踪 = `apps/api/tests/test_export_assembly_scope.py`（F1b）。`apps/api/tests/test_variant_exports.py` 与 `packages/api-client/openapi.json` / `src/generated/openapi.d.ts` 在 F1b 之前**已**是 dirty/未跟踪状态，不是本轮新增。**本轮无任何 Git 写**。

---

## 2026-10-24 F1b：导出 assembly 长度上限（≤64）与 422 契约补齐（独立复核 accept-with-gaps；整体仍不可合并）

**F1b 做了什么（据实施与复核两侧一致的记录）**：

- `apps/api/app/api/v1/variants.py`：`_export_assembly_scope()` 对**解析后的有效 assembly**（显式值优先、否则 release 作用域、两者皆无则 422 拒绝）做 **≤ `MAX_ASSEMBLY_KEY_LENGTH`** 校验，超长抛域 `ValidationError` → **干净 422**；**不截断、不做映射猜测**，显式与 release 默认两条路径都覆盖。helper docstring 纠正为「TSV/CSV/JSON 逐行带 assembly，VCF 只在 header、BED 无自由 metadata 字段」。路由新增**路由级** `responses={422: ValidationErrorResponse}`，描述写明两类拒绝（请求体 schema 校验失败 / 无法绑定唯一 assembly）。
- `apps/api/app/schemas/variant.py`：新增 `MAX_ASSEMBLY_KEY_LENGTH = 64`（对齐 `variant_exports.assembly_key` 的 `String(64)`，**未改列宽、未改迁移**）；`VariantExportFilters.assembly` 的**可见描述**重写为「显式优先 → 缺省用 release 作用域 → 无 scope 拒绝 → 单装配体 → **只校验长度、不校验存在性**」。
- 新增 `apps/api/tests/test_export_assembly_scope.py`：**18 项纯无库单元测试**，import 并**实际调用生产 helper**（不复制实现），覆盖 63/64/65/200 长度、空白、显式/默认、皆空拒绝、不截断、错误不回显值。
- `apps/api/tests/test_variant_exports.py`：+3 项 **DB 回归**（64 接受并入库 / 65 显式 → 422 且 `error.code=validation_error` 且无记录无事件 / release 默认超长 → 422）——**本机未跑**。
- `packages/api-client/openapi.json` + `packages/api-client/src/generated/openapi.d.ts`：用**既有官方命令** `generate:api-client` 重生；`error-codes.json` 字节未变。

### A. F1b 实施代理亲跑的留存证据【F1b 实施代理亲跑】

| 结论 | 留存物 | 要点 |
| --- | --- | --- |
| 18 项无库测试通过（多次） | `.cache/f1b/06-test-export-assembly-scope.log`、`.cache/f1b/07-test-export-assembly-scope-blackhole-db.log`、`.cache/f1b/19-test-export-assembly-scope-final.log`、`.cache/f1b/20-ruff-and-tests-final.log` | `collected 18 items` → `18 passed, 1 warning in 0.24s/0.25s`，`pytest_exit=0`；`20-` 号同时含 `ruff_exit=0`（All checks passed）与 `diff_check_exit=0` |
| **OpenAPI 导出无 DB 连接（已证）** | `.cache/f1b/02-openapi-export-blackhole-proof.log` | 黑洞 DB URL 下导出结果与默认**完全一致** ⇒ 导出链不连库 |
| 静态 OpenAPI delta | `.cache/f1b/11-openapi-diff-before-after.log` | 见下方 §C 的 4 叶子结论（复核侧独立复现） |
| 生成链与客户端 | `.cache/f1b/14-generate-api-client.log`、`15-client-artifacts-after.log`、`16-generated-types-diff.log`、`17-api-client-typecheck.log`、`18-check-contract-after.log` | `generate:api-client` exit 0；生成类型 diff 仅 JSDoc + 422 `$ref`；api-client typecheck exit 0；`check:contract` "in sync" + route visibility PASS exit 0（对照 `.cache/f1b/03-check-contract-before.log` 为前态） |
| 错误码目录现状 | `.cache/f1b/21-error-code-catalog.log` | `validation_error -> ''`、`not_found -> ''`、`forbidden -> ''`，共 12 码**描述全为空串**（**超范围，只记录**） |
| 实施末尾工作树 | `.cache/f1b/22-final-openapi-and-status.log` | `SNAPSHOT_IN_SYNC=yes`、`export_exit=0`；`git status` = **91** 项（含 F1b 新增的 2 个未跟踪测试文件） |

### B. F1b 独立复核代理亲跑的留存证据【F1b 独立复核代理亲跑】

复核范围自述：**只读 + 窄无库测试**；不连 PG、不跑 DB 测试、不安装、不 git 写、不起服务、不改任何仓库源文件。清单见 `.cache/f1b-review/07-review-summary.log`。

| # | 命令 | 实测结果 | 退出码 | 留存物 |
| --- | --- | --- | --- | --- |
| 1 | `(cd apps/api) ruff check app/api/v1/variants.py app/schemas/variant.py tests/test_export_assembly_scope.py tests/test_variant_exports.py` | `All checks passed!` | **0** | `01-ruff-f1b-files.log` |
| 2 | `(cd apps/api) pytest tests/test_export_assembly_scope.py -p no:cacheprovider`（`SOYMUTDB_TEST_DATABASE_URL` unset；`SOYMUTDB_DATABASE_URL` = 黑洞 `postgresql+asyncpg://blackhole:blackhole@127.0.0.1:1/blackhole`；`DOCKER_HOST=unix:///nonexistent/docker.sock`）——**唯一获准的一次单元测试运行** | `collected 18 items` → `18 passed, 1 warning in 0.24s` | **0** | `02-test-export-assembly-scope-reviewer.log` |
| 3 | `bash packages/api-client/scripts/check-contract.sh`（导出到临时目录重生成 TS 类型并与已提交 `src/generated/openapi.d.ts` 逐字节比对，再查手写 route visibility；**不写入仓库**） | `"OK: client schema in sync with backend OpenAPI."` + visibility `"status": "PASS"` | **0** | `03-check-contract-reviewer.log` |
| 4 | 进程内（无 DB、无服务）两种真实 422 handler 输出对照**已声明**的 `ValidationErrorResponse` | 域 `ValidationError` → 422 体 `{error{code,message,details}, request_id, status_code}`，**无 `errors` 键**；请求体 schema 失败 → 422 体 `{error{...}, errors[{field,message,type}], request_id, status_code}`；**两者都符合已声明 schema** | **0** | `04-422-envelope-conformance.log` |
| 5 | 已提交 `packages/api-client/openapi.json` vs 当前源码新鲜导出 | `SNAPSHOT_IN_SYNC=yes` | 导出 **0** | `05-openapi-snapshot-sync.log` |
| 6 | F1b 的 OpenAPI 结构增量（前态快照 vs 当前源码导出） | **恰好 4 个叶子**：① `VariantExportFilters.properties.assembly.description` ② `/api/v1/variants/export` post `.description` ③ `.../responses/422` 的 `$ref`：`HTTPValidationError → ValidationErrorResponse` ④ `.../responses/422` 描述；**无 component 增删**，声明 422 的 operation 数**不变（237）** | — | `06-openapi-f1b-structural-delta.log` |

**独立复核裁决**：`accept-with-gaps（F1b slice only）`；"Whole goal: still not mergeable"。
**独立复核明确列为"未由 F1b 解决"的项**：release 默认词表 vs facts 词表；未知 assembly → 成功空制品；3 项新增 DB 回归未跑；`0049` 迁移往返仍 skip。

### C. 文件范围偏差（如实记录，不淡化）【本轮亲自只读核实 diffstat】

- Lead 原授权只明确允许重生成 `packages/api-client/openapi.json`，且要求**不覆盖其它客户端文件**；实施代理**额外**重生了 `packages/api-client/src/generated/openapi.d.ts`（同一条既有官方生成链 `generate:api-client` 的产物）。
- **独立复核的独立判断**：这是同一条既有生成链的**不可避免同步生成**，生成类型 diff **仅** JSDoc 与该 422 `$ref` 变化，`error-codes.json` 字节未变 ⇒ **必要同步、无破坏**。
- 因此本项**记为文件范围偏差**，但**不构成越界或数据损坏**。本轮记录者另行只读核对 `git diff --stat` 确认该 `.d.ts` 变更在预期范围内（见 §0 表）。

### D. F1b 仍未关闭（不得记作已解决）

1. **release 默认词表 vs facts 词表未对齐** ⇒ 仍可能「状态 succeeded 但制品为空」；推进需要**健康 PG** 证据。
2. **未知 / 拼错 assembly 仍走成功路径产出空制品**（只校验长度，**不校验存在性**）——该事实已如实写进契约描述，但**缺陷本身未修**。
3. **3 项新增 DB 回归未跑**（`apps/api/tests/test_variant_exports.py`）。
4. `0049` 迁移往返测试**仍 skip**（`the test database server refused to create a scratch database`）；手工往返不替代迁移门禁。
5. 本机 PG 16.15 ≠ CI PG 18；PG 18 迁移与端到端未做。
6. **全局 422 形状不一致**（其余 236 个 operation 仍声明 `HTTPValidationError`；`x-error-codes` 12 码描述全空串）——**超范围只记录**，修它要改 `apps/api/app/main.py` 与 `core/exceptions.py`。
7. 真实 broker / S3 / 浏览器 / 双站制品闭环仍无证据。

### E. F1b 验收判定（Lead）

**F1b 单切片可接受**；**整体仍不可合并、不可宣称完成**。未提交、未 push、未合并。

---

## 2026-10-24 D1：依赖安全批次 follow-redirects 1.16.1 + hono 4.13.11（独立复核 accept-with-gaps；治理门禁仍 FAIL）

### A. D1 的写范围（唯一三文件）【D1 独立复核代理亲跑/复算】

| 文件 | 变更 | 复核侧的独立判定依据 |
| --- | --- | --- |
| `pnpm-workspace.yaml` | 唯一 hunk `@@ -54,0 +55,11 @@ overrides:`（+11/-0），新增 `follow-redirects: 1.16.1`、`hono: 4.13.11` + 各自 GHSA 与可达性说明注释 | 逐 hunk 复核；`allowBuilds`(workspace.yaml:90)、`minimumReleaseAgeExclude`(:101) **未触及** |
| `pnpm-lock.yaml` | 19 insertions / 17 deletions（36 行） | `--frozen-lockfile` 报 "Lockfile is up to date" ⇒ **非手改**；基线副本与 HEAD blob `git hash-object` 全等 |
| `docs/ops/dependency-governance.md` | **+112 行** | 实施者 `13-final-scope-check.log` 当时记 108 行，该文件其后 21 秒又被编辑 → 最终 112（父汇报与 `14-final-receipt.log` 用 112，口径正确） |

其余 64 个已跟踪脏文件 + 27 个未跟踪文件属 2026-10-20 fullstack-stabilization 既有工作，**不是 D1 引入**。**复核未用 mtime 证明范围**（用 `git diff --name-only HEAD`=67、`git status --porcelain`=94、基线副本 hash 比对）。`git reflog` 末条停在 2026-10-20 ⇒ **D1 无 Git 写**。根 `package.json` **UNCHANGED**；`.npmrc` 是 tracked 且不在 diff 列表；仓库根**无 `.env`**。

### B. 计数口径订正（原日志不改）

- 实施者日志 `.cache/d1-implementation/05-lock-graph-compare.log` 抬头写 "baseline packages: 1895 / new packages: 1895"、"baseline snapshots: 1901 / new snapshots: 1901"。
- **这是把 pnpm 多文档 YAML 的条目相加**得到的，**口径不准确**。
- **独立有效锁图 = 1880 packages / 1886 snapshots / 14 importers**（importers 逐字节未变）；**D1 独立复核代理自行解析多文档 YAML 复算**得到该口径，并完全复现 05 号日志的实质内容（仅计数抬头不同）。pnpm 自身每次供应链策略检查都打印 **"1880 entries"**，与该口径一致。
- **处理方式：只在本记录订正口径，不修改、不覆盖原日志。**

### C. 锁图 delta（实质内容，两侧一致）

- package 键新增：`follow-redirects@1.16.1`、`hono@4.13.11`；移除：`follow-redirects@1.16.0`、`hono@4.13.9`。
- snapshot 键新增 4 个、移除 4 个（`@hono/node-server@1.19.17(hono@4.13.11)`、`@hono/node-ws@1.3.1(...)(hono@4.13.11)`、`follow-redirects@1.16.1(debug@4.4.3(supports-color@10.2.2))`、`hono@4.13.11`）。
- **peer 快照变化仅两处**：`@hono/node-server` 的 `hono ^4 → 4.13.11`、`@hono/node-ws` 的 `hono ^4.6.0 → 4.13.11`。
- **解析版本集合变化仅两处**：`follow-redirects 1.16.0 → 1.16.1`、`hono 4.13.9 → 4.13.11` —— 同主版本 patch，**无新增主版本**。

### D. 门禁与审计结果

**【D1 实施代理亲跑】留存于 `.cache/d1-implementation/`**：

| 命令 | 结果 | 退出码 | 留存物 |
| --- | --- | --- | --- |
| `pnpm install --lockfile-only` | "✓ Lockfile passes supply-chain policies (verified 2d ago)"、Scope: all **14** workspace projects、19 个 deprecated subdep WARN、peer issues WARN | **0** | `03-install-lockfile-only.log` |
| `pnpm install --frozen-lockfile --ignore-scripts` | "✓ Lockfile passes supply-chain policies (**1880 entries**)"、"Lockfile is up to date"、`Packages: +6 -4` | **0** | `06-frozen-install.log` |
| `pnpm dedupe --check` | 策略检查 1880 entries 通过、19 deprecated WARN、peer WARN | **0** | `09-dedupe-check.log` |
| `pnpm audit --registry https://registry.npmjs.org/ --json --audit-level high` | stderr 为空 | **1**（**如实保留**） | `10-audit.log` |
| `pnpm --filter @soymutdb/api-client typecheck` | `tsc --noEmit` | **0** | `11-api-client-typecheck.log` |
| api-client 契约检查 | route visibility `"status": "PASS"` | **0** | `12-api-client-contract.log` |
| 最终回执 | frozen exit 0、dedupe exit 0、audit exit 1（1 条 high = vite `GHSA-587h-7wmj-h5pm`）、resolved `follow-redirects@1.16.1` + `hono@4.13.11` | — | `14-final-receipt.log` |

**审计对比**（`10d-audit-compare.log`、`10b-audit-after-summary.log`；并经 **【D1 独立复核代理亲跑/复算】** 用 HEAD 锁的**字节级副本**复跑确认同 registry、同包集，两份 JSON 的 metadata 完全一致：totalDependencies 1895 / deps 1559 / dev 155 / optional 198 —— **注意 `totalDependencies` 是依赖统计口径，与锁图 packages 条数（1880）不是同一个量，勿混用**）：

| | BASELINE 锁（fr 1.16.0 / hono 4.13.9） | AFTER 锁（fr 1.16.1 / hono 4.13.11） |
| --- | --- | --- |
| advisories | **11** | **8** |
| severity | info 0 / low 2 / moderate 6 / **high 3** / critical 0 | info 0 / low 2 / moderate 5 / **high 1** / critical 0 |
| **新增** | — | **0 条** |
| 被 D1 修掉 | — | `hono` `GHSA-5r4p-p66f-jhc7`、`follow-redirects` `GHSA-8r9p-f939-6h3c`、`follow-redirects` `GHSA-q3jh-wrc6-jgq8` |

**残留 8 条**：`vite` 7.3.6 **×5**（1 **high** `GHSA-587h-7wmj-h5pm`、3 moderate、1 low；路径均落在 `@umijs/bundler-vite` 与 `@vitejs/plugin-react` 之下）、`react-router` 6.30.6 **×2**（moderate `GHSA-wrjc-x8rr-h8h6`、`GHSA-337j-9hxr-rhxg`）、`elliptic` 6.6.1 **×1**（low `GHSA-848j-6mx2-7j84`）。

### E. 治理门禁仍 FAIL（不可记作通过）【D1 独立复核代理亲跑/复算】

独立复核**跑了仓库自带的 `evaluate_advisory_report`**：

| | gate 判定 |
| --- | --- |
| BASELINE | **FAIL 4 条** |
| AFTER | **仍 FAIL 2 条**：`vite` 的 high **未接受** + **同一条既有的 `braces` stale 接受项** |

⇒ D1 把「未接受高危」由 3 降到 1，但**门禁仍是红的**；`braces` stale 是**批次前既有**、**非 D1 引入**；8 条残留里**只有 1 条进入门禁**（判定只看 high/critical）。**不可把 `pnpm-audit` 治理门禁记作通过。**

### F. 过程问题：`ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK` 的定性【D1 独立复核代理亲跑/复算】

- 真实失败原文（取自实施者 transcript）：`ERR_PNPM_STORE_DIR_OPEN_OPERATION_LOCK ... Read-only file system (os error 30)` ⇒ **内核 EROFS**。
- 根因由复核侧**读 `/proc/mounts` 独立确认**：`tmpfs /run/user/1001 tmpfs ro,...` ⇒ **主机只读挂载**，**不是 sandbox policy denial**。
- 实施者 transcript 中 `[sandbox: file access denied under ... mode]` 出现 **0 次**、`escalation available` 出现 **0 次** ⇒ **不存在「策略拒绝后换路径重试」的违规**。
- 改用工作区内 `.ph/run` 属**运行时目录调整**（该目录早于本批次 3 天即存在；LOCAL-RUN-ENV 已把 `PNPM_HOME=$PWD/.ph` 定为标准配置）。**复核未以「已有成功方式」自动免责**，而是比对失败原文 + 挂载表得出结论。
- **保留意见（如实记录）**：实施报告里 "the sandbox exposes /run/user/1001 read-only" 的措辞**不准确**（是主机挂载，非 DSH 策略）。
- **`XDG_RUNTIME_DIR` 这一具体旋钮本仓 LOCAL-RUN-ENV 未记载 ⇒ 记为运行环境说明缺口；本切片不去改 LOCAL-RUN-ENV。**
- 秘密边界：枚举实施者全部 bash 调用，**0 条**触及 `.npmrc` / `.env`；无 PG 连接、无服务、无迁移。复核侧自己读 `.npmrc` 被 DSH 安全网拦截（`secret.basename.npmrc`），**未重试、未绕行**。

### G. 治理文档论断的源码级核实【D1 独立复核代理亲跑/复算】

`docs/ops/dependency-governance.md` 新增段落的论断经**源码级亲验属实**：`follow-redirects` 1.16.0→1.16.1 的实际 diff 只有两处（数组 header 归一化 + `escapeRegex` 转义 `[ ^ |`）；`hono` 4.13.11 有 `allowPercentInPath` 守卫而 4.13.9 无；`@hono/node-server/dist/serve-static.mjs:78` 仍 `tryDecodeURI(c.req.path)` 无守卫；`@utoo/pack` 声明 `@hono/node-server ^1.19.11`、`dev.js:265` 为 `app.get("/*", serveStatic({root: distRoot, rewriteRequestPath}))`。实施侧佐证见 `.cache/d1-implementation/07-installed-versions.log`、`08-node-server-residual.log`。

### H. D1 未关闭的 gap（独立复核列出，逐条带出）

- **G1** 治理 `pnpm-audit` 门禁**仍 FAIL**（vite high 未接受 + 批次前既有的 stale `braces` 接受项）⇒ 不可记作通过。
- **G2** `13-final-scope-check.log` 记 108 行，其后 21 秒该文件又被编辑、最终 112（父汇报与 14 号回执用 112，口径正确）。
- **G3** 05 号日志抬头 1895/1901 是多文档相加，**有效图是 1880/1886**（见 §B）。
- **G4** `07-installed-versions.log` 含一次 `MODULE_NOT_FOUND` 失败与空段（论断由 08 号日志与复核侧源码核对补齐）。
- **G5** 本地 `node_modules` 仍留**孤儿旧版目录**（`follow-redirects@1.16.0`、`hono@4.13.9` 等）：无 importer 指向、CI 不受影响，但遍历 `.pnpm` 的扫描器仍可见。
- **G6** api-client 合约检查跑在**脏树**上 ⇒ 回归信号非干净基线。
- **G7** **未跑全仓 lint / test / 双站构建 / CI ⇒ install/dedupe/audit 绿不等于仓库仍可构建**；欠账属后续切片。
- **UNKNOWN** `minimumReleaseAge` 窗口天数在 `.npmrc` 内，安全网不可读 ⇒ **具体值未知**。

### I. 未实施的最小下一步（仅讨论，**未实施**）

未决残余只剩 `vite@7.3.6`。**全局 vite override 不可用**：树内还有 `vitest@5.0.5` 使用的 `vite@8.3.4`（vitest peer `^6.4.0 || ^7.0.0 || ^8.0.0`），全局覆盖会造成 vite 8→7 的**新主版本降级**并重写 vitest / `@vitejs/plugin-react` 的 peer 声明 —— 实施者排除它是**正确的**。可讨论的定向形态是**父级选择器**（如 `"@umijs/bundler-vite>vite": "7.3.7"`），但必须在**独立分支试验锁**上先过三关：① vitest 仍用 vite 8.3.4 且 peer 声明未被改写；② `@vitejs/plugin-react` 的 **peer** 上下文确实落到 7.3.7（peer 边被 override 会改写锁中声明，**不能假定**）；③ 7.3.7 满足本仓 `minimumReleaseAge`（以 pnpm 策略检查为准）。任一不成立，则 vite high 只能走 `security/advisory-acceptances.json` 的**签署接受**（90 天上限 / 审批人 / 到期 / 可达性论证），属**另一次受审变更**，**不并入本批次**。`react-router` 与 `elliptic` 本批次**无可修项**。

### J. D1 验收判定（Lead）

**D1 切片本身正确、最小、证据自洽 ⇒ accept-with-gaps**；**但不得在 D1 上关闭整体依赖目标**。治理门禁仍红、vite high 未关闭、全仓回归未跑。置信 **B**。

---

## 2026-10-24 vite 定向试验：**进行中，尚未获正式应用结论**（不得写成"已升级 vite"）

**时序说明（重要）**：本记录者第一次只读核对（00:41-00:45）时 `.cache/vite-targeted-trial/` **尚不存在**（`ls` → `No such file or directory`）；该试验于 **00:46 建立**、推进到 **00:50**。以下是**当时进行中的中间状态**，**不是结论**，也**不是本轮记录者跑的**。

**【vite 试验代理亲跑】** —— 留存物均在 `.cache/vite-targeted-trial/`：

| 项 | 实测值 | 留存物 |
| --- | --- | --- |
| 隔离结构 | `baseline / control / trial` 三份工作区副本；脚本自述**只跑 `pnpm install --lockfile-only --ignore-scripts`**——不安装、不构建、不起服务、不碰数据库、不放宽任何供应链旋钮 | `scripts/10-run.sh`、`scripts/00-setup.sh`、`scripts/20-apply-override.py` |
| 试验 override | `trial/pnpm-workspace.yaml` **只加一条**父级选择器 `"@umijs/bundler-vite>vite": 7.3.7`，注释写明 "ISOLATED TRIAL ONLY (not the formal repository config)"；**仓库正式 workspace 文件未被该试验改动** | `out/trial-workspace-config.diff` |
| 对照有效性 | `control-vs-official.lock.diff` **0 行** ⇒ 对照组**逐字节复现**正式锁图 | `out/control-vs-official.lock.diff` |
| 试验锁图增量 | `trial-vs-control.lock.diff` **65 行** ⇒ 只动 `vite@7.3.6 → vite@7.3.7` 与随动的 `@vitejs/plugin-react` peer 上下文；packages 键增 `vite@7.3.7` / 删 `vite@7.3.6` | `out/trial-vs-control.lock.diff` |
| 两侧 lockfile-only | control exit 0、trial exit 0；两侧均 "✓ Lockfile passes supply-chain policies (**1880 entries**)" | `logs/01-control-lockfile-only.log`、`logs/02-trial-lockfile-only.log` |
| **验收断言** | **8/8 PASS**（`ACCEPTANCE: 8/8 checks passed`）：A1 vite 版本集 7.3.6→7.3.7 且 **8.3.4 保留**；A2 vitest 5.0.5 的 vite 边仍解析到 **8.3.4**、vitest snapshot 键完全相同；A3 `vitest@5.0.5` 的 `peerDependencies` 逐字节未变（`vite: "^6.4.0 \|\| ^7.0.0 \|\| ^8.0.0"`）；A4 `@vitejs/plugin-react@5.2.0` peer **范围**逐字节未变（`vite: "^4.2.0 \|\| ^5.0.0 \|\| ^6.0.0 \|\| ^7.0.0 \|\| ^8.0.0"`）；A5 除 vite 外无任何包改变解析版本集；A6 **14 个 importer 块逐字节相同**；A7 锁 settings/catalogs 逐字节相同；A8 overrides 增量**恰好一条**父>子选择器、无删改 | `out/acceptance-checks.json`、`logs/04-acceptance-checks.log` |
| 治理门禁评估 | **control `passed=false`**：vite high `GHSA-587h-7wmj-h5pm` 未接受 **+** `braces` stale 接受项；**trial `passed=false`**：**只剩** `braces` stale 接受项（vite high 在该评估中不再出现，`reported_advisories` 为空） | `out/governance-gate-evaluation.json`、`logs/03-governance-gate-eval.log` |
| audit 视图 | control 报 1 条 high（vite，路径均在 `@umijs/bundler-vite` / `@vitejs/plugin-react` 之下）；trial 报 0 条；两侧 `metadata.totalDependencies` 均为 **1895**（deps 1559 / dev 155 / optional 198） | `out/control-audit-gate.json`、`out/trial-audit-gate.json` |

**必须随结论一起带出的限定（本记录者只读核对所见，非试验代理自述）**：

1. 试验的 registry 是 **`https://registry.npmmirror.com/`**（见 `logs/01-`、`logs/02-` 的 `### registry=` 行），D1 官方审计用 `https://registry.npmjs.org/`。**〔2026-10-24 订正〕** 二者**用途不同**：镜像用于依赖**解析/安装**，官方 registry 用于**漏洞审计**；registry 不同源**不足以否定审计结果**，"两次审计的 advisory 数据源不可直接互比"这句作为**否定性理由**属口径错误。真正成立的限定是**更窄**的一条：试验的 audit 视图本身被脚本按范围收敛（见第 4 条），因此**只能**用 trial/control 的**相对差**来读，不能把 trial 的 0 条当作"残余全消"。
2. 试验日志打印 **`### effective minimumReleaseAge=undefined`**。**〔2026-10-24 订正〕原表述"⇒ release-age 策略在该隔离上下文未生效"是**错误推断**：`undefined` 只说明**该次 `pnpm config get` 没有报告这个键**，**不排除**存在默认值，也不排除策略实际在跑——**同一份日志**紧接着就打印了 `✓ Lockfile passes supply-chain policies (1880 entries in 13.4s)`，说明 pnpm 的供应链策略校验**在跑且通过**。**〔订正〕具体窗口天数仍为 UNKNOWN**（本仓 `minimumReleaseAge` 在不可读的 `.npmrc` 内，与 D1 独立复核的 UNKNOWN 项一致）；**不得**臆测天数。§I 三关之③「7.3.7 满足本仓 `minimumReleaseAge`」的正确表述是：**以 pnpm 自己的策略校验结果为准，而不是以 `pnpm config get` 的回显为准**——正式切片正是这样取的证。
3. 试验**只做 `--lockfile-only`** ⇒ **未安装、未构建、未跑测试** ⇒ 「vite 7.3.7 真能构建并通过回归」**未被证明**。
4. 试验的 audit 视图似乎被脚本按范围收敛（control 的 `advisories` 只有 1 条，而其 `metadata.vulnerabilities` 合计为 8；trial 的 `advisories` 为空而 metadata 合计为 3）⇒ **不得**据此宣称 8 条残余全部消失。
5. 试验结束时**仍未产生最终裁决/应用**；仓库正式 `pnpm-workspace.yaml` / `pnpm-lock.yaml` 未被该试验改动。

**因此（Lead 判定口径，**当时**）**：**正式依赖图里的 vite 仍是 7.3.6，audit 的 vite high 仍未关闭，治理 `pnpm-audit` gate 仍 FAIL**（trial 评估里仍被 `braces` stale 接受项卡住）。该试验**尚未获正式应用结论**：落地仍需另行受审（正式 override 写入 + 独立分支试验锁三关复核 + `minimumReleaseAge` 生效验证 + 安装/构建/回归 + `braces` stale 接受项处置）。**禁止**把该试验写成"已升级 vite"或"vite 已修复"。

> **〔2026-10-24 已被取代〕** 上面这段在记录当时是准确的。此后**正式 vite 定向切片已落地**并经独立复核 **accept-with-gaps**：正式依赖图里的 vite 现为 **7.3.7**，vite high 已消除，全严重度 audit 残留 **3 条（2 moderate + 1 low）**，治理 `pnpm-audit` gate **仍 FAIL**（只剩既有的 stale `braces` 接受项）。**"vite 已升级"仍不能照抄试验记录**——须以正式切片的留存证据为准，见本文件顶部 **"2026-10-24 文档订正与 vite 正式切片落地"** 节。


## 2026-10-24 前端门禁：仍无有效报告，**前端工作未完成**

- nwafu **两项失败**、amd UIUX **两项失败**、amd 功能**一项失败** —— **仍无有效报告**：本轮只读核对 `.validation/`（最新为 2026-10-23 21:59 的隐私修复日志）与 `.cache/`（最新为 00:50 的 `vite-targeted-trial/`，属依赖试验而非前端产物），**未找到任何对应失败报告产物**。因此这些失败既不能算"已解决"，也不能算"已定位"。
- 用户已批准 **nwafu 改 amd**；**前端改 MiniMax 仍未获用户批准**；前端**双评审未完成**。前端状态 = **门禁未过、工作未完成**，不能计入验收。**〔2026-10-24 晚间订正〕** 用户**已批准**前端改 MiniMax 的**双评审**，A/B **只读评审已启动**；"未获批准"的等待状态已结束，**双评审结论尚未回收**，前端工作**仍未完成**。

## 2026-10-24 仍贯穿全局的未关闭欠账（未变）

1. **CI 计费未启动**：基线 Draft PR #26 的 **17 个 CI job 从未真正执行**（`gh pr checks 26` 全部 fail、`steps: []`，原因 "recent account payments have failed or your spending limit needs to be increased"，见 `15-baseline-verification.md` §5）。这是**账户级**问题，**GitHub 侧当前不能当门禁**，也不等于代码失败。
2. **损坏 PG 禁止再操作**：本机 PG 16.15 报 `could not open file "global/2964": No such file or directory`；已决定**不再连接、不再操作、不清理、不修复**，处置留给有授权的运维。本机 PG 16.15 ≠ CI PG 18。
3. **PG18 迁移 / 端到端（broker+S3+浏览器）/ 双站构建 / 浏览器 / 全仓回归** 全部欠账。
4. **未提交、未 push、未合并**；工作树 dirty 状态原样保留；基线 PR #26 仍是 Draft、未合并、head 仍是 `57e2bcdee`。

## 2026-10-23 F1 导出装配作用域：跨 assembly 混装路径关闭（记录补齐；不可合并、整体未完成）

本节**只补工作记录**。本轮**未跑任何测试、未连接任何数据库、未启停服务、未做任何 Git 写**（只读 `git rev-parse` / `git status` / `git branch --contains` / `git diff` 与一次只读 `gh pr view`）。下列结论分三类标注执行者：**我本轮亲自只读核实** / **实施代理执行、结果有留存日志** / **代理报告、无留存日志**。

### A. 本轮亲自只读核实的锚点

| 对象 | 本轮实测值 | 命令 |
| --- | --- | --- |
| 当前分支 | `fix/fullstack-stabilization-20261020` | `git rev-parse --abbrev-ref HEAD` |
| 当前 HEAD | `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（未变） | `git rev-parse HEAD` |
| 工作树 | 90 项 dirty = 64 已跟踪修改 + 26 未跟踪；**保留、未提交、未 push、未合并** | `git status --porcelain` |
| 草稿基线 PR #26 | `state=OPEN`、`isDraft=true`、`mergedAt=null`、`baseRefName=main`、`headRefOid=57e2bcdee3bab3435578997dba85cf26c3b985bc` | `gh pr view 26 --json …`（本轮亲自查询远端） |
| 基线 SHA 归属 | 是 `baseline/workspace-20261020` 与 `origin/baseline/workspace-20261020` 的头，且为当前 HEAD 的祖先 | `git branch --contains 57e2bcdee` |
| 本机 PG | 16.15 @ `127.0.0.1:55432`（**≠ CI 的 PG 18**） | `.ai-memory/LOCAL-RUN-ENV.md:292,346` |
| 记录目录状态 | `docs/aegis/work/2026-10-20-fullstack-stabilization/` 整体为**未跟踪**目录（`??`），本节写入不改变任何已跟踪文件 | `git status --porcelain docs/aegis/work/…` |

### B. F1 实现（我读真实代码核对，不只凭代理口述）

- `apps/api/app/api/v1/variants.py:116-141` 新增 `_export_assembly_scope(requested, release_context)`：显式给出的 assembly 优先，否则取已解析 release 自身的 `assembly` 作用域（`apps/api/app/services/release_context.py:37`）；两者都为空时抛 `ValidationError`（`apps/api/app/core/exceptions.py:21,62-64` → **422**）拒绝导出，绝不猜一个命名空间。
- `apps/api/app/api/v1/variants.py:276-293`：解析结果同时写入**交给 worker 的命令 filters**（`filters["assembly"]`）与**持久化 export 记录的 `assembly_key`**（`apps/api/app/services/variant_export_service.py` 的 `create_record`），记录与 outbox 事件仍在同一事务。
- `apps/worker/src/soymutdb_worker/tasks/export.py:106,124-133`：`build_export_query` 仅当 filters 含 `assembly` 时追加 `v.assembly_key = :assembly` 条件。**关闭点在此**：此前不写 assembly 时 worker 的 SQL 不带命名空间约束，一条制品可能同时含 v4 与 v5。
- F1 落在 3 个文件：`apps/api/app/api/v1/variants.py`、`apps/api/tests/test_variant_exports.py`（4 项回归：release 默认作用域 `:468`、空串视为未指定 `:492`、显式 assembly 优先 `:508`、两者皆无则拒绝 `:527`）、`apps/api/tests/test_release_bound_queries.py`（桩 DB 记录 `added`，断言命令 filters 含 `assembly`、记录 `assembly_key` 与之同值、记录与事件同事务）。
- **归属证据的边界**：`mtime` 与 `find -newermt "2026-10-23 22:00"` 显示 22:00 后仅这 3 个源文件被修改，**只作佐证**；`git diff` 的范围本身**不足以独自证明没有漏收**，二者都不能当作归属完整性的证明。

### C. 证据来源分级（关键：不要把代理报告当成本人实测）

| 结论 | 执行者 | 留存物 | 可复核性 |
| --- | --- | --- | --- |
| API **2593 passed / 4 skipped**、exit 0 | **实施代理**（非我亲跑） | `.cache/f1-api-suite-final.log`（17.7 KB，mtime 23:32） | 可读日志复核；4 skip = 3 个历史 ClickHouse driver skip + `tests/test_variant_exports_migration.py:191`（临时库创建失败） |
| API 首次全量 **2588 passed / 9 skipped**、exit 0 | 实施代理 | `.cache/f1-api-suite.log` | 多出的 5 skip = `SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL is required`（`test_variant_public_visibility_postgres.py` 4 项 + `test_native_variant_repository.py` 1 项），第二次带上该变量后才转 passed |
| **146 passed / 1 skip** | 代理报告 | **无留存日志** | 不可复核。`.cache/` 内 "146 passed" 命中全部来自 **2026-10-18** 的 admin 前端旧日志（`workspace-final-round1b.log` / `turbo-web-admin-3.log` / `admin-test.log`），与本切片无关 |
| **worker 29 项** | 代理报告 | **无留存日志** | 不可复核 |
| **pre/post 失败对照与 SQL 对照输出** | 代理报告 | **无留存输出** | `.cache/f1-export-scope-evidence.py` 只有脚本、没有输出日志 ⇒ **不冒称可复核** |
| 无库自证 helper 行为、OpenAPI 内存相等、ruff/diff check、collect 36 | **独立复核代理报告**（非我亲跑） | 无留存日志 | 不可复核，仅作为报告转述 |

`.cache/f1-openapi.json`（886 KB，23:28）是本轮**只读**核对契约用的 OpenAPI 导出快照。我从其中读到：`POST /api/v1/variants/export` 声明 202/422/500，其中 422 只写了 FastAPI 的 `HTTPValidationError` 形态（"Validation Error"），**没有**描述新增的"无法解析 assembly"域错误信封。

### D. 验收判定（Lead）

- 独立复核 `ca386191`：**accept-with-gaps**。
- **Lead 判定：仅关闭了跨 assembly 混装这一条路径**。因此 F1 **不可合并**，**整体不完成**，F1 不得被表述为"导出链路已交付"。

### E. 未关闭的风险

1. **默认词表不匹配 → 空制品**：默认 `Release.assembly` 是 `String(128)` 自由文本（`apps/api/app/models/content.py:71`），而 facts 的 `assembly_key` 用的是 name/version 形态的词表（如 `v4`/`v5` 与 `Wm82.a4.v1` 之类）。两者不一致时 worker 的 `v.assembly_key = :assembly` 命中 0 行 ⇒ **状态 succeeded 但制品为空**。当前无任何用例覆盖"release 默认 assembly 与 facts 词表不匹配"。
2. **长度未限 → 500**：`variant_exports.assembly_key` 是 `String(64)`（`apps/api/app/models/variant_export.py:84`），而 `VariantExportFilters.assembly` **没有长度上限**（`apps/api/app/schemas/variant.py:98`，`VariantQueryFilters` 同源）。客户端传入 >64 字符的 assembly 会让 DB 写入失败 ⇒ 500（OpenAPI 已声明 500，但契约未说明触发条件）。
3. **未知 assembly 成功返回空制品**：拼错的 assembly 与上面同因，走成功路径，不 422、不 404。
4. **422 契约描述缺失**：新增拒绝走 SoyMutDB 错误信封（`error_code=validation_error`），OpenAPI 的 422 只声明 FastAPI 请求校验形态，客户端按 OpenAPI 生成的分支处理不了这一种 422。
5. **0049 迁移往返仍 skip**：`test_0049_round_trip_creates_and_removes_the_export_record` 因 `the test database server refused to create a scratch database` 被跳过；**手工往返不替代**迁移测试门禁。
6. **PG 16 ≠ CI PG 18**：本机绿只证明"在 PG 16 上绿"。
7. **CI 17 个 job 因计费未启动**：`15-baseline-verification.md` §5 记录 `gh pr checks 26` 全部 fail 且 `steps: []`，原因是 "recent account payments have failed or your spending limit needs to be increased"。这是账户级问题，**GitHub 侧当前不能当门禁**，也不等于代码失败。
8. **仍缺的真实链路证据**：完整 broker 投递、S3 下载、浏览器闭环、双站制品一律没有。

### F. 过程偏差（如实记录，不淡化）

- 实施代理**两次跑完整 API 套件**，超出限定范围（2588/9 skip → 2593/4 skip）。第二次是必要的：第一次有 5 项因缺 `SOYMUTDB_PG_MIGRATION_TEST_DATABASE_URL` 被 skip。
- 在**这台已损坏的 PG**（`could not open file "global/2964": No such file or directory`，见本文件顶部 2026-10-23 节）上创建过临时库，证据脚本执行过 `DELETE`（`DELETE FROM variant_facts` / `releases` / `assemblies`），`soymutdb_f1_scratch` **无法清理**。
- **决定：不再连接、不再操作该 PG，也不尝试清理或修复它。** 该实例的处置留给有授权的运维/用户；本记录不再把它当作可用测试设施。

### G. 前端门禁（无有效报告）

- nwafu **两项失败**、amd UIUX **两项失败**、amd 功能**一项失败** —— **均无有效报告**：本轮在 `.validation/`、`.cache/` 中未找到对应留存产物（`.validation/` 最新文件为 21:59 的隐私修复日志，`.cache/` 最新为 23:32 的 F1 日志）。因此这些失败既不能算"已解决"，也不能算"已定位"。
- 用户已批准 **nwafu 改 amd**；**前端改 MiniMax 尚未获批**；前端**双评审未完成**。前端状态 = 门禁未过。**〔2026-10-24 晚间订正〕** 用户**已批准**前端改 MiniMax 的**双评审**，A/B **只读评审已启动**；结论未回收，前端仍未完成。

### H. 依赖

依赖候选**未升级**（manifest/lock 本轮无 diff）。后续分批实施前**必须**补上**当前**安全公告与注册表证据；先前的 scratch 审计结论不代表正式依赖图已修复。安装仍需明确授权，不绕过 sandbox。**〔2026-10-24 订正：本节"未升级"仅对 2026-10-23 成立。依赖批次已于 2026-10-24 以 **D1** 形式交付（`follow-redirects` 1.16.1 + `hono` 4.13.11，workspace override + lock + 治理doc 三文件；audit 11→8、新增 0、但 exit=1 保留，治理 `pnpm-audit` gate **仍 FAIL 2 条**，vite high 未关闭）。详见本文件顶部 2026-10-24 D1 节。〕**

### I. 结论与下一步门禁

**本节不构成工程验收通过，也不构成完成声明。** 当前状态：`needs-verification`。

下一步门禁（顺序）：

1. **前端替代模型待用户确认**（未获批前不动前端模型路线）。**〔2026-10-24 更新：前端改 MiniMax 仍未获批；nwafu/amd 失败仍无有效报告 ⇒ 前端工作未完成。〕** **〔2026-10-24 晚间订正〕** 用户**已批准**前端改 MiniMax **双评审**，A/B **只读评审已启动**（不再是等待批准）；nwafu/amd 失败仍无有效报告 ⇒ 前端工作未完成。
2. **F1 收敛 + 独立复验**：assembly 词表（release 默认值与 facts 词表对齐）、输入长度上限（与 `String(64)` 一致）、422 契约描述补齐，之后**重新独立复验**。**〔2026-10-24 更新：**输入长度上限**与**422 契约描述**已由 **F1b** 完成并通过独立复核（accept-with-gaps）；**词表对齐仍未解**，且**未知 assembly 的空制品仍未处置**、3 项 DB 回归未跑。〕**
3. **依赖批次**：拿到当前公告/注册表证据后由主代理按既定边界实施；本轮未升级。**〔2026-10-24 更新：D1 已交付 fr 1.16.1 / hono 4.13.11，audit 11→8 新增 0 但 exit=1，**治理 gate 仍 FAIL**、vite high 未关闭 ⇒ 依赖目标**仍未完成**。〕**
4. **全线验收**：API/Worker/MCP 全量、JS 全套、双站制品、浏览器/权限负例、治理与依赖门禁、真实 broker + S3 下载闭环。

未提交、未 push、未合并；工作树 dirty 状态原样保留。

## 2026-10-23 再次核验：隐私修复保留；新增本机PG环境限制

用户再次要求“那就修复好问题”，核对当前branch/HEAD及完整helper，补丁仍在工作区；未改业务实现、未提交/合并/发布。重新实际执行相同6文件专项：**58 passed，2 warnings，4.31s**；随后完整API：**2589 passed，4 skipped，53 warnings，76.25s，exit0**。日志 `.validation/variant-privacy-targeted-20261023.log` / `.validation/variant-privacy-api-full-20261023.log`。新增5项隐私测试及native2项均passed，无隐私skip/xfail。Ruff、OpenAPI/client contract与diff-check重新exit0，依赖manifest/lock无改动。

与10-22的2590/3 skips不同：本次0049 round-trip迁移测试创建临时数据库失败而skip（另3个仍是历史CH driver skip）。**没有把这个额外skip当迁移验证通过。** 为调查环境只执行只读psql目录/连接查询，服务器返回 `ERROR: could not open file "global/2964": No such file or directory`，命令exit1。说明本机既有PG有系统文件异常，不能宣称环境健康或生产迁移通过；未擅自重启、重建、修补系统目录或强制删除任何数据库，也未绕过权限。这个新环境异常不是公共可见性谓词修复的回归结论，需要独立检查既有PG数据目录/备份后处理。

当前隐私修复已由本次真实PG+ASGI专项和完整API回归覆盖；10-22真实HTTP/Redis毒旧键复验保留为**历史实测**，10-23未重启该服务链路。TCP确认8010/8090/56389/59000/59010/59011都关闭，55432仍监听仅代表进程存在，不证明PG系统目录健康。此次不新增临时服务。置信B：业务缺陷已修复，数据库环境异常和全产品发布仍不在“已完成”声明内。

## 2026-10-22 匿名变异隐私修复：已修复并实证复验（限定本次切片）

### 结果与覆盖

- 新公共查询owner `apps/api/app/services/variant_visibility.py`：原生facts使用published release + release/name关联的公开、未删除、有public_id品系（空名称事实保留）；规范化VariantSummary使用真实FK且release一致。只加EXISTS，不改变分页行数/顺序或增加连接；不误用历史surrogate当主键。
- repository列表/count/region、detail及native类型/密度/dashboard/distinct聚合应用同一原生谓词；summary类型/impact/染色体统计应用等价FK规则。补齐相邻dashboard公开品系/表型、homepage品系/seed来源与mutagens计数的同类过滤。admin角色检查后的全量统计显式public_only=False，公共请求无此开关。
- dashboard/homepage/chromosome-density Redis参数加入 `variant_visibility=public-v2`；保留release上下文，跳过旧键而非清空共享Redis。不改变API形状/客户端类型/数据库迁移/依赖锁。

### 新鲜证据（均由主Agent实际运行）

1. `test_variant_public_visibility_postgres.py` 5项：隔离真实PG schema、真实0047 facts迁移及补充规范化表；公开/无品系正向，私有/已删除/无public_id/孤儿/跨release名称及FK/草稿/v4-v5/历史surrogate与主键相撞负向；分页/region/count/detail/聚合；真实PG+ASGI匿名404/422；最后一项使用**完整生产ORM schema**验证品系、表型、homepage与mutagens计数（仅不相关native聚合mock）。native repository/migration另2项通过，隐私场景**没有skip/xfail**。
2. 专项组合：`test_variant_public_visibility_postgres.py test_native_variant_repository.py test_variant_aggregate_perf.py test_cache.py test_homepage_stats_scope.py test_ablation_stats_release_scope.py` → **58 passed，2 warnings，exit0**，日志 `.validation/variant-privacy-targeted.log`。先前8个全量失败已调查：5项旧缓存键精确断言更新为public-v2，3项旧性能夹具将release7002事实关联到了release7001品系；修正数据归属并另补release7001无事实品系，保持原有2个关系品系计数/连接预算/无DISTINCT断言，未降低可见性要求或修改期望总量迎合泄漏。
3. 全量API：两条PG环境变量均指专用 `soymutdb_test_stabilization_20261020`；`python -m pytest apps/api/tests -q` → **2590 passed，3 skipped，53 warnings，84.00s，exit0**，日志 `.validation/variant-privacy-api-full-final.log`。3个skip为历史ClickHouse adapter/driver用例（模块importorskip + pool配置2项缺历史driver），不是本次PG隐私覆盖。环境为PG16，不冒充生产/PG18。
4. 修复后的真实uvicorn API8010 + Redis56389 + **此前完整迁移保留的chain部署库**，匿名真实TCP请求，无dependency override：v4逐页仅1001/1002且无额外页；v5仅1004；region仅1001/1002；公开detail200，私有1003/草稿1005/不存在记录404；私有public_id404、numeric internal locator422；类型与密度计数2。homepage/dashboard先写入旧键错误99999，再HTTP读取仍为公开事实3且新public-v2键存在、旧毒键未被碰触，实证缓存隔离。脚本exit0，8项断言组见 `.validation/variant-privacy-http.log` / `.validation/variant-privacy-http.json`。
5. 修改文件Ruff、git diff-check、`pnpm --filter @soymutdb/api-client check:contract` exit0；manifest/lock无diff。双站**复用未改动frontend的预构建demo制品重新扫描**（不是本轮重新构建）：`SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh`及额外私有/删除/无public_id/孤儿sentinel扫描exit0，日志 `.validation/variant-privacy-artifacts.log`。未将此扫描包装为生产双站E2E。
6. 两次默认模型独立只读审查：847ce66a核心patch、f1d53736相邻metadata补充均**无阻塞项**；其审查未亲自运行测试，不计测试通过或上线审批。MiniMax路由a510911b本次失败无结果（此前演练亦失败），未冒充MiniMax审查通过。第二次审查确认公开metadata调用仍绑定release、FK子查询关联正确、计数单round-trip不变、缓存参数新旧隔离。

### 交付边界与剩余事项

本次“修复匿名变异列表私有记录泄漏”及发现的同类动态计数缺口完成，置信B（目标+相关回归+真实HTTP实证，仍非全产品验收）。新helper两种存储表示共享API规则；Worker原导出表达式保留，由同样release/name规则与此前链路证据约束，未趁机跨包重构。前端无修改；本轮未再跑Chromium原生下载/完整Worker-MinIO链路，上一轮的该类证据不会被本轮HTTP证据替代。未验证生产volume、固定compose镜像、生产回填或所有external/internal授权矩阵；不自动取得上线/合并权限。

公开 `/stats/releases` / `/stats/discovery-trend` 仍返回已发布Release记录声明的variant_count等元信息，**不是本次过滤后的事实计数契约**；未把这些声明值证明为public-only事实统计，若要统一其数值语义需独立发布元信息契约审查，不能宣称所有统计面已完全一致。metadata新测试未直接填seed库存，seed SQL复用同一公开品系子查询；PG/ASGI、缓存和当前真实API覆盖已分别标注。

隔离演练API/Redis已停止并核对8010/56389端口关闭；既有PG55432/测试数据保留。Git no-commit（用户既定不提交/不合并范围）、branch/HEAD未变，task/repository仍dirty；不接管同任务其它dirty文件、不创建worktree。未删除生产或既有PG数据；整个稳定性goal仍未完成（正式依赖升级、完整发布制品等原剩余项不被本切片关闭）。

### 执行基线与计划（保留）

用户已明确授权修复部署发现的问题。TaskStartSnapshot：branch fix/fullstack-stabilization-20261020，HEAD 01fc163a4c6488f97fe44ecf8f587b145cf989aa；大量同任务dirty改动保留，variant_repository已有2行diff不覆盖；不创建分支、不提交或合并。Change Necessity：真实匿名请求返回is_public=false品系的1003，导出不返回，公共查询边界缺失。风险high（可见性）；ArchitectureReviewRequired=yes，复用PG权威关系，无新存储/API形状/迁移/依赖决策。

基线读集：AGENTS、database-core-contract、LOCAL-RUN-ENV、variant_repository/postgres_variant_service/variant_service、variants与stats/admin路由、worker导出query及native PG测试。TDD off，仍需复现与负向回归。

执行计划：1）原生facts统一公共SQL谓词（published release，未关联品系可见；有名称者必须按release/name关联公开/未删除/有public_id的品系，不能依赖历史surrogate主键）；列表/分页/region/count/detail与公开聚合复用。2）规范化VariantSummary统计按真实FK应用等价可见性，公共缓存加入新可见性版本，受鉴权admin全量统计显式保留。3）新增PG隐私fixture含私有/删除/无public_id/孤儿/草稿/跨release同名/其它assembly以及surrogate不等于FK，HTTP列表和404无存在性泄漏。4）先针对性回归再API完整回归/静态契约、真实HTTP演练及只读独立审查。5）清理临时服务、记录精确覆盖与缺口；不把这个修复当整个稳定性目标完成。

## 2026-10-22 部署演练：真实服务链路通过，发现匿名列表隐私阻塞项

用户后续“部署测试一下 / 继续”授权了本机隔离服务演练，不代表生产发布、对公网暴露或依赖升级提权授权。使用已有PG16 127.0.0.1:55432新建专用 `soymutdb_deploy_20261022` / `soymutdb_chain_20261022` 两库；均真实迁移至0049，未复用生产数据。

### 实际通过的范围

- 真实uvicorn API8010、Redis8.10.1端口56389、Celery Python3.15 export队列、真实MinIO `RELEASE.2025-09-07T16-13-09Z` 端口59010互通。MinIO为GitHub release下载到工作区scratch，**不同于compose固定的2024-12-18版本**，不是固定镜像验收。
- 先用独立scratch venv中的moto端口59000定位链路；随后切到真实MinIO，不能把moto结果包装成MinIO证据。项目manifest/lock未改变，测试工具安装仅在gitignored scratch；此前正式依赖批次拒绝仍有效。
- 真实HTTP链路：邮箱/密码登录200 → POST导出202 → API后台outbox dispatcher → Redis → Worker → PG状态succeeded（2 rows / 429 bytes TSV） → owner下载接口200 → 签名URL实际HTTP下载并比对内容。以真实MinIO完成；样本导出5dd8db5b-4c91-4836-886d-9f811155ff0b。匿名状态/下载401、不存在id404已在前面的本机HTTP检查观察到，**未测试第二账号越权**。
- 隔离fixture包含5行：公开1001、无品系1002、私有品系1003、其它组装1004、草稿release1005。实际导出只含1001/1002，私有品系名/其余3行不出现在产物。
- Chromium真实门户：external-local demo制品以 `http://127.0.0.1:8090/api/v1` 构建（相对origin被配置校验拒绝后改用绝对origin），既有preview代理真实API。最终 `node .validation/deploy-browser-export.mjs` **exit0、6个检查点通过**，日志 `.validation/deploy-browser-final.log`：渲染真实数据、真实登录、Bearer导出POST202、完成状态、签名下载接口200、gzip产物334bytes解压后2行且无排除行。最终export_id=3a2ac7c1-7a61-410b-a225-ea34fcf6ef46。
- 浏览器证据边界：点击真实页面下载按钮取得接口响应，然后用Playwright **APIRequestContext**下载并解压，不是已验证浏览器原生下载事件/磁盘落盘；未测退出登录中途的晚POST/晚下载响应。页面仍有meta frame-ancestors提示、匿名启动刷新401等console输出，不声称零控制台错误。

### 部署演练实际修复

`verify-native-export-chain.py` 的 `_find_or_create` 新建分支之前调用session.add(model(...))却返回旧的None，在全新数据库必然于读取Assembly.id崩溃。改为先赋obj再add/flush/return，保留命中已有行时更新defaults的路径。新增 `scripts/test_native_export_chain_seed.py` 覆盖创建/复用2项，**2 passed**；两文件Ruff与diff-check通过。真实迁移库上的失败→修复后ASGI/API-outbox/独立Worker链路通过也已实际观察（当时S3端点为moto）；随后真实HTTP/MinIO/Chromium链路均通过。

两次MiniMax只读复核均在完成前失败（53577ba3、361ccf6f），无结论，**不计独立审查通过**。未改动产品S3签名代码或对象键。

### 纠正演练中错误判断

- `/exports/exports/...` 是桶名exports + 桶内key前缀exports，API/Worker一致；实际读回成功，**不是重复拼接缺陷**。
- URL使用 `AWSAccessKeyId/Signature/Expires`（SigV2）而非 `X-Amz-Signature`；前序“没有签名/MinIO已不接受SigV2”的口头判断错误。真实MinIO2025实验中SigV2与SigV4均HTTP200，且完整产物链路成功。AWS/其它对象存储的兼容性未测，不因此改全局签名策略。
- 初始Worker调用方式错误、API/Worker库不一致、未配限流Redis、请求体误带release_key、邮箱表单校验、AntD选择器、仅内存token的判定、gzip文本解析等是演练配置/断言错误，不算产品修复。最后浏览器命令直接检查exit status，不以管道末端的0冒充脚本通过。

### 新确认：不可公开上线的隐私差异

**匿名GET `/api/v1/variants?assembly=chain-v4` 返回1001/1002/1003，HTTP200且没有Authorization。** 数据库JOIN实证1003属于 `mutant_lines.is_public=false` 的品系。见 `.validation/deploy-anonymous-visibility.json`。`VariantRepository._predicates` 当前仅按release/组装/过滤条件限制，无私有品系排除；导出与列表可见性出现不一致。尚未修复/审查列表、detail、计数及其它读面是否同类，**此项阻止对外上线**，不能把导出成功当完整隐私门禁通过。只使用人工测试数据，不涉及真实私有样本泄露。

### 保留与清理

preview脚本固定监听0.0.0.0，并非只监听loopback；浏览器完成后已请求停止，不保留带已知测试凭据的对外demo入口。moto已被真实MinIO替代并请求停止。其余本轮API/Worker/MinIO/Redis已停止；managed jobs回报killed，TCP逐项确认8010/8090/56389/59000/59010/59011均关闭，55432仍应答。已有PG16实例与两测试库保留，绝不停止/删改既有PG数据。本轮不是持久部署/生产cutover，不产生可公开发布的服务URL。完整镜像/Pages/JBrowse发布制品、正式依赖批次及上述新隐私问题仍未完成。

## Goal round 12：当前工作区最终可执行回归汇总（不是全线完成）

本轮未新增业务实现、安装、服务或Git写操作。下列脚本均实际完成exit0，缓存命中如实区分；工作区dirty状态保留，未提交/合并/发布。

| 门禁 | 本轮结果 | 原始日志/范围 |
| --- | --- | --- |
| API全量 | **2584 passed / 4 skipped**，78.13s | `.validation/round12-api-tests.log`，Python3.15/专用PG16 |
| Worker + jobs-py全量 | **773 passed / 33 skipped**，5.35s | `.validation/round12-worker-jobs-tests.log`，Worker666 + jobs-py107，包含实际0049迁移表与并发回归 |
| MCP全量 | **66 passed**，7.68s | `.validation/round12-mcp-tests.log`，清除本机不合法proxy/no_proxy变量，非修改产品网络策略 |
| 根JS test | **11/11 tasks**，其中**10 cached** | `.validation/round12-js-tests.log`；本轮web实际执行55 files/456 passed，其余重放Turbo缓存（含admin33/224、client31/198、JBrowse71等），不得称全部无缓存重跑 |
| 根lint | **12/12 tasks**，9 cached | `.validation/round12-lint.log`，`pnpm lint --concurrency=1` |
| 根typecheck | **13/13 tasks**，8 cached | `.validation/round12-typecheck.log`，`pnpm typecheck --concurrency=1` |
| Python Ruff | API生产app与修改过的export源/回归/共享错误模块通过 | 未声称全仓所有历史测试lint清零 |
| OpenAPI/client契约 | schema一致、route visibility **PASS** | 真实导出后临时重生成比对；SOYMUTDB_API_PYTHON指定现有api venv，未安装 |
| locale键 | **PASS** | `pnpm --filter @soymutdb/i18n-core run check:locale-keys` |
| 治理 | architecture、worker test package、web query keys、admin content architecture、worker task registry **25 tasks**通过 | 检查范围遵循各脚本，不等于所有pipeline治理脚本全跑 |
| 当前门户制品headers | **4 files OK**（require-dual） | 与round11的双站demo重建/真实host隔离结果配合；未重新构建JBrowse/Admin |
| 工作区边界 | diff-check通过；正式pnpm-workspace/lock无diff | 未带入scratch候选/构建产物/诊断空锁文件 |

重现环境：PATH前置opencode Node26；pnpm12.11.2，PNPM_HOME=$PWD/.ph，GOMAXPROCS=2/RAYON_NUM_THREADS=1/UV_THREADPOOL_SIZE=2；Python3.15各自venv，OPENBLAS_NUM_THREADS=1/OMP_NUM_THREADS=1；API数据库asyncpg、Worker数据库psycopg2均为本会话专用PG16测试库。后端按API→Worker/jobs→MCP串行执行，未借用生产库。

### 未覆盖与下一步（仍然是未完成项）

1. **真实browser + broker/S3导出闭环未验收**：组件/真实QueryClient回归不验证cookie、真实401/refresh、实际HTTP签名下载、Celery投递与对象写入。服务启动仍无授权；未伪造runtime通过。
2. **完整发布制品未验收**：门户demo双站已建并扫描，content snapshot与release manifest明确跳过；JBrowse完整build此前EAGAIN/errno11、Pages builder此前corepack EROFS尚无成功替代证据。没有image build/smoke、完整release bundle或生产cutover证明。
3. **兼容依赖迭代未落地**：用户批准最小安全批次，但窄化父依赖override后的原命令提权被拒，已停止并撤回配置/锁。先前scratch11→5公告不是正式图已修复；未运行frozen/dedupe/peer/安装后回归，仍不能称安全升级完成；不再重试/改环境绕过拒绝。
4. **剩余UX复核项**：状态GET出404/网络错误时目前停止轮询，尚需确认可恢复错误提示与导出id清理是否完善；不因会话隔离回归通过就当所有错误恢复已验收。
5. **接受的执行取舍**：重投发现>3600秒running即失败，即使原执行健康；无重投不自动超时。原进程可留下未发布对象，不声称有外部对象fencing。已由用户批准并经独立复核，不改写成exactly-once。

整体证据等级为**部分验收**：本地源代码/契约/数据库/组件与门户demo制品覆盖较充分，但业务真实链路、完整制品和依赖目标未达成。goal保持active，不调用complete；自动轮次结束不等于目标完成，也不按轮次耗尽虚构blocker。基线Draft PR #26是既有历史结果，本轮未查询远端或改PR。

## Goal round 11：真实 SessionProvider / QueryClient 整合证据

- 针对上次只读复核的证据缺口，新增 `export-session-integration.test.tsx`：不 mock SessionProvider、Session状态机或 React Query，使用真实 QueryClientProvider/QueryClient/useQuery/query key。模拟边界限于 API传输、auth事件/令牌接口、router和展示包装。
- 5 项渲染整合回归：真实provider signOut与auth失效事件均保持id=1、改变状态；旧缓存成功数据存在时，登出后下载按钮/进度/消息消失，旧key真实observer数量为0；focus切换和active invalidate不再发旧导出读取；在途状态响应晚到不恢复旧UI；真实provider登出后adoptSignIn推进id=2，旧POST晚回不能建立B账号导出；旧下载错误清理，晚签名链接不click。
- focused **5 passed**，门户 typecheck/lint 通过，均使用既有依赖。首次测试因仓库未装Chai的toBeDisabled扩展而3失败，仅将断言改为原生disabled属性检查，未改产品代码迎合测试。
- 明确承认缓存并非抹除：旧key数据仍保留到正常GC，但无observer且不再渲染。此处证明实际客户端库和provider的交互，不证明cookie/refresh网络服务端、真实浏览器计时器、后端授权或S3链路。该增量只新增测试，未变更运行时语义。
- 全量门户 **55 files/456 passed**（104.00s，`.validation/export-session-real-query-full.log`）；既有 `bash scripts/verify-site-variant-artifacts.sh` **exit0**（`.validation/round11-site-variant-artifacts.log`）：demo/offline模式实际重建external/internal各28个文档，CSP完成，internal noindex、无公共snapshot，external受保护标记/内站canonical域名隔离通过。构建后另跑 `check_artifact_headers.py --require-dual`（4 files）与制品隔离checker（额外加入api.internal.soymutdb.test、jbrowse.internal.soymutdb.test两个实际内部配置host）均exit0。未发生useLayoutEffect构建错误，但静态文档生成不等于浏览器渲染/水合；content snapshot未配置、release manifest因demo模式跳过，均不算通过项。header checker对未构建的其它app可退到source，不能据此声称JBrowse/Admin完整制品已重建。tracked public/config/scripts无构建引入差异，正式依赖配置/锁仍无diff。MiniMax只读测试证据复核55666395-d891-4cac-9859-f87233ed92e0返回无阻塞项，确认provider/QueryClient真实且mock整层测试未覆盖的证据已补充；其未执行测试。采纳精度建议：修正文件头mock范围；测试标题改为错误提示“隐藏”而非声称内部错误状态已清空；明确断言晚到状态实际落入旧缓存、旧key无observer、B的sessionId=2 key无数据。返修后focused5、typecheck/lint/diff-check再次通过（14:15本机时间）；之前55/456全套与制品构建在测试断言增强前执行，产品运行时代码未变化，不冒充重新全量运行。依赖拒绝仍保持停止，整体目标未完成。

## 2026-10-22：用户批准过期 running 安全失败，不接管重算

- 用户在明确取舍后选择“批准安全失败、不自动重算”：重投看到过期 running 不得仅凭时间推断原进程已死。已在原计划补充确认，不扩表、不改对象键、不加 retry 接口。该政策替代下方较早记录的 resume/CAS 续租方案。
- 实现：`VariantExportStore.begin_run` 保留活跃租约 skip；过期或 started_at=NULL 时，由 `_expire_run` 按 running + 观察时间戳（NULL安全比较）置 failed、公开固定错误、completed_at/updated_at；返回内部决策 expired。任务在 expired 时记录警告并 skipped，绝不进入 `_run_export`。删除原 `_renew_lease`/export resume 路径（其它任务原有 resume 不改）。用户通过新导出恢复。
- 回归先证明旧实现不符合批准政策：PG并发/过期 focused **3 failed / 1 passed**（旧实现返回 resume）。改后真实0049迁移表上的并发 pending、双过期/NULL失败竞争、过期后晚成功拒绝、原执行在 SELECT 和 expiry UPDATE 之间成功的竞态均通过；新增任务级断言 expired 决策不执行 `_run_export`。
- 新鲜回归：Worker + jobs-py **773 passed, 33 skipped**（Worker666 + jobs-py107），5.25s；API 导出/迁移 **18 passed**（7.08s，含真实迁移往返）；修改文件 Ruff 与 diff-check通过。使用原有venv/运行中的专用PG16，不安装依赖或启动新服务。
- 保证边界：此策略避免新 Worker 为同一过期记录启动第二次执行，且终态不被晚成功覆盖；不杀掉旧进程，也不为外部对象写入提供 fencing。原执行仍可能上传无发布记录的对象，按既有保留策略清理。**没有重投时不会仅到点就自动标失败**（未新增定时器/reconciler）。Celery跳过投递的成功返回不是导出成功，API只认PG记录。混部旧Worker升级期间仍需运维确保旧实现退出。
- MiniMax只读复核 `50e6e422-bdfd-43ec-a72b-55f185c7c6e8` 已返回 No blocker found：确认晚成功、双重投、SELECT后原执行先成功的竞态均受保护，失败不重放；复核未执行测试，不替代主代理真实PG证据。其强调固定3600秒且无heartbeat意味着健康的>1h导出若遇晚重复投递也会失败，属于用户已批准的安全失败取舍，不宣传为无损恢复。UI归属复核 `4fa0ecbf-c40c-4d20-942c-0e13885321de` 已返回所审范围内 No blocker found：确认scope变化、layout reset、卸载失效及四个异步续体检查。复核只读index140-238与测试80-166，未看测试mock框架和JSX渲染；主代理已知React Query整层被mock，因此结论限于组件意图/状态隔离，不把缓存/focus/refetch语义记成实测。UI依赖provider账号变化一定改变id或status；同账号restoring状态也会丢弃本地导出，是当前保守隔离行为。SSG/layout effect提示、downloadError清理显式断言及真实Provider/QueryClient/browser整合仍待验证，不凭该窄审查消除这些证据缺口。完整broker/S3/browser/制品及被拒依赖批次仍未交付；整体goal active。

## Goal round 10：Worker 认领回归绑定真实迁移 DDL

- 消除已知证据缺口：`test_export_claim_postgres.py` 不再调用 Worker 窄 Core 表的 create()；在随机、隔离 PostgreSQL schema 中，通过真实 Alembic Operations/MigrationContext 执行 `0049_variant_exports.py.upgrade()`。只为外键前置创建最小 `users(id UUID PRIMARY KEY)`；导出表自身的枚举、非空约束、FK、索引和默认值均来自迁移原文。测试后只清理自己创建的 schema。
- API 风格插入补齐 release_key/format 必填字段，依赖实际 compress/filters/时间戳服务端默认值。将源代码子串“列名存在”测试替换成实际表反射：验证 Worker 所有投影列存在、状态枚举四值、release_key/format 非空与 updated_at=now()；新增缺必填字段的真实 IntegrityError 负例与默认值断言。
- 既有 3 个 Barrier 同步并发认领、活跃/过期/NULL 租约、终态拒绝覆盖测试现全部在实际迁移表上跑。focused **14 passed**；全量 Worker + jobs-py **771 passed, 33 skipped**（Worker664 + jobs-py107），5.23s；Ruff 与 diff-check exit0。使用已有 Worker Python3.15 venv，PG16专用数据库与之前相同，不新增安装/服务。
- 把误导的测试名 `test_the_stored_key_is_the_key_the_api_signs` 改为 `test_store_roundtrips_shared_artifact_key`，删除 bucket/key 同式拼接的空泛相等断言；不再把该测试冒充 API 签名调用证据。真实 broker/S3/API 跨进程链路仍未验证；迁移 downgrade 仍由前序 API 3 项迁移用例覆盖，本轮未重跑它们。
- 不扩大运行时契约。本轮未改服务/仓库实现，也未解决旧进程超租约仍运行时的 publication/finalization fencing。该风险需要明确恢复策略，而不是再用更多相同的行数/终态测试声称关闭。UI补丁的两次MiniMax复核失败仍未补齐，依赖提权拒绝保持停止，整体goal active。

## Goal round 9：导出会话归属与晚返回隔离

- 根因核实：SessionProvider 在 signOut/过期时保持 sessionId 不变，只改变 status；旧导出页面只监听 sessionId，退出后仍显示旧导出。异步提交成功/失败与下载链接返回都无失效检查，可重建旧账号提示或打开旧账号签名链接。
- 修复前渲染回归真实复现 **5 failed / 4 passed**（`.validation/export-session-before.log`）：anonymous/expired 保留进度、提交晚成功/晚失败恢复旧状态、切换账号后仍点击旧链接。
- 最小修复在页面 owner：用 sessionId + status 定义导出会话边界，layout effect 在绘制前清理本地导出状态并使旧异步续体失效；个人状态查询仅在 authenticated 且归属一致时启用。请求版本号用于拒绝旧会话/被后续提交替代的结果，卸载时也失效，提交与下载的成功/失败路径均检查。未新建 token/session store，不改变服务端 owner 授权或查询 key 契约；原来的仅 sessionId 重置路径已替换。保留 request version 是为覆盖同会话后续提交与卸载，不是冗余的身份来源。
- 修复后 focused 导出交互 **10 passed**（含晚下载在 unmount 后不点击）；门户全套启动时包含当时 9 项导出测试，结果 **54 files / 450 passed**（99.36s，`.validation/export-session-web-tests.log`）；新增 unmount 参数项后 focused 10 项通过，不混记为全套已跑 451。`pnpm --filter @soymutdb/web typecheck`、`lint`、`git diff --check` 均通过。所有测试仅用已有依赖，未重试被拒安装。
- 最新文件全量重跑 **54 files / 451 passed**（100.23s，`.validation/export-session-web-tests-final.log`，exit 0），已包含新增 unmount 参数项；最终 diff-check 另验。
- MiniMax-M3.1-Flash 独立只读复核 `8b240dcd-7baf-4d1e-a401-b96efcbc42f5` 在完成前失败，续派 `7726c1af-5be3-418d-820e-47ac47dd84ee` 同样失败且无结论。没有可采纳的独立复核意见，不将运行失败记作通过，保持待复核。
- 证据限于 rendered component + deferred transport mocks，不等于真实登录 cookie/refresh、真实网络轮询或浏览器验收。人工待验步骤：A 账号导出后退出且不离开 variants 页面；确认旧提示/按钮消失；延迟 POST/下载返回后不得恢复旧状态或开链接；再登录 B 不得继承 A。未执行这些真实浏览器步骤，不报通过。
- 清理上一轮诊断生成的仓库根空文件 `pnpm-store-operation-locks`（删除前核实绝对路径、非链接、长度0）；未操作实际 `/run/user/1001` 锁，不绕过依赖拒绝。整体目标仍 active；attempt fencing、真实 broker/S3、JBrowse/完整 Pages 与依赖安全批次仍未完成。

## 2026-10-21 22:21 +08:00：最小安全依赖批次尝试，未交付

- 用户已明确授权 3 个安全 floor 的正式配置/锁写入、安装与验证（follow-redirects 1.16.1、hono 4.13.11、受影响的 Vite 7.x→7.3.7，不升级 Umi/AntD/直接 Vite 8）。不是尚未得到批次授权。
- 首次普通 `pnpm install --lockfile-only --ignore-scripts` 被 workspace-write 沙箱拒绝运行时锁；严格原命令提权获准后解析成功（供应链规则通过，1880 entries）。未改路径重试、未安装 node_modules。
- 锁图版本键确实仅新增/移除上述 3 组，但同版本 metadata 比较发现全局 Vite 范围 override 会把 Vitest/@vitest/mocker/@vitejs/plugin-react 的宽 Vite peer 范围改成 7.3.7，违反保持 Vite 8 的兼容意图；因此**没有接受该锁图或声称通过**。hono 两个适配器 peer 被全局 floor 收窄也有记录。
- 拟改成 `@umijs/bundler-vite>vite: 7.3.7` 父依赖限定以避免重写宽 peer；从批次前锁图重生。但普通命令仍被沙箱拒绝，原命令的一次提权请求被用户拒绝。已停止，不再重定向 HOME/XDG/运行时路径或采用其他方式实现该被拒操作。
- 为保持工作区一致，撤回本批 3 个 override；正式 lock 与 `.validation/security-batch-before.lock.yaml` **逐字节一致**，`git diff --exit-code -- pnpm-workspace.yaml pnpm-lock.yaml` 与 `git diff --check` exit 0。不影响其余任务改动。最小安全升级、安装、peer/frozen/dedupe/audit/构建验收均未交付；不得沿用旧 scratch audit 5 个公告来代表当前正式依赖已修复。
- 整体 goal 保持 active；依赖批次需要可获准的运行环境或用户在工作区外锁可写的环境执行，不能把拒绝解释为继续绕过的授权。不据此将整体目标标记 blocked/complete。

## Goal round 8：依赖候选真实锁图复核（只读）

- 使用已安装 PyYAML 的 `safe_load_all` 解析 pnpm 多文档锁文件，对正式图与忽略的 `.validation/dep-batch-scratch/pnpm-lock.yaml` 合并全部 package entries 后比较：**1895 → 1901**，新增 **48**、移除 **42** 个包版本键。不能把这个 scratch 视为“仅 3 个安全 floor”的窄批次。**〔2026-10-24 计数口径订正：**1895 / 1901** 是把 pnpm 多文档 YAML 的条目**相加**得到的口径，**不准确**；**独立复核自行解析复算的有效锁图是 1880 packages / 1886 snapshots / 14 importers**（importers 逐字节未变），pnpm 自身的供应链策略检查也每次打印 "1880 entries"。**本条历史记录与原日志一律不改**，仅在此订正口径；另注意 audit JSON 的 `metadata.totalDependencies`（1895）是**依赖统计口径**，与锁图的 packages 条数（1880）**不是同一个量**，勿混用。详见本文件顶部 2026-10-24 D1 节 §B〕**
- 可核对的常规变更包含整个 Umi 4.7.24→4.7.25 家族、@utoo/pack、AntD、TanStack Router/Query、turbo 平台包；旧 i18next/postcss 仍存在。之前“只读候选解析成功”不能证明 peer/dedupe/构建兼容，更不能直接把 scratch 锁拷入正式工作区。
- 建议拆分：先只批准 3 个安全 floor（follow-redirects 1.16.1、hono 4.13.11、仅受影响 Vite 7.x 的 7.3.7；不动直接 Vite 8.3.4），重新生成窄锁 diff、检查 peer/frozen/dedupe、重跑测试/构建。Umi/AntD/TanStack/turbo/i18n 常规升级另批处理。此处未重新查询上游时效，也未执行安装、正式 manifest/lock 写入或声称候选已通过兼容验证。
- 正式写入与安装需要用户明确授权；自动 goal continuation 不替代该授权。仍不自动提交、合并、发布或启动服务。

## 2026-10-21 20:45 +08:00：导出错误隐私修复（M2）

- 根因：字符过滤和限长仍会原样暴露可打印的 SQL、参数、株系名和路径，不能作为脱敏。新增共享 `soymutdb_jobs.export_errors` 固定公开失败消息；Worker 不再把异常类型/文本写入导出记录，API 对历史记录中非空原始错误同样只返回固定提示。无错误仍返回 null。原始异常仍由任务的 `logger.exception` 记录并重新抛出，用户可用 export_id 联系支持或显式重新提交；没有新增重试行为。
- API PostgreSQL 回归改为断言真实响应不含 SQL、internal_id、PRIVATE_LINE、private-secret 与私有路径；Worker 回归注入带 SQL/秘密参数的异常，断言写库的公开消息不含这些数据。共享 8 项参数化测试覆盖长文本、控制字符、空白、缺省错误。
- 验证：API 全套 **2584 passed, 4 skipped**（80.46s，日志 `.validation/export-privacy-api-tests.log`）；Worker + 原共享套件合跑 **762 passed, 33 skipped**（=663 Worker + 99 jobs-py）；新增共享用例后 jobs-py 单跑 **107 passed**；API 导出 15、Worker 生命周期/制品 23 单独通过；修改文件 Ruff 与 `git diff --check` 通过。均使用已有 Python3.15 venv，未安装依赖。
- MiniMax-M3.1-Flash 只读独立复核 `da9fd4d2-fbfe-4c68-96e8-3e3797b42b85` 已回报：未发现当前补丁的 owner-visible error_message 泄漏或阻塞性回归，确认旧记录读时掩码与原始异常日志/重抛路径；其 Worker PG 项跳过，不能补充真实 PG 证据。采纳 O2 删除不再使用异常参数的 `_safe_error_text` 辅助函数，`_fail_export` 直接使用固定消息；采纳 O3 新增 caplog 断言，保证日志带 export_id、exc_info 与原始异常。O1 store 接受原始文本仍为内部接口风险，API 读边界保持掩码；O4 不新增不必要的包根导出；O5 新接口必须复用掩码；O6 Celery 原始异常为运维面，不声明其已脱敏；O7 格式/超租约状态竞态维持未完成记录。返修后 Worker + jobs-py 全套 **770 passed, 33 skipped**（663 + 107），Ruff 与 diff-check 通过。
- 本轮仅封闭导出状态的 error_message 响应边界；不声称所有内部日志/Celery backend 已脱敏，也未解决超租约执行 fencing、broker/S3 E2E、JBrowse 制品构建及正式依赖批次。整体目标保持 active。

## 2026-10-21 20:33 +08:00 后续复验：纠正租约并发与验收结论

本节优先于下方较早记录中的收口表述，整体目标仍未完成。

- **真实并发反例**：先前 H2 的 UPDATE 仅检查 `status='running'`，两个线程用 Barrier 同步读到同一个过期租约后均返回 `resume`；新增并发回归首跑 **1 failed, 1 passed**。此前“只有一个接管赢家”的说明不成立，原测试只是顺序调用，不能作并发证据。
- **根因修复**：`VariantExportStore._renew_lease` 除状态外，以 `started_at IS NOT DISTINCT FROM :observed_started_at` 比较并交换观察到的租约；另一个接管者刷新时间戳后，旧观察者 UPDATE 不再命中。NULL 时间戳同样受保护。真实 PG 参数化回归覆盖 pending 双认领、过期 running 双接管、NULL 时间戳双接管。
- **验证**：专用 PostgreSQL16，`SOYMUTDB_NATIVE_TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:55432/soymutdb_test_stabilization_20261020`，Worker 全套 **663 passed, 33 skipped**。命令：`.mamba-root/envs/py315/venvs/worker/bin/python -m pytest apps/worker/tests -q`，PYTHONPATH 为 jobs-py/src 与 worker/src，低线程变量为 1。新增 3 项真实并发测试，不把 skip 计为通过。
- **仍无 exactly-once 保证**：租约过期不代表旧进程已停止。超时未终止的旧执行可与新执行重叠，写同一对象键；当前成功/失败终态更新也未用 attempt token fencing。任务模块说明已纠正。未引入新列/自动重试/额外框架；该剩余风险不能被“固定对象键”或并发认领测试掩盖。
- **M2 证据纠正**：过滤不可打印字符与限长不是 SQL/参数脱敏；下文“异常文本与 SQL 参数不再原样入库”不可作为敏感信息不泄漏的保证。需要安全错误类别/公开消息与内部诊断分离后才能收口。
- **M7 证据纠正**：Worker PG 测试表由窄 Core 定义创建，非真实迁移 schema；拼接 bucket/key 的相等断言不是实际 Worker 上传到 API 签名的端到端验证。API 测试仍模拟任务完成、签名器仍打桩。不得称真实 broker/S3 全链通过。
- **上一轮额外验收记录（尚非本轮重跑）**：root JS test 11/11 tasks；门户 external/internal build 成功；artifact headers 与 nginx headers 检查通过；JBrowse build 多次因 esbuild EAGAIN/Go errno=11 失败，未证实源代码根因，也没有通过的完整 Pages 制品。`build-pages-artifact.sh` 在 setup 的 corepack 全局路径写入报 EROFS。不能将这些未通过项记作通过。
- **依赖候选仅在忽略的 scratch 中解析**：正式 manifest/lock 未应用候选。上一轮 registry/audit 记录当前图 11 advisories，scratch 图 5（已记录的 residual）；scratch 解析不是安装/peer/回归兼容性证明。scratch 中还出现旧新版 i18next/postcss 并存，且版本范围可能带入计划外传递升级，必须审 diff/peer/dedupe 后再申请正式批次。
- **pnpm 环境根因订正**：store-operation-lock 的实际路径由 strace 定位到 `/run/user/1001/pnpm-store-operation-locks-1001`，不是此前猜测的 global store。此前不能断言 store 本身不可写。敏感配置访问曾被 Safety Net 拒绝，未读取其内容，不继续尝试。正式依赖写入/安装仍需明确授权。

## 2026-10-21 16:10 +08:00：Task5 独立复核逐条答复（H1–H3 / M1–M7 / L1–L7）

- **复核来源与性质**：只读独立复核子代理 `6db2603a-199c-4934-9581-c1cd37275801`（复核本身未改任何文件）。结论是**建议**，不是事实：每条都回到真实代码/真实数据库上核对后再决定采纳、修正或只记录。
- **复核者未跑 PostgreSQL 后端套件**（认为 conftest 的 `create_all/drop_all` 对只读复核过于破坏性），因此其“未被真实库验证”的判断由本轮补齐。

### HIGH

- **H1（API/Worker 根本导入失败：env 里的旧 `soymutdb_jobs` 遮蔽仓库源码）——采纳，已在根因处修复。** 复核者判断“必须重装共享包”+“让 `_ensure_jobs_package()` 无条件优先仓库源码”。本轮**不安装**（无安装授权），改在导入路径上根治：`apps/api/app/__init__.py` 与 `apps/worker/src/soymutdb_worker/__init__.py` 在任何子模块导入前把 `packages/jobs-py/src` 插入 `sys.path[0]`；`apps/api/app/core/task_contract.py:45` 与 `apps/worker/src/soymutdb_worker/shared.py` 的 `_ensure_jobs_package()` 改为**无条件**优先仓库源码，并订正原 docstring 的错误说法。复核后复验：API 与 Worker 实际导入的均为 `packages/jobs-py/src/soymutdb_jobs/export_artifact.py`（不再是 site-packages 里的旧副本）。Docker/CI 本来就拷源码，行为不变。
- **H2（重复投递会重跑导出，且与 docstring 矛盾）——采纳，已按“租约”语义修复。** 复核者的两条修法（lease 判定 / 订正 docstring）都做了，但以前者为主：`apps/worker/src/soymutdb_worker/repositories.py` 新增 `EXPORT_CLAIM_LEASE_SECONDS=3600` 与 `get_claim_state()`；`begin_run()` 现在区分 `missing`（无记录）/ `skip`（终态、失败、或**租约内的重复投递**）/ `resume`（RUNNING 且租约已过期）/ `run`。租约接管用**直接受保护 UPDATE**（`WHERE id=:id AND status='running' SET started_at=now()`，即 `_renew_lease`），因为共享迁移矩阵里没有 `RUNNING→RUNNING` 自转移，`update_status()` 表达不了“只挪租约、不改状态”；该 UPDATE 的 `rowcount` 判定保证两个同时接管的投递只有一个赢。`apps/worker/src/soymutdb_worker/tasks/export.py` 的模块 docstring 已按**实际保证**重写（“租约内重复投递不会再起一次同请求的导出”），不再声称无法保证的事。
- **H3（无记录的导出被静默丢弃且任务报 SUCCESS）——采纳，改为显式失败。** `begin_run()` 对无记录返回 `missing`；`tasks/export.py` 新增 `ExportRecordMissingError`，任务在该分支 `logger.error` 后**抛出**（Celery 记 FAILURE），不再返回 `{"status":"skipped"}`。终态/失败仍是 `skip`（跳过不是失败）。

### MEDIUM

- **M1（所有者域响应缺 `private, no-store` + `Vary: Authorization`）——采纳。** `apps/api/app/api/v1/variants.py` 新增 `_private(response)` 辅助（与 `gwas.py:36-38`、`blast.py:28`、`analyses.py:52` 同形），两个新 GET 都带上；新增回归测试断言 `cache-control: private, no-store` 与 `vary: Authorization`。
- **M2（把 Worker 原始异常文本回给所有者）——采纳，两端都裁剪。** API 侧 `variant_export_service._sanitize_error`（只留可打印字符、上限 500）已先行落地；本轮补上 Worker 侧：`_safe_error_text()`（只留可打印字符、上限 2000，`_MAX_ERROR_LEN`）在 `mark_failed` 前裁剪，异常文本与 SQL 参数不再原样入库。
- **M3（404 与 GWAS 的 403 不一致）——不改动代码，书面记录分歧。** 复核者自己也判定 404 更好（不构成存在性预言机），只要求把分歧写下来：`variant_export_service._load_visible` 的 docstring 明确说明“导出对他人按不存在返回 404，**有意**不同于 GWAS 的 403”。GWAS 的 403 是较弱模式，本轮不扩范围去改 GWAS。
- **M4（持久记录的 `filters` 存的是株系“名字”而非 public_id）——只记录，不改结构。** `filters` 从不出现在任何响应（`ExportStatusResponse` 无该字段，也没有列出导出记录的管理端接口），且它是 **Worker 查询键**（Worker 侧按 `mutant_line_name` 连接，公开 id 在导出 SQL 中被显式拒绝）；改成 public_id 需要改 Worker 的查询契约与共享包，超出已批准的最小扩展。已在模型 docstring 标注 `filters` 为**内部专用、绝不序列化**，并写明它保存的是解析后的株系名。
- **M5（`assembly_key` 取的是发布默认装配而非请求装配）——采纳，已修。** `apps/api/app/api/v1/variants.py` 改为 `assembly_key=filters.get("assembly") or release_context.assembly`，使记录与制品（Worker 用请求装配产出）一致。
- **M6（`release_key` 暴露裸数字发布主键、命名不显式）——只记录，不改字段。** 改成显式命名会同时改动共享契约、制品表头与门户既有词汇（门户 URL/查询早已用数字 release id），属于契约级变更；本轮在模型与 schema 的 docstring 里写明 `release_key` 是**发布标识**（不是株系/变异身份），并把它与 `assembly_key` 一起标注为装配作用域的溯源字段。
- **M7（两个核心保证只在桩上验证：受保护 UPDATE 与“API 签的正是 Worker 存的键”）——采纳，已补真实库测试。**
  - 新增 `apps/worker/tests/test_export_claim_postgres.py`（**10 passed**，真实 PostgreSQL 16 一次性 schema，沿用 `test_postgres_variant_store.py` 的既有模式）：同一命令两次投递只有一个认领成功；租约内不接管；租约过期可接管且刷新 `started_at`；无记录返回 `missing`；failed/succeeded 永不再认领；**迟到的成功不能覆盖失败**；**迟到的失败不能覆盖成功**；Worker 落库的键 == 共享契约键 == API 签名的 `f"{bucket}/{key}"`；另有测试把 Worker 会写的列名逐一钉在 API 迁移 `0049` 的源码上，防止两侧漂移。
  - API 侧 `apps/api/tests/test_variant_exports.py` 补断言：签名路径**精确等于** `f"{settings.s3_export_bucket}/{build_export_artifact_key(record.id, filename)}"`（`build_export_filename(record.id, record.format, record.compress)`），不再只是“包含 exports/”。
  - 客户端与查询键也补了测试：`packages/api-client/src/variants.test.ts`（三个端点与请求体形状）、`packages/query-keys/src/query-keys.test.ts`（导出键按 export id **与 session** 作用域，不与变体列表缓存相撞）。

### LOW

- **L1（客户端手写类型而非生成的 OpenAPI schema）——采纳。** `packages/api-client/src/variants.ts` 改为 `components["schemas"]["ExportStatusResponse"] / ["ExportDownloadResponse"]` 派生（与 `auth.ts`、`analyses.ts` 同形），`check:contract` 通过。
- **L2（每请求 `get_settings()`）——采纳。** `variant_export_service.py` 改为模块级 `settings = get_settings()`。
- **L3（Worker 的 Core 更新不刷新 `updated_at`）——采纳。** `apps/worker/src/soymutdb_worker/tables.py` 的 `variant_exports` 补 `updated_at` 列（NOT NULL + `server_default=now()`，与迁移一致），Worker 的四处受保护 UPDATE（认领/租约续期/成功/失败）都写 `updated_at`。
- **L4（`mark_succeeded` 返回值被忽略）——采纳。** `tasks/export.py` 现在检查返回值：为 False 时 `logger.warning` 明确写出“产物已生成但记录已不是 running，产物未被登记”，不再报出记录并不承载的成功。
- **L5（门户里导出 id 跨登录残留）——采纳。** `apps/web/src/routes/variants/index.tsx` 改用 `useSession()`：查询键改为 `queryKeys.variants.export(exportId, sessionId)`（`packages/query-keys/src/index.ts` 同步接受可选 session 作用域），并在 `sessionId` 变化时清空导出 id、状态与错误；查询出错（404/无权）时停止轮询。新增回归测试“会话切换后不再跟踪上一个账号的导出”。
- **L6（开发校验脚本的 `download_url` 永远是占位符）——采纳。** `scripts/dev/verify-native-export-chain.py` 改为回报 `artifact_key`（任务结果里本来就只有对象键，签名链接由 API 按需签发）。
- **L7（`create_constraint=True` 在 PG 原生 enum 上是空操作）——不改动。** 该写法是本仓库所有枚举模型的既有约定（`analysis_job.py:70,83`、`blast.py:59,99,113`、`gwas.py:90,101` 等），单独改这一处只会制造不一致；复核者也判定无害。保持一致，编译后的 ORM DDL 与迁移 0049 完全相同（复核者已核对）。

### 返修后的全量门禁（复核之后重跑，精确计数）

- API：`.mamba-root/envs/py315/venvs/api/bin/python -m pytest apps/api/tests -q` → **2584 passed, 4 skipped**（新增 1 项：`Cache-Control/Vary` 回归）。
- Worker：`.mamba-root/envs/py315/venvs/worker/bin/python -m pytest apps/worker/tests -q` → **660 passed, 33 skipped**；本轮把 `SOYMUTDB_NATIVE_TEST_DATABASE_URL` 指向专用 PG16 测试库（`postgresql+psycopg2://postgres@127.0.0.1:55432/soymutdb_test_stabilization_20261020`），于是**既有的 native PG 用例与本轮新增的 10 项导出认领用例都真正跑在 PostgreSQL 上**（此前该组因缺环境变量被 skip；skip 不算通过）。
- MCP：**66 passed**（仍需先 unset 代理变量，原因见下）。
- 门户 `pnpm --filter @soymutdb/web exec vitest run --maxWorkers=1` → **54 files / 445 tests**；api-client **31 files / 198 tests**；query-keys **12**；jobs-py **99**。
- 根门禁 `pnpm lint --concurrency=1` → 12/12、`pnpm typecheck --concurrency=1` → 13/13（整条 exit 0）；`packages/api-client/scripts/check-contract.sh` → `"status": "PASS"`；locale 键对齐 → `Locale key check passed`；`git diff --check` exit 0。
- Ruff：CI 的阻塞范围 `apps/api` 内 `ruff check app` → **All checks passed**；本轮改动/新增的 Python 文件单独 lint 干净（仓库其余 210 条历史告警在测试目录内、且不在 CI 门禁范围，未在本轮顺手改动）。

### 复核后仍然成立的边界

- 复核未发现 CRITICAL；其“已核实正确”清单（授权与 404 语义、公开身份边界、受保护 UPDATE 的谓词与 rowcount 语义、failed 为终态、共享契约、迁移与 ORM DDL 一致、POST 响应字节兼容与 blast radius、ruff/命名/无新增权威存储）与本轮独立复跑一致。
- 证据边界不变：**没有**真实 MinIO/S3 端到端下载（签名器在测试中打桩）、**没有** Celery broker 真实投递、**没有**浏览器 E2E、**没有**双站制品构建证据；导出认领语义已在真实 PostgreSQL 上验证，但“真实 worker 进程 + 真实 broker + 真实 S3”的链路仍未覆盖。
- Task5 切片实现 + 复核返修 + 本机门禁已就绪；**Task6（依赖批次）与全线验收未开始**，整体目标保持 active。

## 2026-10-21 15:45 +08:00：Task5 变体导出持久化与所有者可见状态（已批准最小扩展）

- **范围与授权**：仅做已批准的 `variant_exports` 最小扩展（计划 Task5）。未引入通用任务框架、未做执行级自动重试、未加人工重试接口、未加 MCP 导出写工具；不新增权威存储，不改基线分支，不做 Git 写/推送/合并，未启动任何长期服务。
- **缺陷（根因）**：导出请求原先只写一条 outbox 事件，Celery 结果后端是易失的——提交者与 API 都无从知道导出是否完成、文件在哪里；任务失败也没有终态可查。导出因此是一条“提交即消失”的死路。
- **实现（所有者各自落地）**：
  - API：新增 `apps/api/app/models/variant_export.py`（`variant_exports` 表：owner/status/release_key/assembly_key/format/compress/filters JSONB/artifact_path/record_count/file_size/error_message/started_at/completed_at/expires_at）与迁移 `0049_variant_exports.py`（revision 0049→down 0048，enum `variant_export_status_enum` + 表 + 3 索引，downgrade 全部回退）；`apps/api/app/services/variant_export_service.py` 负责所有者判定与**按需**签名；`apps/api/app/api/v1/variants.py` 的 POST 在**同一事务**内写记录与 outbox 事件，响应体保持 `export_id/status=pending/message` 不变，新增 `GET /variants/export/{export_id}`（状态）与 `GET /variants/export/{export_id}/download`（签名下载）。
  - 授权语义：与既有 GWAS 同构的“所有者或管理员”。他人导出**按不存在返回 404**（不泄露存在性），viewer 403，未就绪 409，过期或无制品 404；不可猜 UUID 本身**不是**授权。
  - Worker：`apps/worker/src/soymutdb_worker/repositories.py` 新增 `VariantExportStore`，沿用 BLAST 的受保护 UPDATE 模式（`WHERE status = <期望值>` + `transition_allowed` 矩阵校验）；`apps/worker/src/soymutdb_worker/tasks/export.py` 先**认领**再执行，失败落到终态后**不自动重跑**（FAILED 纳入跳过集），不再把 24 小时预签名 URL 放进任务结果（改由 API 按需签名 900 秒）。
  - 共享契约：制品对象键与文件名由 `packages/jobs-py/src/soymutdb_jobs/export_artifact.py` 唯一拥有（API 与 Worker 同源），Worker 写入 `expires_at = now + 7 天`，API 侧 `EXPORT_ARTIFACT_RETENTION_DAYS = 7` 对齐。
  - 门户衔接：新增 `packages/api-client/src/variants.ts` 的 `getVariantExportStatus/getVariantExportDownload`，`packages/query-keys/src/index.ts` 新增 `queryKeys.variants.export(exportId)`，`apps/web/src/routes/variants/index.tsx` 提交后轮询导出状态，succeeded 时出现下载按钮（按需取签名链接），failed 时显示失败原因；i18n `variants.export*` 六个键 en/zh 对齐。
  - 契约链：`packages/api-client/openapi.json` 与 `src/generated/openapi.d.ts` 由既有生成链重出（新增 2 条路径、2 个 schema），`check:contract` 仍 PASS、route-visibility 无漂移。
- **重试预算核实（计划 Task5 明确要求）**：Worker 侧只有 `tasks/email.py` 有 `max_retries=3`（瞬时投递语义合适）；导出任务**没有** `autoretry_for/self.retry`，即**不做执行级自动重试**。`settings.outbox_max_attempts=5` 是**投递**预算（把事件交给 broker 的次数），不是执行重试，任务异常不会让 outbox 重投。因此失败导出是终态，用户的恢复入口是门户“重新导出”按钮（显式动作），不存在掩盖确定性错误或重复科学计算的重试路径。
- **测试（真实 PostgreSQL 16，非桩）**：
  - `apps/api/tests/test_variant_exports.py` **14 passed**：提交保持旧响应形状；记录与 outbox 事件同事务落库且 owner 正确；匿名 401；所有者可读状态、他人 404、管理员可读、viewer 403、未知 404；succeeded 时按需签发短时效 URL（断言 `expires_in` 与响应一致且对路径签名）、pending 409、过期 404、他人下载 404、failed 状态可读、失败原因按 GWAS 既有约定裁剪（去不可打印字符、限长 500）。
  - `apps/api/tests/test_variant_exports_migration.py` **3 passed**：离线 SQL 断言升级建表/enum/3 索引、降级删表删类型；**真实往返**在自建一次性库 `soymutdb_variant_exports_migration_rt` 上 upgrade head → downgrade 0048 → upgrade 0049，逐次核对表与类型存在/消失（共享测试库不被触碰）。
  - Worker `apps/worker/tests/test_export_lifecycle.py` + `test_export_public_artifact.py` **25 passed**：认领/跳过语义、FAILED 永不重跑、成功记录对象键与到期、失败落终态、终态不被覆盖、任务跳过不可认领的导出、任务失败先落库再抛错、共享键契约、JSON 制品不含内部键。
  - `packages/jobs-py/tests/test_export_artifact.py`：文件名/对象键/前缀逃逸/格式白名单契约（jobs-py 全量 **99 passed**）。
  - 门户 `apps/web/src/routes/variants/export-flow.test.tsx`：提交→跟踪记录、就绪后经签名链接下载、失败不提供下载。
- **全量门禁（固定 Node 路径、workspace `PNPM_HOME=$PWD/.ph`、低线程）**：
  - `.mamba-root/envs/py315/venvs/api/bin/python -m pytest apps/api/tests -q` → **2583 passed, 4 skipped**（bash-f152b957cee144ec；含失败原因裁剪后的最终一次全量）。
  - `.mamba-root/envs/py315/venvs/worker/bin/python -m pytest apps/worker/tests -q` → **638 passed, 42 skipped**（bash-7d5f6a309a9447a5）。
  - MCP：`.mamba-root/envs/py315/venvs/mcp-server/bin/python -m pytest apps/mcp-server/tests -q` → **66 passed**（bash-…；需先 `unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy no_proxy NO_PROXY`：本机沙箱 `no_proxy` 含 `[::1]`，httpx 解析代理时报 `ValueError: invalid literal for int() with base 10: ':1]'` 使被测服务进程启动失败——属沙箱环境变量，不是代码缺陷）。
  - `pnpm --filter @soymutdb/web exec vitest run --maxWorkers=1` → **54 files / 444 tests passed**；api-client **31 files / 196 tests**、query-keys 11、jobs-py 99（bash-bb67ea53d0094e24 覆盖 client/web typecheck+lint+`check:contract`+locale parity）。
  - 根门禁 `pnpm lint --concurrency=1` → 12/12、`pnpm typecheck --concurrency=1` → 13/13，**整条 exit 0**（bash-35df34898a674e1e）。默认并行度下曾出现 `@soymutdb/i18n#lint` 与 `@soymutdb/genome-data#typecheck` 失败，单独复跑两者均 exit 0，判定为沙箱并行资源伪影，已用串行复跑取信。
  - 治理：`scripts/check_architecture.py` 通过、`check_worker_test_package.py` 通过、`check_web_query_keys.py` 通过、`check_workspace_exports.py` 通过、`check_deprecated_api_usage.py` 预算内、`git diff --check` exit 0。
  - `scripts/check-worker-task-registry.py`（发布镜像门禁）：首跑报 `untracked Worker tasks: native_retention.cleanup, page_builder_publish.publish_definition`——这两个任务在 `apps/worker/src/soymutdb_worker/main.py:53,62` 的 include 列表中，但脚本的 `EXPECTED_TASKS` 从未收录（**基线既有漂移**，与本切片无关，且会卡住发布镜像构建）。已把两个既有任务名补进期望集合（只改清单，不改运行时行为），复跑 **Worker task registry OK: 25 tasks**。
- **既有测试的连带修正（非放宽断言）**：
  - `apps/api/tests/test_release_bound_queries.py` 直调路由函数，路由新增 `current_user` 依赖后需显式传入；已补传并**加强**断言（新增“导出记录与命令事件同事务落库、release/assembly 归属正确、状态为 pending”）。
  - `apps/api/tests/test_variant_mutant_identity.py` 的 `export_caller` 夹具原先用无 `id` 的 `SimpleNamespace` 冒充用户；导出记录有指向 `users.id` 的外键，改为**真实建一个 researcher 用户**再覆盖 `get_current_user`。
  - `apps/api/tests/test_security_round2_boundaries.py::test_no_public_response_body_carries_an_internal_id` 断言“内部键不出现在响应体”，但它对**自动生成的整型代理键**做子串匹配：当该键为 `1` 时会命中时间戳里的 `1`（**假阳性**，不是泄漏）。已把该行内部键固定为 `987654321`，断言反而更强（只有真泄漏才会命中）。
  - `packages/api-client/scripts/{generate,check}-api-client.sh` 原先 `export PYTHONPATH="$REPO_ROOT"` 会**覆盖**调用者的 PYTHONPATH，导致以工作区源码方式使用 `soymutdb_jobs` 时 OpenAPI 导出失败；改为 `$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}`（保留调用者路径），生成链与契约检查据此复跑通过。
- **证据边界**：以上是 PostgreSQL 真实库上的 API/Worker/MCP 回归、离线与真实迁移往返、模块级契约测试、门户组件级测试与类型/Lint/治理门禁；**没有**真实 MinIO/S3 端到端下载（签名器在测试中打桩）、没有 Celery broker 真实投递、没有浏览器 E2E、没有双站制品构建证据。Task5 切片实现与本机门禁已就绪；Task6（依赖批次，全线验收）未开始，整体目标保持 active。

## 2026-10-21 15:20 +08:00：JBrowse第二遍独立复核返修（F1–F4）

- 第二遍独立只读复核 `1181fde4-6528-48d5-b4b9-26c3e0e2fc65` 返回四项具体发现，主代理逐项回到本机安装源码与真实调用链核实，不以“71项测试通过”否认runtime契约问题：
  - **F1 viewport属性名**：复核指出 `view.visibleLocString`（单数）不存在。主代理核对本机 `@jbrowse/plugin-linear-genome-view@2.18.0` `esm/LinearGenomeView/model.js:34-46,759`：`calculateVisibleLocStrings` 返回**字符串**（多区域用空格连接，空内容返回 `""`），`model.js` getter 为 `visibleLocStrings`（复数）。已把 `bridge-init.ts`/`App.tsx`/测试桩统一改为复数；`core/util/index.js:258-277` 的 `assembleLocString` 为 1-based 闭区间、`..` 分隔符，本仓 `parseLocus` 同时接受 `-` 与 `..`。
  - **F2 跨发布携带旧坐标/旧轨道**：发布切换时新 view 用旧发布的 `location`，且旧轨道 ID 在新 config 里过滤为空 → 零轨道 view。返修在**两个所有者**同时落地：门户 `postInit` 改用 `scopeSafeInitPayload(raw, lastInitRef.current)`——当 release/assembly 变化且 locus/tracks 与 iframe 当前所示完全相同时**不下发**（属于旧作用域的继承值），用户显式新坐标仍下发；JBrowse 侧 `planPortalInit` 继续在 `scopeChanged` 时丢弃继承坐标，并新增“请求轨道在目标 config 解析为空时回落到目标默认轨道”，不再出现空浏览器。
  - **F3 默认轨道不确定**：API 轨道列表无 `ORDER BY`（`apps/api/app/services/track_service.py:160-195` 确认无 order_by），原 `defaultTrackIds` 取“第一个 Feature/Variant”依赖到达顺序。返修为按 `trackId` 排序后再选，且优先选 release 自身标注为 gene/annotation 与 variant 的轨道；新增“顺序无关”回归。
  - **F4 晚到 viewport 事件**：原守卫只比 release，4→9→4 循环会重新接受旧 release-4 事件。返修为**单调 scope epoch**：门户每次作用域（release/assembly）变化给出自增 `scopeEpoch` 并随 init 下发，JBrowse 回显到 `locus-change`；门户拒绝 epoch 不等于当前值的晚到事件（release 字段保留为旧消息兜底）。该字段是 bridge-v1 的可选扩展，老消息仍可接受。
- 另外修掉两处同链真实缺陷：门户 `validateSearch` 的 locus 默认值由硬编码 `"chr01"` 改为空串（不再把写死染色体当用户坐标），`buildJbrowseUrl` 在无坐标时不下发 `locus`；JBrowse 手工导航改用 `parseLocusList`，JBrowse 多区域 viewport（空格分隔）不再被误判为 gene 查询而触发搜索失败。
- 新增“对着已安装包断言”的契约测试：读取本机 `@jbrowse/plugin-linear-genome-view` 的 `dist/LinearGenomeView/model.d.ts`，断言存在 `visibleLocStrings` 且不存在单数 `visibleLocString`，避免再用自写桩掩盖属性名错误。
- 主代理命令（固定Node路径、workspace `PNPM_HOME=$PWD/.ph`、`RAYON_NUM_THREADS=1 GOMAXPROCS=2 UV_THREADPOOL_SIZE=2`）：
  - `pnpm --filter @soymutdb/jbrowse test && pnpm --filter @soymutdb/jbrowse typecheck && pnpm --filter @soymutdb/jbrowse lint`：JBrowse **71 tests passed, 0 failed**（bash-28af193fe0084516）。
  - `pnpm --filter @soymutdb/web exec vitest run --maxWorkers=1 && pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint && pnpm --filter @soymutdb/i18n-core check:locale-keys && git diff --check`：门户 **53 files / 441 tests passed**，web typecheck/lint、locale parity、diff-check 整条 **exit 0**（bash-fafd7984fe2a42ac）。
  - 中途一次失败为本机测试用 `require.resolve("@jbrowse/plugin-linear-genome-view")` 在 pnpm 严格依赖下不可直接解析（该包是 `@jbrowse/react-linear-genome-view` 的传递依赖），改为经 React 入口的 `createRequire` 解析后通过；另一处为 `buildJbrowseUrl` 的 `locus` 改为可选后 `searchParams.set` 类型报错，改为仅在有坐标时下发。两处都是本轮返修引入的编译/测试问题，已就地修正，未放宽断言。
- 证据边界：以上是纯模块契约测试、组件级真实 `MessageEvent`（带正确 origin/source）与类型/Lint门禁；**没有**真实 iframe 渲染、FASTA/TRIX/BAM 数据加载、双站制品或浏览器 E2E 证据。`pnpm --dir e2e ... --list` 仍被 pnpm 自动依赖校验/只读 store 拒绝，未绕过、未安装。Task1 切片到此收口；导出扩展（Task5）、依赖批次（Task6）与全线验收仍未完成，整体目标保持 active。

## 2026-10-21（+08:00）：JBrowse独立复核返修，覆盖门户真实消息边界

- MiniMax 9af7e48a已返回：初始化intent/release隔离原要求成立，但发现原生gene搜索需Assembly对象、门户把缺轨道发成[]导致空view、默认轨道ID与API不一致、gene写locus、集合顺序引发重建。主代理逐项核对本机core assemblyManager.waitForAssembly（返回已加载模型）、LGV搜索签名和实际portal postInit；不以旧63项/tsc通过反驳runtime契约问题。
- 原生导航helper现在通过当前session.assemblyManager.waitForAssembly(name)获取完整Assembly对象给navToSearchString，坐标仍给navToLocString传名称；返回view.visibleLocString，手工/bridge成功后只写真实viewport，不再把gene输入写坐标URL。manager未就绪安全失败。类型用泛型AssemblyModel约束而不是错误string签名。
- 轨道语义返修：撤销本批自行引入的“bridge []明确清空”语义，保留bridge-v1既有[]表示无指定的兼容性；门户不再为无选择合成[]。同scope空/省略保留选择，跨scope空/省略采用目标默认（undefined哨兵），不把旧ID带入新config。集合排序/去重比较避免无意义rebuild。
- config原所有者新增defaultTrackIds：只从目标config选择真实reference、首个FeatureTrack、首个VariantTrack，不再用gene_models/variants_v4旧别名；App和buildJBrowseConfig.defaultSession复用。缺某类型时如实显示较少轨道，不伪造3。原静态DEFAULT_TRACKS导出保留兼容但不作为运行默认。
- 同链额外核实并修复：installed model并无subscribeToViewState，改用有scope guard/cleanup的MobX reaction观察visibleLocString与轨道（含清空）。原portal mirror漏release导致同坐标release-only URL变更不发init；现比较release。viewport消息增加可选release，拒绝旧release晚到事件，且native assembly/track-only变化更新URL，不再被旧URL反向重置。此字段为bridge-v1可选扩展，老消息仍接受；timer在view/locus未就绪不发viewport通知。
- 新门户组件测试browser.test.tsx实际挂iframe并派发带正确origin/source的ready/locus-change事件：未选tracks不合成[]、显式tracks、同坐标release-only init、拒绝旧release事件、native assembly/track-only URL更新5项。原生owner测试增加Assembly模型对象/返回真实locus、模型不可用、legacy[]兼容、跨scope默认、轨道集合顺序及API形状默认ID；不把stub API当真实浏览器数据加载证明。
- 主代理 `pnpm --filter @soymutdb/jbrowse test && pnpm --filter @soymutdb/jbrowse typecheck && pnpm --filter @soymutdb/jbrowse lint && pnpm --filter @soymutdb/web exec vitest run src/routes/browser.test.tsx --maxWorkers=1 && pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint && git diff --check`：JBrowse **67 passed**、门户组件 **5 passed**、两包typecheck/lint/diff-check，整条exit0（bash-1cb5b1c0a9484668）；之后只增native timer未就绪guard，最终bash-103e951791244226重跑同JBrowse67项、tsc/lint/locale parity/diffcheck整条exit0。门户完整回归bash-ee61bf7f1f8f48c3：53files/438tests+tsc/lint/locale parity/diffcheck整条exit0；随后补“新标签页打开”使用实时search而非iframe初始session，现有release-only组件回归同时断言新标签release9、iframe原src4不重载。最新全套bash-c676c8845baf4abe已收集：53files / **438 tests passed**，web typecheck/lint/diffcheck整条exit0；独立只读返修复核1181fde4-6528-48d5-b4b9-26c3e0e2fc65待返回。
- 仍未做真实iframe/索引/FASTA/BAM加载E2E、双站制品验收；pnpm e2e预执行依赖检查的sandbox拒绝未绕过。Task1等待复核收尾，整个目标和导出/依赖/全线验收保持active。

## 2026-10-21（+08:00）：JBrowse初始化意图与原生导航（Task1浏览器切片）

- 延续同一HEAD/dirty基线，无Git写操作/安装/服务启动。ChangeNecessity：原applyInit先setRelease，再在config未就绪时return而丢弃assembly/tracks/locus；有旧config时按旧track集合过滤新发布请求；release-only变更可在旧view执行locus导航。原手工gene导航调用不存在的navToSearchResults，直接navTo还依赖当前displayedRegions，不支持正常跨染色体切换。
- 新bridge-init纯owner模块保留完整release/assembly/tracks/locus意图，未就绪视图或scope/track变更标记rebuild；显式[]清空轨道，省略tracks保留选择，scope变化省略locus则清除旧坐标，禁止把v4坐标重标v5。App立即保存pending字段、撤下旧view，在目标release的完整config就绪时才过滤/去重track id和解析reference_sequence别名；不存在的轨道不再伪造FeatureTrack session配置。多个pending init按最新snapshot合并，不再检查旧config后丢字段。顶部assembly选择器复用此owner。
- config还验证返回assembly.name与当前resolvedAssembly一致；加载期间清除过期错误，默认assembly尚在采用时不先报无assembly错误。未加入默认/旧发布config fallback。
- 查阅本机实际安装的@jbrowse/plugin-linear-genome-view 2.18.0 dist/LinearGenomeView/model.js:820-855：navToLocString负责等待assembly、解析坐标/配置新displayedRegions再navTo；navToSearchString({input,assembly})是真实搜索API，不存在navToSearchResults。新navigateBrowserView沿原生公共方法，避免手工1→0换算/跨染色体失败；手工与同scope bridge导航使用同helper。失败显示安全双语可重试提示、不展示原始内部diagnostic，未就绪时禁用Go；不清除仍可用的view。
- 扩展既有bridge-contract.test.mjs，新增11项：加载前保留intent、release-only同名assembly、scope变化清坐标/显式新坐标、locus-only复用/无view重建、空tracks清空、pending消息合并、正确config筛轨道及reference别名、invalidrelease不回退、原生跨染色体/feature API委派、失败传播。
- 命令（固定Node、workspace PNPM_HOME、低线程）：`pnpm --filter @soymutdb/jbrowse test && pnpm --filter @soymutdb/jbrowse typecheck && pnpm --filter @soymutdb/jbrowse lint && pnpm --filter @soymutdb/i18n-core check:locale-keys && git diff --check`：**63 tests passed, 0 failed/skipped**，typecheck/lint/locale parity/diff-check整条exit0（bash-38dbcfbc5c084226）。不新增测试依赖、不修改test脚本/安装包。
- 边界：真实owner纯模块执行+既有entry/bridge/config contracts和类型/Lint；没有React effect/iframe真实渲染验收或完整JBrowse模型/数据加载E2E，不把这些当浏览器通过。MiniMax只读复核9af7e48a-258a-47dc-b344-7b6ba5799529待返回。整个目标还剩导出扩展、依赖批次和全线验收。

## 2026-10-21 13:12 +08:00：BLAST按权威基因记录导航（Task1门户切片）

- TaskStartSnapshot：HEAD `01fc163a4c6488f97fe44ecf8f587b145cf989aa`，保留先前dirty工作区，原BLAST WIP把subject_id和DIAMOND AA区间拼成locus。ChangeNecessity：蛋白比对坐标不属于基因组命名空间，必须在已有gene owner解析真实区间。跨client/portal生物坐标契约为Medium，沿用已批准Task1设计并独立复核；不引入新存储/后端端点/推断映射/全局release写入，无新增架构所有权。
- shared BlastJob补API已有release_id/assembly_name可选声明，BlastDatabase补release_id，normalizer本来通过spread保留字段，本轮新增测试证明而非虚构runtime字段丢失；门户局部BlastJobWithProvenance/BlastDatabaseWithAssembly/BlastHitLoose旁路删除，使用真实shared类型。
- 新resolveBlastHitGenomeTarget按用户点击才请求：job release显式X-SoyMutDB-Release覆盖当前pin；同release assemblies精确唯一name、有效正整数id；精确encoded subject_id与assembly_id请求gene，返回assembly/gene_id/有效安全整数区间一致才构建chr:start-end。404、未映射、歧义或无provenance拒绝，不去后缀/模糊匹配，不用AA坐标，不依赖当前数据库列表，不列表N+1。后端genes.py list_assemblies真实依赖ReleaseContext已读核对。
- 门户JBrowse按钮有loading/禁重入、清晰安全错误与再次点击恢复；同tab到/browser避免异步popup blocker，search传job release+assembly+权威locus。离开结果页面取消晚到导航。旧作业Gene search和当前release不一致时明确禁用并说明，未侵入search/genes全局状态；原始subject_id仍完整可读。
- 窄主代理验证命令（Node固定路径、workspace PNPM_HOME、RAYON=1/GOMAXPROCS=2/UV_THREADPOOL=2）：api-client blast12+web blast11 tests passed，两包typecheck/lint、locale parity、diff-check整条exit0。随后新增assembly缺失id不发无scope请求和离页晚响应回归；最终client全套 **31 files / 196 tests passed**、client typecheck/lint、check:contract(OpenAPI+route visibility PASS)，门户新全套 **52 files / 433 tests passed**（最终blast12在内）；client typecheck/lint、check:contract、web typecheck/lint、locale parity、diff-check全部串行执行，`bash-01c108e08da24275`整条exit0。命令为 `pnpm --filter @soymutdb/api-client exec vitest run --maxWorkers=1 && pnpm --filter @soymutdb/api-client typecheck && pnpm --filter @soymutdb/api-client lint && pnpm --filter @soymutdb/api-client check:contract && pnpm --filter @soymutdb/web exec vitest run --maxWorkers=1 && pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint && pnpm --filter @soymutdb/i18n-core check:locale-keys && git diff --check`。原428不作为当前结果。已知非失败警告为JSDOM伪元素getComputedStyle、Node localStorage与API导出dev设置warning。
- E2E spec已改为mock同release精确gene解析，再点击并断言权威chr01:12000-15000和release7/assembly。运行 `pnpm --dir e2e exec playwright test tests/blast.spec.ts --list` 时pnpm自动verify-deps尝试安装，遭只读store/sandbox拒绝（exit1），0tests不算通过；未提升权限、未绕过、未继续安装或启动服务。E2E脚本本轮未执行验收；需要在已准备依赖的授权验证环境运行。
- MiniMax只读复核36438964-3b60-4139-80af-dcf09cf86850失败无结论；备用独立只读复核9c3670ab-c7eb-4ec7-9d1f-a21a426dd524已返回，无具体范围内发现。复核核对了transport/auth重试保留显式release头、backend gene_service的release+assembly限定、返回区间校验、失败/404与异步取消/重试以及Gene search的当前release门禁。静态独立审查不是测试执行证据，JBrowse初始化问题不在该审查范围。JBrowse init/config release切换WIP仍未修，整个Task1/整体目标未关闭；没有双站制品、PG18/完整后端或浏览器验收。

## 2026-10-21 12:51 +08:00：新闻预览门户origin与令牌隔离

- 恢复时 `git rev-parse HEAD`仍为`01fc163a4c6488f97fe44ecf8f587b145cf989aa`，news modal/config无预先业务diff；在同一工作区保留前面所有未提交改动。不安装、不启动服务、不提交/推送。
- 原部署配置所有者 `apps/admin/config/config.ts` 的VITE_PUBLIC_URL不再回退admin base，而是缺配置留空。modal调用shared requireDeploymentOrigin，且只接受HTTP(S)origin；取消window.location.origin猜测。配置缺失/相对/占位/非HTTPS非localhost/非HTTP(S)时显示现有双语配置提示，禁用copy/open且不请求预览token。
- 有效配置只生成门户HTML `/news/{encodeURIComponent(slug)}?preview=...&exp=...`；不采用API响应中的JSON预览url，不把令牌发往管理端。保留noreferrer。token状态绑定articleId+slug，旧请求cleanup取消；父组件重建等价article对象不重新mint，切换文章不能套用旧token。
- 新增 `apps/admin/src/components/news-preview-modal.test.tsx` **14项**：8类缺失/无效配置、有效门户和编码/clipboard/忽略APIurl、显式localhost HTTP、等待/失败、晚到旧token/关闭、等价props不重发、config无base兜底。首次9项失败是测试双件把Alert title+description合并文本、JSDOM将import.meta.url视作非file；修正为检查alert内容和从测试cwd读取config后通过，未削弱业务条件。
- 固定Node路径与低线程、workspace PNPM_HOME：`pnpm --filter @soymutdb/admin exec vitest run src/components/news-preview-modal.test.tsx --pool=threads --maxWorkers=1 && pnpm --filter @soymutdb/admin typecheck && pnpm --filter @soymutdb/admin lint`：14 passed，exit0。
- 最终 `pnpm --filter @soymutdb/admin exec vitest run --pool=threads --maxWorkers=1 && pnpm --filter @soymutdb/admin typecheck && pnpm --filter @soymutdb/admin lint && git diff --check`：**33 files / 221 tests passed**，整条命令exit0。threads是本机工作站已记录的fork配额替代，不改仓库Vitest配置。
- 非失败JSDOM警告：CSS stylesheet解析、伪元素getComputedStyle、scrollTo未实现。未做实际浏览器/制品构建/跨域部署验证；预览接收页面原有preview/exp读取契约已读但本轮未增加后端契约。
- MiniMax只读复核 `dbff3241-3673-4e4f-b74e-6e3ccbec1553` 已收尾：原要求的fail-closed/token隔离成立，但发现子路径被origin-only helper丢弃（Medium）、取消后loading残留（Low）及LAN HTTP opt-in/构建校验/文案等建议。主代理读取build-pages-artifact.sh:32-40、react-app.tsx:47-49，确认子路径部署真实存在；不因原221测试通过而否认问题。
- 审查返修：校验origin后保留显式配置URL的pathname，去除尾斜杠，构造basePath/news；不改变shared helper的origin契约、不新增猜测fallback。effect在提前返回前清除token/error/loading，修复文章清空/关闭后残留状态；将误称dev-only的localhost注释改为shared policy显式例外。新增有/无尾斜杠子路径2例及article=null取消等待1例。
- 2026-10-21 12:58 +08:00，返修后窄测试 **17 passed**，admin typecheck/lint/git diff --check exit0；完整admin回归`bash-43fe4a8637714463`已收集：33 files / **224 tests passed**，admin typecheck/lint/git diff --check，整条命令exit0。这是返修后新证据，不把上一版221结果冒充当前全量。
- 审查建议处置：LAN HTTP放行涉及把现有显式部署opt-in传入客户端，本轮不新增可绕过HTTPS的配置，继续安全拒绝且将此环境限制列为未覆盖；缺配置时build fail-fast不采纳，因为已批准行为允许缺配置构建后显示可恢复提示，runtime仍fail-closed。clipboard复用saveError、number/string id切换额外mint列为低优先文案/效率遗留，不影响链接身份安全。整体目标仍active，BLAST/JBrowse断链/导出扩展/依赖和全线验收未完成。

## 2026-10-20 23:47 +08:00：全局搜索分页/类型筛选

- HEAD仍为设计提交 `01fc163a4c6488f97fe44ecf8f587b145cf989aa`；在原未提交工作区内续接Task3，仅改搜索路由与测试，复用已存在en/zh类型文案。无新manifest/lock/服务/存储/安装或Git写操作。
- 接上五类实体Checkbox筛选和全部类型动作；URL保留q/types/assembly/limit，query submit/筛选清游标。next只消费next_cursor+has_more，previous回访已有游标；初始深链没有历史时明确显示First回首页。结果数沿用API真实total_count，不估算页数。
- 缓存与游标作用域包含响应式release、assembly、query、types、limit和site variant。改变作用域的首个render即不使用旧cursor；resetCursor挡住URL导航异步落地前的旧值。内部目录无分页契约，不提供分页/不支持的类型筛选，仅显示说明。独立子工具页面不触发父搜索请求或因release变化被父路由导航走。
- 独立审查 `9b4d2fd8-2597-4d53-b854-1a52124400fa` 找到P2：updateTypes本地重置history时丢resetCursor，在URL清游标未落地时可能复用旧发布cursor。修复：类型动作不改history，next/previous保留resetCursor；增加延迟URL回归。最终独立复核 `785cc6c7-c333-4e48-aa75-186b5d2c81f0` 对这两个文件未发现新具体问题。均为只读审查，不算测试通过证据。
- 新测试覆盖五类型/全部/白名单、三页next/prev、尾页、初始cursor深链回首页、q/types/assembly/release重置、保留查询过滤、等待/错误重试、延迟URL竞态、子工具隔离和internal无分页；此前误用不存在common.first导致一项失败，改复用已有genes.first后通过，未以放宽断言绕过。
- 最终主代理命令（固定Node路径，`PNPM_HOME=$PWD/.ph RAYON_NUM_THREADS=1 GOMAXPROCS=2 UV_THREADPOOL_SIZE=2`）：`pnpm --filter @soymutdb/web exec vitest run --maxWorkers=1 && pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint && git diff --check`：**52 files / 428 tests passed**，整条命令exit0。包含最终搜索15项和株系页面6项，既有BLAST等门户单测也执行，但不证明尚未修正的蛋白→基因组语义正确。
- 非失败警告：JSDOM伪元素getComputedStyle未实现、Node localStorage实验警告。无测试skip被当作通过。
- 证据边界：客户端组件/已有Mock/API-client调用契约与门户全量单测、类型和Lint，不是实际API游标签名或浏览器E2E/双站制品验收。后端search契约未改变，本轮未重新跑全量后端。整体目标仍active；新闻origin、BLAST/JBrowse、导出状态扩展、依赖迭代和全线验收未关闭。

## 2026-10-20 23:39 +08:00：株系检索/分页增量

- 恢复时 TaskStartSnapshot：工作区 `/mnt/data02/T25ronglin/code/web`，分支 `fix/fullstack-stabilization-20261020`，HEAD `01fc163a4c6488f97fe44ecf8f587b145cf989aa`（设计提交；不是早期基线 SHA）。已有 API/Worker/BLAST/JBrowse/locale 和未完成检索脏改动均保留；未暂存、提交、重置或清理。当前 checkout 未设 upstream；worktree 清单还包含三个既有 detached `.validation` checkout，未操作。
- 子代理失败交接不算完成：Task3 仅留下未使用 Checkbox import，已移除；Task4 留下 mutants API/client/页面半成品，无测试与新闻预览改动。主代理接管株系部分，不把失败代理的意图算作交付。
- 行为：新增 `q` 在名称/品种/诱变方式上大小写不敏感、转义后的字面子串检索；保留 `mutagen` 精确相等和裸数组响应。新增非负 `offset`，保留公开性/删除/release/公开身份边界。页面使用 URL `q/mutagen/page`、50条分页+1条探测，上一页/下一页可达超过100条结果；查询切换重置页码、发布状态响应式更新并重置页码，初始失败可重试。未引入总数契约或新存储。
- 新增参数采用 Annotated + 普通 Python 默认值，避免既有路由直接调用测试拿到 FastAPI Query 对象。首次回归由此失败1项，修复后通过。新增123条夹具首次误用重复 name 触发既有唯一约束；只修正夹具为不同 name，不改变业务约束。
- 验证环境：Python3.15，专用测试库 `postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_test_stabilization_20261020`，PostgreSQL16（不是CI PG18）；`PYTHONPATH=$PWD OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1`。
- `.mamba-root/envs/py315/venvs/api/bin/ruff check apps/api/app/api/v1/mutants.py apps/api/tests/test_mutant_line_search.py`：exit0。
- `.mamba-root/envs/py315/venvs/api/bin/python -m pytest apps/api/tests/test_mutant_line_search.py apps/api/tests/test_mutants.py -q`：**22 passed**，1条开发配置 warning，exit0。覆盖 name/cultivar/mutagen、字面 `%_\\`、空白、精确过滤组合、公开性/删除/其他发布/缺public_id负例、offset边界、123条分页无重复无遗漏。
- 前端命令统一使用固定Node路径、`PNPM_HOME=$PWD/.ph RAYON_NUM_THREADS=1 GOMAXPROCS=2 UV_THREADPOOL_SIZE=2`：`pnpm --filter @soymutdb/web exec vitest run src/routes/mutants/index.test.tsx` **6 passed**；web `typecheck`、`lint` exit0；`pnpm --filter @soymutdb/api-client exec vitest run src/mutant-lines.test.ts` **3 passed**；api-client `lint` exit0。页面单测覆盖offset100、隐藏探测行、首尾页、筛选重置、重试、发布切换、无效深链页码。
- `pnpm --filter @soymutdb/api-client generate:api-client`、`check:contract`、`typecheck` exit0；OpenAPI/client同步且 route visibility `status: PASS`。`git diff --check` exit0（业务增量复核时）。
- 独立只读审查：MiniMax再次无收尾失败，不能作通过证据；备用独立子代理 `a2c8b45f-b51f-4ac3-a358-180f13be4d01` 对 mutants API/client/页面报告无具体问题，未代替主代理测试。
- 验证边界：这是株系检索切片的定向证据，不是全线完成。未做浏览器E2E、双站构建、PG18及全量后端回归；新闻预览、全局搜索分页、BLAST/JBrowse语义、导出状态扩展和依赖批次仍待推进。offset分页在数据并发变化时不保证快照一致性，未新增快照契约。

## 依赖候选独立复核（尚未更新依赖）

主代理于 `2026-10-20T07:35:25Z` 直接查询 npm registry metadata 的 time 字段（Node fetch，exit 0）。候选 `turbo@2.11.9` 已发布84.46小时、`@tanstack/react-router@1.170.45` 82.40小时、`postcss@8.5.31` 35.93小时，均超过24h。`@tanstack/react-query@5.104.5` 仅14.63小时、`i18next@26.5.3` 14.18小时，仍在供应链等待窗口内。纠正依赖子代理将这两项认定为“出窗”的计算错误；不得按其结论添加豁免。

源：`https://registry.npmjs.org/turbo`、`https://registry.npmjs.org/%40tanstack%2Freact-query`、`https://registry.npmjs.org/%40tanstack%2Freact-router`、`https://registry.npmjs.org/postcss`、`https://registry.npmjs.org/i18next`。这是metadata/时间验证，不是兼容性或安装验证。首批可考虑turbo/router/postcss；其他版本延后或重新确认发布年龄。

## 基线保存（完成）

- Draft PR #26：https://github.com/caoronglin/soymutdb-next/pull/26，base main，head baseline/workspace-20261020。
- 远端、本地 SHA 均为 `57e2bcdee3bab3435578997dba85cf26c3b985bc`，tree `e8bf3b626235dc4b625e35cb58279d5fbbd6759a`；612 文件、71196 行新增、15606 行删除。基线保存后 git status 为空。
- `python3 scripts/check-toolchain-pins.py`：exit 0。
- `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .mamba-root/envs/py315/venvs/api/bin/python -m pytest scripts/test_dependency_governance_contracts.py -q`：20 passed，exit 0。
- 不包含全量构建/应用/浏览器验收；基线已有 whitespace 警告原样保存。

## 后端根因复现（诊断完成，不是修复通过）

使用 PostgreSQL16 127.0.0.1:55432 上新建专用库 `soymutdb_test_stabilization_20261020`。`createdb` exit 0。一次性 UUID schema 在同一事务内创建，验证后 rollback；未修改既有业务数据。

主代理调用真实 `_resolve_mutant_line_key` → `VariantRepository.count`：插入原生主键42、名称probe-line-42、历史sha256前4字节hash709926958，同发布7。当前路径返回0；相同发布按 mutant_line_name 关联计数1。断言 actual==0 && expected==1，exit 0，确认错误发生在键空间映射，不是数据缺失。该诊断使用最小表，不是完整 HTTP/生产集成证据。

主代理对真实 `ExportRequest.model_validate` 传入 `filters.mutant_line_id="42"`，再执行路由相同 model_dump；仍得到该内部键。exit 0，确认 schema/序列化边界接受客户端内部参数。尚未修复，后续必须加入 HTTP/Worker 与公开身份负例回归。

现有 `tests/test_ablation_variant_public_filter.py` + `tests/test_variant_aggregate_perf.py` 在显式 `SOYMUTDB_TEST_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55432/soymutdb_test_stabilization_20261020`、低线程和 API315 venv 下：21 passed，1 warning（开发默认配置），exit 0。这证明旧测试没有捕获已复现的 hash/主键错配，不能作为该缺陷不存在的证据。首次未设置测试库导致6个testcontainers setup error（本机无Docker），修正运行参数后通过，未改代码以迎合环境。
