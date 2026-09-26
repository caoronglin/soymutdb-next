# SoyMutDB 全栈性能优化方案（含动效专项）

> 版本：2.0 | 日期：2026-08-29
> 定位：本文档只处理**性能与动效**。`docs/dev/optimization-plan.md`（v1.0）处理的是正确性与工程卫生，两者不重叠。
> 代码基线：`main` @ 2026-08-29，Python 86.7k 行 / TS·TSX 70.9k 行，6 个 app + 5 个共享包。

> **2026-09-26 校正（历史文档）**：`packages/motion` 与 `packages/i18n` 已移除，三端现为 Vue 3；
> 文中动效/路由组件路径为迁移前记录，现状以 `apps/*/src` 为准。

---

## 0. 一句话结论

当前系统的瓶颈**不在并发能力，而在每请求/每帧的单位成本**：

- 前端：首屏关键路径 **≈2.0 MB JS + 12.7 MB 字体**，首页常驻 **3 个全屏 WebGL 循环**；
- 后端：搜索是**全表 `ILIKE '%…%'`**，埋点是 **ClickHouse 单行 INSERT**，每个数据请求多跑一次 release 查询；
- 数据层：PostgreSQL **完全跑默认参数**，无 trigram/全文索引；
- 可观测性：**前端 Web Vitals 采集器写好了但从未调用**，等于闭眼调优。

按本方案的 P0 项落地后，预期：首屏 LCP 从 ~4-6s 降到 < 2.5s，首页 GPU 占用降 ~85%，搜索 p95 从秒级降到 < 150ms。

---

## 1. 现状基线（实测自本仓库构建产物与源码）

| 层 | 指标 | 实测值 | 目标 |
|---|---|---|---|
| 前端产物 | 首屏 modulepreload 合计（未压缩） | **2.02 MB**（index 604K + antd 923K + react 194K + router 109K + antd-icons 68K + CSS 77K） | < 700 KB |
| 前端产物 | 字体（HarmonyOS Sans SC ×3 全量 CJK） | **12.7 MB** | < 500 KB |
| 前端产物 | 懒加载重依赖 | echarts 1019K / pdf.worker 1344K / mammoth 488K / cytoscape 433K / pdf 326K — **均已正确动态导入** ✅ | 保持 |
| 前端运行时 | 首页 WebGL2 上下文数 | **3 个**（Carousel `effect="fade"` 保留全部 slide） | 1 个 |
| 前端运行时 | 首页常驻 rAF 循环 | 3 条，无限帧率，无离屏/后台门控 | 0 条（离屏时） |
| 后端 | `SearchService.global_search` | 3 次串行 `ILIKE '%q%'` 全表扫描，无缓存 | < 150 ms p95 |
| 后端 | `resolve_release_context` | 每请求 1 次 DB 查询（active release 极少变动） | 60s 缓存 |
| 后端 | `track.gif` 写入 | **每次事件 1 行 INSERT** 到 ClickHouse MergeTree | 批量 1k 行 / 1s |
| 数据层 | GIN / trigram / tsvector 索引 | **0 个**（24 个迁移全为 B-tree） | ≥ 6 个 |
| 数据层 | PostgreSQL 调参 | 全部默认（`shared_buffers=128MB`） | 见 §4.1 |
| 基础设施 | nginx `proxy_cache` / brotli / HTTP2 | 均未启用 | 见 §4.3 |
| 可观测性 | `initPerfMonitoring()` 调用点 | **无**（`apps/web/src/lib/perf.ts` 从未被 import） | 生产 25% 采样 |

### 已完成的前序工作（v1.0 计划中已落地，本文档不再重复）

- ✅ 1.1 Admin Vite React chunk 精确正则（`apps/admin/vite.config.ts:122`）
- ✅ 1.2 CI Turbo 远程缓存（`.github/workflows/ci.yml:80`）
- ✅ 2.1 CSRF 统一到 `packages/api-client/src/csrf.ts`，`auth.ts:176/208` 已接线
- ✅ 2.2 `withRetry` 已接入 `authRequest`（`auth.ts:196/226`，幂等方法 1 次重试）

### 顺带发现的正确性问题（非性能，但优先级同样高）

- ⚠️ `apps/worker/src/soymutdb_worker/tasks/ingest.py:657` 的 `import_gff3` 与 `:724` 的 `import_mutant_lines` **只统计行数，从不落库**——流式读完整个 S3 对象后返回 count，无任何 INSERT。GFF3 导入目前是空操作。
- ⚠️ `services/analytics_service.py:32` 的 `hash_ip` 使用硬编码盐 `"soymutdb-analytics"`，IP 哈希可被彩虹表反解。应改为读取部署密钥。
- ⚠️ `infra/nginx/conf.d/default.conf:241` 的 `location ~* \.[0-9a-f]{8,}\.(js|css|woff2?)$` 是 server 级正则，会把 `/soymutdb-admin/assets/*.js` 与 `/soymutdb-jbrowse/assets/*.js` 一并代理到 `web_frontend`。`/admin/` 有 `^~` 前缀保护，但 Pages 上的 `/soymutdb-admin/` 路径没有。

---

## 2. P0 — 首屏与首页（1 个 Sprint，收益最大）

### P0-1 首页 3 个 WebGL 流体画布常驻满帧渲染

**位置**：`apps/web/src/components/home/antd-home.tsx:233`（AntD `Carousel`）→ `components/fluids/fluid-gradient.tsx`

**问题拆解**

1. AntD `Carousel effect="fade"` 保留全部 slide 在 DOM 中（只切 opacity），因此 **3 个 `FluidGradient` 同时挂载** → 3 个 WebGL2 上下文 + 3 条 rAF 循环，其中 2 个完全不可见。
2. 片元着色器是 **5 阶 FBM × 3 层 domain warping**（`q`/`r`/`f`）≈ 每像素 15 次 `noise()`，每次 `noise()` 4 次 `hash()`（含 `sin`）。在 1280×340 @ DPR2 下约 2.6M 片元/帧 × 60 次 `sin` → 单画布就能吃满中端集显。
3. `frame()` 无帧率上限：120Hz 屏上功耗与 GPU 负载直接翻倍。
4. 无 `IntersectionObserver`：滚动到页面底部后仍在渲染。
5. 无 `visibilitychange` 处理：切到后台标签页仍在渲染。
6. `dpr = min(devicePixelRatio, 2)`：无任何渲染缩放。

**修复（4 步）**

**Step 1 — 全局单帧调度器**（一个 rAF 驱动所有画布，统一门控与帧率上限）

新建 `apps/web/src/lib/motion/ticker.ts`：

```ts
export type FrameFn = (now: number) => void;

/**
 * 全局单帧调度器。所有常驻动画（T3/T4）注册到这里，
 * 由它统一负责：帧率上限、页面可见性、订阅者为空时自动停机。
 */
class MotionTicker {
  private subs = new Set<FrameFn>();
  private raf = 0;
  private last = 0;

  constructor(private intervalMs: number) {}

  subscribe(fn: FrameFn): () => void {
    this.subs.add(fn);
    this.start();
    return () => {
      this.subs.delete(fn);
      if (this.subs.size === 0) this.stop();
    };
  }

  setFps(fps: number) { this.intervalMs = 1000 / fps; }

  private start() {
    if (this.raf) return;
    const loop = (now: number) => {
      this.raf = requestAnimationFrame(loop);
      if (now - this.last < this.intervalMs) return;   // 帧率上限
      this.last = now;
      for (const fn of this.subs) fn(now);
    };
    this.raf = requestAnimationFrame(loop);
  }

  private stop() { cancelAnimationFrame(this.raf); this.raf = 0; }
}

export const motionTicker = new MotionTicker(1000 / 30);   // 30fps 足够表现流体
```

页面隐藏时整体停机（`main.tsx` 或 ticker 内部）：

```ts
document.addEventListener("visibilitychange", () => {
  motionTicker.setFps(document.visibilityState === "visible" ? 30 : 1);
});
```

**Step 2 — 画布只在可见时才渲染**

在 `fluid-gradient.tsx` 的 effect 内加 IntersectionObserver + 由 `motionTicker` 驱动：

```ts
let visible = false;
const io = new IntersectionObserver(
  ([entry]) => { visible = entry.isIntersecting; },
  { threshold: 0.01 },
);
io.observe(node);

const unsubscribe = motionTicker.subscribe((now) => {
  if (!visible) return;                       // 离屏：完全不提交 draw call
  gl.uniform1f(uTime, (now - start) / 1000);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
});

return () => { io.disconnect(); unsubscribe(); /* …现有清理… */ };
```

**Step 3 — 降采样 + 降阶**

```ts
// 渲染分辨率 = CSS 尺寸 × DPR(≤1.5) × 0.6；流体渐变是低频信号，放大后肉眼无差
const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
const RENDER_SCALE = 0.6;
node.width  = Math.floor(width  * dpr * RENDER_SCALE);
node.height = Math.floor(height * dpr * RENDER_SCALE);
```

```glsl
// FRAG: fbm 五阶 → 三阶（视觉差异 <5%，GPU 成本 -40%）
float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
    for (int i = 0; i < 3; i++) { v += a * noise(p); p = rot * p * 2.0; a *= 0.5; }
    return v;
}
```

**Step 4 — 只挂载当前 slide 的画布**

`antd-home.tsx` 改为受控 Carousel，只给 active slide 渲染 `<FluidGradient>`，其余用静态 CSS 渐变占位：

```tsx
const [active, setActive] = React.useState(0);
const palette = HERO_PALETTES[active % HERO_PALETTES.length];

<Carousel afterChange={setActive} autoplay autoplaySpeed={5200} effect="fade">
  {HERO_SLIDES.map((slide, i) => (
    <div key={slide.titleKey}>
      {i === active
        ? <FluidGradient reduced={reduced} colors={palette} …>…</FluidGradient>
        : <div style={{ background: `linear-gradient(150deg, ${palette.join(", ")})`, minHeight: 340 }}>…</div>}
    </div>
  ))}
</Carousel>
```

> 注意：`colors` 是 `useEffect` 依赖项。`HERO_PALETTES[i % len]` 是模块常量，引用稳定；但**任何**内联数组字面量都会导致 shader 程序每次渲染重建。建议把 `colors` 改为 `useMemo` 或在 effect 内用 `colors.join()` 作为依赖。

**验收**

```bash
pnpm --filter @soymutdb/web build
npx playwright test e2e/tests/home.spec.ts     # 若存在
# 手工：DevTools → Performance，录制 10s 首页空闲
#   期望：GPU 帧时间 < 8ms；Long Task 数 0；滚动出 hero 后 Frames 曲线归零
```

**回滚**：单文件/单组件 revert，无数据影响。

---

### P0-2 12.7 MB CJK 字体无子集化、无 preload

**位置**：`apps/web/src/style.css` 的 `@font-face` 块，`apps/web/public/fonts/harmonyos/`、
`apps/admin/public/fonts/harmonyos/`

> 状态（2026-09-26）：按 `docs/dev/vue-migration-recovery-plan.md`（保留门户字体、两套应用统一字体），
> 门户与管理端均已引用自托管 HarmonyOS Sans SC。本项不再包含“删除门户字体”；待办收敛为**子集化**
> 与 **preload/回退**，旧计划 T26 的删除步骤已被取代。

实测：`Regular 4178.7 KB / Medium 4240.0 KB / Bold 4300.3 KB`。`font-display: swap` 已配置（不会 FOIT），但字体 URL 只有解析完 CSS 才被发现，而 CSS 又在 JS chunk 之后 → **LCP 文本会经历一次完整换字体**，CLS 抬升。

**修复**

1. **子集化**（最有效）。新增 `tools/subset-fonts.sh`：

```bash
#!/usr/bin/env bash
# pip install fonttools brotli
# cjk-common.txt = GB2312 一级汉字(3755) + 常用标点 + 拉丁 + 数字，约 3900 字符
set -euo pipefail
for w in Regular Medium Bold; do
  pyftsubset "apps/web/public/fonts/harmonyos/HarmonyOS-Sans-SC-${w}.ttf" \
    --output-file="apps/web/public/fonts/harmonyos/HarmonyOS-Sans-SC-${w}.subset.woff2" \
    --flavor=woff2 \
    --text-file=tools/cjk-common.txt \
    --layout-features='' --no-hinting --desubroutinize
done
```

预期：4.2 MB → **≈ 380 KB/字重**（合计 1.1 MB，仍偏大但可接受）。

2. **更激进的选项**（推荐二选一）：
   - 只保留 **Regular + Bold** 两个字重（Medium 用 `font-synthesis` 或直接用 Regular 渲染），合计 ~760 KB；
   - 或直接放弃自托管 CJK，改用系统字体栈 `system-ui, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC"` → **0 字节**，且中文渲染在各平台上是最优的。

3. **preload 关键字重**。`index.html`：

```html
<link rel="preload" as="font" type="font/woff2" crossorigin
      href="/fonts/harmonyos/HarmonyOS-Sans-SC-Regular.subset.woff2">
```

4. **消除换字抖动**（`index.css`）：

```css
@font-face {
  font-family: "HarmonyOS Fallback";
  src: local("PingFang SC"), local("Microsoft YaHei"), local("Noto Sans CJK SC");
  size-adjust: 97%;
  ascent-override: 92%;
  descent-override: 22%;
}
:root {
  --font-sans: "HarmonyOS Sans SC", "HarmonyOS Fallback", system-ui, sans-serif;
}
```

**验收**：`curl -sI` 字体 ≤ 400 KB；Lighthouse CLS < 0.1；Network 面板确认字体在 CSS 之前开始下载。

---

### P0-3 antd 923 KB 进入首屏关键路径

**位置**：`apps/web/src/lib/antd.ts`（39 个组件的桶文件）+ `vite.config.ts:139` `manualChunks`

首页只用 `Button / Typography / Card / Carousel / Row / Col / Space / Input / Empty / Alert`，但因为所有路由都从这个桶文件导入，**Rollup 无法对未使用的组件做摇树**，`Table / Form / Select / Upload / Modal / Drawer …` 全部进了被 `modulepreload` 的 `antd` chunk。

**修复（推荐方案 A：拆桶 + 按引用图分包）**

1. 删除 `src/lib/antd.ts`，改为两个门面：

```ts
// apps/web/src/lib/antd-core.ts —— 首屏必需（≈10 个组件）
export { default as Button } from "antd/es/button";
export { default as Typography } from "antd/es/typography";
export { default as Card } from "antd/es/card";
export { default as Row } from "antd/es/row";
export { default as Col } from "antd/es/col";
export { default as Space } from "antd/es/space";
export { default as Input } from "antd/es/input";
export { default as Spin } from "antd/es/spin";
export { default as Empty } from "antd/es/empty";
export { default as Alert } from "antd/es/alert";
export { default as Carousel } from "antd/es/carousel";
export { default as ConfigProvider } from "antd/es/config-provider";
export { default as theme } from "antd/es/theme";

// apps/web/src/lib/antd-heavy.ts —— 只在表格/表单路由使用，禁止在 __root 与首页导入
export { default as Table } from "antd/es/table";
export { default as Form } from "antd/es/form";
export { default as Select } from "antd/es/select";
export { default as Modal } from "antd/es/modal";
export { default as Drawer } from "antd/es/drawer";
export { default as Tabs } from "antd/es/tabs";
export { default as Descriptions } from "antd/es/descriptions";
export { default as Pagination } from "antd/es/pagination";
export { default as Tooltip } from "antd/es/tooltip";
export { default as DatePicker } from "antd/es/date-picker";
export { default as Upload } from "antd/es/upload";
export { default as Statistic } from "antd/es/statistic";
export { default as Tag } from "antd/es/tag";
export { default as Badge } from "antd/es/badge";
```

2. `manualChunks` 只保留 **antd 底座**（rc-* + theme/util）为独立 chunk，组件交给 Rollup 按引用图自然分包：

```ts
manualChunks(id: string) {
  if (!id.includes("node_modules")) return;
  if (/node_modules\/(react|react-dom|react-is|scheduler|use-sync-external-store)(\/|@)/.test(id)) return "react";
  if (id.includes("@tanstack")) return "router";
  if (id.includes("echarts")) return "echarts";
  if (id.includes("@ant-design/icons-svg")) return "antd-icons";
  // antd 底座：rc-* 与 antd 的 theme/_util/config-provider —— 所有 antd 组件共享，
  // 必须同置（拆开会触发 rc→antd→rc 的 ES module 初始化循环，线上白屏）。
  if (id.includes("/rc-") || /antd\/es\/(theme|_util|config-provider|style|locale)\//.test(id)) {
    return "antd-core";
  }
  // 其余 antd 组件显式返回 undefined：由 Rollup 按引用图放进真正使用它们的 chunk，
  // Table/Form/Select 因此会落进搜索/管理等异步路由，而不再首屏加载。
  if (id.includes("/antd/") || id.includes("@ant-design")) return;
}
```

> ⚠️ 这一步**必须**在修改后做一次生产构建 + `preview` 冒烟，确认没有复现 `createContext undefined` 的 chunk 循环。`apps/web/src/lib/antd.ts` 文件头的注释已经记录过这个坑，改动后请在注释里同步新的分包约定。

3. 校验：构建后 `dist/index.html` 的 `modulepreload` 列表里**不应再出现 antd-heavy 相关 chunk**。

**预期**：首屏 JS 2.02 MB → **≈ 1.0 MB**（gzip 后 ≈ 320 KB → 160 KB）。

---

### P0-4 搜索全表 ILIKE 扫描 + 零缓存

**位置**：`apps/api/app/services/search_service.py`

```python
# 现状：3 次串行、全字段 ILIKE '%q%'、加载完整 ORM 实体、无缓存
Gene.id.ilike(pattern), Gene.name.ilike(pattern), Gene.description.ilike(pattern)
```

B-tree 索引对 `%…%` 无效 → 全表 Seq Scan。基因表 + 突变体表 + 文献表三连扫。

**修复**

1. **建索引**（新迁移 `apps/api/migrations/versions/0024_search_indexes.py`）：

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_bigm")   # 中文/日文 2-gram，支持 LIKE '%…%'

    # 注意：CONCURRENTLY 不能在事务中执行，迁移需设置 autocommit_block
    for stmt in (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_genes_name_bigm"
        "  ON genes USING gin (name gin_bigm_ops)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_genes_description_bigm"
        "  ON genes USING gin (description gin_bigm_ops)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ml_name_bigm"
        "  ON mutant_lines USING gin (name gin_bigm_ops)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pub_title_bigm"
        "  ON publications USING gin (title gin_bigm_ops)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_pub_abstract_bigm"
        "  ON publications USING gin (abstract gin_bigm_ops)",
    ):
        op.execute(stmt)
```

> `pg_bigm` 相对 `pg_trgm` 的优势：2-gram 对 CJK 有效，`gin_bigm_ops` 直接加速 `LIKE '%keyword%'`，且不需要改写 SQL。若发行版镜像无此扩展，退化为 `pg_trgm` + `gin_trgm_ops`（对 CJK 效果较弱，但对基因 ID / 英文名足够）。

2. **三次查询并发化 + 只取需要的列**：

```python
genes, mutants, pubs = await asyncio.gather(
    self._search_genes(db, pattern, per_type),
    self._search_mutant_lines(db, pattern, per_type),
    self._search_publications(db, pattern, per_type),
)
```

```python
stmt = (
    select(Gene.id, Gene.name, Gene.biotype)          # 不再拉 description 全文
    .where(or_(Gene.id.ilike(pattern), Gene.name.ilike(pattern)))
    .limit(limit)
)
```

3. **加缓存**（与 stats/news 同一套 `get_or_set`）：

```python
from ...services.cache import get_or_set
from ...core.config import get_settings

# 搜索结果 60s 缓存；suggest 30s
return await get_or_set(
    "search:global",
    ttl=60,
    params={"q": query, "types": types, "limit": limit},
    loader=lambda: self._global_search_uncached(db, query, types, cursor, limit),
)
```

4. **限流 suggest**：`/search/suggest` 目前无限流、无缓存，前端若无防抖会每个按键打一次全表扫描。后端建议加 `limit` 上限与 Redis 冷却；前端（`packages/api-client/src/search.ts:79`）建议接入 300ms 防抖。

**验收**：`EXPLAIN ANALYZE` 确认走 `Bitmap Index Scan`；`p95(/api/v1/search)` < 150ms。

---

### P0-5 ClickHouse 单行 INSERT（埋点）

**位置**：`apps/api/app/services/analytics_service.py:82`

每次 `track.gif` 命中（页面浏览、点击、搜索、widget，外加 `perf.ts` 的 6 个 Web Vitals 指标）都提交**单行 INSERT** 到 `analytics_events`（MergeTree，按月分区）。ClickHouse 每次 INSERT 生成一个 part → part 数量爆炸、后台 merge 线程饱和、最终触发 `Too many parts` 写入失败。

**修复（方案 A：服务端 async_insert，零应用改动，推荐先上）**

`clickhouse_connect` 支持在客户端级别下发设置：

```python
# apps/api/app/core/database.py
_clickhouse_client = await clickhouse_connect.get_async_client(
    host=settings.clickhouse_host,
    port=settings.clickhouse_port,
    username=settings.clickhouse_user,
    password=settings.clickhouse_password,
    database=settings.clickhouse_database,
    secure=settings.clickhouse_secure,
    connect_timeout=settings.clickhouse_connect_timeout,
    send_receive_timeout=settings.clickhouse_send_receive_timeout,
    settings={                                   # ← 新增
        "async_insert": 1,
        "wait_for_async_insert": 0,              # 不等待落盘，fire-and-forget
        "async_insert_max_data_size": 1_000_000, # 攒够 1MB 刷一次
        "async_insert_busy_timeout_ms": 1000,    # 或最多等 1s
    },
)
```

> 代价：`wait_for_async_insert=0` 下客户端无法感知写入失败。埋点属可丢失数据，可接受；但要确保 `logger.warning("analytics_insert_failed")` 之外增加 Prometheus 计数器。

**修复（方案 B：应用侧批量缓冲，吞吐更高）**

在 API 进程内维护 `asyncio.Queue`，后台任务每 1s 或满 1000 行批量 INSERT，进程退出时 flush：

```python
# apps/api/app/services/analytics_buffer.py
_QUEUE: asyncio.Queue[dict] | None = None
_BATCH_SIZE = 1000
_FLUSH_INTERVAL = 1.0

async def enqueue_event(row: dict) -> None:
    q = get_queue()
    try:
        q.put_nowait(row)
    except asyncio.QueueFull:
        ANALYTICS_DROPPED.inc()          # 埋点可丢，但要可见

async def _flush_loop() -> None:
    client = await get_clickhouse_client()
    while True:
        batch: list[dict] = []
        try:
            first = await asyncio.wait_for(get_queue().get(), timeout=_FLUSH_INTERVAL)
            batch.append(first)
            while len(batch) < _BATCH_SIZE and not get_queue().empty():
                batch.append(get_queue().get_nowait())
        except asyncio.TimeoutError:
            if not batch:
                continue
        if batch:
            await client.insert(table="analytics_events", data=batch, column_names=list(batch[0]))
            ANALYTICS_BATCH_SIZE.observe(len(batch))
```

在 `main.py` 的 `lifespan` 中启动/取消该循环。

**顺带**：`analytics_events` 的 `ORDER BY (timestamp, event_type, session_id)` 对「按天/按类型聚合」不友好，建议改为 `ORDER BY (event_type, toDate(timestamp), session_id)`，并给 `session_id` 加 `bloom_filter` 跳数索引。

---

### P0-6 每个数据请求多跑一次 release 查询

**位置**：`apps/api/app/services/release_context.py:85`

`resolve_release_context` 在每个 `/variants`、`/genes`、`/tracks` 请求上都执行一次 `SELECT … FROM releases JOIN active_release`。active release 只在发布时变动（天级/周级）。

**修复**：走现有 `get_or_set`，TTL 60s；发布/回滚时按 key 失效。

```python
from ...services.cache import get_or_set

async def resolve_release_context(db: AsyncSession, requested_release_id: int | None = None) -> ReleaseContext:
    return await get_or_set(
        "release:context",
        ttl=60,
        params={"rid": requested_release_id},
        loader=lambda: _load_release_context(db, requested_release_id),
    )
```

> 注意 `ReleaseContext` 不是 dict，`get_or_set` 通过 `model_dump` 做 JSON 编码；`_load_release_context` 返回 dataclass 时需在 loader 内先 `.identity()` 化，或在 `release_service` 发布/回滚成功后调用 `invalidate("release:context*")`。`cache.py` 目前没有失效接口，需补一个 `delete_prefix(prefix)`（用 `SCAN` + `UNLINK`，避免 `KEYS`）。

**收益**：每个数据请求省 1 次 DB 往返 + 1 次 JOIN；在 `/variants?limit=200` 这类高频调用上，RT 降 10-25%。

---

### P0-7 前端零 RUM（Web Vitals 采集器从未被调用）

`apps/web/src/lib/perf.ts` 实现了完整的 LCP / FID / INP / CLS / FCP / TTFB 采集 + `sendBeacon` 上报，**但全仓库没有任何 import**。也就是说生产环境完全没有真实用户性能数据——后续所有优化都无法验证。

**修复**（`main.tsx` 末尾）：

```ts
if (import.meta.env.PROD) {
  void import("./lib/perf").then(({ initPerfMonitoring }) => {
    initPerfMonitoring({ endpoint: "/track.gif", sampleRate: 0.25 });
  });
}
```

配套（后端）：`analytics_service` 的 `event_type` 枚举需接受 `"performance"`，并落到独立的 `web_vitals` 表（不要混进 `analytics_events`，采样率与保留期不同）。

配套（监控）：Grafana 新增 `Frontend Web Vitals` 面板（p75 LCP / INP / CLS，按路由分组），并加告警：

```yaml
- alert: FrontendLcpP75Poor
  expr: histogram_quantile(0.75, sum(rate(soymutdb_web_vitals_lcp_bucket[1h])) by (le)) > 4000
  for: 30m
  labels: { severity: warning }
```

**这是所有后续优化的前置项——先测量，再动手。**

---

## 3. 动效专项（Animation & Motion）

### 3.1 设计原则

现有 `AnimationProvider`（`lib/animation-context.tsx`）+ `motion-policy.ts` 已经做了**静态降级**（`prefers-reduced-motion` / Save-Data / 硬件并发数 / 移动端 → `minimal`），这部分是好的。缺的是三件事：

1. **没有运行时的帧预算治理**——降级只在首帧判定一次，之后即使掉帧也不再调整；
2. **没有统一的调度/暂停中心**——每个动画组件各自持有 rAF，各自管生管死；
3. **没有成本分级**——`box-shadow` 动画和 `opacity` 动画被同等对待。

### 3.2 动效分级模型（Tier）

| 档 | 名称 | 本项目实例 | 单帧预算 | 降级规则 |
|---|---|---|---|---|
| **T0** | 即时反馈 | 按钮 `:active`、hover 态、输入框聚焦环 | ≤ 120ms 总时长，纯 `transform`/`opacity` | **永不降级**（交互反馈是可用性底线） |
| **T1** | 状态过渡 | 下拉展开、Tab 切换、Modal 出入、路由 View Transition | ≤ 200ms | `minimal` → 时长压到 80ms 或直接切 |
| **T2** | 进入揭示 | `Reveal` / `FadeUp` / `TextReveal` / 数字滚动 | ≤ 300ms，仅首屏元素，`once: true` | 低资源设备 → 关闭 |
| **T3** | 环境动画 | `DnaBackground`、`gradient-shift`、`glow-pulse`、骨架屏 `shimmer` | 常驻，CPU < 2% | 离屏/后台 → **暂停**；低资源 → 静态 |
| **T4** | 重装饰 | `FluidGradient`（WebGL）、粒子、canvas 可视化 | 常驻，GPU 帧时间 < 8ms | 离屏/后台 → **卸载上下文**；移动端/低资源 → 静态帧 |

**约束**：T3+T4 同时活跃的画布数 ≤ 1；T3 常驻动画节点数 ≤ 16。

### 3.3 统一调度中心

在 §P0-1 的 `MotionTicker` 之上补一个**自适应降档器**：

```ts
// apps/web/src/lib/motion/governor.ts
import { motionTicker } from "./ticker";

const TIERS = ["standard", "minimal", "off"] as const;
export type Tier = (typeof TIERS)[number];

interface GovernorOptions {
  onDowngrade: (next: Tier) => void;
  windowSize?: number;     // 采样帧数
  overrunRatio?: number;   // 超预算帧占比阈值
}

/**
 * 连续 windowSize 帧中超过 budgetMs 的帧占比 > overrunRatio 时，降一档。
 * 只在 T3/T4 有活跃订阅者时采样，避免把首屏加载抖动误判为动画掉帧。
 */
export function startGovernor(current: Tier, opts: GovernorOptions): () => void {
  const { windowSize = 60, overrunRatio = 0.25, onDowngrade } = opts;
  const budget = 1000 / 60 * 1.5;   // 22.5ms
  let frames = 0, overruns = 0, last = 0;
  let tier: Tier = current;

  return motionTicker.subscribe((now) => {
    if (!last) { last = now; return; }
    const dt = now - last;
    last = now;
    frames++;
    if (dt > budget) overruns++;
    if (frames < windowSize) return;

    const ratio = overruns / frames;
    frames = 0; overruns = 0;
    if (ratio > overrunRatio) {
      const idx = TIERS.indexOf(tier);
      if (idx < TIERS.length - 1) {
        tier = TIERS[idx + 1];
        onDowngrade(tier);
      }
    }
  });
}
```

把它接到 `AnimationProvider`：降档时把 `data-anim` 属性改写到 `<html>`，CSS 里已有的 `[data-anim="off"] * { animation: none !important }` 规则会自动生效——**无需改动任何组件**。

### 3.4 逐项改造清单

| 组件 / 规则 | 现状 | 问题 | 改造 |
|---|---|---|---|
| `fluids/fluid-gradient.tsx` | 3 实例、无限帧率、5 阶 FBM、DPR2 | GPU 满载 | → 单实例 + `MotionTicker`(30fps) + IO/可见性门控 + 渲染缩放 0.6 + 3 阶 FBM（详见 P0-1） |
| `dna-background.tsx` + `.dna-*` | 6 股 + 24 横档 + 18 光点 = **48 个常驻 CSS 动画** | 48 个合成层常驻 | **该组件当前无任何引用点**（全仓库仅自身文件），建议直接删除；若保留：减到 ≤12 节点、加 `contain: strict`、用 `MotionTicker` 统一暂停 |
| `dna-background.tsx:50` | `filter: blur(80px)` 于 600×600 元素（2 处） | 滤镜栅格化极贵，滚动时易触发重绘 | 改为预烘焙的 `radial-gradient`（去掉 `filter`），或输出成一张 WebP |
| `@keyframes glow-pulse` | 动画 `box-shadow` | **非合成属性**，每帧重绘阴影 | 改为伪元素 `opacity` 动画（阴影预先画满，只淡入淡出） |
| `@keyframes gradient-shift` | 动画 `background-position`（6s infinite） | 每帧重绘背景 | 改为双层 `transform: translateX()` 合成动画，或直接静态 |
| `@keyframes shimmer` | 骨架屏 `background-position` | 骨架屏常驻时持续重绘 | 确认骨架屏只在 `isLoading` 期间挂载；长列表改用 `@tanstack/react-virtual` 已有的虚拟滚动 |
| `components/route-motion.tsx` | **全部为静态空壳**（`FadeUp`/`Reveal`/`CountUp` 均直接渲染，无 IO、无动画） | 与 `packages/motion` 的真实实现脱节 | 二选一：① 接受现状并删除该空壳，统一从 `@soymutdb/motion` 导入；② 恢复进入动画时直接用 `packages/motion` 的 `useReveal`（IO 驱动、只动 `transform`/`opacity`、`once: true`、reduced-motion 立即终态） |
| `packages/motion/count-up.tsx` | 已经是静态数字 ✅ | — | 保持（数据类数字静态化对 a11y 与 CLS 都更优） |
| View Transitions（`main.tsx:129-147`） | 整页 `startViewTransition` + 已有 skip 逻辑 | 整页快照在低端机上开销大 | 保留 skip 逻辑；后续用 `view-transition-name` 只对内容容器命名，避免整页光栅化 |
| `routeTree` preload | `defaultPreloadStaleTime: 0` | 每次 hover 都重新拉取路由数据 | → `30_000` |

### 3.5 交互响应预算（INP）

- 任何用户交互的**首帧视觉反馈 ≤ 100ms**；重计算（搜索过滤、序列解析）一律进 Web Worker（`apps/web/src/workers/` 已有基础设施）；
- 长任务用 `scheduler.yield()`（或 `requestIdleCallback` 兜底）切片，单任务 ≤ 50ms；
- 禁止在 `scroll` / `pointermove` 事件里同步读写 DOM；统一走 `passive: true` + rAF 节流。

### 3.6 动效验收清单

```
[ ] Lighthouse（移动端模拟）Performance ≥ 90
[ ] INP p75 < 200ms；CLS p75 < 0.1；LCP p75 < 2.5s
[ ] 首页空闲 10s：Long Task（>50ms）= 0，GPU 帧时间 < 8ms
[ ] 滚出 hero 后：Performance 面板 Frames 曲线归零（rAF 已停）
[ ] 切到后台标签页：CPU 占用 → 0
[ ] prefers-reduced-motion: reduce → 所有 T2/T3/T4 动画不播放，T0/T1 保留
[ ] 4 核 CPU 节流 4x：governor 自动降档到 minimal，无掉帧告警
[ ] 移动端（中端安卓）：FluidGradient 渲染静态帧或降级为 CSS 渐变
```

---

## 4. P1 — 后端与基础设施

### 4.1 PostgreSQL 完全跑默认参数

`docker-compose.yml` 的 `postgres` 服务没有任何 `command` 覆盖 → `shared_buffers=128MB`、`work_mem=4MB`、`random_page_cost=4.0`（假设机械盘）。对基因组这类以索引扫描 + 大分组聚合为主的负载，这是**最大的单点收益**。

```yaml
  postgres:
    profiles: [ "core" ]
    image: postgres:18.4-alpine
    shm_size: 256mb
    command:
      - postgres
      - -c
      - max_connections=200
      - -c
      - shared_buffers=2GB                 # ≈ 25% RAM（8GB 机器；按需调整）
      - -c
      - effective_cache_size=6GB           # ≈ 75% RAM
      - -c
      - work_mem=32MB                      # 排序/哈希；注意 max_connections × work_mem 上限
      - -c
      - maintenance_work_mem=512MB
      - -c
      - random_page_cost=1.1               # SSD/NVMe
      - -c
      - effective_io_concurrency=200
      - -c
      - wal_compression=on
      - -c
      - jit=off                            # OLTP 短查询下 JIT 通常是净负收益
      - -c
      - log_min_duration_statement=500ms   # 慢查询采样进日志
      - -c
      - log_temp_files=64MB                # 抓 work_mem 不足导致的落盘排序
      - -c
      - shared_preload_libraries=pg_stat_statements
      - -c
      - pg_stat_statements.track=all
      - -c
      - pg_stat_statements.max=10000
```

上线后一周用 `pg_stat_statements` 找 top-10 慢查询，针对性补索引。

### 4.2 `User` 的级联预加载（认证热路径 N+1）

**位置**：`apps/api/app/models/auth.py:139-146`、`api/v1/deps.py:55`

```
User.role_rel            lazy="joined"     → JOIN roles
User.organization_rel    lazy="joined"     → JOIN organizations
User.project_memberships lazy="selectin"   → 额外 SELECT
Organization.users       lazy="selectin"   → 级联！再额外 SELECT（该组织下所有用户）
```

`select(User)` 一次 = **1 次 JOIN 查询 + 2 次 SELECT IN**，而 `get_current_user` 每次带 token 的请求都会跑。同理 `AuditLog.user` 也是 `lazy="joined"` → 管理员审计日志列表会级联放大。

**修复**

```python
# User
role_rel: Mapped[Role | None] = relationship(..., lazy="selectin")                 # joined → selectin
organization_rel: Mapped[Organization | None] = relationship(..., lazy="raise_on_sql")
project_memberships: Mapped[list[ProjectMember]] = relationship(..., lazy="raise_on_sql")

# Organization —— 防止「加载一个 User 就把整个组织的人拉出来」
users: Mapped[list[User]] = relationship(..., lazy="raise_on_sql")

# AuditLog.user —— 审计列表不需要用户详情
user: Mapped[User | None] = relationship(..., lazy="raise_on_sql")
```

`deps.py` 显式声明需要什么：

```python
from sqlalchemy.orm import selectinload

result = await db.execute(
    select(User)
    .options(selectinload(User.role_rel))
    .where(User.id == user_uuid)
)
```

`raise_on_sql` 会在误触惰性加载时立刻抛错（而不是静默产生 N+1），这是 async ORM 的推荐实践。改动后需跑全量 pytest，把暴露出来的访问点补上显式 `selectinload`。

### 4.3 nginx：无 brotli、无缓存、无 HTTP/2

**位置**：`infra/nginx/nginx.conf`、`infra/nginx/conf.d/default.conf`

| 项 | 现状 | 修复 |
|---|---|---|
| 压缩 | 仅 gzip level 6 | 加 `brotli`（需 `ngx_brotli` 模块或改用 Cloudflare 边缘 Brotli）；静态资源已在构建期 `gzip -9` 预压缩 ✅，建议同时产出 `.br` |
| HTTP/2 | `listen 80` only | HTTPS server 块加 `http2 on;` |
| API 缓存 | `proxy_cache off` + `add_header Cache-Control no-store`（对**所有** `/api/` 一刀切） | 见下方拆分 |
| 静态数据缓存 | `/data/` 直连 MinIO，`proxy_buffering off`，无缓存 | 加 `proxy_cache data_cache` + `slice` 分片支持 Range |
| hashed asset 正则 | server 级正则，会把 admin/jbrowse 的 hashed 资源误路由到 `web_frontend` | 为 `/soymutdb-admin/`、`/soymutdb-jbrowse/` 加 `^~` 前缀 location |

**API 缓存拆分**（替换 `default.conf:158-164`）：

```nginx
# 默认：私密优先，不缓存
location ^~ /api/ {
    proxy_no_cache $has_authorization $has_cookie;
    proxy_cache_bypass $has_authorization $has_cookie;
    proxy_cache off;
    add_header Cache-Control "no-store" always;
    …
}

# 白名单：公开只读端点做 5s 微缓存，削掉搜索/统计的突发流量
location ~ ^/api/v1/(stats|releases|news|content|site|genes|tracks)/ {
    proxy_cache api_cache;
    proxy_cache_valid 200 5s;
    proxy_cache_lock on;                      # 同一 key 并发只回源一次
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_cache_background_update on;
    add_header X-Cache-Status $upstream_cache_status;
    proxy_no_cache $has_authorization $has_cookie;
    proxy_cache_bypass $has_authorization $has_cookie;
    …
}
```

`http` 块补充：

```nginx
proxy_cache_path /var/cache/nginx/api  levels=1:2 keys_zone=api_cache:10m  max_size=1g  inactive=10m use_temp_path=off;
proxy_cache_path /var/cache/nginx/data levels=1:2 keys_zone=data_cache:10m max_size=20g inactive=7d  use_temp_path=off;
```

### 4.4 FastAPI 中间件开销

`main.py` 目前挂了 3 个 `BaseHTTPMiddleware`（Metrics / RequestId / SecurityHeaders）+ CORS + GZip。`BaseHTTPMiddleware` 会把响应包装成流式响应，每个请求多两次协程上下文切换；`GZipMiddleware` 在 Python 层压缩，而 nginx 已经在边缘做了。

**修复**

1. **移除 `GZipMiddleware`**（nginx 已 gzip/brotli，避免重复 CPU 消耗）：

```diff
-    app.add_middleware(GZipMiddleware, minimum_size=1024)
```

2. **把 3 个 `BaseHTTPMiddleware` 合并成一个纯 ASGI 中间件**，省掉两层包装：

```python
class ObservabilityMiddleware:
    """纯 ASGI 中间件：request-id + 安全头 + Prometheus 指标（合并 3 层）。"""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        request_id = next((v.decode() for k, v in scope["headers"] if k == b"x-request-id"), None)
        if not request_id:
            request_id = str(uuid.uuid4())
        bind_contextvars(request_id=request_id)

        status = 500
        start = time.perf_counter()

        async def send_with_headers(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"].extend([
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", b"geolocation=(), microphone=(), camera=()"),
                ])
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            if scope["path"] != "/metrics":
                endpoint = normalize_metrics_path(scope["path"])
                REQUEST_LATENCY.labels(method=scope["method"], endpoint=endpoint).observe(
                    time.perf_counter() - start)
                REQUEST_COUNT.labels(method=scope["method"], endpoint=endpoint, status=status).inc()
            clear_contextvars()
```

### 4.5 前端其它

| 项 | 位置 | 修复 |
|---|---|---|
| 路由预加载过于激进 | `main.tsx:84` `defaultPreloadStaleTime: 0` | → `30_000`（30s 内 hover 不重复拉取） |
| 死依赖 | `apps/web/package.json`、`apps/admin/package.json` | 删除 `@fontsource/fraunces`、`@fontsource/inter`（全仓库无引用）；`@tanstack/router-devtools` 从 `dependencies` 移到 `devDependencies`（web 已注释掉使用点） |
| SSG 与 React 双渲染 | `main.tsx` `SsgHandoff` — 构建期 HTML 在 React 提交后被整体替换（非 hydrate） | 这是**有意为之**（避免 hydration mismatch），但要保证 SSG 骨架与 React 首帧结构一致，否则 CLS 会爆。建议给首屏容器固定 `min-height`，并把 LCP 元素的尺寸在 SSG 阶段就写好 |

---

## 5. P2 — 监控与治理

| 项 | 现状 | 补充 |
|---|---|---|
| 前端 RUM | 无（P0-7） | Web Vitals 面板 + p75 告警 |
| API 延迟告警 | 全局 p95 > 1s | 拆出**按 endpoint** 的 p95（`soymutdb_http_request_duration_seconds_bucket` 已带 `endpoint` label），对 `/search`、`/variants`、`/stats` 单独设阈值 |
| 慢查询 | 无 | `pg_stat_statements` + postgres_exporter；新增 `SlowQueryRate` 告警 |
| ClickHouse parts | 无 | 新增告警：`max(parts) > 300`（`system.parts`），直接暴露 P0-5 的问题 |
| 队列积压 | `soymutdb_worker_queue_depth > 500` 且 `for: 10m` | 收紧到 `> 100` / `for: 5m`，并按队列分组 |
| 构建体积门禁 | 无 | CI 增加 size-limit / `bundlesize`：首屏 JS gzip > 250 KB 则失败 |
| 动效预算门禁 | 无 | e2e 增加一条 Playwright 用例：录制首页 10s，断言 Long Task 数 = 0 |

---

## 6. 实施路线图

```
Sprint 1（测量 + 首屏）           Sprint 2（后端 + 数据层）
─────────────────────────      ─────────────────────────
P0-7  RUM 上线（前置！）    →    P0-4  搜索索引 + 并发 + 缓存
P0-2  字体子集化 + preload  →    P0-5  ClickHouse 批量写入
P0-3  antd 分包            →    P0-6  release context 缓存
P0-1  WebGL 单实例 + 门控   →    4.1   PostgreSQL 调参
                                4.2   User 级联预加载

Sprint 3（基础设施 + 动效）        Sprint 4（治理 + 收尾）
─────────────────────────      ─────────────────────────
4.3   nginx 缓存/brotli/HTTP2 →    5.    监控补强
4.4   中间件合并               →    构建体积门禁 + 动效 e2e 门禁
4.5   前端杂项                 →    清理死依赖 / 死组件（DnaBackground）
3.3   MotionTicker + governor →    回归：全量 CI + e2e + 压测
3.4   动效逐项改造             →    复盘：对比 P0-7 采集的前后数据
```

### 每 Sprint 的验收与回滚

| Sprint | 验收命令 | 回滚方式 |
|---|---|---|
| 1 | `pnpm --filter @soymutdb/web build && pnpm --filter @soymutdb/web preview`；Lighthouse 移动端 Performance ≥ 90；`dist/index.html` 无 antd-heavy modulepreload | 逐文件 `git revert`；字体保留原文件并列，仅切换 `@font-face` src |
| 2 | `cd apps/api && .venv/bin/python -m pytest tests -q`；`EXPLAIN ANALYZE` 确认索引命中；`SELECT count() FROM system.parts WHERE table='analytics_events'` 30min 内不增长 | 索引用 `DROP INDEX CONCURRENTLY`；缓存开关 `SOYMUTDB_REDIS_CACHE_TTL=0` 可一键旁路 |
| 3 | `docker compose config`；`curl -sI` 确认 `X-Cache-Status` 与 `content-encoding: br`；首页空闲 Long Task = 0 | nginx 分块灰度，逐 location 回退 |
| 4 | 全量 CI；`cd e2e && npx playwright test` | — |

---

## 7. 预期收益汇总

| 指标 | 当前 | 优化后 | 幅度 |
|---|---|---|---|
| 首屏关键路径 JS（未压缩） | 2.02 MB | ≈ 1.0 MB | −50% |
| 字体传输量 | 12.7 MB | ≤ 1.1 MB（子集化） / 0（系统字体栈） | −91% ~ −100% |
| 首页 WebGL 上下文 / rAF 循环 | 3 / 3 | 1 / 0（离屏时） | −100% |
| 首页空闲 GPU 占用 | 满载 | < 8ms/帧 | −85%+ |
| 搜索 p95 | 秒级（全表扫描） | < 150 ms | −85% |
| 每个数据请求 DB 往返 | +1（release） | 0（60s 缓存） | −1 RTT |
| ClickHouse 写入 part 数 | 1/事件 | 1/(1s or 1MB) | −99% |
| 认证请求 DB 查询数 | 3 | 2 | −33% |
| 生产前端性能可见性 | 0% | 25% 采样 + p75 告警 | 从无到有 |

---

## 附录 A：关键文件索引

| 关注点 | 路径 |
|---|---|
| WebGL 流体 | `apps/web/src/components/fluids/fluid-gradient.tsx` |
| 首页轮播（3 画布来源） | `apps/web/src/components/home/antd-home.tsx:233` |
| 字体声明 | `apps/web/src/index.css:860-882` |
| antd 桶文件 | `apps/web/src/lib/antd.ts` |
| Vite 分包 | `apps/web/vite.config.ts:139`、`apps/admin/vite.config.ts:105` |
| 动效策略 | `apps/web/src/lib/motion-policy.ts`、`animation-context.tsx` |
| 动效组件（真身） | `packages/motion/src/**` |
| 动效组件（空壳） | `apps/web/src/components/route-motion.tsx` |
| Web Vitals 采集器（未调用） | `apps/web/src/lib/perf.ts` |
| 搜索服务 | `apps/api/app/services/search_service.py` |
| 埋点服务 | `apps/api/app/services/analytics_service.py:82` |
| release 解析 | `apps/api/app/services/release_context.py:85` |
| 缓存助手 | `apps/api/app/services/cache.py` |
| 中间件 | `apps/api/app/core/middleware.py`、`apps/api/app/main.py:253-272` |
| User 关联加载 | `apps/api/app/models/auth.py:139-146` |
| nginx | `infra/nginx/conf.d/default.conf` |
| Celery | `apps/worker/src/soymutdb_worker/main.py` |
| ClickHouse schema | `infra/clickhouse/init.sql` |
| 告警 | `infra/monitoring/rules/alerts.yml` |
