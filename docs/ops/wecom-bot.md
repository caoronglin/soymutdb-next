# 企业微信机器人通知

SoyMutDB 支持通过**企业微信群机器人 webhook**发送运维摘要。功能默认关闭；webhook 只放在 worker secret 环境变量，不写数据库、不回显到管理端、不进日志。

## 配置

在运行 Celery worker 的环境中设置：

```bash
SOYMUTDB_WECOM_BOT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<群机器人密钥>
```

Docker Compose 的 worker queues 已映射该变量。未配置时通知静默跳过；API、导入、发布主流程不依赖企业微信可用性。

## 通知事件

- BLAST / FASTP / Scanpy / GWAS 任务完成或失败：任务类型、短任务 ID、结果。
- 新种子申请：申请 ID、基因数量、待审核状态；**不发送申请人姓名/邮箱**。
- 活跃 release 切换：当前与上一版本 ID。

消息使用企业微信 Markdown，以字段/值摘要呈现；完整、可排序的表格仍在管理端。群机器人不是交互式数据库表格，消息不会包含原始文件、完整报错或申请人个人信息。发送失败只记 warning，绝不使任务失败。

## 本地验证

`apps/worker/tests/test_wecom_bot.py` 覆盖停用态、安全的 webhook host、Markdown payload、WeCom errcode 和异常失败路径。真机发送需注入有效 webhook secret 后验证。
