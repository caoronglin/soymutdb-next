# bio-core wheel 的 ABI / platform tag 证据

## 为什么需要

生产端与 CI 用 `soymutdb_bio_core-*-cp315-*.whl` 这个 glob 找 wheel，再
`import` 一下就算过。但 glob 和 import 都证明不了三件事：

- wheel 真的是 **CPython 3.15 的 cp315 ABI**，不是 `abi3` / `none`；
- 它带的是**本机架构的 native tag**，不是 `py3-none-any` 的纯 Python 壳；
- amd64 与 arm64 两条镜像流水线产出的 wheel **版本与 ABI 一致**。

`abi3` 与 `none` wheel 在 3.15 上都能装、都能 import，却改变了发布镜像
被验证时依赖的 ABI 契约。`check_bio_core_wheel.py --runtime` 跑真实算法能
抓住「装错了包」，抓不住「同一份源码被打成了另一种 ABI」。

## 守卫

`scripts/check_bio_core_wheel_tags.py` 按 PEP 427 解析 wheel 文件名：

| 判据 | 要求 |
| --- | --- |
| distribution | `soymutdb_bio_core` |
| python tag | `cp315` |
| abi tag | `cp315`（拒 `abi3` / `none`） |
| platform tag | 非 `any`，且以本机架构后缀结尾（`x86_64` / `aarch64`） |
| 产物数量 | 目录里恰好一个 `.whl`，缺或歧义都 EXIT 1 |

三种入口：

```bash
python3 scripts/check_bio_core_wheel_tags.py --self-test
python3 scripts/check_bio_core_wheel_tags.py --wheel-dir artifacts/wheels --arch auto --out artifacts/wheels
python3 scripts/check_bio_core_wheel_tags.py --verify-ledger <dir>
```

`--arch auto` 用 `platform.machine()` 映射到发布流水线的 `amd64` / `arm64`
词汇。`--out` 写 `wheel-tags-<arch>.json`：文件名、版本、三个 tag、架构、
wheel 的 SHA-256。`--verify-ledger` 要求两个架构的 ledger 都在、ABI/版本
一致、platform tag 各自 native 且互不相同。

## 接线

- `scripts/verify-bio-core.sh`（唯一的 wheel 生产者）在 `maturin build`
  之后、import smoke 之前调用一次，把本次构建的 tag 与 digest 落成 ledger。
  它跑在 `bio-core` stage 上，一个流水线一个架构。
- `scripts/test_bio_core_wheel_tags.py` 是消融套件，登记进
  `scripts/smoke.sh --profile contracts`：合成树喂真 checker，
  `py3-none-any` / `abi3` / `none` / 错架构 / 缺轮 / 双轮 / 错发行名
  逐条转红；ledger 缺一架构、两架构同 tag、ABI 不一致也转红。另有一条
  读字节的接线断言，防止守卫或登记被悄悄摘掉。

## 边界：这是第一刀，不是全链

这一刀覆盖**生产者侧的 tag 与 digest 证据**和契约层的回归。两条
`docker-images` 流水线各自在 `infra/docker/Dockerfile.api` 的
`bio-core-builder` stage 里按本机架构重写 wheel（`docs/ops/bio-core-wheel.md`
的 R5，PR #118 负责），那一半的 per-arch ledger 落盘与
`scripts/release-contract.golden.sh` 的 `--verify-ledger` 汇总**仍未接线**——
#118 还在 open，按「一个 phase 一个 PR、不双写同一批字节」留给它的后续
phase。在此之前不要写「多架构 ABI 证据已闭环」。

本机无法跑的部分（CPython 3.15 + 真 wheel + 两架构 Docker）一律以 PR
的 CI `verify` 为准；`--self-test` 与消融套件是纯 stdlib，不依赖这些前置。
