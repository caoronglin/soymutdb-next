# SoyMutDB 全项目消融实验计划（2026-09-26 / HEAD 8e78116fd）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

维护者：总控（dev-expert 六步闭环，审计与执行分离）。本文件是**执行计划**，不是结论。

## 1. 目标与判据

对当前工作树（HEAD `8e78116fd`）逐条跑**消融实验**：每个保护性不变量都做「对照（因素在场）→ 消融（只改这一项）→ 比对」三步，
用于回答「这道守卫是否真的在起作用」，而不是「历史测试是否曾经通过」。

判定口径（每个场景必须落到其一）：

| 判定 | 含义 | 处置 |
| --- | --- | --- |
| `GUARD-ACTIVE` | 消融单一因素后行为翻转，对照通过 | 守卫有效，记为已验证 |
| `GUARD-INERT` | 消融后行为不变 | 守卫可能是死代码，必须单独列出 |
| `GAP` | 对照就已经失败 | 当前缺陷，列出复现命令 |

证据分级沿用 `docs/dev/pi-agent-ablation-audit-execution-2026-09-26.md` §1（E1 真实运行 > E2 源码追踪 > E3 历史文档）。
每条结论必须附：精确命令 + 退出码 + 关键输出行。`SKIPPED` 不算 `PASS`。

## 2. 范围（覆盖 `docs/dev/database-core-contract.md` §3 契约矩阵）

| 工作流 | 场景 | 执行者 | 报告 |
| --- | --- | --- | --- |
| W1 身份与公开边界 | ID-01～ID-04 + 草稿/未发布负例 | 子代理 A | `identity.md` |
| W2 assembly 与跨版本 | ASM-01～ASM-05 | 子代理 B | `assembly.md` |
| W3 缓存与站点隔离 | CTX-01～CTX-03 + `private,no-store` | 子代理 C | `cache-site.md` |
| W4 前端与查询键 | UI-01、UI-02、P1-04 游标键 | 子代理 D | `frontend.md` |
| W5 导入管线与投影 | VCF assembly 身份、样本错配、CH 汇总清理、staging DDL | 子代理 E | `pipeline.md` |
| W6 制品与 E2E | ID-05 双站制品扫描、E2E-01/02 可行性 | 子代理 F | `artifact-e2e.md` |

## 3. 环境（本次已实测）

- Node `v24.19.0`；`apps/api/.venv/bin/python` 3.14.6；`apps/worker/.venv/bin/python` 3.14.6。
- PostgreSQL 16 **已在后台作业常驻**，`127.0.0.1:55432`，`soymutdb` trust 认证；
  二进制 `.mamba-root/envs/postgres16/bin`；每个工作流使用**独立库** `abl_<domain>`。
- 探查证据：`abl_probe` 库上 `test_search_database_integration.py -k "public_id_only or persistence_key or ..."` → `3 passed`（1.22s）。
- `apps/api/tests/conftest.py` 支持 `SOYMUTDB_TEST_DATABASE_URL`（跳过 testcontainers，保留受控 schema 生命周期）。
- Playwright 浏览器缓存存在（`~/.cache/ms-playwright/chromium-*`）；`e2e/playwright-public.config.ts` 为同源 mock 离线配置。
- 机器 96 vCPU / ~1TB RAM；turbo/esbuild 受限时加 `GOMAXPROCS=2 RAYON_NUM_THREADS=1`。

## 4. 消融协议（所有子代理必须遵守）

1. **对照**：先跑真实代码路径，记录命令与输出。
2. **消融**：只中和**一个**因素，优先级 `monkeypatch` > 独立 harness > 单行临时改源码（改完必须还原并给出 `git diff` 证据）。
3. **比对**：给出 `GUARD-ACTIVE / GUARD-INERT / GAP` 判定。
4. 子代理**不修改**生产源码的持久状态，不提交，不动 `packages/genome-view-model`（有未提交改动）。
5. 交付必须含中文报告 + 未验证项小节；不得把「测试存在」写成「已验证」。

## 5. 出口

- 6 份分报告 + 总控汇总 `README.md`（含逐条判定、GAP 清单、未验证项）。
- 总控复核：抽查每个工作流至少一条命令并复跑，核对报告与原始输出一致。
