# SoyMutDB 平台优化方案

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

### 后端架构 · 查询性能 · 前端架构 · 管理后台体验

> **版本**：v4.0　**日期**：2026-08-29
> **性质**：设计方案（Design Proposal）

> **2026-09-26 校正（历史文档）**：文中 `packages/i18n` 已移除（现为 `packages/i18n-core`）。
> 前端文件路径与框架描述为迁移前记录：三端曾迁到 Vue 3，Vue 现已完全退役
> （`scripts/check-vue-retirement.mjs` 断言通过），当前为 React 19 + Umi Max 4。
>
> **四份方案的分工**（互不重叠，按此顺序阅读）：
>
> | 文档 | 主题 | 一句话 |
> |---|---|---|
> | `optimization-plan.md` (v1.0) | 工程化改造 | 把工程基建补齐 |
> | `performance-optimization-plan.md` (v2.0) | 性能与动效 | 把慢的跑快 |
> | `desktop-client-plan.md` (v3.0) | 桌面客户端 | 让它能被装上用 |
> | **本文档 (v4.0)** | **架构与体验** | **让它长得好、用得爽** |
>
> v2.0 回答"怎么跑快"，本文档回答"怎么组织"与"怎么用"。
> 重叠处一律引用 v2.0，不重复展开。

---

## 0. 一句话结论

**SoyMutDB 的工程底座比预想的扎实** —— 异常体系、服务层依赖、keyset 分页、插件签名、契约链路、特性开关、审计、限流，这八项都已经做对且做到位了。**不需要重构，需要的是收口**：

- **后端**：50 个路由文件 × 35 个 service 里，同样的六件事被重复写了几十遍。把它们管线化，而不是引入新分层。
- **查询**：94 个索引覆盖良好，缺的是**全文检索类索引**（`ILIKE '%q%'` 无法用 B-tree），以及一套慢查询治理闭环。
- **前端**：数据获取层已经配置得很好，缺的是组件分层纪律与错误降级覆盖（**admin 端连 ErrorBoundary 都没有**）。
- **管理后台**：三个页面吃掉 39% 的代码量（1248 / 1199 / 1173 行），这是体验与可维护性的双重瓶颈，是本期投入产出比最高的一块。

**优先级建议**：管理后台 > 查询性能 > 后端收口 > 前端架构。
理由：后台是运营人员每天面对的界面，痛感最直接；查询性能直接影响所有用户；后两端是长期健康度。

---

## 1. 现状盘点：哪些已经做得很好

开工前必须先确认：**下面这些不要动、不要重造**。分析中发现多处已经做到位的工程实践，任何"引入统一错误处理""引入分层架构"的建议在这里都是倒退。

### 1.1 后端已经成熟的十项

| # | 项 | 证据 | 结论 |
|---|---|---|---|
| 1 | **异常体系** | `core/exceptions.py`：`SoyMutDBError` 基类 + 13 个子类，各带 `error_code`（`not_found` / `forbidden` / `conflict` / `rate_limit_exceeded` / `plugin_disabled`…），统一 `_error_envelope` 响应 | **不要引入新错误处理** |
| 2 | **服务层无环** | 35 文件 / 10,025 行，跨服务 import 仅 3 处（`outbox_service`、`presign` ×2） | **不需要拆分或重建分层** |
| 3 | **keyset 分页** | `test_genes.py:98` 有 cursor pagination 测试；`test_gene_service.py` 覆盖 `list_genes` 的 keyset 与 `has_more` | **已实现，只需推广** |
| 4 | **同位点分页** | `test_release_bound_queries.py:380` 专门测试 "same position variants paginate without skip or duplicate" | 边界情况已考虑 |
| 5 | **插件签名与 fail-closed** | `core/plugins.py`：签名清单 + 版本兼容 + 健康检查；5 个内置插件（jbrowse / blast / analyses / mcp / ols4）；管理员**不能**上传插件代码 | 安全模型正确 |
| 6 | **契约链路** | OpenAPI → `openapi-typescript` → CI `check:contract` 强制同步 + `contract_visibility.py` 可见性基线 | 前后端类型零漂移 |
| 7 | **索引覆盖** | 23 个迁移、94 处 `create_index`、17 个 model 文件定义 63 个 `Index()` | 见 §1.3 修正 |
| 8 | **特性开关** | `core/features.py`：原子化、带 `disable_behavior`、可审计、运行时存 `system_settings` | 可直接用于灰度 |
| 9 | **审计日志** | `core/audit.py`：action 记录、保留期清理、在线时长统计 | 合规基础在位 |
| 10 | **限流** | `core/ratelimit.py`：Redis Lua 原子脚本、固定窗口对齐、Redis 不可用时 **fail-closed**（生产） | 实现正确 |

### 1.2 前端已经成熟的五项

| # | 项 | 证据 |
|---|---|---|
| 1 | **错误边界** | `apps/web/src/components/error-boundary.tsx`，已接入 `routes/__root.tsx` |
| 2 | **数据获取配置** | `lib/query-client.ts`：`staleTime` 5 min、`gcTime` 30 min、`refetchOnWindowFocus: false`、4xx 不重试、指数退避 |
| 3 | **静态化管线** | `build` 串联 SSG → gzip → SW → release-manifest |
| 4 | **国际化** | `packages/i18n` 中英双语 |
| 5 | **视图过渡** | `lib/view-transitions.ts` + `skipVT()` 门控，已包装 `router.load` |

### 1.3 三处需要修正的先前判断

在 v2.0 方案里我给出过三条判断，精查后需要修正。**记录在此以免误导后续工作**：

| 先前判断 | 实际情况 | 修正 |
|---|---|---|
| "0 个 GIN/trigram 索引" | 索引**总量 94 个、覆盖良好**（B-tree 为主）；缺的确实是全文检索类（无 `pg_trgm` / `gin_trgm_ops` / `to_tsvector`） | 改为"**索引充足但缺全文检索类**"，问题更窄、解法更明确（§3.3） |
| "插件机制只有 1 个插件（ols4）" | `BUILTIN_PLUGINS` 有 **5 个**（jbrowse / blast / analyses / mcp / ols4），且是签名清单 + fail-closed 机制；`app/plugins/ols4.py` 只是其中一个的声明文件 | 插件基础设施成熟度被低估，生态扩展的基础已具备 |
| "搜索无分页、cursor 未实现" | 基因列表已是 **keyset 分页**并有测试；变异查询已处理同位点分页去重 | 改为"**keyset 已实现，需推广到其余端点**"（§3.4） |

---

## 2. A · 后端架构优化

### 2.1 核心问题：不是缺分层，是横切逻辑重复

```
现状：50 个路由文件 × 35 个 service
      ┌─ 权限检查      ┐
      ├─ 分页参数解析   │
      ├─ 审计记录      ├── 这六件事在每个端点被重复实现
      ├─ 缓存读写      │
      ├─ 异常映射      │
      └─ 响应包装      ┘
```

**不建议**引入 repository / DAO 层。理由：SQLAlchemy 2.0 的 async session 本身已经是数据访问抽象，再包一层只是增加间接性；且服务层无环、无上帝对象（最大的 `enrichment_service.py` 586 行，合理）。

**建议**把这六件事做成**可组合的横切管线**，让端点只写业务差异。

### 2.2 横切管线化

#### 2.2.1 分页契约统一

现状：keyset 已用于基因列表，但各端点分页参数命名与返回结构可能不一致。统一为一套：

```python
# apps/api/app/core/pagination.py —— 统一 keyset 分页契约
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class Page(Generic[T]):
    """统一分页响应契约。所有列表端点必须返回此结构。"""
    items: list[T]
    next_cursor: str | None
    has_more: bool
    # 不返回 total —— 大表 COUNT(*) 是典型性能陷阱（见 §3.4）

    @classmethod
    def of(cls, items: list[T], limit: int, cursor: str | None) -> "Page[T]":
        has_more = len(items) > limit
        return cls(
            items=items[:limit],
            next_cursor=items[limit - 1].cursor_key() if has_more else None,
            has_more=has_more,
        )
```

**关键决策：不返回总数。**
大表 `COUNT(*)` 在 PG 上是全索引扫描，随数据量线性变慢。前端如果需要"共 N 条"，改用：
- 近似值（`EXPLAIN` 的 rows 估计，或 `pg_class.reltuples`）；
- 游标式 UI（"加载更多"），根本不显示总数。

#### 2.2.2 审计声明化

现状 `core/audit.py` 已有能力，但记录散落在各 service。改为依赖注入 + 声明：

```python
# 声明式审计：路由层只标注动作，记录由依赖统一完成
@router.post("/genes/{gene_id}/publish", response_model=GeneResponse)
async def publish_gene(
    gene_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_role("curator")),
    audit: Auditor = Depends(auditor("gene.publish")),   # ← 一行声明
):
    gene = await GeneService.publish(db, gene_id)
    await audit.record(target=str(gene_id), detail={"assembly": gene.assembly})
    return gene
```

#### 2.2.3 缓存声明化

现状 `services/cache.py` 已有 `get_or_set(name, ttl, loader, *, params, redis)`，但调用点散乱。补一个装饰器：

```python
# apps/api/app/core/cache_decorator.py
def cached(name: str, ttl: int = 300, *, key_params: tuple[str, ...] = ()):
    """声明式缓存。命中返回缓存，未命中执行 loader 并回写。"""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            params = {k: kwargs[k] for k in key_params if k in kwargs}
            return await get_or_set(name, ttl, lambda: fn(*args, **kwargs), params=params)
        return wrapper
    return decorator

# 用法（对应 v2.0 的 P0-6）
@cached("release_context", ttl=60)
async def get_release_context(db): ...
```

#### 2.2.4 权限声明化

现状权限检查依赖 `require_role` 之类的依赖（需在路由里逐个声明）。补一个路由注册期的集中声明，便于生成权限矩阵文档：

```python
# 集中声明，可导出为权限矩阵、可被测试断言覆盖完整性
PERMISSIONS: dict[str, PermissionSpec] = {
    "POST /api/v1/genes/{gene_id}/publish": PermissionSpec(roles={"curator", "admin"}, audit=True),
    "DELETE /api/v1/media/{asset_id}":      PermissionSpec(roles={"admin"}, audit=True),
}
```

**收益**：一个测试就能断言"所有写端点都声明了权限且开启了审计"，杜绝漏网。

### 2.3 契约从"类型一致"升级到"行为一致"

现状：OpenAPI 保证**类型**一致，CI 强制同步。但类型一致不等于行为一致。缺四件事：

| 缺口 | 说明 | 做法 |
|---|---|---|
| **错误码目录** | `error_code` 已有 13 个，但前端无法枚举、无文档 | 从 `exceptions.py` 自动生成 `error-codes.json`，纳入契约产物，CI 校验 |
| **幂等声明** | api-client 的 `withRetry` 对幂等请求重试 1 次，但"哪些端点幂等"没有契约声明 | OpenAPI 扩展字段 `x-idempotent: true`，前端据此决定是否重试 |
| **分页契约** | 有的 keyset、有的 offset，前端无法统一处理 | §2.2.1 统一后，在 OpenAPI 标注 `x-pagination: keyset` |
| **速率限制契约** | 限流已实现，但响应头契约未固化 | 统一 `Retry-After` 与 `X-RateLimit-*` 响应头并写入契约 |

```python
# apps/api/app/scripts/export_openapi.py —— 扩展导出内容
def postprocess(schema: dict) -> dict:
    """在 OpenAPI 上叠加行为契约扩展字段。"""
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            if method.upper() in {"GET", "PUT", "DELETE"}:
                op["x-idempotent"] = True
            if op.get("responses", {}).get("200", {}).get("content"):
                op["x-pagination"] = "keyset" if is_paginated(op) else "none"
    schema["x-error-codes"] = {
        exc.error_code: exc.__doc__ or ""
        for exc in iter_soymutdb_errors()
    }
    return schema
```

生成的 `error-codes.json` 随 api-client 发布，前端可做错误码到文案的完整映射，**不再有兜底的"未知错误"**。

### 2.4 配置治理

现状 `core/config.py` 已经很规范：`SOYMUTDB_` 前缀、`field_validator` 解析、生产环境必填校验、敏感项禁 `*`。

**缺口不是实现，是可见性**：

1. **配置项清单**：新增脚本导出全部配置项（名称 / 类型 / 默认值 / 是否必填 / 说明），生成 `docs/ops/configuration.md`，与 `deploy/.env.example` 双向校验（CI 断言 example 不缺项）。
2. **启动期配置回显**：启动时打印**脱敏后**的有效配置快照，排障时第一手资料。
3. **敏感配置审计**：密钥类配置在日志与错误响应中一律不出现（已做到，加测试固化）。

```bash
# 新增 Makefile 目标
make config-docs    # 导出配置清单到 docs/ops/configuration.md
make config-check   # CI：断言 .env.example 与 Settings 字段一致
```

### 2.5 后台任务与事务边界

现状：`outbox_service.py`（425 行）+ `core/outbox_dispatcher.py` + Celery 8 队列 + `task_acks_late` + `task_reject_on_worker_lost` —— **事务性发件箱模式已经完整实现**，这是正确且高级的做法。

**需要补的是纪律与守卫**：

```python
# 守卫：禁止在事务内直接派发任务（必须走 outbox，否则事务回滚后任务已发出）
# 以测试形式固化，而非文档约定
def test_no_direct_task_dispatch_inside_transaction():
    """扫描 services/ 与 api/v1/，断言不存在事务块内的 .delay( / .apply_async( 调用。"""
    offenders = scan_for_direct_dispatch_in_tx(SOURCE_ROOT)
    assert not offenders, f"事务内直接派发任务：{offenders}"
```

### 2.6 可观测性补强

v2.0 已覆盖 RUM 与 Prometheus 告警规则。本节补后端侧：

| 项 | 现状 | 补充 |
|---|---|---|
| 请求链路 | `RequestIdMiddleware` 已有 | 把 request_id 注入 structlog 上下文，日志全链路可串 |
| 慢查询 | 无 | `pg_stat_statements` 已建议（v2.0 §4.1），补**应用侧**慢查询日志（>500ms 打 WARN + 完整 SQL 摘要 + 参数指纹） |
| 端点 SLO | 告警规则是全局 P95（v2.0 已指出问题） | 按端点分组，读端点与写端点分开设阈值 |
| 结构化日志 | 部分 | 统一 structlog JSON 输出，禁止 f-string 拼接日志 |

```python
# apps/api/app/core/logging_config.py
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,   # ← request_id 自动注入
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)
```

### 2.7 边界守卫自动化

架构约定靠文档会腐化，靠 CI 才有效。补三个守卫：

```bash
# scripts/check-architecture.py（新增，CI 调用）
```

| 守卫 | 断言 |
|---|---|
| **依赖方向** | `services/` 不得 import `api/v1/`（反向依赖）；`models/` 不得 import `services/` |
| **服务层无环** | `services/` 内部 import 图无环（当前仅 3 条边，守住） |
| **路由完整性** | 每个写端点都声明权限 + 审计（§2.2.4）；每个列表端点都返回统一 `Page`（§2.2.1） |

```bash
make check-architecture   # 本地
# CI: .github/workflows/ci.yml 追加一步
```

---

## 3. B · 查询性能专项

### 3.1 现状与问题分类

**索引覆盖良好（94 个）**，但查询性能问题仍然存在。按成因分四类：

| 类型 | 症状 | 根因 | 章节 |
|---|---|---|---|
| **Ⅰ 全文检索** | 搜索慢、随数据量线性劣化 | `ILIKE '%q%'` 无法使用 B-tree 索引 | §3.3 |
| **Ⅱ 列表分页** | 深分页慢、`COUNT(*)` 拖垮列表 | offset 分页 + 返回总数 | §3.4 |
| **Ⅲ 聚合统计** | 统计页慢 | 明细表上实时聚合 | §3.5 |
| **Ⅳ N+1 与级联** | 单请求打几十条 SQL | `lazy="joined"` / `"selectin"` 滥用 | §3.6 |

### 3.2 基线采集（先做，否则无法验收）

在优化前先建立可测量的基线，否则所有优化都是自我感觉：

```sql
-- 启用并重置统计
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
SELECT pg_stat_statements_reset();

-- 跑一轮典型负载（make load-test 或真实流量 24h）后取 Top 20
SELECT
    round(total_exec_time::numeric, 1)                     AS total_ms,
    calls,
    round(mean_exec_time::numeric, 2)                      AS mean_ms,
    round((total_exec_time / sum(total_exec_time) OVER ()) * 100, 1) AS pct,
    query
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
ORDER BY total_exec_time DESC
LIMIT 20;
```

```bash
# 纳入 CI/运维：每周导出一次 Top 20 慢查询，作为优化输入
make slow-query-report
```

### 3.3 类型 Ⅰ：全文检索（v2.0 P0-4 的深化）

**问题**（`services/search_service.py`）：

```python
# global_search 对三个表做三次串行的 ILIKE '%q%'
# Gene:       id / name / description
# MutantLine: name / cultivar / mutagen / description
# Publication: title / authors / abstract
```

`ILIKE '%q%'` 的前导通配符使 B-tree 索引完全失效，只能全表扫描。

**解法：`pg_trgm` GIN 索引**（v2.0 已提出，此处给完整迁移与参数选择）

```python
# apps/api/migrations/versions/0024_search_trigram_indexes.py
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Gene：短字段用 trgm，长文本字段用 trgm 但需限制长度
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_gene_name_trgm
            ON genes USING gin (name gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_gene_description_trgm
            ON genes USING gin (description gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY ix_mutant_line_name_trgm
            ON mutant_lines USING gin (name gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_mutant_line_cultivar_trgm
            ON mutant_lines USING gin (cultivar gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY ix_publication_title_trgm
            ON publications USING gin (title gin_trgm_ops)
    """)
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_publication_abstract_trgm
            ON publications USING gin (abstract gin_trgm_ops)
    """)
```

**四个必须注意的点**：

1. **`CREATE INDEX CONCURRENTLY` 不能跑在事务里**。Alembic 默认包事务，需要：
   ```python
   # migrations/env.py 或在迁移文件里
   with op.get_context().autocommit_block():
       op.execute("CREATE INDEX CONCURRENTLY ...")
   ```
2. **CJK 与 trigram**：`pg_trgm` 按字符切三元组，**中文短词（2 字）命中率低**。中文场景需评估 `pg_bigm`（2-gram，对 CJK 更友好）：
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_bigm;
   CREATE INDEX ix_gene_name_bigm ON genes USING gin (name gin_bigm_ops);
   ```
   **建议**：先建 `pg_trgm`，用真实中文查询集测召回率；不达标再上 `pg_bigm`，可共存。
3. **索引体积**：trigram GIN 索引通常为原表 1–3 倍。`abstract` 这种长文本字段体积大，考虑只索引前 N 字符：
   ```sql
   CREATE INDEX ix_pub_abstract_trgm ON publications
       USING gin (left(abstract, 2000) gin_trgm_ops);
   ```
4. **最小词长**：`pg_trgm` 默认忽略短于 3 字符的词。中文单字/双字查询需要 `gin_trgm_ops` + 调低阈值，或用 `pg_bigm`。

**查询改写**：

```python
# 改写前：三次串行 + 加载完整 ORM 实体
genes = await db.execute(select(Gene).where(Gene.name.ilike(f"%{q}%")))
lines = await db.execute(select(MutantLine).where(MutantLine.name.ilike(f"%{q}%")))
pubs  = await db.execute(select(Publication).where(Publication.title.ilike(f"%{q}%")))

# 改写后：三路并发 + 相似度排序 + 只取展示字段
similarity = func.similarity(Gene.name, q)
gene_stmt = (
    select(Gene.id, Gene.name, similarity.label("score"))
    .where(Gene.name % q)                    # % 运算符走 GIN 索引
    .order_by(desc("score"))
    .limit(per_source_limit)
)
results = await asyncio.gather(*[db.execute(s) for s in (gene_stmt, line_stmt, pub_stmt)])
```

**配套三件事**（缺一不可）：

1. **并发**：三路 `asyncio.gather`，串行改并行（v2.0 P0-4 已提）。
2. **缓存**：`search_service` 加 60s 结果缓存（v2.0 P0-4 已提，用 §2.2.3 的 `@cached`）。
3. **游标**：`global_search` 当前 `next_cursor=None, has_more=False` —— 结果被截断却不告知前端。改为返回真实游标（§2.2.1）。

### 3.4 类型 Ⅱ：列表与分页

**已做对的**：基因列表 keyset 分页、变异同位点去重。

**要推广与补强的**：

| 项 | 做法 |
|---|---|
| **推广 keyset** | 把基因列表的 keyset 实现抽为 `core/pagination.py`（§2.2.1），其余列表端点迁移 |
| **取消总数** | 列表响应去掉 `total`（§2.2.1），改游标式 UI 或近似计数 |
| **近似计数** | 确实要显示总数时用 `pg_class.reltuples`，误差可接受、代价接近零 |
| **深分页保护** | keyset 天然避免深分页问题；对仍用 offset 的端点加 `max_offset` 上限，超限返回 400 引导改用游标 |
| **排序字段必须有索引** | keyset 的排序键必须与索引顺序匹配，否则仍是全排序 |

```python
# 排序键与索引对齐检查（纳入 §2.7 的守卫）
# 例：ORDER BY (created_at, id) DESC 需要
CREATE INDEX ix_news_created_id ON news (created_at DESC, id DESC);
```

### 3.5 类型 Ⅲ：聚合与统计

**现状很好**：ClickHouse 已有多个 `SummingMergeTree` 物化视图（density_10kb / 100kb / 1mb、gene_impact_summary 等），预聚合思路正确。

**补三点**：

1. **查询模式收口**：统计类查询统一走 `clickhouse_service.py`（415 行），禁止在 PG 明细表上做全量聚合。用 §2.7 的守卫断言。
2. **物化视图覆盖度**：按 §3.2 的慢查询报告，找出仍在 PG 上跑的重聚合，逐个补物化视图。
3. **ClickHouse 查询参数**：明确 `max_execution_time`、避免 `SELECT *`、大结果集走流式。

### 3.6 类型 Ⅳ：N+1 与级联加载

**已发现的具体问题**（v2.0 §4.2 已提，此处补具体改法）：

```python
# apps/api/app/models/auth.py:139-146 —— 现状
User.role_rel            = relationship(..., lazy="joined")
User.organization_rel    = relationship(..., lazy="joined")
User.project_memberships = relationship(..., lazy="selectin")
# 且 Organization.users 也是 lazy="selectin"
```

**后果**：加载一个 User 会级联拉出整个组织的所有用户。认证是热路径，每个请求都跑。

**改法**：

```python
# 默认改为 raise_on_sql：未显式指定加载策略就访问关系时直接报错，
# 把 N+1 从"线上慢"变成"开发期就炸"
User.role_rel = relationship(..., lazy="raise_on_sql")
User.organization_rel = relationship(..., lazy="raise_on_sql")

# 需要时显式声明
stmt = select(User).options(
    selectinload(User.role_rel),
    # organization 只在管理端点需要，认证路径不加载
)
```

**分阶段推进**（一次性全改风险大）：

1. 先在**测试环境**把 `lazy` 全局设为 `raise_on_sql`，跑一遍完整测试套件，收集所有触发点；
2. 按触发频率排序，逐个补 `selectinload` / `joinedload`；
3. 认证热路径（User 加载）优先；

```python
# 阶段性开关，避免一次性切换炸掉生产
if settings.sqlalchemy_raise_on_sql:   # 默认 False，测试与预发开启
    Base.set_default_relationship_lazy("raise_on_sql")
```

### 3.7 缓存分层

现状 `services/cache.py` 已有 `get_or_set` + Redis 降级。补**分层策略**：

| 层 | 作用域 | TTL | 适用 |
|---|---|---|---|
| **L1 请求内** | 单次请求 | 请求结束 | `release_context`（v2.0 P0-6） |
| **L2 Redis** | 跨请求 | 30–300s | 搜索结果、能力快照、统计聚合 |
| **L3 物化视图** | 跨请求 | 数据变更时刷新 | ClickHouse 预聚合 |

**必须补的能力**：缓存失效。现状有 `get_or_set` 但**没有失效接口**，数据变更后只能等 TTL。

```python
# apps/api/app/services/cache.py —— 补全
async def delete_prefix(prefix: str, *, redis=None) -> int:
    """按前缀批量失效。写操作后调用，避免读到陈旧数据。"""
    client = redis or get_redis()
    keys = await client.keys(f"{prefix}:*")
    if not keys:
        return 0
    return await client.delete(*keys)

# 用法：发布新 release 后
await delete_prefix("release_context")
await delete_prefix("stats")
```

### 3.8 慢查询治理闭环

把一次性优化变成持续机制：

```
采集（pg_stat_statements 周报）
  → 归档（docs/ops/slow-query-log.md，按周追加）
  → 诊断（EXPLAIN ANALYZE 附在每条记录后）
  → 修复（索引 / 改写 / 缓存 / 物化视图，四选一）
  → 门禁（新增查询必须附 EXPLAIN；慢查询数不增长）
```

```bash
make slow-query-report   # 生成周报
make explain-query Q="SELECT ..."   # 统一 EXPLAIN 入口
```

### 3.9 查询性能验收与门禁

| 指标 | 目标 | 测量 |
|---|---|---|
| 搜索 P95 | < 300 ms | Prometheus 按端点分组（v2.0 §5 已建议拆分告警） |
| 列表 P95 | < 150 ms | 同上 |
| 单请求 SQL 数 | 列表 ≤ 3，详情 ≤ 8 | 测试断言（计数 session 执行的语句） |
| 慢查询总数 | 周环比不增长 | `pg_stat_statements` 周报 |

**测试门禁**（防劣化）：

```python
@pytest.mark.asyncio
async def test_list_genes_query_count_is_bounded(db_session, gene_factory):
    """列表接口不得出现 N+1：SQL 条数必须与数据量无关。"""
    await gene_factory.create_batch(10)
    count_10 = await count_queries(lambda: GeneService.list_genes(db_session, limit=10))

    await gene_factory.create_batch(40)
    count_50 = await count_queries(lambda: GeneService.list_genes(db_session, limit=10))

    assert count_50 == count_10, f"疑似 N+1：{count_10} → {count_50}"
```

---

## 4. C · 前端架构优化

### 4.1 组件分层与复用

现状 `apps/web/src/components/` 有 9 个子目录（analyses / charts / file-viewer / fluids / home / notifications / ontology / page-builder / __tests__）。

**问题**：缺少明确的层内分级，导致"什么都往 components 里塞"。

**建议四级分层**：

```
src/
├── components/
│   ├── ui/          无业务的基础组件（Button / Card / Empty / Skeleton 的本地封装）
│   ├── domain/      业务组件（GeneCard / VariantTable / MutantLineBadge）
│   ├── features/    跨页面的功能块（SearchBar / AnalysisSubmitter / ExportMenu）
│   └── layout/      布局骨架（Header / Sidebar / PageShell）
├── lib/             无 UI 的逻辑（api / format / hooks / query keys）
└── routes/          路由只做编排：取数据 + 组合组件
```

**纪律**：`routes/` 里不写样式、不写复杂逻辑；`components/ui/` 不 import 业务类型。

### 4.2 数据获取层统一

现状 TanStack Query 配置良好（§1.2）。补三件事：

#### 4.2.1 Query Key 工厂

```ts
// apps/web/src/lib/query-keys.ts —— 集中管理，避免 key 漂移与失效遗漏
export const queryKeys = {
  all: ["soymutdb"] as const,
  genes: {
    all: () => [...queryKeys.all, "genes"] as const,
    list: (params: GeneListParams) => [...queryKeys.genes.all(), "list", params] as const,
    detail: (id: string) => [...queryKeys.genes.all(), "detail", id] as const,
  },
  variants: {
    all: () => [...queryKeys.all, "variants"] as const,
    list: (params: VariantListParams) => [...queryKeys.variants.all(), "list", params] as const,
  },
  release: () => [...queryKeys.all, "release"] as const,
};

// 失效时按前缀精确失效，不会漏也不会过度失效
queryClient.invalidateQueries({ queryKey: queryKeys.genes.all() });
```

#### 4.2.2 乐观更新

对高频的收藏、标记、状态切换走乐观更新，避免整表重取：

```ts
const toggleStar = useMutation({
  mutationFn: (id: string) => starGene(id),
  onMutate: async (id) => {
    await queryClient.cancelQueries({ queryKey: queryKeys.genes.detail(id) });
    const prev = queryClient.getQueryData(queryKeys.genes.detail(id));
    queryClient.setQueryData(queryKeys.genes.detail(id), (old) => ({
      ...old, starred: !old.starred,
    }));
    return { prev };
  },
  onError: (_err, id, ctx) => {
    queryClient.setQueryData(queryKeys.genes.detail(id), ctx?.prev);   // 回滚
  },
  onSettled: (_d, _e, id) => {
    queryClient.invalidateQueries({ queryKey: queryKeys.genes.detail(id) });
  },
});
```

#### 4.2.3 请求去重与预取

路由层已配置 `defaultPreload: "intent"`（悬停即预取），保持。补：列表页预取首条详情。

### 4.3 状态管理边界

现状：TanStack Query 管服务端状态，少量局部 `useState` 与 context（主题、动效偏好、认证）。**这个划分是对的**。

**纪律**（写进贡献指南）：

| 状态类型 | 归属 | 反例 |
|---|---|---|
| 服务端数据 | TanStack Query | ❌ 把接口响应塞进 context |
| 跨组件 UI 状态（主题/侧边栏/动效） | Context | ❌ 塞进 Query |
| 组件内 UI 状态（展开/选中） | `useState` | ❌ 提升到全局 |
| URL 可表达的状态（筛选/分页/排序） | **URL search params** | ❌ 存 context（无法分享、无法后退） |

最后一条最关键：**筛选条件应该在 URL 里**，这样用户能复制链接分享筛选结果、能用浏览器后退。

### 4.4 错误处理与降级

**现状**：`error-boundary.tsx` 已接入 web 的 `__root.tsx`。

**缺口**：

1. **admin 端完全没有 ErrorBoundary** —— `apps/admin/src` 下无任何 `ErrorBoundary` 或 `componentDidCatch`。admin 里任一组件抛错 → 整个后台白屏，管理员无法操作、无法恢复。已在 §5.11 处理。
2. **路由级边界缺失** —— 单一顶层边界意味着一个页面崩溃就整站降级。应为每个路由加边界，崩溃局限在单个页面：

```tsx
// routes/__root.tsx —— 顶层保留兜底
// 各业务路由内再包一层，错误不外溢
<RouteErrorBoundary>
  <GeneDetailPage />
</RouteErrorBoundary>
```

3. **错误分类处理** —— 利用 §2.3 生成的 `error-codes.json`，做精确映射：

```ts
// 不再有兜底的"未知错误"
const ERROR_MESSAGES: Record<string, string> = {
  not_found:            "找不到该资源",
  forbidden:            "没有权限执行此操作",
  conflict:             "数据已被他人修改，请刷新后重试",
  settings_version_conflict: "设置已被其他管理员修改，请刷新",
  rate_limit_exceeded:  "操作过于频繁，请稍后再试",
  plugin_disabled:      "该功能当前未启用",
};
```

### 4.5 表单与校验

现状：`routes/blast.tsx` 用 zod 校验（注释里提到 "zod validation logic unchanged"），其余各处做法不一。

**统一为 zod + antd Form 联动**：

```tsx
const schema = z.object({
  query: z.string().min(1, "请输入序列").max(100_000, "序列过长"),
  program: z.enum(["blastn", "blastp", "tblastn"]),
  evalue: z.number().positive().default(1e-5),
  maxTargets: z.number().int().min(1).max(5000),
});

// zod schema 同时驱动：运行时校验 + TS 类型 + 表单默认值
type FormValues = z.infer<typeof schema>;

<Form<FormValues>
  form={form}
  onFinish={handleSubmit}
  validateMessages={{ required: "此项必填" }}
>
```

**收益**：校验规则一处定义，类型自动推导，不用手写 interface 与校验两份。

### 4.6 性能

**不在此展开** —— 见 v2.0（首屏分包、字体子集化、WebGL 治理、动效分级）。
本节只补两条与架构相关的：

1. **构建体积门禁**：v2.0 已建议，落地时用 `scripts/check-bundle-size.sh`（已存在）在 CI 断言。
2. **依赖治理**：`dependency-governance.json` + `scripts/dependency_governance.py` 已存在。补一条规则：**禁止在 `components/ui/` 里引入重依赖**（echarts / pdf.js / cytoscape），防止基础组件被污染。

### 4.7 可访问性与国际化

| 项 | 现状 | 补充 |
|---|---|---|
| 组件 a11y | antd 本身 WCAG 2.1 AA 达标 | 自绘组件（序列轨道、图表）补 `role` / `aria-label` |
| 键盘导航 | 依赖 antd | 补全局快捷键（§5.10 同样适用于前台） |
| 语义化 | 部分 | 补 landmark（`main` / `nav` / `aside`）与标题层级 |
| i18n | 中英双语已具备 | 补 **i18n 完整性检查**：CI 断言 zh/en 的 key 集合一致，缺失即失败 |

```bash
make check-i18n   # 断言 zh/common.json 与 en/common.json 键集合一致
```

### 4.8 测试策略

现状：38 个前端路由，测试集中在 `__tests__`（约 8 个测试文件）。

**建议三层**（按性价比排序）：

| 层 | 覆盖 | 工具 | 优先补 |
|---|---|---|---|
| **契约与纯函数** | `lib/` 下的格式化、解析、校验 | Vitest | ⭐ 最高，投入产出比最好 |
| **组件交互** | 表单、表格、错误状态 | Vitest + Testing Library | ⭐⭐ |
| **关键路径 e2e** | 登录、搜索、提交任务 | Playwright（`e2e/` 已存在） | ⭐⭐⭐ 保主干 |

**门禁**：新增路由必须至少有一个渲染测试（防止路由级崩溃无感知）。

---

## 5. D · 管理后台体验升级

**这是本期投入产出比最高的一块。**

### 5.1 现状：三个页面吃掉 39%

```
apps/admin/src/routes 共 9,207 行（30 个路由）
  content.tsx   1,248 行  ┐
  settings.tsx  1,199 行  ├── 3,620 行 = 39%
  imports.tsx   1,173 行  ┘
```

`content.tsx` 单文件里有 **20 处** `useState` / `useQuery` / `Form.useForm` —— 典型的上帝组件。

**后果是双重的**：
- **体验**：管理员在一个巨页里找功能靠滚动和记忆，改一处要理解整个文件；
- **工程**：任何改动都要触碰千行文件，冲突率高，单测几乎不可能。

### 5.2 信息架构重构

现状平铺 30 个路由（content / settings / imports / publications / media / news / widgets / audit / features / page-builder / …）。**缺少分组**，管理员面对一列平级菜单。

**建议按"操作频率 × 职责"分四组**：

```
运营日常（每天用）
  ├─ 仪表盘（新增 · 今日待办与异常）
  ├─ 内容        新闻 / 页面 / 媒体 / 出版物
  └─ 互动        种子申请 / 通知

数据管理（每周用）
  ├─ 导入（Import Studio）
  ├─ 基因 / 变异 / 突变体
  └─ 发布（Release）

系统（很少用）
  ├─ 设置        拆分为 6 个子页（§5.7）
  ├─ 特性开关
  ├─ 插件
  └─ 用户与角色

监督（按需）
  ├─ 审计日志
  └─ 组件健康（widget-health）
```

**关键改动**：加一个**仪表盘首页**（§5.8），管理员登录后先看到"需要我做什么"，而不是一个空列表。

### 5.3 上帝页面拆分

#### 5.3.1 `content.tsx`（1,248 行）

按内容类型拆 —— 现状很可能是把新闻、页面、媒体、出版物的编辑 UI 全塞在一起：

```
routes/content/
├── index.tsx            内容总览（各类型入口 + 近期变更）
├── news/
│   ├── index.tsx        新闻列表（筛选 + 批量操作）
│   ├── $slug.tsx        编辑（表单 + 预览）
│   └── components/      NewsForm / NewsPreview / PublishingControls
├── pages/               页面构建器内容
├── media/               媒体库（已存在 routes/media.tsx，合并）
└── publications/        出版物（已存在，合并）
```

**拆分顺序**：先抽出**表单组件**（纯展示 + 校验），再把列表逻辑抽成 hook，最后路由只做编排。

#### 5.3.2 `settings.tsx`（1,199 行）

按域拆成子路由 + 独立保存单元：

```
routes/settings/
├── index.tsx            设置总览（各域入口 + 未保存提示聚合）
├── site.tsx             站点信息（名称 / 描述 / 联系 / 备案）
├── appearance.tsx       主题 / Logo / 首页布局
├── integrations.tsx     外部服务（OLS4 / JBrowse / BLAST / MCP）
├── security.tsx         认证 / 限流 / CORS / 会话
├── localization.tsx     语言 / 时区 / 站点变体
└── advanced.tsx         特性开关 / 维护模式 / 危险操作
```

**体验改进**（比拆分本身更重要）：

1. **分域独立保存** —— 现状很可能是"所有设置一个表单、一次提交"。改一处主题却要提交整站配置，冲突风险高（后端已有 `SettingsVersionConflictError` 说明这是真实痛点）。
2. **修订历史** —— 后端已有 `0020_system_setting_revisions.py` 迁移，前端应暴露回滚 UI。
3. **危险操作隔离** —— 维护模式、数据清理等放进 `advanced.tsx` 并加二次确认。

#### 5.3.3 `imports.tsx`（1,173 行）

后端已有 `import_studio_service.py`、`import_inspection_service.py`、`module_import_service.py` 三个服务，前端应对应拆分：

```
routes/imports/
├── index.tsx            导入总览（最近任务 + 入口）
├── new.tsx              新建导入（向导：选类型 → 上传 → 映射 → 校验 → 确认）
├── $taskId.tsx          任务详情（进度 / 日志 / 错误行 / 重试）
└── components/
    ├── FileDropzone.tsx
    ├── ColumnMapper.tsx     字段映射（拖拽）
    ├── ValidationReport.tsx 错误行定位与下载
    └── ImportHistory.tsx
```

### 5.4 批量操作

**现状推测**：管理后台的列表页大概率缺少批量能力（或很弱）。

**统一批量交互模式**：

| 能力 | 说明 |
|---|---|
| 跨页选择 | 选择状态跨分页保留，显示"已选 N 项，全选全部 M 项" |
| 批量动作 | 发布 / 取消发布 / 打标签 / 移动 / 删除 |
| 危险确认 | 破坏性操作显示影响范围，要求输入确认 |
| 进度与部分失败 | 批量是异步任务，显示进度；部分失败展示逐项结果 |
| 撤销 | 见 §5.12 |

```tsx
// 统一的批量操作栏（所有列表页复用）
<BulkActionBar
  selected={selectedIds}
  onClear={() => setSelected([])}
  actions={[
    { key: "publish", label: "发布", icon: <CheckOutlined /> },
    { key: "unpublish", label: "取消发布" },
    { key: "delete", label: "删除", danger: true, requireConfirm: true },
  ]}
  onAction={handleBulkAction}
/>
```

### 5.5 导入体验（Import Studio）

导入是管理员最痛苦也最容易出错的操作。后端已有三个服务支撑，前端应做到：

**四步向导**（每步可回退、可保存草稿）：

```
① 选类型  →  ② 上传文件  →  ③ 映射与校验  →  ④ 确认并导入
   ↓              ↓               ↓                ↓
 模板下载     格式嗅探        错误行高亮      影响预览
 类型说明     解析预览        （行号+原因）    后台任务
```

**关键体验点**：

1. **先校验后导入** —— 上传后立即做干跑（dry-run），把错误全部暴露在确认之前。后端 `import_inspection_service.py` 已有此能力。
2. **错误可定位** —— 错误报表给出**行号 + 列 + 原因 + 原始值**，支持下载 CSV 修正后重传。
3. **字段映射记忆** —— 同类文件下次自动套用上次映射。
4. **可断点续传** —— 大文件走分片上传。
5. **导入是任务** —— 导入进后台队列（已有 worker-ingest），前端显示进度与日志，不阻塞浏览器。

### 5.6 内容编辑体验

| 项 | 建议 |
|---|---|
| **实时预览** | 编辑与预览并排（`routes/widget-preview.tsx` 已存在此能力，复用） |
| **自动保存草稿** | 编辑中的内容存本地，意外关闭可恢复 |
| **版本对比** | 内容已有 staging/production 状态（`schemas/content.py` 有 `STAGING`），补 diff 视图 |
| **富文本** | 已有 `components/rich-editor/`，补：图片粘贴上传、表格、代码块 |
| **发布闸门** | 发布前校验（必填、断链、未保存警告） |

### 5.7 设置页面重构

见 §5.3.2。补充三个体验细节：

1. **搜索设置项** —— 1199 行的设置页拆成 6 个子页后仍需要快速定位，加一个搜索框（前端过滤 + 高亮）。
2. **变更预览** —— 保存前显示"将修改哪些项"，尤其是 integrations 与 security。
3. **导出/导入配置** —— 环境间迁移配置，配合已有的 `settings_service.py`。

### 5.8 仪表盘（新增）

管理员登录后第一屏。回答三个问题：

```
今天需要我做什么？
  ├─ 待审内容（草稿 / 待发布）
  ├─ 失败的导入任务
  ├─ 待处理的种子申请
  └─ 插件健康检查失败

站点状态如何？
  ├─ 数据量（基因 / 突变体 / 变异 · 对比上周）
  ├─ 最近 7 天访问趋势
  └─ API 健康（P95 / 错误率）

最近发生了什么？
  └─ 审计日志最近 20 条（谁在什么时候改了什么）
```

**数据来源**：后端已有 `stats`、`audit`、`analytics`（ClickHouse）、`widget-health`，主要是聚合展示，后端改动小。

### 5.9 可发现性与搜索

**命令面板**（⌘K / Ctrl+K）—— 后台效率提升最显著的单点改动：

```
⌘K → 输入基因 ID → 跳到该基因的编辑页
   → 输入"设置" → 跳到对应设置子页
   → 输入"导入" → 新建导入
   → 输入用户名 → 跳到用户管理
```

同时适用于**前台**（web）—— 用户搜索基因/突变体时也能用。

### 5.10 键盘效率

| 快捷键 | 动作 |
|---|---|
| `⌘K` / `Ctrl+K` | 命令面板 |
| `g` 然后 `d` | 跳仪表盘（g + 首字母的两段式） |
| `/` | 聚焦当前列表的搜索框 |
| `j` / `k` | 列表上下移动 |
| `x` | 勾选当前项 |
| `⌘S` / `Ctrl+S` | 保存当前表单 |
| `Esc` | 关闭抽屉/模态 |

### 5.11 错误与恢复（补 ErrorBoundary）

**这是最紧急的一个改动** —— admin 端目前没有错误边界：

```tsx
// apps/admin/src/routes/__root.tsx —— 补上与 web 端同等的保护
import { ErrorBoundary } from "../components/error-boundary";

export const Route = createRootRoute({
  component: () => (
    <ErrorBoundary>
      <AdminLayout />
    </ErrorBoundary>
  ),
});
```

```tsx
// 并为每个业务路由加一层，把崩溃限制在单页内
// components/route-error-boundary.tsx
export function RouteErrorBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary
      fallback={(error, reset) => (
        <Result
          status="error"
          title="此页面出错了"
          subTitle={error.message}
          extra={[
            <Button key="retry" onClick={reset}>重试</Button>,
            <Button key="home" onClick={() => navigate({ to: "/" })}>返回仪表盘</Button>,
          ]}
        />
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
```

**配套**：把 error_code 映射（§4.4）也用到 admin，让管理员看到可操作的错误说明而非堆栈。

### 5.12 审计与撤销

后端 `core/audit.py` 已有完整能力。前端补：

1. **审计日志可筛选** —— 按人 / 动作 / 对象 / 时间范围（`routes/audit.tsx` 378 行，检查是否已支持）。
2. **"谁改的"可见** —— 内容详情页显示最后修改人与时间。
3. **撤销** —— 对可逆操作（发布/取消发布、设置变更）提供撤销按钮，走审计记录回滚。
4. **设置修订历史** —— 利用已有的 `system_setting_revisions`，提供 diff 与回滚 UI。

---

## 6. 路线图

| 阶段 | 内容 | 依赖 | 优先级 |
|---|---|---|---|
| **P0-1** | admin 补 ErrorBoundary + 路由级边界（§5.11） | — | 🔴 立即 |
| **P0-2** | 查询基线采集：pg_stat_statements 周报（§3.2） | — | 🔴 立即 |
| **P0-3** | 搜索 trigram 索引 + 并发 + 缓存 + 游标（§3.3） | P0-2 | 🔴 高 |
| **P0-4** | 设置页拆分（§5.3.2） | — | 🔴 高 |
| **P1-1** | 导入向导重构（§5.5） | — | 🟡 高 |
| **P1-2** | content.tsx 拆分（§5.3.1） | P0-4 | 🟡 中 |
| **P1-3** | 横切管线化：分页 / 审计 / 缓存 / 权限（§2.2） | — | 🟡 中 |
| **P1-4** | 契约行为层：错误码目录 + 幂等声明（§2.3） | — | 🟡 中 |
| **P1-5** | 仪表盘（§5.8） | — | 🟡 中 |
| **P2-1** | N+1 治理（§3.6） | P0-2 | 🟢 中 |
| **P2-2** | 前端分层与 query key 工厂（§4.1–4.3） | — | 🟢 中 |
| **P2-3** | 命令面板与键盘效率（§5.9–5.10） | P1-5 | 🟢 低 |
| **P2-4** | 架构守卫与 i18n 检查入 CI（§2.7、§4.7） | P1-3 | 🟢 低 |

**每个阶段的验收**见 §3.9（性能门禁）与 §4.8（测试门禁）。

---

## 7. 风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **E1** | **trigram 索引体积膨胀** | 索引可能达原表 1–3 倍，长文本字段尤甚 | 只索引必要字段；长文本用 `left(x, N)`；先在预发测量 |
| **E2** | **CJK 召回不达标** | `pg_trgm` 对中文短词命中率低 | 先测召回率；不达标上 `pg_bigm`，两者可共存 |
| **E3** | **`CREATE INDEX CONCURRENTLY` 在迁移中失败** | 不能在事务块内执行 | 用 `autocommit_block()`；先在预发演练 |
| **E4** | **admin 拆分引入回归** | 管理员工作流中断 | 按子页逐个拆、逐个灰度；保留旧路由重定向一周 |
| **E5** | **`lazy="raise_on_sql"` 全量切换炸生产** | 大量 500 | 配置开关默认关闭，测试/预发开启，收集触发点后分批修 |
| **E6** | **取消总数影响现有 UI** | 前端显示"共 N 条"的地方要改 | 改游标式 UI 或近似计数；与前端约定后再动后端 |
| **E7** | **横切管线过度抽象** | 学习成本上升，简单端点变复杂 | 管线做成可选组合，不强制；先在新增端点用 |
| **E8** | **导入向导重构范围失控** | 长时间无法交付 | 先做"错误可定位"与"先校验后导入"两项，其余后补 |

---

## 附录 A：关键文件索引

### 后端

| 文件 | 现状 | 本文档相关章节 |
|---|---|---|
| `core/exceptions.py` | 异常体系成熟，**不要改** | §1.1、§2.3 |
| `core/plugins.py` | 签名 + fail-closed，**不要改** | §1.1、§1.3 |
| `core/features.py` | 特性开关成熟 | §1.1 |
| `core/audit.py` | 审计能力完备 | §2.2.2、§5.12 |
| `core/ratelimit.py` | Redis Lua + fail-closed | §1.1 |
| `core/config.py` | 规范，缺可见性 | §2.4 |
| `core/database.py` | 引擎与会话管理 | §3.6 |
| `services/cache.py` | 有 `get_or_set`，**缺失效接口** | §3.7 |
| `services/search_service.py` | ILIKE 三次串行，无游标 | §3.3 |
| `services/clickhouse_service.py` | 预聚合查询 | §3.5 |
| `services/release_context.py` | 每请求多一次查询 | §2.2.3（v2.0 P0-6） |
| `models/auth.py:139-146` | 级联预加载 | §3.6 |
| `migrations/versions/0023_*` | 最新迁移 | 新增 `0024_search_trigram_indexes.py` |

### 前端（web）

| 文件 | 现状 | 相关章节 |
|---|---|---|
| `components/error-boundary.tsx` | **已接入 `__root.tsx`** | §4.4 |
| `lib/query-client.ts` | 配置良好 | §4.2 |
| `routes/blast.tsx` | 已用 zod | §4.5 |
| `lib/analyses-local.ts` | localStorage 兜底 | v3.0 已用统一任务中心取代 |
| `lib/perf.ts` | RUM 采集器**零 import** | v2.0 P0-7 |

### 前端（admin）

| 文件 | 行数 | 问题 | 相关章节 |
|---|---|---|---|
| `routes/content.tsx` | 1,248 | 20 处状态钩子 | §5.3.1 |
| `routes/settings.tsx` | 1,199 | 单表单管全站配置 | §5.3.2、§5.7 |
| `routes/imports.tsx` | 1,173 | 缺向导化 | §5.3.3、§5.5 |
| `routes/__root.tsx` | — | **无 ErrorBoundary** | §5.11 🔴 |
| `routes/audit.tsx` | 378 | 检查筛选能力 | §5.12 |
| `lib/auth-context.tsx` | — | 仅有的 context | §4.3 |

---

## 附录 B：四份方案的分工边界

| 主题 | 归属文档 | 本文档是否展开 |
|---|---|---|
| 首屏加载、分包、字体、WebGL、动效分级 | **v2.0** | ❌ 只引用 |
| PostgreSQL 调参、nginx、中间件、ClickHouse 写入 | **v2.0 §4** | ❌ 只引用 |
| 工程化改造（Vite chunk、CI Turbo 缓存、CSRF 统一、重试策略、antd-theme 去重、测试补全、nginx 安全头） | **v1.0** | ❌ |
| 内容管理、模板生成、SSG 管线、Page Builder 契约 | **v5.0** | ❌ |
| 桌面客户端、免安装分发、本地工具箱 | **v3.0** | ❌ |
| 后端分层收口、横切管线、契约行为层 | **本文档 §2** | ✅ |
| 查询性能（全文/分页/聚合/N+1/缓存/慢查询） | **本文档 §3** | ✅ |
| 前端分层、数据获取、状态边界、a11y | **本文档 §4** | ✅ |
| 管理后台体验 | **本文档 §5** | ✅ |

**重叠处的处理**：
- v2.0 P0-4（搜索索引）→ 本文档 §3.3 深化（完整迁移、CJK 考量、并发、游标）
- v2.0 P0-6（release context 缓存）→ 本文档 §2.2.3 用 `@cached` 装饰器落地
- v2.0 §4.2（User 级联加载）→ 本文档 §3.6 给分阶段推进方案
- v2.0 §5（监控与告警）→ 本文档 §2.6 补后端侧，§3.8 补慢查询闭环

---

## 附录 C：勘误

> **2026-08-29 更正**（详见 [`optimization-master-plan.md`](optimization-master-plan.md) §1）

本方案早期版本曾把三条内容归因为"v1.0 已记录"，经回溯核对其中有误：

| 先前表述 | 核实结果 |
|---|---|
| "导入（GFF3/突变体）只计数不落库" | ❌ 不成立。`import_studio_service.py`（299 行）8 个函数全为校验/规整，不落库是设计使然；`module_import_service.py:106,150` 有 `flush()` 确实写库 |
| "hash_ip 硬编码盐" | ⚠️ 事实存在，但出处是 `analytics_service.py:32`（`salt: str = "soymutdb-analytics"`），**v1.0 文档中没有这条** |
| "nginx server 级正则误路由 admin/jbrowse" | ❌ 不成立。`infra/nginx/conf.d/default.conf:100-102` 用 `location ^~ /admin/` 并注释说明正是为规避正则拦截；`:124` `/samples/` 同理。该配置是**正面范例** |

**维护约定**：引用"某文档已记录 X"时必须给出 `文件:行号`；给不出则标注"待核实"，不得当作既有事实传递。

---

*本方案为设计提案。所有索引体积、性能目标与工期需在基线采集（§3.2）后修订。*
