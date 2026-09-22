# Phase 2 · 导入协议与 canonical 数据链路

> **父计划：** `plan.md`（第二轮审计版 §14/§19）
> **前置：** Gate A 已签批（ADR-0004 module_data_rows=staging+promotion；ADR-0005 导入幂等/可见性）；
> Phase 0 完成（T0-6 ClickHouse 引擎已由 canonical DDL 解析，见报告 §CH-RESOLVED）。
> **Wave：** W2 ｜ **退出判据：** §3
> **⚠️ 高影响：** 本阶段触碰数据路径 + 迁移 + CH 写入。按 `AGENTS.md`，实现前须逐任务 review；
> 迁移须 upgrade/downgrade + PostgreSQL 集成测试；**本文件是计划，不等于实施授权。**

---

## 0. 引擎事实（T0-6，驱动本阶段设计）

- `variant_facts` = 纯 `MergeTree()`，单节点，`PARTITION BY (release_key, chromosome)`，ORDER BY 含 `gene_surrogate_id`/`mutant_line_surrogate_id`/`variant_id`，+4 PROJECTION。**无 CH 原生去重。**
- 汇总表 `SummingMergeTree`/`AggregatingMergeTree` 由 MV 从 variant_facts 聚合；**重复插入/回填会使汇总双倍累计**（DDL 注释证实）。→ **幂等是硬约束。**
- `module_data_rows`（PG）= landing/staging，按 `module_key` 泛化，门户无 reader（ADR-0004：staging + 按 module_key promotion）。

---

## 1. 任务清单

### P2-1 · PostgreSQL import manifest 控制面

**Files:** 新增 `apps/api/app/models/import_manifest.py`；新增迁移 `apps/api/migrations/versions/00XX_import_manifest.py`；`apps/api/app/services/import_manifest_service.py`
**Steps:**
1. 建 `import_manifests` 表：`import_id`(PK)、`fingerprint`(唯一)、`source_sha256`、`release_id`、`assembly_id`、`schema_version`、`importer_version`、`normalization_version`、`config_hash`、`status`、`expected_rows`、`written_rows`、`started_at`、`completed_at`、`failure_code`。
2. 状态机：`CREATED → PARSING → WRITING → VERIFYING → PUBLISHED ↘ FAILED`；`fingerprint` 唯一约束保证同语义输入只允许一个 logical import。
3. 迁移须 upgrade/downgrade + PG 集成测试（新建/回滚不丢 manifest）。
4. 定义：哪状态对 portal 可见（仅 PUBLISHED）、谁负责恢复、FAILED 是否可 retry、旧 FAILED 清理策略。

**Verify:** `.venv/bin/python -m pytest tests/test_import_manifest.py tests/test_migrations.py -q`（对 mamba PG）
**Accept:** manifest 表 + 状态机 + 唯一 fingerprint；迁移可升可降；集成测试绿。

---

### P2-2 · import fingerprint（语义完整）

**Files:** `apps/api/app/services/import_manifest_service.py`（或专用 `import_fingerprint.py`）
**Steps:**
1. 实现 `fingerprint = hash(source_sha256 + release_id + assembly_id + importer_version + schema_version + normalization_version + config_hash)`。
2. **任何改变输出事实的配置都进 fingerprint**；文件名/上传时间等非语义字段不进。
3. 单测：改任一语义输入 → fingerprint 变；改非语义字段 → fingerprint 不变。

**Verify:** `.venv/bin/python -m pytest tests/test_import_fingerprint.py -q`
**Accept:** fingerprint 语义契约有单测锁定（语义变/非语义不变）。

---

### P2-3 · variant_facts 幂等写入 + publish 可见性（解 D5 的 vcf）

**Files:** `apps/worker/src/soymutdb_worker/tasks/ingest.py`（`import_vcf`）；可能新增 staging 逻辑；`clickhouse_service.py`
**依赖：** P2-1、P2-2
**Steps:**
1. `import_vcf` 从"首行 raise"改为：算 fingerprint → 查/建 manifest → 写 `variant_facts`（按 batch_id 确定性）→ VERIFYING（row-count/checksum 对账）→ PUBLISHED。
2. **finalize 机制（利用 PARTITION BY (release_key, chromosome)）**：优先 **partition 级 replace**——按 release 把该 release 的分区 drop 后重写，避免重复累计 SummingMergeTree 汇总；备选：确定性 batch_id + insert dedup token（辅助）+ 终检。**不得只靠 CH dedup。**
3. **publish 可见性**：portal 查询只认 PUBLISHED 的 release 数据；半写状态不可见。
4. crash/retry/ambiguous-ACK：见 P2-5 夹具驱动。
5. canonical schema 字段与 `clickhouse_service.py` SELECT 对齐（契约测试锁定）。

**Verify:** 对 mamba PG + CH（若有实例）跑 P2-5 夹具；字段契约测试。
**Accept:** 重试不产生重复事实、不双倍累计汇总；半写对 portal 不可见；checksum 不符不 publish。

---

### P2-4 · module_data_rows → canonical promotion（ADR-0004）

**Files:** `apps/worker/src/soymutdb_worker/tasks/*`（module_tsv 路径）；`module_data_rows` 消费者；portal 读取表（`genes` 等）
**依赖：** P2-1
**Steps:**
1. 定义 `module_key → canonical 表` 映射（如 genes-shaped module → `genes`）。
2. promotion：staging 行在 PUBLISHED 后按 mapping 写入 canonical 表；retention/cleanup/retry 语义落地。
3. 门户读取路径改为读 canonical（promotion 后），消除 D6"只写不读"。
4. 无长期用途的 module_key 按 ADR-0004 删 writer+死代码。

**Verify:** module_tsv 导入 → promotion → 门户 `/genes` 可见；PG 集成测试。
**Accept:** 导入数据经 promotion 进入门户读取路径；staging 有 retention/cleanup。

---

### P2-5 · 导入 retry/crash/ambiguous-ACK 夹具（期望结果表）

**Files:** `apps/worker/tests/test_import_idempotency_fixture.py`（Phase 0 已建骨架，此处补全）
**依赖：** P2-3/P2-4
**Steps:** 按 `plan.md` §10 期望结果表逐条实现并断言（每条有明确期望，不只"全绿"）：
same file+same release+assembly+config → 无第二份逻辑事实；same content+diff filename → 同上；
diff release/assembly → 独立数据；parser/config 版本变 → 由 fingerprint 决定是否重导；
crash before first batch / mid-write / after write before publish；CH timeout after ambiguous ACK；
invalid record；checksum mismatch；duplicate batch；row count mismatch。

**Verify:** `.venv/bin/python -m pytest tests/test_import_idempotency_fixture.py -q`
**Accept:** 每个 case 有明确期望断言；no partial visibility；ambiguous ACK 安全。

---

### P2-6 · 能力重开门（仅 1–5 完成后）

**Files:** `apps/api/app/core/features.py`（谨慎）；回归测试
**Steps:**
1. 仅在 P2-1~P2-5 完成且夹具全绿后，才把 7 类导入开关按类型逐个置 `true`（先 vcf，再其余）。
2. 每个重开类型附：该类型的幂等夹具 + 端到端导入→publish→门户可见的证据。
3. **未完成协议前不重开任何开关**（维持 fail-closed，P1-2 已锁 422）。

**Verify:** 逐个类型的导入→publish→portal 可见；夹具绿。
**Accept:** 重开类型有完整证据；未重开类型仍 422。

---

## 2. 风险与回滚

| 风险 | 缓解 |
|---|---|
| SummingMergeTree 双倍累计 | partition 级 replace + 终检；夹具覆盖 duplicate batch |
| 半写对 portal 可见 | publish 可见性规则（仅 PUBLISHED）；crash 夹具 |
| 迁移损坏 | upgrade/downgrade + PG 集成测试；前滚恢复路径文档化 |
| 误重开开关 | P2-6 门禁；未完成不重开 |
| CH 无实例无法实测 | 先有 CH 实例（或静态 DDL + PG 侧 manifest 先落地，CH 写入后验） |

**回滚：** manifest 迁移可 downgrade；variant_facts 写入按 release partition 可 drop 重来；开关可回置 false。

---

## 3. 阶段退出判据（Gate-2）

```bash
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  .venv/bin/python -m pytest tests/test_import_manifest.py tests/test_import_fingerprint.py \
  tests/test_import_idempotency_fixture.py tests/test_migrations.py -q
```

**DoD：**
- [ ] P2-1 manifest 控制面 + 状态机 + 唯一 fingerprint（迁移可升可降）
- [ ] P2-2 fingerprint 语义契约锁定
- [ ] P2-3 variant_facts 幂等写入 + publish 可见性 + 终检；无重复事实、无汇总双倍累计
- [ ] P2-4 module_data_rows → canonical promotion（按 module_key），门户可见
- [ ] P2-5 retry/crash/ambiguous-ACK 夹具全绿（每条明确期望）
- [ ] P2-6 仅在 1–5 完成后按类型重开开关，各有证据
- [ ] no partial visibility；fingerprint 覆盖全部语义变换输入
