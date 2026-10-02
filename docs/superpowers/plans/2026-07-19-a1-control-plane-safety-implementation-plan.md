# A1 控制面安全骨架实施计划

> **已归档（2026-10-01）**：已被现行计划取代的历史实施计划。继任：`docs/aegis/plans/` 与 `docs/aegis/INDEX.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

> **写作计划头**：A1 / control-plane safety foundation  
> **日期**：2026-07-19  
> **状态**：待 A0 证据包与本计划审核通过；本文件只描述实施，不授权实施  
> **范围**：能力词汇与 deny-first 授权、typed command/digest/idempotency、审批绑定、三条独立追加历史、事务 outbox、relay/worker registry、break-glass/reauth、Admin capability snapshot/真实禁用语义，以及契约/权限/并发/审计/E2E 测试  
> **明确不做**：B-pre-ADR、B、C、D、E、F；不创建未来 dataset/publication/artifact 对象，不实现 ontology、静态发布、CAS、搜索或业务数据迁移。

## 1. A0 证据阻断与执行边界

A1 必须显式 blocked on A0。A0 完成并获得复核证据之前，不得执行本计划中的生产迁移、生产写入切换、publication 实现或任何把旧 `Release` 解释为 `DatasetRelease`/`PublicationRelease` 的逻辑。A1 只能在 disposable 数据库、测试夹具和本地 contract 环境中先建立安全骨架；即使代码已经存在，也不能宣称控制面已经治理完成。

A0 的 gate 输入必须至少包括：

1. 实际 Alembic revision/head、已部署 PostgreSQL schema、ORM metadata 的 reconciliation；不能以 `Base.metadata.create_all()` 代替迁移事实。
2. `README.md`、`apps/api/pyproject.toml`、`apps/worker/pyproject.toml` 与前端 Node/pnpm 约束的运行时 reconciliation；当前 API `>=3.14`、Worker `>=3.13`、README 另有 Python 约束时，记录事实，不在 A1 擅自升级或降级。
3. `migrations`、`apps/api/alembic.ini`、开发 Compose 中 Alembic 挂载/入口的实际 wiring reconciliation。
4. disposable PostgreSQL 的 `upgrade → 可逆部分 downgrade → upgrade`、备份恢复、空库重建和失败回滚记录。
5. OpenAPI、`packages/api-client` 调用、Admin affordance、Celery task 注册名和旧 `Release` 证据分类报告。

**A1 开始条件**：A0 报告中没有未解释的 schema/迁移事实差异，或每个差异都有明确的 unresolved 状态、责任人和禁止动作；迁移 rehearsal、恢复证据、消费者 contract 清单和 Worker registry 清单齐全；Oracle/用户批准 A1 计划。若任一项缺失，A1 实施任务只能写测试/契约草案，不能写迁移或启用写路径。

**兼容性原则**：保留现有 `RoleName`、`has_role`、`get_current_user`、`AuditLog`、`ImportTask`、`/admin/*` 路由和已有 API client 形状作为 compatibility layer；新 capability/command/history/outbox 使用新增 `rl_` 模块和符号。不得删除或重命名旧接口，不得把旧 RBAC 直接声称为细粒度能力授权；旧接口在未获得新能力时返回 truthful `403`，而不是静默放行。

## 2. 现状锚点与文件责任

以下是实施时必须先读并保持兼容的真实 seam：

| 责任 | 现有路径/符号 | A1 处理方式 |
|---|---|---|
| 认证与角色 | `apps/api/app/core/security.py:RoleName, has_role, create_access_token, decode_token` | 保留角色层级；新增能力判断不得由角色字符串拼接推断 |
| 当前用户 | `apps/api/app/api/v1/deps.py:get_current_user, get_user_roles, require_role` | 增加 capability/reauth dependency，旧 dependency 继续可用 |
| 旧审计 | `apps/api/app/core/audit.py:log_action, cleanup_old_audit_logs` | `log_action` 保留兼容；禁止新高风险成功事实只写 `AuditLog`；禁止沿用 180 天删除策略作为 ledger retention |
| 旧审计模型 | `apps/api/app/models/auth.py:AuditLog` | 保留查询/export；新 append-only ledger/outbox 用独立模型，A0 后确定物理字段/迁移 |
| Admin 权限 | `apps/api/app/api/v1/admin.py:_require_admin` | 改为在新入口使用 `rl_require_capability`，旧查询接口继续 administrator 兼容检查并增加能力快照 |
| 静态任务入口 | `apps/api/app/api/v1/admin_static.py:trigger_build` | 不在 A1 实现 publication build；将任意 `dict`、任意 `file_path` 和 post-commit `send_task` 标记为 legacy/禁用，新增安全 command contract 返回 disabled/403 |
| Worker 应用 | `apps/worker/src/soymutdb_worker/main.py:celery_app` | 增加 registry contract 检查和 A1 relay task；保留既有 include/route，修复 task name 只能在 contract 测试中锁定 |
| Worker 任务 | `apps/worker/src/soymutdb_worker/tasks/static_pages.py:build_static_pages` | A1 只登记为 legacy task；不得把它伪装成 publication task 或接收任意路径 |
| Admin 认证 | `apps/admin/src/lib/auth-context.tsx:AuthProvider, AuthContextValue` | 扩展 session/re-auth 状态与 capability snapshot，不仅凭 JWT payload 隐藏按钮 |
| Admin 高风险旧入口 | `apps/admin/src/routes/releases.tsx:ReleasesPage` | 维持页面可访问；无 A1 contract/capability/approval 时显示 disabled + 原因，不能调用旧 transition endpoint |

## 3. 新增聚焦文件

这些文件是 A1 的第一方业务文件；模块、类型、函数、变量、组件和测试夹具均使用 `rl_` 前缀。框架约定的 `__init__.py`、Alembic revision 文件名、Celery task 名称和既有公开接口可按框架例外处理，但其内部新增符号仍使用 `rl_`。

### API 控制面

- `apps/api/app/control_plane/__init__.py`
- `apps/api/app/control_plane/capabilities.py`：能力 enum、role-to-capability compatibility map、deny-first evaluator、capability snapshot schema。
- `apps/api/app/control_plane/commands.py`：Pydantic typed commands、canonical JSON、SHA-256 digest、request/correlation/idempotency key 校验。
- `apps/api/app/control_plane/approvals.py`：immutable approval binding、职责分离、quorum、expiry、policy digest 验证。
- `apps/api/app/control_plane/history.py`：dataset/build/deployment 三条 history 的 domain event 与状态转移，不创建未来领域对象。
- `apps/api/app/control_plane/outbox.py`：业务事务内写入 `rl_audit_outbox`/`rl_task_dispatch_outbox` 的 service。
- `apps/api/app/control_plane/reauth.py`：短时 reauth、MFA proof、break-glass session 与单独审计。
- `apps/api/app/control_plane/registry.py`：registered command/provider/template/task ID；拒绝 arbitrary path/URI/shell/secret。
- `apps/api/app/control_plane/dependencies.py`：`rl_require_capability`、`rl_require_reauth`、`rl_require_break_glass`。
- `apps/api/app/control_plane/router.py`：只提供能力 snapshot、command validation、approval/history read model、rehydration/health contract；不提供 B-F 业务写入。
- `apps/api/app/models/control_plane.py`：A1 需要的 capability policy/snapshot、approval binding/history event、outbox、ledger、reauth/break-glass、registry 物理模型；具体列与约束以 A0 reconciliation 后落定。
- `apps/api/app/schemas/control_plane.py`：OpenAPI DTO，全部为 typed request/response。
- `apps/api/app/workers/rl_control_plane_relay.py`：commit 后 relay 读取两种 outbox 并投递已注册 Celery task；不把投递结果写成业务成功。
- `apps/api/tests/control_plane/`：能力、command、approval、history、outbox、ledger、concurrency、reauth、registry contract tests。

### Worker

- `apps/worker/src/soymutdb_worker/control_plane_registry.py`：Worker task registry 的静态声明、payload schema/digest 校验、业务幂等执行包装。
- `apps/worker/src/soymutdb_worker/tasks/control_plane.py`：仅实现 `rl_relay_audit_delivery`、`rl_relay_task_dispatch`、`rl_audit_checkpoint` 这类 A1 基础任务；不得实现 publication/dataset。
- `apps/worker/tests/test_control_plane_registry.py`

### API client/Admin

- `packages/api-client/src/control-plane.ts`：capability snapshot、typed command、approval/history、reauth contract；不得复用 `globalSearch` 或旧 release transition 类型。
- `packages/api-client/src/control-plane.test.ts`
- `apps/admin/src/lib/control-plane-api.ts`：只调用上述 client，并把 401/403/disabled/legacy/reauth-required 映射为显式状态。
- `apps/admin/src/components/capability-gate.tsx`：按钮禁用不是安全控制，只是服务端 capability snapshot 的 truthful affordance。
- `apps/admin/src/routes/control-plane.tsx`：A1 控制面状态/历史/阻断原因工作区；不展示不存在的 dataset/publication/artifact 对象。
- `apps/admin/src/routes/reauth.tsx`：高风险操作前 reauth/break-glass 流程；默认不显示可用的 break-glass 操作。
- `apps/admin/src/components/legacy-affordance.tsx`：旧 `/releases`、`/admin/build-static` 等入口显示“legacy/disabled/403”精确原因。
- `apps/admin/tests/control-plane.spec.tsx`：snapshot、403、disabled、legacy、reauth UI contract。
- `tests/e2e/control-plane.spec.ts`：跨角色、approval binding、并发和失败审计 E2E。

## 4. 数据与不变量：A1 只建立控制面事实

A1 允许新增控制面元数据，但不能假定以下未来对象已经存在：`rl_dataset_release`、`rl_dataset_object_version`、`rl_publication_manifest`、`rl_artifact`、`rl_publication_pointer`、ontology release 或公开 publication。审批/history 中使用通用 `target_type`、`target_id`、`input_digest` 和 registered ID；当 target 尚未注册时只能是 `rejected/unavailable`，不能创建假的 publication success。

### 4.1 Capability vocabulary 与 deny-first

能力词汇先定义为有限、可审计的字符串，而不是允许用户提交任意权限名：

```python
# apps/api/app/control_plane/capabilities.py
from enum import StrEnum


class RlCapability(StrEnum):
    VIEW_CONTROL_PLANE = "control_plane.view"
    VIEW_AUDIT = "audit.view"
    SUBMIT_TYPED_COMMAND = "command.submit"
    APPROVE_DATASET = "approval.dataset"
    APPROVE_PUBLICATION = "approval.publication"
    APPROVE_DEPLOYMENT = "approval.deployment"
    DISPATCH_REGISTERED_TASK = "task.dispatch"
    PERFORM_REAUTH = "reauth.perform"
    USE_BREAK_GLASS = "break_glass.use"


RL_ROLE_CAPABILITIES: dict[str, frozenset[RlCapability]] = {
    "administrator": frozenset(RlCapability),
    "auditor": frozenset({RlCapability.VIEW_CONTROL_PLANE, RlCapability.VIEW_AUDIT}),
    "data_manager": frozenset({RlCapability.VIEW_CONTROL_PLANE, RlCapability.SUBMIT_TYPED_COMMAND}),
}


def rl_capabilities_for_user(user_roles: list[str]) -> frozenset[RlCapability]:
    """Return an allowlist; unknown roles contribute nothing."""
    rl_result: set[RlCapability] = set()
    for rl_role in user_roles:
        rl_result.update(RL_ROLE_CAPABILITIES.get(rl_role, frozenset()))
    return frozenset(rl_result)


def rl_require_capability_value(
    user_roles: list[str],
    capability: RlCapability,
) -> None:
    rl_granted = rl_capabilities_for_user(user_roles)
    if capability not in rl_granted:
        # 为什么：前端隐藏按钮不是安全边界，未知角色和未知能力必须默认拒绝。
        raise PermissionError(f"capability denied: {capability.value}")
```

实施要求：

- `RoleName`/`has_role` 仍服务旧接口；新高风险入口必须同时经过 `rl_require_capability`，不能仅因 `administrator` 角色而跳过 typed command、approval 或 reauth。
- 服务端返回 capability snapshot：`subject_id`、`role_names`、`capabilities`、`policy_revision`、`expires_at`、`generated_at`、`legacy_affordances`。snapshot 是 UI 提示，不是后端授权缓存；每次 command 在服务端重新评估。
- capability 名称、role mapping、policy revision 都是注册表值；请求传入未注册 capability 返回 `403 capability_denied`，不能动态扩权。
- 403 payload 必须包含稳定 `error_code`、`required_capability`、`policy_revision`、`correlation_id`，不泄露内部 policy 细节。

### 4.2 Typed command、digest、幂等与输入注册

所有控制面写动作先被解析为具体 Pydantic command，再生成 canonical payload digest。禁止 `body: dict`、任意 `file_path`、shell、数据库连接、环境变量、任意 URI 或 secret 作为执行输入；只能引用服务端已登记的 upload session、artifact/object ID、immutable template/provider/task ID。

```python
# apps/api/app/control_plane/commands.py
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RlDispatchRegisteredTaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    command_type: Literal["dispatch_registered_task"] = "dispatch_registered_task"
    registered_task_id: str = Field(pattern=r"^rl-task-[a-z0-9-]+$")
    input_object_ids: tuple[UUID, ...] = ()
    input_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    request_key: str = Field(min_length=16, max_length=128)
    correlation_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128)


def rl_canonical_command_payload(rl_command: BaseModel) -> bytes:
    return rl_command.model_dump_json(
        by_alias=True,
        exclude_none=False,
        exclude_unset=False,
        round_trip=True,
    ).encode("utf-8")


def rl_command_digest(rl_command: BaseModel) -> str:
    # 为什么：审批绑定的是确定的字节，不是可被字段顺序或默认值改变的 Python dict。
    return "sha256:" + sha256(rl_canonical_command_payload(rl_command)).hexdigest()
```

`rl_submit_command` 必须在同一 PostgreSQL transaction 内：验证 capability → 验证 registered IDs/输入 digest → 检查 `(actor, command_type, idempotency_key)` → 比较已有 payload digest → 写 domain command record、audit outbox、必要的 task outbox → commit。相同 idempotency key + 相同 digest 返回第一次结果；相同 key + 不同 digest 返回 `409 idempotency_conflict`；失败 transaction 不得留下成功事实，但拒绝/失败必须走 failure-audit path。

### 4.3 Approval binding 与三条独立 append-only history

Approval binding 的不可变字段至少包括：`command_payload_digest`、`target_type`/`target_id`、`input_digest`、`policy_revision`/`policy_digest`、environment（publication approval 可为 `not_applicable`）、quorum、approver IDs、expiry、request/correlation/idempotency key、职责分离结果和 binding digest。审批者不能是 requester；重复审批者不计入 quorum；过期或 command/target/input 任一不匹配时拒绝执行。

三条 history 必须是三组 event 表/aggregate，不使用一个 `status` 字段覆盖：

1. `rl_dataset_approval_history`：候选、校验、补救、提交、accepted/rejected/expired。A1 只提供通用历史骨架与 target evidence 检查，不建立 dataset 对象。
2. `rl_publication_build_approval_history`：freeze、queue、build、validation、artifact_ready、submitted、approved/rejected/expired。A1 只能拒绝未注册 publication/artifact target，不能生成 publication success。
3. `rl_deployment_attempt_history`：promotion、failure、compensation、rollback、unknown。A1 只验证 binding/state machine 和 append-only event，不执行 CAS、pointer 或 CDN。

代表性不可变 event：

```python
# apps/api/app/control_plane/history.py
class RlHistoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    history_kind: Literal["dataset", "publication", "deployment"]
    event_type: str
    target_type: str
    target_id: str
    binding_digest: str
    payload_digest: str
    actor_id: UUID
    correlation_id: UUID
    idempotency_key: str
    occurred_at: datetime
    result: Literal["accepted", "rejected", "failed", "expired", "unknown"]
    reason_code: str | None = None


def rl_append_history_event(rl_event: RlHistoryEvent, rl_previous_digest: str | None) -> str:
    # 为什么：事件正文不能 update/delete；链前值使并发重放和审计校验可检测。
    rl_chain_input = (rl_previous_digest or "genesis") + "|" + rl_event.model_dump_json()
    return "sha256:" + sha256(rl_chain_input.encode()).hexdigest()
```

A1 的 SQL/ORM 约束（具体名称以 A0 物理事实为准）必须保证：event ID 唯一、`(history_kind, idempotency_key)` 唯一、binding digest 非空且格式正确、sequence 单调、正文不可 ORM 普通 update/delete。修正只能追加 correction/rejection event。数据库角色权限、应用 service 和 repository 三层都要拒绝普通 update。

### 4.4 Audit outbox、task outbox 与 ledger

`rl_audit_outbox` 与业务 command/history 写入同一个 transaction；`rl_task_dispatch_outbox` 只表达待执行任务，二者不得合并。audit outbox 字段包含 actor/capability/target/environment/binding digest/command digest/sanitized diff/result/correlation/idempotency；task outbox 包含 registered task ID、payload digest、attempt、lease、retry、dedupe key。两者均只能 append/claim/mark delivery projection，不能把 Celery 返回值当业务成功。

最终 `rl_audit_ledger` 追加 canonical event，按分区 sequence + previous digest 形成 hash chain，周期性 checkpoint/root digest；拒绝、403、校验失败、投递失败、超时、补偿和 rollback 都要有 failure/operation event。A1 不删除旧 `AuditLog`，但必须把新高风险证据从旧 180 天 cleanup 路径隔离；retention policy 只能追加审批/hold event，不能缩短高风险最低保留期或绕过 legal hold。

## 5. 认证、重新认证与 break-glass

在 `apps/api/app/control_plane/reauth.py` 中添加短时 reauth proof：绑定 user/session、purpose、command digest、issued/expiry、MFA method、correlation ID 和 single-use nonce。`apps/api/app/api/v1/auth.py` 的既有登录/refresh 行为保持不变；A1 只增加受保护的 `POST /control-plane/reauth` contract，不改变 token 兼容字段。

break-glass 默认 disabled。只有预配置的 capability policy 明确允许时，才可创建短时 session；要求当前 session 已认证、重新输入密码或 MFA、冷静期（默认至少 15 分钟，除非 policy 明确记录 emergency exception）、reason、通知目标和独立 audit event。break-glass 不能授予未注册 capability，不能绕过 typed command、approval binding、quorum、expiry、ledger 或职责分离。UI 默认不显示可执行按钮，服务器返回 `403 break_glass_disabled` 或 `reauth_required`。

## 6. Relay 与 Worker registry

`apps/api/app/workers/rl_control_plane_relay.py` 在数据库 commit 后扫描 outbox，按 registered task ID 和 payload digest 调用 Celery。relay 失败只更新 delivery attempt/diagnostic event；不会回写 command/history 的成功状态。claim 使用 PostgreSQL lease/fencing 或等价事实，不依赖 Redis lock 作为正确性来源。Redis 仅可做短时去重/协调。

Worker 端 `control_plane_registry.py` 必须列出 canonical task name、queue、payload schema version、handler、允许 retry policy 和 idempotency extractor。启动 contract test 发现 API registry 与 Celery `celery_app.tasks` 不一致时失败。现有 `soymutdb_worker.tasks.static_pages.build_static_pages` 必须与旧错误名 `soymutdb_worker.tasks.static.build_static_pages` 明确区分；A1 不把任一名称升级为 publication task。`apps/api/app/api/v1/admin_static.py:trigger_build` 的 `send_task` 直接调用改为 legacy disabled/contract path，待后续 C 计划实现安全 dispatch。

代表性 registry：

```python
# apps/worker/src/soymutdb_worker/control_plane_registry.py
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RlTaskSpec:
    registered_task_id: str
    celery_name: str
    queue: str
    schema_version: int
    handler: Callable


RL_TASK_REGISTRY = {
    "rl-task-audit-delivery": RlTaskSpec(
        "rl-task-audit-delivery",
        "soymutdb_worker.tasks.control_plane.rl_relay_audit_delivery",
        "audit",
        1,
        rl_relay_audit_delivery,
    ),
}


def rl_validate_task_payload(rl_task_id: str, rl_schema_version: int, rl_payload_digest: str) -> None:
    rl_spec = RL_TASK_REGISTRY.get(rl_task_id)
    if rl_spec is None or rl_spec.schema_version != rl_schema_version:
        # 为什么：只执行服务端登记且版本匹配的任务，拒绝任意 Celery name/payload。
        raise ValueError("unregistered_or_incompatible_task")
    if not rl_payload_digest.startswith("sha256:"):
        raise ValueError("invalid_task_payload_digest")
```

## 7. API contract 与 Admin truthful affordance

在 `apps/api/app/control_plane/router.py` 注册独立 `/api/v1/control-plane` 路由，并在 `apps/api/app/api/v1/router.py` 中挂载。至少提供：

- `GET /capabilities`：返回当前 user 的 capability snapshot、policy revision、reauth 状态、可见/disabled/legacy affordances。
- `POST /commands/validate`：只解析 typed command、返回 command digest、required capability、registered-input 检查结果；不执行。
- `POST /commands`：A1 仅允许安全基础 command 或明确返回 `409 target_unavailable`；不得创建未来 publication/dataset success。
- `GET /histories/{history_kind}`：按权限读取对应追加历史和 chain verification result。
- `POST /approvals`：验证 binding/职责分离/quorum/expiry；没有已注册 target 或所需 evidence 时返回拒绝事实。
- `POST /reauth` 与 `POST /break-glass/sessions`：按上一节限制并写 audit。
- `GET /registry`：只返回公开给当前 operator 的 registered task/template/provider IDs，不返回内部路径、bucket/key、secret 或任意 URI。

OpenAPI schema 使用 `apps/api/app/schemas/control_plane.py` 的模型；不在 router 中接收裸 `dict`。`packages/api-client/src/control-plane.ts` 复制生成/手写的稳定 DTO，错误统一为：`401 unauthenticated`、`403 capability_denied`、`403 reauth_required`、`403 break_glass_disabled`、`409 idempotency_conflict`、`409 approval_binding_mismatch`、`409 concurrency_conflict`、`422 typed_command_invalid`、`409 target_unavailable`。

Admin 行为：

1. `AuthContextValue` 增加 `capabilitySnapshot`、`refreshCapabilities`、`reauthState`；不能用 JWT payload 的 role 做最终授权。
2. `CapabilityGate` 根据 snapshot 显示 capability label、disabled reason 和“后端仍会重新校验”的说明；按钮 disabled 仅是 UX。
3. `releases.tsx` 中 Activate/Rollback/Archive 不再直接调用任意 `/admin/releases/{id}/{action}`。若后端没有 A1 typed command + target evidence + approval contract，显示 disabled/legacy，并链接到阻断原因。
4. Admin 中只显示 A1 已有的 control-plane history/outbox/registry/reauth 状态；不渲染虚假的 DatasetRelease、PublicationRelease、artifact manifest、CDN pointer 或 ontology release。
5. 403 页面必须可区分：无权限、需要 reauth、break-glass 未启用、legacy endpoint 已禁用、target 尚不可用；不使用笼统“Unavailable”。

## 8. TDD 实施顺序

严格按以下红—绿—重构顺序；每一步先新增失败测试，再写最小实现，再运行对应命令。测试夹具同样使用 `rl_` 前缀，并使用事务 rollback/隔离 schema，不能依赖 `create_all()` 证明迁移。

### 第 1 步：能力 vocabulary 与 deny-first

先写 `apps/api/tests/control_plane/test_capabilities.py`：未知 role/unknown capability/无 token/普通 role 访问高风险 capability 均为拒绝；administrator 也必须继续经过后续 command/approval。再实现 `capabilities.py`/`dependencies.py`，补 OpenAPI 403 schema。

### 第 2 步：typed command、canonical digest、idempotency

先写 `test_commands.py`：extra field、任意 path/shell/URI、错误 digest、缺 key、相同 key 同 digest、相同 key 不同 digest、JSON 字段顺序/default 稳定性。再实现 `commands.py` 与 service transaction。命令不得执行未来对象。

### 第 3 步：approval binding 与职责分离

先写 `test_approvals.py`：requester 自审、重复 approver、quorum 不足、expiry、command/target/input/policy/environment mismatch 均拒绝；publication approval 的 environment 为 `not_applicable`，deployment approval 必须绑定有效 publication approval ID。再实现 `approvals.py`。

### 第 4 步：三条 history 与不可变链

先写 `test_histories.py`：三类 event 互不混写；append-only、sequence/previous digest、correction event、未知 target 的 `target_unavailable`；重复 idempotency key 幂等。再实现 `history.py`、模型和 A0 批准后的 migration。

### 第 5 步：事务 outbox 与 failure audit

先写 `test_outbox.py`：业务事实、audit outbox、task outbox 同 transaction；rollback 后三者均无成功事实；403/422/投递失败留下 failure audit；audit/task 互不消费对方语义。再实现 `outbox.py` 与 ledger writer。

### 第 6 步：relay/worker registry

先写 API↔Worker registry contract：每个 registered ID 对应唯一 Celery name/schema/queue；错误旧名称失败；retry 使用同一 idempotency key；worker timeout 不制造 success。再实现 `rl_control_plane_relay.py`、`control_plane_registry.py` 和 A1 基础任务。

### 第 7 步：reauth/break-glass

先写 `test_reauth.py`：过期 proof、错误 command digest、重复 nonce、未启用 break-glass、无 MFA、冷静期未完成、普通确认框绕过均拒绝；成功 proof 单次使用并审计。再实现 `reauth.py` 和 auth router contract。

### 第 8 步：Admin snapshot/403/legacy

先写 `packages/api-client/src/control-plane.test.ts` 与 `apps/admin/tests/control-plane.spec.tsx`：snapshot 控制按钮、403 显示精确原因、legacy route disabled、reauth-required 进入 reauth、snapshot 过期后刷新。再实现 client、`CapabilityGate`、`control-plane.tsx`、`reauth.tsx` 和 releases legacy guard。

### 第 9 步：跨层 E2E 与并发

最后写/执行 `tests/e2e/control-plane.spec.ts` 和 API concurrency tests：两个 approver 并发、同一 idempotency key 并发、不同 payload 冲突、relay 重试、lease expiry、worker duplicate delivery、approval expiry、失败补偿事件。此步只验证 A1 control-plane facts，不验证 publication/CAS/search/dataset。

## 9. 迁移与数据库实施策略

只有 A0 明确实际 Alembic head/schema/wiring 后，才新增 A1 Alembic revision；revision 文件名按仓库 Alembic 约定，不强行使用 `rl_` 文件名。迁移采用 expand-only：新增表、索引、检查约束和必要的权限，不删除/重命名旧表，不改旧 `AuditLog`/`Release` 语义，不把旧数据自动填成三条历史。旧数据若缺 command digest/binding/target evidence，进入 unresolved compatibility projection 或只读 legacy view，绝不推断成功。

迁移内禁止写入当前公开指针、publication manifest、dataset/publication 对象。验证顺序为：disposable 空库 upgrade；真实 fixture 写入；可逆部分 downgrade；再次 upgrade；备份恢复；并发/唯一约束测试。任何 contract/schema mismatch 先停止并回到 A0，不通过 `create_all()` 或 ORM 自动补表掩盖。

## 10. 精确验证命令与预期结果

以下命令按项目现有入口执行；在 A0 之前，命令只允许在 test/disposable 环境执行。

```bash
cd /mnt/data02/T25ronglin/code/web
python -m pytest apps/api/tests/control_plane -q
```

预期：`passed`，且覆盖 deny-first、digest/idempotency、approval binding、history chain、outbox、reauth；若目录尚未创建，命令应先因红测失败，不能跳过测试直接实现。

```bash
cd /mnt/data02/T25ronglin/code/web
python -m pytest apps/api/tests -q -k 'control_plane or admin or auth'
```

预期：A1 新测试与既有 admin/auth 兼容测试全部通过；旧 `RoleName`、`get_current_user`、audit list/export contract 不回归。

```bash
cd /mnt/data02/T25ronglin/code/web
python -m pytest apps/worker/tests/test_control_plane_registry.py -q
```

预期：registry、Celery task name、schema version、queue、payload digest 和 duplicate retry contract 全部通过；旧 static task 错误名称必须被测试明确拒绝。

```bash
cd /mnt/data02/T25ronglin/code/web
pnpm --filter @soymutdb/api-client test -- control-plane
pnpm --filter @soymutdb/admin typecheck
pnpm --filter @soymutdb/admin lint
```

预期：client contract tests 通过；Admin TypeScript 编译通过；lint 不出现新增错误。不得以修改全局 lint 配置消除错误。

```bash
cd /mnt/data02/T25ronglin/code/web
pnpm exec playwright test tests/e2e/control-plane.spec.ts
```

预期：不同角色的 200/403、disabled/legacy、reauth-required、approval mismatch、idempotency conflict 和 failure-audit UI 场景通过；测试数据不应出现 dataset/publication/artifact 假对象。

```bash
cd /mnt/data02/T25ronglin/code/web
python -m ruff check apps/api/app/control_plane apps/api/tests/control_plane
python -m ruff check apps/worker/src/soymutdb_worker/control_plane_registry.py apps/worker/tests/test_control_plane_registry.py
```

预期：无 E/F/I/W/UP 错误；非显然授权、幂等、不可变性和迁移保护处都有简短中文 `为什么` 注释。

迁移命令必须使用 A0 确认后的实际配置，命令模板如下，不能凭猜测替换路径：

```bash
cd /mnt/data02/T25ronglin/code/web/apps/api
alembic upgrade head
alembic downgrade <A0-confirmed-reversible-revision>
alembic upgrade head
```

预期：upgrade/downgrade/upgrade 在 disposable PostgreSQL 上成功；若 A0 证明某 revision 不可逆，必须记录预期失败及恢复路径，不能把普通 downgrade 说成完整回滚。

## 11. 完成判定、checkpoint 与禁止事项

A1 只有同时满足以下条件才可提交 Oracle review：

- capability vocabulary 是有限注册表，所有新增高风险 router/service 都是 deny-first；旧角色/API 仍可兼容，但不会代替 capability。
- typed command 的 canonical digest、registered input、request/correlation/idempotency key 和冲突语义有 OpenAPI/client/API tests。
- approval binding 逐项比较 command/target/input/policy/environment/quorum/expiry/职责分离；三条 history 独立、append-only、可重建，且没有未来 dataset/publication/artifact success。
- audit/task outbox 同事务、语义分离；failure audit 完整；ledger chain/checkpoint 与 retention/hold contract 可验证；旧 180 天删除不会触及新 ledger。
- relay/worker registry contract 锁定 canonical task name、schema、queue、retry/idempotency；投递失败不产生业务成功。
- reauth/break-glass 默认安全关闭、短时、单次/独立审计，并不能绕过审批或 typed command。
- Admin capability snapshot、disabled/403/legacy/reauth affordance 与后端真实 contract 一致；无后端能力的入口已禁用或移除，不以 UI 文案冒充治理能力。
- 契约、权限、并发、审计失败、Worker registry 和跨角色 E2E 证据齐全；A0 migration/wiring evidence 可追溯。

每个 TDD 阶段结束只允许建立本地 checkpoint，例如：`A1 checkpoint: capabilities`、`A1 checkpoint: histories`、`A1 checkpoint: e2e evidence`。本计划不包含 `git commit`、`git push`、自动提交或发布命令；任何 commit 必须另获用户明确授权后，由用户指定的执行步骤完成。

## 12. 自审

- **范围自审**：仅 A1 控制面安全骨架；未实现 B-F、ontology、dataset/publication/artifact、静态发布、CAS、搜索、JBrowse 或 Admin 完整业务重构。
- **A0 阻断自审**：明确列出 schema/迁移/runtime/OpenAPI/Worker evidence 前置条件；没有把 A0 事实差异藏进新模型或升级动作。
- **安全自审**：前端隐藏不当作授权；未知角色、能力、输入、task、target、approval 和 break-glass 默认拒绝；拒绝/失败/未知均可审计但不会伪造 success。
- **一致性自审**：审批、build/publication、deployment 三条 history 分离；outbox 与业务事实同事务；relay/Celery/Redis 均非成功事实来源；并发依赖数据库唯一约束/lease/fencing，而不是通知或 UI。
- **兼容性自审**：保留 `RoleName`、现有认证、`AuditLog` 查询/export、旧 Admin 路由和 worker 任务作为兼容面；不静默改变旧接口含义，旧高风险入口在缺新 contract 时 truthful disabled/403。
- **命名/注释自审**：新第一方符号、模块、组件、fixture 使用 `rl_`；所有授权、digest、不可变、迁移和性能取舍包含简短中文 why-comment。
- **文档自审**：这是唯一要创建的文件；不留未决占位项；没有自动 commit 命令；命令给出路径、预期结果和 A0-confirmed placeholder 边界。
