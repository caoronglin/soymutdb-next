# OPT-07 / OPT-08 / OPT-09：双站制品守卫补洞（子代理 D）

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../../ARCHIVE.md)。

- 日期：2026-09-26
- 来源：`docs/dev/ablation/2026-09-26/artifact-e2e.md` §4 的 INERT-1（I3）、INERT-3（I5）、INERT-2（I4）
- 判定口径：red-before = 旧代码路径在消融下 `exit 0`；green-after = 新代码在同样消融下 `exit 1`，对照 `exit 0`
- 证据等级：E1（真实运行，命令 + 退出码 + 关键输出）
- 未提交；未触碰 `apps/`、`e2e/`

## 1. 目标

1. **OPT-07（I3）**：external 制品必须和 internal 一样有顶层 HTML 入口；删掉 `external/index.html` 必须失败（exit 1，明确 FAIL 行）。
2. **OPT-08（I5）**：`verify-site-variant-artifacts.sh` 必须用多哨兵扫描（至少含内网站点 origin / token），默认哨兵集合提升为命名常量，扫描脚本与 verifier 共用同一份列表；`--sentinel` 仍可重复，单个 sentinel 仍向后兼容。
3. **OPT-09（I4）**：目录名里的哨兵也要检查（含空目录），报告相对路径；同一目录内文件已经命中时不再为目录重复报一条。

## 2. 改动

### `scripts/check_site_artifact_isolation.py`

| 位置 | 改动 |
| --- | --- |
| `:24-27` | 新增模块常量 `DEFAULT_SENTINELS`（`noindex, nofollow, noarchive`、`internal.soymutdb.invalid`），文档字符串 `:7-9` 说明无 `--sentinel` 时的默认与 `--print-default-sentinels`。 |
| `:42-46` | 新增 `--print-default-sentinels`：逐行打印共享默认哨兵集合，供 bash 消费。 |
| `:81-97` | 新增 `missing_html_entry()`：external 根下无顶层 `*.html`（非 symlink）时返回诊断串。 |
| `:100-187` | `scan_external()` 重构：遍历时收集 `directory_paths` 与 `file_path_hits`；遍历结束后对目录名做哨兵检查，若同目录内已有同哨兵的文件路径命中则不重复报告（`:167-181`）。 |
| `:190-206` | `self_test()` 增加默认集合非空断言与空目录哨兵断言。 |
| `:242-243` | 无 `--sentinel` 时回退到 `DEFAULT_SENTINELS`；显式单个/多个 sentinel 仍只扫描给定值（向后兼容）。 |
| `:250-259` | 入口缺失走 exit 1，并打印 `FAIL: external artifact is missing a top-level HTML entry (external/index.html)`，同时附上已有哨兵 findings。 |

退出码约定未变：0 正常 / 1 校验失败 / 2 配置非法。

### `scripts/verify-site-variant-artifacts.sh`

| 位置 | 改动 |
| --- | --- |
| `:75-87` | 用 `mapfile` 从 `python3 scripts/check_site_artifact_isolation.py --print-default-sentinels` 取共享默认哨兵，再追加本次部署实际使用的 `INTERNAL_SITE_URL`，逐个以 `--sentinel` 传入。 |
| `:38` | `NOINDEX_MARKER` 保留（供 internal `grep` 使用），注释说明哨兵列表归属 Python 侧单一来源。 |

external 入口由 checker 的 `missing_html_entry` 强制；internal 入口仍由原 `grep -Rq ... internal/*.html` 强制，两侧对称。

### `scripts/test_site_artifact_isolation.py`

| 位置 | 用例 | 覆盖 |
| --- | --- | --- |
| `:28` | `setUp` 预置 `external/index.html` | 保证既有用例在入口强制后仍绿 |
| `:124-142` | `test_missing_external_entry_html_fails_closed` | OPT-07：删入口 + 仅有嵌套 html → exit 1 FAIL；恢复 → exit 0 |
| `:143-146` | `test_missing_html_entry_helper` | OPT-07 单元级 |
| `:147-170` | `test_default_sentinel_set_is_shared_and_covers_internal_origin` | OPT-08：常量内容、`--print-default-sentinels` 输出、单 sentinel 向后兼容、缺省回退默认集合 |
| `:171-179` | `test_sentinel_in_empty_directory_name_is_reported` | OPT-09：空目录名命中 → exit 1，`directory path` + 脱敏 |
| `:181-190` | `test_directory_hit_not_duplicated_for_file_inside` | OPT-09：目录内有文件时只报一条（不重复） |

用例数 6 → 11。

## 3. red → green 证据（E1）

### 3.1 旧代码 red-before（`git show HEAD:scripts/check_site_artifact_isolation.py`，未改动工作树）

```bash
S=.validation/ablation/opt-d/dist
# 消融 I3：删 external/index.html
python3 .validation/ablation/opt-d/oldcode/old_checker.py --external-root $S/external \
  --internal-root $S/internal --sentinel 'noindex, nofollow, noarchive' \
  --sentinel 'internal.soymutdb.invalid'
# → OK: external artifact contains no supplied protected values
# → OLD_I3_EXIT=0   （缺口存在）

# 消融 I4：同哨兵名的空目录
python3 .validation/ablation/opt-d/oldcode/old_checker.py ... 
# → OK ...  / OLD_I4_EXIT=0

# 消融 I5：external/index.html 注入 internal.soymutdb.invalid，用旧 verifier 的唯一哨兵
python3 ... --sentinel 'noindex, nofollow, noarchive'
# → OK ...  I5_SINGLE_EXIT=0   （放行）
```

### 3.2 新代码 green-after

```bash
$ python3 -m unittest scripts.test_site_artifact_isolation -v
Ran 11 tests in 0.803s
OK
CMD1_EXIT=0

$ python3 scripts/check_site_artifact_isolation.py \
    --external-root apps/web/dist/external --internal-root apps/web/dist/internal \
    --sentinel 'noindex, nofollow, noarchive' --sentinel 'internal.soymutdb.invalid'
OK: external artifact contains no supplied protected values
CMD2_EXIT=0

# 消融 I3（scratch 复制制品后删 external/index.html）
python3 scripts/check_site_artifact_isolation.py --external-root $S/external \
  --internal-root $S/internal --sentinel 'noindex, nofollow, noarchive' \
  --sentinel 'internal.soymutdb.invalid'
# stderr: FAIL: external artifact is missing a top-level HTML entry (external/index.html)
CMD3_EXIT=1

# 消融 I4（空目录 empty-noindex, nofollow, noarchive/）
# stderr: FAIL: ... sentinel #1 found in directory path: empty-<sentinel-1>
I4_EMPTYDIR_EXIT=1

# 消融 I5（注入 internal.soymutdb.invalid）
# 旧唯一哨兵: I5_SINGLE_EXIT=0；新默认集合（不带 --sentinel）: I5_DEFAULT_EXIT=1
#   stderr: sentinel #2 found: index.html

$ SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh
[site-variants] portal dual-site artifacts are built and isolated
VERIFIER_EXIT=0
```

### 3.3 其他门禁

```bash
$ bash scripts/smoke.sh --profile contracts
246 passed in 17.35s
SMOKE PASS
SMOKE_EXIT=0

$ python3 -m ruff check scripts/check_site_artifact_isolation.py scripts/test_site_artifact_isolation.py
All checks passed!
$ python3 -m ruff format --check ...   # 已应用 ruff format
$ bash -n scripts/verify-site-variant-artifacts.sh
BASH_N_EXIT=0
```

## 4. 未验证

- verifier 的**完整构建路径**（`SOYMUTDB_SITE_VARIANTS_PREBUILT=0` 触发 `pnpm build:sites`）未重跑；本次用 `PREBUILT=1` 走通完整校验段（grep + 多哨兵扫描）。`apps/web/dist/{external,internal}` 为既有构建产物。
- 未做真实“内网 origin 泄漏进 external”的 dist 级消融（只在 scratch 副本上做了字符串注入）。
- `shellcheck` 未安装（未跑）；只做了 `bash -n`。
- verifier 的 internal `grep` 路径未改为与 external 完全同构的 Python 实现——仍是对称的两侧强制，但实现手段不同。

## 5. 回滚点

- 仅 3 个文件，均为工作树未提交改动：`git diff` 可查看，`git status --short` 确认只涉及
  `scripts/check_site_artifact_isolation.py`、`scripts/test_site_artifact_isolation.py`、
  `scripts/verify-site-variant-artifacts.sh`。
- 回滚 = 对上述 3 个文件恢复 HEAD 版本（不 `git checkout`/`reset` 其它文件）。
- scratch 证据目录 `.validation/ablation/opt-d/`（`dist/`、`oldcode/`）可整体删除。
