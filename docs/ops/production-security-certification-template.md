# SoyMutDB 上线安全认证表（模板）

> 使用说明：本表是生产上线 **安全边界 Go/No-Go** 的填表模板，配套参考清单见
> [`production-security-checklist.md`](production-security-checklist.md)。
> 由发布负责人牵头、`qa-acceptance` 复核、`ops-security` 提供证据。每个「检查项」需给出
> 状态与证据；任一「**Not Met**」项即为 **No-Go**。修订版本请在本表头部登记。

---

## A. 认证元信息

| 字段 | 填写 |
|---|---|
| 上线版本 / 构建 | `image@sha256` 引用列表（API/WORKER/MCP/JBROWSE） |
| 目标环境 | [ ] Staging   [ ] Production |
| 生产域名 | `https://` |
| 填表人 / 发布负责人 | |
| 复核人（qa-acceptance） | |
| 数据来源 / 基线 | `docs/ops/production-security-checklist.md` |
| 日期 | |

## B. 密钥与环境准备（前置）

| 检查项 | 证据（命令输出/截图路径） | 状态 |
|---|---|---|
| 已用 `deploy/scripts/gen-prod-secrets.sh` 引导 `.env` 并生成强随机秘密 | `SOYMUTDB_JWT_SECRET` 长度 >= 32，非示例值 | [ ] Met / [ ] Not Met |
| `/opt/soymutdb/.env` 权限 `0600`，仓库外，已列入备份排除/加密 | `ls -l /opt/soymutdb/.env` | [ ] Met / [ ] Not Met |
| `SOYMUTDB_CORS_ORIGINS` 为显式 HTTPS 白名单、无 `*` | | [ ] Met / [ ] Not Met |
| 数据存储凭据非默认/占位符（PG/CH/Redis/MinIO/Grafana） | | [ ] Met / [ ] Not Met |
| 镜像引用均为 `image@sha256:<64hex>` | | [ ] Met / [ ] Not Met |
| `SOYMUTDB_APP_ENV=prod` | | [ ] Met / [ ] Not Met |
| 可选：静态发布/OLS4/邮件秘密按需注入（HMAC key >= 32） | | [ ] Met / [ ] Not Met / [ ] N/A |

## C. 安全边界逐项认证（对应 checklist §3）

> 状态：**Met** = 满足；**Not Met** = 不满足（No-Go）；**N/A** = 不适用（请注明原因）。

| ID | 边界项 | 证据 | 状态 |
|---|---|---|---|
| 3.1 | 仅 HTTPS 入口；HSTS 仅在 https 下发 | | [ ] Met / [ ] Not Met / [ ] N/A |
| 3.2 | TLSv1.2/1.3，无弱套件与 session tickets | | [ ] Met / [ ] Not Met |
| 3.3 | CORS 显式白名单、无 `*`、凭据安全 | | [ ] Met / [ ] Not Met |
| 3.4 | CSP 注释与实际规则一致；`'unsafe-inline'` 目前为 SSG 内联脚本所需（见 G-1，需前端改 nonce/hash 才能收紧） | | [ ] Met / [ ] Not Met |
| 3.5 | `X-Frame-Options` SAMEORIGIN（admin DENY） | | [ ] Met / [ ] Not Met |
| 3.6 | `X-Content-Type-Options: nosniff` | | [ ] Met / [ ] Not Met |
| 3.7 | `Referrer-Policy: strict-origin-when-cross-origin` | | [ ] Met / [ ] Not Met |
| 3.8 | `Permissions-Policy`（禁 geo/mic/camera） | | [ ] Met / [ ] Not Met |
| 3.9 | 速率限制 API 100r/s、BLAST 1r/s、auth 10r/s、连接 50 | | [ ] Met / [ ] Not Met |
| 3.10 | `/admin/`、`/metrics` 私网 ACL | | [ ] Met / [ ] Not Met |
| 3.11 | refresh cookie HttpOnly / `Path=/api/v1/auth` / SameSite=lax / Secure | | [ ] Met / [ ] Not Met |
| 3.12 | 上传/正文上限 `500m`，header 缓冲兜底 | | [ ] Met / [ ] Not Met |
| 3.13 | 生产 fail-fast（缺失/弱 secret 拒绝启动） | | [ ] Met / [ ] Not Met |
| 3.14 | 镜像不可变 `image@sha256` + manifest inspect | | [ ] Met / [ ] Not Met |
| 3.15 | 凭据预检禁默认/占位符 | | [ ] Met / [ ] Not Met |
| 3.16 | `/data/` Range 支持 + immutable | | [ ] Met / [ ] Not Met |
| 3.17 | 敏感请求不缓存（Authorization/Cookie），API `no-store` | | [ ] Met / [ ] Not Met |
| 3.18 | `/track.gif` 无缓存、CORS 政策确认 → 见缺口 G-7 | | [ ] Met / [ ] Not Met |
| 3.19 | `/metrics` 私网、`/health` 无限流 | | [ ] Met / [ ] Not Met |
| 3.20 | DB 连接预算 <= 80% max_connections | | [ ] Met / [ ] Not Met |
| 3.21 | Redis 职责隔离（cache=allkeys-lru，celery=noeviction+AOF） | | [ ] Met / [ ] Not Met |
| 3.22 | 备份 format-v2、quiesce、sha256/`.complete`、异站保留 | | [ ] Met / [ ] Not Met |
| 3.23 | 监控告警覆盖（API/worker/DB/磁盘/Redis/备份/投递） | | [ ] Met / [ ] Not Met |
| 3.24 | 告警投递经 secret 只读挂载，缺失 fail-closed | | [ ] Met / [ ] Not Met |

## D. 安全缺口处置追踪

| 缺口 | 等级 | 处置方案 | 责任角色/任务 | 状态 | 证据 |
|---|---|---|---|---|---|
| G-1 CSP `'unsafe-inline'` 与注释不一致 | 高 | 注释已修正为如实描述（t10 已完成）；真实收紧需前端将内联脚本改 nonce/hash 后移除 unsafe-inline | 一致性：ops-security（已完成）；收紧：frontend-platform (t5/t6) | 注释一致性 [x] 已处置 / 收紧 [ ] 待处置 | infra/nginx/conf.d/default.conf |
| G-2 生产 fail-fast 覆盖不全（CH/管理员口令） | 高 | `clickhouse_password`/`admin_password`/`admin_email` 已入 `_DEFAULT_PRODUCTION_VALUES` + `required_fields` | ops-security（已完成，t9） | [x] 已处置 | config.py / test_config_security.py（24 项通过） |
| G-2b 管理员引导口令 | 高 | `SOYMUTDB_ADMIN_PASSWORD/EMAIL` 已纳入 config fail-fast + upgrade.sh 预检 + gen-prod-secrets.sh 生成 | ops-security（已完成，t9） | [x] 已处置 | config.py / upgrade.sh / gen-prod-secrets.sh（--template 生成 16+ 字符） |
| G-3 `upgrade.sh` 预检与 config.py 规则差距 | 中 | JWT 示例值 + admin/SMTP 预检加入 upgrade.sh，与 config.py 对齐 | ops-security | [ ] 待处置 | upgrade.sh |
| G-4 web/admin/jbrowse 发布拓扑与 nginx 残留 upstream | 中 | 核对发布拓扑后删除/改写 upstream/location | frontend-platform + build-release | [ ] 待处置 | |
| G-5 秘密轮换与单点明文 `.env` | 中 | 定义轮换周期；评估 Vault/SOPS | ops-security | [ ] 待处置 | |
| G-6 备份异站凭据最小权限与调度 | 中 | 最小权限 + 定时调度文档化 | ops-security | [ ] 待处置 | |
| G-7 `X-XSS-Protection` 弃用 / track.gif CORS 回显 | 低 | 评估移除 / 收敛 origin | ops-security | [ ] 待处置 | |

## E. 校验与签名

**校验命令（发布后若已部署，可在此填写）**

```bash
bash deploy/scripts/healthcheck.sh
curl -s https://<域名>/api/v1/health/ready
docker compose config -q
```

**认证结论**：□ **Go**（全部所需项 Met，缺口均已处置或已获豁免审批）　□ **No-Go**（存在 Not Met 项）

| 角色 | 姓名 | 签名 | 日期 |
|---|---|---|---|
| 发布负责人 | | | |
| qa-acceptance 复核 | | | |
| ops-security 会签 | | | |
