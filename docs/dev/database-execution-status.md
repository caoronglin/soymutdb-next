# SoyMutDB 数据库核心能力执行状态

维护者：总控执行实例。更新：2026-09-08（首轮 T0 记录）。
依据：`database-execution-handoff.md` + `database-core-contract.md` + `pi-agent-hard-constraints.md`。
用户已撤销旧 AGENTS.md；本文件不恢复其内容。

## 任务范围

单执行实例（总控）顺序执行 T0→T5，无子智能体委派。

## 环境基线（已验证）

- Node v24.19.0、pnpm 11.21.0、系统 Python 3.14.6、`apps/api/.venv` Python 3.14.6。
- PostgreSQL 16 验证环境：Mamba `.mamba-root/envs/postgres16`，端口 55432（`docs/dev/mamba-validation-environment.md`）。无 Docker/testcontainers。
- fixture 数据库：`soymutdb_testfixtures`（每次运行前重建）。迁移运行库：`soymutdb_validation`。
- API 测试解释器：`apps/api/.venv/bin/python`（3.14）。注意：mamba `soymutdb-test` 环境是 Python 3.13，加载 `.venv` 的 3.14 编译包会 ABI 失败，不用于 API 测试。

## 阻碍修复记录（脏工作区中的缺陷，最小修复，未覆盖他人设计）

1. `apps/api/app/services/news_service.py`：未提交改动中 `except TypeError, ValueError:` 为语法错误，阻塞全部 API 测试导入 → 改为 `except (TypeError, ValueError):`。
2. `apps/api/tests/conftest.py`：未提交改动将 `db_session` 改为外层事务+savepoint，但 `app` fixture 的 get_db 覆盖仍绑定 `test_engine` 新连接，应用看不到 fixture 数据（test_mutants 4 例失败）。修复：新增函数级 `db_connection` fixture，`db_session` 与 `app` 的请求会话共享同一外层事务（savepoint 模式）。并发请求测试（test_auth_sessions）使用独立 fixture，不受影响。
3. `apps/api/.venv`：`soymutdb_jobs` 为过期非编辑安装（缺 `PAGE_BUILDER_PUBLISH_TASK`）→ 移除 site-packages 旧副本，改用指向 `packages/jobs-py/src` 的 `.pth` 编辑安装。

## 基线测试证据（修复后，未提交改动状态，2026-09-08）

```
cd apps/api
SOYMUTDB_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb@127.0.0.1:55432/soymutdb_testfixtures' \
  .venv/bin/python -m pytest tests/test_search.py tests/test_search_contract.py \
  tests/test_search_database_integration.py tests/test_mutants.py tests/test_genes.py \
  tests/test_gene_service.py tests/test_migrations.py -q
→ 63 passed
```

## T0 核验结论（代码现状，2026-09-08）

- `MutantLine`（apps/api/app/models/variant.py）：`id` 自增主键（私有持久化键）；`name` String(128) unique（实验室样本编号，worker ingest TSV 以 name 解析 surrogate id）；`is_public`、`release_id`、软删除。**无 public_id。**
- `Gene`（apps/api/app/models/genomic.py）：`id` String(64) 全局主键（accession，如 Glyma.01G000100）+ `assembly_id` FK。**同名 accession 无法跨 assembly 共存**（H04 缺口）。FK 消费者：transcripts、gene_aliases（genomic）、variant_summaries（variant）、expression_data（expression）、gene_homologs（homolog）、gene_data_cache（gene_data_cache）。
- `Assembly`：name/version 独立表，可关联 release（release_id 可空）；`Release.assembly_id` 是展示性字段。assembly 与 release 已是独立维度，但搜索固定解析 active release 并在未指定 assembly 时回落其默认 assembly（H05/H06 缺口）。
- `search_service.global_search`：external 固定 fail-closed 不返回突变体（防止暴露主键，属临时保护）；internal 分支返回突变体但 id 用持久化主键，且无授权；缓存参数含 query/types/cursor/limit/site_variant/release_id/assembly_id；**internal 结果与其他用户共享同一缓存键**（H09 缺口）。
- `/api/v1/search` JSON 路由固定 `SiteVariant.EXTERNAL`；**无 internal 授权搜索端点**（ID-03/04 缺口）。suggest 未绑定 assembly/release。
- 游标：`release_context.encode_bound_cursor` 已实现 HMAC 绑定 release/filters（复用）；federated 全局搜索仍是数字 offset。
- 站点隔离：`site.py` 已有 internal 变体鉴权与 private/no-store；制品扫描脚本存在但只覆盖部分条件。
- RBAC：`core/security.py` 10 角色，`require_role` 依赖可用；无“内部检索”专项能力位。

## 契约版本 v1（本轮冻结）

已确定工程决定（可逆，测试覆盖）：

| 决定 | 内容 |
| --- | --- |
| internal_id | `mutant_lines.id`（Integer 主键），仅内部契约暴露，外部响应/URL/导出禁止出现 |
| 内部业务编号 | `mutant_lines.name`（实验室样本编号，unique）。内站搜索同时匹配 public_id 与 name，并标注 `matched_field` |
| public_id | 新增 `mutant_lines.public_id`：String(32) unique、发布前可空、发布记录必须非空。签发格式（工程默认）：`SM` + 10 位 Crockford Base32 随机（secrets），不从 id/name 推导；不可变 |
| 内部检索授权 | 服务端强制：已认证用户且角色层级 ≥ researcher（复用 `_ROLE_GRANTS` 层级）；审计记录查询事件（不含凭证）。具体角色/审计保留期为待确认业务输入 |
| 未指定 assembly 搜索 | 按 assembly 分组返回（`groups` + `ambiguous` 标志），不静默默认；未匹配 assembly 的显式查询返回 404 风格错误 |
| 基因持久化身份 | 新增 `genes.gene_pk` BigInt 代理主键；原 `id` 列更名为 `accession`（语义不变），唯一约束 `(assembly_id, accession)`；6 张 FK 表改引 gene_pk；公开 URL/查询仍用 accession + assembly 参数 |
| 跨版本映射 | 新表 `gene_crosswalks`：source/target gene_pk FK、`relation_type`（one_to_one/one_to_many/many_to_one/other）、`provenance_source`、`provenance_evidence` JSONB、release 可空；搜索结果区分 exact/alias/cross-version/text |
| 内部缓存 | internal 上下文搜索禁用共享缓存（直查）；external 缓存键维持 site/release/assembly/query/types/cursor/limit |

待业务输入（不阻塞本轮实现，阻塞生产回填/发布）：
- public_id 正式格式、历史编号保留与 redirect/alias 策略。
- 内部检索角色的最终名单与审计保留期。
- 真实 v4↔v5 映射数据来源。

文件归属（单执行者）：全部变更由本实例执行；迁移链仅本实例写入；生成客户端仅由 OpenAPI 重新生成，不手改。

## 任务状态

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| T0 基线与契约 | VERIFIED（核验+契约记录；见上文） | 本文件 |
| T1 身份与版本模型 | IN_PROGRESS | 待补 |
| T2 搜索与访问边界 | NOT_STARTED | 待补 |
| T3 客户端与界面 | NOT_STARTED | 待补 |
| T4 隔离与回归 | NOT_STARTED | 待补 |
| T5 总集成 | NOT_STARTED | 待补 |

## 下一步

1. T1：模型变更 + 迁移 0032/0033（upgrade/downgrade）+ PostgreSQL 集成测试（唯一性、跨 assembly 共存、外键迁移、crosswalk 约束）。
2. T2： mutants API 双 ID、internal 授权搜索端点、搜索分组/消歧、match_type、缓存隔离。
3. T3：OpenAPI 重新生成客户端，调用方同步。
4. T4：契约 §6 fixture 数据集 + ID/ASM/CTX 矩阵 + 制品扫描。
5. T5：全量门禁（lint/typecheck/test/双构建）与收口。
