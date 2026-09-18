# Phase 2 · 前端与静态性能

> **父计划：** `plan.md`（主路线图）。执行前先读 §2 冻结决策登记表。
> **前置：** Phase 1 已退出（S 组完成、C13 门禁已建立、Node 24 + git-lfs 就绪）
> **Wave：** W2
> **退出判据：** §4

---

## 0. 子计划级修订说明

| 二轮审计问题 | 本计划处置 |
|---|---|
| F1/F2/F6 缺 LCP 参照却要求「不劣化」 | F0 先建三场景基线（cold / warm / SW-controlled），统一用 `transferSize` |
| `turbo` 不在 PATH | 所有命令改 `pnpm exec turbo` |
| F3 的 brace 展开造成假通过 | 明确「脚本只接受 `$1`，两变体分两次调用」 |
| 字体路径 `../assets/fonts/` 指向不存在的目录 | 冻结为 `./assets/fonts/...`（FZ-7） |
| C6 与 F5 职责重叠、顺序互指 | **合并为一个任务**（F5 吸收 C6），先子集化再改路径 |
| 「常用汉字集」不可复现 | 冻结语料来源 + 仓库内字符集文件（FZ-8）+ 自动化缺字检查 |
| F7 断言 `assets/files/*.woff2`（不存在） | 改为解析 CSS URL 并断言目标文件存在 |
| C8 用 `npx knip` 可能拉非锁定版本 | 改 `pnpm exec knip`（本阶段不含 C8，见 Phase 4） |
| C1 排在依赖项 S-2 之前 | C1 移入本阶段（S-2 已在 Phase 1 完成） |

> **F0 的度量口径（冻结）：** 「首访字节」一律以
> `PerformanceResourceTiming.transferSize` 为准；raw 文件大小**只**用于
> 「预缓存清单体积」这一与压缩无关的指标。两者不得混用。

---

## 1. 任务清单

### F0 · 前端性能基线（前置，必须先于 F1/F2/F6）

**Files:** `e2e/playwright-web-performance.config.ts`（**参数化**）、`e2e/tests/web-artifact-performance.spec.ts`、新增 `docs/ops/frontend-perf-baseline-2026-09-15.md`

> **三轮审计 S10：** 当前配置实码硬编码 `apps/web/dist` 与 `http://127.0.0.1:4175/`，
> 而任务要求 external/internal 分别测三场景 —— 必须参数化，否则只测了一个产物。

**Steps:**
1. **配置参数化**（新增两个环境变量，并写入 config 与 static-server 调用）：
   - `PERF_ARTIFACT_ROOT`：产物目录（默认 `apps/web/dist`，本次传 `apps/web/dist/external` / `internal`）
   - `PERF_PORT`：静态服务端口（默认 `4175`，两变体用不同端口避免复用）
   报告文件名必须**含 variant**（如 `performance-report-external.json` / `-internal.json`）。
2. 三种场景分别采集：
   - **cold**：清空 SW 与 Cache Storage 后的首次访问；
   - **warm**：SW 已安装且资源已缓存；
   - **SW-controlled**：断网后刷新（验证离线壳可用）。
3. 每场景记录：`transferSize` 合计、`decodedBodySize` 合计、LCP、INP、CLS、TBT；
   每项 3 次取中位数。
4. **INP 必须有实际交互动作**（三轮审计 S10）：否则没有 INP 样本。
   冻结为三个动作序列之一并写入 spec：`搜索框输入 3 字符` / `点击首个结果` / `切换一次筛选`。
5. 记录首访预缓存清单的**条目数与 raw 体积**（与压缩无关的指标）。
6. 报告必须含：设备/浏览器版本、网络节流设置、采集方式与局限。
   **采集方式标注（强制）**：本机无 Chrome DevTools MCP，采用 Playwright Resource Timing +
   PerformanceObserver，与 `web-perf` skill 的默认工具链不同，须在报告中显式声明。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
cd e2e
PERF_ARTIFACT_ROOT=apps/web/dist/external PERF_PORT=4175 npx playwright test -c playwright-web-performance.config.ts
PERF_ARTIFACT_ROOT=apps/web/dist/internal PERF_PORT=4176 npx playwright test -c playwright-web-performance.config.ts
ls test-results-web-performance/performance-report-{external,internal}.json
```
**Accept:** `docs/ops/frontend-perf-baseline-2026-09-15.md` 入库，含**两个产物**的三场景数据；
INP 有实际交互样本；F1/F2/F6 的「不劣化」一律以本报告为参照。

---

### F1 · 删除 web 未引用字体（19 MB → ≤7 MB）

**Files:** `apps/web/public/fonts/harmonyos/*`（删除）、`apps/web/src/index.css`（注释）、`scripts/check-bundle-size.sh`
**Steps:**
1. **先证明无引用**：`rg -c '@font-face' apps/web/src/` 期望 0；并检查产物 CSS 无 HarmonyOS 引用。
2. `git rm -r apps/web/public/fonts/harmonyos`。
3. 更新 `index.css` 注释：系统 CJK 栈是有意选择，历史字体现存于 admin/jbrowse。
4. 增加断言：web 产物不得出现 `fonts/harmonyos`。

**Verify:**
```bash
rg -c '@font-face' apps/web/src/ || echo 0          # 期望 0
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
! find apps/web/dist -path '*fonts/harmonyos*' | grep -q .
du -sh apps/web/dist/external                        # 期望 <= 7M
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
```
**Accept:** 两个变体产物均不含 HarmonyOS 字体；产物体积 ≤7 MB；F0 的 LCP 不劣化。

---

### F2 · SW 预缓存瘦身（5.7 MB → ≤1.2 MB raw）

**Files:** `apps/web/public/sw.js`、`apps/web/scripts/gen-sw.js`
**Steps:**
1. 预缓存清单只保留**首屏必需**：入口 chunk、`common`/`react`/`router`、CSS、`zh-cn`、`perf`、图标字体。
2. 排除懒加载重包：`echarts*`、`mammoth.browser*`、`cytoscape.esm*`、`pdf*`、`pdf.worker*`。
   `antd*` 是否首屏必需**以 F0 的 cold 场景 trace 为证据**，不得凭猜。
3. 重包改走运行时缓存（`stale-while-revalidate`），缓存名继续按站点变体隔离。
4. 断言：预缓存 raw 总量 ≤1228 KB，清单不含排除前缀。

**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
node -e "
const fs=require('fs');
for (const v of ['external','internal']) {
  const root='apps/web/dist/'+v+'/';
  const s=fs.readFileSync(root+'sw.js','utf8');
  const m=[...s.matchAll(/[\"'](assets\/[^\"']+)[\"']/g)].map(x=>x[1]);
  const uniq=new Set(m); let b=0;
  for (const p of uniq) { try { b+=fs.statSync(root+p).size } catch {} }
  console.log(v, Math.round(b/1024)+'KB', uniq.size+' entries');
}"
# 期望：两变体均 <= 1228 KB，且 entries 不含 echarts/mammoth/cytoscape/pdf
cd e2e && npx playwright test -c playwright-web-performance.config.ts   # SW-controlled 仍可用
```
**Accept:** 预缓存 ≤1228 KB raw；SW-controlled 场景仍可用；变体隔离不回退。

---

### F3 · 体积预算门禁覆盖全部重 chunk

**Files:** `scripts/check-bundle-size.sh`
**Steps:**
1. 把 echarts / mammoth / cytoscape / pdf / common / router / react 纳入预算，
   阈值取主计划 §4.3 实测 **+10% 余量**：echarts ≤370 KB gz、mammoth ≤135 KB gz、
   cytoscape ≤152 KB gz、pdf ≤105 KB gz、react ≤66 KB gz、common ≤59 KB gz、router ≤39 KB gz。
2. `SKIP` 改为「必须显式声明」：未声明的缺失 chunk 判失败；
   `SOYMUTDB_ALLOW_MISSING_HEAVY_CHUNKS=1` 为唯一逃生口且必须打印原因。
3. **脚本只接受一个目录参数（`$1`）**；两个变体必须分两次调用
   （修正 v1/v2 的 brace 展开假通过）。

**Verify:**
```bash
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
bash scripts/check-bundle-size.sh apps/web/dist/internal/assets
# 负向用例（三种，均须实测变红）：
#   a) mv 掉 echarts chunk        → 期望 FAIL（未声明缺失）
#   b) 删掉 pro chunk 且不声明     → 期望 FAIL
#   c) SOYMUTDB_ALLOW_MISSING_HEAVY_CHUNKS=1 重跑 a) → 期望 PASS 且打印原因
```
**Accept:** 三种负向用例可复现；两个变体分别受门禁约束。

---

### F4 · ECharts 按需注册

**Files:** `apps/web/src/lib/use-echarts.ts`、各图表组件
**Steps:** 用 `echarts/core` + 显式 `use([...])` 注册实际用到的 chart/component/renderer；
确认 SSG 路径不引入全量包。
**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
bash scripts/check-bundle-size.sh apps/web/dist/external/assets   # echarts <= 370 KB gz
pnpm --filter @soymutdb/web test
cd e2e && npx playwright test -c playwright-public.config.ts --grep chart
```
**Accept:** echarts gz ≤370 KB；所有图表仍正常渲染。

---

### F5 · 字体子集化 + base-aware 路径（**吸收原 C6 与原 F7**）

> **修正三轮审计：**
> ① `--unicodes='*'` 会把全部 Unicode glyph 加入集合，**抵消** `--text-file` 的子集效果 —— 必须删除。
> ② `fonttools`/`brotli` 只检查是否安装，**未钉版本**。
> ③ v3 的 F5 用 `check_font_assets.py` 验证，而该脚本由 F7 创建 —— **循环依赖**。
>    本版把 F7 并入 F5：门禁与修复同任务，**先红后绿**。

**Files:**
- `apps/admin/public/fonts/harmonyos/*`、`apps/jbrowse/public/fonts/harmonyos/*`（**删除**）
- `apps/admin/src/assets/fonts/*`、`apps/jbrowse/src/assets/fonts/*`（**新增，子集化产物**）
- `apps/admin/src/index.css`、`apps/jbrowse/src/index.css`
- `scripts/fixtures/font-subset-charset.txt`（**新增，字符集**）
- `scripts/subset-fonts.sh`（**新增，可复现的子集化脚本**）
- **`scripts/check_font_assets.py`（新增，同时吸收原 F7 的门禁职责）**
- `scripts/verify-frontend-artifacts.sh`（接入门禁）
- `docs/design/README.md`（记录字体来源与许可证）

**Steps（严格按 0 → 5 顺序，不得跳过红态）：**

**0. 先建门禁（TDD 红态）** —— 创建 `scripts/check_font_assets.py`：
   - 解析产物 CSS 中所有 `url(...)`；对每个字体 URL **断言目标文件存在**（不硬编码路径）；
   - 断言不存在 `url("/fonts/` 形式的**根绝对路径**；
   - 支持 `--assert-charset` 模式（见步骤 5）。
   跑一次，**期望失败**（当前 admin/jbrowse 的 CSS 正是根绝对 `/fonts/harmonyos/...`）——
   这个红态证明门禁真的能捕获该缺陷。

**1. 字符集（FZ-8）**，写入 `scripts/fixtures/font-subset-charset.txt`：
   - ASCII 可打印区（0x20–0x7E）；
   - **GB2312 一级常用字（3755 字）** —— 用 Python 生成，生成命令写进 `subset-fonts.sh` 注释；
   - **仓库内实际用到的全部中日韩字符**：从 `packages/i18n/src/locales/zh*`、
     `apps/{admin,jbrowse}/src/**`、`docs/` 提取并合并。
   - 该文件**入库**，使子集化结果可复现。

**2. 子集化工具链（钉版本）** —— `scripts/subset-fonts.sh` 前置检查：
   ```bash
   FONTTOOLS_SPEC='fonttools[woff]==4.63.0'
   uvx --from "${FONTTOOLS_SPEC}" pyftsubset --help >/dev/null 2>&1 || {
     echo "需要 uv + ${FONTTOOLS_SPEC}（含 brotli）"; exit 2; }
   ```
   使用 `uvx --from` 而非裸 `pip install`：版本可复现、不污染环境、符合仓内 `uv` 治理。
   对三份字重分别执行（**注意：无 `--unicodes='*'`**）：
   ```bash
   uvx --from "${FONTTOOLS_SPEC}" pyftsubset "$SRC/$w.woff2" \
     --text-file=scripts/fixtures/font-subset-charset.txt \
     --flavor=woff2 \
     --layout-features='*' \
     --output-file="$DST/$w.woff2"
   ```
   脚本末尾必须断言产物确实变小（否则说明子集化未生效）：
   ```bash
   [ "$(stat -c%s "$DST/$w.woff2")" -lt "$(stat -c%s "$SRC/$w.woff2")" ] || exit 1
   ```

**3. 落位** —— 子集化产物写入 `apps/{admin,jbrowse}/src/assets/fonts/`；
   删除 `public/fonts/harmonyos/`（public 只放不经打包的静态资源；字体必须经 Vite 处理
   以获得 base-aware 的 hash URL）。

**4. 路径** —— `index.css` 改为：
   ```css
   src: url("./assets/fonts/HarmonyOS-Sans-SC-Regular.woff2") format("woff2");
   ```
   （`./` 相对 `src/index.css` → `src/assets/fonts/…`；Vite 解析后自动加 `base` 前缀并产出 hash。）

**5. 缺字自动化检查** —— `--assert-charset` 断言：从 `packages/i18n/src/locales/zh*` 提取的
   所有 CJK 字符必须全部包含在字符集文件中；否则 FAIL。
   这是本任务的主要正确性判据（截图对比为辅助）。

**Verify:**
```bash
# 0) 红态记录（实现前跑一次，期望 FAIL）；实现后以下全部为绿
bash scripts/subset-fonts.sh
pnpm --filter @soymutdb/admin build && pnpm --filter @soymutdb/jbrowse build
python3 scripts/check_font_assets.py apps/admin/dist
python3 scripts/check_font_assets.py apps/jbrowse/dist
python3 scripts/check_font_assets.py --assert-charset apps/admin/dist
# 1) 路径 base-aware：产物 CSS 不得含根绝对 /fonts
! rg -q 'url\("/fonts/' apps/admin/dist/assets/*.css apps/jbrowse/dist/assets/*.css
# 2) 字体已被 Vite 处理（hash 资源），且体积受控
find apps/admin/dist/assets -name '*HarmonyOS*' -printf '%s %p\n' | sort -rn | head
du -ch apps/admin/dist/assets/*HarmonyOS* apps/jbrowse/dist/assets/*HarmonyOS* | tail -1   # <= 6 MB
# 3) 缺字检查（主要判据）
python3 scripts/check_font_assets.py --assert-charset apps/jbrowse/dist
# 4) 负向用例（写在门禁的单元测试里，不以字面量出现在计划中）
python3 -m pytest scripts/test_font_assets_rules.py -q
```
**Accept:** **门禁红→绿的转入有证据**；字体总量 ≤6 MB；产物 CSS 不含根绝对 `/fonts/`；
**i18n 全部 CJK 字符被字符集覆盖**；两类回归（文件缺失 / 根绝对路径）均有单元测试；
admin/jbrowse 中文页面截图无缺字。

---

### F6 · 入口 chunk 拆分

**Files:** `apps/web/vite.config.ts`、路由文件
**依赖：** F0（模块图）、F3（预算门禁）
**Steps:** 用 F0 的模块图确认 `index-*.js`（565 KB raw / 164 KB gz）中哪些属于非首屏；
可延后部分改动态 `import()`；目标 gz ≤140 KB。
**Verify:**
```bash
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
bash scripts/check-bundle-size.sh apps/web/dist/external/assets   # entry <= 200 KB gz（下调后阈值在 F3 中登记）
cd e2e && npx playwright test -c playwright-web-performance.config.ts   # LCP 不得劣于 F0 基线
```
**Accept:** entry gz 下降且 LCP 不劣于 F0 基线；F3 的 entry 阈值随之下调并登记。

---

### F8 · 静态资源缓存分层（覆盖**全部三个静态应用**）

> **三轮审计 S12：** v3 只列 web `_headers` 与 web/admin nginx，遗漏了
> admin `_headers`、jbrowse `_headers` 与 jbrowse nginx，无法保证三应用策略一致。

**Files:**
- `apps/web/public/_headers`
- **`apps/admin/public/_headers`**
- **`apps/jbrowse/public/_headers`**
- `infra/docker/web-nginx.conf`
- **`infra/docker/admin-nginx.conf`**
- **`apps/jbrowse/nginx.conf`**

**Steps:**
1. 三层缓存策略（三应用一致）：
   - hash 资源（`assets/*-[hash].*`）：`Cache-Control: public, max-age=31536000, immutable`
   - HTML 与无扩展名 SSG 路径：`no-cache` + `ETag`
   - `/samples/*.html`（仅 web）：从 5 min 收敛为短缓存 + `must-revalidate`
2. **只定义行为，不做结构变更**：本任务直接改三份 `_headers` 与三份 nginx 配置的缓存指令。
   结构去重（抽公共片段、合并 server 块）属 Phase 4 C3，**C3 必须保持本任务定义的字节等价**。

**Verify:**
```bash
python3 scripts/check_artifact_headers.py
python3 scripts/check_nginx_security_headers.py
# 三份 _headers 都存在且均含三层策略
for f in apps/web/public/_headers apps/admin/public/_headers apps/jbrowse/public/_headers; do
  test -f "$f" && grep -q 'immutable' "$f" || { echo "缺少分层策略: $f"; exit 1; }
done
```
**Accept:** 三个静态应用的缓存策略一致；两个门禁绿；行为已冻结，供 C3 做字节等价的去重。

---

### D1 · 匿名读路径分级配额

**Files:** `infra/nginx/conf.d/default.conf`、`infra/nginx/cloudflare-tunnel.conf`、`docs/ops/`（策略文档）
**Steps:** 与 Phase 1 的 S-2/S-3 联动。**分级（冻结）：**

> **与 S-2 的不变量（三轮审计 B3）：** 应用层 `public_read_rate_limit_per_minute`
> **必须 ≥** 本表匿名读的边缘等效速率（100 r/s × 60 = 6000/min），
> 否则应用层成为实际瓶颈，本表的边缘配额完全失效。修改任一侧时必须同步核算另一侧。

| 端点类别 | 边缘配额 | 应用层（S-2） |
|---|---|---|
| `/health`、`/metrics` | 无限流 | 豁免 |
| 匿名读（`/api/v1/{variants,genes,mutants,search,stats}`） | 100 r/s burst 200 | fail-open |
| 认证（`/api/v1/auth/*`） | 10 r/s burst 20 | fail-closed |
| BLAST 提交（`/api/v1/blast/*`） | 1 r/s burst 5 | fail-closed |
| JBrowse Range（`/data/`、`/jbrowse-data/`） | **按连接数（`limit_conn`），不按请求频率** | 不适用 |

**注意（与 Phase 4 P1 的接口）：** 容量压测在**隔离基准网络**中通过
`SOYMUTDB_RATE_LIMIT_ENABLED=false` 关闭应用层限流，**不经过本任务的边缘配额**；
本任务的配额由 P2（公网防滥用基线）验证。两条基线互不干扰。

**Verify:**
```bash
python3 scripts/check_nginx_security_headers.py
# 断言：/data/ 与 /jbrowse-data/ 的 location 不含 limit_req，但含 limit_conn
```
**Accept:** 配额可配置、可观测、可解释；Range 路径不被请求频率限流误伤。

---

### D2 · 分页契约统一并固化门禁

> **修正二轮审计：** 强制所有列表端点同一上限会要么浪费要么过载。改为**按类别**定义。

**Files:** `apps/api/app/api/v1/*.py`、`apps/api/app/main.py`、新增 `scripts/check_pagination_contract.py`
**Steps:**
1. **按端点类别定义上限（FZ-12，冻结）：**

   | 类别 | 上限 | 端点 |
   |---|---|---|
   | 检索/聚合 | 50 / 20 | `search`、`search/suggest`、`stats/*` |
   | 实体列表 | 200 | `variants`、`genes`、`mutants`、`publications` |
   | 内部/管理 | 100 | `admin/*`、`audit` |

2. cursor 为主；`homologs` 的 offset 兼容层标注弃用与移除条件
   （写进 `docs/dev/database-core-contract.md`）。
3. `scripts/check_pagination_contract.py` 断言的是
   **「实现上限 == 文档声明上限」**，**不要求跨类别相等**；同时断言 `x-pagination` 存在于每类端点。
4. **只枚举真正的列表端点（三轮审计 G4）**：`/api/v1/stats/*` 下多数端点（`/dashboard`、
   `/variant-types`、`/density` 等）**没有** `limit`/`cursor` 参数，**不得**纳入分页门禁。
   门禁的端点清单必须从路由器实际签名提取（有 `limit` 或 `cursor` 参数才算列表端点），
   不得手写清单。

**Verify:**
```bash
python3 scripts/check_pagination_contract.py
(cd apps/api && .venv/bin/python -m pytest tests -q -k "pagination or keyset or cursor")   # 需 PostgreSQL
# 负向：把某端点实现上限改成与文档不符 → 期望 FAIL
```
**Accept:** 每类端点的上限有机器校验；`homologs` 弃用路径有文档记录。

---

### C1 · 删除死代码并按证据扩大扫描

> **位置变更：** 从 W0 移入本阶段 —— `RateLimitMiddleware` 是「删除」还是「接线」
> 由 Phase 1 的 S-2 决定（S-2 已冻结为**接线**，故本任务删除的对象是 `TimingMiddleware`
> 与 S-2 未接线的残留符号）。

**Files:** `apps/api/app/core/middleware.py`、新增 `scripts/check_dead_code.py`
**依赖：** Phase 1 S-2 已完成（已决定接线）
**Steps:**
1. 用 vulture（后端）与 `pnpm exec knip`（前端）列出候选。
2. **逐个 grep 复核**，只删「全仓零引用且无测试引用」的符号；有测试引用的先改测试再删。
3. 把扫描器接入 `scripts/verify-backend-tests.sh`，**只对新增条目报错**（baseline 白名单带 reason）。

**Verify:**
```bash
python3 scripts/check_dead_code.py
grep -rn "TimingMiddleware" --include='*.py' apps/ || echo "0 hits"   # 期望 0
(cd apps/api && .venv/bin/python -m pytest tests -q)                   # 需 PostgreSQL
# 负向：新增一个无人引用的函数 → 期望 FAIL（不在 baseline 白名单）
```
**Accept:** 扫描器进共享脚本；baseline 白名单每条带 reason；`RateLimitMiddleware` 被接线而非删除。

---

## 2. 阶段内任务顺序

| 顺序 | 任务 | 理由 |
|---|---|---|
| 1 | F0 | 没有基线，「不劣化」无法判定 |
| 2 | F1 | 删 13 MB 死负载，收益最大、风险最低 |
| 3 | F2 | SW 瘦身（用 F0 的 cold trace 决定 antd 是否首屏） |
| 4 | F3 | 门禁先覆盖全部重 chunk，防止 F4/F6 引入回退 |
| 5 | F4 | ECharts 按需（受 F3 约束） |
| 6 | F5（含 C6、F7） | 先建门禁（**红**）→ 子集化 + 改路径 → 门禁**绿**；原子交付 |
| 7 | F6 | 入口拆分（受 F3 约束，并由 F0 的模块图驱动） |
| 8 | F8 | 缓存分层（三应用，定义行为，供 C3 做字节等价去重） |
| 9 | D1 | 边缘配额（依赖 Phase 1 的 S-2/S-3） |
| 10 | D2 | 分页契约（Phase 4 的 P4 依赖它） |
| 11 | C1 | 依赖 Phase 1 的 S-2 决策 |

---

## 3. 边界与约束

- **F1/F2/F6 不得同时进行**：三者的体积/预缓存数字互相影响，必须串行以便归因。
- **F5 是原子任务**：路径变更与子集化必须同 commit，禁止「先改路径后子集化」的中间态进入发布。
- **D1 不得使用 `SOYMUTDB_RATE_LIMIT_ENABLED`**：那是 Phase 4 P1 的基准专用开关，
  生产与公网路径永远保持限流开启。
- **F3 的阈值不得为了通过而放宽**：若某 chunk 超预算，必须先优化（如 F4 的按需注册），
  确需放宽时必须在本文件登记理由与替代缓解措施。

---

## 4. 阶段退出判据

```bash
# 1. 前端体积与预缓存
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
du -sh apps/web/dist/external            # <= 7 MB
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
bash scripts/check-bundle-size.sh apps/web/dist/internal/assets
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/internal

# 2. 字体
bash scripts/subset-fonts.sh
python3 scripts/check_font_assets.py apps/admin/dist
python3 scripts/check_font_assets.py apps/jbrowse/dist
python3 scripts/check_font_assets.py --assert-charset apps/admin/dist

# 3. 契约与治理
python3 scripts/check_pagination_contract.py
python3 scripts/check_nginx_security_headers.py
python3 scripts/check_artifact_headers.py
python3 scripts/check_plan_commands.py
python3 scripts/check_dead_code.py

# 4. 全量前端门禁
pnpm exec turbo run lint --force
pnpm typecheck
pnpm test
bash scripts/verify-frontend-artifacts.sh
```

**需环境的判据**（本机不可执行 → 由 CI 补验，标「未验证」）：
```bash
cd e2e && npx playwright test -c playwright-web-performance.config.ts
(cd apps/api && .venv/bin/python -m pytest tests -q -k "pagination or keyset or cursor")
(cd apps/api && .venv/bin/python -m pytest tests -q)
```

**DoD 勾选项：**
- [ ] F0 三场景基线入库，含**双产物**与 INP 交互样本，并声明采集方式局限
- [ ] 产物 ≤7 MB；SW 预缓存 ≤1228 KB raw
- [ ] 重 chunk 全部纳入预算，三种负向用例变红
- [ ] 字体总量 ≤6 MB；产物无根绝对 `/fonts/`；**i18n 全部 CJK 字符被字符集覆盖**；
      **门禁红→绿的转入有证据**（F7 已并入 F5）
- [ ] `check_font_assets.py` / `check_pagination_contract.py` / `check_dead_code.py` 进共享脚本
- [ ] **lint warning ≤ 94（基线）且不增长** —— 0/0 由 Phase 4 C2 达成；
      本阶段只保证不回退（修正三轮审计 B6：v3 要求本阶段 0/0 与 C2 位置矛盾）
- [ ] D1 配额分级已配置，且**应用匿名读上限 ≥ 边缘等效速率**
- [ ] F8 覆盖**三个** `_headers` 与**三份** nginx 配置，行为已冻结供 C3 使用

---

## 5. 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| F1 删字体影响视觉 | 误判「无引用」 | 删前 `rg -c '@font-face'` + 产物 CSS 双证；回滚 = 单 commit revert |
| F2 SW 瘦身导致离线不可用 | 排除过头 | F0 的 SW-controlled 场景断言；回滚 = 恢复清单（单文件） |
| F3 预算误杀 minimal 部署 | 重 chunk 缺失 | `SOYMUTDB_ALLOW_MISSING_HEAVY_CHUNKS=1` + 打印原因 |
| F5 子集化缺字 | 字符集不全 | `--assert-charset` 自动化断言（主要判据）+ 截图对比 |
| F5 pyftsubset 缺 brotli | 工具链缺失 | 脚本前置检查并给出安装命令；未满足则任务不开始 |
| F6 拆分导致首屏缺模块 | 依赖误判 | 以 F0 的模块图为依据；LCP 劣化即回滚 |
| D1 配额过紧误伤正常用户 | 阈值偏低 | 以 P2（Phase 4）的实测 429 率校准；先宽后收 |
| D2 契约改动破坏既有游标 | 未同步测试 | 契约测试 + `homologs` 兼容层保留；失败即回滚 |
| C1 误删被动态引用的符号 | 静态扫描漏报 | 逐条 grep 复核 + 测试全绿方可提交 |

**通用回滚：** 每任务独立 commit；高风险文件（`apps/web/public/sw.js`、`apps/web/scripts/*`、
`apps/admin/src/index.css`、`apps/jbrowse/src/index.css`、`infra/docker/*-nginx.conf`）
在 PR 中单列 diff。
