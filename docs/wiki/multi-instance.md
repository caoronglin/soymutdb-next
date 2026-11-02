# 多实例与远端信任模型

一个管理面板可以登记多个 SoyMutDB 实例；**每个实例保持自己的数据库、release、权限与审计**，
控制台不合并不同实例的生物记录、坐标或发布状态。

## 当前能力（已实现）

| 能力 | 实现 |
| --- | --- |
| 实例登记 CRUD | 表 `species_instances`（迁移 `0039`/`0040`/`0041`）；API `/admin/species-instances` |
| 本地实例 seed | 迁移 `0041` 幂等插入 local 行（管理员编辑过的行在降级时保留），控制台开箱即有本地目标 |
| 入参校验 | 远端 API 必须 HTTPS origin；禁止凭据/查询串/路径；`site_url` 与 `portal_base_url` 别名一致 |
| 连接探活 | `GET /admin/species-instances/{id}/health`：仅探测固定路径 `/api/v1/health/live` |
| 白名单 | `SOYMUTDB_INSTANCE_HEALTH_ALLOWLIST`（精确 HTTPS origin，逗号/换行分隔） |
| 探活边界 | 本地实例不发起网络请求；禁用实例不探测；未配置白名单返回 `unconfigured` |
| 审计 | 状态变化写入 `species_instance_health_checked`，payload 不含 URL/令牌/响应体 |
| UI | `/instances`：连接状态、最近检查时间、门户跳转、**设为当前目标**；本地实例禁止删除；远端显示 registration-only |
| 当前实例上下文 | 管理端每个页面顶部显示「目标实例 · 发布版本 · API 服务器」；选择只存在模块内存（不写 web storage），刷新回到 local 默认 |
| 连接器接口 | `apps/admin/src/lib/instance-connector.ts`：local 可写、remote 只读（`registration_only`）；`administer()` 在任何构建标志下都拒绝，直到信任通道真正启用 |

## 安全规则

1. 浏览器**不直连**远端 PostgreSQL/MinIO/Redis；不发任意 URL 代理请求（无开放代理）。
2. 远端目标只能取自管理员已登记、启用且通过 allowlist 的实例。
3. 探活请求不携带操作者身份或凭据，禁止重定向跟随，限制超时与响应体大小。
4. 服务间凭据（计划中）放部署密钥，按实例独立轮换；不得进入浏览器存储、URL 或日志。
5. 切换实例前取消旧请求并清理敏感状态；查询缓存按实例命名空间隔离。
6. 任何写操作必须同时显示目标实例与环境。

## 远端写操作（计划中，默认关闭）

在以下条件全部满足前，远端保持**仅登记、探活、跳转门户**：

1. 管理员信任配置与双重授权流程完成；
2. 按实例的服务间凭据、轮换与失效处理通过安全审查；
3. 白名单化的远程路由（路径 + HTTP 方法 + 角色）逐条审核；
4. 双实例集成测试覆盖探活、切换、越权拒绝与失败恢复；
5. 审计关联 ID 与熔断/幂等边界可观测。

## 缓存与上下文

- 查询键包含实例、site variant、release、assembly、query、filters、分页与权限上下文。
- 跨实例只展示注册信息与带来源标注的健康摘要；不合并生物学标识、坐标、release 或权限。
- 实例列表与当前选择持久化在管理端状态；默认只操作 local 实例。

## 本地优先（当前阶段）

- 控制台是**本地部署的管理面**：所有 API 请求始终发往本控制台自己的 API，
  选择远程登记不会改变请求目标。
- `VITE_REMOTE_INSTANCES_ENABLED` 只是「就绪标记」，默认 `false`；即使置为 `true`，
  `InstanceConnector.administer()` 仍然拒绝——避免出现未经审计的远程写入通道。
- 远端当前可用能力仅限：登记、白名单探活、门户跳转；管理操作保持关闭。
- 选择状态在模块内存（与管理员会话一致），不使用 localStorage/sessionStorage，
  满足 `scripts/check_admin_content_architecture.py` 的控制台存储约束。
