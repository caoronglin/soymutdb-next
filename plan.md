# SoyMutDB Next 一体化现代化执行计划（第五轮 · 2026-09-21）

> **文档类型：** 当前唯一主执行计划 / 架构约束 / Release Gate  
> **状态：** 计划，不等于已实施或已授权重开能力  
> **当前执行基线：** `main@1009d40a1fb840162c33e8d724f5ce6fa3ade1b3`  
> **前序数据正确性基线：** ADR-0004~0007、Phase 1 P0 Correctness、Phase 2 Import Protocol  
> **新增参考实现：** `caoronglin/primer-workbench` 基因预览（`GenomeContextPanel.jsx`、`geneStructure.js`、`GenomeContextPanel.test.jsx`、`gene-preview-merged-tracks-design.md`）  
> **外部资料复核日期：** 2026-09-21  
> **核心原则：** build once / verify once / publish exact bytes；external/internal 物理与语义双隔离；数据能力先协议后启用；控制面不因 Rust/企业微信/Cloudflare 改造而旁路。

---

## 0. 本轮目标

本轮把过去分散的“数据正确性、UI/UX、部署、CI/CD、安全、依赖、Rust、Cloudflare、企业微信、数据发布”合并为一份可执行路线图，最终交付应具备：

1. **个人电脑可运行**：Linux/macOS/WSL2 + Docker 可一条入口启动，支持 lite/full 两档，不需要生产密钥。
2. **公开站 / 内部站严格分离**：独立制品、独立 origin、独立缓存/统计边界，internal 必须有真实访问控制。
3. **Cloudflare Pages 正式生产静态发布**：复用已验证制品，不在发布端重新 build；PR preview 与生产 promote/rollback 可追溯。
4. **Gene Preview 加入 SoyMutDB**：借鉴 primer-workbench 的合并轨道与交互正确性，但改造成 SoyMutDB release/assembly-aware 组件。
5. **Admin 数据发布闭环**：manifest → validate → staging → verify → finalize → publish/rollback；扩展更多格式但不提前开启未完成能力。
6. **企业微信通知 + 受控发布入口**：Webhook 负责推送；双向命令使用企业微信自建应用回调，不用群机器人 Webhook 冒充命令通道。
7. **依赖与基础设施基线升级**：语言运行时、前端、数据库、CI action、容器镜像全部进入可审计升级矩阵。
8. **动画和色彩统一治理**：Ant Design 6 / Tailwind / JBrowse / ECharts 只使用统一语义 token；reduced-motion / low-power / dark mode 一致。
9. **统计更高效、更隐私**：批量写入、短期明细 + 长期聚合、DNT/GPC、禁止默认记录可识别的原始搜索词。
10. **仓库瘦身**：生成物、过期方案、重复脚本、死代码和冲突文档有归档/删除证据。
11. **核心计算组件 Rust 化**：把稳定、可测的 CPU/内存热点迁移为 Rust kernel；不重写 FastAPI/ORM/Celery/授权/发布状态机。

---

## 1. 不可突破的硬约束

### H1 · Feature Flag / Release Gate 不得绕过

当前默认关闭的科学导入能力继续关闭。**任何新格式或 writer 只有同时满足以下证据才可单独评审开启：**

```text
protocol frozen
+ parser/validator
+ durable writer
+ idempotency
+ staging visibility isolation
+ checksum/row-count verification
+ finalize
+ retry/ambiguous-ACK/crash recovery
+ rollback/cleanup
+ real PostgreSQL/ClickHouse integration
+ API/Admin/E2E evidence
= eligible for capability reopen review
```

不能因为“前端已支持”“解析器能读”“Rust 版本更快”而启用。

### H2 · external/internal 不是主题切换

- external 与 internal 必须是两棵独立静态制品。
- 不能靠 hostname/cookie/IP 在同一制品运行时推断站点身份。
- internal 的 API、缓存、统计、Service Worker、发布项目必须与 external 分域。
- `noindex` 不是访问控制；internal 必须位于 Cloudflare Access / VPN / SSO / 私有入口之后。
- external 制品中对 `internal_id`、未发布 release、内部 sentinel **零命中**。

### H3 · Build Once / Publish Exact Bytes

CI 构建一次 → 生成 manifest/checksum → 验证 → Cloudflare/GitHub/local publisher 只复制或上传同一字节树。  
发布端不得重新运行 Vite/SSG，不允许“发布环境变量不同所以再 build”。

### H4 · Release / Assembly Context 不得丢失

Gene、Mutant、Variant、JBrowse、静态页、导出、统计、Gene Preview 都必须携带明确 release/assembly context。  
禁止跳转后静默切到 active/default release。

### H5 · Admin 只管理应用，不管理宿主机超级权限

Web Admin 不增加 root/sudo、系统账号、Docker daemon 管理、宿主机防火墙、数据库 superuser 等能力。  
部署/基础设施操作仍由受控 CI/ops adapter 完成。

### H6 · 企业微信不能成为旁路控制面

企业微信触发的 publish/rollback 必须复用现有 publication service、RBAC、幂等、审批、审计与 release gate。  
不能写一条“收到消息 → 直接执行 shell/直接改数据库/直接上传 Pages”的快捷路径。

### H7 · 隐私数据最小化

Seed Request 的联系人、内部用户信息、原始搜索词、Webhook secret、token、内部 release 信息不得进入：
- external artifact；
- Analytics 明细；
- 企业微信普通通知；
- CI log；
- URL query；
- 浏览器持久化缓存。

### H8 · Rust 只迁移稳定 kernel

Rust 不接管：
- FastAPI routers/services；
- SQLAlchemy ORM/migrations；
- Celery/Outbox 状态机；
- RBAC/JWT；
- release/publication/approval 控制面。

Rust 只做边界清晰、可 bit-for-bit / row-for-row 对照的计算与解析 kernel。

---

## 2. 当前仓库事实与升级基线

### 2.1 当前事实

| 域 | 当前事实 | 本轮结论 |
|---|---|---|
| Node | `24.19.0` | 保持 Node 24 主线，补 current-minor 定期审计 |
| pnpm | `11.21.0` | 继续固定 exact version |
| React | `19.2.0` | 保持 |
| TypeScript | `5.9.3` | 保持当前稳定主线，按兼容测试升级 |
| Ant Design | catalog `6.6.1` | 先升同主线 patch；当前 npm latest 已到 6.6.5 |
| Vite | catalog `6.4.3` | 设计 Vite 8 迁移 lane；不能直接跨 major |
| TanStack Query | `5.101.4` | 可先同 major 升到当前 5.103.x |
| ECharts | `5.5.1` | 评估 6.1.x 迁移与 a11y/option 差异 |
| Zod | `3.24.x` | 4.x 为独立 breaking-change lane |
| Python | `>=3.14` | 保持 3.14 基线，镜像/CI 固定 current patch |
| PostgreSQL | compose `18.4-alpine` | 先升级 18 当前 minor（官方当前 18.6） |
| ClickHouse | `24.8-alpine` | P2 writer 稳定后再迁移到当前 LTS；2026-09 当前 26.8 LTS |
| Redis | `7.4-alpine` | 独立升级到 Redis 8.2 安全修复线，先跑 broker/cache 兼容矩阵 |
| MinIO | 2024 固定 release | 先做 S3/API/版本化/策略兼容审计，再决定目标 |
| module import | `.txt/.tsv/.csv/.xlsx` | 扩为 registry-driven formats |
| scientific imports | 7 类多数默认 OFF | 不重开；先完成 writer/protocol |
| Cloudflare Pages | 有 adapter + headers + 文档，但 README/架构口径存在冲突 | 本轮统一为“可选/首选生产静态托管”，demo 仍可 GitHub Pages |
| Analytics | request background task → ClickHouse **单事件单 INSERT** | 改为 bounded batching；隐私 schema v2 |
| Rust | 历史热路径已移除，现有文档要求 evidence-first | 本轮正式加入 kernel migration roadmap，但生产采用仍受 benchmark gate |

### 2.2 版本升级规则

1. **patch/minor 与 major 分开 PR**。
2. 每次升级输出：lock diff、bundle diff、OpenAPI diff、migration compatibility、browser E2E、image CVE diff。
3. 数据库 major/minor 与应用依赖升级不放在同一个不可回滚 PR。
4. 不用 `:latest`；运行时镜像全部固定具体 tag，发布镜像固定 digest。
5. 安全修复可提高优先级，但仍需最小 smoke，不允许“安全升级所以跳测试”。

---

## 3. Primer Workbench Gene Preview → SoyMutDB

### 3.1 可复用的真实设计

从 `primer-workbench` 读取到的价值点是：

- gene / transcript / exon / CDS / 5′UTR / 3′UTR **共享同一 genomic axis**；
- 同一 biological entity 不重复画多条大轨道；
- 不同基因重叠时使用 row packing，不把不同基因合并；
- 负链显示方向，未知链不伪造方向；
- 详情 click/focus 后可 pin，Esc 关闭并恢复焦点；
- 390px 保持可用，必要时横向浏览；
- 信息状态不能用颜色单独表达；
- component test 覆盖 a11y、负链、未知链、重叠、分页、focus restoration。

**不直接复制：**
- primer candidate / off-target 业务语义；
- shadcn UI 组件；
- primer-workbench 的坐标假设；
- 固定色值。

### 3.2 SoyMutDB 目标组件

建议目录：

```text
packages/genome-view-model/         # 纯 TS：区间、row packing、segment、view model
apps/web/src/components/genome/
  gene-context-preview.tsx          # AntD + SVG renderer
  gene-context-detail.tsx
apps/web/src/components/genome/__tests__/
```

若 Admin/JBrowse 后续也复用 renderer，再抽 `packages/genome-view-react`；第一步不要为“可能复用”过度拆包。

### 3.3 坐标契约

Primer Workbench 内部明确使用 0-based half-open；SoyMutDB 当前数据可能来自 GFF/VCF/DB 的不同坐标语义。  
因此先定义显式类型：

```ts
type CoordinateSystem = "zero_based_half_open" | "one_based_inclusive"

interface GenomicInterval {
  assemblyId: string
  chromosome: string
  start: number
  end: number
  system: CoordinateSystem
}
```

所有 API → viewport 经过一个 adapter；禁止组件内部“猜 +1/-1”。

### 3.4 页面接入

**Gene Detail**
- Overview 下方始终展示紧凑 Gene Context Preview；
- gene / transcript / exon / CDS / UTR；
- linked published variants；
- selected variant 高亮；
- “Open in JBrowse”携带 assembly + region + release。

**Variant Detail**
- 展示当前 variant marker + 所在 gene/transcript；
- 近邻基因只从当前 release/assembly public projection 获取；
- external 不请求 internal-only annotation。

**Mutant Detail**
- 按 linked variant/gene 展示可解释 genomic context；
- 若关联过多，只展示默认 focus + bounded window，不一次画全染色体。

### 3.5 视觉与 a11y

- gene range：neutral surface；
- exon/CDS/UTR：语义 token，不写死颜色；
- variant：shape + label + color；
- selected entity：outline/marker，而非只换颜色；
- dark/light/high-contrast/reduced-motion 全覆盖；
- SVG interactive node 有 accessible name；
- tooltip 只能做 hover 补充，关键详情支持 keyboard/pinned panel。

### 3.6 Gene Preview Gate

必须通过：
- coordinate conversion property tests；
- positive/negative/unknown strand；
- overlapping genes row packing；
- multi-transcript 不生成虚假联合转录本；
- 390/1024/1440 visual test；
- axe；
- external unreleased sentinel leakage；
- release/assembly context preservation；
- JBrowse deep-link round-trip。

---

## 4. 个人电脑运行与开发体验

现有 `scripts/compose-local.sh` 保留为生产拓扑本地构建底层，不再创建第二套 Compose 语义。

### 4.1 新统一入口

新增薄封装（名称可在实施时定为 `scripts/dev.sh` 或等价 CLI）：

```bash
pnpm local:doctor
pnpm local:up         # 默认 lite
pnpm local:up:full
pnpm local:down
pnpm local:logs
pnpm local:reset      # 明确提示会删除本地数据
pnpm local:seed       # 仅合成/开发 fixture，明确标注非生产
```

内部只调现有：
- `setup-workspace.sh`
- `compose-local.sh`
- `docker-compose.dev.yml`
- migration/seed/smoke

不得复制 Compose service 定义。

### 4.2 两档本地拓扑

**lite**
- PostgreSQL
- Redis
- MinIO
- API
- Web/Admin dev server
- 不可用能力明确 disabled/503/empty，不伪造 ClickHouse 数据。

**full**
- lite +
- ClickHouse
- worker/beat
- JBrowse
- analyses/MCP（按 profile）

### 4.3 本地安全默认

- 端口默认绑定 `127.0.0.1`；
- 开发 secret 自动生成到 gitignored 文件；
- 不读取未知父目录 `.env`；
- 不复用生产 token；
- `local:doctor` 检查 Docker、Node/pnpm、Python、端口、磁盘、架构；
- 启动结束打印访问 URL、当前 profile、release fixture、disabled capabilities。

---

## 5. CI/CD 重构

### 5.1 分层

```text
PR Fast Gate
  ├─ format/lint/typecheck
  ├─ unit tests
  ├─ architecture/dependency/secret contracts
  ├─ OpenAPI/client contract
  └─ changed-scope build

Integration Gate
  ├─ real PostgreSQL
  ├─ real ClickHouse
  ├─ MinIO
  ├─ import/finalize/retry
  ├─ external/internal leakage
  └─ browser E2E

Release Gate
  ├─ full static artifacts
  ├─ amd64 + arm64 native image build
  ├─ runtime smoke
  ├─ Trivy
  ├─ SBOM
  ├─ provenance/sign
  └─ immutable artifact publish

Nightly / scheduled
  ├─ dependency update rehearsal
  ├─ perf/capacity
  ├─ 2M import fixture
  ├─ accessibility/visual matrix
  └─ backup/restore rehearsal
```

### 5.2 原则

- `scripts/ci-job-steps.sh` 继续做 GitHub/CNB 共享 job body 真源。
- changed-path 只能减少**非安全关键**工作，不能跳 external/internal、migration、security contract。
- pnpm / uv / pip / Cargo cache 都按 lockfile+toolchain key。
- PR fork 不提供 Cloudflare/WeCom/registry secrets。
- 失败 job 也上传 evidence manifest/log 摘要。
- 所有 acceptance 输出 commit SHA、toolchain、test counts、artifact digest。

### 5.3 依赖自动化

加入版本机器人（GitHub Dependabot 或等价单一方案）：
- npm/pnpm：每周 grouped PR；
- Python：按 runtime/dev 分组；
- Docker：只建议固定 tag，不自动改成 latest；
- GitHub Actions：更新 SHA + tag comment；
- Rust crates：Rust lane 启用后再加入。

自动 PR 仍需完整 gate，不自动 merge major upgrade。

---

## 6. 仓库清理与归档

### 6.1 先做 inventory，不直接 rm

生成：
- tracked generated files；
- zero-import TS/Python modules；
- 无调用 shell scripts；
- superseded docs；
- duplicate deployment docs；
- stale evidence；
- 大文件/二进制；
- generated route/cache/temp。

当前已看到 `apps/web/.tanstack/tmp/*` 出现在仓库检索结果，本轮必须确认是否误跟踪；若是生成物则删除并加入 ignore。

### 6.2 文档真源清理

当前存在“README 称 Cloudflare Pages 已废弃”与“架构文档称其为可选生产目标”的冲突。  
本轮统一为：

- GitHub Pages：public demo / mirror；
- Cloudflare Pages：生产静态托管目标；
- internal/admin：独立受保护项目/origin；
- 旧方案移动到 `docs/archive/<yyyy-mm>/`，顶部写 superseded-by。

### 6.3 删除/归档 Gate

文件只有满足以下条件才删：
- git search/import graph 无生产引用；
- 测试无引用；
- CI/deploy 无引用；
- docs 已有替代入口；
- 若是历史决策/证据，归档而不是删除；
- 删除后跑对应 contract + smoke。

---

## 7. 依赖与基础设施升级路线

### D1 · 前端低风险同主线

优先：
- AntD 6.6.1 → 当前 6.6.x；
- TanStack Query 5.101 → 当前 5.103.x；
- patch/minor dev tooling。

### D2 · 前端 breaking lanes

分别独立：
- Vite 6 → 8；
- ECharts 5 → 6；
- Zod 3 → 4。

每条必须附：
- build time；
- bundle chunks；
- CSP；
- SSG；
- browser E2E；
- typecheck；
- visual regression；
- rollback commit。

### D3 · 数据层

1. PostgreSQL 18.4 → 18 current minor。
2. Redis 7.4 → 8.2 security line：
   - cache；
   - Celery broker；
   - result backend；
   - eviction/noeviction；
   - persistence/AOF。
3. ClickHouse 24.8 → 26.8 LTS：
   - **必须在 P2-3 writer/finalize 语义冻结后**；
   - 实测 async insert / MV / dedup settings；
   - migration from 24.8 fixture；
   - duplicate/finalize semantics 不得依赖未验证默认值。
4. MinIO：先兼容审计再升级。

---

## 8. 动画与色彩治理

当前 Web/Admin 已有 `off / minimal / standard` motion 决策和 AntD token，继续收敛，不重造第三套动画系统。

### 8.1 单一设计 token

新增共享 token 真源（可落 `packages/design-tokens`）：

```text
color.surface.*
color.text.*
color.border.*
color.brand.*
color.semantic.success/warning/error/info
color.genomics.gene/exon/cds/utr/variant/selection
motion.duration.fast/mid/slow
motion.easing.standard/emphasized
motion.mode.off/minimal/standard
radius.*
shadow.*
```

Web/Admin/JBrowse/ECharts/Gene Preview 都从此映射。

### 8.2 规则

- 状态不可只靠红/绿；
- 主色可配置，但危险/成功等 semantic color 不跟随品牌色；
- dark mode 单独校验，不对亮色值简单反相；
- `prefers-reduced-motion` → off；
- Save-Data/低功耗 → minimal；
- standard 动画只用 transform/opacity 为主；
- 页面转场不阻塞导航和输入；
- skeleton/placeholder 不使用无限高频 shimmer；
- 图表颜色有 text legend / pattern / decal 备选。

### 8.3 Gene Preview 动画

- zoom/pan 可平滑，但 reduced-motion 立即跳变；
- selection 只做短时 outline/opacity；
- 不做持续闪烁 variant marker；
- tooltip/pinned detail 无运动依赖。

---

## 9. 后台数据发布与更多格式

### 9.1 统一 Import Format Registry

把“文件扩展名判断”升级为 server-owned registry：

```text
format_key
extensions
mime/magic
streaming_parser
schema_version
normalization_version
max_size
decompression_policy
preview_support
writer_capability
rollback_capability
feature_flag
```

### 9.2 格式分层

**Module/tabular（优先）**
- 现有：TXT / TSV / CSV / XLSX
- 新增候选：JSONL / NDJSON、Parquet
- ODS 只在明确需求时加入，避免无收益办公格式依赖。

**Genomic canonical**
- VCF / VCF.GZ
- BCF
- GFF3 / GTF
- FASTA / FASTA.GZ
- BED/BED.GZ（明确 BED3/6/12 子集）
- phenotype/expression：TSV/CSV/XLSX/Parquet

**Track attachment，而非 canonical DB import**
- BigWig
- BigBed
- BAM/CRAM + index
- bgzip/tabix assets

这类文件进入 MinIO/JBrowse track registry，不强行转成 PostgreSQL/ClickHouse facts。

### 9.3 安全预检

所有格式先执行：
- extension + MIME + magic 一致性；
- archive/decompression ratio 限制；
- row/column/record limit；
- streaming checksum；
- UTF encoding/delimiter/sheet detection；
- formula/macro/embedded object 处理策略；
- schema/context/release/assembly validation；
- preview bounded rows；
- diagnostics 不回显敏感内容。

### 9.4 Durable writer 继续执行 P2

必须保留当前 P2 主线：

```text
manifest
→ fingerprint
→ PARSING
→ WRITING(staging only)
→ VERIFYING
→ finalize base + dependent summaries
→ post-finalize verify
→ PUBLISHED
```

FAILED retry 复用同 logical import identity；ambiguous ACK 必须先 reconcile，不能盲目重复写。

### 9.5 Admin Import Studio

改为 Steps：
1. Source
2. Bind release/assembly/module
3. Inspect
4. Validate
5. Preview
6. Ingest
7. Verify
8. Publish/Complete

disabled capability 显示真实原因和前置门，不提供“点了必失败”的主按钮。

---

## 10. 企业微信集成

### 10.1 两种能力必须分开

**A. 群机器人 Webhook：只出站推送**
- Seed Request 新申请；
- Seed Request 状态变化；
- import failed/completed；
- release validation/publish/rollback；
- Cloudflare deployment；
- CI/production health 告警。

Webhook URL 是 secret，只存在服务端 secret store/env；绝不进入前端、数据库普通字段、日志。

**B. 企业微信自建应用 callback：双向命令**
群机器人 Webhook 不承担收消息/执行命令。  
若需要“从企业微信发布”，必须使用带 URL/Token/EncodingAESKey 的自建应用回调通道。

### 10.2 Notification Outbox

新增统一 notification outbox/channel adapter：

```text
domain event
→ notification_outbox
→ in-app / email / wecom
→ retry with backoff
→ delivery evidence
```

相同事件有 deterministic dedup key，避免重试刷屏。

### 10.3 隐私

Seed Request 推送默认只发送：
- request public/reference id；
- 时间；
- 当前状态；
- 管理后台受保护链接。

不在群消息中发送姓名、邮箱、手机号、地址、详细留言。

### 10.4 企业微信命令

第一版仅：
- `status`
- `release <id> status`
- `publication <id> status`
- `preview publish <id>`

生产动作后续才开放：
- `publish external <publication_id>`
- `rollback external <publication_id>`

并必须：
- callback 签名/加解密校验；
- timestamp/nonce replay protection；
- corp/user identity allowlist；
- WeCom user ↔ SoyMutDB admin identity mapping；
- RBAC；
- 二次确认/审批；
- idempotency key；
- AuditLog；
- 不允许 arbitrary shell/SQL/URL 参数。

企业微信发起的 publish 仍调用同一个 `request_publication` / publication state machine。

---

## 11. external / internal 双站点深化

### 11.1 制品

```text
dist/external/
dist/internal/
```

两者分别生成：
- JS/CSS chunks；
- HTML/SSG；
- service worker；
- manifest/SHA256；
- robots/meta；
- CSP；
- analytics config。

禁止共享一份 SW scope。

### 11.2 API

external：
- public projection only；
- cacheable public responses；
- never return internal identifiers；
- unpublished release 统一 not-found。

internal：
- auth required；
- private/no-store；
- 可读 internal projection（按角色）；
- 独立 CORS origin。

### 11.3 Cloudflare

建议三个项目/安全域：
- `soymutdb-external`：公开；
- `soymutdb-internal`：Cloudflare Access；
- `soymutdb-admin`：Cloudflare Access + 更严格 policy。

internal/admin 不和 external 共用 production token scope。

### 11.4 Gate

- anonymous internal request 被边缘阻断；
- external sentinel leakage scan；
- external/internal cache key 不重用；
- source map 不泄漏 internal config；
- external HTML/JSON/JS/URL/log/analytics 全部 negative leakage。

---

## 12. Cloudflare Pages 发布流程

Cloudflare 官方 2026 文档仍支持 Pages Direct Upload + Wrangler；同时官方说明 Workers 是新应用的主平台。  
SoyMutDB 当前是静态 artifact-first 架构，本轮**继续使用 Pages**，不因平台宣传迁移 Workers。

### 12.1 生产路径

```text
CI build
→ build:sites
→ artifact checksums
→ privacy/security scan
→ upload immutable artifact
→ Wrangler Pages Direct Upload
→ verify deployment URL
→ smoke
→ mark publication published
```

优先使用官方 `wrangler pages deploy <verified-dir>`，减少当前自定义 direct-upload HTTP 协议维护面。

### 12.2 不重新构建

Cloudflare stage 只下载 CI artifact，并核对 digest。  
Wrangler 上传的是已验证目录，不运行 `pnpm build`。

### 12.3 Preview

同仓 PR/branch：
- external preview 可自动；
- internal preview 必须 Access protected；
- fork PR 不注入 token，也不自动发布；
- preview URL 回写 deployment evidence。

### 12.4 Rollback

保存 Cloudflare deployment id；rollback/promotion 使用已验证历史 deployment，不重新 build 旧 commit。

### 12.5 迁移旧 adapter

`apps/worker/.../cloudflare_pages.py` 当前自定义 upload 路径先保留兼容；  
Wrangler artifact publisher 验证完成后，再决定：
- worker 只发 publication request；
- CI publisher 完成 upload/promote；
- adapter 退化为状态查询/rollback orchestration。

避免长期维护两套上传协议。

---

## 13. 页面访问统计与隐私

### 13.1 Analytics v2

当前 `record_event` 每次调用单行 INSERT。改为：

```text
client bounded batch
→ POST/beacon
→ in-process bounded queue or analytics worker
→ batch insert ClickHouse
```

flush 条件：rows threshold 或 short interval；队列满时 analytics 可丢弃，**不能拖慢主请求**。

### 13.2 数据最小化

默认不长期保存：
- raw IP；
- full User-Agent；
- raw referrer query；
- raw search query；
- internal URL parameters。

建议：
- IP 继续 salted hash，但 salt 定期轮换；
- session id 改为短期/滚动，减少当前一年 cookie；
- external search 记录 `query_class`、长度、是否 exact-id、结果数 bucket；原始词默认 OFF；
- internal analytics 独立表/namespace；
- DNT + Global Privacy Control 生效；
- 管理操作用 AuditLog，不用 analytics。

### 13.3 Retention

- raw events：短 TTL（例如 30–90 天，由 policy 配置）；
- daily aggregates：长期；
- Web Vitals：短 TTL；
- privacy policy 中写明用途、保留期、退出方式。

### 13.4 Cloudflare Web Analytics

若使用 Cloudflare Web Analytics，只作为粗粒度站点指标；  
不得与 first-party analytics 重复当成“唯一访问量”，后台明确来源。

---

## 14. 安全与隐私强化

### S1 · Supply Chain
- lockfile frozen；
- lifecycle scripts allowlist；
- SBOM；
- Trivy；
- license gate；
- secret scanning；
- GitHub Action SHA pin；
- OCI digest + Cosign/provenance。

### S2 · API/Auth
- rate limit；
- JWT/refresh cookie 安全属性；
- admin/internal origin 精确 CORS；
- Cloudflare Access / MFA 优先放在 internal/admin 前；
- 高风险 publish/rollback 要 fresh auth / second confirmation。

### S3 · Upload
- content sniffing；
- decompression bomb 限制；
- parser timeout；
- bounded memory；
- Office 文件不执行宏/公式；
- uploaded HTML/script/code 继续拒绝；
- MinIO private bucket 默认 deny。

### S4 · External Fetch
现有 WeChat/X-MOL preview 的 host allowlist / SSRF 防线继续保留；  
redirect 每跳重新校验 host，DNS/private-range policy 有专门测试。

### S5 · WeCom
- secret redaction；
- callback crypto/signature；
- replay protection；
- allowlisted commands；
- audit；
- webhook egress timeout/backoff；
- 不允许消息内容直接成为 shell/SQL。

### S6 · Seed Request PII
- 独立 retention；
- admin-only；
- export/download 审计；
- 企业微信只发 reference id；
- 日志结构化 redaction；
- 删除/匿名化流程有测试。

---

## 15. Rust 核心组件迁移

本轮将 Rust 从“可能 someday”变成**明确工作流**，但生产采用仍由基准和一致性 Gate 决定。

### R0 · 前置

必须先完成：
- P2 import writer/finalize；
- 真实 2M 行 Python 基准；
- amd64/arm64 toolchain；
- current CI critical path；
- parser correctness fixtures。

### R1 · Workspace

建议：

```text
crates/
  soymutdb-core/        # pure Rust kernels
  soymutdb-py/          # PyO3/maturin binding
  soymutdb-wasm/        # 仅在浏览器热点被证实时创建
```

Cargo lock 纳入依赖治理、license、SBOM、CVE。

### R2 · 第一批迁移 kernel

优先级：
1. streaming SHA-256 / checksum pipeline；
2. BGZF block decode；
3. VCF/BCF record parse + canonical batch assembly；
4. GFF3/GTF tokenization + bounded validation；
5. FASTA streaming/index helpers。

Python worker 保留 orchestration，Rust 返回 typed batches/diagnostics。

### R3 · 对照与 fuzz

- 同一 fixture Python/Rust row-for-row；
- error row/column 一致；
- property tests；
- fuzz malformed VCF/GFF/FASTA；
- crash 不产生 partial published data；
- no unsafe block 除非有单独 review/理由。

### R4 · Go/No-Go

Production adoption 至少满足现有架构评估的高门槛：
- 吞吐约 ≥2×；
- 峰值内存显著下降（目标 ≥3×）；
- correctness parity 100%；
- amd64/arm64 CI 可维护；
- wheel/image 构建时间可接受。

未达门槛：PoC 可保留 benchmark，不把双实现长期上线。

### R5 · 浏览器/WASM

Gene Preview row packing/SVG geometry 只有在真实 profile 显示 JS 主线程成为瓶颈时才做 WASM。  
普通几十/几百 feature 不为“用了 Rust”而引入 WASM。

---

## 16. 既有 P1 / P2 正确性工作不被新路线覆盖

### P1-1 仍未关闭的门

继续要求真实：
- running API；
- seeded published release；
- unreleased sentinel；
- external/internal build；
- artifact-level ID-05；
- negative leakage；
- E2E-01/02。

没有 full-stack evidence 就保持 BLOCKED，不用 unit green 替代。

### P2-3 仍是数据主线第一优先级

当前已完成 P2-1/P2-2 manifest/fingerprint/control-plane 基础。  
下一步仍为：

```text
P2-3A shared import protocol / worker seam
P2-3B real ClickHouse 24.8 schema + MV dependency inventory
P2-3C staging writer
P2-3D checksum/row/context/schema verify
P2-3E coordinated finalize + recovery
P2-5 crash/retry/ambiguous ACK fixtures
P2-6 per-capability reopen review
```

本轮“支持更多格式”“Rust parser”全部排在 durable writer/finalize 之后。

---

## 17. 执行波次

### Wave 0 · 真源收敛 / Repo Health

- 更新本 plan；
- 生成 dependency baseline；
- 清生成物/冲突文档 inventory；
- 修 Cloudflare 文档真源；
- 建 local doctor；
- 建 security/privacy register。

**Gate W0：** 不再有互相冲突的当前架构文档；依赖、部署、feature flag、数据能力均可机器枚举。

### Wave 1 · 数据正确性 + 本地运行 + CI

并行：
- P2-3A/B；
- local lite/full；
- CI fast/integration 分层；
- secret/SBOM/dependency gate；
- P1-1 full-stack fixture 入口。

**Gate W1：** 新开发者在个人电脑可起栈；PR 能以一套命令复现关键 gate。

### Wave 2 · Design System + Gene Preview

- shared token；
- motion/color 收敛；
- primer-workbench viewport adaptation；
- Gene/Variant detail 接入；
- JBrowse deep link；
- visual/a11y/privacy tests。

**Gate W2：** Gene Preview 在 external 只显示 published public projection，坐标与 assembly/release 有证据。

### Wave 3 · Import Studio / Formats / Publication

- P2 writer/finalize；
- format registry；
- JSONL/Parquet module support；
- scientific format parser/writer 逐个完成；
- Admin Steps；
- Cloudflare artifact publisher。

**Gate W3：** 每个 capability 独立 Release Gate；不批量打开七类 imports。

### Wave 4 · 企业微信 + Analytics v2 + 双站 Cloudflare

- WeCom outbox push；
- analytics batching/privacy schema；
- external/internal Pages 项目；
- internal Access；
- preview/promotion/rollback。

**Gate W4：** 公开站、内部站、Admin 的访问、缓存、统计、发布权限完全分离。

### Wave 5 · 企业微信受控操作

- self-built app callback；
- identity map；
- status commands；
- preview publish；
- production publish/rollback with approval。

**Gate W5：** 从企业微信触发与从 Admin 触发产生相同 publication state/evidence/audit。

### Wave R · Rust Kernels

- R0 baseline；
- R1 workspace；
- R2 import kernels；
- parity/fuzz/benchmark；
- production Go/No-Go。

**Gate R：** 性能和维护收益达门槛才替换 Python 热路径。

---

## 18. Release Gate 汇总

| Gate | 必须证据 |
|---|---|
| Repo | dead/generated inventory + archive map + docs truth source |
| Local | clean machine doctor + lite/full startup + smoke |
| CI | PR fast + real PG/CH integration + artifact evidence |
| UI | visual/a11y/reduced-motion/dark/390px |
| Gene Preview | coordinate/strand/row-packing/release/assembly/leakage |
| Import | manifest/idempotency/staging/verify/finalize/retry/rollback |
| Format | sniff/schema/stream/memory/malformed fixture |
| WeCom Push | dedup/retry/redaction/no secret |
| WeCom Command | callback signature/replay/RBAC/approval/audit |
| Dual Site | separate artifact/origin/cache/SW/analytics + negative leakage |
| Cloudflare | exact-byte publish + digest + preview + rollback |
| Analytics | DNT/GPC + no raw PII/query default + TTL + batching |
| Security | secret scan/SBOM/CVE/CSP/upload/SSRF/auth |
| Rust | parity/fuzz/benchmark/native build |

---

## 19. 建议新增/修改的主要文件

```text
plan.md

packages/
  design-tokens/
  genome-view-model/

apps/web/src/components/genome/
apps/web/src/routes/genes/
apps/web/src/routes/variants/
apps/web/src/routes/mutants/

apps/api/app/services/
  notification_outbox_service.py
  wecom_service.py
  analytics_service.py
  import_* / publication_*

apps/api/app/api/v1/
  admin_integrations.py
  wecom_callback.py

apps/worker/src/soymutdb_worker/
  notifications/wecom.py
  publication/
  import/

crates/
  soymutdb-core/
  soymutdb-py/

scripts/
  local-* / dev entry
  cloudflare-publish.*
  acceptance.*
  dependency/security inventory

docs/
  architecture/
  ops/
  privacy/
  archive/
```

实际命名以现有目录风格为准；禁止仅为匹配本计划而进行无收益重命名。

---

## 20. 当前立即执行顺序

1. **P2-3A/P2-3B**：继续闭合 import control/data plane，不重开 feature flag。
2. **Repo truth cleanup**：Cloudflare 口径、tracked generated/temp、superseded docs。
3. **Local run**：把现有 compose-local/start-cloud-dev/setup-workspace 收到单一开发入口。
4. **CI split**：fast vs integration vs release/nightly，先缩短反馈再增加能力。
5. **Dependency low-risk upgrades**：AntD/TanStack patch/minor；同时建立 breaking lanes。
6. **Design tokens + Gene Preview**：先 pure view-model + tests，再接 Gene/Variant 页面。
7. **Cloudflare Direct Upload**：使用 verified artifact + Wrangler，不重建。
8. **WeCom push**：Seed Request / publish / run status；只出站。
9. **Analytics v2**：batch + privacy。
10. **Format registry + additional formats**：按 writer gate 逐个启用。
11. **WeCom inbound publish**：自建应用 callback + approval。
12. **Rust R0/R1/R2**：在稳定协议上迁移 compute kernels。

---

## 21. Definition of Done

本轮“完成”不是所有 checkbox 写成 implemented，而是以下事实都可复现：

- 一台个人电脑可按文档一条入口启动并跑 smoke；
- PR 有快速反馈，完整 gate 仍 fail-closed；
- 生产发布只上传 CI 验证过的字节；
- external/internal/admin 三个安全域不会相互泄漏；
- Gene Preview 科学坐标准确、可访问、release-aware；
- 数据导入没有 partial visible / duplicate facts；
- 新格式每个都有独立 parser/writer/retry/rollback 证据；
- 企业微信消息不含敏感信息，命令不能绕过 Admin/publication 权限；
- Analytics 不以长期 raw 搜索词/IP 为默认；
- 依赖、数据库和容器版本有机器可读 baseline；
- 过期代码/文档被删除或归档且有引用证明；
- Rust 只替换经过 benchmark 证明值得替换的 kernel，并保持 Python/control-plane 契约不变；
- 所有 feature flag 的开启都有 Release Gate evidence，而不是“功能看起来能用”。

> **最终约束：** 数据正确性、身份/隐私隔离、发布可追溯性优先于功能数量、框架升级和 Rust 化。任何工作流如果让未发布数据更容易暴露、让发布更难回滚、让管理员绕过审计，立即停止并回到上一个已验证状态。
