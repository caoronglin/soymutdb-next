# SoyMutDB 生产就绪（Production Readiness）—— 首版上线范围与 Go/No-Go 标准

> **状态**：本文是**首版生产上线（P0）的范围冻结与验收标准文档**，由 QA/验收工程负责维护。
> 本文只约束「我们要上什么、以什么标准放行」，**不虚构已经上线的能力**。凡是文中标注为
> `✅ 已上线`/`已实现` 的，都有对应源代码/配置/CI 事实支撑；凡标注为 `🎯 目标/待验证` 的，
> 是需要本轮各模块（build-release / frontend-platform / data-platform / ops-security）先完成、再由
> QA 验收后才会放行的。上线边界判定以本文件为准。

> **权威来源索引**（任何判断与本文件冲突时，以下列实际为准）：
> - `README.md`（当前架构、部署现状、快速上手）
> - `docs/dev/architecture-and-deployment.md`（目标架构、模型与状态机、不可变静态发布、CI/Compose/MCP 契约）
> - `docs/ops/data-import-and-release.md`（七类导入、Release 组装/发布/回滚、静态发布、备份恢复）
> - `docs/design/deployment-architecture.md`（历史/现状审计，含「遗留项与现状不符点」R1–R7）
> - `.github/workflows/ci.yml` / `pages.yml` / `e2e-smoke.yml`（实际 CI 门禁与 Pages 发布链路）
> - `docker-compose.yml` + `deploy/.env.example` + `apps/api/app/core/config.py`（生产变量与 prod fail-fast）
> - `apps/web/src/lib/deployment.ts`（DeploymentMode 与生产 origin 校验）
> - `apps/web/scripts/fallback-data.ts` / `generate-samples.ts` / `base-template.ts`（demo 占位数据边界）

---

## 0. 一句话结论

当前**公开可访问的站点是「GitHub Pages Demo」**（`https://caoronglin.github.io/soymutdb-next/`），
其构建使用 `VITE_DEPLOYMENT_MODE=demo`，内容来自内嵌占位/示例数据（`fallback-data.ts`，含 `SMDB-00001` 等
示例条目），**不是生产**。生产目标域名 `soymutdb.org` 目前**尚未上线**；「Staging」「Production」
两个环境在代码/配置层面已具备雏形（`APP_ENV ∈ {dev,staging,prod}`、prod fail-fast、CORS 精确白名单、
OCI digest 引用、blue/green 外部适配器合同），但对应真实后端、真实数据面与真实域名**本轮才能补齐并通过验收**。

---

## 1. 环境边界：GitHub Pages Demo / Staging / Production

> QA 判定「放行」的第一个前提是**把三者彻底区分开**，并确保生产构建路径与 Demo 构建路径**分离**。

| 维度 | ① GitHub Pages Demo（现状） | ② Staging（目标） | ③ Production（目标） |
| --- | --- | --- | --- |
| 状态 | ✅ **已上线**（公开，`main` 成功即由 `pages.yml` 发布） | 🎯 **目标**，本轮搭建，尚未作为真实 stage 验收 | 🎯 **目标**，`soymutdb.org` 域名**未上线** |
| Web 入口 | `https://caoronglin.github.io/soymutdb-next/`；`/soymutdb-admin/`；`/soymutdb-jbrowse/` | 待定（staging 前端 origin） | 生产前端 origin（见 §3） |
| API | `pages.yml`/CI 中 `VITE_API_BASE_URL=https://<owner>.github.io/<repo>/api/v1`（demo） | `api-staging.<domain>`（禁止连生产） | 生产 API origin，须命中 `SOYMUTDB_CORS_ORIGINS` 精确白名单 |
| 构建模式 | `VITE_DEPLOYMENT_MODE=demo`（CI 固定） | `VITE_DEPLOYMENT_MODE=production/standard`（严格模式，见 §5） | 同 Staging（严格模式） |
| 数据来源 | `fallback-data.ts` 内嵌示例（`SMDB-00001` 等） | 真实 staging 数据面 | 真实生产数据面（首版 Release） |
| 认证 | 公开 + 示例 | staging 账号 | 生产账号 |
| `APP_ENV` | `dev/demo` | `staging`（`config.py` 已支持 `Literal["dev","staging","prod"]`） | `prod`（fail-fast：缺失/示例值/短 JWT 直接拒绝启动） |
| 允许使用 | 对外展示、功能演示、摸鱼验证 | 联调、回归、发布演练 | 正式对外数据服务 |
| 是否可作为生产放行依据 | ❌ 否 | ✅ 是（E2E/回归证据） | ✅ 是（最终放行对象） |

**边界规则（QA 强制）：**

1. **Demo 构建与 Production 构建必须走分离路径**：`VITE_DEPLOYMENT_MODE=demo` 只能用于 Demo；
   Production 构建必须使用 `production` 严格模式，且**构建失败**当且仅当 API/JBrowse 未配置或使用了占位域名
   （由 `frontend-platform` 的 t5 实现，见 §5 门禁 G5）。
2. **`fallback-data.ts` 只允许出现在 Demo 构建**；Production 制品一旦出现 `SMDB-00001`、`api.example.com`、
   `localhost`、`change-me`、`demo` 等标记即**判定为不合格**（由 `scripts/check-production-artifact.sh` 扫描）。
3. **Staging 与 Production 的 `SOYMUTDB_CORS_ORIGINS` 各自独立维护**；preview/staging origin 不能混入生产白名单。
4. **禁止用 Demo 数据冒充 Release**：首版 Production 必须绑定真实 `release_id`，静态页带有 `X-SoyMutDB-Release`
   / `release_id`，且不能回退到内嵌示例数据。

---

## 2. 首版 P0 功能范围与明确不承诺

> P0 = 首版必须可用的功能。P0 之外的**不承诺**必须在页面/文档中明确，不能悄悄上线或误导用户。
> 下表以 `apps/web/src/routes/` 与 `apps/api/app/api/v1` 的**实际存在**为准。

### 2.1 P0 功能范围（首版承诺）

| # | 功能 | 前端路由 | 后端端点 | 数据来源（首版） | 放行门槛 |
| --- | --- | --- | --- | --- | --- |
| 1 | 门户首页 / 站点头 / 导航 | `/`（`index`、`about`、`help`、`guide`） | `/content/snapshot`、`/page-definitions/{route}` | 真实 Release 内容快照 | 首屏非 demo 占位 |
| 2 | 基因检索与详情 | `/genes`、`/genes/[id]` | `/genes`、`/genes/{id}` | PostgreSQL `genes` 表（单物种；经「受控真实数据种子/核心写入器」注入，见 G10/G11） | 返回真实基因记录、无 `SMDB-*` 占位 |
| 3 | 变异检索与统计 | `/variants`、`/search` | `/variants`、`/search`、popgen/stats 端点 | ClickHouse `variant_facts`（单一 `assembly_key=Wm82v4.0`；经受控真实数据种子/核心写入器注入，见 G10/G11） | 变体结果与统计一致、无多 assembly 混入 |
| 4 | 基因组浏览 | `/browser` | 数据面 `/data/*`（Range 支持） | JBrowse 轨道（该 assembly 的 bundle + 轨道文件） | JBrowse 能加载该 assembly 轨道、零 `Wm82.a4.v1` |
| 5 | BLAST | `/blast` | `/blast` | 首版**默认 BLAST DB**（`blast_default_db=williams82_cds`） | 对默认 DB 可命中并返回结果 |
| 6 | 下载/数据门 | `/downloads` | `/downloads`、`/data/*` | Release 导出的静态文件（含 checksum） | 下载文件存在且 checksum 命中 |
| 7 | Web-only Admin（受保护） | `/soymutdb-admin/` | `/admin/*`（JWT + 角色） | 生产账号 | 登录成功、权限正确、审计写入 |
| 8 | 数据导入/发布（首版已知链路） | Admin「Data Imports」 | `/admin/imports`、`/admin/publication/*` | Module TSV `module_tsv` → `module_data_rows`（**write-only** 暂存，不供门户读取）+ 静态发布 | 导入→校验→发布闭环可用 |
| 9 | 不可变静态发布 | Admin「Publication」 | `/admin/publication/request` | `local`/`github_pages` 目标 | 发布产物 manifest/SHA-256 校验通过 |

> **数据注入关键事实（对齐 `data-platform`(t3) `docs/ops/first-release-data-plan.md` §5，QA 已按源代码核验）：**
> - 门户 `/genes`（`gene_service.py`）读取 **PostgreSQL `genes` 表**；`/variants` 读取 **ClickHouse `variant_facts`**。
> - 唯一真实写入的导入适配器是 `module_tsv`（`ModuleTsvAdapter`），它写入 **`module_data_rows`**——该表当前
>   **write-only**，仓库内无任何 API/worker 消费者，**并不回填门户所读的 `genes` 表**。
> - 其余 7 类导入（`fasta/gff3/vcf/blast_db/seed_data/expression_csv/homolog_csv`）适配器全部 `raise UnsupportedImportError`；
>   `import_vcf` **fail-closed**；`import_gff3`/`import_mutant_lines` 仅计数**不写库**。
> - **结论**：首版「真实基因/变异数据」**无法经现有 import 管线进入门户所读的库表**。首版数据面必须通过
>   **路线 B（受控真实数据种子脚本，推荐）** 或 **路线 A（补齐核心写入器）** 注入，并绑定 `release_id`。
>   `module_tsv` 仍可承载 Admin 多格式导入的「导入→校验→发布」闭环，但**不作为门户基因/变异数据的来源**。
>   详见 t3 文档 §5.3（收口路径 A/B）。

### 2.2 明确不承诺（首版范围外，不作为放行前提）

> 以下能力**存在代码骨架/占位**，但首版**不保证真实可用**。必须在 UI 中隐藏或明确标注「即将开放」，
> 且前端/Admin 不得让用户误以为已可用。

| 类别 | 字段/入口 | 首版处理 |
| --- | --- | --- |
| 多物种 | 多物种门户（非大豆） | 首版仅大豆单物种；其他物种入口隐藏或置灰 |
| 多 assembly | 多基因组比对（multi-genome BLAST / 轨道堆叠） | 首版仅单一 assembly；多 assembly 视图隐藏 |
| FASTA / GFF3 / VCF 导入 | Import Studio 的 FASTA/GFF3/VCF 类型 | **真实写入未闭环** → 在 Admin 创导入时按能力隐藏（见 `features`/`imports-capabilities`） |
| BLAST DB / Expression / Homolog / Seed 导入 | 对应导入类型 | 同上，按能力隐藏；不作为首版数据承诺 |
| GWAS | GWAS 数据（`gwas` bucket） | 首版可保留 bucket 但**不承诺可查询**；`analyses` 类似 |
| 分析流水线 | fastp/scanpy 等 analyses | 可运行 worker，但不承诺首版出公开结果 |
| 通知 | 站内/邮件通知 | 默认关闭（`smtp_enabled=false`） |
| MCP 外部访问 | `/mcp/*` | 生产 profile 可选；有 token 鉴权，但**未承诺**面向外部提供 |
| 桌面壳 / 原生客户端 | Tauri/rust 热路径 | **已清理移除**，不存在 |
| 多语言 | i18n 中/英 | 已有 `packages/i18n-core`（`packages/i18n` 已移除），不作为 P0 硬门禁 |

> **说明**：以上「不承诺」并非说代码不存在，而是指**首版上线验收不要求其可用**，且**不得用占位数据
> 冒充真实数据**。`frontend-platform`(t5/t6) 与 `data-platform`(t3) 负责在生产构建/前端将 demo 内容与
> 未实现类型隐藏，QA 以「生产制品无占位标记 + 未实现导入类型不可操作」作为通过依据。

---

## 3. 生产域名与访问边界

> 目标生产域名 `soymutdb.org` 目前**仅作为 canonical/`VITE_SITE_URL`/帮助邮箱等静态引用出现**，
> **尚未注册/配置上线**（`grep soymutdb.org` 只命中 `fallback-data.ts`、`ssg-build.ts`、`generate-samples.ts`
> 与帮助页邮箱等；`deploy/.env.example`、`config.py`、`docker-compose.yml` 均无真实生产域名）。
> 以下为**目标边界**，须由 `ops-security`(t2) 与 `build-release`(t4) 落地并给出证据。

### 3.1 对外暴露的入口（生产目标）

| 服务 | 目标入口 | 认证 | 部署方式 |
| --- | --- | --- | --- |
| 公共门户（Web） | `https://www.soymutdb.org/`（目标）或 GH Pages 生产子路径 | 公开 | 静态托管（GH Pages 生产或 CF Pages） |
| Admin（受保护 origin） | `https://admin.soymutdb.org/` **独立受保护 origin** | 生产账号 + 网络策略/独立 origin | 静态托管 + 受保护 Admin API（JWT） |
| 基因组浏览 | `https://jbrowse.soymutdb.org/`（目标）或 `soymutdb-jbrowse/` 子路径 | 公开 | 静态资产 |
| API | `https://api.soymutdb.org/`（目标） | Bearer / refresh cookie | 自管 Nginx → FastAPI（compose） |
| 数据文件 | `https://data.soymutdb.org/` 或 API `/data/*` | 公开（Range 支持） | 自管 Nginx → MinIO `genomic-data` |
| MCP（可选） | `https://api.soymutdb.org/mcp/` | `SOYMUTDB_MCP_API_TOKEN` | 自管 Nginx → mcp-server |

> **注意**：`apps/web/.env.example` 给出的生产占位是 `https://api.example.com`、`https://jbrowse.example.com`，
> CI 构建点名的 `https://api.soymutdb.test` / `https://jbrowse.soymutdb.test` 均为**测试/占位域名**，
> **禁止**作为生产值。真正生产值以 `deploy/.env.example` 为模板、由 `ops-security`(t2) 的
> `deploy/scripts/gen-prod-secrets.sh` **生成/预检**（写入 `/opt/soymutdb/.env`，0600，不含占位/开发默认值），
> 且**绝不把真实 secret 提交进仓库**。安全清单与 24 项边界见 `docs/ops/production-security-checklist.md`（t2），
> 认证表见 `docs/ops/production-security-certification-template.md`（t2）。

### 3.2 不该暴露的边界（生产必须收在内部）

| 服务 | 默认端口 | 暴露策略 |
| --- | --- | --- |
| PostgreSQL | 5432 | 仅 `localhost`/内网；**禁止公网** |
| ClickHouse | 8123 / 9000 | 仅 `localhost`/内网 |
| Redis / redis-celery | 6379 / 6380 | 仅回环；redis-celery 可仅宿主回环供 conda 混合 |
| MinIO S3 | 9001 | 内网/运维 VPN；`genomic-data` 桶经 Nginx `/data/*` 公开但仍需精确 origin/策略 |
| MinIO 控制台 | 9002 | 内网/运维 VPN |
| Grafana | 3000 | 内网；生产凭据必须修改 |
| Prometheus | 9090 | 内网；**禁止公网** |
| API 直连 | 8010 | 仅 compose 内网，公网一律经 Nginx 8080 |

**防火墙/入口规则**：对外仅放行 80/443（经 Nginx / 反向代理）；`8080` 是自管 Nginx 唯一对外入口，
如需直连该端口须确认代理层已上 TLS。数据库/缓存/监控全部只对内。

### 3.3 生产安全结论（QA 放行前提，详见 ops-security t2）

- `SOYMUTDB_JWT_SECRET` ≥ 32 字符、非示例值；`SOYMUTDB_CORS_ORIGINS` 为精确 origin 列表，**不含 `*`**
  （带凭据 CORS + HttpOnly refresh cookie）。缺失/示例/短 JWT 时 `APP_ENV=prod` **拒绝启动**（fail-fast）。
- Cookie 生产为 `Secure`；`SameSite` 边界符合登录/刷新流。
- CSP：生产 `script-src 'self'`（第三方库全部本地打包）；`connect-src` 仅允许生产 API origin；
  `frame-src` 仅允许 JBrowse origin。
- Admin 使用**独立受保护 origin**，不经过公共 API Tunnel。
- 所有镜像引用使用 `*_IMAGE_REF=image@sha256` digest，**禁止 tag 回退**（`upgrade.sh` 拒绝非 digest）。

---

## 4. 正式上线 Go/No-Go 清单

> 本清单是 QA 的**放行关口**。每一项通过后才能在验收单上打 ✅；**任一 P0/安全门槛为 ❌，整体 No-Go**。
> 每一项给出「证据要求 + 负责人 + 佐证工件」，以对应本轮各模块的任务（t2/t3/t4/t5/t6）为输入。
> 清单按「必须先于后」的依赖顺序编号，Gate 之间含明确依赖。

### 4.1 Release 冻结与版本（先决）

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G0 | 首版 Release 命名与数据范围冻结 | 见 §5；`release.version` 唯一、`assembly` 单一 | qa-acceptance + data-platform | `docs/ops/first-release-data-plan.md`（t3） |

### 4.2 构建与工具链

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G1 | 统一 Docker/Node/pnpm/uv 工具链 | Node 26.10.0、pnpm 11.21.0、uv 固定版本；全部 Dockerfile 一致；无重复/陈旧 Dockerfile | build-release | 变更文件清单 + 验证（t4） |
| G2 | `docker compose config` 全部 profile 通过 | `core,blast,analyses,mcp`（+可选 `jbrowse`,`cloudflare-tunnel`）配置均合法 | build-release | CI compose config 输出（t4） |
| G3 | shellcheck / `bash -n` 通过 | `deploy/scripts/*.sh`、`scripts/*.sh` 静态检查无错 | build-release | 本地+CI 输出（t4） |

### 4.3 生产构建模式（硬门禁）

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G5 | 生产严格模式构建 | `VITE_DEPLOYMENT_MODE=production` 时 API/JBrowse 未配置或占位 → **构建失败**；禁止 fallback-data；禁止 `SMDB-00001`/demo；绑定真实 `release_id`；生成 `manifest.json` + SHA-256 | frontend-platform | `check-production-artifact.sh` 扫描结果 + 构建（t5） |
| G6 | 生产制品无占位标记 | `scripts/check-production-artifact.sh` 对 dist 扫描 `api.example.com`/`localhost`/`SMDB-00001`/`demo`/`change-me` 等 → 零命中 | frontend-platform | 扫描日志（t5） |

### 4.4 Admin/JBrowse 与生产 E2E

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G7 | Admin/JBrowse 子路径/独立 origin | `apps/admin/config/config.ts` 与 `apps/jbrowse/config/config.ts` 通过 Umi `base`/`publicPath` 支持 `VITE_BASE_URL`；React replatform 产物及 origin 隔离待构建验证 | frontend-platform | 配置 + 双站/子路径构建验证（t6，待迁移完成） |
| G8 | 生产 E2E 硬门禁 | `e2e/playwright-production.config.ts` + production spec：不接受 API 404/405、不接受示例数据、不接受 localhost/example.com、必须验证真实 Release/JBrowse/Admin 登录 | frontend-platform | 本地/CI E2E 结果（t6） |
| G9 | Demo 与生产 E2E 分离 | 公开 Demo smoke 与生产 E2E 分开，生产 E2E 跑在 staging/production | frontend-platform | workflow 拆分（t6） |

### 4.5 数据面与 Release 数据

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G10 | 首版真实数据范围冻结 | 仅大豆单物种、单一 `assembly=Wm82v4.0` 的最小数据集；真实基因/变异数据经「受控真实数据种子(路线B)」注入（**非** module_tsv/路线A），写入 `genes/transcripts/exons/gene_aliases` + `variant_facts`，绑定 `release_id`/`release_key`，并满足设计 §6 的 D/C/P 校验（D1/D2/C1–C5/P1–P2）。**前置**（设计 §11，未冻结则 G10 维持 No-Go）：①权威数据源与版本/许可（Wm82v4.0 FASTA/GFF3/VCF）；②`mutants.tsv`↔VCF 样本名映射；③CH `variant_facts` 已按 `upgrade_variant_facts_schema.sql` canonical 迁移；④启用 `--write` 写库适配器（depends ①②③ + 授权）。**注**：④已部分完成——loader 真实解析+校验+`--check`/`--plan`/`--emit-sql` 已实现（`scripts/seed_release_data.py`，t16），仅 `--write` PG/CH 插入 + data_sets/provenance/release_data_sets + 置 ready 待数据源冻结+授权后启用 | data-platform | `docs/ops/route-b-seed-data-design.md`（t12，§1–§11）+ `scripts/seed_release_data.py`（t16 loader）+ `scripts/seed-release-data.sh`。证据：`data-query/seed-<release_id>.log` + `seed-manifest.json` + `provenance` 查询（`--check`/`--emit-sql` 可先出 `seed-manifest.json`+`variant_facts.sql`） |
| G11 | 数据导入写入器收口 | 未实现类型（FASTA/GFF3/VCF/BLAST DB/expression/homolog/seed）在 API 拒绝(422) + Admin 隐藏/不可操作；`module_data_rows` 为 write-only 不供门户；首版门户基因/变异数据由受控种子(路线B)注入（非 module_tsv） | data-platform | `scripts/validate-release-data.sh`（G11 段：`imports.*` 应 false/absent）+ 能力开关/UI 验收（t3 §5、t8） |
| G12 | 查询验证 | Gene/Variant/分布/下载/JBrowse 查询满足验收标准与示例命令；`assembly` 归一 `Wm82v4.0`、数据面/制品零 `Wm82.a4.v1` 与零 `SMDB-*` | data-platform | `scripts/validate-release-data.sh`（D1–D4/C1–C6/P1–P3，任一 FAIL 退出码=1）输出 → `acceptance/data-query/validate-release-<release_id>.log`（t7） |

### 4.6 运维与安全

| Gate | 描述 | 通过标准 | 负责人 | 证据 |
| --- | --- | --- | --- | --- |
| G13 | 生产环境变量与 secret 管理 | 必填变量齐全、secret 不进仓库/前端/VITE、CORS 精确、JWT 轮换、MCP 关闭策略、Cookie Secure/SameSite、CSP/CSRF 边界；`gen-prod-secrets.sh` 生成/预检通过 | ops-security | `deploy/scripts/gen-prod-secrets.sh` + `docs/ops/production-security-checklist.md`（t2） |
| G14 | 备份与恢复 | `backup.sh`/`restore.sh`/`verify-restore.sh` 全 PASS；drill 演练通过 | ops-security | 备份+恢复证据（t2） |
| G15 | 监控与告警 | Prometheus/Grafana + 告警规则（磁盘、服务健康、备份失败）就绪 | ops-security | 监控规则 + 截图（t2） |
| G16 | CORS/域名白名单 | 生产前端 origin 精确命中生产 `SOYMUTDB_CORS_ORIGINS` | ops-security | CORS 验证（t2） |

### 4.7 总判定

| Gate | 描述 | 通过标准 |
| --- | --- | --- |
| G-GO | **Go/No-Go 总判定** | 上述 G0–G16 全部 ✅；无未豁免的 `example`/`test`/`localhost` origin；无未豁免占位数据；无未修复的硬门禁失败；生产备份恢复演练通过；生产 E2E 全绿 |

**No-Go 触发条件（任一即否决）：**

- 生产构建仍使用 `VITE_DEPLOYMENT_MODE=demo` 或 `fallback-data.ts`/`SMDB-00001` 进入生产制品。
- 生产 API 指向 `example.com`/`localhost`/`.test` 占位域名，或未命中 `SOYMUTDB_CORS_ORIGINS` 精确白名单。
- `SOYMUTDB_JWT_SECRET` 为示例/短于 32 字符，或 CORS 含 `*`（`config.py` prod fail-fast 会拒绝启动）。
- 首版 Release 含多物种/多 assembly 数据，或用占位数据冒充真实数据。
- 首版门户 `/genes`、`/variants` 数据仍由 `module_tsv`/`module_data_rows`（write-only，无消费者）冒充，或未经
  **受控真实数据种子(路线B)**/**核心写入器(路线A)** 注入真实库表并绑定 `release_id`。
- 数据面/制品出现 `Wm82.a4.v1` 或 `SMDB-*`（assembly 未归一 / 占位未清除）。
- 任一 P0 门禁（G5/G6/G8/G12/G13/G14）失败且无书面豁免。
- 备份恢复演练未通过，或生产镜像引用非 digest（tag 回退）。
- 生产 E2E 出现 API 404/405、示例数据、localhost/example.com 命中。

---

## 5. 首版 Release 命名与数据范围

> 与 `data-platform`(t3) 的 `docs/ops/first-release-data-plan.md` 保持一致。本条为 QA 冻结的标准字段。

### 5.1 命名（对齐 `Release` 模型：`version` 唯一 String(32)，`name` String(256)）

| 字段 | 首版值（建议） | 说明 |
| --- | --- | --- |
| `version` | `0.1.0` | 语义版本，**唯一**，首版从 0.1.0 起；后续发布递增 |
| `name` | `SoyMutDB 0.1.0 — Glycine max (Williams 82) Wm82v4.0` | 人类可读，含物种 + 品系 + assembly |
| `assembly` | `Wm82v4.0` | **单一**；见下「名称归一强制项」，生产数据面/制品必须**零 `Wm82.a4.v1`** |
| `species` | `Glycine max` | 大豆，单物种 |
| `default_blast_db` | `williams82_cds` | `config.py` `blast_default_db` |
| `default_assembly` | `Wm82v4.0` | `VITE_DEFAULT_ASSEMBLY` |

> **名称归一强制项（G12 一致性校验必须通过）**：生产数据面/前端 `default_assembly` 统一为 **`Wm82v4.0`**。
> `apps/web/scripts/fallback-data.ts` 中的示例条目（`SMDB-00001`…，`referenceGenome: "Wm82.a4.v1"`）属于
> **Demo 占位**，只允许出现在 `demo` 构建；**生产数据面/制品中 `Wm82.a4.v1` 与 `SMDB-*` 必须零命中**
> （由 `scripts/check-production-artifact.sh` 扫描 + `first-release-data-plan.md` §6 D2/C6 校验）。
> 首版生产查询固定 `release_id`/`X-SoyMutDB-Release`，不得静默切换其它 release。

### 5.2 数据范围（P0 最小数据集——只含下列，其余不承诺）

| 数据类 | 内容 | 来源/版本 | 许可 | 校验 |
| --- | --- | --- | --- | --- |
| 基因（包含注释/别名） | PostgreSQL `genes` 表（含 `transcripts`/`exons`/`gene_aliases`） | 官方/引用来源 + 版本（经**受控真实数据种子或核心写入器**注入，见 G10/G11） | 记录许可 | 行级校验 + checksum + 零 `SMDB-*` |
| 变异（含坐标/效应） | ClickHouse `variant_facts`（单一 `assembly_key=Wm82v4.0`；需 canonical schema 迁移） | 单一 assembly 的变异集 + 版本（经受控种子/核心写入器注入） | 记录许可 | 坐标范围 + 统计一致 + 零混入其它 assembly |
| 统计/分布 | 染色体/assembly 统计（密度、计数） | 由上述基因/变异派生 | — | 与明细一致 |
| 下载 | Release 导出静态文件 | 上述数据的导出 + checksum | 记录许可 | `sha256` 清单命中 |
| JBrowse 轨道 | 该 assembly 的 bundle + 轨道文件 | 上述基因/变异对应轨道 | — | 浏览器可加载对应 assembly 轨道 |

### 5.3 首版关闭/隐藏的导入类型

> 这些类型的**真实写入链路首版未闭环**，必须在 Admin「Data Imports」/能力开关里隐藏或「即将开放」，
> 不得让用户操作后得到失败/占位结果：

`FASTA`、`GFF3`、`VCF`、`BLAST DB`、`Expression`、`Homolog`、`Seed`（对应 `docs/ops/data-import-and-release.md` 的七类导入）。

处理规则：按 `capabilities`/feature flag 在 Admin 隐藏（`frontend-platform`/`data-platform`）；QA 以
「无法在生产 Admin 触发这些类型的真实写入」为通过依据。

> **数据获取与导入证据**由 `data-platform`(t3) 提供；QA 只冻结范围与验收标准，不负责数据源本身。

---

## 6. 证据归档要求

> QA 需要**可复查、可追溯、带时间戳与哈希**的证据。所有证据统一归档，避免「口头通过」。

### 6.1 归档目录（约定）

```
docs/ops/acceptance-current-state.md  # 受跟踪的验收当前状态汇总（判定状态权威副本，t17）
docs/ops/production-readiness.md      # 本文件（范围与标准，常驻）
docs/ops/first-release-data-plan.md   # t3：首版数据范围（data-platform）
docs/ops/route-b-seed-data-design.md  # t12：Route B 受控真实数据种子设计（data-platform）
deploy/scripts/gen-prod-secrets.sh    # t2：生产 .env 生成/预检（写出 /opt/soymutdb/.env）
docs/ops/production-security-checklist.md                     # t2：环境变量/秘密/24 项边界清单
docs/ops/production-security-certification-template.md        # t2：上线安全认证表模板
# ↓ artifacts/acceptance/ 为 gitignored，仅存【运行期证据】（日志/报告/manifest）；
#   判定状态以 docs/ops/acceptance-current-state.md 为准；目录可能被环境重置，关键证据可另在 docs/ops/ 留一份。
artifacts/acceptance/
├── README.md                         # 证据归档根索引（目录装载内容 + 归档纪律）
├── go-no-go.md                       # 放行判定总表（G0–G16 逐项 ✅/❌ + 结论）
├── build/                            # G1–G3 构建/工具链证据（日志、输出）
├── production-build/                 # G5–G6 生产构建制品 + check-production-artifact 扫描
├── e2e-production/                   # G8–G9 生产 E2E 报告
├── data-query/                       # G10/G11/G12 查询验证（validate-release-data.sh 输出 validate-release-<rid>.log；种子 seed_release_data.py 输出 seed-<rid>.log + seed-manifest.json + variant_facts.sql）
├── security-env/                     # G13 环境变量/secret/CORS/CSP 检查
├── backup-restore/                   # G14 备份恢复 + drill 证据
├── monitoring/                       # G15 监控告警规则 + 截图
└── checksums/                        # 每类证据对应的 SHA-256 清单
```

### 6.2 归档清单（逐 Gate 证据）

| Gate | 必需证据 | 形式 | 归档 |
| --- | --- | --- | --- |
| G0 | 首版 Release 命名 + 数据范围定稿 | markdown | `docs/ops/first-release-data-plan.md` |
| G1–G3 | Dockerfile 统一 diff + `docker compose config` + `shellcheck`/`bash -n` 输出 | 日志/输出文件 | `acceptance/build/` |
| G5–G6 | 生产构建日志 + `check-production-artifact.sh` 输出（零命中） | 日志 | `acceptance/production-build/` |
| G7 | admin `vite.config.ts` 的 `VITE_BASE_URL` 配置 + 构建 | 配置片段 + 构建 | `acceptance/production-build/` |
| G8–G9 | playwright production 配置 + 执行报告 | HTML/JSON 报告 | `acceptance/e2e-production/` |
| G10–G12 | 数据范围 + 导入类型隐藏 + 查询验证 | `scripts/validate-release-data.sh`(t7) 输出 + 种子脚本 `scripts/seed_release_data.py`/`seed-release-data.sh`(t16) 输出 `seed-<rid>.log` + `seed-manifest.json` + `provenance` 查询 | 默认 `acceptance/data-query/`；**建议 `SOYMUTDB_EVIDENCE_DIR=docs/ops/evidence/`（受跟踪）**（`validate-release-<rid>.log` + `seed-<rid>.log` + `seed-manifest.json` + `variant_facts.sql`） |
| G13 | `gen-prod-secrets.sh`（--check/--compose-preflight）输出 + 必填/禁止清单 + 安全清单 | 脚本输出 + markdown | `acceptance/security-env/` |
| G14 | 备份 + 恢复 + verify-restore 全 PASS + drill | 日志 + 校验输出 | `acceptance/backup-restore/` |
| G15 | 告警规则 + 服务健康 + 探活结果 | 规则文件 + 截图 | `acceptance/monitoring/` |
| G16 | 生产前端 origin 命中 `SOYMUTDB_CORS_ORIGINS` 的验证 | 日志/curl 输出 | `acceptance/security-env/` |

### 6.3 归档纪律（QA 强制）

1. **带哈希**：每个构建/制品/备份记录 `sha256`；发布制品必须含 `manifest.json`（逐文件 SHA-256）。
2. **带时间戳**：关键步骤记录 UTC 时间，便于回溯发布顺序。
3. **可复现**：证据应附可执行命令或脚本路径，避免「手工点过」无法复查。
4. **不得覆盖**：敏感值在证据中 redact；真实 secret 绝不进证据/仓库。
5. **一人一签**：放行判定（Go/No-Go）由本 QA（qa-acceptance）在 `go-no-go.md` 签字并注明日期/commit。
6. **失败即留痕**：任一 Gate 失败，归档其失败日志，作为 No-Go 或整改依据。
7. **持久证据目录（QA 强制）**：`artifacts/acceptance/` 被 gitignored、跨轮次可能被环境重置。运行种子/查询验证脚本时用
   **`SOYMUTDB_EVIDENCE_DIR=<持久目录>`**（推荐 `docs/ops/evidence/`，受 Git 跟踪）覆盖默认的
   `artifacts/acceptance/data-query/`，使 `seed-<rid>.log`、`seed-manifest.json`、`variant_facts.sql`、
   `validate-release-<rid>.log` 落在持久目录，避免重置丢失（两脚本已支持该覆盖）。

---

## 7. QA 放行流程（如何从本清单走到 Go/No-Go）

1. 收集 `acceptance/` 下各 Gate 证据（依赖 build-release / frontend-platform / data-platform / ops-security 交付）。
2. 逐项比对 §4.2–4.6 的「通过标准」，判定 ✅/❌；任一 P0/安全门槛失败 → 记 No-Go 触发条件并通知 captain。
3. 汇总写入 `acceptance/go-no-go.md`，给出**总判定（Go / No-Go / Conditional-Go）**。
4. Conditional-Go 仅允许「已书面豁免的非 P0 缺口」，且必须列出豁免清单、风险、回填计划与负责人。
5. 全部 ✅ 且无未豁免缺口 → Go；否则 No-Go。Go/No-Go 结论回传 captain（agent_teams_send_message）。

---

## 8. 当前事实核验清单（避免虚构）

以下为撰写本文时（`main` = `460b1529f`）的**实际**状态，供审计对照：

- ✅ 公开 Demo 已上线：`https://caoronglin.github.io/soymutdb-next/`（含 `/soymutdb-admin/`、`/soymutdb-jbrowse/`）。
- ✅ CI 生产构建当前使用 `VITE_DEPLOYMENT_MODE=demo`（`ci.yml` frontend job），即**当前 CI 产物是 Demo 路径**。
- ✅ `apps/web/scripts/fallback-data.ts` 含示例 `SMDB-00001` 及 `Wm82.a4.v1`，仅允许 demo 构建。
- ✅ `apps/web/src/lib/deployment.ts` `DeploymentMode = "standard" | "demo" | "minimal"`——**尚无 `production` 严格模式**
  （由 `frontend-platform` t5 扩展）。
- ✅ `apps/api/app/core/config.py`：`APP_ENV ∈ {dev,staging,prod}`；`prod` 对 CORS/JWT/示例值 fail-fast。
- ✅ `Release` 模型：`version` 唯一 String(32)，`name` String(256)，`assembly` String(128)，状态
  `draft→validated→ready→published→rolled_back`。
- ✅ OCI 交付合同（ADR-0001）：生产只接受 `*_IMAGE_REF=image@sha256`；blue/green 为外部 slot adapter 合同。
- ⚠️ **未找到** `soymutdb.org` 作为真实生产域名的部署配置；其仅出现在 canonical/帮助邮箱/ssg 脚本中。
- ⚠️ `e2e/` 已存在 `playwright-admin-production.config.ts` 与 `admin-production-login.spec.ts`（说明生产 E2E 部分雏形已具）。
- ⚠️ git tag 仅有 `0.1.2`（此处为版本标签，不等同于生产 Release 数据范围）。
- ⚠️ **数据面写入器缺口（QA 已按源代码复核，对齐 t3）**：唯一真实写入的导入适配器是 `module_tsv`
  （`ModuleTsvAdapter`）→ `module_data_rows`（**write-only**，无消费者）；`fasta/gff3/vcf/blast_db/seed_data/
  expression_csv/homolog_csv` 适配器全部 `raise UnsupportedImportError`；`import_vcf` **fail-closed**；
  `import_gff3`/`import_mutant_lines` 仅计数**不写库**。门户 `/genes` 读 `genes` 表、`/variants` 读 ClickHouse
  `variant_facts`——**均无真实导入写入器**，首版须经受控真实数据种子(路线B)或核心写入器(路线A)注入。
- ⚠️ **t7 数据面查询验证已交付**：`scripts/validate-release-data.sh`（+x，覆盖 G11+G12 的 D1–D4/C1–C6/P1–P3，
  任一 FAIL 退出码=1）；归档输出建议 `acceptance/data-query/validate-release-<release_id>.log`。
- ⚠️ **路线B 受控真实数据种子：设计已产出（t12 `docs/ops/route-b-seed-data-design.md`），loader 已实现（t16
  `scripts/seed_release_data.py`）**——`--check`/`--plan`/`--emit-sql` 为可执行通用实现（parse_fasta→chromosomes、
  parse_gff3→genes/transcripts/exons/gene_aliases、parse_vcf→variant_facts(canonical)、parse_mutants→mutant_lines，
  含校验+Demo/SMDB/Wm82.a4.v1 拒绝）；**`--write` PG/CH 插入 + data_sets/provenance/release_data_sets + 置 ready
  仍 fail-closed**（需 `SOYMUTDB_SEED_ENABLED=1` + asyncpg/clickhouse_connect，待数据源冻结+授权后启用）。
- ⚠️ **G10 释放前置（设计 §11，未冻结则 G10 维持 No-Go）**：①权威数据源与版本/许可（Wm82v4.0 FASTA/GFF3/VCF）；
  ②`mutants.tsv`↔VCF 样本名映射；③CH `variant_facts` 已按 `upgrade_variant_facts_schema.sql` canonical 迁移；
  ④启用 `--write` 写库适配器（depends ①②③ + 授权）。`--write` 落地并跑通前，首版真实基因/变异数据仍无法进入
  门户读取表（`genes`/`variant_facts` 无真实写入器），**G10 维持 No-Go**。

> 上表若有出入，以代码库实际状态为准，并在本文件更新日期栏记录修订。
