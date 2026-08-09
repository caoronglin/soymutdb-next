# 消息通知体系（D2）

通知中心为 SoyMutDB 提供任务完成/失败提醒，共三个通道，从「必然可达」到「尽力而为」：

| 通道 | 载体 | 触发方 | 可达性 |
| --- | --- | --- | --- |
| 应用内通知中心 | `notifications` 表 + 导航铃铛 | worker（`NotifyStore` 直写 PG） | 主通道：登录后必达 |
| 浏览器系统通知 | Web Notification API | 前端（`lib/use-browser-notifications.ts`） | 需用户授权，尽力而为 |
| 桌面通知 | plyer（OS 原生） | worker（`utils/notify.py`） | 可选依赖 + `SOYMUTDB_DESKTOP_NOTIFY=true`，尽力而为 |

## 数据模型

`notifications` 表（迁移 `0013_notifications.py`，模型 `apps/api/app/models/notification.py`）：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID PK | `gen_random_uuid()` |
| `user_id` | UUID FK → users.id (CASCADE) | 非空；无主任务不产生通知 |
| `type` | varchar(64) | 类型词表（见下） |
| `title` | varchar(256) | 展示标题（worker 生成英文文案） |
| `body` | text | 展示正文 |
| `link` | varchar(512) NULL | 点击跳转的应用路由，如 `/blast/jobs/{id}` |
| `read_at` | timestamptz NULL | 已读时间 |
| `created_at` | timestamptz | 服务端默认 now() |

索引：`ix_notifications_user_id (user_id)`、`ix_notifications_user_read (user_id, read_at)`（未读优先列表）。

`type` 词表（字符串，新类型无需迁移）：

- `blast_completed` / `blast_failed`
- `analysis_completed` / `analysis_failed`（fastp 与 scanpy 共用）
- `gwas_completed` / `gwas_failed`
- `seed_request` 等扩展类型由后续需求自行追加

## API 契约（`/api/v1/notifications`，均需认证）

| 端点 | 说明 |
| --- | --- |
| `GET /notifications?limit=N` | 列表；未读优先、新→旧；`limit ∈ [1,50]`（默认 20）；返回 `{items, total, unread_count}` |
| `GET /notifications/unread-count` | `{unread_count}`（铃铛角标，前端 30s 轮询） |
| `POST /notifications/read` | body `{ids: [...]}` 或 `{all: true}`；返回 `{marked}`；`ids` 限定本人，越权 id 忽略 |

实现：`app/api/v1/notifications.py` + `app/services/notification_service.py` + `app/schemas/notifications.py`。
API 侧写入入口 `notification_service.create_notification(db, user_id, type, title, body, link=None)`
供后续 API 生产者（如 seed-request 事件）使用；worker 侧则走窄表直写，不经过 API。

## Worker 侧

- `tables.py`：`notifications` 窄表 + 三个 job 窄表补 `user_id` 列（`blast_jobs` / `analysis_jobs` / `gwas_jobs`）。
- `repositories.py`：`NotifyStore`
  - `create(user_id, type, title, body, link=None) → bool`：**幂等**——`link` 非空时先查同 `user_id + link`，存在则跳过（同 job 只建一条，完成/失败重投递不重复）。
  - `get_job_user_id(job_id, kind) → str | None`：`kind ∈ blast/fastp/scanpy/gwas` 映射 job 表；读不到 `user_id` 返回 `None`（匿名任务跳过）。
- `tasks/notifications.py`
  - `create_notification` 任务：name=`soymutdb_worker.tasks.notifications.create_notification`，queue=`default`，幂等（复用 `NotifyStore.create`）。
  - `notify_completed(job_id, *, kind)` / `notify_failed(job_id, *, kind, error=None)`：触发点辅助函数——解析 owner → 组文案/link → 直写 → 可选 plyer 桌面通知；任何失败仅 warn，绝不拖垮 job 任务。
- 触发点（均在 `mark_succeeded` / `mark_failed` 之后）：
  - `tasks/blast.py` → `notify_completed(job_id, kind="blast")` / `notify_failed(...)`；link `/blast/jobs/{id}`
  - `tasks/analyses/fastp.py` → `kind="fastp"`；link `/analyses/{id}`
  - `tasks/analyses/scanpy.py` → `kind="scanpy"`；link `/analyses/{id}`
  - `tasks/gwas.py` → `kind="gwas"`；link `/gwas/jobs/{id}`
- `utils/notify.py`：`desktop_notify(title, message)` —— `SOYMUTDB_DESKTOP_NOTIFY=true` 时尝试 plyer（缺失/失败静默 + warn），否则 no-op。可选依赖：`pip install soymutdb-worker[notify]`（`pyproject.toml` `[project.optional-dependencies] notify = ["plyer>=2.1"]`，不强制安装）。

## Web 侧

- `components/notifications/notification-bell.tsx`：AntD Badge + Popover 铃铛；未读数 30s 轮询；列表最近 20 条（打开时拉取 + 30s 轮询）；类型图标（completed 绿 / failed 红 / 其他蓝）；未读加粗；点击条目标记已读并跳转 `link`；「全部已读」按钮。挂载于 `components/site-header.tsx`（语言切换按钮旁），仅登录用户可见。
- `lib/use-browser-notifications.ts`：`ensurePermission()`（**仅限用户手势内调用**，浏览器强制）、`showNotification(title, body, link)`（granted 时 `new Notification`，点击聚焦 + 跳转 link）。
- 试点：`routes/blast.tsx` —— 提交时（手势内）请求权限；jobs 列表 30s 轮询，检测到任务 `→ completed` 变化时弹系统通知（首次渲染不通知已有完成项）。

## 配置

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SOYMUTDB_DESKTOP_NOTIFY` | `false` | 置 `true`/`1` 启用 worker 桌面通知通道 |
| （无） | — | 浏览器通道由用户授权控制；应用内通道无需配置 |

## 测试

- API：`apps/api/tests/test_notifications_api.py`（认证门禁、分页上限、未读优先、未读数、ids/all 已读、空选择器 422）。
- Worker：`apps/worker/tests/test_notifications.py`（`NotifyStore` 插入/幂等/owner 解析、任务契约与写库、辅助函数（含匿名跳过与异常吞噬）、blast 触发点 mock、plyer 封装缺失/失败/成功）。
