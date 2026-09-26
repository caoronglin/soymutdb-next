# SoyMutDB 项目状态（2026-09-26）

> 单一状态视图。执行日志与逐项证据见 `docs/dev/vue-migration-recovery-status.md`，
> 功能矩阵见 `docs/wiki/applications.md`，本页只回答“现在是什么状态”。

> **2026-09-26 校正**：按 Vue 迁移后的现有代码复核。三端均为 Vue 3；`packages/motion` 与
> `packages/i18n` 已移除；公共站路由数以 `apps/web/src/router/routes.ts` 为准，管理端功能路由数以
> `apps/admin/src/router/index.ts` 为准。下文旧计数（34/14）与复现包清单已在本次校正中更新；
> “最近一次全绿”的测试条数为迁移期快照，包集合已变化。

## 一句话

Vue 迁移恢复的 P0/P1 已清零；i18n backlog 从 225 串清到 6 串；本机完成无 Docker 全面部署，
并在部署中定位、修复了“迁移链落后于模型”的 39 列 + 1 表漂移；远端多实例按约定保持未启动。

## 运行中的本机部署

| 服务 | 地址 | 状态 |
| --- | --- | --- |
| API（uvicorn） | `127.0.0.1:8010` | `/health` 200 · `live` 200 · `ready` = degraded（PG 正常） |
| 公共站 external | `http://localhost:8090/` | 200 · 同源 `/api/v1` 代理 · CSP 指向 8090 |
| 公共站 internal | `http://localhost:8094/` | 200 · `noindex, nofollow, noarchive` |
| 管理端 | `http://localhost:8091/login` | 200 · 登录/实例上下文/管理 API 全通 |
| JBrowse 2 | `http://localhost:8090/jbrowse/` | 200（同源前缀服务） |
| PostgreSQL | `127.0.0.1:55432/soymutdb_deploy` | 迁移到 `0042`；`0041` 已 seed 本地实例 |
| Redis / ClickHouse / MinIO | — | ❌ 本机无二进制且无 Docker：相应能力降级/503，**不计为通过** |

- 日志：`/tmp/soymutdb-deploy/*.log`；管理员 `deploy_admin` 密码：`/tmp/soymutdb-deploy/credentials.txt`（600，不入仓库）。
- 远端多实例：仅登记/探活/门户跳转；`administer()` 在默认与置位标志下都拒绝。管理端每页显示目标实例/发布/服务器。

## 数据与迁移

| 库 | 角色 | 状态 |
| --- | --- | --- |
| `soymutdb_deploy` | 本机部署运行库 | `0042`，漂移 = NONE |
| `soymutdb_testfixtures` | pytest fixture（每次重建） | 由测试会话创建/销毁 |
| `soymutdb_validation` | 迁移验证/升降级实操 | `0042` |
| `soymutdb_scratch42` | 0042 带数据回填验证（可丢） | `0042` |

- 迁移 `0042_reconcile_model_schema` 修复：`news_articles`/`static_pages` 双语列、
  `publications.is_featured`、`track_categories.display_order`、`tracks.*`、`blast_jobs.*`、
  `blast_databases.file_path`、`seed_inventory.*`、`seed_requests.*`、新建 `content_versions`。
- 验证：带历史数据回填 → 降级精确移除 → 再升级；离线升降级契约测试 2 个。

## 质量门禁（最近一次全绿）

| 门禁 | 结果 |
| --- | --- |
| 逐包 `lint / typecheck / test` | 36/36 顺序执行通过（12 包） |
| 前端单测 | web 106 · admin 37 · api-client 120 · shared 49 · query-keys 10 · i18n-core 7 · genome-view-model 13 · ui-vue 4 · charts 2 |
| 后端 | API **1608 passed** · worker **357 passed / 1 skipped** · 架构守卫通过 |
| 契约烟测 | 232 + 10（含 locale parity、visible-i18n、app-shell self-test） |
| 公共站 E2E（本地离线子路径） | 29 passed / 2 skipped（后端依赖） |
| 管理端产物 E2E | 3/3 |
| 部署态浏览器探针 | 三站点 core 全通过；控制台仅剩 meta `frame-ancestors` 提示 + 无发布数据的预期 503 |
| 仓库 runtime 验收 | `acceptance.sh --profile runtime` PASS（迁移 + 真实 uvicorn + health + search） |
| 产物检查 | 双站构建、隔离扫描、static smoke ×3、favicon、可见文案 6/1、locale 1431=1431 |

## 功能状态摘要

- **公共站** 35 条路由全部实现（`apps/web/src/router/routes.ts` 的 35 个 `PortalRouteDefinition`）；
  首页数据库入口、搜索、实体详情、工具、新闻、登录均可用。
- **管理端** 19 条功能路由（`apps/admin/src/router/index.ts`）：登录、dashboard、发布、导入（列表/新建/详情）、
  内容页、旧内容迁移、表格模板、文献、新闻、媒体、审计、能力、实例、设置、品牌、分析设置已实现；
  Page Builder/Widgets/Layout（ADR-0009）为**有意退役**，`/resource-catalog` 落到明确“未恢复”页，
  其余旧深链已重定向。
- **i18n**：字典 en/zh 各 1431 key 完全对等；可见文案预算 6 串 / 1 文件（数据值白名单）。
- **assembly**：URL/缓存/请求身份统一稳定 `id`，未知/歧义显式报错；后端 label 规范化**计划中**。
- **品牌**：运行时写入页眉/标题/favicon 已通（写入→公共读取→回滚实测）；构建期静态写入**计划中**。
- **多实例**：本地优先管理闭环完成；远端管理通道**未启动**。

## 已知缺口（均标注计划中）

1. 管理端遗留项：`/resource-catalog`（“未恢复”页）；设置历史回滚 UI。Page Builder/Widgets/Layout 为
   ADR-0009 有意退役，不属于待恢复缺口。
2. 后端 `assembly_id` 入参与 ClickHouse `assembly_key` 规范化。
3. 构建期品牌写入静态 HTML/manifest。
4. 部署态在线 smoke 与 Service Worker 升级测试（需部署/网络）。
5. Redis / ClickHouse / MinIO 未部署（本机环境）；远端管理、服务间凭据、双实例测试未启动。

## 环境约束（沙箱）

- 无 Docker → 无 Redis/ClickHouse/MinIO；testcontainers 不可用，使用 Mamba PostgreSQL 55432。
- Node 24 需 `PATH=/usr/local/bin:$PATH`；构建需 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`。
- 本沙箱 cgroup pid 计费异常导致 `turbo run` 的 spawn 偶发 EAGAIN；逐包顺序执行可完整验证。
- `8000` 已被本机其他服务占用，本仓库默认 API 端口为 **8010**。

## 复现

```bash
# 质量门禁（逐包；沙箱下比 turbo 更稳）
for p in @soymutdb/api-client @soymutdb/charts @soymutdb/genome-data @soymutdb/genome-view \
         @soymutdb/genome-view-model @soymutdb/i18n-core \
         @soymutdb/query-keys @soymutdb/shared @soymutdb/ui-vue \
         @soymutdb/web @soymutdb/admin @soymutdb/jbrowse; do
  pnpm --filter "$p" run lint && pnpm --filter "$p" run typecheck && pnpm --filter "$p" run test
done

# 后端（真实 PostgreSQL）
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  bash scripts/verify-backend-tests.sh

# 运行时验收
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_scratch42' \
  bash scripts/acceptance.sh --profile runtime

# 本机部署启停见 docs/wiki/deployment-and-ops.md「无 Docker 本机部署」
```
