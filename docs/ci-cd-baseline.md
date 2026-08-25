# CI/CD baseline

新增 workflow：.github/workflows/baseline-validation.yml。

## 验证范围

- Ubuntu job 使用 GitHub PostgreSQL service，执行 Alembic migration、baseline 配置/健康单元测试、Ruff、API /health smoke 和 API wheel 构建。
- Windows job 不使用 service container；执行 PowerShell parser、deploy/windows/install.ps1 -DryRun、Docker-free unit tests、API /health smoke 和 API wheel 构建。
- Web/Admin 在 Ubuntu 构建静态产物并检查 localhost、CHANGE_ME、placeholder 和 example origin。
- contract job 启动无数据库依赖的 FastAPI OpenAPI 导出链，运行 packages/api-client 的 check:contract，阻断生成 client 与后端 schema 不一致。
- supply-chain job 生成 baseline no-Docker deployment bundle、CycloneDX SBOM、SHA256SUMS 和 commit manifest。
- 所有第三方 GitHub Actions 均使用固定 40 位 commit SHA；job 权限按 job 收缩。

## 部署安全门

- staging-dry-run 和 production-dry-run 只在 workflow_dispatch 且显式输入 deploy_staging/deploy_production 时执行。
- staging 和 production 使用 GitHub protected environments；仓库设置应配置 required reviewers、分支限制、STAGING_HEALTH_URL 和 PRODUCTION_HEALTH_URL。
- 部署 job 仅授予 id-token: write；不在 PR 使用生产 secrets。
- 当前 workflow 只执行 native installer dry-run 和目标配置门禁，不伪装成已经连接远程服务器；真正的 SSH/WinRM/OIDC/backup/migration/deploy/health/rollback target adapter 必须在受保护环境中补齐后才允许接入。
- production 需要 staging 成功、显式 deploy_staging=true 和 deploy_production=true，并经过 production environment 审批。

## 最近远程验证证据

- `ci.yml` release run [`32843469602`](https://github.com/caoronglin/soymutdb-next/actions/runs/32843469602) 已通过前端/API/contract、amd64/arm64 Docker build/smoke、Trivy、SPDX SBOM、Kind smoke、GHCR 多架构发布、Cosign 签名/证明和 OCI release contract。
- `baseline-validation.yml` run [`32843469562`](https://github.com/caoronglin/soymutdb-next/actions/runs/32843469562) 已通过 Windows installer/dry-run、Docker-free unit/liveness smoke、Linux PostgreSQL、Web/Admin、OpenAPI/client contract 和 deployment attestations。
- 上述 run 只证明对应 commit 的 CI/baseline 门禁；真实生产服务器、受保护环境审批和远程回滚仍需按本文件的 deployment safety gate 执行。

## GitHub-only / 本地未执行部分

本地已完成 YAML 解析、固定 SHA 检查、Linux shell 语法、native installer dry-run 和 API unit/Ruff 验证，但无法执行 GitHub runner 的 Windows PowerShell parser、Ubuntu/Windows artifact 服务、protected-environment 审批、OIDC token exchange、远程备份/迁移/部署/回滚和真实 SBOM 产物。合并后必须运行 baseline-validation.yml 并保存 release artifact、manifest、SBOM、migration head 和 smoke 日志。

现有 .github/workflows/ci.yml、pages.yml、e2e-smoke.yml、前端源文件和 docker-compose.yml 未由本方案 workflow 修改。
