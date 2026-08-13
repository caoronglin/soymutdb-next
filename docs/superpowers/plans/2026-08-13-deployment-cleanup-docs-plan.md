# Deployment Cleanup and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将生产 Compose、备份恢复、升级回滚、CI/Pages 发布链与仓库清理调整到已批准规格，删除无消费者的 Rust/Tauri/旧搜索代码，并交付 user/ops/dev 三套可执行文档。

**Architecture:** 保留 API、worker、ClickHouse、PostgreSQL、MinIO、Redis、MCP 和 nginx 的容器主链；为 `analyses` 队列增加独立 worker，GWAS/分析对象统一由配置声明 bucket。部署以带显式 tag 的镜像和一次性迁移容器为边界，Pages 在同一次 orphan 发布中合并 web/admin/JBrowse 产物，避免互相 force-push 覆盖。

**Tech Stack:** Docker Compose, Bash, MinIO `mc`, PostgreSQL/ClickHouse, GitHub Actions, pnpm/Turbo, Vite/SSG, React Web Admin。

---

## 文件结构与所有权映射

### 新建

- `docs/user/README.md`：科研用户门户入口与 Gene ID、Location、BLAST、Primer、GBrowse、全局搜索、下载/引用指南。
- `docs/ops/README.md`：Admin 数据上线手册入口。
- `docs/ops/data-import-and-release.md`：7 类导入、校验、Release、原子发布、回滚、备份恢复、排障。
- `docs/dev/README.md`：开发者文档入口。
- `docs/dev/architecture-and-deployment.md`：架构、状态机、契约、幂等/审计、CI 门禁、部署拓扑、清理清单。

### 修改

- `docker-compose.yml`：gwas/analyses bucket、`worker-analyses`、镜像 tag、镜像内迁移脚本与服务依赖；保留现有未提交修改并逐段合并。
- `docker-compose.dev.yml`：开发栈与生产队列契约同步，明确单机开发可消费 `analyses`。
- `deploy/.env.example`：`S3_GWAS_BUCKET`、`S3_ANALYSES_BUCKET`、分析并发和 MCP/API/worker tag 示例。
- `deploy/scripts/backup.sh`、`restore.sh`、`verify-restore.sh`：默认 bucket 列表加入 `gwas`，并确保 manifest、镜像恢复和校验均覆盖该 bucket。
- `deploy/scripts/upgrade.sh`：修复停栈判定、步骤编号、manifest 预检、迁移顺序与全服务回滚。
- `deploy/scripts/migrate-clickhouse.sh`：支持迁移容器内固定路径，不再推导或依赖宿主仓库挂载。
- `infra/docker/Dockerfile.worker`：将 ClickHouse SQL、迁移 Python 库和迁移入口复制进 worker 镜像。
- `.github/workflows/ci.yml`：API/worker/MCP 显式 tag 自动推送，升级前 `docker manifest inspect` 预检，MCP 镜像构建/扫描/推送。
- `.github/workflows/pages.yml`：同一部署 job 合并 web/admin/JBrowse，发布 `dist-jbrowse` 到 `soymutdb-jbrowse/`，一次完成 orphan/force-push。
- `apps/web/public/_headers`：删除 Cloudflare Pages 专用文件，并注明 gh-pages 不解释该格式，安全头由托管层负责。
- `README.md`：更新 Web-only Admin、GitHub Pages、JBrowse、升级/备份入口与三套文档链接。
- 现有旧设计文档（至少 `docs/design/deployment-architecture.md`、与 Cloudflare Pages/Windows/Tauri/Rust 相关的文档）：在文首标注“历史属性/非当前主路径”，链接当前 dev/ops 文档；不删除仍有参考价值的新闻/about 生成说明。
- `package.json`、`apps/admin/package.json`、`turbo.json`、`pnpm-lock.yaml`：移除 Tauri/桌面/Rust 脚本、依赖和 desktop task；保留 Web Admin build。
- `apps/web/scripts/ssg-build.ts`：删除遗留 `search.html` 生成/发布路径（若仅由现有页面数组产生则保留新闻/about 及其他内容页生成链，不删除整个 SSG）。

### 删除

- `apps/core-rs/`：无消费者 Rust core。
- `deploy/windows/`：Windows 打包/服务链。
- `apps/admin/src-tauri/`：Tauri IPC、Rust 命令和桌面工程。
- `apps/admin/src/lib/tauri-api.ts`：Tauri-aware 客户端。
- `apps/web/src/lib/search-worker-client.ts`、`apps/web/src/workers/search.worker.ts`：死搜索 worker 客户端/worker。
- 与上述死链直接关联的 `tracks.ts`、`mutant-lines.ts`、`releases.ts` 死导出及 `filterSearchResults`/`sortResults`：只删除确认无引用的文件/导出，不触碰 api-client 死接口（留给搜索计划）。
- `apps/web/public/_headers`：Cloudflare Pages `_headers` 文件。

> **工作区安全边界：** 执行者不得覆盖、回滚、暂存或格式化其他已有改动。`docker-compose.yml`、`deploy/scripts/upgrade.sh`、`.github/workflows/ci.yml` 及 `_headers` 已有未提交修改；先读取当前内容，以最小补丁逐段合并。不得加入 commit/提交步骤；完成时只运行 `git diff -- <上述计划文件>` 审查本次改动，不执行其他 git 写操作。

### Task 1: 固化分析队列与对象存储契约

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml`
- Modify: `deploy/.env.example`
- Verify: `apps/worker/src/soymutdb_worker/main.py`, `apps/worker/src/soymutdb_worker/tasks/gwas.py`, `apps/worker/src/soymutdb_worker/tasks/analyses/fastp.py`, `apps/worker/src/soymutdb_worker/tasks/analyses/scanpy.py`

- [ ] **Step 1: 记录实际队列与 bucket 常量。** 确认 `main.py` 将 `tasks.analyses.*` 和 `tasks.gwas.*` 路由到 `analyses`，确认 GWAS 默认 `S3_GWAS_BUCKET=gwas`，fastp/scanpy 默认 `S3_ANALYSES_BUCKET=analyses`；不要把 gwas 错写成 analyses。
- [ ] **Step 2: 在生产 Compose 增加 MinIO bucket。** 将 `minio-init.entrypoint` 的创建命令扩展为：

```sh
/usr/bin/mc mb --ignore-existing local/gwas
```

同时在 `x-app-env` 增加 `SOYMUTDB_S3_GWAS_BUCKET: ${S3_GWAS_BUCKET:-gwas}` 与 `SOYMUTDB_S3_ANALYSES_BUCKET: ${S3_ANALYSES_BUCKET:-analyses}`，保留现有四个 bucket 和权限策略。
- [ ] **Step 3: 增加专用 `worker-analyses`。** 复制 worker 公共 image/build/dependency/environment/healthcheck 约定，命令使用：

```yaml
command: >
  celery -A soymutdb_worker.main:celery_app worker --loglevel=info
  --queues=analyses --concurrency=${WORKER_ANALYSES_CONCURRENCY:-2}
  --max-tasks-per-child=20 --hostname=worker-analyses@%h
```

该服务依赖 postgres、clickhouse、redis-celery、minio 健康及 `migrate` 成功；生产服务注释和连接预算同步包含第四个 worker。不得仅保留“后续再接入”的注释。
- [ ] **Step 4: 同步开发 Compose。** 开发 `worker` 可以继续合并队列，或改名为明确的 `worker-analyses` 专用服务；最终必须能以 `docker compose -f docker-compose.yml -f docker-compose.dev.yml config` 解析且 `analyses` 有消费者。
- [ ] **Step 5: 补环境模板。** 在 `.env.example` 加入：

```dotenv
S3_GWAS_BUCKET=gwas
S3_ANALYSES_BUCKET=analyses
WORKER_ANALYSES_CONCURRENCY=2
MCP_IMAGE_TAG=ghcr.io/soymutdb/mcp-server:2026.08.13-1
```

保留 API/worker 显式 tag，禁止裸 `latest`。
- [ ] **Step 6: 静态验证。** 运行 `docker compose --env-file deploy/.env.example config`；预期退出 0，输出包含 `worker-analyses`、`--queues=analyses`、`local/gwas` 和两个 S3 配置键。

### Task 2: 将 ClickHouse 迁移完全封装进 worker 镜像

**Files:**
- Modify: `infra/docker/Dockerfile.worker`
- Modify: `deploy/scripts/migrate-clickhouse.sh`
- Modify: `docker-compose.yml`
- Verify: `infra/clickhouse/upgrade_variant_facts_schema.sql`, `deploy/scripts/migrate_clickhouse_lib.py`

- [ ] **Step 1: 在 Dockerfile worker 复制迁移输入。** 在 worker 源码复制后加入：

```dockerfile
COPY deploy/scripts/migrate-clickhouse.sh /opt/soymutdb/migrate-clickhouse.sh
COPY deploy/scripts/migrate_clickhouse_lib.py /opt/soymutdb/migrate_clickhouse_lib.py
COPY infra/clickhouse/upgrade_variant_facts_schema.sql /opt/soymutdb/upgrade_variant_facts_schema.sql
```

并确保 runtime 用户可读、脚本的 Python import 路径可找到 `/opt/soymutdb/migrate_clickhouse_lib.py`。
- [ ] **Step 2: 改迁移脚本为镜像优先路径。** 将默认值固定为 `ROOT=/opt/soymutdb`、`SQL_FILE=${CH_MIGRATION_SQL:-${ROOT}/upgrade_variant_facts_schema.sql}`，lib 从 `${ROOT}/migrate_clickhouse_lib.py` 加载；保留 `CH_MIGRATION_SQL`/`CLICKHOUSE_MIGRATION_PYTHON` 覆盖能力供测试使用。
- [ ] **Step 3: 删除生产 compose 的宿主 bind mount。** `migrate-clickhouse` 只使用 worker image 内 `/opt/soymutdb/migrate-clickhouse.sh`，命令改为 `["bash", "/opt/soymutdb/migrate-clickhouse.sh"]`，不再挂载 `deploy/scripts/*` 或 `infra/clickhouse/upgrade_variant_facts_schema.sql`。
- [ ] **Step 4: 验证迁移输入和构建。** 运行 `bash -n deploy/scripts/migrate-clickhouse.sh`、`docker build -f infra/docker/Dockerfile.worker -t soymutdb-worker:plan-check .`；预期 shell 语法通过，镜像构建成功且 `docker run --rm soymutdb-worker:plan-check test -s /opt/soymutdb/upgrade_variant_facts_schema.sql` 返回 0。

### Task 3: 加固备份、恢复与恢复验证

**Files:**
- Modify: `deploy/scripts/backup.sh`
- Modify: `deploy/scripts/restore.sh`
- Modify: `deploy/scripts/verify-restore.sh`

- [ ] **Step 1: 更新默认 S3 bucket。** 三个脚本的默认列表至少为：

```bash
BAK_S3_BUCKETS="${BAK_S3_BUCKETS:-genomic-data user-tracks blast-dbs exports gwas}"
```

`analyses` 是否纳入由当前数据保留策略明确；本任务要求 `gwas` 默认必含，若 analyses 是临时可重建数据必须在脚本注释和 ops 文档写明而非静默遗漏。
- [ ] **Step 2: 保证恢复按 manifest 动态覆盖 gwas。** restore/verify 继续按 `s3_manifest.tsv` 的 bucket 集合循环，不写固定四 bucket 白名单；补显式断言或日志，让缺少 `gwas` manifest 时完整备份拒绝通过，而 `--skip-s3` 仍是明确跳过。
- [ ] **Step 3: 补 bucket policy 和对象清单边界。** backup 对 `gwas` 生成 mirror、policy、对象 SHA-256；restore 对 `gwas` 执行 `--overwrite --remove`；verify 对象数量、大小和 checksum 均覆盖 `gwas`。
- [ ] **Step 4: 静态验证。** 运行 `bash -n deploy/scripts/backup.sh deploy/scripts/restore.sh deploy/scripts/verify-restore.sh`，并运行 `grep -n 'gwas' deploy/scripts/{backup,restore,verify-restore}.sh`；预期三脚本语法通过且每个脚本有 gwas 路径。

### Task 4: 重写 upgrade 的预检、编号、停止判定和全服务回滚

**Files:**
- Modify: `deploy/scripts/upgrade.sh`
- Modify: `docker-compose.yml`
- Verify: `deploy/scripts/healthcheck.sh`, `deploy/.env.example`

- [ ] **Step 1: 统一步骤编号。** 采用连续 `[1/N]`，将配置、预检、manifest 预检、拉取、备份、停止/迁移、启动、readiness、smoke、记录等实际步骤逐一编号；输出编号不得仍出现 `[6/9]` 与 `[7/9]` 这种错位。
- [ ] **Step 2: 修复停栈判定。** 不以 `docker compose ps -q postgres` 是否有容器误判“正在运行”；使用明确状态检查，例如：

```bash
if "${COMPOSE[@]}" ps --status running --services | grep -qx postgres; then
    bash "${SCRIPT_DIR}/backup.sh"
else
    echo "No running postgres service - first deploy or stopped stack; skipping pre-upgrade backup."
fi
```

迁移前显式停止会被迁移/恢复影响的应用服务，不能停止后仍用旧容器存在性判断。
- [ ] **Step 3: 预检所有镜像 tag。** 检查 `API_IMAGE_TAG`、`WORKER_IMAGE_TAG`、`MCP_IMAGE_TAG` 非空且不以 `:latest` 结尾；对每个 tag 执行 `docker manifest inspect "$tag"`，任一失败立即退出，且预检发生在 stop/backup/migrate 之前。
- [ ] **Step 4: 扩展 pull/up 服务集合。** pull 和启动必须包含 `migrate-clickhouse`、`worker-analyses`、`mcp-server` 及所有 API/worker/beat 服务；Compose 中 MCP 增加 `image: ${MCP_IMAGE_TAG:?MCP_IMAGE_TAG is required}`，保留 build 供本地开发覆盖。
- [ ] **Step 5: 记录可回滚状态。** `.release-state.json` 至少记录 API、worker、MCP tag/digest、migration version、发布时间和本次服务集合；读取旧状态时不能用会吞掉空值的无界 `head` 管道掩盖缺失。
- [ ] **Step 6: 实现完整回滚函数。** readiness 或 smoke 失败时，使用旧 API/worker/MCP tag 恢复并 `up -d`：`api migrate worker-default worker-analyses worker-blast worker-ingest beat mcp-server nginx`；回滚前后处理 ClickHouse migration 状态，若新迁移不可逆则停止自动回滚并明确人工恢复门槛。回滚必须等待 API readiness、MCP healthcheck 和各 worker healthcheck，失败打印所有服务日志并退出非零。
- [ ] **Step 7: 验证 shell 静态契约。** 运行 `bash -n deploy/scripts/upgrade.sh`；以 `grep` 断言 `worker-analyses`、`mcp-server`、`migrate-clickhouse`、`docker manifest inspect` 和完整 rollback service list 均存在；预期全部匹配。

### Task 5: MCP 镜像 tag 与 CI 自动推送/升级预检

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy/.env.example`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: 统一 MCP 镜像地址。** Compose 使用与 GHCR 命名一致的 `MCP_IMAGE_TAG`，MCP Docker build context 保持 `apps/mcp-server`；不要让生产 compose 退回仅 build 无 tag。
- [ ] **Step 2: 添加 registry 登录和 tag 计算。** 在 `docker-build` job 使用 `docker/login-action` 登录 GHCR（push main 时使用 `GITHUB_TOKEN`），基于 commit SHA/日期生成不可变 `ghcr.io/soymutdb/{api,worker,mcp-server}:<tag>`，PR 仅 build/scan 不推送。
- [ ] **Step 3: 推送 API、worker、MCP。** 三个镜像均 build、tag、push；保留现有 JBrowse build 和 Trivy 门禁，MCP 至少执行同等 build/health/auth smoke。
- [ ] **Step 4: 增加升级预检。** CI 在可获得 tag 的发布路径运行：

```bash
for image in "$API_IMAGE_TAG" "$WORKER_IMAGE_TAG" "$MCP_IMAGE_TAG"; do
  docker manifest inspect "$image" >/dev/null
done
```

预期三个 manifest 均可读取；PR 若没有远端 tag，应仅运行本地 image smoke，不伪造“远端 manifest 已通过”。
- [ ] **Step 5: YAML 验证。** 运行 `python - <<'PY'` 使用 `yaml.safe_load(open('.github/workflows/ci.yml'))`，断言 `jobs.docker-build` 存在 build/push/manifest inspect 文本；预期退出 0。

### Task 6: Pages 单次原子发布 web/admin/JBrowse

**Files:**
- Modify: `.github/workflows/pages.yml`

- [ ] **Step 1: 保留同一 checkout/install/build 上下文。** 在现有 `deploy` job 内分别构建 `@soymutdb/web`、`@soymutdb/admin` 和 `@soymutdb/jbrowse`，或下载 CI artifact；不要创建三个各自 orphan/force-push job。
- [ ] **Step 2: 组装唯一发布目录。** 在 orphan checkout 前保存三个 dist，目录布局必须为：

```text
/
  web 产物（根站点）
  soymutdb-admin/  <- dist-admin
  soymutdb-jbrowse/ <- dist-jbrowse
```

web 根目录继续生成 `404.html` 和 `.nojekyll`；JBrowse 目录不得被 web 的 `404.html` 覆盖。
- [ ] **Step 3: 一次发布修订一次 force-push。** 在 orphan `gh-pages` 工作树中清理并复制三个产物，生成一个发布修订后执行一次 `git push origin gh-pages --force`；不要让并发 workflows 相互覆盖，保留 `concurrency.group: pages`。本计划不包含 Git 提交操作步骤。
- [ ] **Step 4: 发布前断言。** 在 force-push 前执行 `test -f soymutdb-jbrowse/index.html`、`test -f index.html`、`test -f soymutdb-admin/index.html`；并运行 web 的 news/about smoke，确保静态内容链未被删除。
- [ ] **Step 5: YAML 与文本验证。** 解析 workflow YAML，断言存在 `dist-jbrowse`、`soymutdb-jbrowse/`、单个 `git push origin gh-pages --force`；预期通过且不存在第二个 Pages 发布 job。

### Task 7: 删除 Cloudflare `_headers` 并清理遗留搜索/Tauri/Rust 链

**Files:**
- Delete: `apps/web/public/_headers`
- Delete: `apps/core-rs/`
- Delete: `deploy/windows/`
- Delete: `apps/admin/src-tauri/`
- Delete: `apps/admin/src/lib/tauri-api.ts`
- Delete: `apps/web/src/lib/search-worker-client.ts`
- Delete: `apps/web/src/workers/search.worker.ts`
- Modify: `Makefile`, `Cargo.toml`, `package.json`, `apps/admin/package.json`, `turbo.json`, `pnpm-lock.yaml`
- Modify/Delete: confirmed-unused `tracks.ts`, `mutant-lines.ts`, `releases.ts` exports and legacy `search.html` path

- [ ] **Step 1: 先做引用清单。** 用 `rg` 搜索每个待删路径、`@tauri-apps`、`tauri`、`core-rs`、`build-windows`、`filterSearchResults`、`sortResults` 和 `search.html`；仅对无生产/测试引用的项删除，api-client 的死接口 `getGeneTranscripts` 等不得在本任务删除。
- [ ] **Step 2: 删除桌面/Rust 构建入口。** 从根 `package.json` 删除 `dev:admin-desktop`、`build:admin-desktop`、`build:core`、`dev:core`；从 admin package 删除 `dev:desktop`/`build:desktop` 及所有 Tauri optionalDependencies；从 Turbo 删除 `build:desktop`；从 Cargo workspace 删除两个 member 并删除根 Cargo 文件；从 Makefile `.PHONY`、help/target 删除 `build-windows`。
- [ ] **Step 3: 清理锁文件。** 用 pnpm 在依赖声明已改后更新 `pnpm-lock.yaml`，确认没有 `@tauri-apps/*`、Tauri Rust package 或仅被桌面链使用的锁定条目；不得手工删除不相关依赖。
- [ ] **Step 4: 保留有效 SSG。** 从 `ssg-build.ts`/发布脚本移除遗留 `search.html`，但保留 `PAGES` 中 `index`、`about`、news/content 页面及正常 `dist/index.html` 重写；删除后运行 `pnpm --filter @soymutdb/web build`，预期 news/about smoke 仍通过。
- [ ] **Step 5: 处理 `_headers`。** 删除文件，并在 `README.md`、`docs/dev/architecture-and-deployment.md` 说明 gh-pages 不解析 Cloudflare Pages `_headers`；安全头由 GitHub Pages/自定义托管层配置负责，不把 Cloudflare 格式转换成虚假 gh-pages 配置。
- [ ] **Step 6: 静态清理验证。** `rg -n 'tauri|core-rs|build-windows|filterSearchResults|sortResults|search\.html' package.json apps packages Makefile turbo.json Cargo.toml pnpm-lock.yaml` 只允许历史文档/计划中的说明命中；生产源码无命中，且 `test -e apps/web/public/_headers`、`test -e apps/core-rs`、`test -e deploy/windows`、`test -e apps/admin/src-tauri` 均失败（文件不存在）。

### Task 8: 三套文档、README 与历史设计标记

**Files:**
- Create: `docs/user/README.md`
- Create: `docs/ops/README.md`
- Create: `docs/ops/data-import-and-release.md`
- Create: `docs/dev/README.md`
- Create: `docs/dev/architecture-and-deployment.md`
- Modify: `README.md` and relevant old design/Cloudflare docs

- [ ] **Step 1: 写 user 指南。** 以科研用户任务为索引，给出 Gene ID、Location、BLAST、Primer、GBrowse、全局搜索、下载和 citation 的入口、成功结果、无结果、error/retry、Release/version 说明；所有示例 URL 使用当前前端路由而非 `#`。
- [ ] **Step 2: 写 ops 手册。** 明确 7 类导入 FASTA/GFF3/VCF/BLAST DB/Seed/Expression/Homolog，逐类输入对象、校验、失败重试、Release 组装、ready 门槛、原子发布、理由/审计、回滚、backup/restore/verify 命令和常见故障；注明 gwas bucket 与 analyses worker 的实际名称。
- [ ] **Step 3: 写 dev 手册。** 覆盖目标架构、导入/发布状态机、OpenAPI 契约、`idempotency_key`、outbox/审计、CI 门禁和 manifest、Compose/Pages 拓扑、MCP/worker-analyses、清理清单；明确 api-client 死接口和发布领域模型不在本次清理范围。
- [ ] **Step 4: 更新 README。** 删除 native desktop/Rust 叙述，加入 `pnpm --filter ... build`、`docker compose`、`deploy/scripts/upgrade.sh`、三套 docs、Pages 子目录发布和 JBrowse URL 说明。
- [ ] **Step 5: 标记旧文档。** 对 Cloudflare、Windows、Tauri、旧部署设计文档加：`> 历史文档：非当前主路径；当前规范见 ...`，并修正当前入口链接；不删除 `news/about` SSG 内容文档。
- [ ] **Step 6: 文档静态验收。** 运行 `rg -n 'TODO|TBD|FIXME|待补|稍后' docs/user docs/ops docs/dev README.md`；预期命令无匹配。运行 `rg -n 'FASTA|GFF3|VCF|BLAST|Seed|Expression|Homolog|原子|回滚|gwas|worker-analyses' docs/ops docs/dev`；每个关键词均有命中。

### Task 9: 集成静态验证与本次改动审查

**Files:**
- Verify: all files listed above

- [ ] **Step 1: 解析 Compose。** 运行 `docker compose --env-file deploy/.env.example config`；预期 YAML 可解析，服务含 `worker-analyses`/`mcp-server`，迁移服务无宿主 SQL bind mount，MinIO init 含 gwas。
- [ ] **Step 2: 运行 shell 检查。** 若安装 shellcheck，运行 `shellcheck deploy/scripts/{upgrade,backup,restore,verify-restore,migrate-clickhouse}.sh`；预期无新增 error。无 shellcheck 时运行 `bash -n` 全集并记录工具缺失，不把跳过写成通过。
- [ ] **Step 3: 运行工作流 YAML 检查。** 使用 Python `yaml.safe_load` 解析 `.github/workflows/ci.yml` 和 `.github/workflows/pages.yml`；断言 CI 的镜像 push/manifest inspect 和 Pages 的单次 `gh-pages` push/JBrowse 目录存在。
- [ ] **Step 4: 运行前端/契约验证。** `pnpm install --frozen-lockfile`、`pnpm --filter @soymutdb/web build`、`pnpm --filter @soymutdb/admin build:web`、`pnpm --filter @soymutdb/jbrowse build`；预期 Web SSG 仍生成 index/about/news 内容，JBrowse/admin dist 存在。
- [ ] **Step 5: 扫描范围与占位符。** 运行 `rg -n 'latest|TODO|TBD|FIXME|https://api\.example\.com|#' docker-compose.yml deploy infra .github/workflows docs/user docs/ops docs/dev README.md`；预期生产镜像无裸 latest、计划新增文档无占位符，允许仅在明确历史文档或非链接注释中保留说明，并逐项人工确认。
- [ ] **Step 6: 审查本次改动。** 运行 `git diff -- docs/superpowers/plans/2026-08-13-deployment-cleanup-docs-plan.md`；预期 diff 仅包含本计划文件。本步骤只读审查，不执行 `git add`、`git commit`、`git reset`、`git checkout`、`git stash` 或 push。

## 规格逐条自审清单

- [ ] 第 5 节契约修复仍由搜索计划负责；本计划明确不触碰 api-client 死接口和发布领域模型，仅清理确认无消费者的旧 worker/Tauri/Rust/SSG 搜索链。
- [ ] 第 5 节 Tier 1/Tier 2 删除范围覆盖 `apps/core-rs`、`deploy/windows`、`build-windows`、Tauri、死客户端、死导出和遗留 `search.html`，同时保留新闻/about SSG。
- [ ] 第 7 节三套文档分别覆盖 user、ops、dev 的全部主题。
- [ ] 第 8 节覆盖 worker-analyses 或下线策略（本计划选择 worker）、gwas bucket、三脚本备份、upgrade 编号/停栈/全服务回滚、镜像内 SQL、MCP tag/CI、manifest inspect、JBrowse 同一次 Pages 发布、删除 `_headers`。
- [ ] 第 9 节验收由静态门禁、构建、文档检查和现有业务测试承接；没有把局部检查表述为完整生产验证。
- [ ] 占位符扫描完成；新增计划内容没有未决占位项；没有 Git 提交步骤；已有脏工作区文件使用逐文件合并策略。

## 已知风险

1. **已有未提交修改重叠：** `docker-compose.yml`、`deploy/scripts/upgrade.sh`、`.github/workflows/ci.yml`、`apps/web/public/_headers` 已被用户明确标记为脏文件。执行者必须先读后改，以小范围补丁合并，不能用生成器、格式化器或整文件替换覆盖现状；冲突无法判断时暂停并询问。
2. **Pages 同一次部署约束：** web/admin/JBrowse 必须在同一 workflow run、同一 orphan 工作树、同一次 commit/force-push 中发布；拆成多个 job 会让最后一个 orphan 分支删除前一个应用，拆成多个 workflow 会发生竞态覆盖。`concurrency: pages` 只能减少竞态，不能替代单次组装。
3. **迁移回滚风险：** ClickHouse schema 迁移可能不可逆；升级脚本不能声称能回滚数据库结构。遇到不可逆迁移失败，必须停在明确人工恢复门槛，并依赖刚生成的完整 PG/CH/MinIO 备份。
4. **GWAS 与 analyses bucket 不同：** GWAS 常量默认 `gwas`，fastp/scanpy 默认 `analyses`；bucket 创建和环境变量必须分别保留，不能用一个名字替换全部。
5. **SSG 删除风险：** 删除 `search.html` 时容易误删整个静态生成链；验收必须检查 `index.html`、`about.html`、新闻内容页面、sitemap（若当前构建生成）和 SPA fallback 仍存在。
6. **历史文档与当前配置漂移：** Cloudflare 文档保留历史属性后仍可能被误读为主路径；README 和 dev 文档必须明确 GitHub Pages/gh-pages 为当前静态发布入口。
