# OPT2 可优化清单（2026-09-26 第二轮）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> 输入来源（两处**已验证为"未完成/未验证"**的残留，不是新造需求）：
> 1. `docs/dev/ablation/2026-09-26/OPTIMIZATION-REPORT.md` §4 未验证项 + §6 建议下一步；
> 2. `docs/dev/vue-parity/README.md` §5 仍未完成（Vue↔React 对等战役的残留）。
>
> 协调者复核定性（2026-09-26 23:5x，HEAD `053666680`，工作树 121 处未提交）：
> - ✅ 已修（上一轮）：`apps/web/src/ablation/p1-04` 的 vue-tsc 报错（现 `web typecheck` 0 错误）。
> - ❌ **不在本轮**（已核实为**非对等缺口**或环境不可达，见 §3）：`/search/suggest`（React 基线也零消费者，`git grep -in suggest` = 0）、repo-wide ruff 404 条、真 Redis（无 `redis-server` 二进制）。

## 0. 并发前提（所有子代理必须遵守）

- 本工作区**曾有并发外部会话**（HEAD 从 `8e78116fd` 推到 `053666680`）。规则：不 `checkout/stash/reset` 任何他人文件；改前先 `read`；只动自己负责的文件；**不提交**。
- pnpm 前 `source .validation/ablation/artifact/pnpmenv.sh`（沙箱 `$HOME` 只读）。
- PostgreSQL 16 常驻 `127.0.0.1:55432`（trust），每个代理用独立库 `abl2_<domain>`。
- 仅协调者可改 `packages/i18n-core/**`：代理用 `t("<key>", { defaultValue: "…" })`，并在报告里给出 key + zh/en 文案。

## 1. 清单

| ID | 来源 | 级别 | 内容 | 负责 | 关键文件 |
| --- | --- | --- | --- | --- | --- |
| OPT2-01 | 报告 §4.1 | P1 | 联邦搜索 `format=html` 分支改走**真实 HTTP 层**（httpx ASGITransport + 真实 PostgreSQL），不再 patch 内部依赖 | A | `apps/api/tests/test_opt2_*.py` |
| OPT2-02 | 报告 §4.2 | P1 | release 作用域"best-effort"**证实或修复**：无已发布 release 时，不同 release 参数不得共用同一缓存条目/同一响应 | A | `apps/api/app/search/cache.py`、`apps/api/app/api/v1/search.py`、测试 |
| OPT2-03 | 报告 §4.6 | P2 | 清掉本轮触及文件的 ruff（`app/api/v1/search.py` 的 `I001:15`/`E501:34`） | A | `apps/api/app/api/v1/search.py` |
| OPT2-04 | 报告 §4.4 | P1 | internal 站 E2E 用**真实输入**触发检索（antdv `Input` 需 `pressSequentially`/派发 `input` 事件），删掉 `?q=` 深链绕行 | B | `e2e/tests/internal-site.spec.ts` |
| OPT2-05 | 报告 §4.5 | P1 | verifier **单条命令**完成 build+verify（不靠手工 `PREBUILT=1`），或给出等价的实测证据 | B | `scripts/verify-site-variant-artifacts.sh`、`e2e/` |
| OPT2-06 | 报告 §6.3 | P1 | 把 `apps/web/src/ablation/*` 5 个一次性草稿提升为常规回归套件（新目录 + 明确命名 + 被默认 `vitest run` 覆盖） | C | `apps/web/src/ablation/**` → 新目录 |
| OPT2-07 | vue-parity §5 | P1 | 门户**注册 Service Worker**（仅生产、尊重 base 子路径 scope、CSP 兼容、`/api/*` 永不拦截） | D | `apps/web/src/main.ts`、新 `lib/service-worker.ts` |
| OPT2-08 | vue-parity §5 / 审计 GAP-08 | P1 | **研究者门禁**（React `ResearcherGate` 包住 4 个 analyses 路由；Vue 缺失） | E | `packages/api-client/src/auth.ts`、新 `lib/current-user.ts`、新 `ResearcherGate.vue`、`views/Analyses*.vue` |

## 2. 冻结契约（跨代理，不得各自发明）

**OPT2-08（E 产出）**
```ts
// packages/api-client/src/auth.ts —— GET /auth/me（已存在，response_model=UserResponse）
export function getCurrentUser(): Promise<CurrentUser>;   // 类型取自 generated/openapi.d.ts
// apps/web/src/lib/current-user.ts
export function useCurrentUser(): { user, isResearcher, isLoading };  // vue-query；401 → 匿名态，不报错
// apps/web/src/components/ResearcherGate.vue
// 默认插槽；isLoading → 「正在校验权限…」；非研究者 → 需要研究权限空态 + 登录 / 返回首页按钮
```
门禁**只做 UX**：服务端 `require_role(RESEARCHER)` 才是授权边界（不得声称前端门禁等于鉴权）。

**OPT2-07（D 产出）**
```ts
// apps/web/src/lib/service-worker.ts
export function registerServiceWorker(): void;  // 仅 import.meta.env.PROD；scope 用 BASE_URL；失败只 warn
```

## 3. 明确不在本轮（避免无意义改动）

| 项 | 不做的理由（已核实） |
| --- | --- |
| `/search/suggest` 消费 | React 基线 `git grep -in suggest` = **0**，属既有未接线 API，**不是**迁移对等缺口 |
| repo-wide ruff（404 条，UP045×143 / E501×89 / UP037×59…） | ruff **不在任何 CI 门禁**里（`scripts/verify-backend-tests.sh` 无 ruff；Makefile 指向不存在的 `apps/api/src`）；285 条自动修复属无关大重构 |
| 真实 Redis 验证 | 本机无 `redis-server`/`valkey-server` 二进制，环境不可达；保留为未验证项 |
| 管理端后端聚合端点 / live 部署态 | 需后端或部署目标，前端无法闭合 |

## 4. 每条 DoD

1. 先证明「改前失败/缺口存在」，再证明「改后通过」（命令 + 退出码 + 输出片段）。
2. 新增或收紧回归测试，禁止 `it.skip` / 删除断言。
3. 跑本包窄门禁 + 对应锚点。
4. 交付四要素：已完成（带证据）/ 未完成 / 未验证 / 阻塞。
5. `git status --short` 中只出现自己负责的文件。

## 5. 协调者复核基线（改后必须仍绿）

```bash
# A
cd apps/api && .venv/bin/python -m pytest tests/test_opt_federated_cache_key.py tests/test_opt_federated_cache_callsites.py tests/test_search_federation.py -q -p no:cacheprovider
# C
pnpm --filter @soymutdb/web test
# D / E
pnpm --filter @soymutdb/web typecheck && pnpm --filter @soymutdb/web lint
# B
cd e2e && ./node_modules/.bin/playwright test -c playwright-internal.config.ts
```

## 6. 出口

- 5 份小结写入 `docs/dev/opt2/opt2-{a..e}-*.md`，协调者汇总 `docs/dev/opt2/OPT2-REPORT.md`。
- 协调者逐条复跑；未通过则回退该项并记入未完成清单。
