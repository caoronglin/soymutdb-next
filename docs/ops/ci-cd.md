# CI/CD 交付架构：CNB 主链路

> 单一事实来源：`.cnb.yml`。GitHub Actions 仅作为镜像保留，两者调用**同一批脚本**。

## 1. 为什么这样组织

交付链路曾经只存在于 4 个 GitHub Actions workflow 里，构建、测试、镜像扫描、签名
逻辑全部内联。这带来三个问题：

1. **无法双栈**：迁移到 CNB 就意味着把 1189 行 YAML 重写一遍，之后两边必然漂移。
2. **无法本地复现**：任何一步失败都只能推到远端等 CI。
3. **门禁不可审计**：一个 `break` 位置的变化不会出现在任何 review 里。

现在所有"做什么"的逻辑都在 `scripts/` 下，`.cnb.yml` 与 GitHub workflow 只负责
**编排（顺序、并发、凭据）**。`scripts/test_ci_job_contracts.py` 会在这两者开始
分叉时直接失败。

## 2. 目录与职责

```
.cnb.yml                         CNB 主流水线（权威定义）
.cnb/pipelines/*.yml             各流水线的可评审记录（verify/api/docker-images/…）
.cnb/web_trigger.yml             手动按钮
.cnb/env/                        构建环境镜像 + 凭据引用
scripts/setup-workspace.sh       单容器引导（corepack + pnpm install），每个 stage 自调
scripts/ci-job-steps.sh          任务体：list / run <job>
scripts/verify-frontend-artifacts.sh
scripts/verify-backend-tests.sh
scripts/with-postgres-service.sh 一次性 PostgreSQL（dind 起容器 + 驱动级就绪探针）
scripts/build-static-apps.sh
scripts/build-release-image.sh   构建 → 冒烟 → 扫描 → SBOM → 导出
scripts/release-contract.golden.sh 合并 → 签名 → attestation → 发布
scripts/build-pages-artifact.sh  静态站点构建
scripts/verify-pages-artifact.sh 发布前字节级校验
scripts/stage-pages-publication.sh 校验 + 暂存待发布静态树
scripts/mcp-transport-smoke.sh   MCP 鉴权传输冒烟
scripts/assert-clickhouse-migration.py
scripts/check-toolchain-pins.py  工具链固定版本一致性守门
scripts/smoke.sh                 统一冒烟入口（5 个 layer）
scripts/start-cloud-dev.sh       云原生开发环境启动（依赖引导 / 门户预览 / API 预览）
scripts/acceptance.sh            平台验收入口（分层判定 + 验收清单）
```

### Stage shell：CNB 用 `sh` 执行 stage 脚本

CNB stage 的 `script` 由 `sh` 执行（Debian 系为 dash）。dash **在运行期**拒绝
`set -o pipefail`：

```
sh: 1: set: Illegal option -o pipefail     # 退出码 2，stage 直接失败
```

注意 `sh -n`（仅语法检查）**不会**报错——所以这条路径靠"本地先跑一遍"是发现不了
的。规则只有两条：

1. **配置里不写 shell 逻辑**。stage 体一律是 `bash scripts/<name>.sh [args]`
   的单行调用，解释器由脚本 shebang 决定，与平台默认 shell 无关。
2. **需要逻辑就加脚本**。`scripts/setup-workspace.sh` 就是这么来的：同一段
   引导逻辑要在 3 个 stage 里重复，抽成脚本后既消除了重复，也让 shell 变得确定。

`scripts/test_ci_job_contracts.py` 会逐个 stage 静态检查：任何未以 `bash`/`./`
开头的多行脚本体、或任何包含 bashism 的未固定解释器的脚本体都会直接失败。
回归测试同时固定了"`sh -n` 抓不到这个问题"这一事实，防止有人把守门简化成空操作。

### 每个 stage 都是全新容器

修好 shell 之后，第一次真实构建暴露出第二个此前被掩盖的问题：

```
Setup workspace with cache   → ✅ success (52.5s)     ← shell 问题已修复
Frontend verification        → ❌ error, exit 127
  scripts/ci-job-steps.sh: line 89: pnpm: command not found
```

CNB 的每个 stage 跑在**自己的新容器**里。`corepack enable` 只是往那个容器的文件
系统写 shim，容器一退出就没了；checkout 也不带 `node_modules`。所以：

* **不存在"准备后续 stage"的 setup stage**。名字里带 `Setup workspace` 的 stage
  只会误导人，已删除。
* **每个需要 JS 工具链的 job 自己引导**。`scripts/ci-job-steps.sh` 里
  `frontend_install` / `dependency_governance_step` 都调用
  `scripts/setup-workspace.sh`；后者先 `corepack enable` + 校验 `command -v pnpm`
  （失败立刻报错，而不是留到三个 stage 之后变成 `command not found`），再
  `pnpm install --frozen-lockfile`。
* **只有 pipeline 级的 `docker.volumes` 跨容器传递**。pnpm store
  （`/cache/pnpm-store`）在流水线级显式挂载，因此"每个容器装一次"实际是做链接而非
  重新下载；turbo 的 `.turbo` 不单独挂载——它位于始终共享的 `/workspace` 之下，
  再声明会成为嵌套卷路径被 CNB 拒绝（"存在包含关系的卷路径"）。
* **卷条目必须是 CNB 语法**：`<path>`、`<path>:<type>` 或
  `<group>:<path>:<type>`，**不是** Docker 的 `host:container`。写成
  `- /cache/pnpm-store:/cache/pnpm-store` 时第二段被当成 *类型* 解析，Prepare 直接报
  `Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store`，一个 stage 都跑不到。
* 契约测试 `test_no_stage_depends_on_another_stages_container_state` 沿调用链
  检查每个 `pnpm` job 是否真的到达引导脚本，并禁止再出现 "Setup workspace" 这类
  stage 名，同时要求 pnpm job 必须挂 store volume。

### `services:` 是 **Pipeline 级**键——写在 stage 里等于没写

`api-tests` 门禁先后踩了两个坑，都是 `services:` 的**位置/取值**问题。

**第一个坑：写数据库名没用。** 早期声明：

```yaml
- name: API + Worker verification
  image: python:3.14
  services:
    - postgres:16        # ← 被接受，但什么都不启动
  script: bash scripts/ci-job-steps.sh run api-tests
```

CNB 接受该声明，**然后什么都没起**（探针构建 `cnb-j0g-1k285hm3b`）：

```
CLOSED postgres 5432 [Errno -2] Name or service not known
CLOSED 127.0.0.1 5432 [Errno 111] Connection refused
/var/run/docker.sock missing
getent hosts postgres → （空）
```

`services` 目前**只实现 `docker`（dind）和 `vscode`**，其他名字既不会报错也不会生效。

**第二个坑：即使改成了 `docker`，写在 stage 里仍然不生效。**
`services` 在 CNB 语法里是 **Pipeline 级**配置项
（[grammar.md#pipeline-services](https://docs.cnb.cool/zh/build/grammar.md#pipeline-services)），
与 `stages`、`docker`、`env` 同级；**Stage / Job 的配置项里没有 `services`**
（见 grammar.md 的 Stage 配置项概览表）。写在 stage 里会被静默丢弃，于是 dind
daemon 和 docker CLI 都不会注入，门禁在解析数据库时直接失败：

```
[postgres-service] docker CLI is unavailable: this stage must declare `services: [docker]`
```

（真实构建 `cnb-m06-1k28813m9`。）

正确写法是把它提升到 **Pipeline 级**，与 `stages:` 平级：

```yaml
- name: verify
  runner:
    cpus: 16
  docker:
    volumes:
      - /cache/pnpm-store
  services:          # ← Pipeline 级：与 stages / docker / env 同级
    - docker         # 真实 dind daemon + docker CLI
  env:
    SOYMUTDB_RUN_POSTGRES_INTEGRATION: "1"
  stages:
    - name: Frontend verification
      script: bash scripts/ci-job-steps.sh run frontend
    - name: API + Worker verification
      image: python:3.14
      script: bash scripts/ci-job-steps.sh run api-tests
```

对「stage 本身就是一个嵌套 pipeline」的写法（`stages:` 内部再出现 `stages:`，
例如 `.cnb/pipelines/docker-images.yml` 的按架构构建），`services` 要放在**内层
那个 pipeline** 上，同样与内层 `stages:` 平级。

代价与取舍：`services` 是 Pipeline 级，无法只对单个 stage 生效，所以声明后
**同一 pipeline 的所有 stage** 都会拿到 dind daemon。这对本项目无害：真正需要
dind 的门禁各自在脚本里显式调用 `docker`，其余 stage 忽略即可；比"门禁静默拿不到
docker"要好得多。

`scripts/with-postgres-service.sh` 负责在拿到 dind 之后起数据库：

1. 已经有 `SOYMUTDB_TEST_DATABASE_URL`（开发者本机 / GitHub runner）→ **原样沿用**，
   完全不动 testcontainers 路径；
2. 否则通过 dind daemon 起 `postgres:16-alpine`，**显式**
   `-p 127.0.0.1:5432:5432`（不要用 `--network host`：它会被接受，但 daemon
   的网络命名空间与 stage 容器不是同一个）；
3. 用 **asyncpg** 真的跑一次 `select 1` 才算就绪。只调 `pg_isready` 不够——
   官方镜像 initdb 期间会先在一个**临时 socket** 上提供服务，`pg_isready`
   照样返回 0，于是脚本会在数据库其实已经可用时宣布它不可用（这正是第一次
   修复时踩到的坑，日志里还顺手 dump 了一份完全健康的 initdb 日志）；
4. 失败即**非零退出**，绝不降级成 skip：隐私/身份/组装矩阵是合并门禁，
   `pytest.skip` 在这里等同于把门禁关掉。

消费方式是 `--print-exports`（POSIX 的 `KEY=VALUE`）而不是 `source`：

```bash
PG_ENV="$(bash scripts/with-postgres-service.sh --print-exports)"
while IFS='=' read -r key value; do export "${key}=${value}"; done <<< "${PG_ENV}"
```

原因和上面 `set -o pipefail` 是同一个：CNB stage 用 `sh`（dash）执行，
`source` 在 dash 里不存在（实测报 `sh: 4: source: not found`，退出码 127）。

契约测试 `test_postgres_backed_stages_declare_a_real_service_and_resolve_a_database`
锁定这些事实：跑数据库门禁的 **pipeline** 必须声明 `services: [docker]`、不得出现
`postgres`/`mysql`/`redis` 之类的伪服务名、**任何 stage 都不得再出现 `services:`
键**（它是 pipeline 级，写在 stage 里会被静默丢弃）、resolver 必须保留"外部 URL
优先"和驱动级就绪探针、门禁脚本不得再出现 `source`。

### 治理 stage 必须自带 Python 工具链（PyYAML + uv）

`pnpm deps:graphs|deps:audit` 会调用 `scripts/dependency_governance.py`，而它
`import yaml`；它随后执行的每个分析器命令又都是 `uv`/`uvx` 调用（deptry、
`uv export`、pip-audit）。GitHub mirror 用一行显式安装把两者都补上：

```
python -m pip install --quiet PyYAML==6.0.3 uv==0.11.33
```

CNB 的治理 stage 没有对应步骤，于是门禁在任何分析器跑起来之前就挂了：

```
$ python3 scripts/dependency_governance.py graphs --output artifacts/dependency-graphs
ModuleNotFoundError: No module named 'yaml'
```

`PyYAML` 是**未声明**依赖——没有任何 pyproject 列它，所以它此前只是碰巧存在于
mirror 上。修法两处，缺一不可：

1. `scripts/ci-job-steps.sh` 新增 `ensure_governance_tooling`：先校验 `python3`
   存在且命中 `PYTHON_VERSION` 钉住的 major.minor（不匹配就 fail closed，避免在
   仓库从未声明的解释器上跑分析器），再探测 `import yaml` 与 `command -v uv`，
   缺哪个装哪个。安装走 `governance_pip_install`，裸 `pip install` 被
   externally-managed 拒绝时回退 `--break-system-packages`（容器是一次性的）。
   版本钉在共享脚本里（`SOYMUTDB_CI_PYYAML_VERSION` / `SOYMUTDB_CI_UV_VERSION`），
   两个 provider 才不会各自解析出不同的分析器版本。
2. 三个阶段（`.cnb.yml` 的 PR/main 两条 verify、`.cnb/pipelines/verify.yml`）
   去掉 `image: node:24.19.0`，改用 `.cnb/env/Dockerfile.frontend` 这个
   Node + Python 双工具链镜像（仅 `docker.build` 能引用 Dockerfile）。
   `.cnb/pipelines/dependency-governance.yml` 作为独立 pipeline 补上自己的
   `docker.build` 与 pnpm store 卷。job body 能装 PyYAML/uv，但变不出解释器。

`scripts/test_ci_job_contracts.py` 的
`test_dependency_governance_stage_can_reach_its_python_tooling` 把以上每条都钉住，
包括共享 pin 必须与 GitHub 步骤的写法一致。

### worker 测试的 `from tests.<module> import` 需要一个包标记

数据库真的能连上之后，worker 套件立刻在**收集阶段**就挂了——一个用例都没跑：

```
apps/worker/tests/test_gene_resolution.py:25: in <module>
    from tests.test_module_tsv_postgres_integration import postgres_engine
E   ModuleNotFoundError: No module named 'tests.test_module_tsv_postgres_integration'
```

`test_gene_resolution.py` 按**包路径**复用共享集成 fixture。这个 import 只有在
`apps/worker/tests` 是可导入包、并以 `tests` 出现在 `sys.path` 上时才成立。
pytest 默认的 `prepend` 导入模式把**测试目录本身**放进 `sys.path`，每个文件按顶层
模块导入——单文件够用，跨模块 import 不够。

**它为什么一直没被发现**：这个模块从来没有真正运行过。stage 连不上数据库，
整个文件被 Testcontainers 的失败挡在后面。所以"只让数据库可达"会把
116 个 error 换成 1 个 collection error——而 collection error 会**中断整轮**，
于是 worker 套件里剩下的用例一个都不会执行。

修法是补上 `apps/worker/tests/__init__.py`（与 `apps/api/tests/__init__.py` 对称），
并加 `scripts/check_worker_test_package.py` 作为门禁。它检查四件事：

1. `__init__.py` 存在；
2. 它**被 git 跟踪**（只存在于工作区、不在 checkout 里的文件等于不存在——
   本仓库已经因为一条未锚定的 `.gitignore` 丢过 `.cnb/env/`）；
3. 每一处 `from tests.<module> import` 指向的模块真实存在且是 `test_*`；
4. 按 pytest 真正使用的导入模式**实测可解析**——注意那不是仓库根目录，
   第一次写这个检查时就是想当然地用了仓库根，结果检查自己先失败了。这条
   打印实际解析路径，避免"检查通过但门禁跑起来仍然挂"。

它在 worker 依赖安装**之前**执行：collection error 会吞掉整轮，这个检查又便宜，
必须抢在昂贵的安装之前失败。

### `.cnb/env/Dockerfile.*` 只能出现在 `docker.build`，不能是 `image:`

第一次真实构建在 `Frontend verification` stage **脚本执行前**就失败了：

```
Runner[docker] $ docker pull .cnb/env/Dockerfile.frontend
invalid reference format: repository name (env/Dockerfile.frontend) must be lowercase
```

`image:` 是**镜像仓库引用**，runner 把它原样交给 `docker pull`。写仓库里的文件路径
必然失败，而且失败发生在任何脚本之前（同一问题在 main 的 `docker-images` /
`release` / `mcp-e2e` 管线同样存在：`docker pull .cnb/env/Dockerfile.build-tools`）。

用 Dockerfile 只有一条合法路径：`docker.build`，而它**只在流水线级别**存在——
CNB 文档明确"任务级仅支持 `image` 配置，不支持 `dockerfile`"。因此：

* 需要 Dockerfile 的 stage，其 `image:` 必须**留空**，由流水线级
  `docker.build.dockerfile` 提供默认环境。
* 同一流水线里需要别的环境（API 用 `python:3.14`、governance 用 `node:24.19.0`）
  的 stage，**保留自己的 `image:`** 覆盖默认值，语义与之前完全一致。
* `docker.build.by` 只列 Dockerfile 本身：stage 体通过 `scripts/` 自行引导工具链，
  Dockerfile 是唯一能改变门禁运行环境的输入。

`test_no_stage_image_is_a_dockerfile_path` 现在对**每个**流水线、**每个** stage 的
`image:` 做静态检查：以 `.`/`/` 开头或含 `Dockerfile` 的值一律失败。此前三个测试
只断言"被引用的文件存在、已被 git 跟踪、带对应工具链"——这些在当时全部成立，构建
依然失败，因为它们都没问"平台能不能在这个位置消费一个路径"。

### `.cnb/env/` 的两个引用文件

`.cnb.yml` 通过路径引用它们，因此它们必须真的在仓库里（
`test_cnb_env_helpers_referenced_by_cnb_yml_exist` 会检查）：

| 文件 | 用途 | 内容边界 |
| --- | --- | --- |
| `.cnb/env/Dockerfile.build-tools` | 镜像构建/扫描/SBOM/签名 stage 的构建环境 | 基础镜像为 `docker:<pin>-cli` + bash/curl/jq/python3；**不含任何密钥** |
| `.cnb/env/release.yml` | 发布流水线/手动按钮导入的**非密钥**配置 | 只有 `SOYMUTDB_OIDC_ISSUER`：`cosign verify` 要 pin 的 OIDC trust root。keyless 签名没有长期私钥；真实凭据仍只在平台 secret store |

两点容易误判：

* 基础镜像**不能**用 `alpine`：Alpine 没有 `docker` 包，而 release / image-build
  stage 全部要调 docker CLI，`FROM alpine` 会在第一条命令就 `docker: command not found`。
  用的是 `docker:<pin>-cli`。
* 基础镜像 tag 必须固定。`scripts/check-toolchain-pins.py` 现在会拒绝
  `.cnb/env/*` 里未固定版本或 `:latest` 的 `FROM`——否则"扫描并签名发布的那个环境"
  可以在没有 review 的情况下变化。当前为 `docker:27.5.1-cli`。
* `trivy` 与 `cosign` **故意不预装**：它们的版本由共享脚本固定
  （`aquasecurity/trivy:0.61.0`，cosign 由 `release-contract.golden.sh` 自行安装并
  校验和），装一份浮动副本会让 CNB 与 GitHub 用不同工具扫同一个镜像。

## 3. 流水线拓扑

| 触发 | 流水线 | 作用 |
| --- | --- | --- |
| `vscode`（分支页「云原生开发」按钮） | `soy-mut-db-development` | 启动开发环境 + 门户预览（`start-cloud-dev.sh`） |
| `web_trigger_workspace-preview` | `workspace-preview` | 同上（手动入口） |
| `web_trigger_acceptance` | `acceptance-manual` | contracts → backend → static，上传验收清单 |
| PR | `verify` | 前端 / API+Worker / 依赖治理（无凭据） |
| main push | `verify` | 同上 + 构建并自校验 Pages 制品 |
| main push | `clickhouse-migration` | 真实 ClickHouse 遗留迁移 + 幂等复跑 |
| main push | `mcp-e2e` | nginx 后的 MCP 鉴权契约 |
| main push | `docker-images (amd64)` / `(arm64)` | 原生架构构建 → 冒烟 → Trivy → SPDX → 导出 |
| main push / tag / 手动 | `release` | 合并双架构 manifest、keyless 签名、SLSA+SPDX attestation |
| main push / 手动 | `publish` | 字节级复制已验证静态树（**不重新构建**） |
| 每日 02:00 | `smoke` | 线上站点 Playwright 冒烟 |

镜像校验与发布**刻意分离**：校验流水线没有任何 registry 写权限，发布流水线不做
任何 `docker build`。这样"发出去的字节"必然等于"验过的字节"。

## 4. 镜像构建与打包发布

**构建/校验**（`scripts/build-release-image.sh`，两种 CI 都调用）：

1. `check-supply-chain.sh` + `check-dockerfile-copy.sh`
2. 构建 API / Worker / MCP / JBrowse
3. 逐镜像运行时冒烟（真实 import / 任务注册表 / nginx `-t`）
4. 断言 `docker image inspect .Architecture` 等于目标平台（原生，非仿真）
5. Trivy CRITICAL/HIGH 硬门禁（`.trivyignore` 为可审计例外）
6. 逐镜像 SPDX SBOM
7. 导出 `validate-runtime-images-<arch>/`：压缩 tar + image ID 清单 + `SHA256SUMS`

**打包发布**（`scripts/release-contract.golden.sh`，provider 无关）：

1. 校验两个架构包（checksum + image ID + 架构）
2. 推送 `<registry>/<owner>/<image>:<tag>-<arch>`
3. 合并 manifest，断言平台集合恰为 `linux/amd64,linux/arm64`
4. 对每个镜像 digest 与平台 digest 做 keyless `cosign sign` + SLSA provenance +
   SPDX attestation，并**立即 verify**
5. 输出 `release-contract/`：`release-manifest.json`（只引用 digest）、
   provenance、SBOM、`OCI_SHA256SUMS`、`SHA256SUMS`、签名的 manifest blob

registry 命名空间、源码身份、pipeline id 全部来自环境变量
（`RELEASE_REGISTRY_OWNER` / `SOURCE_REPOSITORY` / `SOURCE_REVISION`），
因此 GitHub 与 CNB 产出结构完全一致。

## 5. 冒烟测试

```bash
bash scripts/smoke.sh                    # 能跑的都跑，跑不了的明确 SKIPPED
bash scripts/smoke.sh --profile contracts
bash scripts/smoke.sh --profile static
SOYMUTDB_DATABASE_URL=... bash scripts/smoke.sh --profile runtime
bash scripts/smoke.sh --profile images
bash scripts/smoke.sh --list
```

| Layer | 覆盖内容 | 前置条件 |
| --- | --- | --- |
| `contracts` | 交付/平台/隔离/供应链/K8s/CI 契约（134 用例） | 无 |
| `static` | 入口文件、引用资源存在性、占位 origin 扫描、`SHA256SUMS` | 已构建 `apps/web/dist` |
| `runtime` | 迁移 → 真实 uvicorn → live/ready → 发布上下文搜索链 | `apps/api/.venv` + 一次性 PostgreSQL |
| `e2e` | 线上/本地站点浏览器冒烟 | `e2e/node_modules` + Playwright |
| `images` | 镜像构建/冒烟/扫描/SBOM | Docker daemon |

**关键约定**：前置条件缺失时输出 `SKIPPED: <原因>` 并计入 summary，**绝不冒充通过**。
只有真正执行过的 layer 才会决定退出码。

### 5.1 冒烟与验收是两种姿态

`scripts/smoke.sh` 是开发者工具，`scripts/acceptance.sh` 是平台验收入口。两者都分层，
但对"缺前置条件"的处理**刻意相反**：

| | `smoke.sh` | `acceptance.sh` |
| --- | --- | --- |
| 前置条件缺失 | `SKIPPED`，不计入成败 | `BLOCKED`，**计入失败** |
| 理由 | 本地能跑多少算多少 | 平台上前置条件是流水线定义的属性，缺了应修流水线 |

验收还会写 `artifacts/acceptance/acceptance-manifest.txt`（commit / profile / 逐层
判定 / 工具链 / 制品 digest），并在 `endStages` 上传，所以失败的验收同样留下记录。
细节见 [`cnb-startup-acceptance.md`](cnb-startup-acceptance.md)。

## 6. 工具链固定

| 组件 | 版本 | 位置 |
| --- | --- | --- |
| Node | 24.19.0 | `.nvmrc` / `.node-version` / `package.json` / 容器镜像 |
| pnpm | 11.21.0 | `package.json` / `setup-workspace.sh` |
| Python | 3.14 | `pyproject.toml` / `api.yml` / 镜像 tag |
| uv | 0.11.33 | Dockerfile / 治理流水线 |
| Trivy | 0.61.0（容器回退） | `build-release-image.sh` |

版本不再逐条写进每个 stage：pnpm 由 `scripts/setup-workspace.sh` 单点声明。一致性
由 `scripts/check-toolchain-pins.py` 强制，并作为 contracts 冒烟层的第一个检查项执行：

```bash
python3 scripts/check-toolchain-pins.py          # 不一致则退出码 1
python3 scripts/check-toolchain-pins.py --json   # 机器可读
```

它同时校验 `.nvmrc` 与 `.node-version` 互相一致——这两个文件分别由 nvm 与
asdf/volta/mise 读取，此前已经漂移过，没有任何东西会发现。`Node 24.19.0 /
pnpm 11.21.0` 这些写入 `.cnb.yml` 或流水线文件的字面量，另由
`scripts/test_ci_job_contracts.py` 锁定（例如禁止再出现 `node:22`、
`python:3.12`）。

## 7. 凭据边界

* PR 事件的 `CNB_TOKEN` 权限受限，因此所有带凭据的流水线（registry 登录、签名、
  发布）只挂在 main push / tag / 手动按钮上，并有契约测试锁定。
* 镜像推送使用 `CNB_DOCKER_REGISTRY` + `CNB_TOKEN`（`--password-stdin`，不落日志）。
* 签名默认 keyless（OIDC）；`.cnb/env/release.yml` 仅声明需要校验的 issuer。
* 真实凭据放在 CNB 密钥仓库，示例见 `.cnb/examples/release-secrets.example.yml`。

## 8. 本地复现

```bash
pnpm ci:jobs                          # 列出可用任务
pnpm ci:verify                        # 前端门禁
pnpm ci:api                           # 后端门禁（需 PostgreSQL）
SOYMUTDB_CI_ARCH=amd64 pnpm ci:images # 镜像构建/校验（不发布）
bash scripts/smoke.sh                 # 统一冒烟
```

## 9. 回滚

* 配置：`git revert` 本 PR 即可恢复 GitHub-only 链路。`.github/workflows/` 保留
  完整可用路径，未删除任何 job。
* 制品：已发布的 release 由 `release-manifest.json` 的 digest 锚定；回滚使用
  `deploy/scripts/blue-green-rollback.sh`（校验上一次 release manifest 后切换）。
* 迁移：本次未改动任何数据库 schema。
