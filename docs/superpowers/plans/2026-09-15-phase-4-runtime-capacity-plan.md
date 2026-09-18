# Phase 4 · 同参数复测 + Gate-1 + 结构治理

> **父计划：** `plan.md`（主路线图）。执行前先读 §2 冻结决策登记表。
> **前置：** Phase 1（S 组）、**Phase 1.5（优化前基线）**、Phase 2（前端/契约）、Phase 3（检索/DB）均已退出
> **Wave：** W4、W5
> **退出判据：** §4

---

## 0. 子计划级修订说明

### v4（第三次审计后）

| 三轮审计问题 | 本计划处置 |
|---|---|
| **B2/S16**：P1 与 P6 同在 Phase 4，「同参数复测」名不副实 | **P1/P2 已移出本计划**，改由 Phase 1.5 承担优化前基线；本计划只做 P6 复测 |
| **B5**：P3 只优化自建 nginx，真实公网入口（tunnel-origin）未覆盖 | P3 重写：两处入口**共用 `public-cache.inc`**，`cloudflare-tunnel.conf` 也必须启用缓存 |
| **G5**：C3/F8 可能重复改 nginx | C3 冻结为**只做结构去重且 `nginx -T` 输出字节等价**；缓存行为由 F8 定义 |
| **S15**：现有 MV 无法产出 `uniqExact` 口径 | D9 新增迁移 `0038` 与 `AggregateFunction(uniqExact)` 状态列 |
| **S17**：Gate-1 阈值是无依据的魔法值 | P6 改为按**端点类别 SLO** 逐项判定（主计划 §5） |
| **S18**：`py-spy` 在 API 镜像不可用（无该包 + `cap_drop: ALL`） | P6 新增 `docker-compose.profiling.yml` override + 专用镜像，验证后立即拆除 |
| 新增任务顺序依赖 | 新增 **P0**：用 Phase 1.5 基线判定 P3/P4/P5 的优先级；新增 **P2b**（配额验证，依赖 Phase 2 D1） |

### v3（第二次审计后）

| 二轮审计问题 | 处置 |
|---|---|
| `turbo` 不在 PATH | C2 改用 `pnpm exec turbo run lint --force` |
| C3 验收要求三个镜像但只构建一个 | Verify 列出三个镜像的 `nginx -t` 与 `nginx -T` |
| C8 用 `npx knip` 可能拉非锁定版本 | 改 `pnpm exec knip` |
| P3 CH 未被计入、命名歧义 | 同时查 PG 与 CH；统一用 `site_variant` |
| P4 目标无依据；Files 缺前端 | 目标**由 Phase 1.5 基线推导**；Files 补前端路由；排序契约冻结（FZ-15） |
| S-9 在两份计划间重复 | S-9 只在 Phase 1；本计划 C12 只负责**长期治理流程** |

---

## 1. 任务清单

### P0 · 在 P3/P4/P5 前先做一个新依赖决策（新增）

> 本任务不产出代码，只产出结论。若不完成，P3/P4/P5 无法判定优先级。

**Files:** `docs/ops/perf-baseline-2026-09-15.md`（引用，不修改）
**Steps:** 根据 Phase 1.5 的基线，为四个端点类别分别判定「是否已低于 §5 的 SLO」：

| 端点类别 | 基线 p95 | SLO | 未达标时的优先优化项 |
|---|---|---|---|
| 详情/列表（PG） | （填） | 300 ms | R1 索引 / C5 缓存 |
| 变体列表（CH） | （填） | 500 ms | **P4** |
| 聚合（缓存后） | （填） | 300 ms | **D9 预聚合 + P3 缓存** |
| 检索（含外部源） | （填） | 2000 ms | R4 降级 / R1 索引 |

**Verify:** 四行均已填入基线实测值，且每行给出「做/不做」的结论
**Accept:** P3/P4/P5 的执行优先级由本表决定，而非拍脑袋。若全类已达标，可在 P6 直接判定 Gate-1 通过。

---

### P3 · 公开读端点 HTTP 缓存（冻结为 nginx `proxy_cache`，**且必须覆盖真实生产入口**）

> **三轮审计 B5（阻塞）：** v3 冻结为「自建 nginx 启用 proxy_cache，tunnel-origin 保持关闭」，
> 但默认公网入口是 `cloudflared → tunnel-origin → API` ——
> 真实公网用户**完全绕过**带缓存的本地 nginx，P3 做完也不改善默认生产流量。

**Files:** 新增 `infra/nginx/conf.d/public-cache.inc`、
**`infra/nginx/cloudflare-tunnel.conf`（主：默认公网路径）**、
`infra/nginx/conf.d/default.conf`、
`apps/api/app/api/v1/{variants,genes,mutants,publications,releases,stats}.py`、
`docs/ops/production-security-checklist.md`

**Steps（**FZ-14，主计划 §2.2**）：**
1. **两处入口共用同一缓存片段** —— 抽 `infra/nginx/conf.d/public-cache.inc`，
   由 **`cloudflare-tunnel.conf`（默认公网路径）** 与 `conf.d/default.conf`（自建/内网）**都 include**。
   这是本任务的核心：只有 tunnel-origin 也启用缓存，才真正覆盖公网流量。
   Cloudflare Cache Rules 仍不在范围内（无 IaC、本机不可测），但此时不再是唯一手段。
2. **公开 GET allowlist**（显式路径列表）：只对这些路径放开缓存并**移除**
   `add_header Cache-Control "no-store" always`，改为透传上游 `Cache-Control`；其余保留 `no-store`。
3. **端点级 cache version token：**
   - `variants` / `genes` / `mutants` / `publications`：`release_key + assembly_id`
   - `releases`：**不带 version token**（列表本身是版本清单），只设短 `max-age`
   - `stats/*`：`release_key + 统计窗口`
4. **ETag 必须低成本可算**：由 version token + 规范化查询参数摘要生成；
   `If-None-Match` 命中时**不查任何数据库**直接返回 304。
   `proxy_cache` 命中时请求根本不到 API —— 这是「不落库」的主要机制。
5. **两处的 `proxy_cache_key` 必须一致**，含 `site_variant` + version token + 规范化查询参数：
   ```nginx
   proxy_cache_key "$site_variant$scheme$host$request_uri";
   ```
   `site_variant` 的具体来源（host / 路径 / 显式头）按实际部署形态固化并写注释。
   带 `Authorization`/Cookie 的请求**永不进共享缓存**（`proxy_no_cache`/`bypass` 已有，须保持并加测试）。
6. 缓存失效：新 release 发布时 version token 变化即自然失效；
   **不提供 `proxy_cache_purge`** —— 它是 nginx plus 特性，stock nginx 不可用；
   需要主动失效时改为在 CDN 层操作，或直接依赖 version token。

**Verify:**
```bash
# 1) 头部契约
curl -sI "http://localhost:8080/api/v1/variants?limit=20" | grep -ci 'no-store'          # 期望 0
curl -sI -H "Authorization: Bearer x" "http://localhost:8080/api/v1/variants" | grep -ci 'no-store'  # 期望 1
# 2) 304 不落库：先取 ETag，再带 If-None-Match
ETAG=$(curl -sI "http://localhost:8080/api/v1/variants?limit=20" | awk -F': ' 'tolower($1)=="etag"{print $2}' | tr -d '\r')
curl -sI -H "If-None-Match: ${ETAG}" "http://localhost:8080/api/v1/variants?limit=20" | head -1   # 期望 304
# 3) **两个入口都要验证**（主：tunnel-origin；次：自建 nginx）—— 需 Docker
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose --profile core --profile cloudflare-tunnel up -d tunnel-origin api
  for _ in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8081/api/v1/variants?limit=20"; done
'
# 4) 回源次数：连续 10 次请求后，PG 与 CH 的计数增量均应为 0（或远小于 10）
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose exec -T postgres psql -U soymutdb -d soymutdb -Atc \
    "SELECT sum(calls) FROM pg_stat_statements WHERE query ILIKE \"%genes%\""
  docker compose exec -T clickhouse clickhouse-client --query \
    "SELECT count() FROM system.query_log WHERE query LIKE \"%variant_facts%\" AND event_time > now() - INTERVAL 1 MINUTE"
'
```
**Accept:** **两个入口**（tunnel-origin 与自建 nginx）的匿名重复请求**均不产生新的 PG 与 CH 查询**；
带凭据请求仍 `no-store`；`releases` 与 `stats` 的 token 策略分别落地；
`public-cache.inc` 为单一来源。

---

### P4 · ClickHouse 查询与排序键对齐

> **修正二轮审计：** v2 目标「read_rows 下降 ≥80%」无依据，且未处理染色体排序语义、
> 也未列出前端改动文件。

**Files:** `apps/api/app/services/clickhouse_service.py`、`apps/api/app/services/variant_service.py`、
`apps/api/app/schemas/variant.py`、`apps/api/app/main.py`（`x-pagination` 增 `cursor_version`）、
**`apps/web/src/routes/variants/index.tsx`**

**Steps（**FZ-15**）：**
1. 排序改为 **`(chromosome, position, variant_id)`**，与表排序键前缀
   `(release_key, assembly_key, chromosome, position, …)` 对齐。
2. 游标携带 `chromosome`；`x-pagination` 增加 **`cursor_version`**；旧游标解码保留一个发布周期的兼容期
   （旧版本按原 `(position, variant_id)` 语义解析，新请求一律签发新版本游标）。
3. **染色体排序语义（冻结）**：API 按 **`chromosome` 字典序**（与 CH 排序键一致，无需 schema 变更）；
   **UI 按生物学顺序呈现**——用 PostgreSQL 已有的 `Chromosome.order`
   （`apps/api/app/models/genomic.py:83`，索引 `ix_chromosome_assembly_order`）驱动染色体选择器。
4. **前端改为按染色体分片浏览**：`apps/web/src/routes/variants/index.tsx` 增加染色体选择，
   默认进入第一个染色体而非「全部」；「全部」仅在显式选择时使用，并提示排序为字典序。
5. **目标由 Phase 1.5 基线推导**（不预设百分比）：
   - 用 Phase 1.5 记录的「每 Mb 行数」与「全量浏览 `read_rows`」计算基线；
   - 目标 = 单次全量浏览的 `read_rows` 收敛到「单染色体范围扫描」量级，
     具体数值在实现前写入本文件（登记原值/目标值/依据）。

**Verify:**
```bash
# CH 侧证据（需 Docker + ClickHouse）
docker compose exec -T clickhouse clickhouse-client --query \
  "SELECT query_duration_ms, read_rows FROM system.query_log WHERE query LIKE '%variant_facts%' ORDER BY event_time DESC LIMIT 10"
(cd apps/api && .venv/bin/python -m pytest tests -q -k "keyset or cursor or variant")   # 需 PostgreSQL
python3 scripts/check_pagination_contract.py
# 跨页不重不漏：按染色体逐页取完，断言并集等于该染色体全量且无重复
pnpm --filter @soymutdb/web test
```
**Accept:** `read_rows` 达到登记的目标值（由 Phase 1.5 推导，非预设）；分页跨页不重不漏有测试；
`cursor_version` 兼容期有测试；前端按染色体分片浏览可用。

---

### P5 · PgBouncer 评估与接入

**Files:** `docker-compose.yml`、`deploy/.env.example`、`docs/ops/production-readiness.md`
**Steps:** 先依据 Phase 1.5 记录的连接数与 `ApiDatabasePoolSaturation` 判定是否需要。若需要：
加入 `core` profile，transaction pooling；asyncpg 侧必须设置 `statement_cache_size=0`
（或启用 PgBouncer 的 `max_prepared_statements` 并把 `statement_cache_size` 设为不超过该值）；
重算 fleet 预算（当前 API 2×(3+2)=10、Celery 10、总 ≤40）。
**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- docker compose --profile core config -q
(cd apps/api && .venv/bin/python -m pytest tests -q -k db_pool)   # 需 PostgreSQL
# 压测下 PG 活跃连接受控，ApiDatabasePoolSaturation 告警不触发
```
**Accept:** 连接数上限可预测；准备语句兼容性有测试；**若判定不需要，登记理由与复查条件**。

---

### P6 · Gate-1 判定与记录（**同参数复测**）

> **三轮审计 B2/S16：** v1–v3 把 P1 与 P6 都放在 Phase 4，导致 P6 的「同参数复测」实际
> 只能对比同一次测量。本版 P1 已移到 **Phase 1.5**（优化前），P6 才是真正的复测。

**Files:** 新增 `docs/ops/perf-decision-2026-09-15.md`
**Steps:**
1. 用与 Phase 1.5 **完全相同参数**重跑 `scripts/perf-baseline.sh backend`
   （相同 VU 梯度、相同端点、相同机器规格、相同基准模式开关）。
2. 取火焰图判定时间去向（需先完成下面的 profiling 环境准备）。
3. 按主计划 §5 的**按端点类别 SLO** 逐类给出达标/未达标，再给出总结论。
4. 无论结论如何都要写文档；未达标时必须给出**具体瓶颈定位**（哪个端点类、哪段代码）。

**Profiling 环境准备（三轮审计 S18 —— py-spy 在 API 镜像中不可用）：**

当前 API 镜像**未安装 `py-spy`**，且 `x-app-runtime` 有 `cap_drop: ALL`，
`docker compose exec api py-spy ...` 会直接失败。冻结方案：

1. 新增 `docker-compose.profiling.yml`（**override，不进生产拓扑**）：
   - 仅覆盖 `api` 服务：`command` 为 sleep 守守型入口（或直接覆盖为 `uvicorn` 但带 `--reload` 关闭）；
   - 增加 `cap_add: [SYS_PTRACE]`（**仅本 override**，基础文件仍为 `cap_drop: ALL`）；
   - 镜像用 **profiling 专用 Dockerfile**：`infra/docker/Dockerfile.api.profiling`，
     基于 API 镜像并 `pip install py-spy==0.4.0`（**钉版本**）与 `procps`。
2. **验证结束后立即 `down` 并删除镜像**；不得保留在生产主机。
3. 该 override **不得**被 `docker-compose.yml` 或任何 CI 组合引用（由门禁断言）。

**Verify:**
```bash
# 1) 复测（同一套参数）
bash scripts/perf-baseline.sh backend   # 需 Docker + release 数据
# 2) 火焰图（专用 override，验证后立即拆除）
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose -f docker-compose.yml -f docker-compose.profiling.yml --profile core up -d api
  docker compose -f docker-compose.yml -f docker-compose.profiling.yml exec -T api \
    py-spy record -o /tmp/profile.svg --pid 1 --duration 60
  docker compose -f docker-compose.yml -f docker-compose.profiling.yml down --rmi local
'
# 3) 门禁：profiling override 不得被基础 compose 引用
grep -c "profiling" docker-compose.yml   # 期望 0
```
**Accept:** 复测与 Phase 1.5 同参数；火焰图成功产出；
按类别 SLO 逐项判定并成文；**profiling 环境已拆除且未被基础 compose 引用**。

---

### P7 · Rust 只读旁路 ADR（**仅设计，条件触发**）

**Files:** 新增 `docs/adr/0001-rust-read-only-sidecar.md`
**前置：** P6 判定进入 Gate-2。**未满足则本任务标注 N/A，不产出文件。**
**Steps:** 按主计划附录 A 骨架产出 ADR，**不写实现**，六项必须齐全（只读账号与网络、语义同源、
工具链与供应链、契约与边界、灰度与回滚、未缓解风险）。
**Verify:** `docs/adr/0001-rust-read-only-sidecar.md` 存在且六项齐全；负责人评审通过。
**Accept:** 实现**不在本阶段范围内**；ADR 通过后另立计划。

---

### P8 · 水平扩容前置条件清单化

**Files:** `docs/ops/production-readiness.md`（扩展）
**Steps:** 列出扩容前必须为真的条件（无状态化、会话/缓存外置、连接预算与 PgBouncer、
CH 查询预算、限流、CDN、备份窗口、监控覆盖），每条附验证命令。
**Verify:** 清单逐条可执行（每条命令实跑一次并记录结果）。
**Accept:** 「能不能加副本」不再靠猜。

---

### P9 · 数据面吞吐与 Range 验证

**Files:** `infra/nginx/*.conf`、`deploy/scripts/healthcheck.sh`
**Steps:** 验证 `/data/` 与 JBrowse 数据路径在大文件 Range 下的吞吐与内存占用；
评估是否让对象存储/CDN 直出替代经 nginx 代理。
**Verify:**
```bash
OBJECT_KEY=${OBJECT_KEY:?需先准备一个基因组对象}
curl -r 0-1048575 -so /dev/null -w '%{http_code} %{size_download}\n' "http://localhost:8080/data/${OBJECT_KEY}"
# 并发下载时 nginx RSS 不随文件大小增长
```
**Accept:** 大文件路径不成为内存与带宽瓶颈；有实测数据支撑结论。

---

## 2. W5 —— 结构治理

### C2 · lint 告警清零并升级为硬门禁

**Files:** 各前端源码、`scripts/verify-frontend-artifacts.sh`、必要时 `eslint.config.js`
**Steps:**
1. 现状 94 条 warning（admin 53 / web 37 / api-client 4），0 error。逐条分类：
   **真实缺陷**（`react-hooks/set-state-in-effect`、render 期访问 ref、`no-console`）→ 修代码；
   **风格类** → 修代码，或按规则给 reason 后关规则。
2. **禁止** `eslint-disable` 批量压制；确需压制必须单行 + 带原因注释。
3. 修复后把 `--max-warnings 0` 写入 `scripts/verify-frontend-artifacts.sh`。

**Verify:**
```bash
pnpm exec turbo run lint --force        # turbo 不在 PATH，必须经 pnpm exec
bash scripts/verify-frontend-artifacts.sh
# 负向：人为加一条 warning → 期望 FAIL
```
**Accept:** workspace 0 errors / 0 warnings；门禁对新增告警变红。

---

### C3 · nginx server 块去重

**Files:** `infra/docker/web-nginx.conf`、`infra/docker/admin-nginx.conf`、`apps/jbrowse/nginx.conf`、
`infra/nginx/conf.d/*.inc`、`infra/docker/Dockerfile.web`、`infra/docker/Dockerfile.admin`、`apps/jbrowse/Dockerfile`
**Steps:** 三份配置 90% 相同（差异：安全头片段、`/samples/`、以及 F8 定义的缓存层）。
抽取公共片段（location 级 `include`），**必须**同步更新三个 Dockerfile 的片段 COPY
（否则容器启动 `nginx: [emerg]`），并保持「每个声明 `add_header` 的 location 都要 include 片段」不变式。

> **与 F8 的边界（三轮审计 G5，冻结）：**
> **F8（Phase 2）定义缓存行为**；C3 **只做结构去重**——
> 抽出的 `public-cache.inc` / `security-headers*.inc` 必须使最终生效的响应
> **字节等价**于 F8 之后的配置（可用 `nginx -T` 对比去重前后的展开结果）。
> C3 不得顺手修改任何缓存或安全头的值。

**Verify:**
```bash
python3 scripts/check_nginx_security_headers.py
apps/api/.venv/bin/python -m pytest scripts/test_dockerfile_contracts.py -q
# 字节等价证据：去重前后各跑一次 nginx -T，渲染结果应只差 include 展开（需 Docker）
bash scripts/compose-fixture-env.sh -- bash -c '
  for s in web admin jbrowse; do
    docker build -f "$( [ $s = jbrowse ] && echo apps/jbrowse/Dockerfile || echo infra/docker/Dockerfile.$s )" -t smoke-$s:ci . && \
    docker run --rm smoke-$s:ci nginx -T > /tmp/$s.rendered
  done
'   # 与去重前保存的 /tmp/*.rendered.before 对比
```
**Accept:** 配置行数下降 ≥50%；门禁仍能捕获「漏 include」；
**三个镜像 `nginx -t` 均通过**；`nginx -T` 渲染结果与 F8 后**字节等价**。

---

### C5 · 缓存 key builder 与观测口径收敛（**限定范围**）

**Files:** `apps/api/app/services/cache.py`（公共 helper）、`apps/api/app/search/cache.py`、
`apps/api/app/widgets/cache.py`、`apps/api/app/services/content_snapshot_cache.py`
**Steps（**FZ-16**）：**
1. 统一 **key 构造**（`make_cache_key` 的哈希算法与命名空间前缀）与**观测**
   （`CACHE_LOOKUPS_TOTAL` 标签口径）。
2. **不统一失效语义**：`search/cache.py`（短 TTL、无失效）、`widgets/cache.py`（分布式锁）、
   `content_snapshot_cache.py`（版本化快照）、`services/cache.py`（cache-aside）的差异是设计意图，
   各自保留 TTL 与失效策略，并在 docstring 写明理由。
3. 不改变现有键的语义（避免缓存击穿）；必要时双读过渡。
**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "cache or snapshot")   # 需 PostgreSQL
# 断言：四处 helper 产出的 key 前缀与哈希算法一致
```
**Accept:** 一套 key 约定 + 一套观测口径；失效策略差异有文档化理由。

---

### C7 · 文档漂移门禁

**Files:** 新增 `scripts/check_doc_links.py`、`scripts/smoke.sh`
**Steps:** 扫描 `docs/**` 与根级 `*.md` 中的仓库内路径引用，不存在即失败（白名单带 reason）。
**Verify:**
```bash
python3 scripts/check_doc_links.py
# 负向：临时写入不存在的路径 → 期望 FAIL
```
**Accept:** 文档引用不可能静默失效。

---

### C8 · 未使用依赖清理

**Files:** `knip.json`、各 `package.json`
**Steps:** 把 `ignoreDependencies` 的 30 余条白名单逐条证明（真未使用 → 删；条件使用 → 写 reason）。
Python 侧用等价工具检查。
**Verify:**
```bash
pnpm exec knip --include dependencies    # 不用 npx（避免临时下载非锁定版本）
pnpm install --frozen-lockfile && pnpm build && pnpm test
```
**Accept:** 白名单每条带 reason 或已删除。

---

### C9 · 超大文件按职责拆分

**Files:** `apps/api/app/core/settings_registry.py`(2311)、`apps/admin/src/routes/settings.tsx`(1200)、
`apps/admin/src/routes/imports.tsx`(1187)、`apps/api/app/services/search_service.py`(1126)
**Steps:** 按**职责**拆分：registry 拆为数据 + 解析；页面拆为容器 + 子组件/表单片段；
search_service 拆为「查询构造 / 排名 / 游标 / 序列化」。
**Verify:**
```bash
pnpm typecheck
pnpm --filter @soymutdb/admin test
(cd apps/api && .venv/bin/python -m pytest tests -q -k "search or registry")   # 需 PostgreSQL
```
**Accept:** 每个文件单一职责且 ≤600 行（registry 数据文件可豁免并注明理由）。

---

### C10 · TODO/FIXME 盘点闭环

**Files:** 全仓
**Steps:** 列出 `TODO`/`FIXME`/`XXX`，分类：立即修 / 建条目 / 删除；删除失效注释。
门禁：新增 TODO 必须带 owner 与解除条件。
**Verify:**
```bash
rg -n 'TODO|FIXME' --glob '*.ts' --glob '*.tsx' --glob '*.py' | wc -l
```
**Accept:** 无无主 TODO。

---

### C12 · `.trivyignore` 长期治理流程

> **说明：** 结构化格式与扫描面扩展已在 **Phase 1 S-9** 完成。本任务只负责**流程**，不重复实现。

**Files:** `docs/ops/dependency-governance.md`
**Steps:** 定义季度复核流程：谁审（owner 角色）、依据（Trivy DB 更新 + 上游修复状态）、
失效处理（`expired_at` 到期后的默认动作 = 阻断发布）、新增豁免的审批要求。
**Verify:** 文档含可执行的复核清单；`git log .trivyignore.yaml` 可按季度追溯。
**Accept:** 豁免有生命周期与负责人；流程可被下一个维护者直接执行。

---

## 3. 阶段内任务顺序

| 顺序 | 任务 | 理由 |
|---|---|---|
| 1 | **P0** | 用 Phase 1.5 基线判定 P3/P4/P5 的优先级；不完成则后续无法排序 |
| 2 | P3 | 需 Phase 1.5 判定缓存收益；两处入口共片段 |
| 3 | P4 | 需 Phase 1.5 的每 Mb 行数与 `read_rows` 推导目标；需 Phase 2 D2 与 Phase 3 D5 |
| 4 | P5 | 需 Phase 1.5 的连接数判定 |
| 5 | P2b | 配额验证（依赖 Phase 2 D1） |
| 6 | P6 | Gate-1 同参数复测 + 按类别 SLO 判定（依赖全部优化完成） |
| 7 | P7 | 条件触发（Gate-2）；未触发则标 N/A |
| 8 | P8、P9 | 独立 |
| 9 | C2 → C5 → C7 → C8 → C9 → C10 → C12 | 治理项，彼此独立 |
| 10 | **C3（最后）** | 必须晚于 Phase 2 F8；只做字节等价的结构去重 |

---

### P2b · 配额验证（从原 P2 拆分）

> Phase 1.5 的 P2a 已验证 Tunnel 限流 zone 生效；本任务验证 **Phase 2 D1 的分级配额**。

**Files:** `scripts/perf-baseline.sh`（`public` 子命令复用）
**Steps:** 经边缘发压，验证四类配额的实际生效点与 `Retry-After`：
匿名读 100 r/s、认证 10 r/s、BLAST 1 r/s、Range 按连接数（不被请求频率误伤）。
并验证 **S-2 的不变量**（应用匿名读上限 ≥ 边缘等效速率，不再出现「边缘允许、应用拦截」的反向瓶颈）。
**Verify:**
```bash
bash scripts/perf-baseline.sh public   # 需 Docker
# 断言：四类配额各自触发 429 且带 Retry-After；/health 全程 200
# 断言：Range 路径在低频高并发下不返回 429，但在连接数超限时受限
```
**Accept:** 四类配额行为可复现；应用层不再是反向瓶颈。

---

## 4. 阶段退出判据

```bash
# 1. 复测与配额
bash scripts/perf-baseline.sh backend   # 需 Docker + release 数据；429 必须为 0；与 Phase 1.5 同参数
bash scripts/perf-baseline.sh public    # 需 Docker；429 必须 > 0；四类配额均触发

# 2. 缓存（**两个入口**）
curl -sI "http://localhost:8080/api/v1/variants?limit=20" | grep -ci 'no-store'          # 0
curl -sI -H "Authorization: Bearer x" "http://localhost:8080/api/v1/variants" | grep -ci 'no-store'  # 1
! grep -q 'proxy_cache off' infra/nginx/conf.d/public-cache.inc 2>/dev/null || true

# 3. 治理
pnpm exec turbo run lint --force
pnpm exec knip --include dependencies
python3 scripts/check_doc_links.py
python3 scripts/check_nginx_security_headers.py
python3 scripts/check_pagination_contract.py
python3 scripts/check_plan_commands.py
apps/api/.venv/bin/python -m pytest scripts/test_dockerfile_contracts.py -q
SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts
bash scripts/verify-frontend-artifacts.sh
```

**需环境的判据**（本机不可执行 → CI 补验，标「未验证」）：
两个 `perf-baseline.sh`、三个 `docker build` + `nginx -t`/`-T`、profiling override、`py-spy`、
`apps/api` / `apps/worker` 全量 pytest。

**DoD 勾选项：**
- [ ] P0 已用 Phase 1.5 基线为四类端点判定优先级
- [ ] P2b 四类配额均验证；应用层不再是反向瓶颈
- [ ] P3 **两个入口**（tunnel-origin 与自建 nginx）的匿名重复请求 PG **与 CH** 增量均为 0；
      `public-cache.inc` 为单一来源；无 `proxy_cache_purge` 依赖
- [ ] P4 排序与游标冻结；目标由 **Phase 1.5** 推导并登记；前端按染色体分片浏览
- [ ] P5 有 PgBouncer 判定结论（需要则接入，不需要则登记理由与复查条件）
- [ ] P6 与 Phase 1.5 **同参数**；按类别 SLO 逐项判定并成文；
      **profiling override 已拆除且未被基础 compose 引用**
- [ ] P7 在 Gate-2 未触发时标注 **N/A**（不产出文件）
- [ ] C2 workspace 0/0 且 `--max-warnings 0` 生效
- [ ] C3 **三个镜像** `nginx -t` 通过，且 `nginx -T` 渲染与 F8 后**字节等价**
- [ ] C5 只统一 key builder 与观测口径，失效语义差异有文档
- [ ] C7/C8/C9/C10/C12 全部关闭
- [ ] 未执行项有 CI 补验路径

---

## 5. 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| 复测参数与 Phase 1.5 不一致 | 参数漂移 | 同一脚本、同一子命令、参数写入报告；不一致则复测无效 |
| `benchmark_mode` 泄漏到生产 | 配置误用 | S-2 已加 prod fail-fast；P6 不额外放宽 |
| P3 缓存陈旧 | version token 未随 release 变化 | token 含 `release_key`；发布即失效；**不依赖 `proxy_cache_purge`**（stock nginx 无此特性） |
| P3 带凭据请求被缓存 | location 未覆盖 | 显式断言 `Authorization` 请求 `no-store` |
| P3 带凭据请求被缓存 | location 未覆盖 | 显式断言 `Authorization` 请求 `no-store` |
| P4 游标兼容期缺测试 | 旧游标解析回归 | `cursor_version` 有测试；跨页不重不漏断言 |
| P4 目标值无依据 | 未跑 P1 | 目标必须由 P1 数据推导并登记；不得预设百分比 |
| P5 PgBouncer 与 asyncpg 不兼容 | transaction pooling | 先验证 `statement_cache_size=0`；不兼容则退回 session pooling 或不上 |
| C3 nginx 去重漏 COPY | Dockerfile 未同步 | `test_dockerfile_contracts.py` 断言；三个镜像 `nginx -t` 实测 |
| C8 删掉条件使用的依赖 | 白名单误判 | 逐条 grep + `pnpm build && pnpm test` 全绿方可提交 |
| C9 拆分引入行为变化 | 机械切分 | 只做职责切分；测试全绿方可提交 |

**通用回滚：** 每任务独立 commit；高风险文件（`docker-compose.yml`、
`apps/api/app/services/clickhouse_service.py`、`apps/web/src/routes/variants/index.tsx`、
`infra/docker/*-nginx.conf`）在 PR 中单列 diff。
