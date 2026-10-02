# 基础模式任务变更边界记录

> **已归档（2026-10-01）**：一次性的基础模式验收战役记录（操作手册仍在 ops/）。继任：`docs/ops/README.md` 及其下的现行运维手册；部署事实见 `docs/dev/project-status.md`。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

## 基线事实

在本轮智能体分派前，工作树已经存在 Web/Admin 重构修改。分派前的 Git 状态快照包含：

- apps/web 多个页面、page-builder、构建脚本和 deployment 文件
- apps/admin 多个组件、路由、Vite 配置和 UI 测试
- apps/admin/Dockerfile、apps/api/Dockerfile、apps/worker/Dockerfile 等删除/修改
- .github/workflows/ci.yml、docker-compose.yml、nginx 和部署文档修改

因此当前工作树不能用来推断这些前端修改来自本轮 baseline 任务。

## 本轮允许范围

| 任务 | 允许修改 | 明确禁止 |
|---|---|---|
| 后端 baseline | apps/api/app、apps/api/tests、后端文档 | apps/web、apps/admin、packages/ui、现有 workflow、docker-compose |
| Linux no-Docker | deploy/linux、deploy/scripts baseline 脚本、Linux 文档 | 前端、API 业务代码、现有 workflow、docker-compose |
| Windows no-Docker | deploy/windows、Windows 文档 | 前端、API 业务代码、现有 workflow、docker-compose |
| CI/CD | 新增独立 baseline workflow 和 CI 文档 | 现有 ci.yml/pages.yml/e2e-smoke.yml、前端源文件、docker-compose |

## 本轮新增/修改证据

- 后端：apps/api/app/api/v1/health.py、apps/api/app/core/config.py、apps/api/tests/test_health.py、apps/api/tests/test_health_unit.py、apps/api/tests/test_config_security.py。
- Linux：deploy/linux、deploy/scripts/baseline-*.sh。
- Windows：deploy/windows/。
- CI：.github/workflows/baseline-validation.yml、docs/ci-cd-baseline.md。
- 验收文档：docs/ops/baseline-*.md。

## 验证规则

1. 不执行 git reset、git clean 或覆盖前端重构文件。
2. 每个任务只在允许目录内修改。
3. 前端完整构建属于原有前端项目的独立验证，不作为 baseline 智能体修改结果。
4. Windows PowerShell、GitHub protected environment、远程备份/迁移/回滚仍必须由真实 runner/staging 提供证据。
