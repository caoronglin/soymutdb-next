# OPT4 第四轮：CMS 内容能力落地 + 一个 P0 回归修复（2026-09-27）

- **方式**：协调者（接口/契约/PageDefinition 移植/P0 修复）+ 1 个子代理（门户 site-content 接线，`nwafu/DeepSeek-V4.1-Flash`）；全部结论由协调者独立复跑。
- **目标**：收口审计最后一项实质缺口（GAP-03/04 CMS 内容），并修掉复跑中发现的一处匿名跳转回归。
- **前提**：HEAD `053666680` + 四轮未提交改动；本轮改动同样**未提交**。

## 1. 交付总表

| ID | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| OPT4-API | `GET /site/content` 增加加法式 `only_overrides` | ✅ | `test_opt4_site_content_overrides.py` **5 passed**（真实 PG + ASGI）；`site/home/openapi` 回归 **32 passed** |
| OPT4-CLIENT | `getSiteContent(variant, { onlyOverrides })` | ✅ | `site.test.ts` 6 passed，整包 **149 passed**；契约重生成后 `check:contract` **EXIT=0 / schema in sync** |
| OPT4-PORTAL | 门户 `useSiteContent()` + HomeView(`hero.*`/`tool.*`) + PortalHeader(`nav.*`)，共 **35 键** | ✅ | 子代理交付；协调者复跑 web **52 files / 272 tests**、typecheck 0、lint 0、构建 exit 0；浏览器四组断言通过 |
| OPT4-CMS | **GAP-03 收口**：PageDefinition `resource_cards` 移植 | ✅ | 真实种子数据端到端：首页渲染 CMS 卡片；桩 404 时回退内置 3 卡带 |
| OPT4-P0 | 修复匿名访问被硬跳 `/login`（OPT3 通知铃铛引入） | ✅ | 修复后匿名仅 1 次 `auth/refresh`，**无 `/auth/me`**，33 路由无异常跳转 |

## 2. GAP-03 的**事实更正**（上一轮我说错了，这里纠正）

上一轮我把 GAP-03 描述为「首页**整页**由 PageDefinition 组件树驱动」。核对 React 源码后，**这个说法不成立**：

```tsx
// d3904c21:apps/web/src/routes/index.tsx
function HomeComponent() {
  const { definition, hasError } = usePageDefinition("/");
  return <AntdHome resourceCards={findResourceCards(definition.root)} ... />;
}
```

- `AntdHome` 只把 `resource_cards` **一个节点**交给渲染器；hero、数据库入口、新闻+轮播、工具卡全是**静态代码**。
- 其余 20 余种节点类型（`columns/tabs/rich_text/data_table/...`）首页从未使用，`RenderNode` 的 `default` 直接 `return null`。

所以 GAP-03 的真实产品效果 = **运营可编辑「资源导览」那一段**。本轮据此只移植了 `resource_cards`：

- `apps/web/src/lib/page-definition.ts`：`usePageDefinition("/")`（`retry:false`，404 不重试）+ 深度优先 `findResourceCards` + `isSafePageHref`（端口自 React 渲染器：仅 `/` 内部路由与 `http(s)/mailto/tel`；拒绝 `javascript:`/`data:`/协议相对/反斜杠）。
- `apps/web/src/components/home/ResourceCardsNode.vue`：`data-testid="resource-cards"`，内链走 `RouterLink`、`http(s)/mailto/tel` 走真实 `<a target=_blank rel=noopener noreferrer>`、不安全或缺失 href 降级为 `<article>`；图片仅在绝对 `http(s)` 时渲染。
  - 有意修正 React 的一处小缺陷：React 把 `mailto:` 也塞给路由 `<Link>`（无法解析）；Vue 按语义走真实锚点。
- `HomeView.vue`：有节点 → 渲染 CMS 节点；无节点/404 → 保留**内置卡片带**（内置带是产品自有默认内容，不是演示数据，因此回退是诚实的；这点与 React「生产环境无节点则什么都不渲染」不同，已在代码注释里写明取舍）。

**端到端证据**（协调者）：向 dev 库种入一条 `route='/'` 的 published PageDefinition（root 为 `resource_cards`）后，浏览器实测首页渲染「资源导览 + CMS 数据下载 / CMS 使用指南 / CMS 文献」且内置 `<ul>` 消失；桩 404 时内置 3 卡带回归（`数据下载/使用指南/文献`）。

## 3. GAP-04：接口只回"被改过的键"

**为什么必须加这个参数**（实测）：`GET /site/content?variant=external` 原本对**每个注册键都返回英文注册默认值**（131 键）。门户是双语的，若"服务端值胜出"，中文首页的 Hero/工具卡文案会在请求返回后立刻变成英文——React 的 `useSiteContent` 契约注释正是这么写的，属其既有双语隐患，不应照抄。

- 接口（`apps/api/app/api/v1/site.py`）：新增可选 `only_overrides: bool = False`；为真时只返回**有存储行**的键（`content_<variant>.<key>`，含迁移期 legacy 行）；默认行为与响应形状不变。
- 安全边界不变：内站仍需 viewer 鉴权（匿名 401/403），缓存策略内站 `private, no-store` + `Vary: Authorization`、外站 `public`，有专项断言。
- 客户端（`packages/api-client/src/site.ts`）：`getSiteContent(variant, { onlyOverrides })`；内站仍走 `authRequest`，外站 `auth:false`；`generated/openapi.d.ts` 已重生成（`only_overrides?: boolean`），`check:contract` 绿。
- 门户（子代理）：`useSiteContent()` = `get(key, fallback) → 覆盖值 ?? fallback`，失败/401 一律退化为"无覆盖"，查询键带 site variant。

**核心断言**（协调者复跑，浏览器 zh-CN）：桩 `{}` → 首页仍是「探索多物种突变的未知疆域」**而不是英文默认值**，且请求确认为 `?variant=external&only_overrides=true`；切到英文后按 i18n 本地化；桩 `{"hero.title":"运营标题"}` → 中英两种语言下都显示「运营标题」。

## 4. 本轮修掉的 P0 回归：匿名访问被硬跳 `/login`

复跑时发现：**匿名访问任何门户页面都会在 1–2 秒后被重定向到 `/login`**。

- **根因链**：OPT3 的通知铃铛把 `useCurrentUser()` 挂进了共享页眉 → 每个页面都会请求 `GET /auth/me` → 匿名 401 → `authRequest` 触发 refresh → refresh 也 401 → `emitLogoutOnce()` → `main.ts` 的 `onAuthLogout` 硬跳 `/login`。`auth.ts:118-139` 明确写的是"boot 期 restore 不发 logout 事件"，但 `/auth/me` 走的是**带重试与登出语义**的通道。
- **修复**：`useCurrentUser` 的探针改为**会话门控**——`sessionEstablished` 模块级 `ref`，由 `main.ts` 在 `restoreSession()` 成功后才置真，登录成功时由 `LoginView` 置真；匿名访问**完全不发这个请求**（顺带省掉每次页面加载的一次无用请求）。
- **证据**：修复后匿名首页只发 1 次 `auth/refresh`（401），**没有 `/auth/me`**；`location.pathname` 保持 `/`。
- **测试**：`current-user.test.ts` +2 例（"会话建立前绝不探测"、"restoreSession 后才开始探测"），`PortalHeader.test.ts` 补会话前置；相关 3 文件 29 tests 通过。
- **验证盲区修复**：`.validation/vue-parity/audit-routes.mjs` 的等待从 600ms 提到 2500ms（这条回归正是"首屏正常、随后跳走"，短等待会把红报成绿）。加长后 33 路由 `missingShell=0` 且**无异常跳转**。

## 5. 复跑验收矩阵（全部 exit 0）

| 门禁 | 结果 |
| --- | --- |
| API：`test_opt4_site_content_overrides.py` | **5 passed** |
| API：`test_site_home + test_openapi_contract + opt4` | **32 passed** |
| API：`test_site_home + brand/instance + openapi + opt4 + admin_settings` | **87 passed** |
| api-client：`test` | **149 passed**（`site.test.ts` 6，含 3 条新增） |
| api-client：`check:contract` | **schema in sync / PASS** |
| web：`test` | **52 files / 272 tests passed** |
| web：`typecheck` / `lint` | **0 / 0** |
| web：`check_visible_i18n.py` / `test_motion_policy.py` | **OK / OK** |
| web：`build`（含 SSG 27 documents） | **exit 0** |
| admin：`test` / `typecheck` | **98 passed / 0 错误** |
| 33 路由外壳审计（等待 2.5s） | **missingShell 0，无异常跳转** |
| 浏览器：CMS 卡片带（真实种子数据） | 渲染 CMS 三卡，内置带消失 |
| 浏览器：PageDefinition 404 | 回退内置三卡带 |
| 浏览器：`only_overrides` 无覆盖/有覆盖/双语 | 全部通过 |
| 双站制品 verifier（无 PREBUILT） | 见 §5.1 |
| internal E2E | 见 §5.1 |

### 5.1 制品与 E2E

```text
### dual-site verifier
OK: external artifact contains no supplied protected values
[site-variants] portal dual-site artifacts are built and isolated
### internal E2E
3 passed (7.5s)
### sw namespaces
const SW_NAMESPACE = "external";
const SW_NAMESPACE = "internal";
```

（internal E2E 必须在导出 `PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"` 的环境里跑——见 `e2e/README.md` 的 Sandbox 小节。）

## 6. 仍未完成

1. **剩余 `content.*` 键接线 —— 已在 OPT5 完成**（见 `docs/dev/opt5/OPT5-REPORT.md`）。此处原写的"96 个"是**错误数字**：当时的提取正则只匹配小写键，漏算了 47 个 camelCase 键；正确的注册键数是 **131**。OPT5 完成后：**131 注册 / 105 已接 / 25 个 React 从未引用（非缺口） / 1 个已解释差异（`blast.hitGeneId` 需重排 Blast 命中表列集）**。覆盖率脚本可复跑：`.validation/opt5/content-coverage.py`。
2. 管理端后端聚合端点（`/releases/current`、dashboard storage_growth、审计聚合/导出、导入上传/校验、媒体上传、插件运行时）—— 前端无法闭合，页面已显式降级。
3. 真 Redis / 真外网 provider（本机无 `redis-server`）。
4. SW：gh-pages 子路径 scope、跨版本轮换、Firefox/Safari。
5. 匿名深链 `/analyses` 落 `/login`（与 React 一致，门禁空态只对已认证非研究者可见）。
6. 详情页成功态真机渲染、live 部署态（CSS/CSP/SW/子路径）。
7. repo-wide ruff 404 条（不在任何 CI 门禁内）。
8. 五轮改动仍全部未提交。

## 7. 回滚点

| 范围 | 回滚 |
| --- | --- |
| 本轮全部 | `git checkout -- <file>` / 删除新增文件（未提交） |
| 客户端契约 | `.validation/opt2/contract-backup/`（OPT2 备份）；本轮重生成后的差异可 `git checkout -- packages/api-client` |
| CMS 种子数据 | 仅 dev fixture（`soymutdb_performance` 的 `route='/'` 行），删表行即可 |
