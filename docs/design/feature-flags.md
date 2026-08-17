# 原子化功能开关

## 目的

将可选能力拆成服务端注册的 feature key，每个 key 可独立启用/关闭，不通过删除路由、修改代码或重启 worker 实现灰度。

## 当前注册项

| key | 默认 | 可公开 | 关闭语义 |
|---|---:|---:|---|
| `page_builder` | on | 是 | 新公开 PageDefinition 请求停止/回退 seed |
| `search.external` | on | 是 | 新外部搜索请求拒绝，内部搜索不受影响 |
| `imports.module_tsv` | on | 是 | 新 module 导入拒绝，运行中的任务不终止 |
| `imports.module_xlsx` | on | 是 | 新 xlsx 导入拒绝，txt/tsv/csv 不受影响 |
| `imports.local_upload` | on | 是 | 新浏览器直传拒绝，S3 URI 高级模式仍可按策略使用 |
| `publication.github_pages` | on | 否 | 禁止选择 GitHub Pages target |
| `publication.cloudflare_pages` | on | 否 | 禁止选择 Cloudflare Pages target |

## API

```text
GET /api/v1/capabilities
GET /api/v1/admin/features
PUT /api/v1/admin/features
```

PUT body：

```json
{"features": {"imports.module_xlsx": false}}
```

所有修改写入 `system_settings` 的 `feature.*` 命名空间，并写 `AuditLog(action="feature_flags_update")`。

## 设计约束

- 只有注册表中的 key 可以修改，拒绝任意 system setting 伪装成 feature。
- 默认值写在代码中；DB override 缺失或非法时回到安全默认。
- 关闭只拒绝新请求，不杀死运行中任务；任务状态继续由状态机管理。
- public capability 只返回标记为 public 的 key；内部发布/MCP 开关不泄露。
- 高风险开关（发布 target）后续应增加重新认证/二人审批；MCP write 等未接入 runtime 的能力不得提前注册。
- feature flag 不是权限系统，也不是 release pointer；权限仍由 RBAC，发布仍由 Publication 状态机控制。
