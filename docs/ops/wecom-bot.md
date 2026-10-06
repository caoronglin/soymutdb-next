# 企业微信机器人通知

SoyMutDB 通过**企业微信官方 CLI**（`@wecom/cli`）发送运维摘要。功能默认关闭；worker 不持有任何企业微信凭据，只持有目标会话 ID。

## 配置

分两步，顺序不能反。

**第一步，在运行 Celery worker 的主机上安装并授权 CLI**（凭据按主机存储，不进 worker 环境变量）：

```bash
npm install -g @wecom/cli
wecom-cli auth init          # 扫码；或 --manual 输入 Bot ID 与 Secret
wecom-cli auth show          # 确认输出 authorized
```

**第二步，在 worker 环境中设置目标会话**：

```bash
SOYMUTDB_WECOM_BOT_CHAT_ID=<单聊填成员 userid，群聊填群会话 ID>
```

会话 ID 用 `wecom-cli message aibot sessions list` 查询（返回最近 20 个会话，按最后一条消息时间倒序）。

未配置 `WECOM_BOT_CHAT_ID` 时通知静默跳过；CLI 未安装或未授权时同样静默并记一次 warning。API、导入、发布主流程不依赖企业微信可用性。

**旧的 `SOYMUTDB_WECOM_BOT_WEBHOOK` 已不再读取。** 群机器人 webhook 通路在切换到 CLI 时退休，保留该变量的主机因为没有 chat ID 而保持静默，不会半可用。需要回退请用 `git revert` 对应的切换提交，而不是把 webhook 变量加回来。

## 通知事件

- BLAST / FASTP / Scanpy / GWAS 任务完成或失败：任务类型、短任务 ID、结果。
- 新种子申请：申请 ID、基因数量、待审核状态；**不发送申请人姓名/邮箱**。
- 活跃 release 切换：当前与上一版本 ID。

消息使用企业微信 Markdown，以字段/值摘要呈现；完整、可排序的表格仍在管理端。企业微信消息不是交互式数据库表格，消息不会包含原始文件、完整报错或申请人个人信息。发送失败只记 warning，绝不使任务失败。

## 排障

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 完全没日志、也没消息 | `WECOM_BOT_CHAT_ID` 未设置 | 通道静默禁用，属预期 |
| 一次 warning：CLI 未安装 | 主机上找不到 `wecom-cli` | 装 `@wecom/cli` |
| 一次 warning：凭据被拒 | 该主机未 `auth init`，或 secret 已轮换 | 重新 `wecom-cli auth init` |
| 反复 warning：exit=2 | 调用形态错误（配置问题，非投递失败） | `wecom-cli <service> --help` 对照 |
| 反复 warning：exit=1 | 后端拒绝或网络问题 | `wecom-cli <service> --help` 后手工复现 |

`wecom-cli` 的 schema 在运行时从服务端下发，能力集合不是静态的。使用某个方法前先看 `wecom-cli <service> [resource] <method> --help`。

调试期可开日志（只写 stderr，不污染 stdout 的 JSON）：

```bash
WECOM_CLI_LOG_LEVEL=debug wecom-cli message aibot send --chat-id <id> --msg-type markdown --markdown '{"content":"probe"}'
```

## 本地验证

`apps/worker/tests/test_wecom_bot.py` 覆盖停用态、CLI 缺失降级、投递失败与鉴权失败路径；`apps/worker/tests/test_wecom_cli.py` 覆盖退出码与错误 JSON 的分类。

真机发送前可先用 `--dry-run` 本地校验请求形态——**该命令不需要凭据**：

```bash
wecom-cli message aibot send --chat-id probe --msg-type markdown --markdown '{"content":"probe"}' --dry-run
```

真机投递必须用真实 chat ID，且会对接收方可见。
