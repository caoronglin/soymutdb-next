# Rust bio-core wheel：构建、安装与门禁

## 为什么必须走 wheel

`packages/bio-core` 是 PyO3 私有编译扩展，不是纯 Python 包。API 与 Worker 通过
`import soymutdb_bio_core` 调用它；**源码目录不能替代 wheel**。生产容器启动时
不得下载 Rust 工具链现场编译（规格 §9.2）。

## 本地 / CI 构建

```bash
export CARGO_HOME=${TMPDIR:-/tmp}/soymutdb-cargo
export RUSTUP_HOME=${TMPDIR:-/tmp}/soymutdb-rustup
bash scripts/verify-bio-core.sh        # 完整门禁，一条命令
```

`verify-bio-core.sh` 依次执行：

1. `cargo metadata --locked`（锁文件一致性）
2. `cargo fmt --all -- --check`
3. `cargo clippy --all-targets --all-features --locked -- -D warnings`
4. `cargo test --all-targets --locked`（unit + golden + adversarial）
5. `maturin build --release --locked --interpreter <py3.15> --out artifacts/wheels`
6. **安装第 5 步产出的那个 wheel** 到隔离目录
7. import smoke + 真实科学函数断言
8. `pytest packages/bio-core/python_tests -q`

缺 cargo / cc / maturin 一律直接失败，不 SKIP 冒充 PASS。编译器版本由
`packages/bio-core/rust-toolchain.toml` 单独 pin（`1.99.1`），脚本里没有第二份。

产物：`soymutdb_bio_core-0.1.2-cp315-cp315-manylinux_2_34_x86_64.whl`。
`artifacts/` 在 `.gitignore` 内，wheel 不进仓库；`Cargo.lock` 必须提交。

## CI 里的两处安装

- **Rust 门禁**：`scripts/ci-job-steps.sh run bio-core` → `verify-bio-core.sh`。
  CNB 与 GitHub 都只写这一行委托。
- **后端门禁**：`scripts/verify-backend-tests.sh` 在 API pytest 之前把同一个
  wheel 装进 `apps/api/.venv`，再跑 `packages/bio-core/python_tests`。这样
  `test_sequence_tools.py` / `test_interval_overlap.py` 跑的是发布制品，不是
  `PYTHONPATH` 里的源码替身。

## 冒烟

```bash
python3 scripts/check_bio_core_wheel.py --static    # 任何 Python 3，查 pin/锁/CI/门禁
python3 scripts/check_bio_core_wheel.py --runtime   # 需已装 wheel，跑真实算法
bash scripts/smoke.sh --profile contracts           # 含 --static
bash scripts/smoke.sh --profile runtime             # 含 --runtime（需 PG + API venv）
```

`--runtime` 在 wheel 缺失时**返回 1**，与「sequence tools 失败关闭为 503」一致；
一个没装引擎的部署不能靠 skipped 冒烟绿灯混过去。

## 灰度

`SOYMUTDB_BIO_ENGINE=rust|python`，默认 `rust`。仓库目前**没有**经过差分验证的
等价 Python 实现，所以 `python` 一律 `503 service_unavailable`，绝不静默返回
空结果或伪造 engine 版本。要开启 Python 回退，必须先补一份与 wheel 逐项对拍的
差分套件，再改 `bio_core_bridge.status()`。

## 还没做（需要独立 PR）

- 把 wheel 装进 `infra/docker/Dockerfile.api` / `Dockerfile.worker` 运行时镜像：
  需新增 Rust builder stage、按 SHA-256 校验安装、覆盖 amd64/arm64 的 native
  wheel，并在 `scripts/build-release-image.sh` 的镜像 runtime smoke 里加
  `import soymutdb_bio_core` + 真实算法断言。
- `cargo audit` / `cargo deny` 接入现有 Trivy / SBOM 链，不生成第二份互相矛盾的
  扫描报告。
- 多架构 wheel 的 CPython ABI / platform tag 证据。

在这条链合完之前，不要写「wheel 已进生产镜像」。
