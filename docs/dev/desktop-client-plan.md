# SoyMutDB 桌面客户端完整设计方案

### 免安装分发 · 远程数据 · 本地工具箱

> **版本**：v1.0　**日期**：2026-08-29
> **性质**：设计方案（Design Proposal），可直接进入 spike 与实施。
> **上游文档**：
> - `docs/dev/optimization-plan.md`（v1.0 · 正确性与工程卫生）
> - `docs/dev/performance-optimization-plan.md`（v2.0 · 性能与动效）
> - 本文档（v3.0 · 桌面客户端 / 免安装分发 / 本地工具箱）
> **外部参考模板**：`biotoolbox-merged/architecture-exploration-merged.md`
> （综合生物信息学工具箱架构勘探，Tauri + Rust 内核 + 本地优先 + 插件生态）

---

## 0. 一句话结论

**做一个 Tauri 2 桌面客户端，是同一个壳里的两层能力：数据库侧全部走远程 API（不携带任何数据），工具侧全部在本地执行（用户数据不出本机）。**

这两层不是妥协，而是各自最优：

- **数据库侧走远程** —— SoyMutDB 的价值在于集中维护的多物种突变数据集，本地携带一份既无必要也维护不起。远程访问让客户端永远看到最新 release。
- **工具侧走本地** —— 生信工具处理的是**用户自己的序列**，把它传到服务器上再算，既慢又涉及数据合规（育种数据、未发表序列）。本地执行零延迟、离线可用、数据不出本机。

**这两层的交界处，是本方案最大的差异化机会**：用户在数据库里查到一个基因，一键"发送到工具箱"，序列落入本地，立刻可以酶切、设计引物、扫 motif —— **TBtools 没有数据库，SnapGene 没有突变体库，只有 SoyMutDB 两端都有**。

---

## 1. 形态定义：一个客户端，两层能力

### 1.1 它是什么

| 维度 | 定义 |
|---|---|
| **产品名** | SoyMutDB Desktop |
| **壳** | Tauri 2.x（Rust），系统 WebView，不捆绑 Chromium |
| **UI** | 复用 `apps/web` 全部代码（React + TS + antd v5），零重写 |
| **数据来源** | 远程 SoyMutDB API（默认官方公共站点，可切换私有部署） |
| **本地数据** | 无预装数据集；本地只存用户文件、结果、缓存与凭据 |
| **工具执行** | 本地 Rust 算法核心，经 Tauri command 调用，同进程零拷贝 |
| **admin** | **不打包**。管理后台保持独立 Web 应用（`apps/admin`） |
| **分发** | 免安装（portable）为主，安装版为辅 |

### 1.2 三个使用场景

```
场景 A · 联网检索（最常见）
  打开客户端 → 搜基因 / 查突变体 / 看变异 → JBrowse 浏览 → 下载
  全部走远程 API。与网页版体验一致，但启动更快、无浏览器扩展干扰、
  下载走原生保存对话框。

场景 B · 本地工具（差异化）
  拖入自己的 FASTA/GenBank，或从数据库"发送到工具箱"
  → 酶切 / 引物 / motif / ORF / 比对 / 富集
  → 全部本地计算，断网可用，数据不出本机
  → 结果导出为 SVG/PNG/CSV/FASTA/GB

场景 C · 混合（最有价值）
  数据库检索到候选基因集 → 批量发送到工具箱
  → 本地批量设计引物 / 批量酶切 / 批量注释
  → 结果表格可反向链接回数据库条目
```

### 1.3 "免安装"的确切含义

| 平台 | 产物 | 用户动作 | 写注册表 | 写用户目录 |
|---|---|---|---|---|
| **Windows** | `SoyMutDB-x64-portable.zip`（约 25 MB） | 解压 → 双击 `SoyMutDB.exe` | 否 | 否（全部落在 `./_data/`） |
| **macOS** | `SoyMutDB.app.zip`（约 22 MB） | 解压 → 拖入 Applications（或就地双击） | 否 | 否（portable 标记时） |
| **Linux** | `soymutdb-x86_64.AppImage`（约 30 MB） | `chmod +x` → 运行 | 否 | 否（portable 标记时） |
| 可选 · Windows | `SoyMutDB-Setup-x64.exe`（NSIS） | 标准安装向导 | 是 | 是 |

**免安装的核心判定**：解压目录自包含，删掉整个目录即彻底卸载，不留残余。
实现方式是 portable 模式检测（见 §7.2）。

### 1.4 与 admin 的关系

`apps/admin` 是管理后台，**不进入桌面客户端**：

- 管理员是少数人，用浏览器访问部署好的 admin 站点即可，没有桌面端需求；
- admin 包含数据导入、发布、用户管理等高风险操作，打包进客户端会扩大攻击面；
- 体积与构建复杂度都能省下来。

桌面客户端内**不隐藏 admin 路由**——因为根本不包含它。`apps/web` 中不存在 admin 路由，天然隔离。

### 1.5 与现有 Web 版的关系

同一套 `apps/web` 源码，通过 **构建模式** 区分，不做分支：

```ts
// apps/web/src/lib/deployment.ts —— 扩展现有枚举
export type DeploymentMode =
  | "standard" | "demo" | "minimal" | "production"
  | "desktop";   // ← 新增
```

`desktop` 模式的差异点全部收敛在构建配置与少量运行时分支里：

| 关注点 | Web 模式 | Desktop 模式 |
|---|---|---|
| `base` | `/` 或子路径 | `./`（相对，兼容 `tauri://` 协议） |
| API 基址 | 同源 `/api/v1` | 绝对 URL，运行时可覆盖 |
| CSP | 构建时注入 meta | 由 Tauri 注入 header，支持多 origin |
| Service Worker | 注册（离线缓存） | 不注册（本地资源本就离线；且 macOS `tauri://` 下不可用） |
| 下载 | 浏览器下载 | 原生保存对话框 |
| 窗口/托盘 | 无 | 原生菜单、托盘、通知 |

---

## 2. 现状盘点：能复用什么，必须补什么

### 2.1 六项可直接复用的资产（不要重造）

分析仓库后确认，以下基础设施已经存在且质量很好 —— 桌面客户端应当**直接站在它们上面**，而不是另起炉灶：

| # | 资产 | 位置 | 对桌面端的价值 |
|---|---|---|---|
| 1 | **契约链路** | `packages/api-client/scripts/generate-api-client.sh` + `check-contract.sh` | OpenAPI → `openapi-typescript` → `src/generated/openapi.d.ts`，CI 强制同步。**已有**，远程层类型安全开箱即用 |
| 2 | **服务层无环** | `apps/api/app/services/`（35 文件 / 10,025 行） | 全部跨服务依赖只有 3 处（`outbox_service`、`presign` ×2），无循环。后端不需要为桌面端重构 |
| 3 | **能力端点** | `GET /api/v1/capabilities`（`apps/api/app/api/v1/capabilities.py`） | 已返回 features + plugins + databases。桌面端据此动态裁剪 UI，无需硬编码 |
| 4 | **特性开关** | `apps/api/app/core/features.py` | 原子化、可审计、带 disable 语义。桌面端可据此隐藏不可用功能 |
| 5 | **部署形态抽象** | `apps/web/src/lib/deployment.ts` | 已有 `DeploymentMode` 枚举、`DeploymentOrigins`、`buildCsp`。加一个 `desktop` 分支即可 |
| 6 | **静态化管线** | `apps/web/package.json` 的 `build` 串联 SSG / gzip / SW / release-manifest | 构建产物已高度优化，直接喂给 Tauri |

**特别说明第 1 条**：参考模板建议用 `ts-rs` 从 Rust 生成 TS 类型。SoyMutDB **远程层已经有更成熟的等价物**（OpenAPI + CI 强制同步），因此**不在远程层引入 ts-rs**。`ts-rs` 只用于**本地 IPC 层**（§5.5），两条契约链路各司其职，互不干扰。

### 2.2 七个必须解决的阻塞点

| # | 阻塞点 | 现状证据 | 后果 | 解法 |
|---|---|---|---|---|
| **B1** | **跨站 Cookie 认证** | `config.py:168` `refresh_cookie_samesite = "lax"` | Tauri origin 对远程 API 是跨站 → Lax cookie 不发送 → 每次启动都掉登录 | §4 |
| **B2** | **API 基址默认同源** | `client.ts:41` `apiBaseUrl = VITE_API_BASE_URL ?? "/api/v1"` | 在 `tauri://` 下解析成 `tauri://localhost/api/v1`，必然 404 | §3.5 |
| **B3** | **vite base 为绝对路径** | `vite.config.ts:86` `normalizeBasePath(VITE_BASE_URL \|\| "/")` | `tauri://` 协议下绝对路径资源加载失败 | §3.3 |
| **B4** | **CSP 构建时硬编码** | `deployment.ts` `buildCsp` → `connect-src 'self' {apiOrigin}` | 运行时切换服务器 → 被 CSP 阻断 | §3.6 |
| **B5** | **CORS/CSRF 白名单** | `config.py:193` `cors_origins`（生产必填）；`csrf.py` 强制 Origin 校验 | Tauri origin 不在白名单 → 认证与状态变更请求全被拒 | §4.3 |
| **B6** | **包体主要来自字体** | 三档 HarmonyOS Sans SC 合计 **12.7 MB** | 免安装包从 ~25MB 膨胀到 ~38MB | §7.4（复用 v2.0 的 P0-2） |
| **B7** | **无本地工具执行路径** | 所有计算都在服务端 worker | 工具侧无法本地化 | §5 |

**B1 是唯一的硬阻塞** —— 其余都是配置与工程问题。B1 不解决，客户端每次启动都要重新登录，产品不成立。

---

## 3. 总体架构

### 3.1 分层

```
┌────────────────────────────────────────────────────────────────────────┐
│ UI 层  React 19 + TS + antd v5（复用 apps/web 全部代码）                 │
│   检索 · 浏览 · 详情 · JBrowse · 工具箱面板 · 结果渲染器 · 导出           │
│   ├─ 远程数据源：@soymutdb/api-client（OpenAPI 生成类型）                │
│   └─ 本地数据源：@soymutdb/ipc-types（ts-rs 生成类型）                   │
├───────────────────────────────┬────────────────────────────────────────┤
│ 远程通道  HTTPS → 服务器        │ 本地通道  Tauri IPC（同进程，零拷贝）    │
│   基因/突变体/变异/分析任务      │   工具注册表 · 文件桥 · job 调度 · 凭据  │
│   JWT + CSRF（HttpOnly cookie）│   #[tauri::command] 强类型              │
├───────────────────────────────┴────────────────────────────────────────┤
│ 本地算法核心  Rust crates（rayon 并行）                                  │
│   soymut-parse（noodles）· soymut-algo（enzyme/primer/motif/align/orf） │
│   soymut-viz-model（绘图数据建模，与渲染解耦）                            │
├────────────────────────────────────────────────────────────────────────┤
│ 本地存储  用户文件（scoped fs）· 结果 · 最近记录 · 凭据（OS keychain）    │
└────────────────────────────────────────────────────────────────────────┘
```

**纪律**（沿用参考模板的分层原则，并结合本项目实际调整）：

| 层 | 职责 | 不做什么 |
|---|---|---|
| UI 层 | 渲染、参数收集、结果可视化、导出 | 不做重计算、不直接读大文件 |
| 远程通道 | 数据库读写契约、任务生命周期 | 不含业务算法 |
| 本地通道 | IPC 契约、工具调度、文件作用域、凭据 | 不接触 DOM |
| 算法核心 | 全部 CPU/内存密集的序列算法与统计 | 不感知 UI 框架、不直接管窗口 |
| 本地存储 | 用户文件、结果、缓存、凭据 | 与 UI 解耦 |

两条硬约束：

1. **UI 线程不做任何 >50ms 的计算**。工具任务一律 job 化，进度经 Tauri event 推送。
2. **大文件不进 IPC**。GB 级 FASTQ 走 Rust 流式解析，UI 只拿摘要与分页结果，或写临时文件后交句柄。

### 3.2 目录结构与 workspace 接入

新增一个 Tauri 应用与一个 Rust crate 工作区，**不改动现有任何 app**：

```
apps/desktop/                          # 新增 · Tauri 应用
├── package.json                       # 构建编排：先 build web，再 tauri build
├── src-tauri/
│   ├── Cargo.toml
│   ├── tauri.conf.json                # 窗口/打包/更新/安全配置
│   ├── capabilities/default.json      # Tauri 2 权限清单（最小权限）
│   ├── icons/
│   └── src/
│       ├── main.rs
│       ├── lib.rs
│       ├── server_config.rs           # 服务器地址：读取/切换/校验
│       ├── portable.rs                # portable 模式检测与数据目录解析
│       ├── job.rs                     # 本地 job 调度、进度、取消
│       ├── auth_broker.rs             # (V1.1) 凭据托管
│       └── download.rs                # 原生下载与保存对话框
└── src/                               # 极薄：仅桌面专属的引导与设置页

crates/                                # 新增 · Rust 算法核心
├── soymut-core/                       # 公共类型：SeqRecord IR、错误、结果类型
├── soymut-parse/                      # noodles 封装：FASTA/FASTQ/GBK/GFF/EMBL
├── soymut-algo/                       # 纯算法：enzyme / primer / motif / align / orf / stats
└── soymut-viz-model/                  # 绘图数据建模（序列图/凝胶/热图/树）

packages/ipc-types/                    # 新增 · ts-rs 生成的 IPC 类型（双前端可共享）
```

`pnpm-workspace.yaml` 追加 `apps/desktop` 与 `packages/ipc-types`；
根 `Cargo.toml` 建 workspace，成员为 `crates/*` 与 `apps/desktop/src-tauri`。

`apps/web` **保持原样**，仅新增一个构建脚本条目（见 §3.3）。

### 3.3 构建管线

```jsonc
// apps/web/package.json —— 追加一个 script，不改动现有 build
{
  "scripts": {
    "build": "...（保持不变）",
    "build:desktop": "SOYMUTDB_DESKTOP=1 tsx scripts/build-desktop.ts"
  }
}
```

`scripts/build-desktop.ts` 做四件事：

```ts
/**
 * Desktop build — 产出可直接喂给 Tauri 的静态资源目录。
 *
 * 与标准 build 的差异（全部为 desktop 模式特有）：
 *   1. VITE_BASE_URL=./            相对路径，兼容 tauri:// 与 http://tauri.localhost
 *   2. VITE_DEPLOYMENT_MODE=desktop
 *   3. VITE_API_BASE_URL=<公共 API>  构建期默认值，运行时可被覆盖（见 §3.5）
 *   4. 跳过 sw.js 生成 —— macOS 的 tauri:// 协议下 Service Worker 不注册，
 *      且本地资源本就离线，SW 只会带来缓存失效的困扰
 */
const env = {
  ...process.env,
  SOYMUTDB_DESKTOP: "1",
  VITE_BASE_URL: "./",
  VITE_DEPLOYMENT_MODE: "desktop",
  VITE_API_BASE_URL: process.env.SOYMUTDB_PUBLIC_API ?? "https://api.soymutdb.org/api/v1",
  SOYMUTDB_SKIP_SW: "1",
  SOYMUTDB_DIST_DIR: "dist-desktop",
};
```

桌面打包：

```bash
# 完整构建（Makefile 追加）
make build-desktop
#   = pnpm --filter @soymutdb/web build:desktop
#   + pnpm --filter @soymutdb/ipc-types generate   （ts-rs 导出 TS 类型）
#   + pnpm --filter @soymutdb/desktop build        （tauri build）

# 分发产物
make dist-desktop
#   → dist-desktop/
#       SoyMutDB_1.0.0_x64-portable.zip      (Windows)
#       SoyMutDB.app.zip                      (macOS)
#       soymutdb_1.0.0_amd64.AppImage         (Linux)
#       SoyMutDB_1.0.0_x64-setup.exe          (Windows NSIS，可选)
#       latest.json                           (Tauri updater 清单)
#       SHA256SUMS
```

### 3.4 部署模式：新增 `desktop`

```ts
// apps/web/src/lib/deployment.ts —— 扩展
export type DeploymentMode =
  | "standard" | "demo" | "minimal" | "production" | "desktop";

export function resolveDeploymentMode(value: string | undefined): DeploymentMode {
  switch (value?.trim().toLowerCase()) {
    case "desktop":    return "desktop";
    case "demo":       return "demo";
    case "minimal":    return "minimal";
    case "production": return "production";
    default:           return "standard";
  }
}

/** Desktop builds must NOT register the service worker (see §3.3 note 4). */
export function isDesktopMode(value: string | undefined): boolean {
  return resolveDeploymentMode(value) === "desktop";
}
```

注册点收敛到一处：

```ts
// apps/web/src/main.tsx —— 唯一的运行时分支
if (!isDesktopMode(import.meta.env.VITE_DEPLOYMENT_MODE)) {
  registerServiceWorker();
}
```

### 3.5 运行时配置：服务器地址

**问题**：`apiBaseUrl` 现在是模块级常量，构建期固定。但桌面客户端必须允许用户切换到**私有部署**的 SoyMutDB（高校/育种单位自建非常常见）。

**解法**：给 api-client 加一个运行时覆盖钩子，默认行为完全不变。

```ts
// packages/api-client/src/client.ts —— 替换常量为可覆盖解析
let runtimeBaseOverride: string | undefined;

/** Desktop clients call this after reading the configured server. */
export function setApiBaseUrl(value: string | undefined): void {
  runtimeBaseOverride = value?.trim() || undefined;
}

const buildTimeBase =
  (import.meta.env?.VITE_API_BASE_URL as string | undefined)?.trim() || "/api/v1";

// 惰性求值：每次请求时解析，使运行时覆盖生效
export function resolveApiBaseUrl(): string {
  return runtimeBaseOverride ?? buildTimeBase;
}

// 既有导出保持兼容（Web 端行为完全不变）
export const apiBaseUrl = buildTimeBase;
```

`request()` 内部把 `apiBaseUrl` 换成 `resolveApiBaseUrl()`。

Tauri 侧在启动时把配置注入前端：

```rust
// apps/desktop/src-tauri/src/server_config.rs
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ServerConfig {
    /// 绝对 origin，例如 "https://api.soymutdb.org"
    pub api_origin: String,
    pub jbrowse_origin: Option<String>,
}

impl ServerConfig {
    pub const DEFAULT_API_ORIGIN: &'static str = "https://api.soymutdb.org";
    pub const DEFAULT_JBROWSE_ORIGIN: &'static str = "https://jbrowse.soymutdb.org";

    /// 校验：必须是 https（localhost / 127.0.0.1 例外），拒绝占位域名。
    pub fn validate(&self) -> Result<(), String> {
        let url = url::Url::parse(&self.api_origin)
            .map_err(|_| "服务器地址不是合法 URL".to_string())?;
        let is_loopback = matches!(url.host_str(), Some("localhost") | Some("127.0.0.1"));
        if url.scheme() != "https" && !is_loopback {
            return Err("服务器地址必须使用 https".into());
        }
        if url.host_str().is_some_and(|h| h.ends_with("example.com")) {
            return Err("服务器地址仍是占位域名".into());
        }
        Ok(())
    }
}

#[tauri::command]
pub fn get_server_config(state: tauri::State<AppState>) -> ServerConfig {
    state.server_config.lock().unwrap().clone()
}

#[tauri::command]
pub async fn set_server_config(
    state: tauri::State<'_, AppState>,
    config: ServerConfig,
) -> Result<(), String> {
    config.validate()?;
    // 切换服务器必须清空本地会话：旧站的 cookie/token 对新站无意义
    crate::auth_broker::clear_session(&state)?;
    *state.server_config.lock().unwrap() = config;
    state.persist()?;
    Ok(())
}
```

前端引导（在路由加载前完成，避免先打到默认站再跳）：

```ts
// apps/desktop/src/bootstrap.ts
import { invoke } from "@tauri-apps/api/core";
import { setApiBaseUrl } from "@soymutdb/api-client";

export async function bootstrapDesktop(): Promise<void> {
  const cfg = await invoke<{ api_origin: string }>("get_server_config");
  setApiBaseUrl(`${cfg.api_origin}/api/v1`);
}
```

**首次启动引导**：如果本地没有任何服务器配置（全新安装），先展示一个原生选择页 ——
「连接公共站点 soymutdb.org」/「连接私有部署（输入地址）」。选完再进入 WebView 主界面。

### 3.6 CSP 处理（关键坑）

**问题**：`buildCsp()` 在构建时把 `connect-src 'self' {apiOrigin}` 写进 `index.html` 的 `<meta>`。
桌面端运行时把 API 切到另一个 origin，`connect-src` 会**直接阻断请求**，且这类失败在 WebView 里报得非常隐晦。

**解法**：desktop 模式**不生成 meta CSP**，改由 Tauri 注入 header，并放宽到允许多 origin。

```ts
// apps/web/src/lib/deployment.ts
export function buildCsp(origins: DeploymentOrigins, analytics = false): string {
  // desktop 模式由 Tauri 的 app.security.csp 接管，此处返回空串，
  // 由构建脚本跳过 meta 注入
  if (isDesktopMode(import.meta.env.VITE_DEPLOYMENT_MODE)) return "";
  return [/* 现有实现保持不变 */].join("; ");
}
```

```jsonc
// apps/desktop/src-tauri/tauri.conf.json
{
  "app": {
    "security": {
      "csp": "default-src 'self'; \
              script-src 'self' 'unsafe-inline'; \
              style-src 'self' 'unsafe-inline'; \
              img-src 'self' data: https: asset: http://asset.localhost; \
              font-src 'self' data:; \
              connect-src 'self' https: http://127.0.0.1:* ipc: http://ipc.localhost; \
              frame-src 'self' https:; \
              object-src 'none'; \
              base-uri 'self'"
    }
  }
}
```

`connect-src https:` 放行全部 HTTPS 目标 —— 这是运行时切换服务器的必要条件。
代价是放宽了对**外发目标**的限制， mitigation 依赖：

- 远端 API 地址由用户显式选择并校验（§3.5）；
- 本地 job 与凭据不出本机；
- 工具层不发起任何网络请求（纯本地计算，可在 Rust 侧静态保证）。

### 3.7 Service Worker：为什么桌面端不注册

| 平台 | Tauri 2 WebView origin | SW 可用性 |
|---|---|---|
| Windows | `http://tauri.localhost` | 可用 |
| Linux | `http://tauri.localhost` | 可用 |
| macOS | `tauri://localhost` | **不可用**（WKWebView 不为自定义协议注册 SW） |

既然 macOS 上不可用，就不该让三端行为分叉。而且桌面端资源本就在本地，SW 的唯一价值（离线缓存静态资源）已经由"本地打包"天然满足。跳过 SW 还能避免"更新客户端后旧 SW 缓存静态资源导致白屏"这一经典事故。

---

## 4. 认证方案（最大阻塞点 B1）

### 4.1 根因

后端把 refresh token 放在 **HttpOnly cookie** 里：

```python
# apps/api/app/api/v1/auth.py:66-73
response.set_cookie(
    key=settings.refresh_cookie_name,        # soymutdb_refresh
    httponly=True,
    secure=settings.refresh_cookie_effective,  # https 下自动 True
    samesite=_samesite(),                     # config.py:168 默认 "lax"
    path=settings.refresh_cookie_path,        # /api/v1/auth
)
```

Session 恢复完全依赖这个 cookie：

```
packages/api-client/src/auth.ts
  "boot-time session restore from the HttpOnly refresh cookie"
  → refreshInFlight / performRefresh() → GET <base>/auth/refresh
```

**`SameSite=Lax` 的语义**：cookie 只在**同站**或**顶级导航**的跨站请求中发送。

桌面客户端的情况：

```
WebView origin        http://tauri.localhost   （Win/Linux）
                      tauri://localhost        （macOS）
API origin            https://api.soymutdb.org
关系                  跨站（cross-site）
fetch 类型             XHR/fetch，非顶级导航
→ SameSite=Lax 的 refresh cookie 不发送  ❌
```

**后果链**：
1. 启动 → `performRefresh()` → cookie 未携带 → 401；
2. 401 → 触发 logout 事件 → 用户看到"请登录"；
3. 即使手动登录，关掉客户端再开，又要登录一次。

**这个问题不影响网页版**（网页版与 API 同源或同站），是桌面端独有的。

### 4.2 三方案对比

| | **方案 A · 桌面令牌托管** | **方案 B · SameSite=None + 白名单**（推荐 MVP） | **方案 C · 本地反向代理** |
|---|---|---|---|
| **做法** | Rust 侧接管登录/刷新，token 存 OS keychain，前端经 command 取 token 用 Bearer | 后端 cookie 改 `SameSite=None; Secure`，CORS/CSRF 白名单加 Tauri origin | Tauri 内起本地 HTTP 服务，前端访问同源 `127.0.0.1`，代理转发并注入 cookie |
| **前端改动** | 中：api-client 加 `TokenProvider` 抽象 | **零** | 零 |
| **后端改动** | 中：新增 token 传输通道 | **仅配置**（`SOYMUTDB_REFRESH_COOKIE_SAMESITE=none`） | 零 |
| **安全性** | 高：凭据在 keychain，不进 WebView | 中：cookie 在所有跨站上下文发送，依赖 Origin 校验兜底 | 高：cookie 不进 WebView |
| **跨端一致性** | 好 | **需验证 macOS `tauri://`** | 好 |
| **性能** | 好 | 好 | 差：多一跳，大文件与流式响应要特殊处理 |
| **复杂度** | 中 | **低** | 高：端口管理、流式转发、本地服务鉴权 |
| **落地节奏** | V1.1 | **MVP（先做 spike 验证）** | 备选 |

**推荐路径**：

```
M0 spike（2 天）→ 验证方案 B 在 macOS 的 tauri:// origin 下能否走通
  ├─ 通过 → MVP 用 B，零前端改动，最快交付
  └─ 不通过 → MVP 用 A（不引入 C，C 的代理复杂度不值得）
V1.1 → 升级到 A（keychain 托管，安全性与原生体验更好）
```

### 4.3 MVP：方案 B 落地

#### 4.3.1 后端配置（三处，全部是配置，不改代码）

```bash
# deploy/.env.example —— 追加
# Tauri 桌面客户端的 WebView origin。
# Win/Linux 为 http://tauri.localhost；macOS 为 tauri://localhost。
# 逗号分隔，加入 CORS 与 CSRF 双白名单。
SOYMUTDB_CORS_ORIGINS=https://soymutdb.org,http://tauri.localhost,tauri://localhost

# 桌面客户端是跨站上下文，refresh cookie 必须 SameSite=None 才能送出。
# None 强制要求 Secure，因此 API 必须走 https（localhost 开发除外）。
SOYMUTDB_REFRESH_COOKIE_SAMESITE=none
SOYMUTDB_REFRESH_COOKIE_SECURE=true
```

> `refresh_cookie_samesite` 与 `refresh_cookie_secure` 已经是既有配置项
> （`config.py:168` / `config.py:171`），**无需新增代码**，只需在部署时设置。

#### 4.3.2 CORS：确认非 `*` origin 允许凭据

```python
# apps/api/app/main.py:255-266 —— 现状已正确，无需改动
CORSMiddleware,
allow_origins=settings.cors_origins,
allow_credentials=True,          # ← 必须
allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
allow_headers=[..., "X-Requested-With", ...],   # CSRF 头已在列
```

`config.py:342` 已有"含 `*` 且开启凭据时报错"的校验，白名单机制是安全的。

#### 4.3.3 CSRF：白名单同步

```python
# apps/api/app/core/csrf.py:23-30 —— 现状
def _is_trusted_origin(origin: str, request: Request, settings: Settings) -> bool:
    own_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin == own_origin:
        return True
    if origin in settings.cors_origins:      # ← 复用同一份白名单，自动生效
        return True
    return False
```

**好消息**：CSRF 白名单直接复用 `cors_origins`，加一处.env 即两处生效。

#### 4.3.4 前端：携带凭据

确认 api-client 的 fetch 使用 `credentials: "include"`。

```ts
// packages/api-client/src/client.ts —— 检查并确保
const res = await fetch(url, {
  ...init,
  credentials: "include",      // ← 跨域带上 refresh cookie 的必要条件
});
```

> 若当前是 `same-origin`，需改为 `include`。Web 端同源场景下 `include`
> 与 `same-origin` 行为一致，**无回归风险**。

#### 4.3.5 安全缓解（SameSite=None 的代价）

`SameSite=None` 意味着 cookie 会在**所有跨站上下文**发送。缓解依赖三层，缺一不可：

1. **严格的 Origin 白名单**：`cors_origins` 只允许自己的站点与两个 Tauri origin，不含 `*`；
2. **强制的 Origin 校验**：`csrf.py` 对状态变更请求强制要求 `Origin`/`Referer` 且不信任空值（现状已是如此）；
3. **CSRF 双提交校验**：现有 `X-Requested-With` / CSRF token 机制保持不变。

结论：即使 cookie 被跨站携带，攻击者仍无法构造出通过 Origin 校验的写请求。

#### 4.3.6 M0 spike 必验项

| # | 验证点 | 方法 | 通过标准 |
|---|---|---|---|
| S1 | macOS `tauri://localhost` 是否发送 `Origin` 头 | 抓包看 `POST /auth/login` | 请求带 `Origin: tauri://localhost` |
| S2 | Starlette CORS 是否接受该非标准 origin | 看响应是否含 `Access-Control-Allow-Origin: tauri://localhost` | 精确回显，非 `null` |
| S3 | `SameSite=None` cookie 是否被 WebView 存储并回传 | DevTools → Application → Cookies | 存在且后续 refresh 携带 |
| S4 | 冷启动 session 恢复 | 登录后重启客户端 | 无需重新登录 |
| S5 | Windows/Linux `http://tauri.localhost` 同链路 | 同上 | 同上 |

**S2 是最可能失败的一环**：`tauri://` 不是合法 HTTP scheme，Starlette 的 `CORSMiddleware`
做的是字符串比较，理论上能匹配，但 WKWebView 可能根本不发这个头。
若 S1/S2 失败，**立即切换到方案 A**，不要在这里纠缠。

### 4.4 V1.1：方案 A 落地（桌面令牌托管）

#### 4.4.1 思路

把"session 恢复"这件事从 WebView 的 cookie jar 搬到 Tauri 的 Rust 侧：

```
登录    UI 提交凭据 → Rust command → reqwest 调 /auth/login?transport=token
                   → 后端在响应体里返回 { access_token, refresh_token }
                   → Rust 存 refresh_token 到 OS keychain
                   → access_token 返回给前端（仅内存）

请求    UI → api-client → Authorization: Bearer <access_token>

刷新    access_token 过期 → 前端调 Rust command refresh_session
                        → Rust 用 keychain 里的 refresh_token 调 /auth/refresh
                        → 轮换后回写 keychain，返回新 access_token

登出    Rust 调 /auth/logout，清空 keychain
```

**关键优势**：refresh token 从不进入 WebView，XSS 拿不到；不受 SameSite 约束；跨端行为一致。

#### 4.4.2 后端：新增 token 传输通道

```python
# apps/api/app/api/v1/auth.py —— 在现有登录/刷新端点上增加 transport 分支
from fastapi import Query

@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    # 仅桌面客户端使用；后端仍强制校验 Origin
    transport: Literal["cookie", "token"] = Query("cookie"),
) -> TokenResponse:
    result = await AuthService.login(payload, request)
    if transport == "token":
        # 桌面客户端：refresh token 随响应体返回，不落 cookie。
        # Origin 校验已在依赖层完成，此处无需重复。
        return TokenResponse(
            access_token=result.access_token,
            refresh_token=result.refresh_token,   # 新增字段，cookie 模式下为 None
            token_type="bearer",
            expires_in=result.expires_in,
        )
    _store_refresh_cookie(response, result.refresh_token)
    return TokenResponse(
        access_token=result.access_token,
        refresh_token=None,
        token_type="bearer",
        expires_in=result.expires_in,
    )
```

```python
# apps/api/app/schemas/auth.py —— 扩展 TokenResponse
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None   # 新增：仅 transport=token 时非空
```

**安全约束**（三条，必须同时满足）：

1. `transport=token` **仅**在 Origin 命中 Tauri 白名单时可用（复用现有 `validate_request_origin`）；
2. 该模式下**不设置** refresh cookie，避免凭据双份；
3. refresh token 轮换与失效逻辑复用现有实现，不新建一套。

#### 4.4.3 Rust：keychain 托管

```rust
// apps/desktop/src-tauri/src/auth_broker.rs
use keyring::Entry;

const SERVICE: &str = "soymutdb-desktop";
const REFRESH_KEY: &str = "refresh_token";

fn entry() -> Result<Entry, keyring::Error> {
    Entry::new(SERVICE, REFRESH_KEY)
}

#[tauri::command]
pub async fn desktop_login(
    state: tauri::State<'_, AppState>,
    email: String,
    password: String,
) -> Result<LoginResult, String> {
    let origin = state.server_config.lock().unwrap().api_origin.clone();
    let client = reqwest::Client::new();
    let res = client
        .post(format!("{origin}/api/v1/auth/login?transport=token"))
        .header("Origin", desktop_origin())      // 让后端 Origin 校验通过
        .json(&serde_json::json!({ "email": email, "password": password }))
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if !res.status().is_success() {
        return Err(format!("登录失败：HTTP {}", res.status()));
    }
    let body: LoginResponse = res.json().await.map_err(|e| e.to_string())?;

    // refresh token 只进 keychain，绝不返回给 WebView
    entry().map_err(|e| e.to_string())?
        .set_password(&body.refresh_token.ok_or("服务端未返回 refresh token")?)
        .map_err(|e| e.to_string())?;

    Ok(LoginResult { access_token: body.access_token, expires_in: body.expires_in })
}

#[tauri::command]
pub async fn desktop_refresh(state: tauri::State<'_, AppState>) -> Result<String, String> {
    let refresh_token = entry().map_err(|e| e.to_string())?
        .get_password().map_err(|_| "本地没有有效会话".to_string())?;
    // ... 调 /auth/refresh，轮换后 set_password 回写，返回新 access_token
}

pub fn clear_session(state: &AppState) -> Result<(), String> {
    // 允许"不存在"——切换服务器或首次启动时不应报错
    if let Ok(e) = entry() { let _ = e.delete_credential(); }
    Ok(())
}
```

**依赖**：

```toml
# apps/desktop/src-tauri/Cargo.toml
[dependencies]
keyring = { version = "3", features = ["apple-native", "windows-native", "linux-native"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"], default-features = false }
```

三端凭据后端：Windows Credential Manager / macOS Keychain / Linux Secret Service(libsecret)。

#### 4.4.4 前端：TokenProvider 抽象

```ts
// packages/api-client/src/token-provider.ts
export interface TokenProvider {
  /** 返回当前 access token，没有则 null。 */
  getAccessToken(): string | null;
  /** 主动刷新。返回新 token，失败返回 null（调用方负责登出）。 */
  refresh(): Promise<string | null>;
  /** 会话失效时回调（用于统一登出 UI）。 */
  onSessionExpired(cb: () => void): () => void;
}
```

```ts
// 浏览器模式：沿用现有 HttpOnly cookie 实现，行为完全不变
export class CookieTokenProvider implements TokenProvider { /* 现有 auth.ts 逻辑搬入 */ }

// 桌面模式：委托给 Tauri command
export class DesktopTokenProvider implements TokenProvider {
  constructor(private readonly invoke: <T>(cmd: string, args?: unknown) => Promise<T>) {}
  private token: string | null = null;

  getAccessToken() { return this.token; }

  async refresh() {
    try {
      this.token = await this.invoke<string>("desktop_refresh");
      return this.token;
    } catch {
      this.token = null;
      this.expired();
      return null;
    }
  }
}
```

`client.ts` 在请求前调用 `provider.getAccessToken()` 并注入 `Authorization`。
**Web 端默认的 `CookieTokenProvider` 行为与现状逐字节一致**，零回归风险。

### 4.5 决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| MVP 认证方案 | 方案 B | 零前端改动，后端仅配置，最快验证产品假设 |
| 是否引入本地反代（方案 C） | 否 | 大文件下载与流式响应要特殊处理，复杂度不划算 |
| V1.1 是否升级到方案 A | 是 | 凭据不进 WebView 是桌面应用的正确姿势；keyring 三端成熟 |
| 是否放弃 cookie 模式 | 否 | Web 端继续用 cookie（更安全、更成熟），桌面端走独立通道 |

---

## 5. 本地工具箱（核心新增能力）

这是本次相对参考模板**采纳度最高**的部分。参考模板的核心主张 ——
"工具 = 声明式配置（参数 schema + 调用内置算子），UI 自动生成表单" ——
对功能堆叠型项目是极高的杠杆，SoyMutDB 已有 38 个前端路由、50 个后端路由文件，
正需要这种收敛机制。

### 5.1 设计原则

1. **声明式优先**：新增一个工具 = 加一份 descriptor + 一个 Rust 函数，不写新页面；
2. **本地优先**：用户数据不出本机，工具层零网络请求（Rust 侧静态保证）；
3. **结果即资产**：每个结果都能导出、能复现（记录输入哈希 + 参数 + 算法版本）；
4. **与渲染解耦**：Rust 只产出 `viz-model` 数据结构，渲染由 TS 决定；
5. **契约编译期一致**：`ts-rs` 从 Rust 生成 TS 类型到 `@soymutdb/ipc-types`。

### 5.2 工具清单

按 SoyMutDB 的真实场景（大豆突变体研究）筛选，**不照搬 TBtools 的 130+**。
判断标准：是否与"查到基因/突变体之后要做什么"强相关。

#### A 组 · 序列基础（MVP，第一个交付）

| # | 工具 | 依赖 | 输出 |
|---|---|---|---|
| A1 | **格式解析与转换** FASTA/FASTQ/GenBank/GFF/EMBL → 统一 IR，互转 | `noodles` | 摘要（条数/长度/GC/特征数）+ 转换后文件 |
| A2 | **序列基本操作** 反向互补、翻译（6 框）、GC 含量、GC 滑动窗口 | 自研（<200 行） | 序列 + GC 曲线图 |
| A3 | **限制性酶切** REBASE 子集，支持部分酶/错配/甲基化敏感 | 自研 + REBASE 数据 | 片段表 + **凝胶模拟图** + 位点图谱 |
| A4 | **引物设计** SantaLucia 最近邻 Tm + 盐校正 + 二聚体/发夹 | **自研**（见 §5.10） | 候选对表（Tm/GC/长度/clamp/评分）+ JBrowse 深链 |
| A5 | **Motif 扫描** IUPAC 简并 + PWM，允许错配 | 自研 + Aho-Corasick | 位点表 + 序列轨道图 |
| A6 | **ORF 查找** 6 框、起始/终止、最小长度 | 自研 | ORF 表 + 序列轨道图 |

> **A4 是对现状的直接升级**：现有 `apps/web/src/routes/search/primer.tsx`
> 是纯前端启发式（`lib/primer-design.ts`），文件头自己标注
> "No Primer3 backend is involved — this is a simplified heuristic tool"。
> 桌面端用真实热力学替换它，是**正确性的实质提升**，不是重复造轮子。

#### B 组 · 比对与统计（V1.1）

| # | 工具 | 依赖 | 输出 |
|---|---|---|---|
| B1 | 两两比对 Needleman-Wunsch / Smith-Waterman | 自研 + SIMD | 比对视图 + 一致性/相似度 |
| B2 | 多序列比对 包装 MAFFT（BSD） | 外部二进制 | 着色比对视图 |
| B3 | 系统发育 NJ / UPGMA | 自研 | 树 + Newick 导出 |
| B4 | **富集分析**（本地 GO/KEGG 注释包） | 预置数据 | 富集表 + 气泡图/网络图 |
| B5 | k-mer 与序列统计 | 自研 | 分布图 |
| B6 | FASTQ 质控统计（质量分布/长度分布/重复率） | `noodles` | 质控报告图 |

> B4 与服务端 `enrichment_service.py`（586 行，已有 GO/KEGG）形成"两端都有"的格局：
> 服务端版用全量注释库，本地版用精简注释包，UI 完全一致，按数据量自动选择（§6）。

#### C 组 · 可视化（与结果渲染器配套，贯穿 A/B 组）

| # | 图 | 渲染 |
|---|---|---|
| C1 | 序列轨道图（特征/位点/ORF/motif） | 自绘 SVG/Canvas |
| C2 | 凝胶电泳模拟图 | 自绘 SVG |
| C3 | 质粒/序列环形图 | 自绘 SVG |
| C4 | 热图 / 聚类热图 / 火山图 / 曼哈顿图 | **已有 ECharts** |
| C5 | 多序列比对着色视图 | 自绘 Canvas |
| C6 | 进化树 | 自绘 SVG |

#### 明确不做

| 不做 | 理由 |
|---|---|
| 测序峰图 `.ab1/.scf` | 参考模板 R6：ABIF 解析 + 波形渲染是 SnapGene 护城河，自研成本高 |
| 完整 NGS 流水线 | 服务端已有 fastp / scanpy（`routes/analyses/`），不重复 |
| 质粒图谱**设计**（编辑/组装） | SnapGene 域，且 SoyMutDB 场景不需要 |
| 云端协作 / ELN / 账号同步 | 本期非目标 |

### 5.3 工具注册表：schema 驱动

**这是整个工具箱的杠杆点**：一份 descriptor 同时生成表单、任务、结果渲染与导出菜单。

```rust
// crates/soymut-core/src/tool.rs
use ts_rs::TS;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export, export_to = "tool.ts")]
pub struct ToolDescriptor {
    pub id: String,                 // "enzyme.digest"
    pub name: String,               // "限制性酶切"
    pub group: ToolGroup,           // sequence | align | stats | viz
    pub execution: Execution,       // Local | Remote
    pub params: serde_json::Value,  // JSON Schema 子集 → 驱动 antd 表单
    pub inputs: Vec<InputSpec>,
    pub outputs: Vec<OutputSpec>,
    pub cost: CostClass,            // Instant | Seconds | Job
    pub algo_version: String,       // 可复现性：记入结果元数据
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum InputSpec {
    SequenceFile { formats: Vec<String>, multiple: bool },
    DatabaseRef { kind: DatabaseRefKind },   // Gene / MutantLine / Variant
    Text { label: String, multiline: bool },
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum OutputSpec {
    Table { columns: Vec<ColumnSpec> },
    Chart { kind: ChartKind },
    Sequence { format: String },
    File { extension: String, mime: String },
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, TS)]
#[ts(export)]
pub enum CostClass {
    Instant,   // <50ms，同步返回
    Seconds,   // <10s，走 command + 进度
    Job,       // 长任务，job 化，可取消
}
```

参数 schema 用 **JSON Schema 子集**（`type` / `enum` / `minimum` / `maximum` / `default` /
`description` / `x-widget`），前端一个 `SchemaForm` 组件统一渲染：

```tsx
// apps/web/src/components/toolbox/schema-form.tsx
// 把 JSON Schema 子集映射为 antd 表单控件
//   string           → Input / TextArea（multiline）
//   number + range   → Slider 或 InputNumber（x-widget 指定）
//   boolean          → Switch
//   enum             → Select / Radio.Group（x-widget 指定）
//   array of enum    → Select mode="multiple"
export function SchemaForm({ schema, value, onChange }: SchemaFormProps) { /* ... */ }
```

**收益量化**：每新增一个工具，前端工作量从"一个页面（300–700 行）"降到"零"。
参考现有 `tools/enrichment.tsx`、`tools/seqfetch.tsx` 的体量，这是数量级的节省。

### 5.4 Rust crate 划分

```
crates/
├── soymut-core/         SeqRecord IR · 错误类型 · ToolDescriptor · 结果契约
├── soymut-parse/        noodles 封装：FASTA / FASTQ / GenBank / GFF / EMBL
│                        格式嗅探 + 流式读取 + 进度回调
├── soymut-algo/         纯函数、可单测、无 IO：
│                          enzyme（REBASE 子集，Aho-Corasick 多点扫描）
│                          primer（SantaLucia NN + Owczarzy 盐校正 + 二聚体/发夹）
│                          motif（IUPAC + PWM）
│                          align（NW/SW，可选 SIMD）
│                          orf · stats · enrich（超几何 + BH FDR）
└── soymut-viz-model/    绘图数据建模：序列轨道 / 凝胶 / 热图 / 树
                          —— 只产出数据结构，不含任何渲染代码
```

**依赖原则**：

```
soymut-core   ← 被所有 crate 依赖，自身零业务依赖
soymut-parse  ← soymut-core + noodles
soymut-algo   ← soymut-core（纯计算，不依赖 parse，输入是 IR）
soymut-viz-model ← soymut-core
apps/desktop/src-tauri ← 全部 crate + tauri
```

`soymut-algo` **不依赖** `soymut-parse` 是有意为之：算法只认 IR，便于单测与未来 CLI 复用。

**关键依赖版本**（参考模板 §7.2 的建议，结合当前生态）：

```toml
# crates/soymut-parse/Cargo.toml
noodles = { version = "0.99", features = ["fasta", "fastq", "gff", "genbank"] }

# crates/soymut-algo/Cargo.toml
rayon = "1.10"
aho-corasick = "1.1"
statrs = "0.18"          # 超几何分布（富集分析 p 值）

# 根 Cargo.toml
[workspace.dependencies]
ts-rs = "10"
serde = { version = "1", features = ["derive"] }
```

> **是否引入 `rust-bio`（参考模板推荐）**：**建议不引入**。
> 理由：A 组六个工具的核心算法都是几百行量级的自研实现，
> `rust-bio` 带来的是 MSRV 约束（v4 要求 Rust 1.87）与 API 演进风险
> （参考模板自己列为 R8）。等 B 组需要复杂比对/系统发育时再评估，
> 届时以**薄封装适配层**引入，避免算法层被外部 API 绑死。

### 5.5 类型契约：`ts-rs` → `@soymutdb/ipc-types`

参考模板主张"用 `ts-rs` 从 Rust 结构生成 TS 类型，保证前后端编译期一致"。
**在远程层已有 OpenAPI 链路的前提下（§2.1 第 1 条），ts-rs 只用于本地 IPC 层。**

```
crates/*/src/**.rs  ──ts-rs──▶  packages/ipc-types/src/generated/*.ts
                                        ▲
                                        │ 由 Rust 单测触发导出（见下）
apps/web / apps/admin  ──import──────────┘
```

```rust
// crates/soymut-core/tests/export_bindings.rs
#[test]
fn export_ts_bindings() {
    // 每次 cargo test 都重新导出，CI 用 git diff 校验无漂移
    soymut_core::tool::ToolDescriptor::export_all_to("../../packages/ipc-types/src/generated")
        .expect("ts-rs export failed");
}
```

```jsonc
// packages/ipc-types/package.json
{
  "name": "@soymutdb/ipc-types",
  "exports": { ".": { "types": "./src/index.ts", "import": "./src/index.ts" } },
  "scripts": {
    "generate": "cargo test -p soymut-core --test export_bindings",
    "check:contract": "pnpm generate && git diff --exit-code src/generated"
  }
}
```

**与远程层的对照**（两条链路并存，职责清晰）：

| | 远程层 | 本地层 |
|---|---|---|
| 契约源 | FastAPI OpenAPI | Rust `#[derive(TS)]` |
| 生成器 | `openapi-typescript` | `ts-rs` |
| 产物 | `api-client/src/generated/openapi.d.ts` | `ipc-types/src/generated/*.ts` |
| 校验 | `check:contract`（CI 强制） | `check:contract`（CI 强制） |

### 5.6 数据流

```
场景：用户在基因详情页点「发送到工具箱 → 限制性酶切」

[UI]  基因详情 → 点「酶切」
  │   （序列来源二选一：① 数据库引用，经 API 拉取；② 用户本地文件）
  ▼
[Cmd] tool_run { tool_id: "enzyme.digest", inputs, params }
  │
  ├─ 输入是 DatabaseRef → Rust 侧先经 reqwest 从 API 取序列
  │                       （复用已登录的 access token）
  └─ 输入是本地文件     → 经 Tauri scoped fs 读取（权限在 capabilities 声明）
  ▼
[Rust] soymut-parse 解析 → SeqRecord IR
     → soymut-algo::enzyme::digest(&ir, &enzymes, &opts)
     → soymut-viz-model 建凝胶/图谱数据结构
     → 进度经 tauri::Window::emit 推 UI（仅 Seconds/Job 类）
  ▼
[UI]  结果渲染器（按 OutputSpec 选择）
     ├─ Table    → antd Table（虚拟滚动，复用 DataTable）
     ├─ Chart    → SchemaChart（ECharts 或自绘 SVG）
     └─ Sequence → 序列轨道组件
  ▼
[导出] 原生保存对话框 → SVG / PNG / CSV / FASTA / GB
```

**结果元数据**（可复现性，对齐参考模板"输入哈希 + 参数 + 算法版本"）：

```rust
#[derive(Debug, Clone, serde::Serialize, TS)]
#[ts(export)]
pub struct ResultMeta {
    pub tool_id: String,
    pub algo_version: String,        // 来自 ToolDescriptor
    pub input_hash: String,          // BLAKE3(输入内容)
    pub params_hash: String,         // BLAKE3(规范化参数 JSON)
    pub created_at: String,
}
```

每个导出文件头都嵌入这份元数据，任何人拿到结果都能重算出完全相同的输出。

### 5.7 job 化与进度/取消

本地任务与远程分析任务走**同一套前端抽象**，任务中心不区分来源：

```rust
// apps/desktop/src-tauri/src/job.rs
#[derive(Debug, Clone, serde::Serialize, TS)]
#[ts(export)]
pub struct JobHandle {
    pub job_id: String,
    pub source: JobSource,          // Local | Remote
    pub status: JobStatus,          // Queued | Running | Succeeded | Failed | Cancelled
    pub progress: f32,              // 0.0 - 1.0
    pub message: Option<String>,
}

#[tauri::command]
pub async fn tool_run(
    window: tauri::Window,
    state: tauri::State<'_, AppState>,
    request: ToolRunRequest,
) -> Result<String, String> {
    let job_id = Uuid::new_v4().to_string();
    let cancel = CancellationToken::new();

    state.jobs.insert(job_id.clone(), JobEntry {
        cancel: cancel.clone(),
        started: Instant::now(),
    });

    let wid = job_id.clone();
    let win = window.clone();
    tokio::spawn(async move {
        // 进度回调：每 100ms 节流一次，避免刷爆 IPC
        let progress = |p: f32, msg: &str| {
            let _ = win.emit("job://progress", JobHandle {
                job_id: wid.clone(),
                source: JobSource::Local,
                status: JobStatus::Running,
                progress: p,
                message: Some(msg.to_string()),
            });
        };

        // 大批量扫描走 rayon 并行；每完成一块检查取消令牌
        let result = soymut_algo::run_with_progress(
            &request,
            &cancel,
            &progress,
        ).await;

        let _ = win.emit("job://done", /* ... */);
    });

    Ok(job_id)
}

#[tauri::command]
pub fn job_cancel(state: tauri::State<AppState>, job_id: String) -> Result<(), String> {
    state.jobs.get(&job_id).ok_or("任务不存在")?.cancel.cancel();
    Ok(())
}
```

**前端统一任务中心**（吸收 v2.0 方案中"analyses 列表用 localStorage 兜底"的痛点）：

```ts
// apps/web/src/lib/job-center.ts
export interface UnifiedJob {
  jobId: string;
  source: "local" | "remote";
  toolId?: string;          // 本地任务：工具名
  status: JobStatus;
  progress: number;
}

// 一个 useJobs() hook 同时聚合：
//   - Tauri event "job://progress" / "job://done"（本地）
//   - TanStack Query 轮询 /analyses（远程）
// 统一渲染在 /analyses 页，不再需要 localStorage 兜底
```

### 5.8 结果渲染器注册表

```tsx
// apps/web/src/components/toolbox/registry.ts
type RendererId = "table" | "sequence-track" | "gel" | "heatmap"
                | "volcano" | "manhattan" | "msa" | "tree" | "bar" | "line";

const RENDERERS: Record<RendererId, React.ComponentType<{ model: unknown }>> = {
  table:          ResultTable,      // 复用现有 DataTable
  "sequence-track": SequenceTrack,  // 自绘 SVG
  gel:            GelView,          // 自绘 SVG
  heatmap:        EChartsRenderer,  // 复用 use-echarts.ts
  volcano:        EChartsRenderer,
  manhattan:      EChartsRenderer,
  msa:            MsaView,          // 自绘 Canvas
  tree:           TreeView,         // 自绘 SVG
  bar:            EChartsRenderer,
  line:           EChartsRenderer,
};
```

**复用优先**：热图/火山图/曼哈顿图/柱状/折线全部走已有的 ECharts 封装
（`apps/web/src/lib/use-echarts.ts`），只有序列轨道、凝胶、MSA、树需要自绘。

### 5.9 与数据库的协同：发送到工具箱（差异化能力）

这是本方案**最有价值的一环**，也是参考模板完全没有的场景。

```tsx
// 在基因详情、变异列表、突变体详情等页面统一提供
<SendToToolboxMenu
  payload={{ kind: "gene", geneId, assembly }}
  // 可选目标工具由 payload 类型推导：
  //   gene        → enzyme.digest / primer.design / motif.scan / orf.find
  //   variant     → seq.extract / primer.design
  //   mutantLine  → 批量：primer.design（批量设计）
/>
```

批量场景（最有说服力）：

```
用户在突变体列表筛出 120 个候选（诱变方式 = EMS × 表型 = 矮化 × 基因 = GmDW1）
  → 全选 → 「发送到工具箱 → 批量设计引物」
  → 本地一次性为 120 个位点设计引物（rayon 并行，约 3–8 秒）
  → 结果表格：每对引物的 Tm/GC/长度/产物大小/评分
  → 导出 CSV 直接送测序公司
```

**这条路在纯 Web 版上走不通**（120 个位点逐个请求服务端，慢且占用服务端资源），
在纯 TBtools 上也走不通（没有突变体库）。**这是桌面客户端存在的理由。**

### 5.10 许可证处理

参考模板 §7.4 与 R1/R2 风险同样适用于本项目，处理如下：

| 项 | 许可证 | 处理 | 理由 |
|---|---|---|---|
| **Primer3** | GPLv2+ | **自研，不链接** | 重写 SantaLucia 1998 最近邻参数 + Owczarzy 2004 盐校正；二聚体/发夹用简化 NN 模型 |
| **REBASE 酶库** | 官网声明 open database | **内置常用子集** | 引用 PMID 36318248；仍需法务确认再分发条款；提供用户导入通道 |
| **EMBOSS** | GPL | **仅作参考实现** | 不链接、不复制代码 |
| **MEME Suite** | 学术免费/商用需核 | 不引入 | motif 扫描用自研 PWM 实现 |
| **MAFFT** | BSD | **可包装**（B2） | 外部二进制，按需下载，不静态链接 |
| **muscle v5** | GPLv3 / 非商用免费 | 优先不用 | 若必须用，改用 MAFFT 或自研 |

**Primer3 替代方案的正确性门槛**（对齐参考模板 R1）：

```
黄金集对拍：
  取 200 条参考序列（含高 GC 60–75%、长产物 1–3 kb、含简并位点）
  → 分别用 Primer3 与自研实现计算 Tm
  → 通过标准：平均绝对偏差 < 0.5 °C，最大偏差 < 1.5 °C
  → 不通过则降级为「调用用户自备 Primer3 二进制」
```

**这个 spike 必须在 MVP 之前做**（参考模板把引物热力学列为 R1 头号风险是有道理的
—— 同类项目的经典翻车点）。

---

## 6. 本地 vs 远程的调度规则

### 6.1 决策表

| 能力 | 执行位置 | 判据 |
|---|---|---|
| 基因/突变体/变异检索 | 远程 | 数据在服务端 |
| 详情、JBrowse 浏览 | 远程 | 同上 |
| BLAST | **远程** | 需要全库索引（GB 级），本地放不下 |
| GWAS / PopGen / 表达模式 | 远程 | 需要全量数据与服务端预聚合 |
| 分析任务（fastp / scanpy） | 远程 | 算力密集，服务端有队列与资源隔离 |
| **序列解析与格式转换** | 本地 | 输入是用户文件 |
| **酶切 / 引物 / motif / ORF** | 本地 | 输入小（单条序列），秒级完成 |
| **多序列比对 / 系统发育** | 本地 | 输入是用户的小数据集 |
| **富集分析** | **两端都有** | 见下 |
| **批量工具**（≤500 条） | 本地 | 数据已从服务端取回，本地并行更快 |

**富集分析的两端选择规则**：

```ts
function pickEnrichmentExecution(geneCount: number): "local" | "remote" {
  // 本地注释包是精简版（约 5000 基因），覆盖不全；
  // 大基因集走服务端全量注释库更准。
  return geneCount <= 500 ? "local" : "remote";
}
```

两种执行路径的 UI 完全一致（同一份 descriptor，只有 `execution` 字段不同），
用户无需感知。

### 6.2 统一任务中心

`/analyses` 页面同时展示本地与远程任务（§5.7），统一的状态色、进度、取消、结果入口。
这顺带解决了 v2.0 方案里提到的"远程任务列表 404 时回落到 localStorage"的体验缺口。

---

## 7. 免安装打包与分发

### 7.1 产物矩阵

| 平台 | 免安装产物 | 体积（估） | 安装版产物 | 说明 |
|---|---|---|---|---|
| Windows x64 | `SoyMutDB_1.0.0_x64-portable.zip` | ~25 MB | `SoyMutDB_1.0.0_x64-setup.exe`（NSIS） | WebView2 缺失时引导下载 |
| macOS aarch64 | `SoyMutDB_aarch64.app.zip` | ~22 MB | `SoyMutDB_aarch64.dmg` | 无需 WebView2 |
| macOS x64 | `SoyMutDB_x64.app.zip` | ~22 MB | 同上 | |
| Linux x64 | `soymutdb_1.0.0_amd64.AppImage` | ~30 MB | `.deb` / `.rpm` | 需 WebKitGTK 4.1+ |

### 7.2 portable 模式实现

**目标**：解压目录自包含，删目录即卸载，不写注册表、不写用户目录。

**检测逻辑**：可执行文件同级存在标记文件 → portable 模式 → 数据目录用 `./_data/`。

```rust
// apps/desktop/src-tauri/src/portable.rs
const PORTABLE_MARKER: &str = "portable.txt";

pub fn data_dir(app: &tauri::AppHandle) -> PathBuf {
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|p| p.to_path_buf()))
        .expect("无法定位可执行文件目录");

    if exe_dir.join(PORTABLE_MARKER).exists() {
        // 免安装模式：全部状态落在解压目录内
        let dir = exe_dir.join("_data");
        let _ = std::fs::create_dir_all(&dir);
        dir
    } else {
        // 安装模式：使用平台标准目录
        app.path().app_data_dir().expect("无法解析应用数据目录")
    }
}
```

打包时把 `portable.txt` 放进 zip 根：

```jsonc
// tauri.conf.json
{
  "bundle": {
    "resources": {
      "../portable.txt": ""      // 仅 portable 构建变体包含
    },
    "targets": ["app", "appimage", "nsis", "dmg", "deb", "rpm"]
  }
}
```

用一个 cargo feature 区分两种变体：

```bash
cargo tauri build --features portable    # 产出免安装包
cargo tauri build                        # 产出安装版
```

**portable 目录布局**：

```
SoyMutDB-Portable/
├── SoyMutDB.exe            （或 SoyMutDB.app / *.AppImage）
├── portable.txt            ← 标记文件，删掉它就变成"安装模式"
└── _data/                  ← 首次运行时创建
    ├── config.json         服务器地址、UI 偏好
    ├── jobs/               任务产出与缓存
    └── logs/
```

### 7.3 更新通道

```jsonc
// tauri.conf.json
{
  "plugins": {
    "updater": {
      "active": true,
      "endpoints": ["https://desktop.soymutdb.org/{{target}}/{{arch}}/{{current_version}}"],
      "dialog": true,
      "pubkey": "<minisign 公钥>"
    }
  }
}
```

**免安装版的更新是个真问题** —— 没有安装程序，谁来做替换？

方案：**应用内自更新 + 手动兜底**

1. Tauri updater 下载新版本到临时目录；
2. 检测到 portable 模式 → **不自动替换正在运行的 exe**（Windows 上文件被占用），
   改为提示用户：「新版本已下载，点击重启以完成更新」，重启时用
   一个小的 Rust 引导进程完成文件替换（或提示手动解压覆盖）；
3. macOS/Linux 无文件占用问题，可直接替换后重启。

**最低限度**：即使自更新失败，也要保证"下载新 zip → 解压覆盖 → 配置与数据保留在 `_data/`"这条路走得通。
这正是 portable 模式把数据分离到 `_data/` 的又一个收益。

### 7.4 体积预算

| 组成 | 当前 | 优化后 | 说明 |
|---|---|---|---|
| Tauri 壳（不含 WebView） | — | ~4 MB | Win/Linux；macOS 更小 |
| 前端 JS（首屏） | 2.02 MB | **~0.9 MB** | v2.0 方案 P0-3（antd 拆桶）的收益 |
| **CJK 字体** | **12.7 MB** | **~0.4 MB** | v2.0 方案 P0-2（GB2312 一级汉字子集化） |
| 其它静态资源 | ~1.5 MB | ~1.5 MB | 图片、JBrowse 配置等 |
| 算法核心（Rust） | — | ~3 MB | release + LTO + strip |
| REBASE 酶库子集 | — | ~0.6 MB | 约 400 常用酶 |
| GO/KEGG 精简注释包 | — | ~8 MB | B 组启用后；MVP 可不含 |
| **合计（MVP）** | — | **约 25 MB** | 与参考模板"Tauri 3–10MB"的量级一致（含资源） |

**关键协同**：v2.0 性能方案的 **P0-2（字体子集化）在这里有额外且巨大的收益** ——
免安装包从 ~38 MB 降到 ~25 MB。字体子集化原本是"首屏性能优化"，
在桌面场景下直接变成"分发体积优化"。两项工作应合并排期。

### 7.5 签名与公证

| 平台 | 要求 | 动作 |
|---|---|---|
| Windows | 建议签名（否则 SmartScreen 警告） | 需 EV/OV 代码签名证书 |
| macOS | **必须**签名 + 公证，否则 Gatekeeper 拦截 | Apple Developer ID + `notarytool` |
| Linux | 无强制 | AppImage 附 SHA256SUMS + GPG 签名 |

**macOS 公证是免安装版的硬门槛** —— 用户双击 `.app` 时 Gatekeeper 会拦截未公证的应用。
必须在 CI 里串进 `notarytool`，不能留给手动。

---

## 8. 功能边界（要 / 不要）

### 要做

- [x] 复用 `apps/web` 全部 UI，零重写
- [x] 数据库能力走远程 API，不携带任何数据集
- [x] 生信工具本地执行，数据不出本机
- [x] 服务器地址可配置（公共站 / 私有部署）
- [x] 原生文件对话框、原生下载、系统通知
- [x] 免安装（portable）为主，安装版为辅
- [x] 统一任务中心（本地 + 远程）
- [x] 工具注册表 schema 驱动，新增工具不写页面
- [x] 结果可导出、可复现（输入哈希 + 参数 + 算法版本）

### 不要做

- [x] **不打包 admin**（保持独立 Web 应用）
- [x] 不在客户端内置数据集
- [x] 不重写现有 Python 算法为 Rust（只新增本地工具层）
- [x] 不引入 Go sidecar（已有 Celery 做长任务调度，无收益）
- [x] 不做 Vue 版（项目已锁定 React + antd）
- [x] 不做峰图 `.ab1`、质粒设计、NGS 重型流水线
- [x] 不做云端协作 / ELN / 跨设备同步
- [x] 不在远程层引入 ts-rs（已有 OpenAPI 链路，见 §2.1）

---

## 9. 与既有三份方案的协同

| 既有方案 | 关联项 | 协同方式 |
|---|---|---|
| **v1.0 正确性** | 数据导入 writer 未实现（7 个导入类型 feature flag 默认 OFF） | 桌面端不直接解决，但工具箱的"结果可复现"元数据可复用于导入审计 |
| **v2.0 性能 · P0-2** | 字体子集化 12.7 MB → 0.4 MB | **直接收益于分发体积**（§7.4），应合并排期 |
| **v2.0 性能 · P0-3** | antd 拆桶 923 KB → 首屏不加载 | 同时缩小免安装包体积 |
| **v2.0 动效** | WebGL 流体渐变、ECharts 在 WebView 的表现 | 桌面端 WebView 固定版本，**必须**做三端渲染回归（见 §10 spike S6） |
| **v2.0 监控 · P0-7** | `initPerfMonitoring` 未调用 | 桌面端同样接入，但需尊重本地优先：遥测默认关闭，用户可开启 |
| **架构（本次）** | 统一任务中心 | 吸收 v2.0 提到的"localStorage 兜底"痛点 |
| **架构（本次）** | `/capabilities` 端点 | 桌面端据此动态裁剪 UI，无需硬编码功能开关 |

---

## 10. 路线图与 Spike

### 10.1 Spike 清单（必须先行）

| # | Spike | 内容 | 通过标准 | 工期 |
|---|---|---|---|---|
| **S1** | **跨站认证**（阻塞级） | 方案 B 在 macOS `tauri://` 下走通登录 → 重启 → session 恢复 | §4.3.6 五项全通过 | 2 天 |
| **S2** | 引物热力学 | Rust 实现 vs Primer3 黄金集对拍 | Tm 平均绝对偏差 <0.5 °C | 3–5 天 |
| **S3** | WebView 渲染回归 | 三端跑首页 WebGL 流体渐变 + ECharts + 序列轨道 | 视觉一致，无崩溃，帧率达标 | 2 天 |
| **S4** | 打包与公证 | 三端打包 + macOS 公证 + 体积实测 | 免安装包可双击运行，体积 <30 MB | 2 天 |
| **S5** | noodles 大文件 | 1 GB FASTA 流式解析 + 进度回传 | 内存 <500 MB，进度平滑 | 1 天 |
| **S6** | IPC 大数据回传 | 10 万行结果表经 IPC 传前端 | 首屏 <1 s，不卡 UI | 1 天 |

> **S1 与 S2 是 go/no-go 门槛**：任一失败，方案需要重新设计
> （S1 失败 → 强制走方案 A；S2 失败 → 引物改为调用用户自备 Primer3）。

### 10.2 里程碑

| 阶段 | 交付 | 依赖 |
|---|---|---|
| **M0 · 可行性** | S1–S4 全部 spike 通过，产出决策记录 | — |
| **M1 · 壳与认证** | Tauri 应用跑起来，登录/会话/服务器切换可用，三端免安装包 | S1, S4 |
| **M2 · 工具箱 MVP** | A 组六工具 + 工具注册表 + 结果渲染器 + 导出 | S2, S3, S5, S6 |
| **M3 · 数据库协同** | 「发送到工具箱」+ 批量工具 + 统一任务中心 | M1, M2 |
| **M4 · 工具箱扩展** | B 组：比对 / 系统发育 / 本地富集 / 质控统计 | M2 |
| **M5 · 安全与生态** | 方案 A（keychain 凭据托管）+ 插件机制 + WASM 沙箱评估 | M3 |

### 10.3 每阶段验收与回滚

- **M1–M2**：桌面端是**纯增量**，不影响 Web 版与 API，回滚 = 不发布客户端；
- **M3**：涉及 `apps/web` 新增"发送到工具箱"入口，需保证非桌面模式下该入口隐藏；
- **M5**：方案 A 与方案 B **并行可用**一段时间（后端同时支持两种 transport），
  灰度验证后再下线 B。

---

## 11. 风险

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| **D1** | **macOS `tauri://` origin 的 CORS 不接受**（S1 失败） | 认证走不通 | 立即切方案 A（keychain 托管），已备好设计与代码 |
| **D2** | **引物热力学重写不达标**（S2 失败） | 功能降级 | 改为调用用户自备 Primer3 二进制；UI 不变 |
| **D3** | **WebView 跨端渲染差异**（Win WebView2 / macOS WKWebView / Linux WebKitGTK） | 出图不一致、动效卡顿 | S3 三端截图回归；复杂图优先 Canvas/ECharts；AppImage 捆绑 WebKitGTK 说明 |
| **D4** | **macOS 公证阻塞** | 用户打不开 | CI 集成 `notarytool`；M1 就要跑通，不留到最后 |
| **D5** | **SameSite=None 扩大 CSRF 面** | 安全 | 严格 Origin 白名单 + 强制 Origin 校验 + CSRF 双提交（§4.3.5） |
| **D6** | **REBASE 再分发条款未确认** | 法务 | 法务优先确认；内置子集 + 用户导入双通道 |
| **D7** | **工具注册表过度设计** | 开发效率反降 | 约束 schema 只支持 UI 真正需要的子集；超过 3 个 `x-widget` 扩展就要评审 |
| **D8** | **本地大文件内存爆炸** | 崩溃 | Rust 流式 + 分块；UI 只拿采样/聚合视图；S5 验证 |
| **D9** | **rust-bio API 不稳定**（若后续引入） | 维护成本 | 锁次版本 + 薄封装适配层（参考模板 R8） |
| **D10** | **桌面端与 Web 版功能漂移** | 维护两份 | 同一套 `apps/web` 源码 + `DeploymentMode` 分支；CI 双模式构建校验 |

---

## 附录 A：关键文件索引

### 现状（需改动或对接）

| 文件 | 作用 | 改动 |
|---|---|---|
| `apps/api/app/core/config.py:161-171` | refresh cookie 配置 | 部署时设 `SAMESITE=none` / `SECURE=true` |
| `apps/api/app/core/config.py:193` | `cors_origins` | 追加两个 Tauri origin |
| `apps/api/app/core/csrf.py:23-30` | Origin 白名单校验 | 无改动（复用 cors_origins） |
| `apps/api/app/api/v1/auth.py:66-73` | cookie 设置 | V1.1 加 `transport=token` 分支 |
| `apps/api/app/schemas/auth.py` | `TokenResponse` | V1.1 加 `refresh_token` 字段 |
| `apps/api/app/api/v1/capabilities.py` | 能力端点 | 无改动，桌面端直接消费 |
| `apps/api/app/core/features.py` | 特性开关 | 无改动，桌面端据此裁剪 UI |
| `apps/web/src/lib/deployment.ts` | 部署模式与 CSP | 加 `desktop` 模式；CSP 返回空串 |
| `apps/web/vite.config.ts:86,112` | base 路径 | desktop 构建传 `VITE_BASE_URL=./` |
| `apps/web/src/main.tsx` | SW 注册 | desktop 模式跳过 |
| `packages/api-client/src/client.ts:41` | `apiBaseUrl` | 加 `setApiBaseUrl` 运行时覆盖 |
| `packages/api-client/src/auth.ts` | session 恢复 | V1.1 抽 `TokenProvider` 接口 |
| `apps/web/src/routes/search/primer.tsx` | 引物设计（启发式） | M2 用真实热力学替换 |
| `apps/web/src/lib/analyses-local.ts` | localStorage 任务兜底 | M3 由统一任务中心取代 |

### 新增

| 路径 | 内容 |
|---|---|
| `apps/desktop/` | Tauri 应用（壳、命令、job、凭据、portable） |
| `apps/desktop/src-tauri/src/server_config.rs` | 服务器地址管理（§3.5） |
| `apps/desktop/src-tauri/src/portable.rs` | 免安装模式检测（§7.2） |
| `apps/desktop/src-tauri/src/job.rs` | 本地任务调度（§5.7） |
| `apps/desktop/src-tauri/src/auth_broker.rs` | V1.1 凭据托管（§4.4） |
| `crates/soymut-core/` | IR、错误、ToolDescriptor、结果元数据 |
| `crates/soymut-parse/` | noodles 封装 |
| `crates/soymut-algo/` | enzyme / primer / motif / align / orf / stats / enrich |
| `crates/soymut-viz-model/` | 绘图数据建模 |
| `packages/ipc-types/` | ts-rs 生成的 IPC 类型 |
| `apps/web/src/components/toolbox/` | SchemaForm、结果渲染器、发送到工具箱 |
| `apps/web/scripts/build-desktop.ts` | 桌面构建脚本（§3.3） |

---

## 附录 B：参考模板（biotoolbox）对照决策记录

逐条对照 `architecture-exploration-merged.md`，记录采纳 / 改造 / 否决与理由。

| 模板主张 | 决策 | 理由 |
|---|---|---|
| **Tauri 2.x 桌面壳** | ✅ **采纳** | 正是本次需求。体积与启动优势对免安装分发意义重大 |
| **React + antd v5 主力** | ✅ **已是现状** | 项目已锁定，无需决策 |
| **Vue + antdv 双轨** | ❌ **否决** | 项目无 Vue 轨；双前端维护成本翻倍（模板自己列为 R9） |
| **Rust 算法核心（同进程）** | 🔄 **改造采纳** | 采纳于**本地工具层**；不重写现有 Python 算法（BLAST/scanpy 生态无法重写） |
| **Go sidecar（V2）** | ❌ **否决** | 已有 Celery 按 8 队列分工做长任务调度，引入 Go 无收益 |
| **MVP 全部 Rust** | 🔄 **改造** | 改为"MVP 本地工具全部 Rust"；数据库能力仍走 Python API |
| **ts-rs 生成 TS 类型** | 🔄 **部分采纳** | 仅用于本地 IPC 层；远程层已有 OpenAPI + CI 强制同步，更成熟 |
| **插件机制三阶段** | ✅ **采纳（延后 M5）** | 仓库已有 `core/plugins.py` + `plugin_service.py` + `/capabilities`，基础设施在位；当前仅 1 个插件（ols4），先做工具注册表，插件生态放 M5 |
| **本地优先、数据不出本机** | ✅ **采纳** | 本项目最直接的产品价值（育种数据合规） |
| **工具 = 声明式配置，UI 自动生成表单** | ✅ **核心采纳** | 对 38 路由 / 50 路由文件的堆叠型项目是最高效敛手段（§5.3） |
| **UI 线程不做 >50ms 计算** | ✅ **采纳** | 写入 §3.1 纪律 |
| **大文件流式 + UI 只拿采样** | ✅ **采纳** | 写入 §3.1 纪律 + S5 spike |
| **持久化 .biox 项目包（SQLite + 资产）** | 🔄 **改造** | 本项目是数据库而非设计工具，改为**结果元数据**（输入哈希 + 参数 + 算法版本）嵌入导出文件（§5.6） |
| **REBASE 酶库（open database）** | ✅ **采纳** | 内置常用子集 + 用户导入；法务确认再分发 |
| **Primer3 GPLv2+ → Rust 重写** | ✅ **采纳（含 S2 门槛）** | 采纳重写路径，但设黄金集对拍门槛（模板 R1） |
| **EMBOSS 仅作参考** | ✅ **采纳** | 同样约束（GPL 传染性） |
| **不做峰图 .ab1** | ✅ **采纳** | 模板 R6，本项目同样排除 |
| **WASM 插件沙箱（V3）** | ⏸ **延后 M5 评估** | 与插件机制一并评估 |
| **Go 独立 CLI（对标 SeqKit）** | ❌ **否决** | 无批量 CLI 需求；服务端 worker 已覆盖 |

**一句话总结**：模板中**架构分层、声明式工具、本地优先、许可证纪律**四项正确且高价值，直接采纳；
**Rust 全量重写、Go sidecar、双前端**三项不适用于已有成熟 Python API 与 Celery 体系的 SoyMutDB，予以否决或改造。

---

## 附录 C：工具清单总表

| ID | 名称 | 组 | 执行 | 阶段 | 依赖 |
|---|---|---|---|---|---|
| `io.convert` | 格式解析与转换 | A | 本地 | M2 | noodles |
| `seq.basic` | 反向互补/翻译/GC | A | 本地 | M2 | 自研 |
| `enzyme.digest` | 限制性酶切 | A | 本地 | M2 | 自研 + REBASE |
| `primer.design` | 引物设计 | A | 本地 | M2 | **自研（S2 门槛）** |
| `motif.scan` | Motif / 顺式元件扫描 | A | 本地 | M2 | 自研 |
| `orf.find` | ORF 查找与翻译 | A | 本地 | M2 | 自研 |
| `align.pairwise` | 两两比对 | B | 本地 | M4 | 自研 |
| `align.msa` | 多序列比对 | B | 本地 | M4 | MAFFT（BSD） |
| `phylo.tree` | 系统发育（NJ/UPGMA） | B | 本地 | M4 | 自研 |
| `stats.enrich` | 富集分析 | B | **两端** | M4 | GO/KEGG 包 |
| `stats.kmer` | k-mer 统计 | B | 本地 | M4 | 自研 |
| `qc.fastq` | FASTQ 质控统计 | B | 本地 | M4 | noodles |
| — | 序列轨道图 | C | 渲染 | M2 | 自绘 SVG |
| — | 凝胶模拟图 | C | 渲染 | M2 | 自绘 SVG |
| — | 热图/火山/曼哈顿 | C | 渲染 | M2 | **已有 ECharts** |
| — | MSA 着色视图 | C | 渲染 | M4 | 自绘 Canvas |
| — | 进化树 | C | 渲染 | M4 | 自绘 SVG |

---

*本方案为设计提案。所有版本号、体积估算与工期需在上述 spike 后修订。*
