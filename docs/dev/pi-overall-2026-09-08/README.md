# SoyMutDB 整体完善：PI 执行包

日期：2026-09-08。范围：整体完善方案、硬性约束、技术与界面设计、分阶段实施与验收。此次交付是方案，未实施产品改造或运行产品测试。

## 使用入口

### 本次补齐：系统提示词与检测入口

本轮新增 [追加系统提示词](system.md)、[可直接执行的修改提示词](start.md)、[检测与硬门禁](verification.md) 和 [本轮代码/资料核验](research-refresh.md)。复用下方整体方案、H01–H12 和已有执行记录。本轮默认续接 R01–R07/V01–V03，避免把一次修复扩大为全项目重写。

本机已只读核对 PI `0.85.1` 的 `--version`/`--help`：`--append-system-prompt` 接受文本或文件内容，`@file` 可加载任务。检查时 settings 锁因沙箱只读出现 EROFS 警告；并未启动模型会话、验证 provider 或修改 PI 配置。其他机器仍须核对安装版本和模型清单。

在实际仓库根目录执行以下命令，使用 PI 中已配置且核实可用的模型：

```bash
pi --append-system-prompt docs/dev/pi-overall-2026-09-08/system.md \
  @docs/dev/pi-overall-2026-09-08/start.md
```

不加载旧 `docs/dev/pi-agent-system-prompt.md`。本包 system.md 使用追加方式，保留 PI 默认提示和适用 AGENTS.md。本次没有安装扩展、修改生产配置或运行产品修改；下面的旧启动方式仍可用于整体 W0–W7 范围，但不要与本轮限定范围混用。

1. 阅读 [整体方案](plan.md)：目标设计、硬约束、任务依赖、验收和恢复协议。
2. 把 [执行提示词](prompt.md) 交给 PI，工作目录设为实际仓库根目录。
3. [证据与官方资料](sources.md) 区分代码观察、历史记录和设计建议。
4. PI 执行时在本目录另建 `execution-status.md`，按方案模板保存进度；不要把本次方案交付标为产品完成。

用户最新清单已去重为 [W1–W3 修复接续任务](w1-w3-repair.md)：R01–R05 修复、R06–R07 先验证，以及迁移/签发/搜索的三组运行证据。在仓库根目录交给 PI：

```bash
pi @docs/dev/pi-overall-2026-09-08/prompt.md @docs/dev/pi-overall-2026-09-08/w1-w3-repair.md
```

该接续任务限定本轮范围，复用已完成 W0，不要求重新规划全部阶段。

本包用于本次“整体完善”任务。根目录及适用子目录的 AGENTS.md、本次用户提供的仓库约束继续有效。旧 `../pi-agent-system-prompt.md` 中“用户已撤销 AGENTS.md”的表述不适用于本次任务；不要把旧提示词作为本包的系统提示加载。旧数据库 T0–T5 是核心工作参考，旧优化 A-* 项是待核验设计索引，均不是要求重做的清单。

## 在 PI 中启动

这里按 pi coding agent 理解 PI。官方旧仓库地址目前重定向到 `earendil-works/pi`；以下参数依据 2026-09-08 官方文档，执行前仍须核对安装版本。此次未安装或启动 PI。

在仓库根目录先运行：

```bash
pi --version
pi --help
pi --list-models
```

确认使用预期 provider/model；本次 Codex 子代理指定了 gpt-5.6-luna，但这不证明你的 PI provider 提供同名模型。若要指定，使用本机模型清单中的真实名称配置 `--provider` / `--model`，不可静默换模型或在日志中伪报模型。

推荐交互启动，保留 PI 默认系统提示和 AGENTS 加载：

```bash
pi @docs/dev/pi-overall-2026-09-08/prompt.md
```

需要非交互运行时，每次指定一个阶段；print 退出本身不代表阶段验收通过：

```bash
pi -p @docs/dev/pi-overall-2026-09-08/prompt.md "本次只完成 W0，写入执行状态和下一阶段输入，不修改产品代码。"
```

W0 冻结契约后，按依赖顺序对 W1–W7 分次运行，例如：

```bash
pi -p @docs/dev/pi-overall-2026-09-08/prompt.md "读取 execution-status.md，完成 W1；保留 W0 契约，按验收更新状态。"
```

上例的 `execution-status.md` 指本执行包目录中的文件。阶段未通过就修复该阶段；不要用自动 shell 循环根据 PI 退出码推进全部阶段。交互模式下可连续推进依赖已满足的已授权阶段。

需要续跑时：

```bash
pi @docs/dev/pi-overall-2026-09-08/prompt.md "续跑：先读本包 execution-status.md，核对 diff 与证据，继续第一个依赖满足的未完成任务。"
```

也可用官方 `--session` 选定已记录的会话。不要在同一工作目录存在多个任务时依赖“最近会话”猜测恢复目标。

本包不写入 `.pi/SYSTEM.md`，不关闭上下文文件加载，不默认加 `--approve`。项目 trust 可加载/执行本地扩展，应检查实际资源后按 PI 的项目信任流程处理。提示词与工具列表不是文件系统或生产数据库的权限边界；运行器须只提供工作区、隔离测试环境和必要凭证。[PI 官方用法](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)

## 交付边界

默认包含本地实现、迁移文件、隔离测试、文档与 staging 验收方案；真实数据接入依赖已确定来源和授权。生产写入、生产迁移、正式发布不包含在默认执行范围内。W8 为明确列出的独立后续方向，不纳入本轮整体完善完成度。
