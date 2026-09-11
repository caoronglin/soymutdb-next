# 本轮项目与 PI 核验

日期：2026-09-08。目标是提示词和验收协议交付，不是产品修改或全仓审计。经用户同意，委派两个 gpt-5.6-luna 子代理分别只读梳理代码、搜集 PI 官方资料；原请求的 gpt-5.4-mini 不在本次子代理接口支持列表中。

2026-09-09 收尾说明：资料子代理已交付官方来源；代码子代理因额度限制未交付报告。下列源码观察由主代理直接核对，不冒称为子代理完成的全仓审计。

## 主代理直接确认

- 当前 SMB 工作区 HEAD 为 `6592dfd8e562e5b1722ffc9f3c12068c05654525`；全仓 git status 读取缓慢，不能据此声明工作树干净。现有 execution-status.md 的改动数、原生路径和环境阻碍都是历史记录，需 PI 开工重验。
- 根 package.json：pnpm/Turbo monorepo，pnpm 11.21.0、Node >=24 <25；.nvmrc 为 24.19.0。apps/web/package.json 使用 React 19、Vite 6、TanStack、AntD，含 build:sites。这里的依赖范围不等于实际安装版本。
- apps/api/pyproject.toml：Python >=3.14，FastAPI、SQLAlchemy asyncio、asyncpg、Alembic、Celery/Redis、ClickHouse 与对象存储相关依赖。不是 Vue/Rust 项目，不沿用其他任务的语言假设。
- packages/api-client/package.json 具有 generate:api-client 和 check:contract 正式入口；根质量入口为 lint/typecheck/test/build。API/worker Python 测试需单独运行。
- docs/dev/database-core-contract.md 明确自身是目标契约，2026-09-06 基线不能当今天的缺陷清单。本包 execution-status.md 已记录部分实现及未验证状态；R01–R07 必须逐项重验，不能照历史描述重新改一遍。
- 旧 docs/dev/pi-agent-system-prompt.md 有“AGENTS.md 已撤销”的过时表述。本次用户明确提供并采用仓库约束，因此新增 system.md 作为当前入口；保留旧文件及执行历史，不加载旧指令。
- scripts/check_site_artifact_isolation.py:19 定义双目录与哨兵参数；:59 的扫描只覆盖传入值；:102 读取原始字节，不自动解压或解析编码。verification.md 因此要求额外的编码/压缩及响应/日志检查，不能扩大宣称现有扫描能力。
- .github/workflows/ci.yml:163 已有 client contract 检查，:271 有 API pytest，:282 有 worker PG 集成测试步骤；e2e-smoke.yml:88 有 Playwright 入口。文件中存在步骤不证明远程已成功，也不证明全部 H/C 矩阵和 required checks 已接入。

## PI 使用核验与来源

补充源码证据：apps/api/app/main.py:280 为 create_app 入口，:325 挂载 API router；apps/web/src/main.tsx:85 创建前端 router，:159 渲染入口。apps/api/app/models/variant.py:145 已有 public_id；genomic.py:110 已有 gene_pk，:164 有 assembly/accession 联合约束，:258 已有 GeneCrosswalk。不能将这些能力写为“完全不存在”。apps/web/src/routes/search.tsx:56 的 queryKey 当前包含 q/types/cursor/limit/external，未显式包含 assembly/release/site variant，:63 保留 previous placeholderData；这是 R05 的现状核验依据，实际串数据影响仍需上下文切换与网络测试证明。

主代理在 `/tmp` 执行本机 `pi --version` 和 `pi --help`，版本为 **0.85.1**。帮助明确支持 `--append-system-prompt <text>` 加载文本或文件内容，以及 `@files`、`--session`、`--list-models`。帮助执行出现 ~/.pi/agent/settings.json.lock 的只读 EROFS 警告；未读出凭证、未启动模型会话、未验证 provider 可用性。

官方文档核对日期为 2026-09-08，main 分支可能继续变化：

| 官方来源 | 与本包的关系 |
| --- | --- |
| [PI usage](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md) | 系统替换/追加、上下文文件与项目信任规则；本包用显式 CLI 文件追加 |
| [PI README](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/README.md) | 命令行 @files 和模型选择；模型由运行器配置，不由提示文本切换 |
| [Prompt templates](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/prompt-templates.md) | 可选 /name 模板和参数展开；本轮直接用 @start.md，无需安装模板 |
| [Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) | tool_call 可在工具执行前阻断；扩展具有系统权限，不能将拦截器等同于沙箱 |

系统提示替换会替换默认内容；追加保留默认行为。当前官方文档也支持 APPEND_SYSTEM.md，但本包不依赖自动发现、不改全局配置，不自动信任未知项目扩展。生产隔离和不可绕过的门禁要由操作系统/容器、数据库权限和 CI 实施，不能由提示词单独保证。

## 本轮交付边界

新增 system.md、start.md、verification.md、本文件；更新 README 启动入口。复用 plan.md、w1-w3-repair.md、H01–H12、核心测试矩阵与现有 execution-status.md，不修改业务代码或执行生产动作。

文档检查只能证明入口、引用和命令名称一致。PG 迁移、双站构建、真实 API/E2E、模型加载与行为遵循均未在本轮运行；这些是 PI 实施阶段必须提交的证据。
