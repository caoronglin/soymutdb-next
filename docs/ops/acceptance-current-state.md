# SoyMutDB 首版生产上线 —— 验收当前状态汇总（受跟踪）

> **状态**：本文是 QA（qa-acceptance）维护的**受 Git 跟踪**的验收状态汇总，作为
> `artifacts/acceptance/`（gitignored、可能被环境重置）的**权威副本**。`artifacts/acceptance/` 仅保留
> **运行期证据**（日志/报告/manifest），本文件保留**判定状态**。
> 本文件与 `docs/ops/production-readiness.md` §4（Go/No-Go 标准）、`docs/ops/route-b-seed-data-design.md`（t12）
> 一致，是发布放行的**权威当前状态**。
>
> **写者约定**：每次逐 Gate 更新判定后，同步更新本文件「§1 状态表」与「§2 结论」，并在文末「修订记录」登记。

---

## 0. 判定元信息

| 字段 | 值 |
|---|---|
| 上线版本 / 构建 | `image@sha256` 引用待 CI 发布（API/WORKER/MCP/JBROWSE） |
| 目标环境 | Staging（待） / Production（待）；`soymutdb.org` 域名未上线 |
| Release | `version=0.1.0`　`assembly=Wm82v4.0`　`species=Glycine max`（定义层已冻结） |
| 评估基线 | main `460b1529f` + 交付 t1–t16 |
| **当前总判定** | **❌ No-Go**（G10 种子 `--write` 未落地；G12 无真实数据可过验） |
| 最近更新 | 2026-08-23（t16 loader 反映） |

---

## 1. 门禁状态总表（G0–G16）

> 图例：`✅ Met`（实现层通过，待真实环境实证）；`⚠️ 待实证/待配置`；`❌ No-Go`（放行前置缺口）。
> 注意：多数 `✅` 是「实现/单元层通过」，尚未在真实 staging/production 运行实证；真正硬 No-Go 是 G10/G12。

| Gate | 判定 | 负责人 | 证据来源（受跟踪） | 说明 |
|---|---|---|---|---|
| G0 | ✅ Met | qa + data-platform | `docs/ops/first-release-data-plan.md` §2 | Release 命名/范围已冻结定义层；DB 实际 release 待种子 + D1 校验 |
| G1 | ⚠️ 待实证 | build-release | `docs/ops/production-readiness.md` + t4 | Node 26.10.0/pnpm 11.21.0/uv 固定；Dockerfile 统一；本机无 docker，待 CI docker build |
| G2 | ⚠️ 待实证 | build-release | t4 | `docker compose config` 全 profile 待 CI 实证（本机无 docker） |
| G3 | ⚠️ 待实证 | build-release | t4/t9 | gen-prod-secrets.sh/upgrade.sh bash -n + shellcheck 0 告警；全量脚本扫描待 CI |
| G5 | ✅ Met | frontend-platform | t5 | 生产严格模式 fail-closed + release-manifest.ts(SHA-256)；CI vitest 待跑 |
| G6 | ✅ Met | frontend-platform | t5 | `check-production-artifact.sh` 已测：干净 PASS / demo FAIL / --allow-demo PASS |
| G7 | ✅ Met | frontend-platform | t6 | admin `VITE_BASE_URL` 已验证；jbrowse 生产 base 正确 |
| G8 | ⚠️ 待实证 | frontend-platform | t6 | 生产 E2E harness 就绪（--list 4 tests）；需真实后端绿跑 |
| G9 | ✅ Met | frontend-platform | t6 | Demo 与生产 E2E 分离（独立 config/spec） |
| G10 | ❌ **No-Go** | data-platform | `docs/ops/route-b-seed-data-design.md`（t12）+ `scripts/seed_release_data.py`（t16）| 见 §3；种子 `--write` 未落地 |
| G11 | ✅ Met | data-platform | t8 + validate-release-data.sh | per-type flag + 422 + Admin 隐藏；module_data_rows write-only 不供门户 |
| G12 | ❌ **No-Go** | data-platform | `scripts/validate-release-data.sh`(t7) | 无真实数据可过验，且需真实 DB/CH/API；强依赖 G10 |
| G13 | ✅ Met | ops-security | t2/t9 | gen-prod-secrets + config.py fail-fast + upgrade 预检；tests 24/24 |
| G14 | ⚠️ 待实证 | ops-security | t2 | 备份/恢复脚本存在；无 drill 证据 |
| G15 | ⚠️ 待实证 | ops-security | `infra/monitoring/` | Prometheus/Grafana 存在；无 live 告警证据 |
| G16 | ⚠️ 待配置 | ops-security | t2 | gen-prod-secrets 校验 CORS 无 `*`；生产域名/CORS 白名单未配置 |

**计数**：✅ Met = 7（G0/G5/G6/G7/G9/G11/G13）；⚠️ 待实证/待配置 = 7（G1/G2/G3/G8/G14/G15/G16）；❌ No-Go = 2（**G10/G12**）。

> 门禁编号跳跃 G4（不在范围）；G0–G16 共 16 项。

---

## 2. 当前结论（判定口径）

首版生产上线暂判 **No-Go**：

- **G10**：受控真实数据种子（路线 B）loader 已实现
  `scripts/seed_release_data.py`（t16，`--check`/`--plan`/`--emit-sql` 可执行，含解析+校验+Demo/SMDB/Wm82.a4.v1 拒绝），
  但 **`--write` PG/CH 插入 + `data_sets`/`provenance`/`release_data_sets` + 置 ready 仍 fail-closed**
  （需 `SOYMUTDB_SEED_ENABLED=1` + asyncpg/clickhouse_connect，待数据源冻结+授权）。
- **G12**：`scripts/validate-release-data.sh`（t7）就绪（逻辑冒烟 27 PASS/exit 0），但**无真实数据可过验**，
  且需真实 DB/CH/API 环境运行；强依赖 G10 `--write` 落地。

其余门禁为**实现层通过**但缺 CI/真实环境运行证据（G1/G2/G3/G8/G14/G15/G16），证据到位后可转 ✅。

---

## 3. G10 / G12 放行前置（未冻结则维持 No-Go）

| # | 前置 | 责任 | 状态 |
|---|---|---|---|
| ① | 权威数据源与版本/许可（Wm82v4.0 FASTA/GFF3/VCF） | captain 拍板 + data-platform | 未冻结 |
| ② | `mutants.tsv` ↔ VCF 样本名映射 | data-platform | 未冻结 |
| ③ | CH `variant_facts` 已按 `upgrade_variant_facts_schema.sql` canonical 迁移 | data-platform/ops-security | 待确认 |
| ④ | 启用 `scripts/seed_release_data.py --write` 写库适配器（depends ①②③ + 授权）| data-platform | fail-closed，未启用 |

G10 退出路径：①②③ 冻结 + ④ 启用后，在 staging 跑 `--check`/`--emit-sql` 出 `seed-manifest.json`+`variant_facts.sql`
供 QA 复核解析/校验/无 Demo；数据源/迁移确认后启 `--write` 出 `data-query/seed-<release_id>.log`+`provenance` 记录；
随后运行 `scripts/validate-release-data.sh` 出 `validate-release-<release_id>.log`，QA 按 §6/§10 放行 G10、解 G12。

---

## 4. 证据来源与归属

> 判定状态以本文件 + `docs/ops/production-readiness.md` §4 为准；**运行期证据**默认放
> `artifacts/acceptance/`（gitignored，可能被环境重置，只作证据卷轴）。二者分工：
> - **判定状态**（受跟踪）：本文件、`production-readiness.md`、`first-release-data-plan.md`、`route-b-seed-data-design.md`、`route-b-data-source-checklist.md`（QA 选型/许可/验收映射清单，G10 前置①）。
> - **运行期证据**（gitignored）：`artifacts/acceptance/{build,production-build,e2e-production,data-query,security-env,backup-restore,monitoring,checksums}/`。
>
> **持久证据建议（QA 强制，避免重置丢失）**：运行种子/验证脚本时用
> **`SOYMUTDB_EVIDENCE_DIR=<持久目录>`**（推荐 **`docs/ops/evidence/`**，随交付提交、受 Git 跟踪）覆盖默认的
> `artifacts/acceptance/data-query/`。两个脚本均已支持该覆盖（默认仍 `artifacts/acceptance/data-query/`）：
> `scripts/seed_release_data.py`、`scripts/seed-release-data.sh`（`--manifest-out`/`--emit-sql` 默认目录取自
> `${SOYMUTDB_EVIDENCE_DIR:-artifacts/acceptance/data-query}`）。关键证据另在 `docs/ops/evidence/` 留一份。

| Gate 组 | 判定来源 | 运行期证据（artifacts/acceptance/） |
|---|---|---|
| G0/G10/G11/G12 | `first-release-data-plan.md`、`route-b-seed-data-design.md` | `data-query/`（seed-<rid>.log、seed-manifest.json、validate-release-<rid>.log、variant_facts.sql、provenance 查询） |
| G1–G3 | t4 | `build/` |
| G5–G7 | t5/t6 | `production-build/` |
| G8–G9 | t6 | `e2e-production/` |
| G13/G16 | t2/t9 | `security-env/` |
| G14 | t2 | `backup-restore/` |
| G15 | `infra/monitoring/` | `monitoring/` |
| — | — | `checksums/`（各类证据 SHA-256 清单） |

---

## 5. 修订记录

| 日期 | 变更 |
|---|---|
| 2026-08-23 | 初稿：按 t1–t11 冻结范围/标准/t2/t3 交付填初始态；G10/G12 判 No-Go。 |
| 2026-08-23 | 纳入 t12（route-b-seed-data-design.md）与 t16（`scripts/seed_release_data.py` loader）；G10 前置收敛为 §3 四项；G10 仍 No-Go 直至 `--write` 落地。 |
| 2026-08-23 | 确立「持久证据目录」约定（QA 强制）：数据平台两脚本已支持 `SOYMUTDB_EVIDENCE_DIR` 覆盖默认 `artifacts/acceptance/data-query`，首选 `docs/ops/evidence/`（受跟踪）；G10/G12 证据（seed-<rid>.log、seed-manifest.json、variant_facts.sql、validate-release-<rid>.log）落此。 |
| 2026-08-23 | **QA 复核 loader 实现层验证（t18，非生产虚拟数据）**：`docs/ops/evidence/route-b/`（check.log exit 0：chromosomes=2 genes=2 transcripts=1 exons=2 aliases=3 variants=3 mutants=2；plan.log、emit.log；seed-manifest.json 三文件真实 sha256；variant_facts.sql 3 行 canonical，release_key=9001、assembly_key=VirtualSoy1.0、consequence/impact 自 ANN，variant_type=SNP/subtype=SNV）。抽查：数据文件无 Demo 标记（只命中 fixture README 的自我描述）、基因前缀 VitGene.*、`--write` 未设 `SOYMUTDB_SEED_ENABLED` 时 exit 4（guard 生效，未写库）。**结论**：loader 的解析/校验/计数/无 Demo/幂等 guard 满足 route-b §6（D2/C5/P1）实现层契约。**不改变 G10/G12 No-Go**（真实数据注入仍需数据源 + `--write` 授权）。 |
| 2026-08-23 | **QA 复核 loader 增强（t18 补充）**：`parse_vcf` 现从 `ANN` 提取 `gene_id`/`gene_symbol`（此前仅 consequence/impact），支持 C3 基因引用校验。已重跑 `--emit-sql` 验证：`variant_facts.sql` 的 `gene_id`/`gene_symbol` = `VitGene.01G000100`/`VitGene.02G000200`，`gene_surrogate_id` 与 `surrogate_id()` 确定性函数一致（853938470/913130216），连续两次输出**完全一致（确定性）**。**结论**：C3 覆盖到位；`--write` guard 仍 exit 4（未写库）。不改变 G10/G12 No-Go。 |

> 系统状态：**等 captain 拍板 ①数据源/版本/许可 + ③CH `variant_facts` canonical 迁移**；数据平台已就绪（loader `--check`/`--emit-sql` 已在虚拟 fixture 上通过 QA 复核）。G10/G12 维持 No-Go。
