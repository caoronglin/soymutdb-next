# 生产环境变量、秘密管理与安全边界清单

> 维护人：**ops-security**（soymutdb-production-go 团队，任务 t2）
> 面向对象：SoyMutDB 正式生产上线（单物种可信生产 MVP）的运维/安全值班与发布负责人。
> 权威来源：`apps/api/app/core/config.py`（pydantic-settings 生产 fail-fast）、
> `docker-compose.yml`（生产 compose 与环境注入）、`deploy/.env.example`（生产变量模板）、
> `deploy/scripts/upgrade.sh`（发布前预检）、`infra/nginx/conf.d/default.conf`（安全头/CORS）、
> `infra/monitoring/*`（监控告警）、`docs/ops/disaster-recovery.md`（备份恢复）。
>
> 本清单用于生产 **Go/No-Go 判定**：任一「**No-Go**」项未满足即不得放行上线；「**待加固**」项
> 记录当前弱点与建议动作，需在计划内排期。

---

## 1. 环境变量总览与生产默认值

### 1.1 变量前缀约定

| 前缀 | 用途 | 读取方 | 模板 |
|---|---|---|---|
| `SOYMUTDB_*` | 应用配置，字段名与 `config.py` 对齐 | api / worker / beat / migrate / mcp-server | `deploy/.env.example` |
| `COMPOSE_PROFILES` | compose 能力 profile（`core,blast,analyses,mcp`） | compose | 同上 |
| `*_IMAGE_REF` | 镜像 **immutable digest** 引用（`image@sha256:...`） | compose / upgrade.sh | 同上 |
| `POSTGRES_PASSWORD` 等 | 数据存储容器级密码（compose `:?` 必填校验） | postgres / clickhouse / redis / minio / grafana | 同上 |
| `VITE_*` | 前端构建期变量（**不**作用于后端/运行时） | apps/web 构建 | 根目录 `.env.example` |

> 注意：根目录 `.env.example` 是前端 `VITE_*` 模板，**不**生效于后端；后端一律读取 `SOYMUTDB_*`。

### 1.2 应用级必填变量（生产 fail-fast 强制）

`config.py::Settings.validate_security_configuration` 在 `app_env == "prod"` 时要求以下字段非空，
且不得等于开发默认值（`dev_jwt_secret_change_in_production` / `minioadmin` / `soymutdb_dev_password` 等）：

| 字段（环境变量） | 生产要求 | 校验 | 来源 |
|---|---|---|---|
| `SOYMUTDB_APP_ENV` | 必须为 `prod` | Literal[dev/staging/prod] | `x-app-env` anchor |
| `SOYMUTDB_DATABASE_URL` | 非空、非开发默认 | required + `_DEFAULT_PRODUCTION_VALUES` | compose `api/worker` |
| `SOYMUTDB_REDIS_URL` | 非空、含 `:${REDIS_PASSWORD}` | required + 默认值 | `x-app-env` |
| `SOYMUTDB_S3_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` | 非空、非 `minioadmin` | required + 默认值 | `x-app-env` |
| `SOYMUTDB_JWT_SECRET` | **>= 32 字符**且非示例值 | 长度 + 示例黑名单 | `x-app-env` / upgrade.sh |
| `SOYMUTDB_CORS_ORIGINS` | 非空、逗号分隔、**无通配符** `*` | required + wildcard 拒绝 | `x-app-env` / upgrade.sh |
| `SOYMUTDB_CLICKHOUSE_PASSWORD` | compose 层 `:?` 必填 | compose 强制（见 §3 缺口） | `x-app-env` |

### 1.3 compose 层必填（容器/凭据）

`docker-compose.yml` 使用 `${VAR:?message}` 强制以下变量在 `docker compose config -q` 阶段存在：

- `POSTGRES_PASSWORD`、`CLICKHOUSE_PASSWORD`、`REDIS_PASSWORD`
- `MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`GRAFANA_PASSWORD`
- `ALERTMANAGER_WEBHOOK_URL_FILE`、`CLOUDFLARE_TUNNEL_TOKEN_FILE`（secret 文件路径）

### 1.4 通过 `upgrade.sh` 预检的凭据

`deploy/scripts/upgrade.sh`（Step 2 Pre-flight，与 `config.py` 对齐并**更严**）逐项校验：

- `SOYMUTDB_JWT_SECRET` 长度 >= 32
- `SOYMUTDB_CORS_ORIGINS` 非空
- `MINIO_ROOT_USER/PASSWORD` ≠ `minioadmin`
- `POSTGRES/CLICKHOUSE/REDIS_PASSWORD` ≠ `soymutdb_dev_password`
- `GRAFANA_USER/PASSWORD` ≠ `admin`
- 上述凭据不含 `change-me-*` 占位符
- 镜像引用必须匹配 `@sha256:[0-9a-f]{64}`（immutable digest，禁 `:latest`）

### 1.5 可选变量（按需启用，均默认关闭且 fail-closed）

| 作用域 | 变量 | 行为 |
|---|---|---|
| 静态发布 | `SOYMUTDB_PUBLICATION_LOCAL_ROOT` / `SOYMUTDB_GITHUB_PAGES_TOKEN` / `...CLOUDFLARE_PAGES_*` | 未配置目标在 Admin 显示 `is_configured=false`，不会出现在可选发布列表 |
| OLS4 插件 | `SOYMUTDB_PLUGIN_MANIFEST_SIGNING_KEY`（>=32 字符）/ `SOYMUTDB_PLUGIN_MANIFESTS_JSON` | HMAC 签名校验，缺失/不匹配则保持 `not_installed` |
| 邮件 | `SOYMUTDB_SMTP_ENABLED`（默认 false）/ `SOYMUTDB_SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL/USE_TLS` / `SOYMUTDB_SMTP_ADMIN_TO` | 未开启则不真发邮件 |
| Cloudflare Tunnel | `CLOUDFLARE_TUNNEL_TOKEN_FILE`（路径）/ `CLOUDFLARE_TUNNEL_HEALTH_URL` | compose `--profile cloudflare-tunnel`，token 经 secret 只读挂载 |
| Celery 调优 | `SOYMUTDB_CELERY_RESULT_EXPIRES`（默认 604800）、`REDIS_CACHE_MAXMEMORY`/`REDIS_CELERY_MAXMEMORY` | 默认 512mb |
| 连接预算 | `SOYMUTDB_DB_POOL_SIZE`（5）/ `DB_MAX_OVERFLOW`（5）/ `WORKER_DB_POOL_SIZE`（2）/ `WORKER_DB_MAX_OVERFLOW`（4） | 须与 postgres `max_connections` 齐步 |

---

## 2. 秘密管理策略

### 2.1 秘密存放与注入（当前实现 + 工具）

| 秘密 | 存放 | 注入方式 | 权限 |
|---|---|---|---|
| 应用/数据存储密码（JWT、POSTGRES、CLICKHOUSE、REDIS、MINIO、GRAFANA、SMTP） | `/opt/soymutdb/.env`（由 `install.sh` 从模板复制） | compose 读取 `.env` → 容器环境变量 | `chmod 600` |
| Cloudflare Tunnel token | `/etc/soymutdb/secrets/cloudflare_tunnel_token` | compose `secrets:` 只读挂载 `/run/secrets/...` | `0600`（部署账户所有） |
| Alertmanager webhook URL | `/etc/soymutdb/secrets/alertmanager_webhook_url` | compose `secrets:` 只读挂载 | `0600` |
| 静态发布凭据（GitHub/Cloudflare token、本地发布根） | `/opt/soymutdb/.env` | 仅 env 注入，**不落库**、不进 API 响应/审计日志 | `0600` |

**秘密生成/校验工具**：`deploy/scripts/gen-prod-secrets.sh` 可从模板或既有 `.env` 引导出强随机秘密，
自动替换仍为占位/默认值的必填凭据，并校验 `JWT>=32`、禁 `change-me-*`/`minioadmin`/`admin123`/
`soymutdb_dev_password`、CORS 无通配符；写入前备份、`chmod 600`、幂等非破坏。支持 `--check`（只校验）、
`--template`（新建）、`--compose-preflight`（追加 `docker compose config -q`）。

### 2.2 已落实的硬性边界

- **绝不入库**：`.env`、`*.pem`、`*.key`、`secrets/` 全部在 `.gitignore` 中；仓库内无任何真实秘密。
- **镜像不可变**：生产镜像一律 `image@sha256:<64hex>`，CI 无 `:latest`；`upgrade.sh` 校验 digest 格式并 `docker manifest inspect`。
- **秘密不进日志/响应**：`publication_targets` 对公开凭据做 redact；审计日志不含秘密。
- **secret 文件挂载只读** 且位于仓库外，归部署账户所有。

### 2.3 需要补齐的治理缺口（→ 见 §4 缺口 G-5..G-7）

- 无统一的**秘密轮换周期**与轮换标准操作流程（JWT、DB、MINIO、SMTP）。
- 生产仍以**明文 `.env`** 承载全部秘密，未接任何密钥管理/密文存储（Vault/SOPS 等）；若暴露 `/opt/soymutdb/.env` 即全量泄露。
- `BACKUP_S3_ACCESS_KEY` / `BACKUP_S3_SECRET_KEY`（异站备份凭据）走环境变量，属受限敏感配置，应纳入轮换与最小权限（只写目标桶）。
- 静态发布目标 token（GitHub/Cloudflare Pages）目前建议放 `.env`。

---



## 3. 安全边界清单（Go / No-Go 判定）

> 判定：**Go** = 满足；**No-Go** = 上线阻断，必须整改；**待加固** = 记录弱点、排期整改。

| # | 边界项 | 当前状态 | 判定 |
|---|---|---|---|
| 3.1 | **传输安全**：仅 HTTPS 入口；HSTS 仅在 `https` 下发 `max-age=31536000; includeSubDomains; preload` | `nginx.conf` `$hsts_header_value` 按 `$scheme` 动态 | Go |
| 3.2 | **TLS 版本/套件**：`TLSv1.2 TLSv1.3`，禁用弱套件与 session tickets | `nginx.conf` | Go |
| 3.3 | **CORS**：`SOYMUTDB_CORS_ORIGINS` 显式白名单、无 `*`、启用凭据安全 | `config.py` 拒绝 wildcard；prod 要求非空 | Go |
| 3.4 | **Content-Security-Policy**：见 §4 缺口 **G-1**（`script-src` 含 `'unsafe-inline'`，与注释「no unsafe-inline」不一致） | nginx | **待加固** → 建议 Go 前收敛 |
| 3.5 | **点击劫持**：`X-Frame-Options: SAMEORIGIN`（admin `DENY`） | nginx / admin-nginx | Go |
| 3.6 | **MIME 嗅探**：`X-Content-Type-Options: nosniff` | 全局 | Go |
| 3.7 | **Referrer**：`strict-origin-when-cross-origin` | 全局 | Go |
| 3.8 | **Permissions-Policy**：`geolocation=(), microphone=(), camera=()` | 全局 | Go |
| 3.9 | **速率限制**：API 100r/s、BLAST 1r/s、auth 10r/s、`limit_conn 50` | `nginx.conf` | Go |
| 3.10 | **管理控制台 IP ACL**：`/admin/` 仅本地 + RFC1918，`/metrics` 同理 | `default.conf` | Go |
| 3.11 | **鉴权 Cookie**：refresh 走 HttpOnly、`Path=/api/v1/auth`、`SameSite=lax`、prod/staging `Secure` | `config.py` `refresh_cookie_secure_effective` | Go |
| 3.12 | **上传/正文上限**：`client_max_body_size 500m`，`large_client_header_buffers` 兜底 | `nginx.conf` | Go |
| 3.13 | **失败关闭**：生产缺失/弱 secret 时 API 拒绝启动（fail-fast） | `config.py` + `upgrade.sh` | Go（见 §4 G-2 覆盖不全） |
| 3.14 | **镜像不可变**：`image@sha256` 校验 + `docker manifest inspect` | `upgrade.sh` | Go |
| 3.15 | **凭据预检**：JWT/CORS/MINIO/PG/CH/Redis/Grafana 禁默认值与占位符 | `upgrade.sh` | Go |
| 3.16 | **范围请求 (Range)**：`/data/` 支持 BAM/CRAM/tabix，`Cache-Control immutable` | `default.conf` | Go |
| 3.17 | **敏感请求不缓存**：`proxy_no_cache`/`proxy_cache_bypass` 命中 `Authorization`/`Cookie`，API `no-store` | `nginx.conf` | Go |
| 3.18 | **跟踪像素**：`/track.gif` 无缓存、无速率限制、CORS open | `default.conf` | Go（见 §4 G-4 讨论） |
| 3.19 | **监控探针隔离**：`/metrics` 私网、`/health` 无速率限制 | `default.conf` | Go |
| 3.20 | **数据库连接预算**：app 总预算 <= 80% postgres max_connections | `config.py` + compose | Go |
| 3.21 | **Redis 职责隔离**：cache=allkeys-lru，celery=noeviction+AOF，独立口令 | compose | Go |
| 3.22 | **备份完整性与法定时效**：format-v2 三源、`BACKUP_WRITES_QUIESCED=1`、sha256/`.complete`、异站保留 | `backup.sh`/`verify-restore.sh`/`disaster-recovery.md` | Go |
| 3.23 | **监控告警覆盖**：API 5xx/p95、worker offline、任务积压/失败、PG 连接、磁盘、Redis 内存、备份陈旧/失败、Alertmanager 投递 | `infra/monitoring/rules/alerts.yml` | Go |
| 3.24 | **告警投递**：webhook URL 经 secret 只读挂载，缺失即 fail-closed | compose secrets | Go |

---

## 4. 上线前须处理的安全缺口

下列缺口为本次审查实际发现，按优先级排序，均建议在 Go/No-Go 前整改或给出明确处置结论。

### G-1（高 · CSP 与注释不一致，弱化脚本策略）

**位置**：`infra/nginx/conf.d/default.conf` 第 21–27 行
**现象（已澄清）**：原注释声明 `script-src 'self' (no unsafe-inline; hashed assets only)`，但实际
`add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; ..."`。
**根因**：SSG 页面（`apps/web/scripts/base-template.ts` 的 `THEME_INIT_SCRIPT` ~L412、
`WIDGET_LOADER_SNIPPET` ~L144、redirect ~L455；`ssg-build.ts` 的 i18n-ready ~L201）都会输出
**内联 `<script>` 块**，因此 `script-src 'unsafe-inline'` 是**当前必须**的，移除会直接破坏这些页面。
**t10 已处置（一致性）**：`ops-security` 已修正该注释，改为如实描述 `script-src 'self' 'unsafe-inline'`
并说明内联脚本来源与完全一致的 `<meta>` CSP（见 `index.html`/`base-template.ts`），CRLF 保留。
**仍待处置（真实加固，交 frontend-platform t5/t6）**：
- 让前端内联脚本改为 **nonce / hash** 后，再移除 `script-src 'unsafe-inline'`（网关头 + meta CSP 两处）。
- 收敛 `connect-src 'self' https:`（尽量限定 API 与静态域）、`img-src ... https: blob:`、`frame-src`（JBrowse/beacon 域）。


### G-2（高 · 生产 fail-fast 覆盖不全）

**位置**：`apps/api/app/core/config.py` `validate_security_configuration`（约 308–359 行，`required_fields` 330、`_DEFAULT_PRODUCTION_VALUES` 343）
**现象**：prod 必填/默认值校验仅覆盖 `database_url / jwt_secret / redis_url / s3_endpoint / s3_access_key / s3_secret_key`；应用层 **`clickhouse_password`（默认 `soymutdb_dev_password`）未入 `_DEFAULT_PRODUCTION_VALUES`**——compose 虽用 `${CLICKHOUSE_PASSWORD:?...}` 强制，但若 API 在 compose 外以应用层默认运行，prod 不会拒绝（纵深缺口）。`admin_password`/`admin_email`（`admin123`/`admin@soymutdb.local`）字段在配置中存在，但经核实**并未被任何认证路径消费**——真实管理员引导由 `apps/api/app/scripts/create_admin.py` 直接读取 `SOYMUTDB_ADMIN_USERNAME/EMAIL/PASSWORD`（缺 password 即报错）。
**已处置**：`ops-security` 已纳入以下（`t9`）：
- `config.py`：`clickhouse_password`、`admin_password`(`admin123`)、`admin_email`(`admin@soymutdb.local`) 全部加入 `_DEFAULT_PRODUCTION_VALUES`；`admin_password`/`admin_email` 加入 `required_fields`；新增 `admin_password` 长度与示例校验、`admin_email` 格式与非默认校验。
- `deploy/.env.example`：新增 `SOYMUTDB_ADMIN_EMAIL` / `SOYMUTDB_ADMIN_PASSWORD`（含注释）。
- `docker-compose.yml` `x-app-env`：新增 `SOYMUTDB_ADMIN_EMAIL` / `SOYMUTDB_ADMIN_PASSWORD` 注入。
- `deploy/scripts/gen-prod-secrets.sh`：生成 `SOYMUTDB_ADMIN_PASSWORD`（>=16），校验 `SOYMUTDB_ADMIN_EMAIL` 非默认/格式。
- `deploy/scripts/upgrade.sh` 预检：校验 `SOYMUTDB_ADMIN_PASSWORD`（>=12、非默认）、`SOYMUTDB_ADMIN_EMAIL`（非默认、含 `@`）。
- **`apps/api/tests/test_config_security.py` 全 24 项通过。**
**仍待处置**：
- 可选秘密（`smtp_password`、`github_pages_token`、`cloudflare_pages_api_token`、`plugin_manifest_signing_key`）的强度/存在性未校验。
- 与 `data-platform`（backend/config 主责）协作确认不改动被真实消费的字段。

### G-3（中 · upgrade.sh 预检与 config.py 存在差距）

**位置**：`deploy/scripts/upgrade.sh` Step 2（第 114–147 行）
**现象**：
- `SOYMUTDB_JWT_SECRET` 仅校验长度 >= 32，**未**校验示例值（`config.py` 有示例黑名单）。
- 未预检 `admin_password`、`SOYMUTDB_SMTP_PASSWORD`。
**建议**：将 `config.py` 的示例值黑名单与 `admin_password`/SMTP 校验并入 upgrade.sh 预检，保持两处规则**单一来源**或至少同步。

### G-4（中 · 管理控制台/静态边界需与前端发布协同确认）

**位置**：`docker-compose.yml` 顶部注释声明「web/admin/jbrowse 已移出本 compose，由 Cloudflare Pages 托管」，但 `infra/nginx/conf.d/default.conf` 仍保留 `web_frontend` / `admin_app` / `jbrowse_app` upstream 与对应 location。
**影响**：若上游已不在 compose 中，相关 location 指向不存在的 upstream，会因 DNS/upstream 解析失败造成 502，或产生「看似可用、实际不可达」的边界。
**建议**：与 `frontend-platform`（t5/t6）与 `build-release`（t4）核对发布拓扑后，删除或改写残留 upstream/location；同时确认 `/admin/` 的 IP ACL 在 Cloudflare Pages 场景下是否仍适用。

### G-5（中 · 秘密轮换与单点明文）

**现象**：无秘密轮换周期/SOP；生产以单个明文 `.env` 承载全部秘密。
**建议**：为 JWT、DB、MINIO、SMTP、静态发布 token 定义轮换周期（至少 JWT/DB 建议 90 天）；评估接入 Vault/SOPS 做静态加密；`/opt/soymutdb/.env` 仅 root 可读且列入备份排除/加密。

### G-6（中 · 备份运行主体与凭据）

**现象**：`backup.sh` 通过 `BACKUP_S3_ACCESS_KEY/SECRET_KEY` 做异站上传，凭据走环境变量；要求 `BACKUP_WRITES_QUIESCED=1`（先停全部写者）。
**建议**：异站凭据用最小权限（只写目标桶/前缀），纳入轮换；备份 cron/systemd timer 与停止写者/`upgrade.sh` 的调用顺序须文档化（已有 `disaster-recovery.md`，可补充定时调度）。

### G-7（低 · 安全头冗余/弃用项）

**现象**：`X-XSS-Protection: 1; mode=block` 已被现代浏览器弃用且可能引入兼容性问题；`track.gif` 的 CORS 直接回显 `$http_origin`。
**建议**：评估移除 `X-XSS-Protection`（保留 CSP 即可）；确认 `/track.gif` 允许任意 origin 回显是否为有意设计（无凭据、无敏感数据时风险低），否则收敛为静态可配置 origin。

---

## 5. 上线检查表（操作步骤）

### 5.1 发布前（`upgrade.sh` 之前）

1. 引导并生成强凭据：`bash deploy/scripts/gen-prod-secrets.sh --template --env-file /opt/soymutdb/.env`（自动生成 JWT/DB/Redis/MinIO/Grafana 强随机值，`chmod 600`，写入前备份）。
2. 填齐 `SOYMUTDB_CORS_ORIGINS`（真实域名，无 `*`）与 `SOYMUTDB_APP_ENV=prod`；确认镜像引用为 `image@sha256:<64hex>`（来自 CI 发布合同）。
3. `bash deploy/scripts/gen-prod-secrets.sh --check --env-file /opt/soymutdb/.env` 复核；如需，追加 `--compose-preflight`。
4. 若启用静态发布/OLS4/邮件：按 `deploy/.env.example` 注释生成并注入对应秘密（HMAC key >=32 字符）。管理员引导凭据已由 gen-prod-secrets.sh 生成 `SOYMUTDB_ADMIN_PASSWORD`；请填真实 `SOYMUTDB_ADMIN_EMAIL`（非 `admin@soymutdb.local`）。
5. 创建 secret 文件：`/etc/soymutdb/secrets/alertmanager_webhook_url`、`cloudflare_tunnel_token`（`0600`，仓库外）。
6. `docker compose config -q` 校验变量完整性。

### 5.2 发布执行

```bash
sudo -E deploy/scripts/upgrade.sh        # 内部含预检、manifest 校验、拉取、备份、迁移、滚动
bash deploy/scripts/healthcheck.sh       # API liveness/readiness/metrics、DB、Redis、MinIO
```

### 5.3 发布后校验

- API `/api/v1/health/ready` 通过；`/metrics` 私网可读。
- Prometheus `/-/healthy`、`up{job="alertmanager"}`、`alertmanager_notifications_failed_total == 0`。
- 备份指标 `soymutdb_backup_status == 1`、`soymutdb_backup_last_success_timestamp_seconds` 在 48h 内（`BackupStale` 不触发）。
- 逐项核对 §3 清单 Go 项。

### 5.4 回滚

- `deploy/scripts/blue-green-rollback.sh`（或 `upgrade.sh` 失败时的 `restart_pre_upgrade_services`）。
- 回滚后必须重新跑 `verify-restore.sh`（若回滚涉及数据）。

---

## 6. 与其他任务/角色的交接

| 本清单条目 | 交接对象 | 说明 |
|---|---|---|
| G-1 CSP | frontend-platform（t5/t6） | 移除 `script-src 'unsafe-inline'` 需前端产物支持 |
| G-2（CH/管理员口令） | ops-security（已完成，t9） | `clickhouse_password`/`admin_password`/`admin_email` 已入 prod fail-fast + 预检 + 测试（config 24 项通过） |
| G-2b/G-3（管理员引导口令 + 预检/规则单一来源） | ops-security（已完成） + data-platform | `SOYMUTDB_ADMIN_PASSWORD/EMAIL` 已纳入 upgrade.sh 预检与 gen-prod-secrets.sh；与 config.py 对齐 |
| G-4 发布拓扑 | frontend-platform + build-release | 核对 web/admin/jbrowse 在 compose 与 Cloudflare Pages 的归属 |
| G-6 备份调度 | ops-security（自持） | 补定时调度与异站凭据最小权限 |
| 验收证据 | qa-acceptance（t1） | 本清单 + `production-security-certification-template.md` 作为 Go/No-Go 证据归档 |

> 上线安全认证填表模板见同目录 [`production-security-certification-template.md`](production-security-certification-template.md)。
