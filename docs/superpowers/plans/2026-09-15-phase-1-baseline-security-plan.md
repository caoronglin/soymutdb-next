# Phase 1 · 收口门 + 安全与部署遗留收口

> **父计划：** `plan.md`（主路线图）。执行前先读 `plan.md` §2 冻结决策登记表与 §3 前置门。
> **Wave：** W-1、W0、W1
> **退出判据：** §5

---

## 0. 子计划级修订说明

| 二轮审计问题 | 本计划处置 |
|---|---|
| W-1 循环依赖（要求执行尚未创建的门禁） | §1.3 限定为**白名单命令集合**，不等待未来脚本 |
| C13 门禁自身立即失败 | C13 增加 **planned-output allowlist**（从 `Files: 新增` 推导）+ 运行期参数改 `$VAR` |
| Compose 命令缺 fixture（S-2/S-5/S-6/S-7/S-10） | 新增 **S-0** 统一封装 `scripts/compose-fixture-env.sh` |
| S-4 无法消除重复头 | 冻结为 **`proxy_hide_header`**（FZ-3） |
| S-7 移除 `default` 后 MCP 无法访问 Redis | 冻结为**三条专用网络**（FZ-4） |
| S-9 豁免格式未冻结 | 冻结为 **`.trivyignore.yaml` 结构化格式**（FZ-5） |
| C4 Git LFS 验证与收益判断错误 | 改用 `git lfs ls-files` + blob 验证；Accept 改为「停止未来膨胀」（FZ-6） |

---

## 1. W-1 —— 收口门（未通过则 Phase 2/3/4 不得开始）

### W-1.1 · 上一阶段收口

**Files:** `docs/superpowers/plans/2026-09-15-portal-security-ux-perf-optimization.md`、工作树全部改动
**Steps:**
1. 逐条核对上一阶段 §7 DoD（当前 180 项未勾选）：完成，或显式记为「接受风险（理由 + owner）」。
2. 按任务粒度提交（不合并成大 commit）；回归断言与其修复同 commit。
3. PR 描述记录：命令、pass/fail 计数、迁移/环境变量影响、回滚方式、未验证项。

**Verify:**
```bash
git status --porcelain          # 期望：空（或只剩计划文档本身）
git log --oneline -20           # 期望：按任务粒度
```
**Accept:** 工作树干净；无未解释的未勾选项；关键文件（`security-headers*.inc`、`finalize-csp.ts`、三份 nginx 配置、Dockerfile）已在提交历史中。

---

### W-1.2 · 工具链准备（Node 24.19.0 + git-lfs）

> **依据：** 基线曾用 Node 26.8.1 记录，而 `.nvmrc`/`.node-version`/`package.json`/`.cnb.yml`
> 全部钉死 24.19.0；`scripts/check-toolchain-pins.py` 会拒绝不一致。
> C4 需要 `git-lfs`，而当前环境**未安装**。

**Files:** 无仓库改动；本机工具链
**Steps:**

**(a) Node 24.19.0**（官方 tarball + 校验和，与 `check-toolchain-pins.py` 的 `NODE_TARBALL_SHA256` 同源）：
```bash
NODE_VERSION=24.19.0
case "$(uname -m)" in
  x86_64|amd64) ARCH=x64; SHA=14b342e71204f811bde6153be8e04b62aef63c236fef92b55f9c83154b409647 ;;
  aarch64|arm64) ARCH=arm64; SHA=01443c1e1a29e531ccad5a46fefa6df490d2189c49f7955904aecdbb0fe86fdc ;;
  *) echo "unsupported arch"; exit 2 ;;
esac
TARBALL="node-v${NODE_VERSION}-linux-${ARCH}.tar.xz"
curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}"
echo "${SHA}  ${TARBALL}" | sha256sum -c -
mkdir -p "$HOME/.local/node" && tar -xJf "${TARBALL}" -C "$HOME/.local/node" --strip-components=1
export PATH="$HOME/.local/node/bin:$PATH"
node --version   # 必须输出 v24.19.0
```

**(b) git-lfs**（发行版包或官方二进制，二者择环境可用者；必须记录安装方式）：
```bash
git lfs version || {
  echo "git-lfs 未安装：用发行版包管理器安装（apt/dnf/pacman），或从 https://git-lfs.com 取官方二进制"
  exit 2
}
```

**Verify:**
```bash
node --version                      # v24.19.0
pnpm --version                      # 11.21.0
pnpm exec turbo --version           # 2.10.11（turbo 不在 PATH，必须经 pnpm exec）
git lfs version
python3 scripts/check-toolchain-pins.py
```

**Accept:** 四条版本命令输出符合预期；后续所有门禁在 Node 24.19.0 下执行；Node 26 结果**不计入**基线。

**未验证项披露（强制）：** 若本机无法提供 Node 24 或 git-lfs，则 W-1.2 标「未验证」，
W-1.3 基线全部标注「Node 26 临时值，以 CI 的 Node 24 结果为准」，**不得据此做容量结论**，
且 C4 不得开始。

---

### W-1.3 · 基线复测与固化

**Files:** 新增 `docs/ops/baseline-2026-09-15-v2.md`
**Steps:** 在 Node 24.19.0 下重跑主计划 §3 的**白名单命令**（V1–V19），记录：
commit SHA、Node/pnpm/Python/turbo 版本、每条命令的退出码与计数；
对产物记录**全树哈希**（三轮审计 G1：只对两个 `index.html` 做哈希不代表完整制品）。

**Verify（与主计划 §3 白名单一致）：**
```bash
pnpm install --frozen-lockfile
pnpm exec turbo run lint --force
pnpm typecheck
pnpm test
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=https://api.soymutdb.test \
VITE_JBROWSE_BASE_URL=https://jbrowse.soymutdb.test pnpm --filter @soymutdb/web build:sites
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
du -sh apps/web/dist/external
python3 scripts/check_nginx_security_headers.py
python3 scripts/check_artifact_headers.py
SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/external
bash scripts/smoke.sh --profile static --static-dir apps/web/dist/internal
bash scripts/verify-frontend-artifacts.sh
apps/api/.venv/bin/python -m pytest scripts/test_ci_job_contracts.py scripts/test_dockerfile_contracts.py scripts/test_site_artifact_isolation.py scripts/test_supply_chain_contracts.py scripts/test_production_compose_contract.py -q
python3 scripts/check-toolchain-pins.py
apps/api/.venv/bin/python -m pytest scripts/test_cloudflare_tunnel_contract.py -q
apps/api/.venv/bin/python -m pytest scripts/test_development_compose_contract.py -q
# 产物全树哈希（排序后逐文件），而非只哈希 index.html
(cd apps/web/dist/external && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /tmp/ext.sums)
(cd apps/web/dist/internal && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > /tmp/int.sums)
sha256sum /tmp/ext.sums /tmp/int.sums   # 这两个值写进基线报告
```
**Accept:** 报告入库；每个数字可追溯到一条已执行命令；未执行项显式标「未验证」并给出 CI 补验路径。

> **禁止：** 在此任务中执行 `check_font_assets.py` / `check_search_golden.py` /
> `check_pagination_contract.py` / `check_doc_links.py` / `check_plan_commands.py` ——
> 它们由后续任务创建，本任务不等待（避免循环依赖）。

---

## 2. W0 —— 零风险清理与防复发

### C11 · 本机垃圾目录清理与文档化

**Files:** `.gitignore`、`docs/dev/`（新增说明）
**Steps:** 删除 `.validation/`(284 MB)、`.turbo/`(44 MB)、`.pytest_cache/`、`.ruff_cache/`；
确认均在 `.gitignore`；在开发者文档写明「构建缓存目录可安全删除」。
**Verify:**
```bash
test ! -e .validation && test ! -e .turbo
git status --porcelain
```
**Accept:** 工作区体积下降 ≥300 MB 且无文件丢失。

---

### C4 · 仓库二进制纳入 Git LFS

> **修正二轮审计：** v2 的验证写 `git ls-files | xargs du`，但 LFS checkout 后工作区仍是完整
> 2.5 MB 文件，该命令**不会**变成「百字节指针」；且把现有文件转为 LFS **不会**清除 Git 历史中的大对象。

**Files:** `ui-r/网页-查询V2.pdf`、`ui-r/网页-查询V2.pptx`、`.gitattributes`、`docs/design/README.md`
**依赖：** W-1.2 的 `git-lfs` 已安装。**未安装则本任务不得开始。**
**Steps:**
1. `git lfs install --local`
2. 写 `.gitattributes`（**只覆盖 `ui-r/`，避免误伤 `docs/` 下的小体积引用文档**）：
   ```gitattributes
   ui-r/*.pdf  filter=lfs diff=lfs merge=lfs -text
   ui-r/*.pptx filter=lfs diff=lfs merge=lfs -text
   ```
3. `git add .gitattributes`；`git rm --cached "ui-r/网页-查询V2.pdf" "ui-r/网页-查询V2.pptx"`；
   `git add "ui-r/"` 使其按 LFS 指针重新入库。
4. 在 `docs/design/README.md` 说明：两份是设计稿原件，经 LFS 管理；`git lfs pull` 后方可查看；
   后续新增 >1 MB 设计资产一律走 LFS。
5. **历史瘦身不在本任务范围**（破坏性操作，需单独确认后另立计划）。在本任务描述中显式记录这一点。

**Verify:**
```bash
# 暂存区内容（提交前）：必须是 LFS 指针而非 PDF 本体
git show :"ui-r/网页-查询V2.pdf" | head -3       # 期望 version https://git-lfs.github.com/spec/v1
git check-attr filter -- "ui-r/网页-查询V2.pptx"   # 期望 filter: lfs
git lfs ls-files                                  # 期望：两份设计稿均在列
# 提交后可用 HEAD: 复验（等价）：
# git cat-file -p "HEAD:ui-r/网页-查询V2.pdf" | head -3
```
**Accept:** 两份大文件以 LFS 指针入库；`.gitattributes` 只覆盖 `ui-r/`；
`docs/design/README.md` 有可追溯说明；**明确声明「停止未来膨胀」，不宣称历史体积下降**。

---

### C13 · 计划命令门禁

> **修正二轮审计：** v2 要求「引用的仓库内路径存在」，但计划本身引用大量未来文件，
> 门禁在创建当天即失败。

**Files:** 新增 `scripts/check_plan_commands.py`、`scripts/smoke.sh`
**Steps:**
1. 解析 `plan.md` 与五份子计划中所有 fenced 代码块。
2. **planned-output allowlist（核心修正）**：扫描所有 `**Files:**` 行，凡含 `新增` / `new` 的路径
   加入允许缺失集合；另加少量显式白名单（避免任务描述里的「目标文件名」误报）。
3. 检查项：
   - ① 仓库内路径引用存在，**除非**在 planned-output allowlist 中；
   - ② `--profile` 取值属于 `contracts|static|runtime|e2e|images`；
   - ③ 不出现 `bash`/`sh` 执行 `.py` 文件；
   - ④ 不出现裸尖括号占位符（运行期参数必须写成 `$VAR`）；
   - ⑤ 不出现两字母昵称式占位编号、日期占位符、`TODO`、`待补充`。
4. 接入 `scripts/smoke.sh --profile contracts`。

> **必须避免的自触发（三轮审计 B1）：** 规则 ④⑤ 的**负向测试用例不得以字面量写进计划文档**，
> 否则门禁会被自己的示例触发。所有负向用例一律放入 `scripts/test_plan_command_rules.py`，
> 由脚本自己的单元测试覆盖。

**Verify:**
```bash
python3 scripts/check_plan_commands.py
python3 -m pytest scripts/test_plan_command_rules.py -q
# 单元测试必须覆盖三个规则，各一个用例：
#   ① 引用不存在的仓库路径（且不在 planned-output allowlist）
#   ② 用 bash/sh 执行 .py 文件
#   ③ 运行期参数写成裸尖括号而非 $VAR
```
**Accept:** 门禁进共享脚本；三条规则各有单元测试支撑；对**当前**计划文档运行 exit 0。

---

## 3. W1 —— 安全与部署遗留收口

> 必须在任何压力测试之前完成 —— 无限流的公开 API，其容量数字没有意义。

---

### S-0 · Compose fixture 环境封装

> **新增（二轮审计 S5）：** 生产 `docker-compose.yml` 使用 `${VAR:?…}` fail-fast 引用，
> 直接 `docker compose config` 必然失败。此前所有 compose 命令都隐含「调用者已设好变量」，不可复现。

**Files:** 新增 `scripts/compose-fixture-env.sh`、`scripts/ci-job-steps.sh`（`compose_acceptance_run`）、`docs/ops/ci-cd.md`（补说明）
**Steps:**
1. 封装 **6 个 Compose 镜像引用**（与 `docker-compose.yml` 实际使用的一致，
   web/admin 的镜像由静态发布链路处理，**不在 Compose 内**）：
   `API_IMAGE_REF`、`WORKER_IMAGE_REF`、`MIGRATE_IMAGE_REF`、`MIGRATE_CLICKHOUSE_IMAGE_REF`、
   `MCP_IMAGE_REF`、`JBROWSE_IMAGE_REF`；
   以及 7 个凭据/令牌：`POSTGRES_PASSWORD`、`CLICKHOUSE_PASSWORD`、`REDIS_PASSWORD`、
   `MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`SOYMUTDB_MCP_API_TOKEN`、`GRAFANA_PASSWORD`。
2. **只填补未设置的变量**（`${VAR:-default}` 语义），调用者提供的真实值保持权威。
3. 用法：`bash scripts/compose-fixture-env.sh -- <command...>`。
4. **内聚到共享脚本**：`scripts/ci-job-steps.sh` 的 `compose_acceptance_run()`
   内部调用本 helper，使 CNB 与 GitHub 两家 CI 都不再各自列变量
   （当前 `.github/workflows/ci.yml` 只注入 4 个引用，缺两个 migrate —— 这正是缺口来源）。
5. **不得**把 fixture 值写入仓库内 `.env`。

**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- docker compose --profile core config -q
bash scripts/compose-fixture-env.sh -- bash scripts/ci-job-steps.sh run compose-acceptance
# 需 Docker；本机不可执行则标「未验证」
```
**Accept:** 封装可被后续所有 compose 命令复用；不覆盖调用者提供的值；无秘密落盘。

---

### S-1 · 移除全部 `forwarded-allow-ips=*`

**Files:** `infra/docker/Dockerfile.api:60`、`deploy/scripts/conda-services.sh:66`、`deploy/scripts/conda-deploy.sh:182`、`deploy/conda/README.md:79,99,140`
**Steps:**
1. Dockerfile 默认值改为 `127.0.0.1`，**不留 `*` 兜底**；缺变量时退化为「不信任任何代理」。
2. conda 路径引入 `SOYMUTDB_FORWARDED_ALLOW_IPS`；systemd 用 `Environment=` 字面量
   （systemd **不解析** `${VAR:-default}` 语法）。
3. 三处 README 同步 + 新增「反向代理信任边界」小节。
4. 新增门禁：`deploy/`、`infra/` 下出现 `forwarded-allow-ips=*` 或 `0.0.0.0/0` 即失败。

**Verify:**
```bash
! grep -rn "forwarded-allow-ips=\*" deploy/ infra/
! grep -rn "forwarded-allow-ips=0\.0\.0\.0/0" deploy/ infra/
grep -n "SOYMUTDB_FORWARDED_ALLOW_IPS" deploy/scripts/conda-services.sh
```
**Accept:** 全仓无 `forwarded-allow-ips=*`；伪造 XFF 的功能性负向测试通过
（发 `X-Forwarded-For: 1.2.3.4`，断言限流/审计/分析看到的 IP 不是 1.2.3.4）。

---

### S-2 · 限流中间件分级接线

**Files:** `apps/api/app/core/middleware.py`、`apps/api/app/main.py`、`apps/api/app/core/config.py`、`apps/api/app/core/ratelimit.py`
**Steps:**
1. **决策（FZ-2）**：**接线**。直接删除会让 `rate_limit_per_minute` 长期是死配置。
2. **配置拆分（FZ-2，主计划 §2.1）** —— 修复「应用 60/min vs 边缘 100 r/s」的冲突：

   | 配置项 | 默认值 | 作用域 | 后端不可用时 |
   |---|---|---|---|
   | `rate_limit_enabled` | `True` | 总开关 | — |
   | `benchmark_mode` | `False` | **仅 `app_env != prod` 可置 `True`** | — |
   | `public_read_rate_limit_per_minute` | **6000**（=100 r/s） | 匿名 GET | **fail-open** |
   | `write_rate_limit_per_minute` | 120 | 写操作 | **fail-closed** |
   | `login_rate_limit_window` / `_max` | 60 / 10 | `/auth/*` | **fail-closed**（复用 `core/ratelimit.py`） |

   **不变量：** `public_read_rate_limit_per_minute` **不得低于**边缘 `limit_req` 的等效速率
   （100 r/s × 60 = 6000/min）。否则应用层成为实际瓶颈，Phase 2 D1 的边缘配额完全失去意义。
   同时**删除旧字段 `rate_limit_per_minute`**，避免两个来源。
3. **benchmark 开关（Phase 1.5 的 P1 依赖它）：** 关闭限流需**同时**满足
   `benchmark_mode=True` **且** `rate_limit_enabled=False` **且** `app_env != "prod"`；
   生产环境出现任一即 **fail-fast 启动失败**。不得提供 Header 旁路。

   | 路径类别 | 后端不可用时的行为 | 依据 |
   |---|---|---|
   | `/api/v1/auth/*` | **fail-closed**（503） | 已有 `core/ratelimit.py`，不改 |
   | 写操作（POST/PUT/PATCH/DELETE） | **fail-closed** | 防止无约束写入 |
   | 匿名公开读（GET） | **fail-open**；Nginx 边缘 `limit_req` 仍生效 | 公开数据可用性优先 |

4. 限流键使用**可信对端 IP**（与 S-1 同源）；`/health`、`/metrics` 豁免。
5. 进程内 fallback 必须有界（复用 `core/ratelimit.py` 的 2048 键上限写法）。

**Verify:**
```bash
(cd apps/api && .venv/bin/python -m pytest tests -q -k "ratelimit or rate_limit or config_security")
# 断言：写路径 Redis 掉线 → 503；匿名读 Redis 掉线 → 200
# 断言：app_env=prod 且（benchmark_mode=True 或 rate_limit_enabled=False）→ 启动失败
# 断言：配置中已无 rate_limit_per_minute 旧字段
bash scripts/compose-fixture-env.sh -- bash scripts/ci-job-steps.sh run compose-acceptance   # 需 Docker
```
**Accept:** 应用匿名读上限 ≥ 边缘等效速率；两个开关有生产环境 fail-fast 保护；旧字段已删除。

---

### S-3 · 公网 Tunnel 路径补限流

**Files:** `infra/nginx/cloudflare-tunnel.conf`、`scripts/check_nginx_security_headers.py`
**Steps:** 给 Tunnel origin 增加 `limit_req_zone`/`limit_conn_zone`（auth / API 两类）；
把「Tunnel 路径必须有限流 zone」写进门禁。
**Verify:**
```bash
python3 scripts/check_nginx_security_headers.py
apps/api/.venv/bin/python -m pytest scripts/test_cloudflare_tunnel_contract.py -q
```
**Accept:** 经 Tunnel 的公网请求超限返回 429，`/health` 不受影响。

---

### S-4 · 统一安全头权威（冻结为 `proxy_hide_header`）

> **修正二轮审计：** 方案「API 不再发头；若直连 API 仍需要则在 Middleware 补齐」**无法工作** ——
> Middleware 执行时看不到后续 nginx 要加的头，因此仍会补齐，nginx 再追加一次，重复依旧。

**Files:** `infra/nginx/conf.d/default.conf`、`infra/nginx/cloudflare-tunnel.conf`、`apps/api/app/main.py`（仅注释说明职责）
**Steps（**FZ-3**）：**
1. 在 `/api/` 等代理到 API 的 location 中，先隐藏上游同名头，再由片段发出唯一规范值：
   ```nginx
   proxy_hide_header X-Frame-Options;
   proxy_hide_header X-Content-Type-Options;
   proxy_hide_header Referrer-Policy;
   proxy_hide_header Permissions-Policy;
   include /etc/nginx/conf.d/security-headers.inc;
   ```
2. **API 侧 `SecurityHeadersMiddleware` 保留**（直连 API、非 nginx 部署路径的纵深防御），
   在 `main.py` 注释中写明「经 nginx 时会被 `proxy_hide_header` 去重」。
3. `cloudflare-tunnel.conf` 的 `/api/` location 同样处理。

**Verify:**
```bash
# 经 nginx：每个头只出现一次（需 Docker）
curl -sI http://localhost:8080/api/v1/health/live | grep -ci '^x-frame-options:'          # 期望 1
curl -sI http://localhost:8080/api/v1/health/live | grep -ci '^x-content-type-options:'   # 期望 1
# 直连 API：仍有头（纵深防御未被削弱）
curl -sI http://localhost:8000/api/v1/health/live | grep -ci '^x-frame-options:'          # 期望 1
python3 scripts/check_nginx_security_headers.py
```
**Accept:** 经 nginx 无重复头；直连 API 仍有头；门禁绿。

---

### S-5 · Grafana ClickHouse 数据源口令注入

**Files:** `docker-compose.yml`（grafana 服务）、`infra/monitoring/grafana/provisioning/datasources.yml`
**Steps:** 用 `${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD is required}` fail-fast 注入 grafana 环境变量。
**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- bash -c \
  'docker compose --profile core config | awk "/^  grafana:/,/^  [a-z]/" | grep -c CLICKHOUSE_PASSWORD'
# 期望 >= 1（需 Docker）
```
**Accept:** 数据源可用；未配置时 fail-fast 而非静默空口令。

---

### S-6 · 仅隔离管理员引导口令

> **`admin_email` 不得移除**：它是 SMTP 管理员通知收件人的 fallback
> （`config.py:265-267` `smtp_admin_to_effective`）。

**Files:** `docker-compose.yml`（`x-app-env`）、`deploy/.env.example`、`apps/api/app/core/config.py`
**Steps:**
1. `SOYMUTDB_ADMIN_PASSWORD` 从 `x-app-env` 移到**专用 `bootstrap-admin` one-shot 服务**
   （`profiles: ["bootstrap"]`、`restart: "no"`，命令 = `create_admin` CLI）。
   **不冻结到 `migrate`**：迁移容器的职责是 schema，不应兼管账号初始化。
2. `SOYMUTDB_ADMIN_EMAIL` **保留**在长驻服务环境中；在 `deploy/.env.example` 中把它的说明改为
   「SMTP 管理员通知收件人（运维联系邮箱，非凭据）」。
3. 保留 prod fail-fast 校验；`bootstrap-admin` 不在默认 `core` profile 内，需显式选择。

**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose --profile core config > /tmp/compose-rendered.yml
  awk "/^  api:/,/^  [a-z]/" /tmp/compose-rendered.yml | grep -c SOYMUTDB_ADMIN_PASSWORD   # 期望 0
  grep -c SOYMUTDB_ADMIN_EMAIL /tmp/compose-rendered.yml                                   # 期望 >= 1
'   # 需 Docker
```
**Accept:** 长驻容器环境无管理员引导口令；管理员通知邮件链路仍可用。

---

### S-7 · MCP 服务网络最小化（冻结为三条专用网络）

> **修正二轮审计：** v2 只写「保留 `local-mcp-proxy` + 新增到 api 的最小网络」，
> 移除 `default` 后 MCP **无法再解析 `redis:6379`**（限流需要），任务无法完成。

**Files:** `docker-compose.yml`（`mcp-server` 服务与 `networks:` 段）、`infra/nginx/conf.d/default.conf`
**Steps（**FZ-4**）：**
1. 定义三条专用网络：

   | 网络 | 成员 | 用途 |
   |---|---|---|
   | `mcp-proxy` | nginx ↔ mcp-server | nginx 转发 `/mcp` |
   | `mcp-api` | mcp-server ↔ api | 工具调用 REST |
   | `mcp-ratelimit` | mcp-server ↔ redis（**缓存实例，非 `redis-celery`**） | `SOYMUTDB_MCP_REDIS_URL` |

2. 从 mcp-server 移除 `default` 与旧的 `local-mcp-proxy`。
3. nginx 侧把 `mcp-local` 别名迁到 `mcp-proxy`。
4. **负向验证**：用专用脚本断言 MCP 无法连接 postgres / clickhouse / minio / redis-celery。

**Files（补充）:** 新增 `scripts/check_mcp_network_isolation.py`

> **三轮审计 S9：** v3 的内联 Python 片段把所有服务都测 5432 端口，
> 且未处理 DNS 不可解析（`socket.gaierror`）会异常退出。

**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose --profile core --profile mcp config > /tmp/c.yml
  awk "/^  mcp-server:/,/^  [a-z]/" /tmp/c.yml | grep -A8 "networks:"
'   # 期望：只出现 mcp-proxy / mcp-api / mcp-ratelimit，无 default
bash scripts/compose-fixture-env.sh -- bash scripts/mcp-transport-smoke.sh               # 需 Docker
bash scripts/compose-fixture-env.sh -- python3 scripts/check_mcp_network_isolation.py   # 需 Docker
```

`scripts/check_mcp_network_isolation.py` 的要求（**冻结**）：
- 按**真实端口表**逐一对 `(host, port)` 断言，不使用单一端口：

  | 服务 | 端口 | 期望 |
  |---|---|---|
  | `postgres` | 5432 | 不可达 |
  | `clickhouse` | 8123、9000 | 不可达 |
  | `minio` | 9000 | 不可达 |
  | `redis-celery` | 6379 | 不可达 |
  | `api` | 8000 | **可达** |
  | `redis`（缓存实例） | 6379 | **可达** |

- **DNS 不可解析（`socket.gaierror`）与连接被拒绝（`ConnectionRefusedError`）均判为「不可达」= 通过**；
  只有「TCP 连接成功」判为失败。
- 退出码：全部符合预期 → 0；任一不符合 → 非 0 并打印具体服务与端口。

**Accept:** MCP 仅能访问 api 与 redis 缓存；网络隔离由脚本断言，可复现。

---

### S-8 · readiness 信息面收敛

**Files:** `apps/api/app/api/v1/health.py`、`infra/nginx/*.conf`、`deploy/scripts/healthcheck.sh`
**Steps:** 匿名可达的 readiness 只返回聚合状态；依赖明细移到需内部鉴权的路径（如
`/api/v1/health/details`，要求 `AUDITOR`+）。`upgrade.sh` 的就绪轮询改用不泄露细节的端点。
**Verify:**
```bash
curl -s http://localhost:8080/api/v1/health/ready | grep -cE 'postgres|clickhouse|redis'   # 期望 0
curl -s http://localhost:8080/api/v1/health/ready | grep -c '"status"'                     # 期望 1
bash deploy/scripts/healthcheck.sh
```
**Accept:** 公网无依赖拓扑泄露；发布脚本仍能判定就绪。

---

### S-9 · `.trivyignore` 结构化 + 扫描面扩展

**Files:** `.trivyignore` → **`.trivyignore.yaml`**、`scripts/build-release-image.sh`、`docs/ops/dependency-governance.md`
**Steps（**FZ-5**）：**
1. 新建 `.trivyignore.yaml`（Trivy 兼容的结构化格式），把现有 40 条迁移为：
   ```yaml
   vulnerabilities:
     - id: CVE-2025-69720
       statement: "Debian 13 基础镜像，上游暂无修复版本；随基础镜像刷新复核"
       expired_at: 2026-12-31
   ```
2. `trivy_scan` 改为 `--ignorefile .trivyignore.yaml`，并扩展扫描面：`--scanners vuln,misconfig,secret`。
3. **过期条目自动失败**：Trivy 对 `expired_at` 已过的条目不再豁免；补一条门禁断言
   （`scripts/build-release-image.sh` 中检查 exit code，或在 governance 契约测试中断言无过期条目）。
4. 删除旧 `.trivyignore`（避免双份来源漂移）。

**Verify:**
```bash
test ! -e .trivyignore && test -e .trivyignore.yaml
bash scripts/build-release-image.sh   # 需 Docker
# 负向：把某条 expired_at 设为过去 → 期望 FAIL
```
**Accept:** 豁免可审计、会过期、不可静默累积；单一来源。

---

### S-10 · dev compose 端口绑定收敛

**Files:** `docker-compose.dev.yml`
**Steps:** 5173/5174/8080 绑定改为 `127.0.0.1`；云预览若确需外部可达，
用显式变量 `SOYMUTDB_DEV_BIND`（**默认 `127.0.0.1`**）并在文档说明风险与前提。
**Verify:**
```bash
bash scripts/compose-fixture-env.sh -- bash -c '
  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile core config | grep -E "0\.0\.0\.0"
'   # 期望无输出（需 Docker）
apps/api/.venv/bin/python -m pytest scripts/test_development_compose_contract.py -q
```
**Accept:** 默认不对外暴露开发服务。

---

## 4. 阶段内任务顺序

| 顺序 | 任务 | 理由 |
|---|---|---|
| 1 | W-1.1 | 工作树不干净，后续所有「不回退」承诺无效 |
| 2 | W-1.2 | Node 24 + git-lfs 是后续一切的门槛 |
| 3 | W-1.3 | 基线只在 Node 24 下才有意义 |
| 4 | C11 | 零风险，释放磁盘 |
| 5 | C4 | 依赖 git-lfs（W-1.2 已装） |
| 6 | C13 | 后续任务引用的命令由它守护；**必须在 S 组前建立**；负向用例放脚本单元测试（避免自触发） |
| 7 | S-0 | 后续所有 compose 命令的前提 |
| 8 | S-1 → S-2 | S-2 的限流键依赖 S-1 的可信对端 IP |
| 9 | S-3、S-4、S-5、S-6、S-7、S-8、S-9、S-10 | 相互独立，可并行 |
| 10 | §5 退出判据 | 阶段收口 |

---

## 5. 阶段退出判据

```bash
# 1. 安全回退防线
! grep -rn "forwarded-allow-ips=\*" deploy/ infra/
! grep -rn "0\.0\.0\.0/0" deploy/
python3 scripts/check_nginx_security_headers.py

# 2. 门禁与契约
python3 scripts/check_plan_commands.py
apps/api/.venv/bin/python -m pytest scripts/test_cloudflare_tunnel_contract.py -q
apps/api/.venv/bin/python -m pytest scripts/test_development_compose_contract.py -q
apps/api/.venv/bin/python -m pytest scripts/test_dockerfile_contracts.py -q
SOYMUTDB_SMOKE_PYTHON=apps/api/.venv/bin/python bash scripts/smoke.sh --profile contracts

# 3. 前端未回退
pnpm exec turbo run lint --force
pnpm typecheck
pnpm test
```

**需 Docker 的判据**（本机不可执行 → 由 CI 补验，标「未验证」）：
```bash
bash scripts/compose-fixture-env.sh -- bash scripts/ci-job-steps.sh run compose-acceptance
bash scripts/build-release-image.sh
```

**DoD 勾选项：**
- [ ] W-1.1 工作树干净 + 上一阶段 DoD 有结论
- [ ] W-1.2 Node 24.19.0 + git-lfs 就绪（或显式标未验证并阻断 C4）
- [ ] W-1.3 基线报告入库，含**全树** `SHA256SUMS`（非单个 index.html）
- [ ] C11 工作区体积下降 ≥300 MB
- [ ] C4 两份设计稿以 LFS 入库，且明确声明不宣称历史瘦身
- [ ] C13 门禁对当前计划 exit 0，三个负向用例变红
- [ ] S-0…S-10 全部关闭或登记为接受风险（理由 + owner）
- [ ] §5 无需 Docker 的命令全绿；需 Docker 项有 CI 补验路径

---

## 6. 风险与回滚

| 风险 | 触发条件 | 缓解 / 回滚 |
|---|---|---|
| W-1.2 无 Node 24 | 本机受限 | 标未验证并用 CI 补；不得据此做容量结论 |
| C4 未装 git-lfs | 工具链缺失 | 任务不开始；不得用「移到 docs/」代替 |
| C13 误报 | allowlist 不完整 | 白名单条目必须带 reason；不得放宽判定换绿灯 |
| S-2 fail-open 被利用 | 匿名读无限流 | 边缘 `limit_req` 是兜底；Phase 4 的 P2 验证 429 生效 |
| S-4 `proxy_hide_header` 失效 | location 未覆盖 | 门禁断言 `/api/` 的 location 必须有 hide 语句 |
| S-7 网络变更导致 MCP 不可用 | 遗漏 Redis 通路 | `mcp-ratelimit` 显式声明；`mcp-transport-smoke.sh` 验证 |
| S-9 迁移遗漏 CVE | 手抄错误 | 迁移前后条目数必须相等（40 条），门禁断言 |
| S-1 移除 `*` 取不到真实 IP | 部署未配可信网段 | 先文档化必需变量 + 预检报错，再移除兜底 |

**通用回滚：** 每任务独立 commit；高风险文件（`infra/nginx/**`、`docker-compose.yml`、
`.trivyignore.yaml`、`infra/docker/Dockerfile.api`）在 PR 中单列 diff。
