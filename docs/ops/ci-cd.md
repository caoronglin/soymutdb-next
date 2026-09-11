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
* **只有 `volumes` 跨容器传递**。pnpm store（`/cache/pnpm-store`）与 turbo cache
  （`.turbo`）是显式挂载的，因此"每个容器装一次"实际是做链接而非重新下载。
* 契约测试 `test_no_stage_depends_on_another_stages_container_state` 沿调用链
  检查每个 `pnpm` job 是否真的到达引导脚本，并禁止再出现 "Setup workspace" 这类
  stage 名，同时要求 pnpm job 必须挂 store volume。

## 3. 流水线拓扑

| 触发 | 流水线 | 作用 |
| --- | --- | --- |
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
