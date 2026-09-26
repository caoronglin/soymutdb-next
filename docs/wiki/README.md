# SoyMutDB 项目 Wiki

面向开发、运维与接手者的项目知识库。本目录只写**当前事实**（代码、配置、契约可核对）；
尚未实现的能力明确标注「计划中」，不写成已上线。

## 页面

| 页面 | 内容 |
| --- | --- |
| [architecture.md](architecture.md) | 系统组成、数据流、权威存储与隔离边界 |
| [applications.md](applications.md) | 公共站与管理端功能、路由与 Vue 迁移状态 |
| [api-and-ports.md](api-and-ports.md) | API 路由分组、端口表、配置来源 |
| [deployment-and-ops.md](deployment-and-ops.md) | 构建交付、部署、备份/迁移/回滚、门禁命令 |
| [multi-instance.md](multi-instance.md) | 多实例登记、探活与远端信任模型 |

当前总体状态（部署、门禁、缺口）：[../dev/project-status.md](../dev/project-status.md)。

## 事实来源（以这些为准）

- 交付流水线：`.cnb.yml`（权威）+ `scripts/ci-job-steps.sh`（任务体）。
- 数据库与身份契约：`docs/dev/database-core-contract.md`。
- Vue 迁移状态与证据：`docs/dev/vue-migration-recovery-status.md`。
- 项目总体状态（单一视图）：`docs/dev/project-status.md`。
- 端口与编排：`docker-compose.yml`、`deploy/.env.example`、`deploy/conda/env.example`。
- API 契约：`apps/api/app/api/v1/router.py`、`packages/api-client/openapi.json`。

## 维护规则

1. 端口、路由或部署方式变化时，同时更新本 wiki 与对应的契约测试。
2. 功能实现状态变化时更新 [applications.md](applications.md)，并在
   `docs/dev/vue-migration-recovery-status.md` 记录命令与结果。
3. 本目录不复制大段配置；引用文件路径与契约测试，避免漂移。
