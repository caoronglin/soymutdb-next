# Python 3.15 isolated validation — evidence page (C1 + C2 + C3)

> **2026-10-16 最新状态**：本文后续章节保留历史过程。当前 API Python 3.15 全套 2326 passed（3 历史驱动专用跳过），MCP 66 passed，Worker 原生默认全套 657 passed、零跳过，完整科学计算能力检查通过。历史 chdb 引擎测试另在 Python 3.14 迁移通道执行。镜像/生产切换未实测。以 [最新全栈验收](fullstack-validation-20261015.md) 为准。

- Date: 2026-10-10 (C1/C2); C3 appended 2026-10-11
- Owner: the C1/C2 implementation slice of `docs/aegis/plans/2026-10-10-antv-analytics-python315.md`
  (C3: the bounded worker-dependency probe slice)
- Status: **C1 done, C2 partially done, C3 blocked at binary-only install (deterministic
  evidence, not a source-build verdict)**
- Write scope of this slice: `.mamba-root/envs/py315/**`, `.mamba-root/pkgs/**`, this page,
  and the plan/design/checkpoint records. **No production pin file was touched and no
  Git lifecycle operation was performed.**

This page records evidence, not a decision to migrate. The overall objective remains the
core migration *after* sufficient evidence exists; "this slice changed no pin" is a property
of the current phase, not the permanent end state of the work.

## 0. Baseline re-checked this session (read-only)

| Field | Value |
| --- | --- |
| branch | `chore/node-26-pin-20261010` |
| HEAD | `166f76bda6ed347af86c658d374c3525995c6a11` |
| dirty entries | 21 (13 tracked/staged + 8 untracked) |
| drift vs the planning `TaskStartSnapshot` | the 11 modified + 2 staged-renamed tracked paths are **byte-identical in set** to the snapshot; the 3 extra untracked entries are this workstream's own `docs/` files. **No new dirty path in `packages/jobs-py`, `apps/api` or `apps/mcp-server`.** |

The 18 paths inherited from the snapshot (including `apps/web/src/react-app.tsx`,
`apps/admin/src/components/admin-shell.tsx`, `packages/i18n-core/src/locales/{en,zh}/common.json`)
were **not** touched.

## 1. Environment shape

| Item | Value |
| --- | --- |
| mamba | 2.5.0 (`/mnt/data02/T25ronglin/.miniforge3/condabin/mamba`) |
| uv | 0.12.21 |
| env prefix | `.mamba-root/envs/py315` |
| pkg cache | `.mamba-root/pkgs` |
| channel | `conda-forge` only (`--override-channels`) |
| version control | `.gitignore:215` ignores `.mamba-root/`; verified with `git check-ignore -v` for the prefix and the pkgs dir, so **no mamba artifact can enter version management** |
| pre-existing assets in the prefix | none — `.mamba-root/envs/` contained only `postgres16` before this slice. **No old env was deleted or overwritten** |

### Solver evidence for the build choice (dry run first, not a filename guess)

```
mamba create -p $PWD/.mamba-root/envs/py315 --override-channels -c conda-forge "python=3.15" --dry-run -y
  + python  3.15.0  h6e52b48_100_cp315  conda-forge
---DRYRUN_EXIT:0
```

The solver resolved build string **`h6e52b48_100_cp315`** (`_cp315`, i.e. the regular
CPython ABI). The create was then pinned to that exact build:

```
mamba create -p $PWD/.mamba-root/envs/py315 --override-channels -c conda-forge \
  "python=3.15.0=h6e52b48_100_cp315" -y
---CREATE_EXIT:0
```

## 2. C1 — interpreter facts (verified, exit 0)

```
.mamba-root/envs/py315/bin/python -V
Python 3.15.0
```

| Probe | Value |
| --- | --- |
| `sys.executable` | `/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/bin/python` |
| `sys.version` | `3.15.0 | packaged by conda-forge | (main, Oct 9 2026, 18:56:31) [GCC 15.3.0]` |
| `sysconfig SOABI` | `cpython-315-x86_64-linux-gnu` |
| `sysconfig Py_GIL_DISABLED` | `0` |
| `sys.abiflags` | `''` (empty → **not** a free-threaded build; `cp315t` was not selected) |
| `sys.flags.utf8_mode` | `1` (PEP 686 — UTF-8 default) |
| `sys.flags.warn_default_encoding` | `0` |
| `sys.getfilesystemencoding()` | `utf-8` |
| `-X utf8` / `-X warn_default_encoding` | both accepted, exit 0 |

Official source: <https://www.python.org/downloads/release/python-3150/> returned HTTP 200
and states **release date Oct. 9, 2026**, with PEP 686 (UTF-8 default), PEP 810 (explicit
lazy imports), PEP 661 (`sentinel`), PEP 814 (`frozendict`), the experimental JIT and
PEP 799 (profiling package) among the headline features. Every one of those claims that
this page relies on was re-confirmed locally (UTF-8 mode, `sentinel`, `frozendict`).

`https://docs.python.org/3/whatsnew/3.15.html` could **not** be retrieved through the
Jina reader route inside the 30 s network budget (`curl` exit 124, timeout, no bytes
written). Recorded as a **failed fetch**, not as a read. The removed-API claims below
are therefore taken from the interpreter itself, which is stronger evidence for this
environment anyway.

## 3. Compatibility probes the user added to the checklist

Run directly on the 3.15 interpreter (`importlib.util.find_spec`):

| Module | Result |
| --- | --- |
| `sre_parse`, `sre_compile`, `sre_constants` | **ABSENT** |
| `cgi`, `cgitb` | **ABSENT** |
| `telnetlib`, `nntplib`, `pipes`, `crypt`, `imghdr`, `aifc`, `audioop`, `chunk` | **ABSENT** |
| `msilib`, `nis`, `ossaudiodev`, `spwd`, `sndhdr`, `sunau`, `uu`, `xdrlib`, `lib2to3` | **ABSENT** |
| `sqlite3` | **present** |

`sqlite3` legacy attributes: `sqlite3.version` → **False**, `sqlite3.version_info` →
**False**, `sqlite3.enable_shared_cache` → **False**. The module still imports, but the
old version/shared-cache attributes are gone.

Repo impact of those absences: `grep -rE "import (cgi|sre_parse|telnetlib)|from (cgi|sre_parse)"`
over `apps/*/app`, `apps/*/src`, `packages/*/src` returned **no hits** — the removed
stdlib surface is not used by the product code that this slice installed. (Not a proof for
the worker tier; that is C3.)

New-feature state on this interpreter, deliberately **not enabled**:

| Feature | Observed | Policy |
| --- | --- | --- |
| PEP 810 lazy imports | `PYTHON_LAZY_IMPORTS` unset → off by default | **not enabled globally**; see below |
| PEP 661 `sentinel` | `builtins.sentinel` exists (`<class 'sentinel'>`) | second-phase candidate only |
| PEP 814 `frozendict` | `builtins.frozendict({'a':1})` works | second-phase candidate only |
| experimental JIT | not probed (no LLVM installed, and none will be installed here) | out of scope |
| PEP 799 profiling / Tachyon | not probed | out of scope |

**Native lazy imports stay a phase-2 candidate.** They are not merged into the
compatibility work, and the already-approved *frontend* native React lazy/Suspense scope is
unaffected by this decision — the two are different layers and neither one changes the other.

## 4. C2 — install evidence

Toolchain split, as designed: **mamba supplies the interpreter, uv/pip supplies the Python
packages.** No project dependency was installed through conda.

Deviation from the plan's one-line `uv pip install --python …` wording, and why:

- `uv sync --locked` was preferred because it consumes the committed `uv.lock` without
  rewriting it. `--locked` fails loudly instead of re-resolving, so **no lock file was
  modified** (verified: no new dirty path under `apps/api` or `apps/mcp-server`).
- **Three separate virtual environments were used, one per project**, instead of one shared
  env: `uv sync` prunes anything not in the project's lock, so syncing api then mcp-server
  into one env would have deleted the previous project's dependencies and produced a fake
  "all good" result. The isolation lives at
  `.mamba-root/envs/py315/venvs/{jobs-py,api,mcp-server}`, inside the approved write scope
  and inside the already-ignored `.mamba-root/`.
- `UV_PROJECT_ENVIRONMENT` was set explicitly on every uv invocation, and `--python` was
  pinned to the mamba interpreter. **No `uv sync` ever resolved to an existing
  `apps/*/.venv`**, `webdb` or any running service environment. `mamba env list` is unchanged
  (10 envs, none created or removed by this slice).
- `pytest` is **not** in any lock extra for `apps/mcp-server`, so it was added with a plain
  `uv pip install pytest` into the scratch venv only. That is a local test-runner
  convenience, not a project dependency claim.
- **No lock validation is claimed beyond "sync with `--locked` succeeded"**; the pytest
  runs below are the real evidence, and they are not green everywhere.

### Exact commands and exit codes

| # | Command | Exit |
| --- | --- | --- |
| 1 | `mamba create -p .mamba-root/envs/py315 --override-channels -c conda-forge "python=3.15" --dry-run -y` | 0 |
| 2 | `mamba create -p .mamba-root/envs/py315 --override-channels -c conda-forge "python=3.15.0=h6e52b48_100_cp315" -y` | 0 |
| 3 | `uv venv --python .mamba-root/envs/py315/bin/python .mamba-root/envs/py315/venvs/jobs-py` | 0 |
| 4 | `uv pip install --python .mamba-root/envs/py315/venvs/jobs-py/bin/python ./packages/jobs-py "pytest>=8.0.0"` | 0 |
| 5 | `UV_PROJECT_ENVIRONMENT=$PWD/.mamba-root/envs/py315/venvs/api uv sync --locked --project apps/api --python .mamba-root/envs/py315/bin/python` | **1** (first attempt) / **0** (second attempt) |
| 6 | `UV_PROJECT_ENVIRONMENT=$PWD/.mamba-root/envs/py315/venvs/api uv sync --locked --extra dev --project apps/api --python .mamba-root/envs/py315/bin/python` | 0 |
| 7 | `UV_PROJECT_ENVIRONMENT=$PWD/.mamba-root/envs/py315/venvs/mcp-server uv sync --locked --project apps/mcp-server --python .mamba-root/envs/py315/bin/python` | 0 |
| 8 | `… uv sync --locked --extra test --project apps/mcp-server --python .mamba-root/envs/py315/bin/python` | 0 |
| 9 | `uv pip install --python .mamba-root/envs/py315/venvs/mcp-server/bin/python "pytest>=8.0.0"` | 0 |

### The one real install failure, in full

`apps/api` sync attempt #1 exited 1. Minimal verbatim failure:

```
Running `maturin pep517 build-wheel -i .../builds-v0/.tmpisdW5e/bin/python --compatibility off`
[stderr]
Python reports SOABI: cpython-315-x86_64-linux-gnu
Installing rust to /mnt/data02/T25ronglin/.cache/puccinialin/rustup
warn: it looks like you have an existing rustup settings file at: …
💥 maturin failed
  Caused by: Cargo metadata failed. Does your crate compile with `cargo build`?
  Caused by: failed to start `cargo metadata`: Text file busy (os error 26)
hint: `orjson` (v3.11.9) was included because `soymutdb-api` (v2.0.0) depends on `orjson`
```

Two facts, both worth keeping:

1. **The trigger is a real 3.15 packaging gap, not flakiness.**
   `apps/api/uv.lock:1304-1316` shows `orjson 3.11.9` publishing **only `cp314` wheels**
   (macosx, manylinux, musllinux) plus an sdist. There is no `cp315` and no `abi3` wheel,
   so on 3.15 uv must **build orjson from source with Rust/maturin**. A production image on
   3.15 would therefore need a Rust toolchain in the build stage, or a bumped `orjson`.
2. The `Text file busy (os error 26)` part was environmental: the first run was still
   downloading and writing the rustup toolchain under
   `/mnt/data02/T25ronglin/.cache/puccinialin` when cargo was executed. Once the toolchain
   was materialised, **the identical command succeeded (exit 0)**. No fix was applied to
   any project file, and the second run was a retry of a *changed environment*, not a
   blind repeat of the same failure.

## 5. Test results (real runs, not collect-only)

All runs used `-p no:cacheprovider` and the project interpreter from the isolated env.

| Project | Command | Result |
| --- | --- | --- |
| `packages/jobs-py` | `python -m pytest tests -q` | **95 passed**, 0 failed — exit 0 |
| `packages/jobs-py` | `python -X warn_default_encoding -W default::DeprecationWarning -W default::PendingDeprecationWarning -m pytest tests -q` | **95 passed**, 0 failed — exit 0, **no warnings emitted** |
| `apps/mcp-server` | `PYTHONPATH=src python -m pytest tests -q` | **collection error**, exit 2 — see below |
| `apps/mcp-server` | `… -m pytest tests -q --ignore=tests/test_tools.py` | **6 failed, 28 passed, 3 errors** (6 warnings) — exit 1 |
| `apps/api` | `python -X warn_default_encoding -m pytest tests/test_health_unit.py tests/test_public_id_service.py tests/test_analytics_privacy.py -q` | **6 passed, 5 errors**, 1 warning — exit 1 |

### `apps/mcp-server` failures — root cause

```
ImportError: FastMCP server support is not installed. Install `fastmcp` or `fastmcp-slim[server]`.
  from fastmcp.server.context import Context
  src/mcp_server/server.py:47: from fastmcp import Context, FastMCP
```

`apps/mcp-server/uv.lock:394-399` resolves `fastmcp 3.4.7` → `fastmcp-slim[client, server]`.
The error is raised from inside the **installed 3.15 environment**, and the failing import
is the project's own `src/mcp_server/server.py:47`. This is recorded as a **lock /
dependency-set gap in fastmcp 3.4.7 under this sync shape**, i.e. a dependency-problem to
investigate, *not* a claim that fastmcp is 3.15-incompatible and *not* a claim that the
project is broken on 3.14. All 6 failures and all 3 errors share this single import cause
(`test_server_module_imports`, `test_entrypoint_parses_args`, tool-registry,
bearer-auth and transport-auth cases). The 28 passing tests are the ones that do not import
`fastmcp`.

### `apps/api` errors — environment ceiling, not a 3.15 failure

```
ERROR at setup of test_ensure_public_id_never_reassigns_issued_value
E   FileNotFoundError: [Errno 2] No such file or directory
E   urllib3.exceptions.ProtocolError: ('Connection aborted.', FileNotFoundError(2, …))
```

That is **testcontainers reaching for a Docker socket that does not exist on this host**
(`.ai-memory/LOCAL-RUN-ENV.md` §8). Those 5 cases are **NOT COVERED** — they are neither
passes nor 3.15 failures. `SOYMUTDB_TEST_DATABASE_URL` against the documented
`postgres16` pattern was not used in this slice (budget; it is the C2 remainder below).

### Encoding / deprecation honesty

- Both test runs above were repeated with `-X warn_default_encoding` and
  `-W default::DeprecationWarning -W default::PendingDeprecationWarning`. jobs-py emitted
  **zero** warnings; mcp-server emitted **6** warnings and api **1** (a pydantic
  `UserWarning` about development defaults).
- **`apps/api/pyproject.toml` sets `filterwarnings = ["ignore::DeprecationWarning",
  "ignore::PendingDeprecationWarning"]`.** A clean api pytest run therefore proves nothing
  about deprecations. That silencing is **pre-existing** and was left alone: mechanically
  "fixing" third-party deprecations is not this slice's job, and a silenced run must never
  be reported as a pass. Any future api 3.15 run must override it explicitly before its
  warning count can be believed.
- No new encoding regression test was written in this slice; if one proves necessary it
  belongs to a later slice, as scoped.

## 6. Side effects recorded in full

1. `.mamba-root/envs/py315/` — new mamba env (22 packages, 45 MB download) + `pip 26.2.1`.
2. `.mamba-root/envs/py315/venvs/{jobs-py,api,mcp-server}` — three uv virtualenvs
   (`api` also holds the `dev` extra; `mcp-server` also holds the `test` extra plus a
   locally added `pytest 9.1.1`).
3. `.mamba-root/pkgs/` — conda package cache gained the 3.15 downloads.
4. `/mnt/data02/T25ronglin/.cache/puccinialin/` — uv's Rust toolchain for the orjson build
   (outside the repo, shared uv cache).
5. `/mnt/data02/T25ronglin/.cache/uv/` — shared uv cache.
6. A transient `rustup` settings/toolchain update under `~/.cache/puccinialin`.
7. Nothing else. No service started, no port bound, no throwaway server written, no
   SQLite substitute used anywhere.

## 7. Not covered / failed / next

| Item | State |
| --- | --- |
| C1 interpreter | **done, verified** |
| C2 jobs-py | **done: 95/95 pass on 3.15** |
| C2 api install | **done with evidence**: requires an orjson Rust source build; lock untouched |
| C2 api tests | **partial**: 6 passed, 5 errors are Docker-fixture not-covered |
| C2 api PostgreSQL-backed layers | **not covered** — next: `SOYMUTDB_TEST_DATABASE_URL` against `.mamba-root/envs/postgres16` on port 55432 |
| C2 mcp-server | **blocked on a dependency-set question** (fastmcp 3.4.7 `fastmcp-slim[server]`), 28 pass / 6 fail / 3 error, root cause identified |
| C2 permission + security-matrix tests | **not run** — needs the PostgreSQL layer above; nothing was run against production |
| C3 worker / biology | **not started** |
| Native lazy imports, `sentinel`, `frozendict`, JIT, profiling | **deliberately not enabled**; phase-2 candidates, official sources checked first |

**No production pin moved.** `requires-python`, `ruff target-version`, every `uv.lock`,
`.cnb.yml`, `.cnb/env/Dockerfile.frontend`, `infra/docker/Dockerfile.*`,
`apps/mcp-server/Dockerfile`, `scripts/ci-job-steps.sh` and
`scripts/test_ci_job_contracts.py` are untouched. Python 3.14 remains the production and CI
interpreter; the point of this page is evidence for a *later, separately approved*
migration, not its conclusion.

---

# C3 — worker / biology tier (appended 2026-10-11)

Bounded scope: worker dependency install + import check only. **No pin migration, no product
code change, no service start, no database touched, no git lifecycle operation.** TDD off;
proportionate probing only.

## C3.0 Interpreter re-verified (not taken on the C1 receipt)

| Probe | Value |
| --- | --- |
| `python -V` | `Python 3.15.0` |
| `sys.executable` | `/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/bin/python` |
| `sysconfig SOABI` | `cpython-315-x86_64-linux-gnu` |
| `Py_GIL_DISABLED` | `0` |
| `sys.abiflags` | `''` → **regular CPython 3.15, not a free-threaded `cp315t` build** |
| `warn_default_encoding` | `0` (so the pytest runs must set `-X warn_default_encoding` explicitly) |

Exit 0 for all of the above. Read-only `git status --porcelain` was taken before any write;
the dirty set was **byte-identical before and after** this slice (37 entries), i.e. this slice
introduced **zero** new dirty paths.

## C3.1 Locked version candidates — confirmed by reading `apps/worker/uv.lock`

Every candidate in the request was verified against the lock, not assumed:

| Package | Requested candidate | Actual locked version | Match |
| --- | --- | --- | --- |
| `cyvcf2` | 0.34 | **0.34.0** | yes |
| `polars` / `polars-runtime-32` | 1.43.2 | **1.43.2** | yes |
| `python-igraph` | 0.11.9 | **0.11.9** | yes |
| `leidenalg` | 0.10.2 | **0.10.2** | yes |

Also read from the lock: `numpy 2.5.2`, `scipy 1.18.0`, `pandas 2.3.3`, `pyarrow 25.0.1`,
`pysam 0.24.0`, `scanpy 1.12.3`, `anndata 0.12.19`, `pyfaidx 0.9.0.4`, `chdb 4.4.0`,
`clickhouse-connect 1.7.0`, `pydantic-core 2.46.4`.

## C3.2 The `--no-build` diagnostic — real command, real failure

`--no-build` was **verified in the existing uv's help text before use**, not guessed:

```
$ uv --version
uv 0.12.21 (x86_64-unknown-linux-gnu)

$ uv sync --help | grep -- --no-build
--no-build
    Don't build source distributions [env: UV_NO_BUILD=]
```

Command actually run (isolated target, mamba interpreter, `UV_PROJECT_ENVIRONMENT` explicit):

```
cd /mnt/data02/T25ronglin/code/web
UV_THREADPOOL_SIZE=2 \
UV_PROJECT_ENVIRONMENT="$PWD/.mamba-root/envs/py315/venvs/worker" \
timeout 115 uv sync --locked --no-build --extra dev \
  --project "$PWD/apps/worker" \
  --python "$PWD/.mamba-root/envs/py315/bin/python"
```

Output, verbatim:

```
Using CPython 3.15.0 interpreter at: .mamba-root/envs/py315/bin/python
Creating virtual environment at: .mamba-root/envs/py315/venvs/worker
Resolved 113 packages in 34ms
error: Distribution `clickhouse-connect==1.7.0 @ registry+https://pypi.org/simple`
       can't be installed because it is marked as `--no-build` but has no binary distribution
```

| Item | Value |
| --- | --- |
| uv exit code | **2** |
| re-resolution? | **no** — `Resolved 113 packages in 34ms`, `--locked` honoured, no `uv lock` run |
| packages installed | **0** — it aborted at the first source-only distribution |
| `apps/worker/.venv` | **untouched** (`mtime` Oct 10 17:03 identical before and after) |
| target venv | created but **empty** (no `site-packages` content) |

## C3.3 Why: offline wheel-tag classification of all 113 locked packages

uv stops at the first offender, so the **complete** gap was computed offline from the lock's
own `wheels = [...]` lists, parsing the standard
`{dist}-{ver}(-{build})?-{pytag}-{abitag}-{plattag}` layout against this interpreter's tag
(`cpython-315-x86_64-linux-gnu`, manylinux x86_64, GIL-enabled).

**Result: 113 locked packages = 79 pure-python (`py3-none-any`) + 8 with a lock-tag-matching
binary + 26 with none.**

**Scope of that count:** the 26 are derived **only from the wheel lists already recorded in the
lock file**, parsed against this one interpreter's tag (`cpython-315-x86_64-linux-gnu`, GIL
enabled). **3 of the 26 are not registry packages at all** — they are the local
`[tool.uv.sources] path` builds (see below), blocked only because `--no-build` also blocks local
wheel builds. So the real registry count in this table is **23**, and even that is **not** an
inventory of PyPI: it says nothing about packages or versions outside this lock, and "no
matching tag in the lock" is **not** a claim that no usable wheel exists on any other platform,
tag or newer release.

### Lock-tag satisfaction ≠ proven install — do not read the tag match as "it installs"

These packages' lock entries carry an `abi3` or native `cp315` wheel tag **compatible with this
regular CPython 3.15 x86_64 tag**. That is a **metadata/label-level** reading: it predicts the
wheel would be selected without a source build, and it corrects an earlier draft of this analysis
that mis-split the ABI tag and wrongly condemned them. **It is not install evidence** — no
install of these eight ran, none was imported, and nothing here has been executed on 3.15:

| Package | Version | Actual wheel tag (verbatim from lock) | Verdict |
| --- | --- | --- | --- |
| `igraph` | 0.11.9 | `igraph-0.11.9-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | tag satisfies 3.15 label; **install/import unverified** |
| `leidenalg` | 0.10.2 | `leidenalg-0.10.2-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | tag satisfies 3.15 label; **install/import unverified** |
| `polars-runtime-32` | 1.43.2 | `polars_runtime_32-1.43.2-cp310-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` | tag satisfies 3.15 label; **install/import unverified** |
| `ast-serialize` | 0.8.0 | `cp39-abi3` | tag satisfies 3.15 label; **install/import unverified** |
| `numpy` | 2.5.2 | native `cp315-cp315` | tag satisfies 3.15 label; **install/import unverified** |
| `pillow` | 12.3.0 | native `cp315-cp315` | tag satisfies 3.15 label; **install/import unverified** |
| `greenlet` | 3.5.5 | native `cp315-cp315` | tag satisfies 3.15 label; **install/import unverified** |
| `librt` | 0.15.0 | native `cp315-cp315` | tag satisfies 3.15 label; **install/import unverified** |

So the four candidates named in the request — **cyvcf2, polars, igraph, leidenalg — split at the
label level only**: polars / igraph / leidenalg have a 3.15-satisfying tag in the lock; cyvcf2
does not. **Which of them actually installs, builds or imports on 3.15 remains unverified for all
four.**

### Lock entries with no 3.15-satisfying linux wheel tag — source build would be required

All rows below are read off **the lock's own `wheels` lists for these pinned versions on this
platform**. "Source build required" describes what `--no-build` refuses to do for *these locked
entries*; it is **not** a claim that the project or any wheel index has no usable artifact for
some other version, tag or platform.

| Package | Version | Tags present in lock | sdist? |
| --- | --- | --- | --- |
| `cyvcf2` | 0.34.0 | `cp314` only | yes |
| `pysam` | 0.24.0 | `cp314` only | yes |
| `pyarrow` | 25.0.1 | `cp314` only | yes |
| `pandas` | 2.3.3 | `cp314` only | yes |
| `scipy` | 1.18.0 | `cp314` only | yes |
| `clickhouse-connect` | 1.7.0 | `cp314`, `cp314t` | yes |
| `pydantic-core` | 2.46.4 | `cp314` only | yes |
| `psycopg2-binary` | 2.9.12 | `cp314` only | yes |
| `numba` | 0.67.0 | `cp314` only | yes |
| `llvmlite` | 0.49.0 | `cp314` only | yes |
| `matplotlib` | 3.11.1 | `cp314` only | yes |
| `h5py` | 3.16.0 | `cp314` only | yes |
| `scikit-learn` | 1.9.0 | `cp314` only | yes |
| `statsmodels` | 0.14.6 | `cp314` only | yes |
| `contourpy` | 1.3.3 | `cp314` only | yes |
| `kiwisolver` | 1.5.0 | `cp314` only | yes |
| `markupsafe` | 3.0.3 | `cp314` only | yes |
| `pyyaml` | 6.0.3 | `cp314` only | yes |
| `google-crc32c` | 1.8.0 | `cp314` only | yes |
| `lz4` | 4.4.5 | `cp314` only | yes |
| `numcodecs` | 0.16.5 | `cp314` only | yes |
| `biopython` | 1.88 | `cp314`, `cp315` present **but no manylinux-x86_64 cp315 wheel** | yes |
| `chdb-core` | 26.7.3 | `cp39` only, **no sdist** | **no** |

`chdb-core 26.7.3` is the sharpest edge **within this lock**: it is a `dev`-extra dependency
(`chdb>=4.0` in `apps/worker/pyproject.toml`), its lock entry has **no sdist**, so a
`--no-build` install of *this locked version* cannot obtain it on 3.15 by any route short of
changing the pinned version. That is a statement about the lock entry, not about the package as
published. This slice did **not** download it and did **not** confirm whether its `cp39` wheels
are actually `abi3`; the classification stays **unconfirmed**.

The three `soymutdb-*` entries (`soymutdb-worker 2.0.0`, `soymutdb-jobs 0.1.0`,
`soymutdb-import-protocol 0.1.0`) have zero wheels in the lock because they are local
`[tool.uv.sources] path` packages built by hatchling. They are **not** a cp315 gap; they only
appear in the table because `--no-build` also blocks local wheel builds.

## C3.4 What this does and does not prove

**The one thing actually diagnosed:** the exact command above — `uv sync --locked --no-build
--extra dev` against the isolated mamba CPython 3.15 interpreter — **failed: exit code 2, stopped
at `clickhouse-connect 1.7.0`, 0 packages installed.** That is the entire real diagnostic. What
it establishes is narrow: **a locked, binary-only (`--no-build`) install of `apps/worker` in
*this* environment failed at the first source-only distribution.** The 23 registry rows in the
table above are an **offline tag parse of the existing lock's wheel lists**, not a uv-reported
count; `clickhouse-connect 1.7.0` is the only offender uv actually named, and `cyvcf2 0.34.0` /
`pysam 0.24.0` / `pyarrow 25.0.1` were never reached.

**Explicitly NOT proved:**

- That these packages are *incompatible* with 3.15. Most ship an sdist and would presumably
  build. This slice deliberately **did not start** those builds — `cyvcf2`, `pysam` (Cython +
  bundled htslib) and `pyarrow`/`llvmlite`/`numba` are long compiles, far outside this slice's
  time budget. The failure is a **binary-availability** fact about these pinned entries, nothing
  more.
- That no usable wheel exists anywhere for them. Nothing here surveyed other versions, other
  platforms/tags, or the wider index; **newly published wheels and alternative dependency
  versions were not checked**.
- That any of the eight tag-satisfying packages actually installs or imports. Nothing was run.

**Do not transfer the API-side evidence to the worker.** The earlier API-track binary compile
(orjson, Rust/maturin) that ended `exit 0`, and the `cargo metadata` retry, are **API/cargo-path
results served from an already-materialised toolchain/cache**. They say nothing about
`apps/worker`'s other packages and must not be cited as evidence that a worker build would work.

**Not reached:** the import smoke (numpy / scipy / pandas / polars / pyarrow / pysam / cyvcf2 /
scanpy / anndata / igraph / leidenalg) and the narrowest no-DB unit pytest run both depend on a
successful install. **They did not run — no import test of any kind was executed.** **No
pass/fail/skip count is claimed for C3**, and no hand-rolled `pip install` of individual packages
was used to manufacture a fake green result.

## C3.5 Build chain the next slice will need

To move `apps/worker` onto 3.15, one of these must be decided *before* any compile:

1. **Wait/bump** — the blockers are already-published wheels whose upstream simply has not
   cut cp315 yet. `cyvcf2`, `pysam`, `pyarrow`, `pandas`, `scipy`, `pydantic-core`,
   `clickhouse-connect` are all actively maintained with recent `cp314` cuts; `cp315` wheels
   are the expected near-term fix. This is the cheapest path and changes only lock content.
2. **Source build** — requires a C compiler, Cython, Rust (`maturin`/`puccinialin` for
   `pydantic-core`, `google-crc32c`, `lz4`) and a C++ toolchain for `igraph`/`leidenalg` are
   *not* needed (abi3), but `pyarrow` additionally needs CMake + a long Arrow C++ build, and
   `scipy`/`pandas`/`h5py`/`scikit-learn`/`matplotlib` each need BLAS/LAPACK/OpenMP/MKL
   headers. That is a heavy build image, and `chdb-core 26.7.3` has **no sdist to fall back
   to**. Not attempted, not recommended.
3. **Split the worker env** — run the *analysis* half (scanpy/anndata/igraph/leidenalg/polars,
   all of which are cp315-clean or abi3) on 3.15 and keep the *ingestion* half (cyvcf2, pysam,
   pyarrow, clickhouse-connect, psycopg2-binary) on 3.14. Smaller blast radius, but it
   splits one service across two interpreters.

## C3.6 Side effects of this slice — complete

1. `.mamba-root/envs/py315/venvs/worker/` — **created, empty** (interpreter + `pyvenv.cfg`
   only, zero packages). Verified gitignored via `.gitignore:215` (`.mamba-root/`), so it
   cannot enter version management. **Persistent on disk** unless removed by hand.
2. Shared uv cache `/mnt/data02/T25ronglin/.cache/uv/` — negligible metadata only; this run
   resolved from cache and installed nothing.
3. `docs/dev/mamba-python315-validation.md` — this C3 section (status line + appended text).
4. **Nothing else.** `apps/worker/uv.lock` and `apps/worker/pyproject.toml` verified
   unmodified by `git diff --stat` (empty output). `apps/worker/.venv` never written. No
   service started, no port bound, no database contacted, no SQLite substitute, no Docker
   invocation, no long-running compile started, no background job left running.

## C4. Formal 3.15 support for `apps/mcp-server` (`beartype` 0.23.1 locked)

Appended 2026-10-11 by the C2 minimal-migration slice. **The header status line above is
owner-owned and was deliberately left untouched**; this slice only appends.

### C4.1 Toolchain disclosure — the pinned uv is **not** on this host

| Field | Value |
| --- | --- |
| repo pin (unchanged) | `uv 0.11.33` (Dockerfiles, governance pipeline) |
| uv actually used | **0.12.21** (`/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin/uv`, the only uv on PATH) |
| toolchain pin changed? | **No.** No second toolchain was installed. |

**Lock format did not spill.** `uv lock --check` passed against the existing lock before the
edit (`Resolved 79 packages`, exit 0), and the file still opens with `version = 1`,
`revision = 3` after it. Package count 79 → 79, `name` order byte-identical, no
resolution-marker churn. A `0.12.21` rewrite of this lock is therefore format-compatible with
what `0.11.33` reads, but that was **not** re-proved by executing 0.11.33.

### C4.2 The resolver call and the exact delta

Resolution was done in an isolated scratch copy first (`.ph/c2-uvscratch`, real `pyproject.toml`
+ `uv.lock` + `src` + `tests`), with the project's own uv, and **no hash was hand-written**:

```
uv lock --upgrade-package "beartype==0.23.1"   # exit 0
Updated beartype v0.22.9 -> v0.23.1
```

The resulting diff is **one hunk, three lines** — nothing else:

| | 0.22.9 (before) | 0.23.1 (after) |
| --- | --- | --- |
| sdist sha256 | `8f82b54aa723a2848a56008d18875f91c1db02c32ef6a62319a002e3e25a975f` | `8b805f246b32931c74f2b321ea0939fe5bb2ff43c12a3eff19cc4c854b832e1d` |
| wheel sha256 | `d16c9bbc61ea14637596c5f6fbff2ee99cbe3573e46a716401734ef50c3060c2` | `4461b4dc57e3fdd6c8a8464b22cf118002eea107c33e9fef651c69068ab3cce3` |

Only `beartype` carries a version change in the whole 79-package lock; a full-file diff filter
leaves 2 non-beartype lines, which are exactly the `-version`/`+version` pair.
`uv lock --check` on the real project after the write: exit 0. `py-key-value-aio 0.4.5` and its
`beartype` requirement are untouched. `apps/mcp-server/pyproject.toml` is **unmodified**.

### C4.3 Encoding warnings: cause and fix (repo UTF-8 protocol, not a global filter)

Baseline on 3.15 with the locked graph — `66 passed, 7 warnings`; the **same 3 tests fail**
under `-W error::EncodingWarning` (`3 failed, 63 passed`, exit 1):

```
tests/test_smoke.py:96                compose.read_text()             EncodingWarning
tests/test_smoke.py:108               config.read_text()              EncodingWarning
tests/test_transport_auth.py:107-110  4 x read_text()                 EncodingWarning
beartype/_util/cls/pep/clspep3119.py:1280                             DeprecationWarning
```

So the 7 warnings are **6 `EncodingWarning` + 1 third-party `DeprecationWarning`** — not "7
EncodingWarnings". The fix is the repo's own protocol, six call sites,
`read_text(encoding="utf-8")`. The scope is controlled and is stated as measured: **6 call
sites changed**, all inside `apps/mcp-server/tests` (`test_smoke.py` ×2,
`test_transport_auth.py` ×4), following the UTF-8 read protocol that `apps/api` / `apps/worker`
tests already use as examples in this repo. This slice did **not** audit, count, or unify
encoding handling across the repository, and makes no repo-wide claim. **No `filterwarnings`, no
`ignorewarnings`, no `typing` monkeypatch** was added, and `pyproject.toml` was not edited to
relax anything.

### C4.4 3.15.0 formal run — `exit 0`

Env `/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/mcp-candidate`
(`version_info = 3.15.0`, conda-forge CPython, GCC 15.3.0).

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra test --project apps/mcp-server --python <py315>` | exit 0, `Resolved 79 packages` |
| `uv pip check` | `Checked 75 packages` → **All installed packages are compatible** |
| `import mcp_server.server` / FastMCP | `fastmcp 3.4.7`, `beartype 0.23.1`, `mcp.name soymutdb`, `API_BASE http://localhost:8010` |
| strict encoding gate — full command, see note below | **66 passed**, exit 0, **0 EncodingWarning** |

Run this gate from `/mnt/data02/T25ronglin/code/web/apps/mcp-server` (`PYTHONPATH=src` is
relative to that directory), with the exact command:

```
PYTHONPATH=src /mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/mcp-candidate/bin/python -X warn_default_encoding -W error::EncodingWarning -m pytest tests -q -p no:cacheprovider
```

`-X warn_default_encoding` and `-W error::EncodingWarning` are **CPython interpreter** flags, so
both must appear **before `-m pytest`**; after `-m` they would be passed to pytest, which does
not accept them. The command above is the invocation these numbers belong to — this docs
correction did not re-run it, and does not claim a new result.
None of the three previously failing cases was skipped or deselected.

### C4.5 3.14.8 regression on the *same* lock — `exit 0`

New, separate env `/mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/mcp-compat314`
(`version_info = 3.14.8`, from `/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin/python3`),
created with explicit `UV_PROJECT_ENVIRONMENT` + `--python`, never by entering the project's
own venv.

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra test` | exit 0 |
| `uv pip check` | `Checked 72 packages` → all compatible |
| `import mcp_server.server` | `fastmcp 3.4.7`, `mcp.name soymutdb` |
| strict encoding gate — full command, see note below | **66 passed**, exit 0, 0 EncodingWarning |
| installed set, 3.15 vs 3.14 | **identical**, 73 packages (excluding the env-only pytest trio) |

Same working directory `/mnt/data02/T25ronglin/code/web/apps/mcp-server`, same flag ordering
(`-X` / `-W` before `-m pytest`), different interpreter — run from that directory:

```
PYTHONPATH=src /mnt/data02/T25ronglin/code/web/.mamba-root/envs/py315/venvs/mcp-compat314/bin/python -X warn_default_encoding -W error::EncodingWarning -m pytest tests -q -p no:cacheprovider
```

As above, this row is corrected to the exact command behind the numbers; it was not re-run by
the docs correction.

Both interpreters fall in the same lock fork (`python_full_version >= '3.14'`), which is why the
resolved set matches. `beartype 0.23.1` is installed from the lock on **both** — the lock is the
single source of truth, not a local override.

`apps/mcp-server/.venv` and `.mamba-root/envs/py315/venvs/mcp-server` were verified **untouched**:
identical directory-tree md5 and identical `mtime` before and after both syncs.

### C4.6 Residuals — do **not** read this as "3.15 done"

1. **The container image does not run 3.15.** `apps/mcp-server/Dockerfile:6` is still
   `FROM python:3.12-slim`. This slice makes the *lock* formally installable and testable on
   3.15; it moves no image, no `.cnb.yml` pin, no Dockerfile, and no shared-job pin.
2. **`apps/worker` is still blocked** (C3.2): `cyvcf2` / `pysam` / `pyarrow` /
   `clickhouse-connect` have no cp315 wheel. Untouched here.
3. **`bash scripts/ci-job-steps.sh run mcp-e2e` cannot run on this host** — `docker: 未找到命令`.
   That job is an image build plus a transport smoke against a live container; it is **not**
   evidence for or against this slice, and it was not run.
4. **One warning survives on 3.15 and is not ours to fix here**: a `DeprecationWarning` from
   `beartype/_util/cls/pep/clspep3119.py:1280` — `<class 'key_value.aio.protocols.key_value.AsyncKeyValue'>`
   is not `@runtime_checkable` but is used in `isinstance()`. Third-party code, upstream
   `py-key-value-aio` concern; it becomes a `TypeError` in Python 3.20. On 3.14.8 it does not
   fire (0 warnings total). Being a `DeprecationWarning`, `-W error::EncodingWarning` is
   unaffected.
5. **pytest is env-only, not a declared dependency.** The `test` extra ships `fakeredis` only.
   `uv sync --locked` *prunes* `pytest`/`pluggy`/`iniconfig` on every run (observed), so it was
   reinstalled with `uv pip install --python <venv> pytest` after each sync. No pin file changed.
6. `ruff check` passes on both edited files. `ruff format --check` still reports "would
   reformat" for both — **this is pre-existing at HEAD** (verified against `git show HEAD:`), and
   the first requested hunk lands on an untouched `assert read == {...}` line. Not reformatted.

### C4.7 Side effects — complete

1. `apps/mcp-server/uv.lock` — `beartype` 0.22.9 → 0.23.1, 3 insertions / 3 deletions.
2. `apps/mcp-server/tests/test_smoke.py`, `apps/mcp-server/tests/test_transport_auth.py` —
   6 × `read_text(encoding="utf-8")` and nothing else.
3. `.mamba-root/envs/py315/venvs/mcp-compat314/` — **new**, 3.14.8 (72 locked packages plus the
   env-only pytest trio). Gitignored via `.gitignore:215` (`.mamba-root/`).
4. `.mamba-root/envs/py315/venvs/mcp-candidate/` — the pre-existing candidate env, now
   **lock-synchronised** (the env-level 0.23.1 override it carried is now the locked truth).
5. Workspace scratch `.ph/c2-uvscratch/`, `.ph/head-tests/`, `.ph/l314.txt`, `.ph/l315.txt` —
   temporary, safe to delete.
6. This doc section. **Nothing else.** No pyproject, no pipeline script, no Dockerfile, no shared
   job, no worker file, no other pin. No Git lifecycle operation, no server started, no port
   bound, no database contacted, no background job left running.

### C4.8 Docs-only correction — one file, no test re-executed

Written 2026-10-11. Scope of this subsection: **this file only**. No source, no test, no lock, no
`pyproject.toml`, no Dockerfile, no pipeline script, no pin. Nothing was executed.

1. **The C4.4 / C4.5 gate rows now carry the full, copy-runnable command** with the interpreter
   named by absolute path — `venvs/mcp-candidate` for 3.15.0, `venvs/mcp-compat314` for 3.14.8 —
   both run from `/mnt/data02/T25ronglin/code/web/apps/mcp-server`, with `-X`/`-W` ahead of
   `-m pytest`. The earlier abbreviated form (`pytest tests -Xwarn_default_encoding -W error::…`)
   handed those options to pytest rather than the interpreter, so it was not a runnable form of
   this gate and did not produce the results reported.
2. **The 66 / 66 figures and the 0-EncodingWarning results are unchanged and are not a fresh
   claim.** They are the recorded outcome of the 74bbc re-run of these two gates; this edit only
   made the documentation match the command that produced them. No pytest run, no pass/fail
   recount, and no new evidence is asserted here.
3. **Encoding scope restated.** The six `read_text(encoding="utf-8")` edits in C4.3 / C4.7 are
   the entire source-side footprint of this slice. The `apps/api` / `apps/worker` UTF-8 protocol
   is cited as the repo pattern those 6 sites follow — not as evidence of repository-wide
   uniformity. The earlier `42 existing sites` count is withdrawn as an unverified figure.
4. **Earlier failing numbers are preserved, not erased.** C4.3's baseline stays exactly as
   recorded: `66 passed, 7 warnings` before the fix, and `3 failed, 63 passed`, exit 1 under
   `-W error::EncodingWarning` on 3.15. Those failures are the evidence the six edits were
   required; C4.4 / C4.5 do not replace them.

#### C4.8.1 Supersession note for the header status line

The header status line ("C1 done, C2 partially done, C3 blocked …") is owner-owned and was left
byte-identical. It is a 2026-10-10 snapshot and stays as history; read against the current state
of this page it means:

| Header wording | Current truth (this page, 2026-10-11) |
| --- | --- |
| "C2 partially done" | superseded **only** for `apps/mcp-server`: the lock is formally installable and testable on 3.15, **66 passed / 0 EncodingWarning on 3.15.0 and the same 66 on 3.14.8** |
| what that pass is | a **Python gate on two candidate venvs**. It is **not** a whole-Docker or runtime-pipeline result: no image moved, no `.cnb.yml` / shared-job pin changed, `mcp-e2e` was not run |
| not superseded | `apps/mcp-server/Dockerfile:6` is still `FROM python:3.12-slim`, and `apps/worker` is still blocked (C3.2). **3.15 is adopted nowhere by this workstream** |
