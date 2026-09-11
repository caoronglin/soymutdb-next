# SoyMutDB 优化总纲

> **版本**：v6.0（整合版）
> **日期**：2026-08-29
> **性质**：执行视图，不是又一份设计文档
> **上游**：v1.0 工程化改造 · v2.0 性能与动效 · v3.0 桌面客户端 · v4.0 架构与体验 · v5.0 内容与模板

---

## §0 这份文档怎么用

五份方案已经写完了各自的详细设计。这份文档不复述它们的内容，只回答五个问题：

1. **先做什么** —— §6 统一优先级
2. **谁依赖谁** —— §5 依赖图
3. **有没有重复或冲突** —— §4 裁决表
4. **有没有说错的地方** —— §1 勘误表
5. **总共多大工作量，怎么验收** —— §7、§8

**阅读顺序**：第一次看这份文档，按 §1 → §4 → §6 的顺序读。§1 有必须知道的更正，§4 有必须遵守的裁决，§6 决定你明天做什么。其余章节按需查阅。

**维护约定**：子文档（v1.0–v5.0）负责"怎么做"，本文档负责"先做哪个"。子文档新增任务时，同步更新本文档附录 A；优先级变动时，更新 §6。

---

## §1 勘误表（务必先读）

整合过程中对前五份文档的引用做了逐条回溯核对，发现三处实质错误。**这些错误如果不纠正，会直接导致后续工作走错方向。**

### C1 · "nginx server 级正则误路由 admin/jbrowse" —— 不成立

| 项 | 内容 |
| --- | --- |
| 先前说法 | v4.0、v5.0 §9 R1 均称"v1.0 已记录 nginx server 级正则误路由 admin/jbrowse 的先例" |
| 核实结果 | ❌ **不成立。nginx 配置是刻意正确的，是正面范例** |

实际配置：

```nginx
# infra/nginx/conf.d/default.conf:98-102
    # Admin console — IP-restricted (private networks only)
    # ^~ prevents regex asset locations from intercepting /admin/* paths
    # ----------------------------------------------------------------
    location ^~ /admin/ {
```

```nginx
# infra/nginx/conf.d/default.conf:120-124
    # /samples/ — static sample HTML pages (SSG output from web frontend)
    # ^~ ensures sample pages aren't intercepted by asset regex locations
    # ----------------------------------------------------------------
    location ^~ /samples/ {
```

两处都用了 `^~` 前缀匹配，并且**注释里明确写了这么做正是为了规避资源正则 location 的拦截**。作者预见到了这个坑并主动处理了。

**修正**：这不是待修复的 bug，而是 v5.0 §2 新增 `/pages/*` 路由时**应当照抄的模式**——用 `location ^~ /pages/` 而不是普通前缀匹配，否则会被资源类正则 location 抢走。

### C2 · "导入（GFF3/突变体）只计数不落库" —— 不成立

| 项 | 内容 |
| --- | --- |
| 先前说法 | v4.0、v5.0 称"v1.0 已记录导入只计数不落库" |
| 核实结果 | ❌ **不成立。两类导入服务的职责不同，都不是"只计数"** |

- `apps/api/app/services/import_studio_service.py`（299 行）的 8 个函数**全部是校验与规整**：`validate_import_shape`、`validate_field_mapping`、`validate_data_patches`、`validate_import_draft_snapshot`、`apply_data_patches`、`build_publication_manifest`、`canonical_records`。它处理的是 draft 快照，**不落库是设计使然**，不是缺陷。
- `apps/api/app/services/module_import_service.py:106`、`:150` 有 `await db.flush()`，**确实在写库**。

**修正**：从任务清单中移除该条目。若仍有关于导入正确性的疑虑，需要先写一份针对导入链路的独立审计报告，而不是沿用一条来源不明的结论。

### C3 · "hash_ip 硬编码盐" —— 事实存在，但出处标错

| 项 | 内容 |
| --- | --- |
| 先前说法 | 标注为"v1.0 已记录" |
| 核实结果 | ⚠️ **代码事实成立，但 v1.0 文档里没有这条** |

真实位置：

```python
# apps/api/app/services/analytics_service.py:32
def hash_ip(ip: str, salt: str = "soymutdb-analytics") -> str:
```

**修正**：这是一个真实的安全问题（盐硬编码在源码里，同盐可彩虹表反查），但出处是代码而非 v1.0 文档。归入本总纲附录 A 的 **A-17**，优先级 P1（analytics 属内部统计，非认证凭据，但盐值泄露会削弱匿名化承诺）。

### C4 · v1.0 的内容定性错误

| 项 | 内容 |
| --- | --- |
| 先前说法 | 前几份文档的索引表把 v1.0 定性为"正确性与工程卫生" |
| 核实结果 | ❌ **定性错误。v1.0 是一份工程化改造清单，不是正确性审计** |

v1.0 的实际章节：

| Phase | 条目 |
| --- | --- |
| P0 | 1.1 Admin Vite React chunk 匹配修复 · 1.2 CI Turbo 远程缓存 |
| P1 | 2.1 CSRF 保护统一到 api-client · 2.2 重试策略集成到传输层 · 2.3 设计系统去重（共享 antd-theme） |
| P2 | 3.1 共享工具去重（cn + format） · 3.2 测试补全 · 3.3 Widget 运行时类型安全 · 3.4 版本统一（vitest + vite catalog） |
| P3 | 4.1 Nginx 安全头补全 · 4.2 .dockerignore 补全 · 4.3 ESLint no-console · 4.4 Docker gzip 压缩脚本去重 · 4.5 Knip 配置收窄 |
| 附 | 部署顺序总览 · 每 Phase 部署检查清单 · 回滚矩阵 · CI/CD 影响 · 预期收益 |

**修正**：本文档 §3 的索引表已更正为"工程化改造"。这也解释了 C1–C3 为何会发生——此前把 v1.0 当成了正确性问题的归档处，往里归因了不属于它的条目。

### 教训

三条错误里，两条是"把未经验证的结论当作已记录事实"造成的。**后续任何方案文档在引用"某文档已记录 X"时，必须给出文件与行号；给不出就标注为"待核实"，不得当作既有事实传递。**

---

## §2 全局基线：一组统一的数字

五份方案各自引用了一些数字，这里统一收口，避免口径不一。

| 维度 | 数值 | 来源 |
| --- | --- | --- |
| Python 代码 | 382 文件 / 86,712 行 | v2.0 |
| TS + TSX 代码 | 336 文件 / 70,857 行 | v2.0 |
| 后端 service | 35 文件 / 10,025 行，跨服务 import 仅 3 处且无环 | v4.0 |
| 后端迁移 | 23 个 · 94 处 `create_index` · 63 个 `Index()` | v4.0 |
| 异常体系 | `SoyMutDBError` + 13 子类，各带 `error_code` | v4.0 |
| 内置插件 | 5 个（jbrowse / blast / analyses / mcp / ols4），签名 fail-closed | v4.0 |
| Admin 路由 | 30 个 / 9,207 行 | v4.0 |
| Admin 三大巨型页 | content 1,248 · settings 1,199 · imports 1,173 = 3,620 行（39%） | v4.0 |
| Page Builder 组件 | 19 个，两端完全对齐 | v5.0 |
| SSG 构建步骤 | 9 步串行，external / internal 双变体 | v5.0 |
| 首屏 JS | 2.02 MB（gzip 前） | v2.0 |
| 字体 | 12.7 MB | v2.0 |
| Admin ErrorBoundary | **0 个**（web 端有） | v4.0 |

**两条最重要的事实**：

1. **后端基建已经相当成熟**——异常体系、服务层无环、keyset 分页、插件签名 fail-closed、OpenAPI→TS 契约链路带 CI 校验。任何"引入统一错误处理""引入分层架构"的建议都是倒退。
2. **Admin 端连 ErrorBoundary 都没有**。这是所有 Admin 工作的前置风险，也是性价比最高的单项改动。

---

## §3 五份方案的分工与索引

| 文档 | 真实主题 | 核心内容 |
| --- | --- | --- |
| [`optimization-plan.md`](optimization-plan.md)（v1.0） | **工程化改造** | 4 Phase 共 14 项：Vite chunk 修复、CI Turbo 缓存、CSRF 统一、重试策略、antd-theme 去重、共享工具去重、测试补全、Widget 类型安全、版本统一、nginx 安全头、.dockerignore、ESLint、gzip 去重、Knip 收窄；含部署与回滚矩阵 |
| [`performance-optimization-plan.md`](performance-optimization-plan.md)（v2.0） | 性能与动效 | P0 七项（WebGL 单实例、字体子集化、antd 拆桶、搜索索引、ClickHouse 批量写入、release context 缓存、启用 perf 监控）+ 动效 T0–T4 分级与统一 rAF 调度 |
| [`desktop-client-plan.md`](desktop-client-plan.md)（v3.0） | Tauri 桌面客户端 | 免安装分发、跨站认证三方案（keychain / SameSite=None / 本地反代）、本地工具箱、本地与远程调度边界、6 个 Spike |
| [`platform-optimization-plan.md`](platform-optimization-plan.md)（v4.0） | 架构收口 · 查询性能 · 前端 · 管理后台 | 横切管线化、`pg_trgm` 索引、游标分页、前端状态边界、Admin 巨型页拆分、命令面板 |
| [`content-template-plan.md`](content-template-plan.md)（v5.0） | 内容管理 · 模板生成 · SSG | 三套内容源收敛、StaticPage 进 SSG、模板数据化、组件契约单一真相、编辑器拖拽 |
| **本文档**（v6.0） | **执行视图** | 勘误、裁决、依赖、优先级、里程碑、验收 |

---

## §4 冲突与重叠裁决

整合时发现 4 处重叠、2 处真冲突。以下裁决**具有约束力**，实施时以裁决结果为准。

### §4.1 明确重复（以谁为准）

| # | 重叠项 | v? | v? | **裁决** |
| --- | --- | --- | --- | --- |
| D1 | **content.tsx 拆分** | v4.0 P1-2（通用方法论：识别巨型页 → 按职责切分） | v5.0 §5.2（具体行边界：200/548/758/951/1036 + StaticPage 语义） | **以 v5.0 为准**。v4.0 §5 保留为方法论，不再重复列任务 |
| D2 | **搜索索引** | v2.0 P0-4（一条占位："搜索索引"） | v4.0 §3.Ⅰ（`pg_trgm` GIN 完整方案 + 四个坑 + `pg_bigm` 评估） | **以 v4.0 为准**。v2.0 的条目并入 v4.0，不单独排期 |
| D3 | **契约同步** | v4.0 P1-4（契约行为层：错误码目录、`x-idempotent`、分页响应头） | v5.0 P0-3（组件契约：`PAGE_COMPONENT_TYPES` + CI 校验脚本） | **两者不冲突，但都叫"契约"**。本文档统一命名：v4.0 的称 **API 行为契约**，v5.0 的称 **组件注册表契约**。分开排期，v5.0 优先（1–2 天即完成） |
| D4 | **前端分层** | v4.0 §4（分层、数据获取、状态边界、错误降级） | v5.0 §5.2（content.tsx 拆分时抽 query key 工厂 + URL 承载筛选） | **不冲突**，v5.0 是 v4.0 铁律的具体应用实例。v5.0 的改动应满足 v4.0 §4.3 的状态边界要求 |

### §4.2 真冲突（必须一起改）

| # | 冲突 | 说明 | **裁决** |
| --- | --- | --- | --- |
| X1 | **nginx 路由** | v5.0 §2 要新增 `/pages/*` 静态页路由；v1.0 P3-4.1 要补 nginx 安全头 | **同一批次修改 `infra/nginx/conf.d/default.conf`**，不得分两次。新路由照 `/samples/` 的 `location ^~ /pages/` 写（见 C1），并同时套用统一安全头。理由：nginx 每次改动都要全量回归，分两次改等于回归两次 |
| X2 | **Admin ErrorBoundary 与所有 Admin UI 改动** | v4.0 P0-1 要补 ErrorBoundary；v4.0 P0-4（设置页）、v4.0 P1-1（导入向导）、v5.0 P1-2（content 拆分）都在动 Admin | **ErrorBoundary 必须先于所有 Admin UI 改动合并**。它是这些改动的保险——拆分过程引入的错误，有边界时能定位到具体页面，没有就是整站白屏 |

### §4.3 顺序约束（不冲突但有先后）

| 前置 | 解锁 | 原因 |
| --- | --- | --- |
| v5.0 P0-3 契约单一真相 | v5.0 P1-4 编辑器拖拽 | `canNest` 依赖新增的 `is_layout_container` 字段；否则嵌套规则只是把第三份真相换个地方 |
| v5.0 P0-1 StaticPage 进 SSG | v5.0 P1-3 迁移器 | 先把存量内容救活，再谈迁移；否则迁移期内容中断 |
| v4.0 P0-2 基线采集 | 所有查询性能优化 | 没有 `pg_stat_statements` 基线，优化无法验收 |
| v4.0 P1-4 API 行为契约 | v3.0 桌面客户端 | Tauri 客户端完全依赖 API，错误码与分页行为不定型，客户端就要跟着改 |
| v3.0 S1 跨站认证 Spike | v3.0 其余全部 | 认证走不通，整个桌面客户端方案不成立。这是 go/no-go 门槛 |

---

## §5 依赖图

```
                    ┌─────────────────────┐
                    │  C1 勘误：nginx 配置 │  （阅读前置，非任务）
                    │  是范例不是 bug      │
                    └─────────────────────┘

  【保险与基线】
  A-01 admin ErrorBoundary ──────────┬──→ A-07 设置页拆分
                                     ├──→ A-08 content.tsx 拆分
                                     └──→ A-09 导入向导重构
  A-02 pg_stat_statements 基线 ──────┬──→ A-04 查询性能四件套
                                     └──→ A-11 N+1 治理

  【内容链路】
  A-03 StaticPage 进 SSG ────────────→ A-10 StaticPage 迁移器 ──→ 体系收敛
  A-05 契约单一真相 + CI ───────────┬──→ A-13 编辑器拖拽
                                     └──→ 模板可视化选择器（含于 A-06）
  A-06 模板数据化 ──────────────────→ A-14 SSG 路由动态化

  【架构与体验】
  A-12 横切管线化 ──────────────────→ A-15 API 行为契约 ──→ 【v3.0 桌面客户端】
                                                             S1 认证 Spike ──[go]──→ Tauri 客户端 ──→ 本地工具箱
                                                                          └─[no-go]─→ 降级方案 B

  【独立，可随时插入】
  A-11 首屏性能七项（v2.0 P0）  ·  A-16 hash_ip 盐外置  ·  A-17 命令面板
```

**关键路径**（最长依赖链）：

```
A-05 契约 → A-13 拖拽 → A-06 模板选择器完整形态
A-03 SSG 止血 → A-10 迁移 → 体系收敛
A-12 管线化 → A-15 行为契约 → S1 Spike → Tauri 客户端
```

三条关键路径**互不阻塞**，可以三条线并行推进。

---

## §6 统一优先级

排序依据：`风险 × 价值 ÷ 成本`。风险高（安全、数据、白屏）、价值大（功能不生效）、成本低（天级）的排前面。

### 第一梯队 · 立即（第 1–2 周）

| ID | 任务 | 来源 | 工作量 | 理由 |
| --- | --- | --- | --- | --- |
| **A-01** | Admin 补 ErrorBoundary | v4.0 P0-1 | **0.5d** | 半天、零风险，是后续所有 Admin 改动的保险 |
| **A-02** | `pg_stat_statements` 基线周报 | v4.0 P0-2 | 1d | 没有基线的优化无法验收 |
| **A-03** | StaticPage 进快照 + SSG | v5.0 P0-1 | 2–3d | **功能不生效**：用户发布内容，公共站零产出 |
| **A-05** | 组件契约单一真相 + CI 校验 | v5.0 P0-3 | 1–2d | 消灭三份真相；解锁 A-13 |

四项合计 **4.5–6.5 天**，且彼此不阻塞，可以并行。

### 第二梯队 · 近期（第 3–6 周）

| ID | 任务 | 来源 | 工作量 | 理由 |
| --- | --- | --- | --- | --- |
| **A-04** | 查询性能四件套（trigram / 并发 / 缓存 / 游标） | v4.0 P0-3 | 5–7d | 依赖 A-02 基线 |
| **A-06** | 模板数据化（表 + seed + API + 前端） | v5.0 P0-2 | 4–5d | 解锁管理员自定义模板 |
| **A-07** | 设置页拆分（1,199 行 → 6 子页） | v4.0 P0-4 | 3–4d | 依赖 A-01 |
| **A-16** | `hash_ip` 盐外置到配置 | C3 勘误新增 | 0.5d | 安全问题，成本极低 |

### 第三梯队 · 中期（第 7–12 周）

| ID | 任务 | 来源 | 工作量 | 依赖 |
| --- | --- | --- | --- | --- |
| **A-11** | 首屏性能七项（v2.0 P0 全量） | v2.0 P0 | 8–10d | — |
| **A-08** | content.tsx 拆分 + query key 工厂 + URL 状态 | v5.0 §5.2 | 1–2d | A-01 |
| **A-20** | 导航重构（统一 Content 分组） | v5.0 P1-1 | 1d | A-06 |
| **A-09** | 导入向导重构（1,173 行 → 四步向导） | v4.0 P1-1 | 4–5d | A-01 |
| **A-12** | 横切管线化（`@cached` / 声明式审计 / 统一 `Page`） | v4.0 P1-3 | 6–8d | — |

### 第四梯队 · 远期（第 13 周起）

| ID | 任务 | 来源 | 工作量 | 依赖 |
| --- | --- | --- | --- | --- |
| **A-10** | StaticPage 迁移器 | v5.0 P1-3 | 3d | A-03 |
| **A-13** | 编辑器拖拽（dnd-kit） | v5.0 P1-4 | 3d | A-05 |
| **A-14** | SSG 路由清单动态化 | v5.0 P2-1 | 2d | A-03 |
| **A-15** | API 行为契约（错误码目录 / 幂等 / 分页头） | v4.0 P1-4 | 4–5d | A-12 |
| **A-17** | 命令面板 ⌘K | v4.0 P2-3 | 3d | A-01 |
| **A-18** | 前端分层与测试 | v4.0 P2-2 | 5–7d | A-12 |
| **A-19** | 架构守卫入 CI | v4.0 P2-4 | 2d | A-12 |
| **S1–S6** | 桌面客户端 Spike → M0–M5 | v3.0 | 见 v3.0 | A-15 |

### 明确不做

| 项 | 理由 |
| --- | --- |
| 引入 repository 层 | 服务层 35 文件仅 3 处跨服务 import 且无环，加层是净负担 |
| 重写异常处理 | 已有 `SoyMutDBError` + 13 子类 + error_code |
| 替换 Page Builder 为第三方低代码 | 已有 19 组件 + 服务端校验 + 版本 + 审批，自建部分不可复用 |
| 桌面客户端内嵌数据库 | 用户已明确"不携带数据，通过 API 交互" |

---

## §7 工作量汇总

| 梯队 | 任务数 | 工作量 | 并行度 |
| --- | --- | --- | --- |
| 第一梯队 | 4 | 4.5–6.5d | 4 项互不阻塞，可 4 线并行 → 墙钟 ~2d |
| 第二梯队 | 4 | 12.5–16.5d | A-04/A-06/A-07 可并行 → 墙钟 ~7d |
| 第三梯队 | 5 | 20–24d | A-11 独立，A-08/A-09/A-12 可并行 → 墙钟 ~12d |
| 第四梯队 | 8 | 24–29d | 三条关键路径并行 → 墙钟 ~15d |
| **合计（不含桌面客户端）** | **21** | **61–76 人日** | **理想并行下墙钟 ~8–10 周（2 人）** |

**桌面客户端**（v3.0）单独计：Spike 阶段 S1–S6 约 15–20 人日；S1 通过后再投入 M0–M5 完整实施。建议 **S1 认证 Spike 提前到第一梯队末尾做**（2 天），因为它是整个方向的 go/no-go 门槛——早否定早止损。

---

## §8 验收标准

每个里程碑配可验证的指标。**没有指标的任务不计入完成。**

### M0 · 止血与基线（第 2 周末）

- [ ] Admin 任意页面组件抛错时，显示错误边界而非整站白屏；错误可被定位到具体路由
- [ ] `pg_stat_statements` Top 20 慢查询周报已产出，第一份基线入库
- [ ] 在 Content → Pages 新建并发布一个 StaticPage，重新 SSG 后 `dist/pages/{slug}/index.html` 存在且含正文；取消发布后该文件消失
- [ ] CI 新增 `check:page-registry`，人为改动后端组件清单后 CI 失败

### M1 · 内容链路打通（第 6 周末）

- [ ] `/content/pages` 列表页 P95 响应时间较基线下降 ≥ 50%
- [ ] 在管理后台新增一个模板（不经发版），刷新后能在创建页看到并使用
- [ ] 设置页拆分为 6 个子页，每页独立保存，保存一个域不影响其他域
- [ ] `hash_ip` 的盐从配置读取，源码中无硬编码字符串

### M2 · 性能与体验（第 12 周末）

- [ ] 首屏 JS 从 2.02 MB 降至 ≤ 1.2 MB
- [ ] 字体从 12.7 MB 降至 ≤ 1.5 MB
- [ ] LCP ≤ 2.5s、INP ≤ 200ms（生产环境 P75）
- [ ] content.tsx 单文件 ≤ 400 行；筛选状态可通过 URL 分享后完整还原
- [ ] 导入向导：错误行可定位、可下载错误清单、重复提交不产生重复数据

### M3 · 架构收口（第 20 周末）

- [ ] 横切逻辑（分页/审计/缓存/权限）由声明式管线提供，路由层无重复样板
- [ ] 架构守卫进 CI，人为引入跨层依赖时 CI 失败
- [ ] 命令面板可用，高频操作的键盘路径 ≤ 3 次按键

### S1 · 桌面客户端 go/no-go（第 3 周内）

- [ ] Tauri WebView 冷启动能通过跨站 cookie 恢复会话，无需重新登录
- [ ] 若失败，明确记录失败原因并选择降级方案 B（`SameSite=None` + 白名单）或终止

---

## §9 风险总表

汇总五份文档的风险，去重后按严重度排列。

| ID | 风险 | 来源 | 影响 | 缓解 |
| --- | --- | --- | --- | --- |
| **R1** | `/pages/*` 静态页路由被资源正则 location 拦截 | v5.0（经 C1 更正） | 静态页 404 | 照 `default.conf:124` 用 `location ^~ /pages/`；**与 v1.0 P3-4.1 的 nginx 安全头同批修改** |
| **R2** | `schema_version` 1→2 破坏旧快照消费方 | v5.0 | 旧前端读新快照异常 | 消费方仅 `fetch-content-snapshot.ts` 一处；检查 `fallback-data.ts` 是否含 `schema_version` |
| **R3** | `pg_trgm` 对中文二字词召回率低 | v4.0 | 搜索结果不全 | 评估 `pg_bigm`（2-gram 对 CJK 友好），两者可共存；阈值需实测 |
| **R4** | `CREATE INDEX CONCURRENTLY` 在事务块内失败 | v4.0 | 迁移中断 | 用 `autocommit_block()`；迁移脚本本地先跑一遍 |
| **R5** | 跨站 cookie 认证走不通 | v3.0 | 桌面客户端方案不成立 | **S1 Spike 提前到第 3 周**，2 天内出结论；备选方案 B 已备好 |
| **R6** | 内置模板与前端兜底常量不一致 | v5.0 | API 不可达时创建出过期模板 | 兜底只保留 blank + research 两个最简模板 |
| **R7** | StaticPage 迁移丢失富文本格式 | v5.0 | 迁移后样式异常 | 生成 draft 不自动发布；原记录保留可回滚 |
| **R8** | `content_key` 的 i18n 方案与 `packages/i18n` 不兼容 | v5.0 | 双语占位失效 | 先技术验证；不兼容则降级为模板携带双语字面量 |
| **R9** | 字体子集化后生僻字显示为豆腐块 | v2.0 | 内容缺字 | 用 GB2312 一级汉字 + 动态补丁；保留完整字体作 fallback |
| **R10** | dnd-kit 与 antd 弹层冲突 | v5.0 | 拖拽时弹层错位 | `property-panel.tsx` 若用 Modal 需设 `getContainer={false}` |
| **R11** | 首屏优化引入 ES module 初始化循环 | v2.0 | 白屏 | `manualChunks` 拆桶后必须跑一遍生产构建冒烟 |

---

## 附录 A · 任务全清单

按优先级平铺，含来源、工作量、依赖。**本文档是任务状态的唯一权威来源**——子文档新增任务时同步更新此表。

| ID | 任务 | 来源 | 梯队 | 工作量 | 依赖 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| A-01 | Admin 补 ErrorBoundary | v4.0 P0-1 | 1 | 0.5d | — | 已完成（已验证） |
| A-02 | `pg_stat_statements` 基线周报 | v4.0 P0-2 | 1 | 1d | — | 已完成（Mamba PostgreSQL 16 preload/扩展、Top-20 周报脚本与 25 万行首份基线已验证） |
| A-03 | StaticPage 进快照 + SSG | v5.0 P0-1 | 1 | 2–3d | — | 已完成（API 测试已验证） |
| A-05 | 组件契约单一真相 + CI | v5.0 P0-3 | 1 | 1–2d | — | 已完成（已验证） |
| A-04 | 查询性能四件套 | v4.0 P0-3 | 2 | 5–7d | A-02 | 进行中（Mamba 0027、25 万行 Bitmap Index Scan、真实 DB 搜索字面量/89.87 ms 调用/continuation cursor；多 source keyset 兼容契约已设计，见 `a04-search-keyset-continuation.md`） |
| A-06 | 模板数据化 | v5.0 P0-2 | 2 | 4–5d | — | 已完成（Mamba 0026、模板 CRUD/builtin 不可变与 seed upsert 真实 DB、模型/API/OpenAPI client 已验证） |
| A-07 | 设置页拆分 | v4.0 P0-4 | 2 | 3–4d | A-01 | 已完成（四个独立表单及 CDN revisioned settings optimistic patch 已验证） |
| A-16 | `hash_ip` 盐外置 | C3 勘误 | 2 | 0.5d | — | 已完成（Compose 注入已补） |
| A-11 | 首屏性能七项 | v2.0 P0 | 3 | 8–10d | — | 进行中（AntD provider 延迟加载后 static-artifact 初始 JS 930 KB（≤1.2 MB guard）、CSS 78.6 KB；仍缺生产 RUM LCP/INP） |
| A-08 | content.tsx 拆分 | v5.0 §5.2 | 3 | 1–2d | A-01 | 已完成（252 行组件拆分、URL state 与路由组合测试已验证） |
| A-20 | 导航重构 | v5.0 P1-1 | 3 | 1d | A-06 | 已完成（统一 Content 导航与安全 Legacy Pages 迁移预览已验证） |
| A-09 | 导入向导重构 | v4.0 P1-1 | 3 | 4–5d | A-01 | 进行中（类型、来源、模块预览、验证报告切片；submit route upload-open contract 已类型验证；Imports dashboard 已有仅暴露 resume-safe metadata 的 server draft list 与 Resume link；`?draft=<id>` 使用既有 getDraft() 加载 persisted state，Mamba API/client/Admin 聚焦测试通过；未在 pre-upload wizard 伪造 DatasetVersion 元数据，mapping/patch/validate/commit editor controls 仍待接入） |
| A-12 | 横切管线化 | v4.0 P1-3 | 3 | 6–8d | — | 进行中（声明式缓存与六个 Admin 写端点审计策略已验证；路径/方法/角色冻结基线已加入测试） |
| A-10 | StaticPage 迁移器 | v5.0 P1-3 | 4 | 3d | A-03 | 进行中（Mamba 真实 DB 已验证 dry-run、draft-only、源页不变与重试幂等；受治理 apply 设计已批准，仍刻意不暴露 apply endpoint/UI，见 `a10-static-page-migration-apply-governance.md`） |
| A-13 | 编辑器拖拽 | v5.0 P1-4 | 4 | 3d | A-05 | 进行中（嵌套拖拽、重基准、DnD adapter 与真实 KeyboardSensor lifecycle 已测；artifact PointerSensor 尝试未触发 onDragEnd，E2E 保持 skip） |
| A-14 | SSG 路由动态化 | v5.0 P2-1 | 4 | 2d | A-03 | 已完成（Mamba 真实 DB → published-routes API → embed-page-definitions 静态产物已验证） |
| A-15 | API 行为契约 | v4.0 P1-4 | 4 | 4–5d | A-12 | 已完成（错误码、幂等、分页、登录限流与文档化的显式安全重试边界已验证） |
| A-17 | 命令面板 | v4.0 P2-3 | 4 | 3d | A-01 | 进行中（路由、限量基因搜索与用户查询审计；email-like 输入仅能触发 `limit: 5` gene lookup；非编辑态 `B` 侧栏切换安全回归已验证） |
| A-18 | 前端分层与测试 | v4.0 P2-2 | 4 | 5–7d | A-12 | 进行中（Web + Admin content query key/URL state CI 边界；content list/version keys 保留 `contentKeys.all` invalidation root 的回归测试已验证） |
| A-19 | 架构守卫入 CI | v4.0 P2-4 | 4 | 2d | A-12 | 进行中（导入边界、服务无环、i18n、六个 Admin 审计路由与九条已审分页 GET 基线均由 CI pytest 硬门禁） |
| A-21 | 发布就绪检查 | v5.0 P2-2 | 4 | 2d | A-06 | 进行中（就绪 UI + 权威插件能力检查；Mamba runtime 已报告 PostgreSQL 健康与缺失的 extended 依赖） |
| A-22 | 构建产物校验断言 | v5.0 P2-3 | 4 | 1d | A-03 | 已完成（定向验证） |
| S1 | 跨站认证 Spike | v3.0 | 1（建议提前） | 2d | A-15 | 进行中（后端 Go/No-Go harness 已就绪） |
| S2–S6 | 其余 Spike | v3.0 | 4 | 13–18d | S1 通过 | 待办 |
| **已移除** | ~~导入只计数不落库~~ | ~~v4.0/v5.0~~ | — | — | — | **C2 判定不成立** |
| **已移除** | ~~nginx 正则误路由修复~~ | ~~v4.0/v5.0~~ | — | — | — | **C1 判定不成立** |

---

## 附录 B · 受影响文件总表

按子系统归拢，便于评估改动面与回归范围。

### 后端（`apps/api`）

| 文件 | 关联任务 |
| --- | --- |
| `app/services/content_snapshot_service.py` | A-03（新增 `static_pages`，`schema_version` 1→2） |
| `app/services/analytics_service.py:32` | A-16（`hash_ip` 盐外置） |
| `app/services/search_service.py` | A-04（`ILIKE` → trigram + 并发） |
| `app/services/cache.py` | A-12（新增 `delete_prefix`） |
| `app/services/static_page_migration_service.py`（新建） | A-10 |
| `app/page_builder/registry.py` | A-05（组件契约）、A-06（模板校验） |
| `app/page_builder/schemas.py` | A-05（`is_layout_container`）、A-06（模板 DTO） |
| `app/api/v1/admin_page_builder.py` | A-05、A-06（模板 API） |
| `app/api/v1/page_definitions.py` | A-14（`published-routes` 端点） |
| `app/models/page_builder.py` | A-06（`PageTemplate` 模型） |
| `app/scripts/seed_page_builder.py` | A-06（内置模板种子） |
| `migrations/`（新增 0024、0025） | A-04（trigram 索引）、A-06（page_templates 表） |

### 前端 Admin（`apps/admin`）

| 文件 | 关联任务 |
| --- | --- |
| `src/routes/__root.tsx`（新建 ErrorBoundary） | A-01 |
| `src/routes/settings.tsx`（1,199 行 → 6 子页） | A-07 |
| `src/routes/content.tsx`（1,248 行 → 6 文件） | A-08 |
| `src/routes/imports.tsx`（1,173 行 → 四步向导） | A-09 |
| `src/routes/page-builder/index.tsx` | A-06（模板选择器） |
| `src/components/page-builder/page-builder-editor.tsx` | A-13（dnd-kit） |
| `src/lib/page-builder-templates.ts` | A-06（常量 → API 客户端） |
| `src/lib/page-builder-templates.test.ts` | A-05（删手写 allowlist） |
| `src/components/admin-sidebar.tsx` | A-20（导航重构） |
| `src/components/admin-header.tsx` | A-17（命令面板入口） |

### 前端 Web 与 SSG（`apps/web`）

| 文件 | 关联任务 |
| --- | --- |
| `scripts/ssg-content.ts` | A-03（静态页渲染） |
| `scripts/embed-page-definitions.ts:25` | A-14（`EMBED_ROUTES` 动态化） |
| `scripts/base-template.ts` | A-11（首屏模板） |
| `scripts/validate-static-tree.ts` | A-22（产物校验断言） |
| `vite.config.ts`（manualChunks） | A-11 |
| `public/fonts/` | A-11（子集化） |
| `src/page-builder/loader.ts` | A-14 |
| `src/routes/guide.tsx:355` | A-10（迁移后改走 PageDefinition） |

### 共享与基础设施

| 文件 | 关联任务 |
| --- | --- |
| `packages/shared/src/page-builder.ts` | A-05（常量驱动类型 + `is_layout_container`） |
| `packages/i18n/` | A-06（模板 `content_key`） |
| `infra/nginx/conf.d/default.conf` | **X1：A-03 新增 `/pages/` + v1.0 P3-4.1 安全头，同批修改** |
| `.github/workflows/ci.yml` | A-05（`check:page-registry`）、A-19（架构守卫） |
| `scripts/check-page-registry.sh`（新建） | A-05 |

---

## 附录 C · 文档维护约定

1. **子文档管设计，本文档管排序。** 子文档不写优先级与排期，避免两处更新不同步。
2. **引用必带行号。** 任何"某文档已记录 X"的说法必须给出 `文件:行号`；给不出就标"待核实"。这是 C1–C3 三条错误的直接教训。
3. **新增任务同步附录 A。** 子文档新增任务时，在附录 A 补一行，标来源与依赖。
4. **勘误持续累积。** 后续发现新的引用错误，追加到 §1，不修改原条目（保留错误痕迹便于追溯）。
5. **每季度重新核验基线。** §2 的数字会随代码演进失真，核验后更新并注明日期。
