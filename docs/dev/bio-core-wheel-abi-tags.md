# bio-core wheel：CPython ABI / platform tag 台账

`packages/bio-core` 是 PyO3 原生扩展，wheel 不是跨架构可移植的产物。
`infra/docker/Dockerfile.api` 的 `bio-core-builder` stage 为**当前镜像自己的架构**
编译一个 wheel；两条 image pipeline（`amd64` / `arm64`）各自产出各自的 wheel，
不交叉复用。本文档记录判据与已实测的标签，供发布时逐架构核对。

## 判据（PEP 425 / PEP 600）

wheel 文件名形如
`{distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl`，本仓库固定要求：

| 字段 | 要求 | 理由 |
| --- | --- | --- |
| `python` | `cp315` | 运行时镜像是 `python:3.15.0-slim`，crate 的 `requires-python = ">=3.15"` |
| `abi` | `cp315` | CPython 3.15 的 C ABI；`abi3` 会让扩展加载错 ABI |
| `platform` | `manylinux_<major>_<minor>_<machine>`、`manylinux2014_<machine>` 或 `linux_<machine>` | glibc 原生标签；`any` / `musllinux` / 其它平台一律拒绝 |

`python` 与 `abi` 两个字段都必须是 `cp315`，因为生产者
（`scripts/verify-bio-core.sh`）和消费者（`scripts/verify-backend-tests.sh`）
共用 `soymutdb_bio_core-*-cp315-*.whl` 这个 glob。只放宽其中一个字段会让
"生产了一次、只消费一次" 的边界两侧读到不同的轮子。

`platform` 的 machine 必须与镜像架构对应：

| 架构 | machine | 期望标签形状 | 已实测 |
| --- | --- | --- | --- |
| `amd64` | `x86_64` | `manylinux_<major>_<minor>_x86_64` | 见下 |
| `arm64` | `aarch64` | `manylinux_<major>_<minor>_aarch64` | **pending** — 本机无 arm64 构建器，不编造 glibc minor |

`manylinux_<major>_<minor>` 里的 glibc 版本来自构建镜像，不是仓库能预先声明的
常量：amd64 的实测值不能抄到 arm64 行上。没有实际构建过的架构一律标
`pending`，由该架构的 image pipeline 在构建日志里写入自己的真实标签后再补。

## 已实测记录

- `0.1.2` / `cp315-cp315-manylinux_2_34_x86_64.whl`：`verify-bio-core.sh` 在
  Rust 1.99.1 + CPython 3.15.2 上真编译、真安装、真跑算法（历史会话记录，
  不是本仓库本机的产物；本机无 Rust 工具链）。仅作格式样例，**不是** amd64
  生产镜像的当场证据。
- `arm64`：无可复现证据，pending。

## 校验

```bash
python3 scripts/check_bio_core_wheel_abi.py --ledger       # 台账 + 源码 glob 一致
python3 scripts/check_bio_core_wheel_abi.py --self-test    # 负例各自真红
python3 scripts/check_bio_core_wheel_abi.py \
  --wheel artifacts/wheels/soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl \
  --arch amd64                                            # 文件名 + WHEEL 元数据双读
```

`--wheel` 不只解析文件名：它同时读 archive 内的 `.dist-info/WHEEL`，要求
`Tag: cp315-cp315-<platform>` 真的声明过。一个被改名的 x86_64 wheel 装进
arm64 镜像，单看文件名能骗过 glob，读内部 Tag 仍会咬住。

判据挂在 `scripts/smoke.sh --profile contracts`；`--self-test` 的每一个负例
由 `scripts/test_bio_core_wheel_abi.py` 在合成树上独立复跑，删掉任一条判据
都会红。这是源码级守卫，不替代真 OCI 构建：两架构 wheel 的真实编译与镜像
smoke 仍以 CNB runner 为准，本仓库不代签。

## 供应链（cargo audit / cargo deny）

`scripts/verify-bio-core-supply-chain.sh` 在**唯一带 Rust 工具链的 bio-core
job** 里跑两个扫描器，合并成 `artifacts/bio-core/cargo-supply-chain.json`
一份结论。`dependency-governance.json` 刻意不注册第二份 `cargo-*` analyzer：
对同一份 `Cargo.lock` 出两份互相矛盾的报告，比不出报告更糟。判据由
`scripts/check_bio_core_wheel_abi.py` 按源码字节钉住，删接线即红。


两个扫描器的版本下限是**解析结论**，不是「谁更近就写谁」：

| 扫描器 | 默认 | 为什么是它 |
| --- | --- | --- |
| `cargo-audit` | `0.22.2` | `rustsec ^0.33` → `cvss ^2.2` → 2.2.0，第一个认 CVSS 4.0 向量的解析器 |
| `cargo-deny` | `0.18.9` | `rustsec ^0.31` → `cvss 2.2.0`；0.18.4 落在 `0.30.x` → cvss 2.1.0 |

两个下限由同一条判据守着：`check_bio_core_wheel_abi.py` 里
`AUDIT_FLOOR` / `DENY_FLOOR`，`test_ci_job_contracts.py` 把同一个数字再钉
一次，`test_bio_core_wheel_abi.py` 各配三条负例（低于下限、卡在红线上的
中间版本、默认值被写成 `${ENV}` 让比较失败即放行）。

**下限不是上限**：pin 的用途是「同一 commit 两次跑的 finding set 不漂移」，
只钉下限的话 `0.22.99` / `0.18.99` 也会放行，而它们是另一套解析器、另一份
结论。因此 `AUDIT_PIN` / `DENY_PIN` 把默认值钉成**精确版本**，两层守卫都改
成 `==`，并各加一条「高于下限」负例；环境变量覆盖仍允许，但提交的默认值
只能是一个固定版本。

**还有一层别漏**：`AUDIT_PIN` / `DENY_PIN` 的 `==` 比的是**脚本里声明的默认
值**，不是 runner 实装值。`cargo install --version "0.22.2"` 里的裸版本是
caret 下限（`^0.22.2`），runner 可以装到 `0.22.99`。所以安装行写成
`--version "=${AUDIT_VERSION}"`（`=` 是精确 requirement），由 source 守卫
把那个 `=` 钉住：声明值与安装契约从此是同一件事。守卫仍验不到 runner
实装结果，那一格以平台 runner 日志为准，不代签。

**再往下一层（本轮补上）**：`=` 是**安装契约**，不是**执行观测**。
`verify-bio-core-supply-chain.sh` 以前把 `cargo-supply-chain.json` 里的
`cargo_audit.version` 硬写成 `"pinned"` —— 一个声明，不是一次观测：二进制被
PATH 阴影、环境变量覆盖、或 `=` 被摘掉，签出来的报告逐字节相同，发布链把
它折进 SBOM / SHA256SUMS 时无从分辨刚才到底是哪一版扫描器判的「0 findings」。

现在安装后各跑一次 `cargo audit --version` / `cargo deny --version`（同样在
`CRATE_DIR` 内，沿用同一套 rustup channel），把输出落进 evidence；
`check_bio_core_supply_chain.py` 读回每个二进制自报的版本、与装进去的
`AUDIT_VERSION` / `DENY_VERSION` 逐字比对，**漂移 / 空输出 / 缺 evidence 一律
fail closed**，观测值写进签名报告。守卫在 `check_bio_core_wheel_abi.py`
（source 层）、`test_ci_job_contracts.py`（contracts 层）、
`test_bio_core_supply_chain.py`（行为层）三处钉这根线，5 类消融各自真红、
复原转绿；`test_scanner_rejects_a_drifted_binary_end_to_end` 用假 cargo 实跑
整条脚本，证明「声明与安装都正确、但执行的是 0.22.99」不会签出报告。

**边界照旧**：这一格关掉的是「哪一版扫描器签的字」，不是 deepseek 在支线
回执里记的那整格「`--locked` 认的 crate 自带 Cargo.lock 里 cvss / rustsec
解析结果对不对」。后者要读每版发布 lock + runner 日志，守卫读不到，仍不代签。
`cargo audit` / `cargo deny` 真跑、两架构 wheel、镜像 smoke、Playwright E2E
一律以平台为准。

下限别从 caret 推：`cargo install --locked` 认的是**发版时发布的
Cargo.lock**。`0.21.2` 死在 `unsupported CVSS version: 4.0`
（`cnb-k4a-1k6kbhl3c` L4405，那跑装的就是 `0.21.2`，不是 `0.22.1`）。
`0.22.1` 也红了（`cnb-7qb-1k6kbvp1e` exit 1），但那跑把 scan 输出重定向
进文件，stage 日志里没有失败原因；它自己的安装链解析到 `cvss 2.2.0 /
rustsec 0.32.0`（L3441/L3541），日志里的 `cvss 2.1.0 / rustsec 0.30.4`
（L4000/L4076）属于另一条 cargo-deny 0.18.4 安装链。`0.22.2` 是第一个
runner 日志里 audit 扫完且无 CVSS 报错的版本（`cnb-qf2-1k6kc4hoo`），
下限据此取。所以每次调下限要读发布的 `Cargo.lock` 与 runner 日志，不是
读 `Cargo.toml` 的 caret。

### 故障复盘：供应链 lane 的两层接线（`cnb-j3f-1k6k9lt98` → `cnb-qf2-1k6kc4hoo`）

`Rust bio-core` stage 连续几轮挂在同一个 lane 上，两层原因彼此独立：

1. **工具链是兄弟进程，不继承 PATH**。首轮报
   `bio-core supply chain: FAIL: cargo unavailable`，但同一 stage 几秒前刚用
   cargo 编译出 wheel。`verify-bio-core.sh` 把 rustup 引导到
   `${CARGO_HOME}/bin` 并在**自己的进程内** export PATH，而
   `ci-job-steps.sh` 把供应链脚本作为**兄弟进程**启动，两者都不继承。
   这一层已由本分支的 `2a4fcfcc`…`e444eaf6` 一串提交修掉并钉了守卫
   （重新声明工具链根、每条 cargo 命令 `(cd "${CRATE_DIR}" && ...)`、
   cargo-audit 抬到 0.22.2 以解析 CVSS 4.0、失败路径把证据打到 stderr）。
2. **没有 `deny.toml`，策略是空的**。这是解析器修好之后的**下一道红**：
   cargo-deny 无配置时回落到**空的 license allowlist**，把 `Cargo.lock` 里
   148 个 `[[package]]` 中带 `source` 的 147 个外部 crate 全部判成「未显式
   允许」（本地 crate `soymutdb-bio-core` 无 `source`，不进检查）；
   `--deny warnings` 又会把「7 个重复 major 版本」等
   维护告警升级成错误。（`cnb-qf2-1k6kc4hoo` 那次静默 exit 1 的真因是上一节
   的 CVSS 4.0 解析墙，由 `2649f71f` 把 cargo-deny 抬到 0.18.9 修掉；这一层
   不能记成它的死因。）本轮用一个显式、随 `Cargo.lock` 一起评审的策略收掉：

   - `packages/bio-core/deny.toml`：逐项写死 lint level。真漏洞、未知
     license、yanked、wildcard、未知 registry / git 是硬错误。
   - 重复的传递依赖**按名放行**：`multiple-versions = "deny"` + `skip` 逐条
     列出当前 `Cargo.lock` 里真实存在的 7 组（syn 1/2/3、hashbrown、
     thiserror、proc-macro2、quote、strum_macros）。删掉任一条 bans 立刻红
     （7 组逐一实测），所以下一组重复版本仍然是一次决策，而不是被
     `multiple-versions = "allow"` 顺手放过。
   - 锁内三条**无修复版本**的 unmaintained 通告按 ID 豁免：`paste@1.0.15`
     → RUSTSEC-2024-0436、`custom_derive@0.1.7` → RUSTSEC-2025-0058、
     `fxhash@0.2.1` → RUSTSEC-2025-0057。依赖链并不整齐：`custom_derive` /
     `fxhash` 是 `bio@4.2.2` 的直接子节点，`paste` 则挂在
     `simba@0.9.1 ← nalgebra@0.33.3 ← statrs ← bio` 上 —— 所以「真升级
     `bio` 栈」只对前两条成立，`paste` 会留下来。不用 scope 拼法：
     `transitive` 实测仍然报错（判据看的是「直接依赖者」，前两条挂在
     `bio`、第三条挂在 `simba`），`workspace` 又会把任何直接依赖带来的
     unmaintained 全部吞掉 —— 两个方向都是盲区。ID 列表会随通告过期：
     升级依赖后这三条变成未命中的 note 提醒删除；新出现的 unmaintained
     仍然是错误。
   - license allowlist 实测取值，其中只有单 crate 使用的走
     `[[licenses.exceptions]]` 并卡版本（`unicode-ident` → Unicode-3.0、
     `ryu@1.0.23` → BSL-1.0），避免窄场景被抬成全局允许。
   - 脚本在 crate 目录内运行，cargo-deny 自动发现同目录 `deny.toml`，不需要
     第二份 `--config` 真相源。

守卫：`check_bio_core_wheel_abi.py` 的 `source_failures()` 要求策略文件存在，
且保留显式 allowlist、`unmaintained = "all"` + 三条按 ID 的豁免、
`multiple-versions = "deny"` + 具名 `skip`、未知 registry / git 拒绝；
`test_ci_job_contracts.py` 在 contracts 层重复钉一次；
`test_bio_core_wheel_abi.py` 新增四条负例（删策略 / 写空策略 / 把
unmaintained 换成 scope 拼法 / 把 `multiple-versions` 换成 `allow`）和
一条行为回归（把假 cargo/rustc 只放进临时 `CARGO_HOME/bin`、清空系统 PATH
后实跑脚本，删掉 PATH 引导这行立刻复现 `cargo unavailable`，已做变异验证）。
合成树助手同步复制 `deny.toml`，否则每条负例都会被误判成缺策略。

3. **判定层是 fail-open 的，而且没人能测它**。前两层都在「扫描器有没有跑起来」，
   但真正签发 `cargo-supply-chain.json` 的是脚本里一段 heredoc Python。它把
   `vulnerabilities.found`（**布尔**）当成漏洞数：两条真漏洞打印
   `True vulnerability/ies`，而 `found: false` + `list` 里两条漏洞**直接放行**；
   cargo-deny 的判据是 stdout 子串，`error` 与 `warning` 同现时放行、工具
   没写任何输出时也放行；`cargo audit --json` 的非零退出被 `> file` 吃掉，
   DB 读不动和「没洞」分不开。这三种形状都能在**绿**的 contracts 套件下
   产出一份 `status: passed` 的报告。更根本的问题是 heredoc 不可 import，
   所以没有任何守卫能验证它的判据——前两层修完它仍然会假绿。

   本轮把判定收成真模块 `scripts/check_bio_core_supply_chain.py`：读
   `count`/`list` 长度（取较大者，不取 `found`）、以两个扫描器的**退出码**
   为唯一判据、空输出/畸形 JSON/缺字段一律 fail-closed，报告里带上两个退出码。
   脚本捕获 `AUDIT_RC` / `DENY_RC` 后调用它；失败路径把证据打到 stderr。
   `cargo deny check` 不加 `--deny warnings`：`deny.toml` 已逐项写死 lint
   level，那面旗会越过策略把维护告警升级成错误，形成第二份真相源。
   `scripts/test_bio_core_supply_chain.py` 用 15 条用例覆盖三种 fail-open
   形状 + CLI + 用假 cargo 实跑整条脚本；`check_bio_core_wheel_abi.py` 与
   `test_ci_job_contracts.py` 从源码字节再钉一次（含「必须传退出码」「不得
   回到 `found`/子串判据」「不得摘 smoke 接线」）。六组双向变异各自至少咬
   一层，复原后 42 passed / 95 OK。

两架构 wheel 的真编译、`cargo audit` / `cargo deny` 的真跑仍以 CNB runner
为准，本仓库不代签。
