# CNB 启动与验收

> 面向"在 CNB 上把这个项目跑起来，并判断某个修订是否可用"的两条入口。
> 交付链路本身见 [`ci-cd.md`](ci-cd.md)，迁移对照见
> [`../dev/pipeline-migration.md`](../dev/pipeline-migration.md)。

## 1. 两条入口

| 问题 | 入口 | 实现 |
| --- | --- | --- |
| 能不能跑起来？ | 分支页「启动 SoyMutDB 开发环境」按钮（`vscode` 事件） | `scripts/start-cloud-dev.sh` |
| 这个修订能不能收？ | 「运行验收」按钮 / `bash scripts/acceptance.sh` | `scripts/acceptance.sh` |

两条入口都遵守同一条规则：**配置里只做编排，逻辑放进脚本**。stage 体一律是
`bash scripts/<name>.sh [args]` 的单行调用，理由见 `ci-cd.md` 的「Stage shell」——
CNB 用 `sh`（dash）执行 stage 脚本，dash 在运行期拒绝 `set -o pipefail`。

## 2. 启动：云原生开发

### 2.1 点击路径

分支页右上角「云原生开发」→ 触发 `.cnb.yml` 中 `$` 下的 `vscode` 流水线。按钮文案
与 CPU 规格在 `.cnb/settings.yml`：

```yaml
workspace:
  launch:
    button:
      name: 启动 SoyMutDB 开发环境
    cpus: 4
```

`cpus: 4` 是刻意的：平台默认 8 核是给交付流水线（构建并扫描镜像）用的，开发环境
装依赖 + Vite + uvicorn 用不到。

### 2.2 环境做了什么

`vscode` 流水线声明 `services: [docker, vscode]`，其中：

- `docker`：数据层（postgres/clickhouse/redis/minio）可以在环境内起；
- `vscode` + `options.onlyPreview`：进入环境后直接是**门户预览页**，而不是 IDE。

环境准备由 `scripts/start-cloud-dev.sh full` 完成，它做五件事：

1. 把服务绑定到 `0.0.0.0`（`VITE_HOST` / `HOST`）。绑 `localhost` 的服务在 CNB
   端口预览里是**不可达**的——代理从容器 loopback 之外连接。这是"环境起来了但预览
   一片空白"最常见的原因，也是本地开发发现不了的原因（本地浏览器能访问 loopback）。
2. **允许 CNB 预览域名**（见 §2.2.1）。Vite 6 会拒绝 `Host` 不在 `allowedHosts`
   里的请求，而 CNB 给每个开发环境**新生成**一个 `*.cnb.space` 主机名。
3. 调 `scripts/setup-workspace.sh`：`corepack enable` + 校验 `pnpm` 在 PATH 上 +
   `pnpm install --frozen-lockfile`。**每个 stage 都是新容器**，所以这步必须在
   本容器内做，不能指望上一个 stage 留下的 shim。
4. （`preview` / `api-preview`）按需拉起数据层：`docker compose … up -d
   postgres clickhouse redis minio`，并把 `SOYMUTDB_DATABASE_URL` 指向它。没有
   PostgreSQL 时 API 无法解析 active release，数据页全部显示"不可用"。compose
   插值所需的变量由 `scripts/setup-workspace.sh` 补默认值（见 §2.2.2）。
5. 打印原始命令（`pnpm dev:web`、`uvicorn`、`docker compose …`），需要更多面时直接
   在终端里起。

### 2.2.1 为什么需要 allowedHosts（Issue #10）

在 CNB 上打开门户预览时曾经直接看到：

```
Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is not allowed.
To allow this host, add "cnb-38o-1k28dm5ta-001.cnb.space" to
`server.allowedHosts` in vite.config.js.
```

Vite 6 默认只接受 `localhost` / 显式配置的 `Host`。CNB 的预览代理用的是
形如 `<环境 id>.cnb.space`（仅预览模式是 `<环境 id>-<端口>.cnb.space`；
`CNB_VSCODE_PROXY_URI` 给的是 `<id>-{{port}}.cnb.run`）的主机名，**每建一个环境
换一个**，所以按提示把报告里的主机名写进 `vite.config.js` 只能修好那一个环境。

处理方式：

* `apps/{web,admin,jbrowse}/vite.config.ts` 的 `server.allowedHosts` 与
  `preview.allowedHosts` 都走 `resolveDevAllowedHosts()`：平台域名
  （`.cnb.space`、`.cnb.run`）按**模式**匹配（Vite 规则：以 `.` 开头的条目匹配该
  域名及其所有子域），`localhost` / `127.0.0.1` / `[::1]` 直接列出。
* 其他隧道通过 `SOYMUTDB_DEV_ALLOWED_HOSTS`（逗号或空格分隔）扩展；
  `start-cloud-dev.sh` 额外从 `CNB_VSCODE_PROXY_URI` / `CNB_DEV_DOMAIN` /
  `CNB_WEB_HOST` / `CNB_HOSTS` 提取主机名并**追加**进去（不覆盖已有值）。
* **不**使用 `allowedHosts: true`：那等于接受任意主机名，会把一个转发出来的预览
  地址变成 DNS rebinding 的跳板。`true` 只在显式设置时生效。
* 作用域仅限 `server` / `preview`，`vite build` 完全不读它，因此构建产物与 CSP
  不受影响。

契约由 `scripts/test_ci_job_contracts.py` 的
`test_cloud_development_preview_survives_a_generated_hostname` 锁定：它**执行**
真正的 `resolveDevAllowedHosts` 并按 Vite 的匹配规则断言
`cnb-38o-1k28dm5ta-001.cnb.space` 通过、`evil.example.com` / `cnb.space.evil.com`
被拒；对应的单元测试在 `apps/web/src/lib/__tests__/deployment.test.ts`。

### 2.2.2 为什么 compose 变量要在引导阶段补默认值（本次构建失败）

打开门户预览曾经在 **Prepare** 阶段直接失败，日志尾部是：

```
[start-cloud-dev] starting the data layer (postgres clickhouse redis minio)
error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
  required variable MINIO_ROOT_USER is missing a value: MINIO_ROOT_USER is required
Pipeline prepare error: Preview launch script execution failed
```

根因不是 minio，而是 **compose 的插值时机**：

* `docker compose` 在**选择服务之前**对**整个文件**做变量插值，所以一个必填变量
  缺失就足以让**任何** compose 调用失败——哪怕命令行只写了 `up -d postgres`；
* `docker-compose.yml` 是**生产**拓扑，刻意 fail-fast：`${POSTGRES_PASSWORD:?…}`、
  `${CLICKHOUSE_PASSWORD:?…}`、`${REDIS_PASSWORD:?…}`、`${MINIO_ROOT_USER:?…}`、
  `${MINIO_ROOT_PASSWORD:?…}` 都**没有默认值**；
* `docker-compose.dev.yml` 里那句 `minio: environment: MINIO_ROOT_USER: minioadmin`
  只是**给容器**赋环境变量，**不定义**插值变量，所以两处都没有兜底；
* 云原生开发环境里没有发布用的 `.env`，插值必然失败。而 `start-cloud-dev.sh`
  的**第一次** compose 调用就会撞上它，于是 preview 流水线在 Prepare 就报错。

处理方式：默认值集中放在 `scripts/setup-workspace.sh`（两个 CNB 入口与本地运行都会
经过它，且都在第一次 compose 调用之前）：

* 只在变量**未设置**时赋值，调用方传进来的值（GitHub 镜像的 `ci-compose-*`、
  运维的真实口令）始终优先；
* 只用 `127.0.0.1` 的开发口令，且**不**在 `docker.build` 镜像构建阶段生效——
  发布路径必须继续 fail-fast；
* 生产文件里**不**加默认值，由
  `test_development_data_layer_environment_satisfies_compose` 锁定这条边界。

### 2.3 预览模式

`onlyPreview` 模式下业务服务必须监听 **8686** 端口（平台固定要求，不是本项目的
偏好），因此端口通过 stage `env` 传入：

```yaml
env:
  SOYMUTDB_DEV_WEB_PORT: "8686"
```

`launch` 命令是 `bash scripts/start-cloud-dev.sh preview`：

- 脚本自己把 Vite 转到后台，并**等到端口可连接**才返回；
- `daemon: false`（默认）保持启动日志可见，符合平台推荐的
  "启动业务 → 确认就绪 → 自行退出" 契约；
- 若 Vite 在绑定端口前退出，脚本**打印日志尾部并返回非 0**，而不是让预览页空着；
- 前端形态由 `SOYMUTDB_DEV_FRONTEND` 选择：`dev`（默认，HMR）或 `preview`
  （`vite preview` 服务已构建的 `apps/web/dist`，启动只需一秒左右，适合看已有的
  制品并避开 HMR 的首次预构建）；`off` 表示只准备环境不起前端。
- `preview` 模式还会按需拉起数据层；`SOYMUTDB_DEV_DATA_LAYER=off` 可显式跳过，
  `on` 则在拿不到 Docker 时报错而不是静默降级。数据层的 compose 插值变量
  （`POSTGRES_PASSWORD` / `CLICKHOUSE_PASSWORD` / `REDIS_PASSWORD` /
  `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`）由 `scripts/setup-workspace.sh`
  在未设置时补开发默认值，否则 compose 会在插值阶段直接失败（§2.2.2）。

想用 WebIDE 而不是预览页，进入环境后从「头像 → 我的云原生开发」切换即可——两种模式
是同一个环境，不存在两套准备逻辑。

### 2.4 手动入口

「启动门户预览环境」按钮（`web_trigger_workspace-preview`）与上面的 `vscode`
流水线调用**同一个脚本、同一个模式、同一个端口**。它存在的原因是默认按钮按分支
展示：评审人想专门要预览、或要在一个默认按钮不出现的分支上起环境时需要一个显式
入口。两条路径共用一个脚本，所以不会漂移——契约测试
`test_cloud_development_buttons_share_one_bootstrap` 锁定这一点。

## 3. 验收：分层判定

### 3.1 一条命令

```bash
bash scripts/acceptance.sh --profile contracts   # 默认，无外部依赖
bash scripts/acceptance.sh --profile backend     # API + Worker（需 PostgreSQL）
bash scripts/acceptance.sh --profile static      # 静态制品 + 字节校验
bash scripts/acceptance.sh --profile runtime     # 迁移 → uvicorn → health → search
bash scripts/acceptance.sh --list
```

| Profile | 内容 | 前置条件 |
| --- | --- | --- |
| `contracts` | 交付/平台/隔离/供应链/K8s 契约 | 无 |
| `static` | 入口文件、引用资源、占位 origin、`SHA256SUMS` | 已构建树 |
| `runtime` | 一次性 PostgreSQL → 真实 uvicorn → live/ready → 搜索链 | `apps/api/.venv` + `SOYMUTDB_DATABASE_URL` |
| `backend` | API + Worker pytest（`SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`） | 同上 |
| `e2e` | Playwright 站点冒烟 | `e2e/node_modules` + 浏览器 |
| `images` | 镜像构建 → 运行时冒烟 → Trivy → SBOM | Docker daemon |
| `full` | contracts + backend + static + runtime | 全部 |

### 3.2 与 `scripts/smoke.sh` 的区别（重要）

两者都分层，但**姿态相反**，这是刻意的：

| | `scripts/smoke.sh` | `scripts/acceptance.sh` |
| --- | --- | --- |
| 定位 | 开发者本地工具 | 平台验收入口 |
| 前置条件缺失 | `SKIPPED: <原因>`，不计入成败 | `BLOCKED: <原因>`，**计入失败** |
| 退出码 | 只由真正跑过的层决定 | 任一层失败或被阻塞即非 0 |

理由：在平台上，前置条件是**流水线定义的属性**，缺了就该在流水线里补，而不是把这一层
放行。所以验收不会把"没跑"报成"通过"。契约测试
`test_acceptance_entry_point_never_reports_a_missing_prerequisite_as_a_pass`
同时锁定两种姿态，防止有人把任一方改成另一方。

### 3.3 验收清单（evidence）

每次运行都写 `artifacts/acceptance/acceptance-manifest.txt`：

```
digest=sha256:<对下方内容取摘要>
repository=crl-code/mutlidb
commit=<sha>
branch=<分支>
event=<触发事件>
build=<CNB build id>
pipeline=<pipeline key>
profile=<profile>
passed=…
failed=…
blocked=…
package_manager=pnpm@11.21.0
node=…
python=…
web_artifact_digest=sha256:…   # 有构建产物时
```

摘要行本身不参与摘要计算，所以**任何人可以重算并核对**，不需要信任这个文件。
流水线在 `endStages` 上传该目录，因此即使某一层失败，验收记录仍在。

## 4. 流水线拓扑（新增部分）

| 触发 | 流水线 | 作用 |
| --- | --- | --- |
| `vscode`（分支页按钮） | `soy-mut-db-development` | 准备环境 + 门户预览 |
| `web_trigger_workspace-preview` | `workspace-preview` | 同上（手动入口） |
| `web_trigger_acceptance` | `acceptance-manual` | contracts → backend → static，上传验收清单 |

按钮声明在 `.cnb/web_trigger.yml`，同时挂到 `^main$`、`^feature/` 与
兜底 `^(?!main$|feature/).*$` 三类分支：验收的意义就在于**合并前**给出判定，
所以只挂在 main 上等于没有验收。

所有新入口都是**无凭据**的（不 `docker login`、不签名、不发布），因此可以安全地
出现在任何分支——契约测试
`test_acceptance_pipeline_reports_per_layer_and_uploads_evidence` 会拒绝把发布动作
混进验收流水线。

## 5. 本地复现

```bash
pnpm dev:cloud          # 等价 bash scripts/start-cloud-dev.sh full
pnpm accept             # 等价 bash scripts/acceptance.sh
pnpm accept --profile contracts
scripts/acceptance.sh --profile full
```

本地无 Docker、无 PostgreSQL 时 `full` 会明确报 `BLOCKED`，这是预期行为，不是缺陷。

## 6. 未验证项

诚实声明：本文描述的两个入口，其**脚本逻辑**已在本机真实执行（`contracts` 层通过、
`start-cloud-dev.sh` 语法与分支自检通过），但以下几点必须在 CNB 上跑过才能判定：

- `vscode` 流水线在平台上的真实启动与 8686 端口预览（含数据层真正 Up）；
  Issue #12 的 compose 插值失败就是在这一步暴露的，修复后仍需平台验证；
- `docker compose config` 在本机不可执行（无 Docker daemon），因此"插值变量齐全"
  由 `scripts/test_ci_job_contracts.py` 的静态契约断言，而不是本机实跑；
- `web_trigger_acceptance` 的 backend / static 两层（需要平台 Runner 与真实
  PostgreSQL）；
- `.cnb/settings.yml` 的按钮文案在分支页的实际呈现。

在这些跑通之前，环境判定仍是 `DEV_READY ✅ / STAGING_READY ❌`，与
`../dev/pipeline-migration.md` §7 保持一致。
