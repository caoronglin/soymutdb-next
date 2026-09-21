# Gate A · 合同/架构决策简报（待负责人拍板）

> **父计划：** `plan.md`（第二轮审计版 §18）+ Phase 0 报告 `docs/ops/phase-0-fact-baseline-2026-09-20.md`
> **日期：** 2026-09-20 ｜ **性质：** 决策材料，**非决策**。每项给 证据(E级) + 选项 + 建议 + 决策人 + 未定则阻断什么。
> **规则：** 拍板后各自升为正式编号 ADR（`docs/adr/`）；已有正式契约处引用现有 ADR，不重复造文档。
> **注意：** ADR-ID-01（ln vs public_id）已在 Phase 0 纠正为**误报并废止**（公开身份统一为 `public_id`，合规），故不在本 Gate A 列表。

---

## ADR-DATA-01 · `module_data_rows` 的角色

**证据（E1）：** 表定义 `migrations/versions/0015_module_tsv_imports.py`；写入方 `apps/worker`（module_tsv 导入，`tables.py:170`）；**apps/api（门户读取路径）无 reader**；唯一约束 `uq_module_data_rows_module_release_row` + 索引 `module_key`/`release_id` → 形态像 landing/staging，非 canonical。

**待决：** 这张表的长期角色是什么？谁拥有 schema evolution？数据保留多久？

| 选项 | 含义 | trade-off |
|---|---|---|
| A. **staging** | 临时落地，需 promotion 到 canonical `genes` 供门户读 | 需定义 consumer/promotion state/retention/cleanup/retry |
| B. **extension storage** | 插件扩展存储 | 需 schema/version/reader contract，不强回填 canonical |
| C. **canonical** | 直接作为门户读取源 | 与现有 `genes` 表职责重叠，改动大 |
| D. **删除** | 无长期用途则删 writer+表+migration+死代码 | 若后续要用则重造 |

**建议：** 倾向 **A（staging + 明确 promotion 到 `genes`）**——门户 `/genes` 读 `genes`，导入只写 `module_data_rows`，二者当前不连通（D6）。要么补 promotion/reader，要么明确它只是 staging 并配清理策略。**不能长期留一张只写不读的表。**

**决策人：** 数据/产品负责人。
**未定则阻断：** Phase 2 导入写入器设计（不知落地目标就无法定 finalize/promotion）。

---

## ADR-DATA-02 · 导入可见性 + 幂等协议

**证据（E1）：** D5 —— 7 类导入 fail-closed（`features.py:51-70` 默认 False；`ingest.py:448`、`data_adapters.py:125/135/148/158/171` raise `UnsupportedImportError`）。按 §5.3 判为**合法保护**，真正缺口是缺写入器/幂等协议。**CH 引擎待 T0-6 确认（RUNTIME_ONLY）。**

**待决：** 重试/崩溃/模糊 ACK 下如何保证"不产生重复事实 + portal 不看到半成品"？

| 选项 | 含义 | trade-off |
|---|---|---|
| **A. PG manifest 控制面 + 确定性 batch_id + CH dedup token(辅助) + publish 可见性 + 行数/校验和终检** | 应用层 manifest 主导，DB dedup 仅辅助 | 可靠、可恢复；实现量中 |
| B. 仅靠 CH insert_deduplication_token | 依赖 DB dedup history | **否决**：dedup window 有生命周期，MV/async insert 依版本配置而异，非 exactly-once |
| C. ReplacingMergeTree + FINAL | 后台合并去重 | eventual，普通 SELECT 仍可能见多版本；FINAL 有性能成本 |

**建议：** **A**。import_fingerprint 至少含 `source_sha256 + release_id + assembly_id + importer_version + schema_version + normalization_version + config_hash`（任何改变输出事实的配置都进 fingerprint）。manifest 状态机 `CREATED→PARSING→WRITING→VERIFYING→PUBLISHED ↘ FAILED`，明确哪状态对 portal 可见、谁恢复、FAILED 是否可 retry、旧 FAILED 如何清理。

**决策人：** 数据/架构负责人。
**未定则阻断：** Phase 2；也是安全重开 7 类导入开关（解 D5）与 D7 埋点批量化的前置。

---

## ADR-API-01 · `total_count` 兼容语义

**证据（E1）：** D3 —— `search_service.py:550`(`total_count=len(hits)`)、`:595`(`len(mutants)+len(genes)`)：**返回页内计数**；契约（`database-core-contract.md` §5）规定 `total_count=null` 表示隐藏总数。前端/generated client 的实际依赖未核查（部分 RUNTIME_ONLY）。

**待决：** `total_count` 到底是真总数 / null / 还是页计数？`number → null` 是否 breaking？

| 选项 | 含义 | trade-off |
|---|---|---|
| A. `total_count=null`（隐藏） | 语义纯净，符合契约 | 可能 breaking（客户端期待 number） |
| B. `total_count=真总数` | 信息完整 | 大表加 `COUNT(*)` 成本（见 D4） |
| C. 拆字段：`page_count`(当前页) + `total_count`(真总数或 null) | 最清晰 | 需 OpenAPI + client + 前端同步改 |

**建议：** **C**（消除"名叫 total_count 实则页计数"的歧义），并先做**兼容性评估**（OpenAPI 类型、前端是否依赖 number、第三方 consumer），必要时走 API 版本策略。**禁止继续复用错误语义。**

**决策人：** API/产品负责人。
**未定则阻断：** Phase 4 搜索改造、OpenAPI/client 重新生成、相关前端迁移。

---

## ADR-OPS-01 · 支持的部署架构

**证据（E1/E4 混合）：** Context —— 单 compose 多 profile；CI 有 amd64/arm64 双架构 + kind/k8s；Rust 评估提过 arm64 工具链疑问。**CH 集群拓扑未知（T0-6 RUNTIME_ONLY）。**

**待决：** 目标交付架构矩阵（哪些服务必须 amd64/arm64？DB/CH 单节点 vs 集群？）

| 选项 | 含义 | trade-off |
|---|---|---|
| A. amd64 主力 + arm64 尽力 | 前端/无状态双架构，DB/CH amd64 | 简单；arm64 非全功能 |
| B. 全栈双架构一等公民 | 所有服务双架构 | CI/构建/扫描成本翻倍（旧评估 P-7 已证是瓶颈） |
| C. 按服务定架构矩阵 | 明确每个镜像的目标 arch | 需逐服务评估，最精确 |

**建议：** **C 的轻量版**：明确"无状态/前端 = amd64+arm64；DB/CH/worker 重服务 = amd64 主力，arm64 视需求"。此决策直接影响 CI 关键路径与未来 Rust 内核（§17.1 前置 #8）的架构目标。

**决策人：** Ops/平台负责人。
**未定则阻断：** Phase 5 容量验证目标、Phase R（Rust）的架构目标、CI matrix 裁剪。

---

## 决策汇总表（请负责人逐项签）

| ADR | 一句话问题 | 建议 | 决策人 | 状态 |
|---|---|---|---|---|
| DATA-01 | `module_data_rows` 角色？ | A（staging→promotion 到 genes） | 数据/产品 | ☐ 待签 |
| DATA-02 | 导入幂等/可见性协议？ | A（PG manifest + 确定性 id + dedup 辅助 + publish + 终检） | 数据/架构 | ☐ 待签 |
| API-01 | `total_count` 语义？ | C（拆 page_count，先做兼容评估） | API/产品 | ☐ 待签 |
| OPS-01 | 部署架构矩阵？ | C 轻量版（无状态双架构，重服务 amd64 主力） | Ops/平台 | ☐ 待签 |

**Gate A 通过 = 以上四项签批。** 签批后：各自升为正式 ADR；Phase 1（P0 正确性，注意 D8 已解除，P0 项已大为减少）与 Phase 2（导入协议）方可按决策展开。
