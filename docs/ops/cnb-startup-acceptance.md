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

环境准备由 `scripts/start-cloud-dev.sh full` 完成，它只做三件事：

1. 把服务绑定到 `0.0.0.0`（`VITE_HOST` / `HOST`）。绑 `localhost` 的服务在 CNB
   端口预览里是**不可达**的——代理从容器 loopback 之外连接。这是"环境起来了但预览
   一片空白"最常见的原因，也是本地开发发现不了的原因（本地浏览器能访问 loopback）。
2. 调 `scripts/setup-workspace.sh`：`corepack enable` + 校验 `pnpm` 在 PATH 上 +
   `pnpm install --frozen-lockfile`。**每个 stage 都是新容器**，所以这步必须在
   本容器内做，不能指望上一个 stage 留下的 shim。
3. 打印原始命令（`pnpm dev:web`、`uvicorn`、`docker compose …`），需要更多面时直接
   在终端里起。

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
- 若 Vite 在绑定端口前退出，脚本**打印日志尾部并返回非 0**，而不是让预览页空着。

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

- `vscode` 流水线在平台上的真实启动与 8686 端口预览；
- `web_trigger_acceptance` 的 backend / static 两层（需要平台 Runner 与真实
  PostgreSQL）；
- `.cnb/settings.yml` 的按钮文案在分支页的实际呈现。

在这些跑通之前，环境判定仍是 `DEV_READY ✅ / STAGING_READY ❌`，与
`../dev/pipeline-migration.md` §7 保持一致。
