# Plan F：基准、验证、OCR、清理与最终证据实施计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` (or the repository-approved equivalent) to execute this plan task-by-task. Do not start Plan F until A0、A1、B-pre-ADR、B、C、D、E 已完成并分别通过 Oracle 复核和用户确认；本计划只定义 F 的验证、证据、清理和最终收口，不授权提前实现、迁移、依赖升级、部署或提交。

## 1. 目标、前置闸门与不变边界

Plan F 的目标是把 A0→E 的实现变成可复核、可重复、可回滚的证据包：真实数据基准、focused-to-broad 验证、公开投影安全证明、搜索/JBrowse/无 JS/可访问性证据、供应链与许可证据、打包/灾备/回滚演练、受引用保护的生成文件清理，以及最终 Oracle 简化性和可读性复核。

F **阻塞于 A0-E 全部完成**。开始前必须逐一存在并可追溯：

| 前置阶段 | 必须已有的证据 | F 的使用方式 |
|---|---|---|
| A0 | 实际 Alembic revision/schema/ORM/OpenAPI/client/worker reconciliation、迁移 rehearsal、备份恢复、旧 `Release` 证据分类、runtime/wiring 差异 | 以实际 schema 和历史为基线，不按目标模型猜测；迁移验证只重复既定链路 |
| A1 | capability matrix、typed command、三条 append-only history、`rl_audit_outbox`/`rl_task_dispatch_outbox`、hash-chain、幂等/并发/失败审计证据 | 验证权限、状态机、outbox 和审计事实不能被 OCR 或 UI 代替 |
| B-pre-ADR | 大豆+第二物种 walking skeleton、对象/制品规模、存储和 provider 观察、固定搜索上限、真实 B-pre-ADR cap 和 P50/P95 基线 | F 只验证基线未回归；不得在 F 中重新选择搜索引擎或偷偷扩大 cap |
| B | dataset/object version、ontology closure、Taxonomy/ECO mapping、license、asserted-only、diagnostic/unresolved 证据 | 验证科学身份、scope、闭包、许可证和 unresolved 阻断公开发布 |
| C | 冻结输入、manifest、allowlist schema、artifact registry、capability profile、ready marker、CAS/fencing saga、compensation/unknown、reconcile | 验证发布完整性、跨存储一致性、清理引用保护和恢复 |
| D | Internal/External Search 分离契约、签名 cursor、API/Worker/静态目录 fallback、错误和 provenance 证据 | 验证消费者体验和无权访问边界，不重复宣称 C 的构建校验 |
| E | public/admin UX、scope ledger、ontology/provenance/JBrowse 语义、第二物种端到端发布/回滚 | 验证用户可观察语义、a11y、无 JS、JBrowse 和真实业务闭环 |

任一前置证据缺失，F 的结果只能标为“未开始”，不能用旧报告中的“91/91 PASS”、`Base.metadata.create_all()`、人工截图或 OCR 结论补齐。所有新增 F 代码、脚本、类型、函数、变量、组件和测试夹具继续使用 `rl_` 前缀；框架约定、迁移名、第三方 API、环境变量、已有公共接口和数据库协议名不强行改名。新增非显然的权限、版本转换、清理保护、恢复和性能逻辑必须写简短中文“为什么”注释。

实施前在仓库声明本地技能：`skills/ontology-postgresql-control-plane/README.md`。该文件在本计划中是**实施阶段的 skill declaration 交付物**，不得把外部 skill、凭据或会话状态复制进仓库；F 文档本身不创建该文件，避免违反“只创建本计划文件”的文档任务边界。

## 2. 实际仓库命令与证据目录约定

先读取并以实际脚本为准，不臆造不存在的 review 入口：根 `package.json` 的 `review` 是：

```bash
python3 tools/code-review/review.py --project apps --output tools/code-review/reports/manual
```

它生成 `review-report.html` 和 `review-report.json`；`tools/code-review/review.py` 是仓库内确定性规则引擎，覆盖 XSS、SQL 注入、硬编码密钥、N+1 启发式、动画和 HTML5 建议。它不是 Alibaba 官方 OCR，不能替代测试、人工科研审查、SBOM、许可证或权限验证。根脚本的通用命令是 `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm build`；Web 的真实构建脚本还会运行 `vite build`、`ssg-build.ts`、`generate-samples.ts`、`gzip-compress.ts`。后端/Worker 的真实入口来自 Makefile：`make test-api`、`make test-web`、`make test-e2e`、`make smoke-test`、`make load-test`、`make stress-test`、`make backup`、`make restore BACKUP_DIR=...`、`make health`。

F 证据包应写入受版本控制的文档/报告位置或 CI artifact；运行生成物默认放在被忽略的 `tools/code-review/reports/`、`test-results/`、`artifacts/` 等目录，不能为了保留证据删除忽略规则。每份 JSON 证据必须记录 command、commit/ref、lockfile digest、环境版本、输入 manifest digest、时间、结果和 artifact 路径；不得记录 secret 值、token、cookie、完整敏感请求或 provider credential。

## 3. TDD 与 checkpoint 顺序

F 的执行顺序固定为：先写失败的验证/契约测试，再运行确认失败，再实现最小修正或补齐前置证据，再运行 focused 验证，最后扩大范围。不要先改生产实现来“让报告通过”。每个 checkpoint 必须有：输入快照、命令、机器可读结果、人工结论、失败分类、回滚/停止条件和 Oracle 复核记录。

1. **Checkpoint F0：闸门与基线冻结。** 只读确认 A0-E 证据、确认 working tree、记录 Node/pnpm/Python/Cargo/Docker/k6/Playwright 版本；无证据即停止。
2. **Checkpoint F1：focused tests。** 先测受影响领域的迁移/契约/权限/状态机/outbox/投影 schema/provider/search/JBrowse；失败时不跑 broad gate 掩盖根因。
3. **Checkpoint F2：双物种和全链路。** 在隔离环境运行数据质量、构建、发布、搜索、回滚、DR、a11y、no-JS 和权限 E2E；保存每一条 manifest digest 和 scope。
4. **Checkpoint F3：performance/load。** 使用 B-pre-ADR 已冻结 caps 和真实代表性数据，记录 P50/P95、内存、构建、恢复和移动端预算；超 cap 只产生 ADR 输入，不直接扩容或换组件。
5. **Checkpoint F4：供应链、OCR、清理。** 先生成 SBOM/license/sensitive projection 证据，再运行条件 OCR，最后做 reference-based cleanup dry-run、人工确认、最小删除和删除后复验。
6. **Checkpoint F5：最终评审。** Oracle 先做 simplification/readability review，再确认是否有需修复的确定性失败；修复后重跑受影响的 focused gate 和 broad smoke，不能以“风险接受”隐藏阻断级问题。

## 4. focused-to-broad 验证矩阵

### 4.1 阶段一：focused 合约、迁移和权限

| 证据域 | 代表文件/fixture | focused 检查与预期结果 |
|---|---|---|
| Migration/schema | `apps/api/alembic.ini`、实际 `apps/api/migrations/`、`apps/api/app/models/base.py`、A0 schema snapshot、`apps/api/tests/conftest.py` | disposable PostgreSQL 上执行真实 Alembic `upgrade head`；仅对明确可逆 revision 做 `downgrade`；再 `upgrade head`；空库重建和备份恢复成功。`create_all()` 只能作为 ORM 对照，不能作为 migration pass。任何 ORM/schema/revision 漂移进入 A0 reconciliation，不自动改 schema。 |
| Contract | `apps/api/app/main.py`、`apps/api/app/api/v1/`、`packages/api-client/src/`、各 `*.test.ts`、Admin route client | 导出 OpenAPI 与 typed client 请求/响应逐项比对；404、字段缺失、scope/digest 不一致、未知状态均 fail；前端没有后端契约的按钮必须 disabled/removed，而不是容忍 404。 |
| Permission | `apps/api/app/core/security.py`、admin routers/deps、`apps/admin/src/lib/auth-context.tsx`、Admin routes | capability matrix 对每个命令做 allow/deny matrix：未认证、错误 capability、Auditor 写入、self-approval、过期 approval、环境不匹配均拒绝并写 failure audit；UI 403 只反映后端事实，不是授权来源。 |
| State machine | A1 状态模型、approval/build/deployment history tests、Admin publication UI | 合法转移和非法转移分别有测试；`approved_for_promotion` 必须绑定完成且校验通过的 immutable final manifest；deployment approval 独立；rollback 是新 attempt，不修改历史。 |
| Outbox/audit | `apps/api/app/core/audit.py`、`rl_audit_outbox`、`rl_task_dispatch_outbox`、worker relay/task registration | 同一事务提交业务事实和两个 outbox；事务 rollback 不得制造 success；relay 重试以业务幂等键安全；`ingest`/`ingestion`、`stats` 无 worker、旧 static task 名称等已知漂移必须由 contract test 捕获并归零；hash chain/checkpoint 可重算。 |
| Physical constraints | B schema tests、科学对象/ontology/manifest fixtures | scope、namespace、assembly、Transcript parent、dataset object version、closure、license、approval binding、artifact digest、pointer generation/fencing、audit sequence 的唯一/检查约束和服务层双重校验全部通过；冻结字段普通 ORM update 被拒绝。 |

预期结果是 focused 阶段零阻断级/高风险失败；任何“仅 UI 可见”“OCR 未发现”或“旧报告已通过”都不算通过。

### 4.2 阶段二：publication、artifact、projection 和恢复 focused

代表文件为 C 阶段实际新增的 publication/manifest/artifact/provider/reconcile 模块，以及已有 `apps/web/scripts/ssg-build.ts`、`generate-samples.ts`、`gzip-compress.ts`、`apps/worker/src/soymutdb_worker/tasks/static_pages.py`、`apps/worker/src/soymutdb_worker/utils/s3.py`、`infra/nginx/conf.d/default.conf`、`infra/docker/web-nginx.conf`。逐类验证：

- 冻结输入包含 dataset/ontology/mapping/content/config/template/code/locale/timezone/sort/compressor/randomness（无随机也要声明）；同一输入重复构建得到同一 manifest、artifact digest、文件列表和排序。
- 每个公开 artifact 先过 common validation：registered ID、immutable path、content-type、size、SHA-256、manifest membership、权限、route、ready marker；再按 JBrowse random-access 或 download capability profile 验证 sidecar/Range/CORS/origin/threshold，不能把所有资源强制套用 JBrowse 条件。
- 每类 HTML/JSON/search/facet/download/JBrowse config/track/provenance/export 都用版本化 `rl_public_projection_schema` field allowlist 作为第一道边界；敏感字段扫描是 defense-in-depth。必须证明公开产物不含 internal object ID、bucket/key、internal URI、presigned URL、upload session、secret/token、unpublished diagnostic、approval identity 或 restricted policy detail。allowlist 通过而 scan 失败仍阻断 `artifact_ready`；scan 通过而 allowlist 失败也阻断。
- SBOM、SPDX/许可证清单、来源/归属、public citation、artifact digest 和 manifest digest 绑定同一 publication；`unknown/pending/restricted` 许可证不得进入 public manifest。大体量科学 binary 按 schema/capability 校验，不用文本 OCR 代替。
- Promotion 严格为 Prepare DB transaction → External CAS → Finalize DB transaction。CAS 前失败保持旧 active pointer；CAS 成功后必须 `verifying`，smoke/CDN 失败生成带 fencing 的 compensation attempt 指向 CAS-time prior verified manifest，或进入 `unknown` 并冻结后续 promotion；不把 provider 返回或 Redis task success 当 publication commit。
- 注入对象已写但未登记、manifest 已登记但对象不可读、ready marker digest mismatch、pointer/DB commit divergence、worker timeout unknown、orphan candidate 等故障；reconciler 只能按 registered artifact ID、manifest/generation/fencing/attempt 证据分类为 retry、cleanup candidate 或 unknown。active/approval/audit/legal-hold/recovery-window 可达 artifact 必须保留。

### 4.3 阶段三：search、a11y、no-JS、JBrowse 与跨浏览器

代表文件为 `apps/api/app/api/v1/search.py`、`apps/api/app/services/search_service.py`、`apps/web/src/workers/search.worker.ts`、`apps/web/src/lib/search-worker-client.ts`、`packages/api-client/src/search.ts`、`apps/jbrowse/src/{App.tsx,config.ts,deep-link.ts}`、`tests/e2e/playwright.config.ts`、`tests/e2e/search.spec.ts`、`tests/e2e/accessibility.spec.ts`、`tests/e2e/genes.spec.ts`。

- Internal Search 只读 manifest-backed published shards，固定 exact ID→ID prefix→exact alias→title→summary/body rank tiers、tie-breaker、最大 shard/doc/timeout/limit；签名 cursor 绑定 manifest digest、scope、canonical query/filter/sort/schema/provider/limit。manifest 变化、scope 变化或 digest 不匹配返回明确 invalidated。
- Worker 失败、索引 checksum/config/schema mismatch、JS 禁用、API 暂时不可用时，按契约回退 Internal API 或固定 publication/dataset/version 的静态 directory/index；不能主线程全量过滤、读取 ORM、暴露未公开字段或把 external result 当 local result。External Search 使用独立 route、adapter、cache、limit、timeout/circuit-breaker、provenance，失败不影响 local result。
- public `rl_scientific_context_bar`/scope ledger 显示 Species/TaxID/Assembly/Dataset/Publication、scope_type、适用 levels、unavailable/not-applicable、canonical URL 和 manifest digest；不能默认填充不适用的 assembly/dataset。
- JBrowse launch summary 必须 release-pinned，显示 assembly、dataset/publication、config/track version、digest 和 capability 缺失项。验证实际 adapter/format/origin 所需的 Range、CORS、sidecar 和 digest；不得切换到其他 release，也不得把 JBrowse 当 provenance store。
- Playwright 以真实 `tests/e2e/playwright.config.ts` 的 chromium/firefox/webkit/mobile-chrome 项目运行；重点覆盖键盘 focus、`aria-live`、heading/lang/labels/button names、44px public/36px compact-admin target、reduced motion、缩放、移动卡片、图表文本替代、403/stale/error/empty/permission/preview/deprecated。现有 accessibility 测试中“skip link 可选”和多个结果“if visible”只能作为遗留基线；E 阶段契约要求的关键路径必须改成确定性断言后再算 pass。

## 5. broad 验证、数据质量和真实双物种证据

focused 通过后，使用 B-pre-ADR 选定的大豆和第二物种相同 fixture 形状、不同 namespace/assembly/scope 的最小真实或受控数据做完整 walking skeleton：导入→diagnostics→dataset object version→ontology assertions→license→manifest→SSG/search/download/JBrowse→publication→rollback。验证：

1. Gene/Transcript identity 不因相同 local string、species 或 assembly 静默合并；Transcript parent scope 一致；冲突进入 unresolved queue。
2. ClickHouse variant facts 仍由 dataset/object version 和 publication evidence 绑定；不得把首阶段 ClickHouse 全量搬进 PostgreSQL。
3. ontology closure 中 relation/predicate、parent/replacement/xref、TaxID、ECO、annotation source 全部来自冻结 release set 或带 URI/digest/version/license 的 immutable external reference；缺失项阻断 public approval，但保留原始输入和 diagnostic。
4. asserted facts 与 inferred facts 分开；首阶段不能把推理结果伪装成公开事实；obsolete/do-not-annotate/consider 语义和 replacement candidate 可追溯。
5. 许可证 inventory、SPDX/URL/归属/再分发状态与 public projection 一致；restricted source 只留 admin evidence，不出现在 public manifest。
6. 页面、导航、sitemap、search shards、downloads、JBrowse config/track、citation 均引用同一 publication manifest digest；第二物种发布和补偿回滚均可用同一证据重放。

## 6. B-pre-ADR cap、性能和负载证据

F 不自行发明容量阈值。B-pre-ADR 形成的 caps 必须在 F 的证据表中逐项引用并冻结：最大 shard 数、最大文档数、单次 `limit`、请求 timeout、Worker 内存上限、压缩大小、解压大小、构建时长、发布时长、CDN cache window、RPO/RTO。每个 cap 记录数据集、设备/浏览器、代码/manifest digest 和为何采用该边界的中文注释；为什么：没有真实数据和消费端测量，扩大上限会把安全边界误当成性能优化。

命令按可用条件执行：

```bash
# 已安装依赖、API/Worker 可运行时：
make test-api
pnpm --filter @soymutdb/web test
pnpm --filter @soymutdb/web typecheck
make load-test BASE_URL=http://localhost:8000
make smoke-test BASE_URL=http://localhost:8000
make stress-test BASE_URL=http://localhost:8000

# Playwright 服务已启动且 E2E_BASE_URL 指向可访问发布预览时：
E2E_BASE_URL=http://localhost:8080 make test-e2e

# 已安装 pnpm 依赖、Rust toolchain 和各 workspace 条件满足时：
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm --filter @soymutdb/jbrowse build
pnpm --filter @soymutdb/admin build:desktop
pnpm build:core
```

`tests/load/api-load.js` 当前明确是 20→50 VU、p95<2000ms、错误率<1%；`tests/load/variant-stress.js` 是最高 100 VU、p95<3000ms、错误率<2%；它们只能作为现有 API/ClickHouse 压力基线，不能替代 B-pre-ADR 对 Internal Search 的 cap 证明。新/更新的 F benchmark 必须按 endpoint、scope、species、manifest digest、cold/warm cache、Worker load/query、mobile/desktop 分开输出 P50 和 P95，不能只报平均值或全局 p95。至少记录：静态 page TTFB、Internal API、Worker index load/query、External Search timeout、JBrowse launch、SSG build、artifact validation、promotion、rollback 和 restore 的 P50/P95；同时记录 error rate、peak memory、long task、LCP/INP/CLS、cache hit、shard bytes、gzip ratio 和 cap violation 数。超过 cap 时预期结果是 bounded error/API/static-directory fallback 和 ADR 输入，不是静默降级为无界扫描。

## 7. Alibaba Open Code Review 与确定性门禁

仓库实际存在的 `pnpm review` 必须每次 F broad gate 运行并保存 JSON：

```bash
pnpm review
python3 tools/code-review/review.py --project . --output tools/code-review/reports/full
```

前一条扫描 `apps`，后一条扫描全仓库；两者均是 repository-local deterministic rule engine。对启发式 N+1、HTML5 suggestion 等结果必须逐项人工 triage，不能无条件以“false positive”关闭；安全、projection、secret、SQL、路径和权限问题必须有代码/测试证据。`pnpm review` **不是** Alibaba Open Code Review，不得用它的 HTML/JSON 结果冒充官方 OCR 证据。

### 7.1 固定的官方版本和可用性闸门

Alibaba Open Code Review 的接受协议固定为 **`@alibaba-group/open-code-review@1.7.7`**，不得使用范围版本、`latest`、自动更新版本或未记录版本的 `ocr` 可执行文件。该版本是本计划的 exact-version pin；未安装时不安装、不修改 lockfile、不授权实施者自行补依赖。

官方 OCR 只有在以下条件全部满足时才可运行：

1. **Git repository/full history/merge-base：** `git rev-parse --is-inside-work-tree` 返回 `true`；目标 commit、`origin/main`（或受信任 CI 明确指定的 base ref）存在；浅克隆被证明不是完整历史（例如 `git rev-parse --is-shallow-repository` 返回 `true`）时拒绝；`git merge-base "$BASE_REF" "$HEAD_SHA"` 成功且结果可记录。
2. **Trusted checkout：** checkout 来自受信任的受保护分支、受信任 merge queue 或受信任 CI 构建产物；不能是 fork/untrusted PR 直接提供的 checkout，不能执行其 package install script、test script、build hook 或任意仓库脚本来获取凭据。untrusted PR 只能在无凭据 job 生成隔离 diff，或由受信任服务读取 diff 数据。
3. **Controlled CI provider credentials：** provider credential 只由受控 CI secret store 注入，job 明确标记为 trusted/protected environment，secret 不通过仓库文件、PR 变量、命令参数、日志或 artifact 传递；本地开发机、fork job、未保护的 PR job 和用户粘贴的 token 均不满足条件。
4. **Exact official CLI/package：** CI 中的 `ocr` 必须由固定的 `@alibaba-group/open-code-review@1.7.7` 提供，并能通过 package metadata、CLI version 输出和实际 executable path 三者交叉验证；任一无法证明 exact version，均不得运行 review/scan。

安全 availability check 只在**受信任 CI 的 gate job 中、尚未执行 OCR 前**运行；示例必须将所有条件作为 fail-closed 检查，不得把缺少条件解释为“暂时可试”：

```bash
# 仅在受控、受保护的 CI gate job 中执行；不安装任何包，不打印 secret。
set -eu

test "${CI_TRUSTED_CHECKOUT:-false}" = "true"
test "${CI_PROTECTED_ENVIRONMENT:-false}" = "true"
test "${OCR_PROVIDER_CREDENTIALS_AVAILABLE:-false}" = "true"
test "${OCR_NO_UPDATE:-}" = "1"
test "$(git rev-parse --is-inside-work-tree 2>/dev/null)" = "true"
test "$(git rev-parse --is-shallow-repository 2>/dev/null)" = "false"
BASE_REF="${BASE_REF:-origin/main}"
HEAD_SHA="${HEAD_SHA:-$(git rev-parse HEAD)}"
git rev-parse --verify "$BASE_REF^{commit}" >/dev/null
git rev-parse --verify "$HEAD_SHA^{commit}" >/dev/null
MERGE_BASE="$(git merge-base "$BASE_REF" "$HEAD_SHA")"
test -n "$MERGE_BASE"

command -v ocr >/dev/null
OCR_PATH="$(command -v ocr)"
test -x "$OCR_PATH"
OCR_VERSION="$(ocr --version 2>/dev/null)"
case "$OCR_VERSION" in
  *"1.7.7"*) : ;;
  *) exit 1 ;;
esac
```

只有上述 availability check 全部成功后，才允许执行 exact-version verification。verification 必须证明当前 CLI 的 package metadata 为 `@alibaba-group/open-code-review` 且版本精确为 `1.7.7`；不能只匹配任意输出中的 `1.7.7`。以下示例仍只适用于已满足全部前置条件的 trusted CI，并将版本检查结果写入不含 secret 的 JSON：

```bash
# 仅在上一段 availability check 成功后执行；不执行 npm/pnpm install。
set -eu
EXPECTED_PACKAGE='@alibaba-group/open-code-review'
EXPECTED_VERSION='1.7.7'
OCR_PACKAGE_JSON="$(node -p 'require.resolve("@alibaba-group/open-code-review/package.json")')"
OCR_PACKAGE_NAME="$(node -p 'require(process.argv[1]).name' "$OCR_PACKAGE_JSON")"
OCR_PACKAGE_VERSION="$(node -p 'require(process.argv[1]).version' "$OCR_PACKAGE_JSON")"
test "$OCR_PACKAGE_NAME" = "$EXPECTED_PACKAGE"
test "$OCR_PACKAGE_VERSION" = "$EXPECTED_VERSION"
test "$(ocr --version 2>/dev/null)" = "$EXPECTED_VERSION"
node -e 'const fs=require("fs"); const p={package:"@alibaba-group/open-code-review",version:"1.7.7",cli_path:process.env.OCR_PATH,base_ref:process.env.BASE_REF,head_sha:process.env.HEAD_SHA,merge_base:process.env.MERGE_BASE}; fs.writeFileSync("artifacts/ocr-version.json", JSON.stringify(p,null,2)+"\n")'
```

在当前非 Git 工作区，上述条件不满足，因此本次计划的官方 OCR 状态必须保持：**`not run — prerequisite unavailable`**。不得通过初始化 Git、创建临时历史、伪造 `HEAD_SHA`、使用 `pnpm review` 替代、复制 provider credential 或安装 package 来改变该状态。

### 7.2 只有前置条件全部满足时的官方 JSON 命令

以下是 accepted protocol 的 exact commands；它们只能在前述 availability check、exact-version verification、trusted checkout、protected CI credentials 和有效 merge-base 全部成功后运行。所有输出必须是 JSON，目标目录必须是受控 CI artifact 目录；输出只能包含 commit/ref、版本、模型/provider 名称、问题 severity、修复引用和结果摘要，不得包含 secret、token、cookie、provider credential、完整敏感请求或不受信任 PR 代码内容。

```bash
# 仅在全部 prerequisites 已成功时运行；固定 exact package/CLI version，禁止自动更新。
OCR_NO_UPDATE=1 ocr llm test --format json > artifacts/ocr-llm-test.json
OCR_NO_UPDATE=1 ocr review --from "$BASE_REF" --to "$HEAD_SHA" --format json --audience agent > artifacts/ocr-review.json
OCR_NO_UPDATE=1 ocr scan --path apps/api --format json > artifacts/ocr-scan-api.json
OCR_NO_UPDATE=1 ocr scan --path apps/web --format json > artifacts/ocr-scan-web.json
OCR_NO_UPDATE=1 ocr scan --path apps/admin --format json > artifacts/ocr-scan-admin.json
OCR_NO_UPDATE=1 ocr scan --path infra --format json > artifacts/ocr-scan-infra.json
```

如果 Git repo/full history/merge-base、trusted checkout、受控 CI provider credentials、exact official package/CLI version 或 provider health 任一缺失，结果统一记录为 **`not run — prerequisite unavailable`**，并记录缺失条件名称但不记录 secret。CI 必须在 credentialed job 中拒绝 untrusted PR checkout；即使 review 只读，也不能执行 untrusted PR 的安装、测试、构建或 hook。OCR 不能替代 deterministic gates：`pnpm lint/typecheck/test/build`、pytest、Alembic rehearsal、contract/permission/state-machine/outbox、Playwright、k6、SBOM/license/sensitive projection、人工科学审查和 recovery evidence 均必须独立通过。

## 8. SBOM、许可证和敏感投影证明

在 packaging gate 中为 Web/Admin/JBrowse、API、Worker、Rust、Docker image、SSG/static bundle、search/download/JBrowse artifact 生成 SBOM；优先使用仓库现有 lockfiles 和实际构建输入，不为 F 强行升级依赖或引入新生成器。每份 SBOM 绑定 package lock digest、镜像 digest/commit、构建工具版本和 publication manifest digest。许可证证据至少覆盖根 `CC-BY 4.0` database content、`MIT` code、Python packages、pnpm workspace packages、JBrowse/React/字体/运行时和对象来源；未知、受限或需要人工确认的 license 阻断 public release，不以“依赖存在于 lockfile”代替许可判断。

对每个 `rl_public_projection_schema` 做 positive/negative fixture：允许字段完整输出；内部 ID、bucket/key、internal URI、presigned URL、upload ID、token、secret、unpublished source/diagnostic、approval identity、restricted detail 必须在构建前或 schema validation 中失败。scan 报告保留字段名、artifact digest、schema version、发现数量和修复/阻断结果，不保留敏感值。二进制科学 payload 使用登记的 schema、format、digest、size、content-type 和 capability profile 证明，不能用 OCR 文本扫描冒充结构完整性。

## 9. Packaging、rollback、DR 与发布后观察

打包必须遵循：approved inputs → frozen manifest → Web SSG/Admin/API/Worker/Rust 各自构建 → tests → SBOM/license/projection evidence → checksums → final artifact manifest → preview smoke → publication approval → deployment approval → Prepare/CAS/Finalize。每个制品记录 commit、lockfile hash、toolchain、SHA-256、manifest digest、capability profile、适用 scope 和 prior verified rollback target；发布器不从工作区当前文件读取，失败制品隔离且不能覆盖 immutable path。

恢复演练在 disposable 或隔离环境执行并记录实际 RPO、RTO、最大 CDN cache window、artifact reachability retention、备份位置和恢复耗时：PostgreSQL backup → restore；对象存储 manifest/pointer/ready marker restore；CDN/static entry digest verification；Internal Search manifest-backed resource rebuild/read；JBrowse config/track/read-range；Admin audit/history continuity。恢复后必须证明 PostgreSQL ledger、public pointer、manifest、static entry、search 和 JBrowse 均指向同一 digest。rollback 是新 deployment attempt，绑定已验证旧 manifest 和 CAS-time prior verified manifest；不改旧 approval/build/deployment/audit event。

可用的实际备份命令是 `make backup`、`make backup-full`，恢复需明确 `make restore BACKUP_DIR="/path/to/backup.tar.gz"`；若 Docker、PostgreSQL、MinIO、ClickHouse 或目标备份不存在，精确标记 conditional skip，不声称 DR passed。发布后观察至少包括 pointer/ready/CDN digest mismatch、artifact unreadable、unknown saga、orphan candidate、audit relay lag、outbox backlog、search cap violation、Worker memory/error、External provider timeout、JBrowse capability failure、HTTP 4xx/5xx 和 a11y regression；任何 observation 不得直接改写业务成功事实。

## 10. 安全的 reference-based cleanup

清理只处理已生成、陈旧或明确无引用的候选文件，不删除用户文档、设计/研究/计划、audit/legal-hold 材料、当前或可回滚 publication、registered artifact、备份和仍可达的证据。候选扫描必须先列出路径、大小、mtime、digest、来源、generation、manifest/pointer/approval/deployment/audit/recovery/legal-hold 引用和 grace period；删除条件是：无 active manifest 引用、无 pointer intent/deployment attempt 引用、无 approval/audit/legal hold/recovery window、已过 grace period、不是用户文档、不是当前 lockfile/配置/源码、且已有可验证清单和回滚副本。任何无法判断的路径标为 `unknown`，永不自动删除。

优先复用已有 `pnpm clean` 和 Makefile `clean` 的显式目标，但不得直接运行 `make clean-all`：它会删除 `pnpm-lock.yaml`，不符合本计划的锁文件保护。现有 `Makefile clean` 也包含 shell `find`，因此实施者必须先 dry-run 列出目标，再按引用分析逐项删除，不能把“命令成功”当安全证明。`dist/`、`build/`、`target/`、coverage、Playwright/test-results、临时 OCR/manual reports、未登记失败 artifact 可在确认后清理；`artifacts/.gitkeep`、用户报告、`docs/`、当前 publication、rollback target、audit/法律保留对象必须保留。删除后重新运行 manifest reachability、`pnpm review`/projection scan、build smoke、pointer/search/JBrowse digest check；如任一引用或 digest 变化，立即停止并恢复清单中的文件。

## 11. Final Oracle 简化性与可读性复核

最后 Oracle review 不是再次设计架构，而是逐文件确认：是否引入无测量的新服务/搜索集群/图数据库/升级；是否重复实现 C 的 projection/provider validation 和 D 的 consumer fallback；是否把 Redis、OCR、Worker、JBrowse 或 search index 当 authority；是否把普通删除、downgrade、rollback 或审计状态覆盖写成不真实的恢复；是否存在可合并的重复 adapter/check、过宽接口、隐式最新版本、模糊 `unknown`、仅靠颜色/按钮文案的状态、缺少中文 why-comment 或不符合 `rl_` 的新增自有标识。

Oracle 输出必须逐项给出 `keep`、`simplify`、`fix-before-close` 或 `defer-with-ADR`，并引用文件、测试和 JSON evidence。`fix-before-close` 只允许在修复后重跑受影响 focused gate；性能超过 cap、需要新 runtime 或无法证明 provider 语义时必须形成独立 ADR，不在 F 内扩大范围。计划关闭条件：A0-E gate evidence 完整、focused-to-broad matrix 通过、双物种同 digest/rollback 证据存在、caps 与 P50/P95 可复现、SBOM/license/projection 通过、OCR 按条件诚实记录、cleanup 有引用清单且未伤及保留对象、DR/RPO/RTO 证据通过、Oracle simplification/readability review 无 blocking finding。整个过程不自动提交、合并、推送或创建 PR。

## 12. 计划自审

- 本计划只新增目标路径所要求的文档，不修改其他文件。
- 计划明确阻塞 A0-E，并保留 A0 观察性边界、B-pre-ADR cap、C/D 验收分工和 PostgreSQL/CAS/fencing authority。
- 已检查根 `package.json`、Makefile、真实 `tools/code-review/review.py`、Playwright、k6、API/Worker/Web/Admin/JBrowse package scripts、schemas/models/tests、build/ignore 配置后再命名命令；已将 Alibaba OCR 固定为 `@alibaba-group/open-code-review@1.7.7`，并将所有官方命令置于 Git/full-history/merge-base、trusted checkout、受控 CI credentials、exact CLI/package 和 provider 可用性全部满足的 conditional gate 下。
- 已覆盖 migration、schema、contract、permission、state machine、outbox、artifact、search、a11y、no-JS、JBrowse、performance/recovery、SBOM/license/sensitive projection、cleanup、packaging/rollback/DR 和最终 Oracle 简化性复核。
- 已规定 JSON evidence、当前非 Git 工作区保持 `not run — prerequisite unavailable`、untrusted PR credentialed CI 隔离、无 secret artifact、OCR 不替代 deterministic gates、`rl_` 命名、中文 why-comments、TDD/checkpoint 顺序以及不自动提交。

**文件路径：** `docs/superpowers/plans/2026-07-19-f-verification-ocr-cleanup-implementation-plan.md`
