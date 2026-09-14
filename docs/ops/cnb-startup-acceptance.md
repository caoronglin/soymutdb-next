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
4. （`preview` / `api-preview`）按需拉起数据层：`docker compose … up -d postgres
   clickhouse redis minio`，并把 `SOYMUTDB_DATABASE_URL` 指向它。没有
   PostgreSQL 时 API 无法解析 active release，数据页全部显示"不可用"。
   调用前脚本会补齐 `POSTGRES_PASSWORD` / `CLICKHOUSE_PASSWORD` /
   `REDIS_PASSWORD` / `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` 的开发默认值
   （已导出的值优先，空值视为未设置），并统一加 `--env-file /dev/null`，
   理由见 §2.2.2。
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

### 2.2.2 为什么数据层不需要先 export 任何变量（Issue #12）

`docker-compose.yml` 里每个 `${NAME:?message}` 都是生产 fail-fast 的一部分。
Compose 对**每个文件分别插值**，且在**合并 overlay 之前**完成，所以一个开发环境
曾直接死在 `start-cloud-dev.sh`：

```
error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
required variable MINIO_ROOT_USER is missing a value: MINIO_ROOT_USER is required
```

> 现状（P0 冻结规格）：CNB preview 路径已改为只加载 data-only 的
> `docker-compose.preview.yml`，完全不加载生产 `docker-compose.yml`，因此预览
> 根本不会插值任何生产必填变量；下面的 `docker-compose.dev.yml` `!reset` 修复
> 仍然适用于**本地开发** overlay（它确实加载生产基座）。契约见
> `scripts/test_development_compose_contract.py` 的
> `test_cloud_preview_data_layer_is_standalone_and_data_only`。

这一行不是"少了 `.env`"，而是 overlay 没有真正覆盖到那个 key。四个坑：

1. **`minio: environment:` 不够。** 报错来自 `x-app-env` 这个顶层扩展块（被
   `*app-env` 锚点复用），跟 MinIO 服务本身是不是覆盖了没关系。overlay 里
   `minio: environment: MINIO_ROOT_USER: minioadmin` 只给**容器**赋值，不定义
   插值变量。
2. **`x-app-env: {<<: *dev-app-env}` 也不够。** Compose 对映射做的是**合并**而
   不是替换，`<<:` 的锚点侧仍然会被插值——写在下面的字面量只是"合并后取胜"，
   早于它发生的插值照样报错。只有 `!reset` 能让这个 key 彻底不带默认分支，
   因此 `docker-compose.dev.yml` 用的是 `x-app-env: !reset`。
3. **服务级 `healthcheck` 也要覆盖。** 基础文件里
   `redis` / `redis-celery` 的健康检查是
   `redis-cli -a "${REDIS_PASSWORD:?…}" ping`；`REDIS_PASSWORD` 必须能被插值
   解析（服务自己的 `environment:` 对插值不可见），所以 overlay 直接写死开发
   密码的健康检查。
4. **在 `scripts/setup-workspace.sh` 里 `export` 解决不了问题。**
   `start-cloud-dev.sh` 是用 `bash scripts/setup-workspace.sh` **子进程**调它的
   （第 191 行），子进程的 `export` 不会回到父进程，所以数据层那次
   `docker compose` 拿到的仍是空环境。修在 overlay 里而不是在引导脚本里，
   这一点才成立。

`scripts/test_development_compose_contract.py` 用节点级模型锁住这三条：它按文件
分别模拟插值、映射合并与 `<<:` 默认分支，断言"开发栈从空环境启动时不再要求任何
变量"，同时断言生产文件本身仍然 fail-closed（避免有人用"给基础文件加默认值"的方式
把测试改绿）。`scripts/start-cloud-dev.sh` 另外显式补齐开发默认值，
不依赖调用者先 `export`，也不依赖任何 `.env`。

附带修掉同类的一个坑（PR #14）：若把补默认值的步骤放在脚本开头，而 `log()` 仍声明在
它**下面**，第一次调用就会

```
scripts/setup-workspace.sh: line 122: log: command not found   (exit 127)
```

`set -euo pipefail` 抓不到「未定义命令」，所以整条脚本在 0.1 秒内退出。因此
`scripts/setup-workspace.sh` 里的函数一律**先声明后使用**，由
`test_setup_workspace_declares_helpers_before_it_calls_them` 静态锁定。


### 2.2.3 为什么 license 门要自己做规范化（第二次构建失败）

上一节修好后，`log: command not found` 不再出现，流水线跑到了真正的门禁，
Dependency governance 又失败在 **python-licenses-api**：

```
python-licenses-api: failed (analyzer_exit_nonzero)
license UNKNOWN not in allow-only licenses was found for package fastapi:0.137.1
```

`fastapi` 0.137.1 的元数据是 `License-Expression: MIT`（PEP 639），但
`pip-licenses` 只读旧的 `License` 字段和 Trove 分类器，两者都没有，于是报
`UNKNOWN`。在固定的解释器（python:3.14 / pip-licenses 5.0.0）上复现：API 的
85 个包里 **31 个**被判为 `UNKNOWN`，逐个核对后**每一个都带合法的
`License-Expression`**，没有一个是真正未知的许可证——即门禁在报噪音，而不是
在报发现。

第一次修复给三个 check 都加了 `--from=mixed`，**这不够**：下一个构建
`cnb-fng-1k29s324u` 在同一个包上仍然报 `UNKNOWN`。原因是 piplicenses 的两个
读取分支最终都汇进它的 `License` 列，`mixed` 模式的回退链是
`classifiers or {license metadata}`，而 `license` 只读旧的 `License` 字段；一个
只声明 `License-Expression` 的 wheel，产出的字符串与"完全没有许可证"的包**逐字
相同**。`--with-licenses` 也塞不进权威值：piplicenses 5.0.0 该选项名是
`--with-license-file`，argparse 的前缀匹配会让 `--with-licenses` 命中它，报告会
悄悄开始携带每个包的许可证**全文**。

换成探针之后还有第二个坑：`823a966` 为了让门禁变绿，曾用
`pip-licenses --ignore-packages` 把约 30 个包名塞进跳过列表——分析器根本看不到
这些发行版。这份列表必须随解析出的依赖图重新生成，一旦漂移两个包，门禁就以

```
python-licenses-api: failed (2 license findings)
```

失败，而那两个包正是它被交代过要跳过的。**跳过列表已全部删除**。

处理方式见 [`../design/dependency-graphs.md`](../design/dependency-graphs.md) §8：
探针用 check 自己的 `uv run --project <app>` 选择器把 `pip-licenses` 换成
`python -c`，在同一个环境里按优先级读取每个发行版的声明——权威的
`License-Expression`、真实的 Trove 分类器叶（裸 `License :: OSI Approved` 是类别
不是许可证）、以及单行的旧 `License` 字段（整段粘贴进来的许可证**全文**不算声明）；
投影把声明解析成析取范式（`;`/大写 `OR` 是选择、`AND` 要全满足、`AND` 内的嵌套
`OR` 会分配展开，`WITH` 绑右操作数并归一化掉）后应用 `dependency-licenses.json`；
探针描述不了的包一律 `UNKNOWN` 并继续 fail-closed，元数据确实缺失的包用逐包、
逐许可证的 `@allow-undeclared <name>=<license>` 显式登记（许可证必须已在允许列表
内，否则是硬错误）。规范化结果写进 `summary.json`、`<check>.findings.log` 和
`<check>.declared-licenses.json`。锁定它的测试在
`scripts/test_dependency_governance_contracts.py`（表达式形态与嵌套 OR 分配、
探针三种来源的优先级、探针改写、fail-closed、无忽略列表、fixup 的窄范围、
三处策略不漂移）。

### 2.2.4 为什么发布流水线必须挂在 `main` 而不是 `$`（第三次构建失败）

`cnb-fng-1k29s324u` 的两个流水线都失败在**发布侧**，而且根因相同：

```
Wait for the verified amd64 image package:
  Deadlock detected: cnb:await key "validated-runtime-images-amd64"
  cannot be resolved. Awaiting pipeline: "release"
  Cause: No pipeline contains a cnb:resolve job for this key.

Verify and stage the CI-built artifact before publication:
  [stage-pages-publication] pages artifact pages-dist missing;
  the verify pipeline must run first
```

`release` / `publish` 原本声明在 `$` -> `push` 下。`$` 是**兜底分支**：凡是
有 glob 规则匹配的分支，其流水线**整体替换**兜底（文档
[触发规则](https://docs.cnb.cool/zh/build/trigger-rule.md)，"匹配策略"）。于是
`auto/*` 分支的一次 push 也会启动一个 `release`，而那个事件里根本不存在
`docker-images (amd64)`，也就没有任何 `cnb:resolve`——`cnb:await` /
`cnb:resolve` 只在**同一个事件**的流水线之间配对（文档
[内置任务](https://docs.cnb.cool/zh/build/internal-steps.md)，"使用限制"），
等待因此变成死锁。`publish` 同理：`pages-dist` 由该事件的 `verify` 产出，
在别的分支上它永远不会被构建。

原来的配置试图用一个 pipeline 级 `resources:` 字段表达这个启动依赖，但 **CNB 没有
这个字段**：pipeline 的合法键是
`name / runner / docker / git / services / env / imports / allowFailure /
stages / failStages / endStages / ifNewBranch / ifModify / breakIfModify /
label / retry / lock / sandbox`。写上去既不生效，又读起来像个门禁——这正是问题
被掩盖到第三次构建的原因（三项目标校验现在都能过：
`validate.js .cnb.yml` 的 YAML / 语义 / Schema 全绿，此前 Schema 一直报
`不允许的字段 "resources"`）。

修法是**把两个发布流水线挪到 `main:` 下**：`main` 是 glob 键，它匹配的分支
push 会用它替换 `$`，于是 `verify`、`docker-images (amd64)`、`release`、
`publish` 处在**同一个事件**里，`cnb:await` 才能配对上 `cnb:resolve`；而在其他
分支上仍然是 `$` 兜底，发布流水线**不会启动**，也就不可能启动一个没有上游的发布。
`tag_push` / `vscode` / `web_trigger_*` / `issue.*` 这些仓库级或按钮级事件仍留在
`$` 下（它们只能声明在兜底分支）。

`scripts/test_ci_job_contracts.py` 现在锁定这条不变量：`release` 属于
`main` -> `push`，且任何分支下都不得出现 pipeline 级 `resources` 键。

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
| `main` -> `push` | `verify` | 前端 + API/Worker + 依赖治理 + 静态制品 |
| `main` -> `push` | `docker-images (amd64/arm64)` | 原生架构构建、冒烟、扫描、SBOM、导出 |
| `main` -> `push` | `release` | `cnb:await` 镜像包后签名发布（见 §2.2.4） |
| `main` -> `push` | `publish` | 字节级复制已验证静态制品（见 §2.2.4） |
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
- `docker compose config` 在本机不可执行（无 Docker daemon），因此"开发 overlay
  不再要求任何插值变量"由 `scripts/test_development_compose_contract.py` 的
  节点级静态契约断言，而不是本机实跑；`start-cloud-dev.sh` 交给 compose 的环境与
  命令已用桩验证（`docker` 替换为记录环境的脚本）；
- `web_trigger_acceptance` 的 backend / static 两层（需要平台 Runner 与真实
  PostgreSQL）；
- `.cnb/settings.yml` 的按钮文案在分支页的实际呈现。

在这些跑通之前，环境判定仍是 `DEV_READY ✅ / STAGING_READY ❌`，与
`../dev/pipeline-migration.md` §7 保持一致。
