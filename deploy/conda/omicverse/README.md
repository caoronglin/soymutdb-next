# M3 OmicVerse 环境资格 profile（CPU-only）

本目录由 `deploy/conda/` 拥有，但这是 **uv/pip hash-lock 资格 profile**，不是
conda solver 的资格证明，不更改通用 mamba/conda API 或 worker 环境。
仅复现隔离环境的公开 `omicverse.bulk.pyDEG` import 和 toy counts smoke；没有
生产 adapter、任务/队列、数据库、CI、镜像或线上启用。M4–M7 仍单独验收。

## 固定内容与资格边界

- CPython **3.14**，实际资格机 **3.14.8 / Linux x86_64**；uv **0.11.33**。
  现有 resolver/import/runtime 通过，没有 Python 降级依据；不改主项目 pin。
- [requirements.in](requirements.in) 仅固定 **omicverse 2.3.2 + pydeseq2 0.5.4**。
  后者虽为上游可选分析依赖，`deg_analysis` 实际无条件导入它（包括 ttest）。
- [requirements.lock](requirements.lock) 为 2026-10-08 经 uv 0.11.33 实际 resolver
  得到的完整 **131 项**依赖/hash。固化保留全部版本/hash，仅调整来源注释；不是再次
  求解或手猜兼容版本。base OmicVerse 的传递依赖（包括 Scanpy、Transformers、
  notebook/OpenAI 库）仍保留，不通过裁剪冒充 pyDEG 最小闭包。没有 easy/full/GPU
  extras、torch/NVIDIA 包，不使用网络 API 或需要密钥的功能。
- 本机通过不代表其他 Linux/glibc、ARM、macOS、Windows、free-threaded Python 或
  wheel ABI 的资格。锁可含其他平台 hash，但只有本机 Linux x86_64 实跑。
  初次同步需要索引可达或 caller 另备可信 wheel/cache；hash-lock 不是离线 wheel 包。

## 一次性新环境与实际 smoke

从仓库根运行；工具与已有解释器只读使用。caller 必须提供 **尚不存在**的
`ENV_PREFIX` 和 `OUTPUT_DIR`，且两个路径不嵌套、父目录已存在，均应放在忽略目录。
入口拒绝任何 existing folder/file/symlink，不删除、清空或更新旧环境；失败时保留
新建的部分环境及证据，下一次选新路径，不重用失败目录。

```bash
mkdir -p .validation/m3-delivery-20261009
UV_BIN="$PWD/.validation/m3-omicverse-20261008/tool-env/bin/uv" \
PYTHON314="$PWD/apps/api/.venv/bin/python" \
ENV_PREFIX="$PWD/.validation/m3-delivery-20261009/env-fresh" \
OUTPUT_DIR="$PWD/.validation/m3-delivery-20261009/fresh" \
  bash deploy/conda/omicverse/setup.sh
```

以上 uv 路径只是本机复验示例，不是脚本内依赖；其他 checkout 给出自己的 uv 0.11.33
和真实 CPython 3.14 路径。读取 API 解释器创建新 venv 不向 API 环境安装任何依赖。
[setup.sh](setup.sh) 唯一入口执行新 venv → `uv --no-config pip sync --require-hashes`
→ `uv --no-config pip check` → [toyqualify.py](toyqualify.py)。脚本不编译/刷新锁。
有意升级时用 uv 0.11.33 在本目录执行锁头的 compile 命令，审查完整 resolver 差异并
重跑 fresh 资格，不能仅改 pins 宣称通过。

[run_bounded.py](run_bounded.py) 仅为本 profile 实验命令 runner：create/check 30 秒，
hash-sync 240 秒，真实 smoke **180 秒**；每个子进程 **8 GiB RLIMIT_AS**、CPU 时间限制、
单 CPU affinity。公开 `PYTHON_CPU_COUNT=1` 加 BLAS/OMP/MKL/NUMBA/LOKY/Rayon/uv 线程
限制为 1，在 **子解释器启动之前**设置，无 monkeypatch。
OmicVerse 未把 `n_cpus` 转给 `DeseqStats`，PyDESeq2 的默认 multiprocessing CPU 数在
资格机是 256；单 affinity 与 LOKY 限制不足，必须保留 Python CPU override。
资源上限是每进程地址空间/CPU，不是 cgroup 总 RSS 或生产作业预算。

runner 给命令建立独立进程组，timeout（exit 124）、SIGINT/SIGTERM 或 leader 退出后
清理整个组并 wait，避免保留同组 orphan。脱离 session 的任意恶意子程序不在此 toy
runner 的 containment 保证中；它不是线上取消系统。证据输出各步 `command.log` /
`command.json`（精确命令、退出码、墙钟、child max RSS）及 `toy/qualification.json` /
toy CSV。缓存、HOME、临时目录都在 caller 的 evidence 子树，不写 source 或用户 cache。
这些 CSV/日志只作本地证据，不应纳入版本控制。直接重跑 runner/toy 时也要选 NEW output。

## 方法语义与通过断言

固定 seed **20261008**，genes×samples 的 **200×8 int64** 原始 counts，两组各四重复；
20 个 treated 上调、20 个下调、一个全零基因、一个恒定基因。toy IDs 的 assembly/release
均标 synthetic-only，不表示大豆生物学映射或科学参考集。

1. `pyDEG(raw).normalize()`（真实方法名不是 `normalization()`）保留 caller/raw_data，
   但 `self.data` 变成 float normalized counts。随后 `method='ttest'`，treated 为 group1、
   control 为 group2；固定 `alpha=.05, multipletests_method='fdr_bh', n_cpus=1`，
   cooks/independent filter 均 False。199 行、有限 p/q∈[0,1]、40 显著、方向 20+/20−。
   SciPy ttest 与独立 statsmodels BH 核对实际上游 **NaN→0 后 BH 再删 NA**规则；
   与先删 NA 再 BH 最大差约 **0.00516046952474114**。复现不是认可：**不作为生产 default**。
2. normalized 同对象调用 `method='DEseq2'` 必须实际出现
   `ValueError: The count matrix should only contain integers.`；意外成功或其他异常均失败。
   **不 rounding、不将 float 伪装整数**，保留原始 counts。
3. fresh `pyDEG(original_integer_counts).deg_analysis(..., method='DEseq2')` 让 PyDESeq2
   内部 normalize；200 行、199 finite，全零基因的 NA p/padj 保留；40 显著、20+/20−，
   finite p 的 BH 逐项核对 `rtol=1e-12, atol=1e-15`。OmicVerse 此分支忽略
   `multipletests_method`，PyDESeq2 0.5.4 直接使用 BH；ttest qvalue 与 DEseq2 padj
   是不同方法输出，不混称同一统计路径。

manifest 记录 runtime distributions、公开签名、库 source/lock/input/output SHA256、
方向、BH、零基因、原始 counts 不变和 warnings。Python 优化模式被拒绝，保证断言生效。
工具 exit 0 仅表示此环境/toy 资格通过，保留 `qualified_with_method_caveats` 标签。

## 2026-10-09 tracked profile fresh 复验

上述命令新建 `env-fresh`，全部四步 exit 0（无 skipped）：create **0.118 s**，
hash-sync **43.962 s**（131 项），pip check **0.118 s**，runner smoke **11.790 s** /
child max RSS **480220 KiB**；toy 自身 **11.082 s / 469824 KiB**。真实 import、normalize、
ttest、fresh raw-count DEseq2 四项 passed；同对象 normalized DEseq2 是预期 ValueError。
两方法各 40 显著、20+/20−，ttest 199 行，DEseq2 200 行 / 199 finite，零基因语义及
BH 如上。库 source/counts/metadata hashes 与原资格记录相同；新锁 SHA256：
`68674e7d1f78c94322784a8359129d684828c998332ea3247e62dc1f09f9a359`（来源注释改变，
逐行剔除注释后与原锁依赖/hash 完全相同）。

只读 API Ruff 默认规则和显式 E/F/I（100 列）、`bash -n` 均通过；现存 prefix、
dangling symlink fail-closed、runner timeout exit 124 三个负向 probe 通过。
最初 uv guard 因 `--version` 带平台后缀而 exit 2（尚未建环境）；改为精确版本词边界
匹配后通过。Ruff 的单线程 `preexec_fn` 与顶层失败 manifest 两项规则均有局部说明，
不禁用项目规则。未运行 root/线上测试（本次写 fence 与 M3 范围之外）。

## 未覆盖与后续

没有公开参考表达数据的科学等价性、真实 counts 负载、M4 非法输入矩阵、M5 作业/持久化/
并发取消、M6 API/UI、M7 镜像/部署或 production default 决策。不可把此 smoke 当上线，
亦不可由本次成功推断通用 analyses worker 已具备 pyDEG 支持。
