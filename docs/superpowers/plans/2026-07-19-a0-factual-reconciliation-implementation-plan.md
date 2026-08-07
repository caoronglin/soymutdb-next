# Plan A0：事实、契约与迁移闸门实施计划

> 本文件定义 observational-only reconciliation、A0-local 测试夹具、只读审计和 disposable PostgreSQL 演练；不实现产品领域模型，也不授权 A1、生产迁移、生产写入切换或 publication 实现。Oracle Gate 2 的计划级 verdict 为 `APPROVE_WITH_NON_BLOCKING_NOTES`，因此可启动本文定义的有界 A0 实施；这不表示 A0 evidence 已完成、A1 已解锁或任何生产动作已获批准。

**Goal：** 以仓库实际 runtime、Alembic revision graph、disposable PostgreSQL 实际 schema、ORM metadata、OpenAPI/client/Admin/Worker 消费关系、完整 fresh-target catalog baseline 和可恢复数据库演练为事实，产出一套可审计、可复现、fail-closed 的 A0 reconciliation evidence package。

**Non-goals：** 不新增业务表或领域对象；不新增或修改产品 migration；不修改产品代码、配置、依赖、部署和既有备份脚本；不写入生产或其它非-disposable 数据库；不执行自动 Git action。

**Execution rule：** 实施者必须按第 10 节的 TDD 顺序执行。每个数据库 action 只有在本计划定义的 guard 成功、attestation 成功、preceding event 已落入 manifest 后才能执行。任何事实无法观察、profile 无法证明、artifact 缺失、退出码非零、owner/reviewer 缺失或 trusted-boundary 缺失，均保持 `BLOCKED`。

---

## 0. A0 不可越过的边界与统一 contract

### 0.1 Observational-only 边界

- A0 只读取已有仓库、已有 migration、已有 ORM/OpenAPI/client/Admin/Worker wiring 和受控 disposable target 的实际状态，并生成 reconciliation、unresolved queue、canonical snapshots、full-catalog baseline、migration/restore evidence。
- 不新增 `rl_species`、`rl_scientific_object`、`rl_dataset_release`、`rl_publication_manifest` 或其它产品/domain ORM 表；不把 legacy `Release` 改写成新领域对象。
- 不写新的 Alembic migration；迁移演练只运行现有 revision chain，并记录实际 head、实际 reviewed reversible boundary、schema drift、seed semantic drift 和阻断原因。
- 不修搜索拆分、publication saga、Admin capability、audit outbox、Worker 幂等或静态构建 dispatch；这些只作为事实和契约差异被记录。
- `Release.is_public`、`published_at`、页面可访问性和旧字段状态不能单独证明 historic publication。
- A0 的 `PASS` 只表示本文定义的 observational evidence chain 完整；不代表 Oracle Gate 2 已批准、不代表 A1 已解锁，也不授权任何生产动作。
- 计划不要求、不执行 `git add`、`git commit`、`git push`、merge 或 PR 创建。

### 0.2 已核验本地 runtime 事实

| 事实 | A0 contract |
|---|---|
| API 数据库依赖 | API package 只声明 SQLAlchemy async + `asyncpg`。所有 A0 Python DB helper 使用 `create_async_engine`、`async with`、`connection.run_sync`，CLI 边界使用 `asyncio.run`；不新增同步 PostgreSQL driver。 |
| Alembic import 顺序 | `apps/api/migrations/env.py:17-19` 先 import config，再 import database/models；`apps/api/app/core/database.py:24` 在 import 时捕获 module-level `settings=get_settings()`。A0 不依赖 import 后改变 environment 来切换 target。 |
| Alembic URL wiring | `apps/api/migrations/env.py:26-27` 调用 cached `get_settings()`，再覆盖 Alembic Config URL；online path 使用 `async_engine_from_config`。A0 不使用 `Config` URL、`get_settings.cache_clear()` 或进程内 environment mutation 证明 target。 |
| Settings 来源 | `apps/api/app/core/config.py` 使用 `SOYMUTDB_` prefix、`.env`、lru-cached `get_settings()` 和 default development URL。`.env`、default development URL、预热 settings cache 和 `alembic.ini` 中带 password 的 dev URL 都是 poisoned/default fixture fact，绝不是 A0 target fallback。 |
| Alembic path | `apps/api/alembic.ini` 使用 relative `script_location=migrations`；CLI child cwd 必须是 `${rl_root}/apps/api`，absolute `PYTHONPATH` 必须是 `${rl_root}/apps/api:${rl_root}`。 |
| Worker context | Worker registry cwd 必须是 `${rl_root}`，`PYTHONPATH=${rl_root}/apps/worker/src`；Worker 不承担 A0 PostgreSQL helper。 |
| Cluster identity | guard 实际读取 `pg_control_system().system_identifier`、`current_database()`、`inet_server_addr()`、`inet_server_port()`；system identifier 是 primary cluster identity，endpoint 只是 context，`version()` 不是 identity。 |

### 0.3 A0 必须交付的 evidence

1. `docs/reconciliation/a0-runtime-migration-reconciliation.md`：README、API/Worker Python、Node/前端、Docker/Compose、Alembic config/path、service entrypoint、child-process context 和 poisoned-default findings。
2. `docs/reconciliation/a0-schema-orm-openapi-reconciliation.md`：revision/head、deployed schema、ORM metadata、OpenAPI routes/schemas、TypeScript consumers、Admin affordances、Worker registry、catalog baseline 和 semantic drift 矩阵。
3. `docs/reconciliation/a0-legacy-release-evidence.md`：每条 legacy `Release` 的默认 DatasetRelease 映射、historic PublicationRelease 证据或 `unresolved` 原因。
4. `docs/reconciliation/a0-unresolved-items.jsonl`：每个无法证明的映射、契约、部署或 evidence 条件一行，包含稳定 `rl_` code、source path、canonical digest、owner 和 blocking state。
5. `artifacts/a0/` 下只保存 redacted command records、runtime facts、identity digest events、attestation digest events、revision graph、canonical snapshots、semantic projections、catalog baseline summary、opaque archive/list refs、digest、size、format、redacted list category summary、retention/deletion result 和 versioned gate manifest；不保存 raw custom archive、raw full list、password、token、完整 URL 或完整 environment。
6. A0-local audit scripts、fixtures/tests、真实 Alembic trajectory、fresh rebuild proof、synthetic-source backup/restore rehearsal、semantic validator 和 independent-review gate validator。

### 0.4 统一 execution context

| 操作 | cwd | 必须的 absolute `PYTHONPATH` / input |
|---|---|---|
| OpenAPI snapshot | `${rl_root}/apps/api` | `${rl_root}/apps/api:${rl_root}`；只在 child process start 前提供 API path |
| Worker registry | `${rl_root}` | `${rl_root}/apps/worker/src` |
| Alembic child | `${rl_root}/apps/api` | `${rl_root}/apps/api:${rl_root}`；`script_location=${rl_root}/apps/api/migrations` |
| A0 module / pytest | `${rl_root}` | `${rl_root}/apps/api:${rl_root}`；使用 `python -m tools.a0...` |

所有 launcher 先解析并校验绝对 `${rl_root}`：必须存在 `apps/api/alembic.ini`、`apps/api/migrations`、`apps/api/app` 和 `tools/a0`。Python 进程内部不得写入 `PYTHONPATH`，不得追加 `sys.path`。OpenAPI、Worker、Alembic、A0 module/pytest 不得互用错误 cwd。

### 0.5 Profile registry、marker 与 observed identity

#### External provisioner contract

disposable target 的 provisioner/registry 在 A0 writer scope 外维护；A0 只读验证。registry 每个 profile 必须保存 expected tuple：

```text
(system_identifier, database, role, marker, expires_at, run_id)
```

其中 raw `system_identifier` 和 opaque `marker` 只存在于受限 profile registry/child environment，不进入普通 evidence。独立 provisioner 以数据库级 custom GUC 设置 marker：

```sql
ALTER DATABASE <bare-database-name>
  SET soymutdb_a0.disposable_marker = <opaque-marker>;
```

guard 只读 `current_setting('soymutdb_a0.disposable_marker', true)` 并与 registry expected marker 比较；禁止把 COMMENT、对象描述或对象名称当作安全 marker。marker 不由 guard 写入或修改。

#### Guard contract

`tools/a0/rl_disposable_target.py` 是每个 Task 3/4/7 database action 的唯一 guard。它通过 asyncpg URL 的内部 profile resolution 创建 `create_async_engine`，使用 `async with` 和 `connection.run_sync`，CLI 使用 `asyncio.run`。actual preflight 必须读取：

```sql
SELECT current_database(),
       inet_server_addr()::text,
       inet_server_port(),
       (pg_control_system()).system_identifier,
       current_setting('soymutdb_a0.disposable_marker', true);
```

guard 必须在连接前校验 profile host/name policy、opaque profile role、registry expiry、registry run ID、expected database 和 caller context；连接后校验实际 database、endpoint、raw system identifier、marker 和 registry tuple。以下任一项失败，立即 `BLOCKED`：

- system identifier 读取失败；
- `current_database()` mismatch；
- `inet_server_addr()` 或 `inet_server_port()` 为 NULL/Unix socket；
- marker 缺失、不相等或 registry 过期；
- role、run ID、configured profile digest、database 或 endpoint context mismatch；
- host/name policy failure；
- caller-controlled `PGSERVICE`、`PGOPTIONS` 或其它 profile override 出现在 child environment。

raw system identifier 只在 guard/attestation child 和受限 registry 内参与比较。所有 evidence、manifest、review attestation 统一使用：

```text
identity_digest_version = "a0.identity.v1"
system_identifier_digest = SHA-256(raw system_identifier)
```

不存在“raw-or-digest”两种 evidence 形态；evidence 永远只有 `system_identifier_digest`。endpoint 只记录 `endpoint_context_digest`、observed port 和 redacted configured components。source/restore distinctness 只比较内部 raw `(system_identifier,current_database)`，证据层同时记录两个 digest 和 distinctness result。`localhost`/`127.0.0.1`、service alias/IP 指向同一 raw key 时必须拒绝。

中文 why-comment：

```python
# 为什么：hostname、IP 和 service alias 可能指向同一 cluster；只有实际 system identifier 加 current_database 才能证明 distinctness。
```

### 0.6 Profile resolver 与 sanitized child environment

`tools/a0/rl_prepare_pg_profile.py` 是内部 resolver/library，不是 shell export command。它只接受 `--profile-env NAME` 或 opaque `--profile-id ID` 的内部调用，拒绝 URL、password、database target positional input；它返回受限 `rl_profile_record`，包含内部 asyncpg URL、redacted configured components、bare database name、profile digest、role、run ID 和 raw secret handle。raw URL 只在 process-start child environment 使用，永不进入 argv、logs、artifact 或 evidence。

`rl_prepare_pg_profile` 不提供 shell export interface。`tools/a0/rl_run_pg_client.py` 和 `tools/a0/rl_alembic_child.py` 在 fresh process 中调用 resolver，再构造 sanitized environment。sanitized environment 只允许必要的 `PATH`、固定 locale、`PGHOST`、`PGPORT`、`PGUSER`、受控 `PGPASSFILE`、必要时的 profile-derived `PGDATABASE`，以及 Alembic child 专用的 process-start `SOYMUTDB_DATABASE_URL`、profile digest、role、run ID 和 opaque attestation request ref；必须删除/拒绝继承 `PGSERVICE`、`PGOPTIONS`、`PGPASSWORD`、其它 caller-controlled `PG*` override 和控制字符。

profile component 校验拒绝 NUL、newline、carriage return、其它 ASCII control character、未允许的 host/database/role 字符和过长值。profile registry 返回的 raw URL 不由 `Config.set_main_option` 注入，也不通过运行中 environment mutation 选择 target。

### 0.7 `rl_run_pg_client.py` controlled launcher

所有 shell-level database command 只调用 Python module，不直接调用 PostgreSQL binary。`tools/a0/rl_run_pg_client.py` 的 operation allowlist 只有 `dump`、`list`、`restore`；不接受 arbitrary argv、arbitrary executable、arbitrary SQL、URL、password 或 filesystem path。它使用：

```python
subprocess.run(rl_argv, shell=False, env=rl_sanitized_env,
               capture_output=True, check=False)
```

`rl_argv` 只由 operation/profile/opaque archive ref 内部生成。pgpass 内容由 launcher 内部创建，runtime directory mode 为 `0700`，passfile mode 为 `0600`；每个 pgpass field 先把 `\` 编码为 `\\`，再把 `:` 编码为 `\:`，并拒绝 NUL/newline/control character。cleanup 失败写入 blocking evidence。测试必须断言写入的 pgpass 行可被 libpq 按原字段还原，不能只断言文件存在。

restore 的唯一内部 direct-restore argv contract 是：

```python
rl_restore_argv = [
    "pg_restore",
    "--dbname=" + rl_profile.rl_bare_database_name,
    "--no-password",
    "--exit-on-error",
    "--single-transaction",
    "--no-owner",
    "--no-privileges",
    rl_restricted_archive_path,
]
```

`rl_profile.rl_bare_database_name` 和 `rl_restricted_archive_path` 只存在 launcher memory/受限 runtime；redacted argv template 只记录 profile role、operation 和 opaque refs。full URI、password、bare database name、restricted path 都不写入 logs/evidence。因为没有 database selection option 时 `pg_restore` 会把 SQL 写到 stdout，所以 direct restore 必须使用上面的 bare database name；launcher 断言 restore stdout 为空，任何 restoration SQL、非预期 stdout、nonzero exit、archive 缺失或 partial restore 都 `BLOCKED`。`--single-transaction` 与 parallel restore 不同时启用。

dump 的内部 argv 只使用 `pg_dump --format=custom --no-password --no-owner --no-privileges --file=<restricted-file>`；list 的内部 argv 只使用 `pg_restore --list --no-password <restricted-archive>`；database connection parameters 来自 sanitized libpq environment。launcher 记录 exit code、stdout digest、stderr digest、start/end timestamp 和 redacted argv template，不记录 raw output。dump/list/restore 均禁止 `--clean`、`--create`、`--jobs`；restore 额外固定 `--exit-on-error --single-transaction`，并不启用 parallel restore。

### 0.8 Full fresh-target catalog baseline

窄化的“没有业务表/没有 migration table”检查不是 fresh-target proof。`tools/a0/rl_catalog_baseline.py` 必须使用与目标同 PostgreSQL major/minor、同 init 参数/locale 的 init reference baseline，并记录：

```text
catalog_baseline_version
postgresql_version_context
init_configuration_digest
explicit_system_baseline_allowlist_digest
catalog_read_digest
```

baseline 是显式 object/class allowlist，不使用 `pg_*` 名称前缀 shortcut。inventory 必须覆盖并逐项比较：

- schemas/namespaces；
- `pg_class` 的 tables、views、materialized views、sequences、foreign tables、partitioned tables 和其它 relkind；
- columns/defaults；indexes、constraints、rules；
- types、domains、composites、enums、ranges；
- procedures/functions、triggers、policies；
- extensions、languages、collations；
- FDW、servers、user mappings；
- publications、subscriptions；
- large objects；
- event triggers；
- text-search configurations/templates/dictionaries/parsers；
- casts、operators、opclasses、opfamilies、transforms；
- statistics；
- security labels；
- ownership、ACL、tablespace；
- PostgreSQL version/init baseline 和 catalog read success。

unknown relkind、unknown catalog object class、unexpected owner/ACL/policy/trigger/extension/publication/subscription/FDW object、baseline version mismatch、init digest mismatch、catalog read failure 或 tunnel/alias 将同名 object 映射到错误 identity，均 `BLOCKED`。full fresh proof 必须产生 versioned inventory artifact、explicit allowlist comparison 和 action count；failure 时 Alembic/restore action count 为零。

### 0.9 Canonical snapshot 与 semantic projection

`tools/a0/rl_snapshot_database.py` 是 Task 4/7 唯一 canonical async snapshot producer；其它 module 不生成第二种 schema signature。snapshot payload 使用：

```text
canonical_snapshot_version = "a0.canonical-snapshot.v2"
semantic_projection_version = "a0.semantic-projection.v1"
identity_digest_version = "a0.identity.v1"
```

payload 必须包含 redacted configured identity、role、run ID、`system_identifier_digest`、database、endpoint context digest/port、observed Alembic revision、canonical structural JSON、count-independent `schema_signature` 和 semantic projection；payload **不包含自身 file digest 字段**，parent manifest/sidecar 在文件写完后负责 SHA-256。

canonical structural JSON 必须 deterministic sort，并包含：

- tables；
- columns：name/type/nullability/normalized default；
- primary key、foreign keys、unique、check；
- indexes 与 normalized definition；
- sorted enum labels/order；
- extensions name/version；
- observed Alembic revision。

`schema_signature` 只对 structural JSON 的 canonical bytes 做 SHA-256；row counts 不进入 structural JSON，因此 count 变化不能改变 schema signature。key-table semantic projection 另行比较 `present`、`count`、content digest 和 sequence state。missing key table 必须 `present=false` 且不写 count；实际空 table 才是 `present=true,count=0`。

semantic projection 必须是 versioned、content-only、无 raw row values 的 representation：每张 key table 由 policy 明确 stable key、stable ordering、included fields 和 excluded nondeterministic fields；每行生成 canonical normalized token digest，按 stable key/token 排序后生成 table content digest。UUID、timestamp、volatile/generated fields 只能按显式 versioned exclusion policy 排除；policy 缺失或新增未声明 nondeterministic field 时 `BLOCKED`。每项同时记录 count、content digest、sequence name、last_value、is_called；sequence state 不被 content digest 吞掉。

中文 why-comment：

```python
# 为什么：schema signature 只表达 structural contract；semantic projection 才表达 fixture 内容和 sequence state，二者不能互相替代。
# 为什么：raw row values 可能含敏感内容；digest 保留可比较性而不把数据正文写入 evidence。
```

### 0.10 Synthetic source、restricted archive/list 与 retention

full custom archive、content digest 和 restore rehearsal 只允许使用 profile registry 明确标记为 `synthetic-non-sensitive` 的 fixture source，并且要求 `RL_A0_SYNTHETIC_SOURCE_APPROVED=1`。普通、生产、未分类或敏感 source 在 dump/content action 前即 `BLOCKED`。synthetic fixture 的 stable key/field policy、seed digest 和 non-sensitive classification 必须进入 manifest。

`RL_A0_RESTRICTED_ROOT` 必须由外部 trusted provisioner 预先创建为 mode `0700`，且 producer root 不得拥有删除 reviewer evidence 的权限。custom archive 和 full list 只在该 root 中创建为 mode `0600` 文件；文件引用只通过 opaque archive/list ref 传递。

普通 `artifacts/a0` 只保存：archive/list opaque ref、archive SHA-256、size、format、redacted list category summary、expected-object result、retention result 和 deletion result。不得保存 raw archive、full list bytes、restricted absolute path、sensitive object path 或 raw list line。list parser 在 restricted root 内运行；unknown/dangerous object class、invalid grammar、unexpected object category、missing expected object 或 parse failure 在 restore 前 `BLOCKED`。

retention/deletion 是 application policy：成功路径必须记录 restricted file deletion/retention outcome；删除失败、retention policy failure、restricted root cleanup failure 或 mode/ownership drift 都阻止 gate success。清理不会删除 normal evidence manifest。

### 0.11 Versioned manifest 与 independent review

`tools/a0/rl_emit_gate_evidence.py` 只接受 versioned manifest 和 artifact root，不接受任意 bool summary。manifest version 为 `a0.gate.v2`，每个 action record 至少包含：

```text
action_id
action_type
run_id
role
preceding_guard_event_id
attestation_event_id
identity_digest_version
system_identifier_digest
endpoint_context_digest
configured_identity_redacted
redacted_argv_template
exit_code
stdout_sha256
stderr_sha256
started_at
finished_at
plan_source_sha256
spec_source_sha256
tool_source_sha256
test_source_sha256
executable_version
artifact_refs_and_sha256
owner
reviewer
```

manifest 顶层还必须绑定 runtime context、profile policy、catalog baseline、canonical snapshot policy、semantic projection policy、migration trajectory、archive policy、source stability、restore-empty proof、list summary、legacy evidence、unresolved queue 和 reviewer attestation ref。每个 nonzero exit、missing artifact、digest mismatch、identity mismatch、list invalidity、source drift、semantic drift 或 cleanup failure 都是 `BLOCKED`。

independent reviewer attestation 是单独 object，由 `tools/a0/rl_reviewer_attestation.py` 在 reviewer-controlled non-producer-writable root 或 trusted CI context 写入；producer 不得写入、覆盖或修改它。reviewer 在 producer evidence 完成后重新计算 bundle digest，并记录 manifest digest、bundle digest、review source refs、reviewer identity、timestamp、decision、findings、trusted boundary/access-control reference。gate 拒绝 producer-root 内的 attestation、缺 attestation、attestation 早于 producer evidence、bundle digest 不匹配或 reviewer root writable。

本地文件本身不能 cryptographically prove hostile-writer integrity；计划只把 trusted boundary 明确限定为 reviewer-controlled filesystem/ACL 或 trusted CI identity。没有该 boundary，A0 保持 `BLOCKED`，不能把本地 self-written review 文件当作独立 review。

---

## 1. 文件地图、责任边界与证据 owner

### 1.1 现有只读事实来源

| 事实 | 路径/符号 | A0 读取重点 | producer / consumer / reviewer / owner |
|---|---|---|---|
| runtime baseline | `README.md:52-100` | Node、pnpm、Python、API start/build | `rl_collect_runtime_facts` / runtime report / `rl_runtime_reviewer` / `rl_runtime_evidence_owner` |
| API package | `apps/api/pyproject.toml:[project]` | Python baseline、FastAPI、async SQLAlchemy、Alembic、test deps | `rl_collect_runtime_facts` / runtime/schema / `rl_runtime_reviewer` / `rl_runtime_evidence_owner` |
| settings | `apps/api/app/core/config.py` | prefix、`.env`、cache、default dev URL | `rl_collect_runtime_facts` / child binding report / `rl_migration_reviewer` / `rl_migration_evidence_owner` |
| API database import | `apps/api/app/core/database.py:24` | module-level settings capture | `rl_collect_runtime_facts` / child binding report / `rl_migration_reviewer` / `rl_migration_evidence_owner` |
| Alembic env | `apps/api/migrations/env.py:17-19,26-27` | import order、cached settings、async_engine_from_config、URL override | `rl_alembic_child` / attestation / `rl_migration_reviewer` / `rl_migration_evidence_owner` |
| Alembic config | `apps/api/alembic.ini` | relative script location、poisoned dev URL | `rl_collect_runtime_facts` / runtime report / `rl_runtime_reviewer` / `rl_runtime_evidence_owner` |
| ORM registry | `apps/api/app/models/__init__.py`, `Base.metadata` | ORM versus migration/deployed facts | `rl_reconcile_schema` / schema report / `rl_schema_reviewer` / `rl_schema_evidence_owner` |
| migrations | `apps/api/migrations/versions/` | graph、head、enums、extensions、downgrade edges、seed policy | `rl_migration_rehearsal` / trajectory / `rl_migration_reviewer` / `rl_migration_evidence_owner` |
| existing tests | `apps/api/tests/conftest.py:test_engine` | legacy `create_all` fact only | `rl_collect_runtime_facts` / runtime report / `rl_schema_reviewer` / `rl_runtime_evidence_owner` |
| Compose/deploy | `docker-compose*.yml`, `infra/docker`, `deploy/linux`, `deploy/scripts` | path/entrypoint/backup facts | `rl_collect_runtime_facts` / runtime report / `rl_runtime_reviewer` / `rl_runtime_evidence_owner` |
| API/client/Admin/Worker | API router, `packages/api-client/src`, `apps/web/src`, `apps/admin/src`, Worker main/tasks | actual consumer/registry map | `rl_reconcile_contracts` / contract report / `rl_contract_reviewer` / `rl_contract_evidence_owner` |
| legacy Release | `apps/api/app/models/content.py:Release`, releases API, migration `0001` | old fields and evidence chain | `rl_classify_legacy_releases` / legacy report/unresolved / `rl_legacy_reviewer` / `rl_legacy_evidence_owner` |

### 1.2 A0-local modules/tests and ownership

以下是获 Gate 2 有界授权后实施 A0 时可创建或修改的文件清单。每个 runtime evidence 输出仍须在相应任务的受控输入、测试和审查完成后生成；不得伪造实际数据库、archive 或 gate evidence。

| Task | 文件 | producer | consumer | reviewer | evidence owner |
|---|---|---|---|---|---|
| 1 | `tools/a0/rl_collect_runtime_facts.py` | `rl_collect_runtime_facts` | runtime report/gate | `rl_runtime_reviewer` | `rl_runtime_evidence_owner` |
| 1 | `apps/api/tests/a0/test_rl_runtime_facts.py` | pytest runner | Task 1 collector | `rl_runtime_reviewer` | `rl_runtime_evidence_owner` |
| 2 | `tools/a0/rl_prepare_pg_profile.py` | internal profile resolver | guard/client/Alembic child | `rl_database_safety_reviewer` | `rl_profile_evidence_owner` |
| 2 | `tools/a0/rl_run_pg_client.py` | shell-free PostgreSQL launcher | dump/list/restore evidence | `rl_database_safety_reviewer` + `rl_restore_reviewer` | `rl_client_evidence_owner` |
| 2 | `apps/api/tests/a0/test_rl_prepare_pg_profile.py` | test runner | resolver | `rl_database_safety_reviewer` | `rl_profile_evidence_owner` |
| 2 | `apps/api/tests/a0/test_rl_run_pg_client.py` | test runner | launcher | `rl_database_safety_reviewer` + `rl_restore_reviewer` | `rl_client_evidence_owner` |
| 2 | `tools/a0/rl_disposable_target.py` | async observed identity guard | every DB action | `rl_database_safety_reviewer` | `rl_guard_evidence_owner` |
| 2 | `apps/api/tests/a0/test_rl_disposable_target.py` | pytest-asyncio runner | guard/distinctness | `rl_database_safety_reviewer` | `rl_guard_evidence_owner` |
| 3 | `tools/a0/rl_catalog_baseline.py` | full-catalog inventory/baseline | fresh rebuild/restore-empty/schema report | `rl_schema_reviewer` + `rl_migration_reviewer` | `rl_catalog_evidence_owner` |
| 3 | `apps/api/tests/a0/test_rl_catalog_baseline.py` | pytest-asyncio runner | catalog baseline | `rl_schema_reviewer` + `rl_migration_reviewer` | `rl_catalog_evidence_owner` |
| 3 | `tools/a0/rl_reconcile_schema.py` | migration/ORM/deployed comparison | schema report | `rl_schema_reviewer` | `rl_schema_evidence_owner` |
| 3 | `apps/api/tests/a0/test_rl_schema_reconciliation.py` | test runner | schema comparison | `rl_schema_reviewer` | `rl_schema_evidence_owner` |
| 4 | `tools/a0/rl_alembic_child.py` | fresh Alembic child launcher | migration trajectory | `rl_migration_reviewer` | `rl_migration_evidence_owner` |
| 4 | `tools/a0/rl_alembic_attestation.py` | opt-in connection attestation hook | Alembic action manifest | `rl_migration_reviewer` | `rl_attestation_evidence_owner` |
| 4 | `apps/api/tests/a0/test_rl_alembic_child.py` | test runner | child binding | `rl_migration_reviewer` | `rl_migration_evidence_owner` |
| 4 | `apps/api/tests/a0/test_rl_alembic_attestation.py` | test runner | actual connection identity proof | `rl_migration_reviewer` | `rl_attestation_evidence_owner` |
| 4/7 | `tools/a0/rl_snapshot_database.py` | **唯一 canonical async snapshot producer** | migration semantic proof/backup restore | `rl_migration_reviewer` + `rl_restore_reviewer` | `rl_snapshot_evidence_owner` |
| 4/7 | `tools/a0/rl_semantic_projection.py` | versioned content/sequence projection | migration/restore comparison | `rl_schema_reviewer` + `rl_restore_reviewer` | `rl_semantic_evidence_owner` |
| 4/7 | `apps/api/tests/a0/test_rl_snapshot_database.py` | pytest-asyncio runner | canonical snapshot | `rl_migration_reviewer` + `rl_restore_reviewer` | `rl_snapshot_evidence_owner` |
| 4/7 | `apps/api/tests/a0/test_rl_semantic_projection.py` | pytest-asyncio runner | semantic projection | `rl_schema_reviewer` + `rl_restore_reviewer` | `rl_semantic_evidence_owner` |
| 4 | `tools/a0/rl_migration_rehearsal.py` | trajectory runner | migration/gate manifest | `rl_migration_reviewer` | `rl_migration_evidence_owner` |
| 4 | `tools/a0/rl_migration_rehearsal.sh` | Python-only launcher wrapper | migration logs | `rl_migration_reviewer` | `rl_migration_evidence_owner` |
| 4 | `apps/api/tests/a0/test_rl_migration_rehearsal.py` | test runner | trajectory | `rl_migration_reviewer` | `rl_migration_evidence_owner` |
| 5 | `tools/a0/rl_reconcile_contracts.py` | contract map producer | OpenAPI/client/Admin/Worker report | `rl_contract_reviewer` + `rl_worker_contract_reviewer` | `rl_contract_evidence_owner` |
| 5 | `apps/api/tests/a0/test_rl_contract_reconciliation.py` | test runner | contract map | `rl_contract_reviewer` | `rl_contract_evidence_owner` |
| 6 | `tools/a0/rl_classify_legacy_releases.py` | conservative classifier | legacy report/unresolved | `rl_legacy_reviewer` | `rl_legacy_evidence_owner` |
| 6 | `apps/api/tests/a0/test_rl_legacy_release_evidence.py` | test runner | legacy classifier | `rl_legacy_reviewer` | `rl_legacy_evidence_owner` |
| 6 | `apps/api/tests/a0/fixtures/rl_legacy_release_cases.json` | controlled fixture | legacy tests | `rl_legacy_reviewer` | `rl_legacy_evidence_owner` |
| 7 | `tools/a0/rl_archive_policy.py` | restricted archive/list policy | backup/restore/gate | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| 7 | `tools/a0/rl_backup_restore_rehearsal.py` | archive/list/semantic validator | restore result/gate | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| 7 | `tools/a0/rl_backup_restore_rehearsal.sh` | Python-only rehearsal wrapper | backup/restore action records | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| 7 | `apps/api/tests/a0/test_rl_archive_policy.py` | test runner | restricted policy | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| 7 | `apps/api/tests/a0/test_rl_backup_restore_rehearsal.py` | test runner | validator/orchestrator | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| 8 | `tools/a0/rl_reviewer_attestation.py` | independent review object writer | gate validator | `rl_gate_reviewer` | `rl_review_evidence_owner` |
| 8 | `tools/a0/rl_emit_gate_evidence.py` | versioned manifest validator | gate result | `rl_gate_reviewer` | `rl_gate_evidence_owner` |
| 8 | `apps/api/tests/a0/test_rl_reviewer_attestation.py` | test runner | reviewer boundary | `rl_gate_reviewer` | `rl_review_evidence_owner` |
| 8 | `apps/api/tests/a0/test_rl_gate_evidence.py` | test runner | manifest/gate | `rl_gate_reviewer` | `rl_gate_evidence_owner` |

缺任一 producer、consumer、reviewer 或 owner，相关 Task 直接 `BLOCKED`。所有新增第一方函数、变量、类型、fixture、module-local command name 使用 `rl_` 前缀；框架 hook、Alembic revision、environment key、third-party API 和已有公共接口遵循既有名称。非显然 identity、marker、migration、digest、retention 和 privilege 规则必须有简短中文 why-comment。

### 1.3 Evidence storage map

| 内容 | 存储位置 | 允许内容 |
|---|---|---|
| runtime/schema/contract/legacy reports | `docs/reconciliation/` | redacted facts、computed digest、owner/reviewer |
| ordinary A0 artifacts | `artifacts/a0/` | JSON summaries、opaque refs、SHA、size、format、category summary、exit/stream digests |
| custom archive/full list | `RL_A0_RESTRICTED_ROOT` | only synthetic source files, mode `0600`, restricted ACL |
| profile registry/raw identity | external restricted registry | raw system identifier、opaque marker、raw URL/secret handle、expected tuple |
| reviewer attestation | reviewer-controlled `RL_A0_REVIEW_ROOT` or trusted CI | independent bundle digest、review decision、trusted boundary reference |

普通 artifacts 不得引用 restricted absolute path；只使用 opaque ref。restricted root、review root 的 mode/ownership/access-control observation 是 gate evidence 的一部分。

---

## 2. Task 1：runtime facts、poisoned defaults 与 execution-context evidence

### Files

- Create: `tools/a0/rl_collect_runtime_facts.py`
- Create: `tools/a0/__init__.py`
- Create: `apps/api/tests/a0/test_rl_runtime_facts.py`
- Create: `docs/reconciliation/a0-runtime-migration-reconciliation.md`

### TDD steps

1. 先写 failing tests：
   - 记录 README/API/Worker Python requirements、Node baseline、Compose/Docker facts，不写 secret/value。
   - 记录 `env.py:17-19` import order、`database.py:24` module settings capture、`env.py:26-27` cached settings override、`async_engine_from_config` online path。
   - 记录 `SOYMUTDB_` prefix、`.env`、lru cache、default development URL 和 `alembic.ini` password-bearing development URL 均是 poisoned/default fact，不能当 disposable target。
   - 验证四行 execution context、absolute root、profile-only input、no in-process `PYTHONPATH`/settings switching。
2. 从 `${rl_root}` 运行 focused test；在 collector 尚未存在时预期失败。
3. 实现最小静态 collector 和 redacted report renderer，不连接数据库、不修改产品文件。
4. 对版本/路径差异写中文 why-comment：A0 记录事实，不替实施者决定升级、降级或修复方向。
5. 重新运行 focused tests；只在后续实施阶段生成 runtime artifact。

### Commands and expected results

命令是实施计划，不代表本次已运行：

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_runtime_facts.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_collect_runtime_facts \
      --project-root "${rl_root}" \
      --output "${rl_root}/artifacts/a0/runtime-facts.json"
)
```

预期：测试覆盖事实冲突和 redaction；不可取得的 command version 记录 observed unavailable 与 blocking reason，不能猜测版本；报告明确 ini/dev URL 不是 target fallback。

### Review checkpoint

`rl_runtime_reviewer` 必须检查 README、两个 pyproject、config/database/env.py、alembic.ini、Compose、Dockerfile、service entrypoint 和 artifact digest。缺 owner、reviewer、source digest 或 poisoned-default classification，Task 1 `BLOCKED`。

---

## 3. Task 2：profile resolver、shell-free client、async guard 与 identity registry

### Files

- Create: `tools/a0/rl_prepare_pg_profile.py`
- Create: `tools/a0/rl_run_pg_client.py`
- Create: `tools/a0/rl_disposable_target.py`
- Create: `apps/api/tests/a0/test_rl_prepare_pg_profile.py`
- Create: `apps/api/tests/a0/test_rl_run_pg_client.py`
- Create: `apps/api/tests/a0/test_rl_disposable_target.py`
- Capture: `artifacts/a0/identity/rl_guard-events.jsonl` (digest-only fields)

### TDD steps

1. 先写 failing tests：
   - resolver 只接受 profile env/opaque profile ID；拒绝 URL、password、database target positional input。
   - profile components 拒绝 NUL、newline、carriage return、ASCII control character、非法 role/name，并拒绝 caller-controlled `PGSERVICE`/`PGOPTIONS`。
   - pgpass field 正确 escape `:` 和 `\`；runtime directory `0700`、passfile `0600`；cleanup failure 为 blocking。
   - launcher 使用 `subprocess.run(..., shell=False)`，operation allowlist 精确只包含 dump/list/restore；不接受 arbitrary argv/executable/SQL。
   - launcher 的 restore internal argv 使用 bare profile database name、no-password、exit-on-error、single-transaction、no-owner、no-privileges；不含 URI、password、destructive cleanup/creation/parallel flags。
   - direct restore stdout 为空；stdout 含 SQL、archive absent、nonzero exit 或 simulated partial restore 都 `BLOCKED`。
   - guard async 读取 `current_database()`、endpoint、`pg_control_system().system_identifier` 和 custom GUC marker；读取失败、NULL endpoint、database mismatch、marker mismatch、expired registry、run mismatch 都 `BLOCKED`。
   - `localhost`/`127.0.0.1` 和 service alias/IP 指向同一 raw observed key 时 distinctness `BLOCKED`；不同 cluster/database 才可继续。
2. 运行 pytest-asyncio/unit focused tests；在实现不存在时预期失败。
3. 实现 resolver、launcher 和 guard；不修改 API config，不改变 app settings cache，不在运行中修改 `PYTHONPATH`/`sys.path`。
4. 加入中文 why-comment：pgpass escape 防止字段边界改变，shell-free launcher 防止 profile/argv 注入，bare DB name 防止 `pg_restore` 把 SQL 写回 stdout。
5. 重新运行 tests；只有所有 fail-closed cases 和 safe disposable case 具备明确断言，后续 database action 才可引用 Task 2。

### `rl_run_pg_client.py` public contract

CLI 只接：

```text
--operation dump|list|restore
--profile-env NAME 或 --profile-id ID
--archive-ref OPAQUE_REF（list/restore）
--run-id ID
--role ROLE
--evidence PATH
```

它内部调用 `rl_prepare_pg_profile`，构造 passfile 和 sanitized env，并根据 operation 生成 fixed argv。所有 output 以 bytes capture 后只留下 SHA-256；list raw bytes 写入 restricted root，由 `rl_archive_policy.py` 解析并只输出 category summary。restore 必须把 direct target 设置为 bare internal database name，不接受 URI。任何 launcher exit code 非零直接阻断对应 action；正常 TDD red-phase command 不进入 gate evidence manifest。

### `rl_disposable_target.py` evidence contract

guard event 固定包含：

```text
guard_event_version = "a0.guard.v2"
run_id
role
profile_digest
configured_identity_redacted
registry_tuple_digest
identity_digest_version = "a0.identity.v1"
system_identifier_digest
observed_database
endpoint_context_digest
observed_port
marker_digest
expires_at
command_template_digest
owner
reviewer
```

guard event 不含 raw system identifier、raw marker、URL、password、PG options 或 raw SQL output。guard role 只读验证 registry/GUC，不修改 DB/settings。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_prepare_pg_profile.py \
           apps/api/tests/a0/test_rl_run_pg_client.py \
           apps/api/tests/a0/test_rl_disposable_target.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_disposable_target \
      --profile-env RL_A0_SCHEMA_PROFILE \
      --role schema \
      --run-id "${rl_run_id}" \
      --evidence "${rl_root}/artifacts/a0/identity/rl_guard-events.jsonl"
)
```

预期：unit/async tests 覆盖 marker GUC、registry tuple/expiry、alias resistance、control injection、pgpass escaping、no interactive password、exact argv、stdout and zero-call failures；命令输出不包含 URL/password/raw identity。

### Review checkpoint

`rl_database_safety_reviewer` 必须核对 external registry tuple、custom GUC read-only marker、sanitized env、profile digest、identity digest version、shell-free launcher、pgpass mode/escape、exact operation allowlist 和 cleanup evidence。任何 COMMENT marker、caller override、raw identity evidence 或 producer-owned raw secret artifact 都阻断 A0。

---

## 4. Task 3：Alembic/ORM/deployed reconciliation 与 full catalog baseline

### Files

- Create: `tools/a0/rl_catalog_baseline.py`
- Create: `tools/a0/rl_reconcile_schema.py`
- Create: `apps/api/tests/a0/test_rl_catalog_baseline.py`
- Create: `apps/api/tests/a0/test_rl_schema_reconciliation.py`
- Modify only as an A0 evidence output: `docs/reconciliation/a0-schema-orm-openapi-reconciliation.md`
- Capture: `artifacts/a0/schema/rl_revision-graph.json`
- Capture: `artifacts/a0/schema/rl_catalog-baseline-summary.json`
- Capture: `artifacts/a0/schema/rl_deployed-introspection.json`

### TDD steps

1. 先写 failing tests：
   - ORM-only table 不得进入 deployed facts；deployed-only object、migration-only object、enum/extension/constraint drift 分类为 blocking/unresolved。
   - same-version/init reference baseline mismatch、catalog read failure、unknown relkind、unknown object class、view、sequence、function、domain、extra extension、same-name tunnel/alias mismatch 均 `BLOCKED`，所有 action call count 为零。
   - catalog inventory 覆盖 schemas/namespaces、all requested `pg_class` relkinds、columns/defaults、indexes/constraints/rules、types/domains/composites/enums/ranges、procs/triggers/policies、extensions/languages/collations、FDW/server/user mappings、publications/subscriptions、large objects、event triggers、text search、casts/operators/opclasses/opfamilies/transforms、statistics、security labels、ownership/ACL/tablespace。
2. 运行 focused tests，确认 baseline/reconciliation module 尚未存在时失败。
3. 实现 async catalog inventory；每个 database query 前先 guard，使用 `create_async_engine`、`async with`、`connection.run_sync`、`asyncio.run`。
4. 使用 explicit system-baseline allowlist 和 same-version/init reference，不使用 object-name prefix shortcut。
5. 重新运行 tests；baseline mismatch 只能保持 `BLOCKED`，不能通过删对象或写入 marker 解决。

### Full catalog baseline contract

`rl_catalog_baseline` 输出 `a0.catalog-baseline.v2` summary 和 sidecar digest。inventory 的每一类 object 都记录 stable class、schema/name identity digest、relkind/object-kind、owner/ACL/tablespace digest、definition digest 和 expected-system-baseline decision；不写敏感正文。system baseline allowlist 由同版本/init reference 生成并由 reviewer 固定 digest，不能由当前目标反向生成。

Fresh-target proof 必须满足：

- PostgreSQL version context 与 reference 一致；
- init configuration digest 与 reference 一致；
- catalog read 全部成功；
- 每个 observed object/class 都能在 explicit system allowlist 或 expected A0 migration/fixture policy 中解释；
- 未出现 user/business/migration object、unexpected schema/namespace、unexpected relkind、routine、domain、extension、publication、subscription、FDW、policy、trigger、ACL/owner/tablespace 或其它未知类；
- `alembic_version`、migration enums 和迁移/业务对象缺失在 full inventory 中被证明，而不是用简单表名列表替代。

### Schema comparison contract

`rl_reconcile_schema` 输出分离的 `alembic`、`orm`、`deployed`、`catalog_baseline` 和 `semantic` 列。Task 3 raw introspection 不是 canonical snapshot；Task 4/7 只消费 `rl_snapshot_database.py` 的 versioned representation。Release drift 按 migration `0001` 与 ORM 实际字段逐项记录，不在 deployed inspection 前选择任一侧为 truth。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_catalog_baseline.py \
           apps/api/tests/a0/test_rl_schema_reconciliation.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_catalog_baseline \
      --profile-env RL_A0_SCHEMA_PROFILE \
      --reference-baseline-ref RL_A0_REFERENCE_BASELINE \
      --output "${rl_root}/artifacts/a0/schema/rl_catalog-baseline-summary.json" \
      --run-id "${rl_run_id}"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_reconcile_schema \
      --profile-env RL_A0_SCHEMA_PROFILE \
      --catalog-baseline "${rl_root}/artifacts/a0/schema/rl_catalog-baseline-summary.json" \
      --output "${rl_root}/artifacts/a0/schema"
)
```

预期：unknown class、catalog failure、baseline mismatch 和 identity mismatch 在任何 migration/restore action 前停止；report 含 owner/reviewer/source digest，且没有 second canonical schema signature。

### Review checkpoint

`rl_schema_reviewer` 和 `rl_migration_reviewer` 必须逐项复核 reference version/init digest、explicit allowlist、所有 catalog categories、unknown object policy、guard ordering、ORM/deployed drift 和 no-write boundary。窄化 empty check 不能替代 full-catalog baseline。

---

## 5. Task 4：fresh Alembic child、connection attestation、migration trajectory

### Files

- Create: `tools/a0/rl_alembic_child.py`
- Create: `tools/a0/rl_alembic_attestation.py`
- Create: `tools/a0/rl_snapshot_database.py`（Task 4/7 唯一 canonical producer）
- Create: `tools/a0/rl_semantic_projection.py`
- Create: `tools/a0/rl_migration_rehearsal.py`
- Create: `tools/a0/rl_migration_rehearsal.sh`（只调用 Python module）
- Create: `apps/api/tests/a0/test_rl_alembic_child.py`
- Create: `apps/api/tests/a0/test_rl_alembic_attestation.py`
- Create: `apps/api/tests/a0/test_rl_snapshot_database.py`
- Create: `apps/api/tests/a0/test_rl_semantic_projection.py`
- Create: `apps/api/tests/a0/test_rl_migration_rehearsal.py`
- Capture: `artifacts/a0/migration/rl_reviewed-reversible-boundary.json`
- Capture: `artifacts/a0/migration/rl_migration-seed-policy.json`
- Capture: `artifacts/a0/migration/rl_pre-rebuild-catalog-summary.json`
- Capture: `artifacts/a0/migration/rl_initial-snapshot.json`
- Capture: `artifacts/a0/migration/rl_downgrade-snapshot.json`
- Capture: `artifacts/a0/migration/rl_final-snapshot.json`
- Capture: `artifacts/a0/migration/rl_trajectory.json`

### Fresh-target precondition

`RL_A0_DATABASE_PREPROVISIONED` 未设置、为空或不是显式 `1` 时立即 `BLOCKED`。通过后仍必须：

1. guard role `migration-rebuild`；
2. actual async canonical pre-snapshot；
3. actual async full-catalog baseline comparison；
4. `rl_empty_before_rebuild` proof 记录 full inventory/version/init/allowlist digests；
5. 所有 precondition 失败路径的 Alembic child invocation count 为零。

不得用日志文字、空值、预期值或预置 bool 代表 fresh empty。baseline mismatch、unexpected system catalog class、catalog read error、migration-defined enum、user table、`alembic_version` 或任何未解释 object 都阻断。

### Fresh Alembic child contract

每个 Alembic action 都由独立 fresh process 执行：

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_alembic_child \
      --operation upgrade \
      --profile-env RL_A0_MIGRATION_PROFILE \
      --attestation-ref "${rl_attestation_ref}" \
      --run-id "${rl_run_id}"
)
```

launcher parent 只解析 opaque profile、校验 absolute root/context、构造 process-start child env，并以 `subprocess.run(..., shell=False)` 启动 child；`SOYMUTDB_DATABASE_URL` 只在 child environment 注入，永不进入 argv/log/artifact。child 在任何 `app.*` import 之前验证：

- `SOYMUTDB_DATABASE_URL` 存在且 digest 与 selected profile digest 相等；
- `SOYMUTDB_` settings env 是 process-start value，不是 `.env`/default development fallback；
- `PGSERVICE`、`PGOPTIONS`、`PGPASSWORD` 和 caller-controlled `PG*` override 不存在；
- absolute cwd、absolute `PYTHONPATH`、absolute script location 和 opaque attestation ref 正确；
- role/run/profile registry tuple 未过期且 guard event 已成功。

child 不调用 `get_settings.cache_clear()`，不修改已经 import 的 settings，不在进程内改变 environment，不用 Config URL 选择 target。`apps/api/migrations/env.py:17-19` 的 import order 和 `database.py:24` module capture 由 process-start env 正确绑定；`env.py:26-27` 的 cached settings override 只能看到该 child 的 selected env。ini dev URL 和 config default URL 即使存在也不能继续。

### Opt-in actual connection attestation

`tools/a0/rl_alembic_attestation.py` 是 A0-local opt-in hook。只有 child environment 存在 opaque `RL_A0_ATTESTATION_REQUEST_REF` 时，child 才在 Alembic import 前安装 hook；没有 ref 时不运行 hook，也不改变 migration semantics。hook 在 `async_engine_from_config` 返回 engine 后，为该 engine 的 actual connection path 安装只读 identity attestation listener，读取相同的 identity/marker query，写入受限 attestation registry，并在第一次 migration connection 使用前比较：

```text
selected_profile_digest
configured_identity_redacted
role
run_id
identity_digest_version
system_identifier_digest
observed_database
endpoint_context_digest
observed_port
marker_digest
preceding_guard_event_id
```

actual connection identity 与 preceding guard 不一致、attestation 缺字段、request ref 不存在、registry expiry/run mismatch 或 hook 无法读取 identity 时，hook 抛出 `BLOCKED`，Alembic action call 不进入 migration body。hook 只读取 identity，不改 Config URL、schema、revision、transaction 或 migration operation。

中文 why-comment：

```python
# 为什么：外部 wrapper 只能证明“准备过某个 profile”；只有 env.py 实际建立的 async engine connection attestation 才能证明 Alembic 真正连接了该 target。
```

### Programmatic Alembic config

programmatic path 只设置一次 absolute script location：

```python
rl_config = Config(str(rl_root / "apps/api/alembic.ini"))
# 为什么：env.py:26-27 以 process-start settings.database_url 选择目标；script location 必须唯一且绝对。
rl_config.set_main_option("script_location", str(rl_root / "apps/api/migrations"))
```

不设置 `sqlalchemy.url`，不重复设置 `script_location`，不以 Config URL、ini URL、default dev URL 或 cache clear 选择 target。

### Reviewed reversible boundary and seed semantics

revision graph 必须生成 dynamic head 和 reviewed boundary artifact。`RL_A0_DOWNGRADE_REVISION` 只能引用 reviewer-approved artifact；该 revision 必须是 dynamic head 的 strict ancestor，且从 boundary 到 head 的 traversed edge set 必须明确记录为 nonempty。boundary 等于 head、edge set empty、graph digest mismatch、reviewer 缺失或 downgrade edge 不可逆，均 `BLOCKED`。

`rl_migration-seed-policy.json` 是 versioned semantic policy，明确 migration-declared seed tables、stable key/field policy、nondeterministic exclusions 和 expected seed projection。initial/final migration proof 必须比较 structural signature、revision、extensions/enums、key-table presence/count、seed content digest 和 sequence state。

### Fixed migration trajectory

1. full guard + full catalog precondition；失败时 Alembic child call count 为零；
2. reviewer boundary/seed policy validation；
3. guard + attestation request `migration-upgrade-initial`；fresh child `upgrade head`；
4. child 返回后立即读取 actual observed initial head 和 initial canonical/seed semantic snapshot；
5. guard + attestation request `migration-downgrade`；fresh child downgrade reviewed boundary；
6. child 返回后立即读取 actual observed downgrade revision；
7. guard + attestation request `migration-upgrade-final`；fresh child `upgrade head`；
8. child 返回后立即读取 actual observed final head，必须等于 dynamic ScriptDirectory head；
9. final canonical structural + migration seed semantic projection compare；不重复读取最终 revision作第二份 evidence。

### Required migration tests

`test_rl_alembic_child.py` 必须覆盖 poisoned ini URL/default URL、missing process-start settings env、`.env` source、prewarmed settings cache、changed environment after import、wrong root/cwd/PYTHONPATH、PGSERVICE/PGOPTIONS override 和 no action call。

`test_rl_alembic_attestation.py` 必须覆盖 selected profile digest mismatch、actual system identity mismatch、marker/role/run expiry mismatch、missing attestation request、hook import order和 actual `async_engine_from_config` connection proof。

`test_rl_migration_rehearsal.py` 必须覆盖 full-catalog empty failure zero child calls、strict-ancestor/no-op boundary、nonempty edge set、initial/final seed drift、same count different content、sequence state drift、immediate observed revisions 和 no duplicate final read。

`test_rl_snapshot_database.py` 必须覆盖 ordering、default normalization、constraint/enum/extension/revision drift、count-independent schema signature、missing-vs-empty，以及 snapshot payload absence of self-digest field。

`test_rl_semantic_projection.py` 必须覆盖 same count/different content、stable ordering、nondeterministic exclusion policy、sequence `last_value/is_called` drift、raw row value absence 和 policy version mismatch。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_alembic_child.py \
           apps/api/tests/a0/test_rl_alembic_attestation.py \
           apps/api/tests/a0/test_rl_snapshot_database.py \
           apps/api/tests/a0/test_rl_semantic_projection.py \
           apps/api/tests/a0/test_rl_migration_rehearsal.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_migration_rehearsal \
      --profile-env RL_A0_MIGRATION_PROFILE \
      --boundary-ref RL_A0_REVIEWED_BOUNDARY \
      --seed-policy-ref RL_A0_MIGRATION_SEED_POLICY \
      --catalog-baseline-ref RL_A0_REFERENCE_BASELINE \
      --output "${rl_root}/artifacts/a0/migration" \
      --run-id "${rl_run_id}"
)
```

预期：flag unset、full baseline failure、attestation mismatch、boundary invalid、semantic seed drift 和 any nonzero child exit 均 `BLOCKED`；只有 actual initial/downgrade/final reads 和 reviewed policy 全部一致才能继续。

### Review checkpoint

`rl_migration_reviewer` 必须复核 child process start env、import order、attestation hook、actual connection identity、single script location、dynamic head、strict ancestor boundary、nonempty edge set、seed semantic projection、full baseline 和 zero-call failure evidence。

---

## 6. Task 5：OpenAPI、TypeScript client、Admin 与 Worker contract map

### Files

- Create: `tools/a0/rl_reconcile_contracts.py`
- Create: `apps/api/tests/a0/test_rl_contract_reconciliation.py`
- Modify only as an A0 evidence output: `docs/reconciliation/a0-schema-orm-openapi-reconciliation.md`
- Capture: `artifacts/a0/contracts/openapi.json`
- Capture: `artifacts/a0/contracts/worker-tasks.json`
- Capture: `artifacts/a0/contracts/admin-call-sites.json`

### Contract map

`rl_reconcile_contracts` 必须枚举 router、service、TypeScript client、web/admin call site、Worker task registry 和 authorization proof。详细 rows 至少包括 search、search suggest、releases/content、admin imports、admin static build、health、genes/variants/mutants 和 worker-triggered operations；每 row 分开记录 route/client/Admin/Worker/authorization status。

static build API task name 与 Worker registered task name 不匹配时记录 blocking drift，不修产品 dispatch。mixed search contract 只能记录 observed behavior，不把未来 Internal/External Search contract 写成现状。中文 why-comment：UI affordance 不是 backend capability proof，route existence 不是 authorization proof。

### TDD and commands

先写 failing tests，覆盖 route/client/Admin/Worker/authorization 五维 map、static dispatch mismatch、unverified consumer 和 `rl_` naming。计划命令如下：

```bash
(
  cd "${rl_root}/apps/api"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_reconcile_contracts \
      --emit-openapi "${rl_root}/artifacts/a0/contracts/openapi.json"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/worker/src" \
    python -m tools.a0.rl_reconcile_contracts \
      --emit-worker-registry "${rl_root}/artifacts/a0/contracts/worker-tasks.json"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_contract_reconciliation.py -q
)
```

预期：OpenAPI 含实际 routes；Worker snapshot 只含实际 registered names；所有未证明授权状态为 `unverified`/blocking unresolved；artifact 有 source/tool/test digest、owner 和 reviewer。

### Review checkpoint

`rl_contract_reviewer` 和 `rl_worker_contract_reviewer` 按 route → client → Admin → Worker → authorization 顺序检查，不能把页面按钮、client function 或 task name 当作 capability proof。

---

## 7. Task 6：legacy Release evidence classification

### Files

- Create: `tools/a0/rl_classify_legacy_releases.py`
- Create: `apps/api/tests/a0/test_rl_legacy_release_evidence.py`
- Create: `apps/api/tests/a0/fixtures/rl_legacy_release_cases.json`
- Create: `docs/reconciliation/a0-legacy-release-evidence.md`
- Create: `docs/reconciliation/a0-unresolved-items.jsonl`

### TDD and contract

先写 failing fixtures：incomplete Release 默认 `DatasetRelease` + `unresolved`；只有 content revision、frozen build input、immutable manifest、独立 approval、deployment evidence 和 digest linkage 全部完整时，才允许 historic `PublicationRelease`。`is_public`、`published_at`、`approved_by` 和 page accessibility 不能升级 classification。中文 why-comment：旧字段状态不能替代可重建 publication chain。

实际 read-only query 通过 guard/profile/async contract；关系缺失时保留 absence evidence，写稳定 `rl_missing_source_relation`。每 row 包含 legacy identity、dataset default、content revision、frozen input、manifest、approval、deployment、classification、unresolved codes、evidence digest、owner、reviewer。JSONL 一行一个 unresolved condition。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_legacy_release_evidence.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_classify_legacy_releases \
      --profile-env RL_A0_READONLY_PROFILE \
      --output "${rl_root}/docs/reconciliation/a0-legacy-release-evidence.md" \
      --unresolved "${rl_root}/docs/reconciliation/a0-unresolved-items.jsonl" \
      --run-id "${rl_run_id}"
)
```

预期：至少一个 sample 保持 unresolved；没有 row 因 `is_public` 单独升级；query/action evidence 有 guard、identity digest、owner、reviewer 和 source digest。

### Review checkpoint

`rl_legacy_reviewer` 抽样 actual rows、fixtures 和 unresolved JSONL，检查 evidence 独立性、digest linkage、owner/reviewer 和 no-write boundary。

---

## 8. Task 7：synthetic backup/restore、restricted archive/list 与 semantic recovery

### Files

- Create: `tools/a0/rl_archive_policy.py`
- Create: `tools/a0/rl_backup_restore_rehearsal.py`
- Create: `tools/a0/rl_backup_restore_rehearsal.sh`（只调用 Python modules）
- Create: `apps/api/tests/a0/test_rl_archive_policy.py`
- Create: `apps/api/tests/a0/test_rl_backup_restore_rehearsal.py`
- Reuse唯一 canonical producer: `tools/a0/rl_snapshot_database.py`
- Reuse semantic producer: `tools/a0/rl_semantic_projection.py`
- Capture only summaries: `artifacts/a0/backup-restore/rl_archive-summary.json`
- Capture only summaries: `artifacts/a0/backup-restore/rl_list-summary.json`
- Capture: `artifacts/a0/backup-restore/rl_source-pre-snapshot.json`
- Capture: `artifacts/a0/backup-restore/rl_source-post-snapshot.json`
- Capture: `artifacts/a0/backup-restore/rl_restore-empty-proof.json`
- Capture: `artifacts/a0/backup-restore/rl_restored-snapshot.json`
- Capture: `artifacts/a0/backup-restore/rl_semantic-comparison.json`

raw custom archive and raw full list are never normal artifacts. Their restricted files are referenced only through opaque refs and digest/size metadata.

### Per-file ownership

| 文件 | producer | consumer | reviewer | evidence owner |
|---|---|---|---|---|
| `tools/a0/rl_archive_policy.py` | restricted root/mode/list/retention policy | launcher/rehearsal/gate | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| `tools/a0/rl_backup_restore_rehearsal.py` | archive/list/source-stability/semantic validator | gate manifest | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| `tools/a0/rl_backup_restore_rehearsal.sh` | Python-only wrapper | action records | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| `apps/api/tests/a0/test_rl_archive_policy.py` | test runner | archive policy | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| `apps/api/tests/a0/test_rl_backup_restore_rehearsal.py` | test runner | validator/orchestrator | `rl_restore_reviewer` | `rl_backup_evidence_owner` |
| source pre/post snapshots | `rl_snapshot_database` | source stability validator | `rl_restore_reviewer` | `rl_snapshot_evidence_owner` |
| restore-empty proof | `rl_snapshot_database` + `rl_catalog_baseline` | restore launcher gate | `rl_restore_reviewer` | `rl_catalog_evidence_owner` |
| restored snapshot/semantic result | `rl_snapshot_database` + `rl_semantic_projection` | gate manifest | `rl_restore_reviewer` | `rl_semantic_evidence_owner` |

### TDD steps

1. 先写 failing tests：
   - synthetic/non-sensitive source missing or approval flag not explicit `1` blocks archive/content actions before launcher call。
   - restricted root absent, mode not `0700`, archive/list mode not `0600`, owner/access drift or cleanup/retention/deletion failure blocks success。
   - launcher operation is invoked only by opaque profile/archive refs; no raw archive/list bytes enter normal artifacts.
   - `pg_restore --list` output is parsed only in restricted root; empty, malformed, unknown/dangerous class, missing expected object or list digest mismatch blocks before restore.
   - source pre/post revision, structural schema signature, semantic content digest, count, sequence state, extensions or enums drift blocks and restore call count is zero.
   - restore target flag unset/non-`1`, full catalog baseline nonempty, unknown class, marker/identity mismatch all block and restore call count is zero.
   - direct launcher restore uses exact internal argv contract, no output SQL, no interactive password, no URI/password, no destructive cleanup/creation/parallel flags; missing archive/nonzero/partial restore blocks.
   - same count/different content, sequence state drift, and source/restored semantic mismatch block even when structural schema signature matches.
2. 运行 focused tests，确认 validator/orchestrator 尚未存在时失败。
3. 实现 restricted archive policy、launcher integration、list parser、source stability、restore-empty full-catalog proof 和 semantic validator。
4. 重新运行 tests；只有所有 zero-call failure paths、digest bindings、retention/deletion result 和 owner/reviewer 完整，才允许 disposable rehearsal。

### Fixed 15-step sequence

以下是 Task 7 唯一 sequence；每一步必须有 action ID、preceding guard/attestation binding、exit code、stream digests、owner、reviewer。`rl_run_pg_client` 内部负责实际 PostgreSQL binary invocation，shell 只调用 Python modules：

1. **source guard**：synthetic-source role，读取 registry tuple/GUC，写 `system_identifier_digest` event。
2. **source pre-dump canonical snapshot**：`rl_snapshot_database.py` 读取 structural schema、revision、semantic content digest/count/sequence projection。
3. **source guard**：重新验证 source identity、marker、expiry、run ID 和 synthetic-source policy。
4. **custom dump**：`rl_run_pg_client --operation dump` 在 restricted root 创建 `0600` custom archive；normal evidence 只收 opaque archive ref、digest、size、format。
5. **archive digest/self-check**：对同一 restricted file 重新计算 SHA-256；size/mode/ref/digest mismatch blocks。
6. **list**：`rl_run_pg_client --operation list` 在 restricted root 创建 `0600` list；`rl_archive_policy` parse list，输出 nonempty/parseable/expected-object category summary、list digest/size；raw list 不外泄。
7. **source guard**：dump 后再次验证 source identity/marker。
8. **source post-dump canonical snapshot**：使用唯一 `rl_snapshot_database.py` producer。
9. **source pre/post comparison**：比较 revision、structural schema signature、semantic content digest/count/sequence、extensions/enums；任一 drift blocks，不能进入 restore。
10. **restore guard**：验证 restore target observed identity distinct、registry tuple、marker、expiry、run ID 和 target preprovision flag。
11. **restore-empty proof immediately before restore**：先实际运行 `rl_snapshot_database.py`，再实际运行 `rl_catalog_baseline.py`，生成 restore-empty artifact；必须证明 same-version/init full catalog baseline 无 user/migration/business object、unknown class、unexpected relkind/owner/ACL/policy/trigger/extension/publication/subscription/FDW/large object 等。
12. **direct restore**：只有 Step 11 完整通过后，实际调用 `rl_run_pg_client --operation restore`；launcher 内部使用 bare database name direct argv、no-password、exit-on-error、single-transaction、no-owner、no-privileges。
13. **restore guard**：重新读取 restore identity/marker/expiry/run context。
14. **restored canonical snapshot**：读取 structural snapshot、semantic content digest/count/sequence projection、revision、extensions/enums。
15. **recovery comparison and cleanup**：比较 source/restored structural and semantic fields；随后执行 restricted retention/deletion policy，记录 outcome；semantic mismatch、cleanup/retention/deletion failure 均使 result `BLOCKED`。

### Safe command block

下面是唯一允许的 external command shape；它展示 actual restore action，不把 raw archive path、database name、URL 或 password写入 shell argv：

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_snapshot_database \
      --profile-env RL_A0_RESTORE_PROFILE \
      --role restore-empty \
      --run-id "${rl_run_id}" \
      --output "${rl_root}/artifacts/a0/backup-restore/rl_restore-empty-snapshot.json"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_catalog_baseline \
      --profile-env RL_A0_RESTORE_PROFILE \
      --role restore-empty \
      --reference-baseline-ref RL_A0_REFERENCE_BASELINE \
      --output "${rl_root}/artifacts/a0/backup-restore/rl_restore-empty-proof.json" \
      --run-id "${rl_run_id}"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_run_pg_client \
      --operation restore \
      --profile-env RL_A0_RESTORE_PROFILE \
      --archive-ref RL_A0_RESTRICTED_ARCHIVE_REF \
      --role restore \
      --run-id "${rl_run_id}" \
      --evidence "${rl_root}/artifacts/a0/backup-restore/rl_restore-action.json"
)
```

The launcher internally executes exactly the direct restore argv defined in §0.7. It never writes the bare database name, restricted path, URI or password to command record/evidence. A restore-empty failure has launcher restore-call count zero.

### Archive/list and semantic validator contract

`rl_validate_restore` 接收 opaque archive/list refs、archive/list SHA/size/format、source pre/post snapshot paths、restore-empty baseline artifact、restored snapshot path、run ID、synthetic-source classification、retention/deletion result 和 manifest ref。它不接任意 readable boolean，不接 raw archive/list content，不接 raw database URL。

semantic comparison 必须同时比较：

```text
canonical_snapshot_version
semantic_projection_version
observed_revision
schema_signature
key_table.present
key_table.count
key_table.content_digest
sequence.last_value
sequence.is_called
extensions
enums
```

archive SHA 只证明同一 restricted custom archive 在 restore 前未变，绝不与 schema signature、semantic digest 或 restored SQL bytes 比较。list summary 的 unknown/dangerous class count 必须为零，expected object policy 必须完整。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_archive_policy.py \
           apps/api/tests/a0/test_rl_backup_restore_rehearsal.py -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_backup_restore_rehearsal \
      --source-profile-env RL_A0_SYNTHETIC_SOURCE_PROFILE \
      --restore-profile-env RL_A0_RESTORE_PROFILE \
      --archive-ref RL_A0_RESTRICTED_ARCHIVE_REF \
      --list-ref RL_A0_RESTRICTED_LIST_REF \
      --reference-baseline-ref RL_A0_REFERENCE_BASELINE \
      --output "${rl_root}/artifacts/a0/backup-restore" \
      --run-id "${rl_run_id}"
)
```

预期：任何 source classification、restricted mode、list validity、full baseline、identity、semantic、exit-code 或 cleanup failure 都为 `BLOCKED`；不生成 ordinary raw archive/list。

### Review checkpoint

`rl_restore_reviewer` 按 15 steps 逐项复核 source stability、restricted archive/list policy、direct launcher action、restore-empty immediate proof、full catalog categories、semantic content/sequence comparison、archive digest isolation、retention/deletion outcome、owner/reviewer 和 independent attestation binding。

---

## 9. Task 8：versioned evidence manifest、independent reviewer attestation 与 A0-only gate

### Files

- Create: `tools/a0/rl_reviewer_attestation.py`
- Create: `tools/a0/rl_emit_gate_evidence.py`
- Create: `apps/api/tests/a0/test_rl_reviewer_attestation.py`
- Create: `apps/api/tests/a0/test_rl_gate_evidence.py`
- Capture: `artifacts/a0/gate/rl_gate-input.json`
- Capture: `artifacts/a0/gate/rl_gate-result.json`
- External: reviewer-controlled `RL_A0_REVIEW_ROOT` attestation ref

### TDD steps

1. 先写 failing tests：
   - manifest 缺 action guard/attestation binding、identity digest/version、source/tool/test SHA、executable version、redacted argv、exit code、stream digest、timestamps、artifact ref/digest、owner/reviewer 时 `BLOCKED`。
   - 任一 nonzero final evidence action exit、digest mismatch、source drift、list invalidity、restore-empty failure、semantic drift 或 cleanup failure 时 `BLOCKED`。
   - snapshot payload 含 self-digest field 时 `BLOCKED`；parent manifest sidecar digest 缺失时 `BLOCKED`。
   - reviewer attestation path 位于 producer root、review root writable by producer、attestation missing/early、bundle digest mismatch 或 reviewer identity missing 时 `BLOCKED`。
   - 只提供 bool summary 而没有 versioned artifact-oriented manifest 时 `BLOCKED`。
   - complete manifest + independently recomputed reviewer attestation 可以产生 A0-only result，但所有 A1/production/publication permissions 仍为 false。
2. 运行 focused test，确认 manifest/attestation validator 尚未存在时失败。
3. 实现 manifest parser、source digest checker、artifact binding checker、reviewer root/trusted-boundary checker 和 gate renderer；不接 arbitrary booleans。
4. 加入中文 why-comment：gate 必须验证可回溯 artifact chain，不能相信 producer 自报状态；本地文件不能证明 hostile-writer integrity，必须依赖明确 trusted boundary。
5. 重新运行 tests；只有 independent attestation 和所有 Task 2–7 evidence 完整才可生成 gate result。

### Manifest contract

`artifacts/a0/gate/rl_gate-input.json` 顶层为：

```text
a0_evidence_manifest_version = "a0.gate.v2"
run_id
project_root_digest
plan_source_sha256
spec_source_sha256
context_contract
profile_contract
identity_digest_version
database_actions[]
catalog_baseline
canonical_snapshot_contract
semantic_projection_contract
migration_trajectory
empty_before_rebuild
empty_before_restore
source_stability
synthetic_source_policy
restricted_archive_policy
archive_summary
list_summary
restore_semantic_result
legacy_release_classification
unresolved_queue
review_attestation_ref
trusted_boundary
```

每个 action item 必须包含：

```text
action_id
action_type
role
run_id
preceding_guard_event_id
attestation_event_id
system_identifier_digest
endpoint_context_digest
configured_identity_redacted
redacted_argv_template
exit_code
stdout_sha256
stderr_sha256
started_at
finished_at
tool_source_sha256
test_source_sha256
executable_version
artifact_refs_and_sha256
owner
reviewer
```

manifest 必须绑定 Task 3 full-catalog baseline、Task 4 child/attestation/trajectory/seed projection、Task 7 archive/list/empty/source/restored/semantic/retention evidence 和 Task 1/5/6 reports。每个 database action 的 preceding guard 必须包含 role、registry tuple digest、marker digest、run ID、expiry、system identifier digest、endpoint context digest 和 redacted argv template；每个 Alembic action 还必须有 actual connection attestation event。

### Independent reviewer attestation

`rl_reviewer_attestation.py` 只在 producer evidence 完成后执行，输入 manifest ref 和 reviewer-controlled root，重新计算 bundle digest，不复用 producer 声称的 digest。attestation object 至少包含：

```text
review_attestation_version
manifest_sha256
recomputed_bundle_sha256
reviewer_identity
review_started_at
review_finished_at
decision
blocking_findings
review_source_sha256
trusted_boundary_reference
```

`rl_emit_gate_evidence.py` 检查 reviewer root 的 mode/ownership/ACL、producer 不可写、attestation time order、manifest/bundle digest 和 reviewer identity。没有可信 boundary/access-control evidence 时，validator 只返回 `BLOCKED`，不把本地 producer-written file当成 independent review。此处不声称本地 evidence 能防御 hostile writer。

### Gate result

仅在 B1–B11 全部 complete、final evidence action exit code 全为零、artifact/identity/semantic/archive/list/cleanup checks 通过、independent reviewer attestation 通过时，gate result 才能记录：

```text
status = "PASS"
a0_observational_evidence_complete = true
a1_allowed = false
production_migration_allowed = false
production_write_cutover_allowed = false
publication_implementation_allowed = false
```

任一 finding、unresolved blocking item、missing attestation、trusted-boundary failure 或 nonzero exit 都产生 `status=BLOCKED`。Gate 2 仅授权开始有界 A0 实施；它不预先生成或保证此 result 为 `PASS`。

### Commands and expected results

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_reviewer_attestation \
      --manifest-ref RL_A0_GATE_MANIFEST_REF \
      --review-root-ref RL_A0_REVIEW_ROOT_REF \
      --run-id "${rl_run_id}"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m tools.a0.rl_emit_gate_evidence \
      --manifest-ref RL_A0_GATE_MANIFEST_REF \
      --review-attestation-ref RL_A0_REVIEW_ATTESTATION_REF \
      --run-id "${rl_run_id}" \
      --output "${rl_root}/artifacts/a0/gate/rl_gate-result.json"
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0/test_rl_reviewer_attestation.py \
           apps/api/tests/a0/test_rl_gate_evidence.py -q
)
```

命令是未来实施 contract，不代表本次已运行。预期：缺 artifact/identity/owner/reviewer/attestation/trusted boundary、任一 nonzero exit 或任何 semantic/archive/list/cleanup drift 都保持 `BLOCKED`。

### Final review checkpoint

`rl_gate_reviewer` 必须按以下顺序审查：

1. 对照 A0 obligations 和本文 B1–B11；
2. 复核四行 execution context、profile-only input、fresh process binding 和 no in-process settings switching；
3. 复核 external registry tuple、custom GUC marker、identity digest version、endpoint digest、expiry/run/role；
4. 复核 full catalog baseline、unknown class policy、same-version/init reference 和 zero-call failure paths；
5. 复核 canonical structural snapshot、versioned semantic projection、content digest/sequence state、migration seed/boundary；
6. 复核 synthetic source、restricted root modes、opaque archive/list refs、list category summary、retention/deletion result；
7. 复核 Task 7 fixed 15-step sequence，特别是 restore guard 后 immediate snapshot/full-catalog proof 和 launcher direct restore；
8. 重新计算 manifest bundle digest，并在 reviewer-controlled root 重新生成独立 attestation；
9. 复核 source/tool/test SHA、executable version、redacted argv、exit codes、stdout/stderr digests、timestamps、owner/reviewer；
10. 记录 decision 和 blocking findings。未完成独立 review 不得暗示 Gate 2 已批准。

---

## 10. TDD execution order 与 validation matrix

### 10.1 Rigid order

1. runtime facts failing tests → collector/report；
2. profile/pgpass/launcher/guard failing tests → internal resolver、shell-free launcher、registry/GUC guard；
3. catalog/schema failing tests → full baseline/reconciliation；
4. Alembic child/attestation/snapshot/semantic/migration failing tests → fresh child、actual connection proof、empty rebuild、strict ancestor trajectory；
5. contract map failing tests → OpenAPI/client/Admin/Worker evidence；
6. legacy evidence failing tests → conservative classifier/unresolved queue；
7. archive/list/restore/semantic failing tests → restricted synthetic backup/restore fixed sequence；
8. reviewer/manifest/gate failing tests → independent attestation and A0-only gate evaluator。

每个 task 都遵循：先写 failing test，运行确认失败，写最小 A0-local implementation，再运行 focused validation，然后生成 evidence。red-phase expected failures不进入 final manifest；final evidence action 任意 nonzero exit 都是 blocking。

### 10.2 Static/focused validation commands

```bash
(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    pytest apps/api/tests/a0 -q
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    python -m compileall tools/a0 apps/api/tests/a0
)

(
  cd "${rl_root}"
  PYTHONPATH="${rl_root}/apps/api:${rl_root}" \
    ruff check tools/a0 apps/api/tests/a0
)
```

这些是实施计划命令，本次任务不执行它们。integration environment unavailable 时未来必须记录 exact command、`SKIPPED: environment unavailable` 和 reason；skip 永远不计入 A0 PASS。任何 skip、warning、unresolved blocking item、nonzero exit 或 missing independent attestation 都保持 `BLOCKED`。

### 10.3 Command safety matrix

| action | external invocation | internal safety proof |
|---|---|---|
| async DB snapshot/guard | `python -m tools.a0.rl_snapshot_database` / `rl_disposable_target` | async engine、async context、run_sync、process-start profile、identity/marker attestation |
| Alembic | `python -m tools.a0.rl_alembic_child` | fresh child、absolute cwd/path、process-start `SOYMUTDB_DATABASE_URL`、actual connection attestation |
| dump/list/restore | `python -m tools.a0.rl_run_pg_client` | shell=False、operation allowlist、sanitized env、0600 passfile、opaque refs、fixed argv |
| full catalog | `python -m tools.a0.rl_catalog_baseline` | same-version/init reference、explicit class allowlist、unknown blocks |
| gate | `python -m tools.a0.rl_emit_gate_evidence` | v2 manifest、all SHA/exit/identity bindings、independent reviewer attestation |

没有 external shell command 直接传数据库 URL、password、bare database name 或 restricted path。shell wrapper 只能调用上述 Python modules。

---

## 11. Gate 2 A0 B1–B11 observable acceptance criteria

| Gate item | Required evidence | Hard failure |
|---|---|---|
| B1 runtime truth | config/database/env.py import/cache facts、poisoned defaults、runtime/path report | 把 dev URL/.env/cache 当安全 fallback、secret、owner/reviewer 缺失 |
| B2 execution context | 四行 cwd/absolute path contract、fresh process boundaries、no in-process settings switch | cwd/path 错、import 后改 env、Config URL/cache clear 作为 target proof |
| B3 profile/client safety | profile-only resolver、pgpass escape、0600/0700 modes、sanitized env、shell=False、exact operation allowlist | URI/password argv、interactive password、caller PG override、shell evaluation |
| B4 observed identity | actual system id/current db/endpoint/marker、registry tuple/expiry/run、consistent digest version | raw identity evidence、version/hostname identity、NULL endpoint、COMMENT marker、marker mismatch |
| B5 alias distinctness | observed raw comparison internally、system_identifier_digest externally、localhost/IP and service/IP alias tests | configured strings不同但 observed key相同仍继续 |
| B6 full catalog baseline | same-version/init reference、explicit allowlist、all catalog categories、unknown class policy | narrow table check、pg_* shortcut、unknown class、catalog failure、baseline mismatch |
| B7 canonical/semantic snapshot | versioned structural snapshot、count-independent schema signature、versioned content/sequence projection、missing-vs-empty | snapshot self-digest、raw rows、same count different content/sequence drift被忽略 |
| B8 migration trajectory | explicit preprovision `1`、full empty baseline、fresh child、actual attestation、strict ancestor/nonempty edge、initial/downgrade/final immediate reads | precondition failure仍调用 child、poisoned default、no-op boundary、identity mismatch、nonzero exit |
| B9 backup/restore safety | synthetic source、restricted root/modes、opaque archive/list refs、list parser/category summary、restore guard后immediate full proof、fixed sequence | ordinary raw archive/list、non-synthetic source、invalid list、nonempty restore target、unsafe direct invocation |
| B10 semantic recovery | source pre/post and source/restored structural + content digest/count/sequence/extensions/enums/revision comparison | archive digest冒充 semantic proof、semantic drift被忽略、partial/nonzero restore继续 |
| B11 manifest/review gate | v2 manifest、source/tool/test SHA、executable/argv/exit/stream/time fields、guard/attestation binding、independent reviewer attestation、trusted boundary | 缺 digest/identity/owner/reviewer、producer-written attestation、nonzero exit、A0 PASS 暗示生产授权 |

Gate result 只有在 B1–B11 全部 evidence complete、independent review complete、trusted boundary complete 时才能为 A0-only `PASS`。当前 Gate 2 `APPROVE_WITH_NON_BLOCKING_NOTES` 只允许启动 A0，不改变这一实际 evidence 验收条件，也不解锁 A1。

### Gate criteria 必须重复的 restore semantics

manifest 必须逐 action 绑定：source guard → source pre canonical snapshot → source guard → controlled custom dump → archive digest/self-check → controlled list + restricted parse/category summary → source guard → source post snapshot → source stability compare → restore guard → immediate `rl_snapshot_database` + full `rl_catalog_baseline` restore-empty proof → controlled direct restore → restore guard → restored canonical snapshot/semantic projection → semantic compare → retention/deletion outcome。direct restore 的 bare database name只在 launcher internal argv存在；archive/list raw bytes、URL/password和restricted path不在 evidence。

### Gate criteria 必须重复的 Alembic semantics

每个 migration action 必须是 fresh child；selected `SOYMUTDB_DATABASE_URL` 只在 process-start child env；`env.py` actual engine connection 必须有 opt-in attestation，且实际 `system_identifier_digest`/database/endpoint/marker 与 preceding guard 匹配。full-catalog precondition failure、attestation failure、boundary 非 strict ancestor、edge set empty、seed semantic drift 或 child nonzero exit 均为 `BLOCKED`。

---

## 12. Self-review checklist

实施完成前，`rl_gate_reviewer` 必须只读全文和 generated evidence，逐项确认：

- A0 仍是 observational-only；没有产品/domain implementation、product migration、依赖升级、配置/部署修改、生产 write 或自动 Git。
- execution context、profile-only input、fresh Alembic child、process-start settings env、no in-process cache/environment switching 全文一致。
- `rl_prepare_pg_profile` 是 internal resolver；`rl_run_pg_client` 是唯一 shell-free PostgreSQL launcher；没有 shell export、shell evaluation、arbitrary argv 或 raw URL/password。
- pgpass `:`/`\` escaping、0600 file、0700 runtime root、sanitized `PGSERVICE`/`PGOPTIONS`、no interactive password 和 cleanup failure block 全部出现在 contract/tests/commands/gate。
- registry expected tuple、custom GUC marker、read-only guard、expiry/run/role、system_identifier_digest version 和 alias-resistant distinctness 全文一致；evidence 没有 raw system id。
- full same-version/init catalog baseline 覆盖所有规定 categories、explicit system allowlist、unknown class、owner/ACL/tablespace/policy/trigger/extension/publication/subscription/FDW 和 catalog read failure。
- canonical snapshot 是 Task 4/7 唯一 producer；payload 没有 self-digest；structural signature count-independent；semantic projection versioned、无 raw rows、包含 content digest/count/sequence state、explicit exclusion policy。
- migration preprovision unset failure、full empty proof zero child calls、fresh child、actual connection attestation、single absolute script location、strict ancestor/nonempty edge、seed semantic drift 和 immediate revision reads 全文一致。
- synthetic source approval、restricted root `0700`、archive/list `0600`、opaque refs、redacted category summary、unknown list class、retention/deletion outcome 和 cleanup failure 全文一致。
- fixed 15-step sequence 中 restore guard 后立即运行 canonical snapshot/full-catalog proof，再由 `rl_run_pg_client --operation restore` 执行 direct restore；没有 ordinary raw archive/list。
- manifest v2 有 plan/spec/tool/test source SHA、executable version、redacted argv、exit/stream/time fields、identity/guard/attestation/action binding；nonzero exit hard block。
- reviewer attestation 是 reviewer-controlled/trusted CI separate object，producer 不可写，bundle digest由 reviewer重新计算；trusted boundary缺失不能 PASS；不声称 hostile-writer integrity 已被本地文件证明。
- 没有 literal unsafe URL flags、同步 engine、unsafe restore mode、raw archive path、raw list、self-digest field、旧恢复 schema digest contract、任意 bool gate 或含糊占位措辞。
- TDD 顺序、中文 why-comments、`rl_` first-party naming、测试命令和 expected outcomes 均未被后文覆盖；本文不声称 A0 tests、runtime evidence 或 A0-only gate result 已完成。Gate 2 仅批准本文范围内的实施启动。

**Self-review conclusion：** 若任一项只能靠 producer 自报、缺 source/tool/test digest、缺 independent reviewer attestation/trusted boundary、缺 artifact owner/reviewer 或存在 unresolved blocking finding，`rl_gate-result.json.status` 必须为 `BLOCKED`，并写入稳定 `rl_` code。Gate 2 计划级批准不等于 A0 evidence 通过、A1 解锁或生产授权。

---

## 13. 最终声明

- A0 的唯一事实边界是观察、比较、验证和 evidence；不扩大到生产操作。
- A0 Python DB helper 统一使用 asyncpg + `create_async_engine` + `async with` + `connection.run_sync` + `asyncio.run`；shell-level PostgreSQL action 统一经过 `rl_run_pg_client` 的 `shell=False` launcher。
- Alembic 每个 action 都在 fresh child process 中以 process-start settings env 绑定 target，并由 opt-in actual connection attestation 证明 `env.py` 真正连接目标。
- cluster identity 内部使用 raw `(system_identifier,current_database)`，外部 evidence 统一使用 versioned `system_identifier_digest`；marker 由 external provisioner 的 database-level custom GUC 提供，guard 只读验证。
- fresh rebuild 使用 same-version/init full-catalog baseline；unknown object/class、catalog failure、baseline mismatch、identity/marker mismatch 全部 fail-closed。
- `rl_snapshot_database.py` 是 Task 4/7 唯一 canonical producer；structural signature 与 versioned semantic content/sequence projection 分离；snapshot payload 不自带 file digest。
- backup/restore 只使用 synthetic/non-sensitive source、restricted root、opaque archive/list refs、controlled direct restore、full restore-empty proof、source stability 和 semantic comparison。
- gate 只接受 versioned evidence manifest 和 independent reviewer attestation，不接受任意 bool；缺 artifact、identity、owner、reviewer、trusted boundary 或 nonzero exit 直接 `BLOCKED`。
- Gate 2 已以 `APPROVE_WITH_NON_BLOCKING_NOTES` 批准有界 A0 实施；A0 仍须完成真实 evidence、独立 phase review 和整改后，才可请求 A1 的单独门禁。

**保存路径：** `docs/superpowers/plans/2026-07-19-a0-factual-reconciliation-implementation-plan.md`
