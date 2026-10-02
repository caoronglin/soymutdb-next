# PI 检测与验收门禁

> **已归档（2026-10-01）**：智能体执行日志与提示词草稿（治理要求工作区不存放日志）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §7 变更记录；执行结论见 docs/dev/project-status.md。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

本文件是实施时的检查协议；本次提示词交付没有运行产品测试，也没有将下列全部要求接入 CI。依据当前 package scripts、数据库核心契约和本包 R/V 清单；执行前核对路径与版本。H01–H12、C01–C18 的原要求继续有效。

## 0. 基线

在实际仓库根目录记录：

```bash
git rev-parse HEAD
git status --short
node --version
pnpm --version
python3 --version
apps/api/.venv/bin/python --version
apps/worker/.venv/bin/python --version
```

要求 Node 24（.nvmrc 为 24.19.0）、pnpm 11.21.0、Python >=3.14。依赖范围不代表已安装版本；不能把 API venv 通过当 worker 环境通过。SMB 路径不是状态文档中原生路径的运行验证。确认测试目标隔离及 fixture 清理行为，记录脱敏的隔离依据后再启动数据库测试。

## 1. 约束到证据

| 触发面 | 必需检查 | 关联 |
| --- | --- | --- |
| 公开身份/发布 | 合法 public_id 正测、现存/不存在内部键负测、未发布/删除排除、唯一性/并发碰撞/缺号发布拒绝 | H01–H03；ID-01–04；R01/V02/V03 |
| 模型/迁移/worker | 隔离 PG 旧数据升级、约束/外键、降级及再次升级；不可表示数据明确拒绝降级并验证恢复方案；真实 worker 读写和投影关联 | H04/H12；R02/R03/V01 |
| assembly/crosswalk | v4/v5 同 accession 共存、指定/未指定/不匹配版本；可信映射与相似但无映射反例 | H04–H08；ASM-01–05；R04/V03 |
| 缓存/权限 | 同 query 跨站点、release、assembly、内部 A/B 数据范围；错误及成功响应 private/no-store；cursor 与旧结果失效 | H03/H09/H10；CTX-01–03；R05/R06 |
| 对象与制品 | 两 release/assembly 同名对象真实写读不覆盖、未发布对象不可公开；两套制品和哨兵输入/检出证据 | H10/H11；ID-05；R07 |
| API/client/UI | 正式生成及契约检查、所有消费者、真实网络搜索→详情→JBrowse；版本/身份可见；键盘/空错态/响应式 | H07；UI-01/02；E2E-01/02；R01/R04 |

完整核心交付必须覆盖 external/internal × public/internal identifier × v4/v5，并补权限和发布状态维度。对基因专有场景说明标识符维度不适用，不能硬造 mutant 场景。关键矩阵不得 skip/xfail 放行。

## 2. 从窄测试到根门禁

先通过 rg 和当前测试配置找到每个 R/V 的具体用例并记录 node ID；不要把“有测试文件”当“已覆盖”。下列为现有全套入口，按变更范围执行；Python 测试含哪些隔离资源以当前 conftest 为准。

```bash
# cwd: apps/api
.venv/bin/python -m pytest tests -q
# cwd: apps/worker
.venv/bin/python -m pytest tests -q
# cwd: 仓库根目录
pnpm --filter @soymutdb/api-client generate:api-client
pnpm --filter @soymutdb/api-client check:contract
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm --filter @soymutdb/web build:sites
python3 -m unittest scripts.test_site_artifact_isolation -v
# cwd: e2e；先核对真实 API 和 external/internal 项目配置
pnpm exec playwright test
```

API 变化才需生成客户端；生成后审查 diff。worker/jobs-py/MCP 变动还需其对应 suite，不能以根 Vitest 代替 Python 测试。双站构建不被单站 build:ui 替代。infra/deploy/认证/发布改动增加对应现有脚本与隔离 health-check。定位测试配置后再填写准确命令，不随意新增空 job。

## 3. 泄漏检测不得空跑

1. fixture 含合成的私有内部身份、未发布记录与唯一保护值；证明这些输入实际进入待验证 API/构建链。
2. 检查扫描器污染样例确实失败、缺目录/缺哨兵会失败，再对本轮真实制品扫描。不可仅扫描已有旧 dist。
3. 对每个真实注入值传一次 --sentinel；下面环境变量必须由隔离 fixture 设置，非空检查不等于注入证明。

```bash
# cwd: 仓库根目录；SOYMUTDB_PRIVATE_SENTINEL 由本轮合成 fixture 提供
test -n "$SOYMUTDB_PRIVATE_SENTINEL"
python3 scripts/check_site_artifact_isolation.py \
  --external-root apps/web/dist/external \
  --internal-root apps/web/dist/internal \
  --sentinel "$SOYMUTDB_PRIVATE_SENTINEL"
```

不得在 test 命令失败后继续扫描。扫描器当前按传入值的原始字节/路径检测，不自动证明压缩包、编码变体、响应体、URL、客户端日志或对象权限安全。补充解压/解析后的适用制品与浏览器/网络断言；JSON/HTML/manifest/source map/SW 都需覆盖。通用字符串 internal_id 的存在与真实私有值泄漏是不同问题，公开 DTO 字段结构另用 schema/响应断言验证。

## 4. 可强制执行的边界

提示词用于行为约束，真正阻断依赖外部控制：运行器只授予工作区和隔离测试资源；不注入生产凭证；将适用测试设置为受保护分支 required checks；CI 保存本轮日志/报告和制品关联。检查 job 的 continue-on-error、条件跳过、失败吞掉和 pytest 关键 skip/xfail，不能只依赖退出码 0。

PI extension 的工具拦截可以补充交互防护，但不能把 shell 正则黑名单当系统沙箱；脚本、子进程、网络和扩展自身权限必须由运行环境控制。本次不自动安装扩展、不改 CI 或分支保护设置；实施阶段需逐项记录哪些门禁已经真实接入。

## 5. 证据格式与结论

```text
任务/约束/Scenario：
当前 HEAD + 相关 diff/文件摘要：
cwd / 工具版本 / 运行时间：
完整命令 / 退出码：
pass / fail / skip / xfail：
日志或报告路径（不含凭证）：
结论：PASS / FAIL / NOT_RUN / N/A（必须解释）
阻碍与恢复动作：
```

VERIFIED = 当前行为实现 + 所有适用正反例/集成证据通过 + 消费者一致 + 证据可复现。实现存在但关键集成未运行是 IMPLEMENTED_UNVERIFIED；缺输入无法推进是 BLOCKED。PI 进程成功退出、历史通过数、静态阅读和提示词检查都不能证明产品完成。
