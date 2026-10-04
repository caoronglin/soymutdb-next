# 新对话执行提示词

状态：可用于新会话启动；不是既有代码全部验收通过的声明。对应方案：[审计后全局优化执行方案](../aegis/plans/2026-10-02-audited-optimization-execution.md)。

## 完整启动文本

```text
在当前 SoyMutDB 仓库执行审计后的优化实施，不沿用旧对话的错误结论。

先读取：
AGENTS.md
docs/README.md
docs/aegis/BASELINE-GOVERNANCE.md
docs/aegis/baseline/2026-10-01-react-only-baseline.md
docs/dev/database-core-contract.md
docs/dev/design-audit-2026-10-02.md
docs/aegis/plans/2026-10-02-audited-optimization-execution.md
按涉及页面继续读 admin-pro-migration、门户 UI 和运维/企业微信文档。

以执行方案为本轮工作合同，遵守 H-01 至 H-18。旧 .validation/docopt-2026-10-02 草稿只作历史证据。
先完成 W0：记录 HEAD、分支、完整 dirty 状态、工具版本、真实环境可用性、现存红灯。
保留已有文档改动、apps/web/src/ablation/、apps/web/src/lib/session.ts；它们需审查而非默认正确。
读相关历史踩坑记录，但沿发布入口与当前源码逐条复核。

默认按 W0 → W1 执行，再做 W2/W3 的明确任务，并按页推进 W4。
每包先记录修改路径、风险、依赖、对照、验收、回滚；完成后实际跑相关测试，给出命令和真实 exit。
别只给计划：在前置齐备的范围内继续实现、复测、更新状态。无关阻碍不停止整个任务。

必须记住：
1. 守卫已通过共享脚本间接接入 CI；检查完整调用链，避免重复接线。
2. assemblies API 已 release-scoped；修查询工厂漂移，保留 all() 为失效前缀。
3. 复用 api-client 的 token/refresh/单飞/登出协调；React 层提供响应式会话状态。
   不直接把孤立 session.ts 布尔门控接入就宣布修复。
4. 匿名公共浏览与公开申请保持可用；个人功能按登录与服务端 grants 控制。
   网络/5xx 不作匿名或权限失败；登录、恢复、登出、账号切换清理个人缓存。
5. 公开申请是 seed_request_contacts，已有 processed_by 外键与新申请机器人通知。
   与 seed_requests 分开；扩展既有 outbox，不重建同一通知链。
6. 企业微信群机器人、智能表格、表单、回调、文档搜索先核实具体产品/API/官方权限合同。
   凭据分服务管理；可靠同步需幂等映射、版本、防乱序、重试/死信/对账。
   文档搜索必须逐文档 ACL，撤权后标题/摘要也不泄漏。
7. pgcli 是客户端。索引候选在独立测试库做公平 A/B，不宣称旧“100×”或“从未 ANALYZE”。
   不终止未知会话、不改共享库参数、不重启数据库、不直接在主库做实验。
8. ant CLI 需记录别名门面盲区；多行 alt、适配器 rowKey、键盘焦点与窄屏查真实渲染。
   不靠 export 全部组件、baseline 洗白或源码计数获得绿灯。
9. 消融必须对照通过、只改一个实际保护因素、真实路径翻转、恢复复测。
   导入/语法失败、未命中变异、孤立辅助函数通过不计端到端 ACTIVE。
10. 数据 release 原子切换不等于整栈发布；W7 要有 manifest/digest、兼容迁移、候选健康、流量切换和故障回退。

测试与发布纪律：
skip/xfail/缺环境均单列，不计完成。CI pin 和锁文件保持，不引入第二权威存储。
生产发布、真实企业数据出站、主库配置、提交/amend/push 只在明确指令后执行。
秘密不写入日志、文档、URL 或前端存储；API 和迁移变更同步契约与 PostgreSQL 验证。
发现身份泄漏、数据损坏风险、证据矛盾或与用户改动冲突，停止对应子任务并定位最早不确定节点。

最终交付：逐包结果、文件 diff、测试/消融数量及层级、命令/exit、原始证据路径、未跑项与前置、回滚点、下一步。
把实际结论更新到现行方案/项目状态，不把待执行写成已完成。
```

## 最短启动文本

```text
读取 docs/aegis/plans/2026-10-02-audited-optimization-execution.md 和 docs/dev/execute-audited-optimization-prompt.md，
按完整启动文本及 H-01–H-18 执行。先做 W0，保留 dirty 工作树，再修 W1，继续 W2/W3；
每包真实验证并记录消融证据层级。不要重复接 CI、直接挂孤立 session.ts、实验主库或自动发布。
```
