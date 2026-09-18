# SoyMutDB 第二阶段优化 —— 主计划（Master Roadmap）
## 前端 · 性能/并发 · 检索 · 公众数据库 · 脏代码清理

> **面向执行者：** 本文件是**路线图与跨阶段契约**，不含任务细节。任务在五份子计划里：
>
> | 阶段 | 子计划 | 内容 | Wave |
> |---|---|---|---|
> | **Phase 1** | `2026-09-15-phase-1-baseline-security-plan.md` | 收口门 + 安全与部署遗留 | W-1、W0、W1 |
> | **Phase 1.5** | `2026-09-15-phase-1.5-capacity-baseline-plan.md` | **优化前**容量基线（Gate-0） | W1.5 |
> | **Phase 2** | `2026-09-15-phase-2-frontend-static-plan.md` | 前端与静态性能 | W2 |
> | **Phase 3** | `2026-09-15-phase-3-search-public-db-plan.md` | 检索与公众数据库 | W3 |
> | **Phase 4** | `2026-09-15-phase-4-runtime-capacity-plan.md` | 同参数复测 + Gate-1 + 治理 | W4、W5 |
>
> （全部位于 `docs/superpowers/plans/`）
>
> 执行前必须先读 `AGENTS.md` 与 `docs/dev/database-core-contract.md`。
> **不要**在任务外做无关重构；**不要**提交、暂存或回滚他人已有改动。
>
> **上一阶段：** `docs/superpowers/plans/2026-09-15-portal-security-ux-perf-optimization.md`

---

## 0. 修订记录

### v4（第三次审计后）

第三轮审计判定 **72/100 · No-Go**，列出 6 项阻塞、12 项严重、6 项一般。本版逐条处置：

| # | 三轮审计问题 | 处置 |
|---|---|---|
| B1 | C13 被自己的负向示例触发 | 负向示例移入脚本单元测试；文档内不再出现字面量 |
| B2 | Gate-0 时序颠倒（P1/P2 在 Phase 4，优化已先做完） | **新增 Phase 1.5**，P1/P2 移出 Phase 4，形成真正的优化前基线；Phase 4 只做同参数复测 |
| B3 | 应用层 60/min 与边缘 100 r/s 冲突；`benchmark_mode` 变量不一致 | S-2 拆配置（`public_read_*` / `write_*` / `login_*`），应用匿名读上限 ≥ 边缘；冻结 `benchmark_mode` + `rate_limit_enabled` 两开关 |
| B4 | F5/F7 循环依赖（F5 用 F7 才创建的脚本） | **F7 并入 F5**，门禁与修复同任务（先红后绿） |
| B5 | P3 只优化回环 nginx，默认公网路径（Tunnel）未覆盖 | FZ-14 改为 **`tunnel-origin` 与自建 nginx 共用缓存片段**，覆盖真实生产入口 |
| B6 | Phase 2 DoD 要求 lint 0/0，但 C2 在 Phase 4 | Phase 2 DoD 改为「不高于基线 94 且不增长」 |
| S7 | S-0 镜像引用数量错误、CI 未接线 | 明确 **6 个 Compose 引用**；fixture helper 内聚到 `compose_acceptance_run()` |
| S8 | C4 用 `HEAD:` 验证暂存区 LFS 指针 | 改用 `git show :path` |
| S9 | S-7 负向测试端口全错、未处理 `gaierror` | 新增 `scripts/check_mcp_network_isolation.py`，按真实端口表逐一断言 |
| S10 | F0 未参数化，无法分别测双产物 | 增加 `PERF_ARTIFACT_ROOT` / `PERF_PORT`；定义 INP 交互动作 |
| S11 | F5 的 `--unicodes='*'` 抵消子集化；工具未钉版本 | 删除该参数；`fonttools` 钉版本 |
| S12 | F8 未覆盖 admin/jbrowse 的 `_headers` 与 nginx | F8 Files 补齐三个 `_headers` + 三份 nginx 配置 |
| S13 | R1 的 UNIQUE 索引忽略 assembly 作用域（违反数据契约） | 冻结为 `(assembly_id, upper(accession))`；别名同查 assembly 作用域 |
| S14 | R4 超时后重跑全部 adapter，等待翻倍；Files 缺 models.py | 改为「取消未完成 + 收集已完成」，禁止重发；补 Files；wall-clock 断言 |
| S15 | D9 现有 MV 无法产出 `uniqExact` 口径 | 新增 AggregateFunction 状态列 MV，或保留独立查询 + 缓存；Summing 表必须 `sum(cnt) GROUP BY` |
| S16 | P1 实为优化后基线 | 同 B2 |
| S17 | Gate-1 的 300ms/60% 是无依据魔法值（生产告警是 1s） | 改为**按端点类别的 SLO**，SLO 由 Phase 1.5 基线推导并登记 |
| S18 | P6 的 `py-spy` 在 API 镜像不可用（无 py-spy + `cap_drop: ALL`） | 专用 profiling override：临时镜像 + 仅基准环境加 `SYS_PTRACE`，不进生产拓扑 |

**一般问题处置：**

| # | 问题 | 处置 |
|---|---|---|
| G1 | W-1 产物哈希只覆盖两个 `index.html` | 生成**全树**排序 `SHA256SUMS` |
| G2 | S-6 「migrate 或 one-shot」未冻结 | 冻结为独立 `bootstrap-admin` one-shot 服务 |
| G3 | S-10 未用 fixture helper | 改用 `compose-fixture-env.sh` |
| G4 | D2 把 `stats/*` 归入分页类别（部分无分页参数） | 门禁只枚举**真正的列表端点** |
| G5 | C3/F8 可能重复改 nginx | F8 定义行为（Phase 2），C3 只做结构去重且输出**字节等价**（Phase 4） |
| G6 | 文件所有权表把 P4 标成 Phase 3 | 修正为 Phase 4 |

### v3（第二次审计后）

新增 W-1 收口门、S 组前移、压测拆分、删除事实错误的 R6、重写 P3、Rust 降级为 ADR、
D4 拆五层、冻结全部占位符。详见各子计划的 §0。

### v2（第一次审计后）

修正 v1 的 10 条不可执行命令、Wave 顺序冲突、Rust 无法部署、隐私矩阵层级不足等。详见 Phase 1 §0。

### v1

初版（`docs/superpowers/plans/2026-09-15-portal-security-ux-perf-optimization.md` 的后续）。

---

## 1. 阶段目标与非目标

### 目标

1. **前端优化**：首访传输字节从 5.7 MB（raw 预缓存）压到 ≤1.2 MB；删除 13 MB 未引用字体。
2. **性能与并发**：建立**可比较的优化前基线**；先做索引/缓存/连接层优化；
   只在数据证明 Python 进程是瓶颈时才讨论 Rust。
3. **检索优化**：索引先取证后建；排名语义与 `match_type` 一致；检索可观测且不泄露查询内容。
4. **公众数据库**：匿名读在**真实生产入口**（Tunnel）也可缓存；配额分级；隐私矩阵五层全绿。
5. **脏代码清理**：死代码、重复配置、仓库垃圾、lint 告警、文档漂移清零。

### 非目标

- **不做全量 Rust 重写**；Rust 实现**不在本阶段范围内**（只产出 ADR）。
- 不改 `public_id` / `internal_id` 契约，不改 v4/v5 装配体语义，不改发布状态机。
- 不更换 React / Ant Design / TanStack / ClickHouse / PostgreSQL 技术栈。
- 不新增业务功能。
- 不对 `.cnb.yml` / `.github/workflows/*` 增加逻辑。
- **不削弱任何安全扫描换绿灯**。
- **不做 Git 历史重写**（破坏性，需单独确认）。

---

## 2. 冻结决策登记表

> 任何修改必须在本表登记并附理由。执行期不得重新打开「二选一」。

| ID | 决策 | 冻结值 | 理由 |
|---|---|---|---|
| FZ-1 | 迁移编号 | **`0037`**（索引）、**`0038`**（预聚合状态列，若 D9 需要） | 当前 head 为 `0036` |
| FZ-2 | 限流策略与开关 | 见 §2.1 | 修复 60/min 与 100 r/s 的冲突 |
| FZ-3 | S-4 安全头权威 | nginx `proxy_hide_header` 隐藏上游同名头，再发唯一规范值；API 保留 Middleware | 真正消除重复，且保留直连 API 纵深 |
| FZ-4 | S-7 MCP 网络 | `mcp-proxy` / `mcp-api` / `mcp-ratelimit` 三条专用网络 | 移除 `default` 后必须显式给出 Redis 通路 |
| FZ-5 | S-9 豁免格式 | `.trivyignore.yaml` 结构化（`id` / `statement` / `expired_at`） | 可审计、会过期 |
| FZ-6 | C4 二进制治理 | Git LFS（`ui-r/*.pdf`、`ui-r/*.pptx`） | 仓外存储在无人值守时不复现 |
| FZ-7 | 字体路径 | `./assets/fonts/...`（相对 `src/index.css`） | `../assets/fonts/` 指向不存在的 `apps/*/assets/fonts/` |
| FZ-8 | 字体子集化语料 | GB2312 一级常用字（3755）+ ASCII + 仓库实际 CJK 字符；**禁止 `--unicodes='*'`** | 后者会抵消子集化 |
| FZ-9 | R2 排名顺序 | `exact > curated alias > prefix > substring`；游标 `rank` 保持 3/2/1 | 与现有 `case()` 和 `MatchType` 一致 |
| FZ-10 | R4 联邦检索 | 同步单响应 + **6s 硬墙钟**；超时源标 degraded；**禁止重发** | 不改传输协议，且不把 6s 翻倍 |
| FZ-11 | R8 无 release 的 suggest | **503 `release_context_unavailable`** | 空列表会被误读为「无结果」 |
| FZ-12 | D2 分页上限 | 仅对**真实列表端点**分类：检索 50 / 实体列表 200 / 内部管理 100；**聚合端点不纳入** | `stats/*` 多数无分页参数 |
| FZ-13 | D6 区域查询预算 | span ≤10 Mb；`max_results` ≤10000；timeout 10s；**422 `region_query_too_large`** | 数值由 Phase 1.5 复核一次后固化 |
| FZ-14 | P3 缓存落点 | **`tunnel-origin` 与自建 nginx 共用缓存片段**（覆盖真实生产入口）；Cloudflare Cache Rules 仍不在范围 | 见 §2.2 |
| FZ-15 | P4 排序契约 | CH 顺序 `(chromosome, position, variant_id)`；游标携带 `chromosome`；API 字典序，UI 用 `Chromosome.order` | 匹配排序键前缀，避免 schema 变更 |
| FZ-16 | C5 缓存收敛范围 | 只统一 **key builder + 观测口径**，不统一失效语义 | 四处失效语义差异是设计意图 |
| FZ-17 | Gate-1 判据 | 见 §5：**按端点类别的 SLO**（由 Phase 1.5 推导）+ CPU < 60% + 错误率 < 1% | 300ms 魔法值无依据（生产告警为 1s） |
| FZ-18 | 字体门禁归属 | `check_font_assets.py` 由 **F5 创建**（合并原 F7），先红后绿同任务 | 消除 F5/F7 循环依赖 |
| FZ-19 | P6 profiling 环境 | 专用 override：临时镜像 + `SYS_PTRACE`，仅基准环境，不进生产拓扑 | API 镜像无 py-spy 且 `cap_drop: ALL` |

### 2.1 限流配置（FZ-2）

| 配置项 | 默认值 | 作用域 | 后端不可用时 |
|---|---|---|---|
| `rate_limit_enabled` | `True` | 总开关 | — |
| `benchmark_mode` | `False` | 仅 `app_env != prod` 可置 `True` | — |
| `public_read_rate_limit_per_minute` | **6000**（=100 r/s） | 匿名 GET | **fail-open** |
| `write_rate_limit_per_minute` | 120 | 写操作 | **fail-closed** |
| `login_rate_limit_window` / `_max` | 60 / 10 | `/auth/*` | **fail-closed**（复用 `core/ratelimit.py`） |

**不变量：**
1. `public_read_rate_limit_per_minute` **不得低于**边缘 `limit_req` 的等效速率
   （边缘 100 r/s × 60 = 6000/min），否则应用层成为实际瓶颈，边缘配置失去意义。
2. 关闭限流需要 `benchmark_mode=True` **且** `rate_limit_enabled=False` **且** `app_env != "prod"`；
   生产环境出现任一即 **fail-fast 启动失败**。
3. `/health`、`/metrics` 豁免。
4. 限流键使用**可信对端 IP**（与 S-1 同源）。

### 2.2 缓存落点（FZ-14）

**问题：** 默认公网入口是 `cloudflared → tunnel-origin → API`，
而 v1–v3 的 P3 只在自建 nginx（`infra/nginx/conf.d/default.conf`）启用 `proxy_cache` ——
真实公网用户完全绕过它。

**冻结方案：**

| 层 | 落点 | 覆盖 |
|---|---|---|
| 主 | **`infra/nginx/cloudflare-tunnel.conf`（tunnel-origin）启用 `proxy_cache`** | 默认公网生产路径 |
| 主 | `infra/nginx/conf.d/default.conf`（自建 nginx）启用同一片段 | 自建/内网路径 |
| 共用 | 抽 `infra/nginx/conf.d/public-cache.inc`，两处 `include` | 单一来源，与 C3 的结构去重对齐 |
| 应用 | 低成本 ETag（304 不落库） | 边缘未命中时的兜底 |
| 明确不做 | Cloudflare Cache Rules / IaC | 无 IaC 且本机不可测；此时不再是唯一手段 |

**约束：** 两处 `proxy_cache_key` 必须一致，含 `site_variant` + 端点级 version token + 规范化查询参数；
带 `Authorization`/Cookie 永不进共享缓存。

---

## 3. 前置门：W-1（未通过则任何阶段不得开始）

| 子任务 | 判据 |
|---|---|
| **W-1.1 上一阶段收口** | 工作树干净；上一阶段 DoD 无未解释未勾选项；关键文件已在提交历史中 |
| **W-1.2 工具链** | Node `v24.19.0`；`pnpm exec turbo --version` 可用；`scripts/check-toolchain-pins.py` 通过；git-lfs 就绪（仅 C4 需要） |
| **W-1.3 基线固化** | `docs/ops/baseline-2026-09-15-v2.md` 入库；**只跑已存在的命令**；产物**全树** `SHA256SUMS` |

**W-1.3 允许执行的命令集合（白名单）：**

```text
V1  node --version
V2  pnpm install --frozen-lockfile
V3  pnpm exec turbo run lint --force
V4  pnpm typecheck
V5  pnpm test
V6  VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=... VITE_JBROWSE_BASE_URL=... pnpm --filter @soymutdb/web build:sites
V7  bash scripts/check-bundle-size.sh apps/web/dist/external/assets
V8  du -sh apps/web/dist/external
V9  SW 预缓存清单解析（内联 node 命令，见 Phase 2 F2）
V10 python3 scripts/check_nginx_security_headers.py
V11 python3 scripts/check_artifact_headers.py
V12 SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts
V13 bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
V14 bash scripts/smoke.sh --profile static --static-dir apps/web/dist/internal
V15 bash scripts/verify-frontend-artifacts.sh
V16 apps/api/.venv/bin/python -m pytest scripts/test_ci_job_contracts.py \
      scripts/test_dockerfile_contracts.py scripts/test_site_artifact_isolation.py \
      scripts/test_supply_chain_contracts.py scripts/test_production_compose_contract.py -q
V17 python3 scripts/check-toolchain-pins.py
V18 apps/api/.venv/bin/python -m pytest scripts/test_cloudflare_tunnel_contract.py -q
V19 apps/api/.venv/bin/python -m pytest scripts/test_development_compose_contract.py -q
V20 产物全树哈希：
      (cd apps/web/dist/external && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /tmp/ext.sums)
      (cd apps/web/dist/internal && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /tmp/int.sums)
      sha256sum /tmp/ext.sums /tmp/int.sums
```

**不在白名单内的门禁**（`check_font_assets.py` / `check_search_golden.py` /
`check_pagination_contract.py` / `check_doc_links.py` / `check_plan_commands.py` /
`perf-baseline.sh`）由各自阶段创建并即时验证，W-1.3 不等待它们。

---

## 4. 冻结基线

### 4.1 环境

| 项 | 要求 |
|---|---|
| Node | **v24.19.0**（`.nvmrc`） |
| pnpm | 11.21.0 |
| Python | 3.14.6 |
| turbo | **2.10.11**（经 `pnpm exec turbo`，不在 PATH） |
| git-lfs | **仅 Phase 1 C4 需要**（一次性）；CI 不读取 `ui-r/`，不得做成常驻 pin |
| fonttools / brotli | **仅 Phase 2 F5 需要**，版本钉死（见 F5） |
| py-spy | **仅 Phase 4 P6 需要**，通过专用 profiling override，不进生产拓扑 |
| Docker / PostgreSQL / 浏览器 | 本机不可用 → CI 补验 |

### 4.2 门禁基线（当前工作树实测，Node 26 临时值）

| # | 命令 | 结果 |
|---|---|---|
| B1 | `python3 scripts/check_nginx_security_headers.py` | OK（6 configs / 37 locations / 2 fragments） |
| B2 | `python3 scripts/check_artifact_headers.py` | OK（5 files） |
| B3 | `pnpm exec turbo run lint --force` | exit 0；0 errors / **94 warnings**（admin 53 / web 37 / api-client 4） |
| B4 | `pnpm typecheck` | 6/6 successful |
| B5 | `pnpm test` | web 36 files / 180 tests；admin 48 files / 127 tests |
| B6 | `bash scripts/check-bundle-size.sh apps/web/dist/external/assets` | OK；antd 296/320 KB gz、entry 165/200 KB gz；`pro` → SKIP |
| B7 | `smoke.sh --profile contracts` | 217 passed（+10 environment-bound） |
| B8 | `smoke.sh --profile static --static-dir <单变体>`（**须分两次**） | 两变体各 PASS |
| B9 | 5 个 `scripts/test_*` 套件 | 86 passed |
| B10 | `smoke.sh --profile runtime` / `e2e` / `images`（**三个独立 profile**） | **未验证** |

**未验证项披露（强制）：** B10 在本机不可执行；相关 Accept 一律标「需 CI 补验」。

### 4.3 关键量化事实

**前端**：产物 **19 MB**（`fonts/` **13 MB** + `assets/` 5.8 MB）；web `@font-face` **0**；
HarmonyOS 字体 3 份 × 13 MB = **38 MB 进 git**；SW 预缓存 **30 项 / 5.7 MB raw**。

**SW 预缓存前 8（raw）**：`pdf.worker.min-*.mjs` 1343 KB、`echarts-*.js` 1015 KB、
`antd-*.js` 924 KB、`index-*.js` 565 KB、`mammoth.browser-*.js` 488 KB、
`cytoscape.esm-*.js` 433 KB、`pdf-*.js` 326 KB、`react-*.js` 194 KB。

**chunk gzip**：echarts 336、antd 295、index 164、mammoth 122、cytoscape 138、
pdf 95、react 60、common 53、router 35（KB）。

**检索与查询**

| 项 | 事实 |
|---|---|
| 匹配与排名 | `ILIKE '%term%'`（31 处）+ `case()` 排名 `exact=3 / alias=2 / text=1`（`search_service.py:637-641`） |
| 别名 | **已在检索中**（`:625-646`）；`tests/test_search_database_integration.py:238` 已断言 `match_type == "alias"` |
| 已有 trgm 索引 | `0024`：`genes.name`、`mutant_lines.name`、`publications.title`；`0027`：`genes.description`、`mutant_lines.{cultivar,mutagen,description}`、`publications.{authors,abstract}` |
| 待取证缺口 | `genes.accession`（`ix_gene_accession` **非唯一**）、`mutant_lines.public_id`、`publications.{doi,pmid}` |
| **assembly 作用域** | `Gene` 注释明确："accessions are only unique per assembly (v4 and v5 are distinct namespaces)"；`GeneAlias` 的 `uq_gene_alias` 也是 `(gene_id, alias)` |
| CH 排序键 | `(release_key, assembly_key, chromosome, position, gene_surrogate_id, mutant_line_surrogate_id, variant_id)` |
| CH 查询排序 | `ORDER BY position ASC, variant_id ASC`（`clickhouse_service.py:230`）→ 与排序键前缀不匹配 |
| **aggregator 超时行为** | `aggregator.py:98-118`：`wait_for` 超时后**重建全部 task 并 `gather`** → 等待时间翻倍 |
| 聚合缓存 | 仅 `stats` / `content snapshot` 走 Redis cache-aside |
| 物化视图 | `release_dashboard`（`variant_type/impact/consequence/cnt`）、`gene_impact_summary`、`mutant_line_summary`、`chromosome_summary` |
| **MV 口径缺口** | `get_dashboard_stats` 需 `uniqExact(gene_id)` 与 `uniqExact(mutant_line_surrogate_id)`；现有 MV 无 `AggregateFunction(uniqExact)` 状态列，无法精确恢复 |
| 公开读 HTTP 缓存 | 无 `Cache-Control`/`ETag`；两个公网路径均 `proxy_cache off` + `add_header Cache-Control "no-store" always` |
| 限流配置 | `rate_limit_per_minute = 60`（`config.py:138`）——与边缘 100 r/s 冲突 |

**脏代码与治理**

| 项 | 事实 |
|---|---|
| nginx server 重复 | `web-nginx.conf`(90) / `admin-nginx.conf`(76) / `apps/jbrowse/nginx.conf`(72)，90% 相同 |
| `_headers` 文件 | **三份**：`apps/{web,admin,jbrowse}/public/_headers` |
| 死代码 | `RateLimitMiddleware`、`TimingMiddleware`（`middleware.py:98,119`） |
| 缓存实现 | `services/cache.py` / `search/cache.py` / `widgets/cache.py` / `content_snapshot_cache.py` |
| 仓库二进制 | `ui-r/网页-查询V2.pdf`(2.5 MB) + `.pptx`(328 KB) |
| 本机垃圾 | `.validation/` **284 MB**、`.turbo/` **44 MB** |
| 镜像集合 | `scripts/list-images.sh` **8 个**（api/worker/migrate/migrate-clickhouse/mcp/jbrowse/web/admin） |
| **Compose 镜像引用** | **6 个** `*_IMAGE_REF`（api/worker/migrate/migrate-clickhouse/mcp/jbrowse）；web/admin 不在 Compose 内 |
| **CI 现状缺口** | `.github/workflows/ci.yml` 的 compose-acceptance 只注入 **4 个**引用，缺 `MIGRATE_IMAGE_REF` 与 `MIGRATE_CLICKHOUSE_IMAGE_REF` |
| 超大源文件 | `settings_registry.py` 2311、`admin/routes/settings.tsx` 1200、`admin/routes/imports.tsx` 1187、`search_service.py` 1126 |
| 语言分布（非测试 LOC） | api 41530 / web 24026 / admin 16801 / worker 9870 / mcp 1246 / shared 425 |

---

## 5. Rust 决策门（Phase 4 判定）

```
Phase 1.5 P1（优化前基线）─► Phase 2/3 优化 ─► Phase 4 P6（同参数复测）─► Gate-1
                                                                            │
                                                              达标 ────────┴── 关闭 Rust 议题
                                                                │
                                                             未达标 → P7 ADR（仅设计）→ 后续独立计划
```

| 门 | 准入 | 动作 | 通过判据 |
|---|---|---|---|
| **Gate-0** | Phase 1 完成 | **Phase 1.5** P1（后端容量）+ P2a（公网防滥用） | 两份基线入库；P1 的 429 = 0；数字可追溯 |
| **Gate-1** | Gate-0 + Phase 2/3 完成 | Phase 4 P6 同参数复测 + 火焰图 | 见下方**按类别 SLO** 全部达标 **且** CPU < 60% **且** 错误率 < 1% |
| **Gate-2** | Gate-1 未达标，且 (a)(b)(c)(d) 全满足 | P7 产出 ADR（附录 A） | (a) ≥50% 时间在 Python 进程内；(b) 瓶颈在 ≤3 个无状态只读端点；(c) 契约可由 OpenAPI 生成；(d) 不涉写路径/编排 |
| **Gate-3** | 后续独立计划 | 试点→灰度→对比 | p95 ↓≥40% **且** CPU ↓≥30% **且** 双跑一致性 100% |

### Gate-1 的 SLO 判据（FZ-17）

三轮审计指出 `p95 < 300ms` 与生产告警 `> 1s` 从未对齐，是无依据的魔法值。改为：

**SLO 由 Phase 1.5 的基线推导并登记，初值如下（首次执行时填入实际值）：**

| 端点类别 | 代表端点 | SLO 上限（p95） | 依据 |
|---|---|---|---|
| 详情/列表（PostgreSQL） | `/api/v1/genes` | **300 ms** | 简单索引查询，远低于生产告警 1s |
| 变体列表（ClickHouse） | `/api/v1/variants`、`/region` | **500 ms** | 分析投影，允许高于 PG 路径 |
| 聚合（缓存后） | `/api/v1/stats/*` | **300 ms** | 命中缓存时不应触及 DB/CH |
| 检索（含联邦外部源） | `/api/v1/search` | **2000 ms** | 外部源不可控；R4 的 6s 为硬墙钟而非目标 |

**登记规则：** Phase 1.5 报告必须为每类填入实测 p95；若实测 p95 **已低于**上表上限，
则 SLO 取 `max(实测 × 0.7, 上表下限)`；若实测高于上限，先按上表判定，不因基线差而放宽。

**明确不做 Rust（满足任一即否决）：** 瓶颈在 DB/CH/网络；需要写路径或事务编排；
需要 Celery/outbox 语义；无 Rust 运维与值班能力；Gate-1 已达标。

---

## 6. 依赖与 Wave 总览

| Wave | 阶段 | 内容 | 退出判据 |
|---|---|---|---|
| **W-1** | 1 | 收口门（W-1.1 → W-1.2 → W-1.3） | §3 白名单全绿 + 基线报告 + 全树哈希 |
| **W0** | 1 | C11（垃圾）、C4（LFS）、C13（计划门禁） | 三项通过；C13 对当前计划 exit 0 |
| **W1** | 1 | S-0…S-10 | 安全回退防线三命令通过 |
| **W1.5** | 1.5 | **P1（后端容量）、P2a（Tunnel 限流）** | 零 429 证明 + 429>0 证明；基线报告入库 |
| **W2** | 2 | F0 → F1 → F2 → F3 → F4 → F5（**含原 F7**）→ F6 → F8；D1、D2；C1 | 体积/预缓存达标；字体门禁红→绿；lint 不增长 |
| **W3** | 3 | R3 → R2、R1；R4、R5、R7、R8；D3…D9 | 黄金集绿；五层隐私矩阵**无 skip** |
| **W4** | 4 | P0（优先级判定）→ P3 → P4 → P5 → P2b（配额验证）→ P6（同参数复测）→ P7（条件） | Gate-1 按类别 SLO 成文 |
| **W5** | 4 | C2、C5、C7、C8、C9、C10、C12；P8、P9；**C3 最后**（字节等价） | 结构治理门禁通过 |

**硬依赖（违反则后续验证无效）**

1. W-1 必须先于所有 Wave；W-1.3 只跑白名单命令。
2. **W1（S 组）必须早于 W1.5** —— S-2 的 `benchmark_mode` / `rate_limit_enabled` 是 P1 的前提。
3. **W1.5 必须早于 W2 与 W3** —— 否则基线是「优化后」，Gate-1 无参照。
4. **C1 必须在 S-2 之后**（`RateLimitMiddleware` 的去留由 S-2 定）。
5. **D1 必须在 P2b 之前** —— P2b 验证的正是 D1 配置的配额。
6. F0 必须在 F1/F2/F6 之前 —— 否则「不劣化」无参照。
7. **F5 内部先红后绿**：先建门禁（红）→ 再改字体与路径（绿）；不得跳过红态。
8. **R3 必须在 R2 之前** —— 黄金集先锁住 v4/v5 不混淆与 `match_type` 契约。
9. R1 的索引必须晚于 EXPLAIN 取证；且**必须含 assembly 作用域**（FZ-13/R1）。
10. D2/D3 契约测试必须早于 P4 的游标改动；D5 必须先于 P4。
11. **F8 必须早于 C3** —— F8 定义缓存行为，C3 只做结构去重且输出字节等价。
12. P3 必须在 W1.5 之后（需基线判定缓存收益）；P4 的目标由 W1.5 的 `read_rows` 推导。

---

## 7. 文件所有权映射

| 区域 | 主责阶段 | 高风险文件 |
|---|---|---|
| `apps/web/**` | Phase 2 | `apps/web/scripts/*`、`apps/web/public/_headers`、`apps/web/public/sw.js` |
| `apps/admin/**`、`apps/jbrowse/**` | Phase 2 | `src/index.css`、`src/assets/fonts/**`、`public/_headers`、`apps/jbrowse/nginx.conf` |
| `infra/nginx/**`、`infra/docker/*-nginx.conf` | Phase 1（S-3/S-4）、Phase 2（F8）、Phase 4（C3、P3） | 头片段、`public-cache.inc`、server 块合并 |
| `infra/docker/Dockerfile.{web,admin}`、`apps/jbrowse/Dockerfile` | Phase 4（C3） | 片段 COPY |
| `apps/api/app/core/**` | Phase 1（S-2/S-4）、Phase 2（C1） | `middleware.py`、`main.py`、`config.py` |
| `apps/api/app/services/search_service.py`、`apps/api/migrations/versions/0037_*.py` | Phase 3 | 迁移需 upgrade/downgrade 双向 |
| `apps/api/app/search/**` | Phase 3（R4） | `aggregator.py`、`models.py` |
| `apps/api/app/services/clickhouse_service.py`、`apps/api/migrations/versions/0038_*.py` | **Phase 3（D9）、Phase 4（P4）** | CH 排序与公开游标契约 |
| `apps/web/src/routes/variants/index.tsx` | **Phase 4（P4）** | 按染色体分片浏览 |
| `docker-compose.yml`、`deploy/**` | Phase 1（S 组）、Phase 4（P5） | 生产拓扑 |
| `scripts/**` | 全体 | 所有门禁的单一来源 |

---

## 8. 跨计划通用规则

1. **提交粒度**：每任务独立 commit；回归断言与其修复同 commit。
2. **门禁位置**：新门禁一律落入 `scripts/ci-job-steps.sh` / `scripts/verify-frontend-artifacts.sh` /
   `scripts/smoke.sh`；`.cnb.yml` 与 `.github/workflows/*` 不得增加逻辑。
3. **未验证披露（强制）**：需 Docker / PostgreSQL / 浏览器 / release 数据的项一律标「未验证」，
   给出 CI 补验路径，**不得计入已完成**。
4. **占位符禁令**：计划内 **fenced code block** 不得出现 `00XX`、`YYYY-MM-DD`、裸 `<...>`；
   运行期参数一律 `$VAR`。**负向测试用例不得以字面量写进计划**（否则 C13 自触发），
   一律放在脚本的单元测试里。
5. **命令可复现**：所有命令必须能在仓库根直接执行；`turbo` 一律 `pnpm exec turbo`，
   `knip` 一律 `pnpm exec knip`。
6. **冻结决策**：§2 登记表的决策不得在执行期重新打开；变更需登记理由。
7. **门禁不得放宽换绿灯**。

---

## 9. 全局验证矩阵

> **A 已实测**（当前工作树跑过）／**B 目标命令**（脚本尚未创建）／**C 需环境**。
> 每条命令必须在 PR 附一次性证据（命令 + 退出码 + 计数）。

| # | 命令 | 期望 | 状态 | 归属 |
|---|---|---|---|---|
| V1 | `node --version` | `v24.19.0` | C | W-1.2 |
| V2 | `pnpm install --frozen-lockfile` | exit 0 | A | 全局 |
| V3 | `pnpm exec turbo run lint --force` | 0 errors **0 warnings** | A（当前 94 warnings） | Phase 4 C2 |
| V4 | `pnpm typecheck` | 6/6 successful | A | 全局 |
| V5 | `pnpm test` | web ≥180、admin ≥127 全绿 | A | 全局 |
| V6 | `VITE_DEPLOYMENT_MODE=demo … pnpm --filter @soymutdb/web build:sites` | exit 0，双产物 | A | Phase 2 |
| V7 | `bash scripts/check-bundle-size.sh apps/web/dist/external/assets` **和** `…/internal/assets` | 均 exit 0，无未声明 SKIP | A | Phase 2 F3 |
| V8 | `du -sh apps/web/dist/external` | ≤7 MB | A（当前 19 MB） | Phase 2 F1 |
| V9 | SW 预缓存清单解析（Phase 2 F2 内联命令） | ≤1228 KB raw，不含 echarts/mammoth/cytoscape/pdf | A（当前 5.7 MB） | Phase 2 F2 |
| V10 | `python3 scripts/check_nginx_security_headers.py` | exit 0（含 Tunnel 限流与缓存断言） | A | Phase 1 S-3 |
| V11 | `python3 scripts/check_artifact_headers.py` | exit 0 | A | Phase 2 F8 |
| V12 | `python3 scripts/check_font_assets.py apps/{admin,jbrowse}/dist` 与 `--assert-charset` | 均 exit 0 | B | **Phase 2 F5**（含原 F7） |
| V13 | `python3 scripts/check_search_golden.py` | exit 0 | B | Phase 3 R3 |
| V14 | `python3 scripts/check_pagination_contract.py` | exit 0 | B | Phase 2 D2 |
| V15 | `python3 scripts/check_doc_links.py` | exit 0 | B | Phase 4 C7 |
| V16 | `python3 scripts/check_plan_commands.py` | exit 0 | B | Phase 1 C13 |
| V17 | `python3 scripts/check_mcp_network_isolation.py` | exit 0（仅可达 api 与 redis 缓存） | B | Phase 1 S-7 |
| V18 | `SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts` | ≥217 passed | A | 全局 |
| V19 | `bash scripts/smoke.sh --profile static --static-dir apps/web/dist/{external,internal}`（两次独立） | 均 PASS | A | Phase 2 |
| V20 | `bash scripts/verify-frontend-artifacts.sh` | exit 0 | A | 全局 |
| V21 | 5 个 `scripts/test_*` 套件 | 86 passed | A | 全局 |
| V22 | `bash scripts/perf-baseline.sh backend` | 429 = 0；基线报告 | C | **Phase 1.5 P1** |
| V23 | `bash scripts/perf-baseline.sh public` | 429 > 0；`/health` 全程 200 | C | **Phase 1.5 P2a** / Phase 4 P2b |
| V24 | `SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile runtime` | PASS | C | Phase 3 |
| V25 | `cd apps/api && .venv/bin/python -m pytest tests -q` | 全绿 | C | Phase 3 |
| V26 | `cd apps/worker && .venv/bin/python -m pytest tests -q` | 全绿 | C | Phase 4 |
| V27 | `cd e2e && PERF_ARTIFACT_ROOT=… PERF_PORT=… npx playwright test -c playwright-web-performance.config.ts`（双变体各一次） | 两份含 variant 名的报告 | C | Phase 2 F0 |
| V28 | `cd e2e && npx playwright test -c playwright-public.config.ts` | 全通过 | C | Phase 3 D4 |
| V29 | `bash scripts/compose-fixture-env.sh -- bash scripts/ci-job-steps.sh run compose-acceptance` | 6 组合 `config -q` 通过 | C | Phase 1 S-0 |
| V30 | `bash scripts/build-release-image.sh` | 构建+冒烟+扫描+SBOM 全绿 | C | Phase 1 S-9 |
| V31 | `apps/api/.venv/bin/python -m pytest scripts/test_cloudflare_tunnel_contract.py -q` | 通过 | A | Phase 1 S-3 |
| V32 | `apps/api/.venv/bin/python -m pytest scripts/test_development_compose_contract.py -q` | 通过 | A | Phase 1 S-10 |
| V33 | `python3 scripts/check-toolchain-pins.py` | 通过 | A | W-1.2 |
| V34 | `git lfs ls-files`（**仅 Phase 1 C4 一次性**） | 两份设计稿在列 | B | Phase 1 C4 |

**安全回退防线（Phase 1 结束后立即执行）：**

```bash
! grep -rn "forwarded-allow-ips=\*" deploy/ infra/
! grep -rn "0\.0\.0\.0/0" deploy/
python3 scripts/check_nginx_security_headers.py
```

---

## 10. 全局风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| W-1 收口拖延 | 上一阶段 DoD 未完成 | 本阶段不启动 |
| 优化前基线缺失 | W1.5 未执行就进 W2/W3 | §6 硬依赖 3 强制阻断；「提升」不可证 |
| 冻结决策被重新打开 | 执行者偏好 | §2 登记表 + PR 登记变更理由 |
| 跨阶段回归 | 后阶段破坏前阶段 | 每阶段退出判据包含前阶段防线命令 |
| 门禁为绿灯放宽 | 压力 | §8 规则 7；`receiving-code-review` 逐条核验 |
| 计划门禁自触发 | 负向示例写成字面量 | §8 规则 4：负向用例只放脚本单元测试 |

**分阶段回滚**：每阶段内任务独立 commit；阶段级回滚 = revert 该阶段 commit 序列。
高风险文件（`infra/nginx/**`、`docker-compose.yml`、`apps/web/public/sw.js`、
`apps/web/scripts/*`、`apps/api/migrations/versions/003{7,8}_*.py`）必须在 PR 中单列 diff。

---

## 11. 总完成定义（DoD）

- [ ] **W-1 通过**：工作树干净、Node 24.19.0、基线报告入库（含**全树** `SHA256SUMS`）
- [ ] **Phase 1 通过**：S 组 10 项关闭或登记为接受风险；安全防线三命令通过；C13 对当前计划 exit 0
- [ ] **Phase 1.5 通过**：P1 含零 429 与全量浏览 `read_rows` 基线；P2a 含 429>0；**两类 SLO 已登记**（§5）
- [ ] **Phase 2 通过**：产物 ≤7 MB；SW 预缓存 ≤1228 KB raw；字体门禁红→绿；
      **lint warning ≤94 且不增长**（0/0 由 Phase 4 C2 达成）
- [ ] **Phase 3 通过**：黄金集绿；五层隐私矩阵**无 skip/xfail**；
      迁移 `0037` 含 assembly 作用域；D9 的 `uniqExact` 口径有证据
- [ ] **Phase 4 通过**：P6 同参数复测完成；Gate-1 按类别 SLO 判定并成文；
      Rust 未实现（或 ADR 六项齐全）；P2b 验证配额
- [ ] §2 冻结决策登记表**无未登记变更**
- [ ] 计划内 fenced code block 无占位符；负向用例不在计划中以字面量出现
- [ ] 门禁全部位于共享脚本；`.cnb.yml` 与 `.github/workflows/*` 无逻辑增量
- [ ] 每个修复的回归断言与修复在**同一 commit**
- [ ] 每个 PR 含：命令、pass/fail 计数、迁移/环境变量影响、回滚方式、**未验证项与 CI 补验路径**

---

## 附录 A · Rust 只读旁路 ADR 骨架（Phase 4 P7 输出物）

```markdown
# ADR-0001：Rust 只读旁路服务

## 状态
Proposed（由 Gate-1 判定触发）

## 上下文
- Gate-1 按类别实测（填入 §5 的 SLO 表实际值）：
  | 端点类别 | 实测 p95 | SLO | 是否达标 |
  - API CPU：$CPU_PCT%（阈值 < 60%）
  - 火焰图：Python 进程内占比 $PY_SHARE%（阈值 ≥ 50%）
- 目标端点（≤3 个，无状态只读）：$TARGET_ENDPOINTS

## 决策
引入 / 不引入 Rust 只读旁路（附理由）

## 后果

### 只读账号与网络
- 网络：`api-rs`（接 nginx）+ `db-read` + `clickhouse-read`（**不含 default**）
- PostgreSQL：角色 `soymutdb_read`，仅 SELECT，`default_transaction_read_only=on`
- ClickHouse：独立用户，仅 SELECT，`readonly=1`
- Rust 服务**不得**持有写凭据

### 语义同源
- 唯一语义来源：黄金查询集（Phase 3 R3）+ OpenAPI 契约
- **禁止复制 Python SQL**；语义变更必须同时更新黄金集
- 双跑一致性测试为上线前置（逐字段，含错误码与游标）

### 工具链与供应链
- `rust-toolchain.toml` 钉死版本；`Cargo.lock` 入库
- 依赖许可证 + 漏洞审查；SBOM 产出
- 镜像加入 `scripts/list-images.sh`；签名与扫描沿用现有发布合同

### 契约与边界
- `site_variant`、release、assembly、分页游标必须与 Python 完全一致
- **assembly 作用域不得放宽**（v4/v5 是不同命名空间）
- 负向泄露测试（Phase 3 D4 五层）必须覆盖 Rust 端点

### 灰度与回滚
- nginx `split_clients`：5% → 50% → 100%；回滚 = 改权重（秒级）
- 放量门禁：按类别 SLO 全部达标 且 CPU ↓≥30% 且双跑一致性 100%

### 未缓解风险
- 两份实现的长期漂移 → 抑制：黄金集 + 契约测试进 CI，任一失败即阻断发布
- Rust 运维能力 → 值班/回滚负责人：$OWNER
```

---

## 附录 B · 技能使用说明

| Skill | 作用 | 备注 |
|---|---|---|
| `dev-expert` | 六步闭环总控；规划门禁、失败升级、写后即记 | 可用 |
| `systematic-debugging` | 性能与检索问题的根因闭环 | 可用 |
| `receiving-code-review` | 对扫描器输出逐条核验，**拒绝以放宽判定换绿灯** | 可用 |
| `ui-ux-pro-max-zh` | 前端规则来源（无障碍/触摸/性能/对比度） | 可用 |
| `brainstorming` | 仅用于 P7 的 ADR 设计 | 可用 |
| `web-perf` | Phase 2 F0/F2/F6 的方法论 | **替代方法**：该 skill 要求 Chrome DevTools MCP，本机不可用；改用 Playwright Resource Timing + PerformanceObserver，须在 F0 报告标注局限 |
| ~~`rust`~~ | — | **不存在该 skill**；P7 只产出 ADR |

> **设计基线来源：** 仓库内 token 定义（`apps/web/src/index.css` 的 `@theme`、
> `apps/admin/src/index.css` 对应段落）。**不引用仓外脚本或用户主目录绝对路径。**
