# Incremental implementation roadmap

## Phase 0: baseline and audit (complete)

- Audited the existing BLAST API, service, model, worker, frontend, MCP manifest and tests.
- Confirmed release-scoped database discovery, transactional outbox, idempotent worker writes and authenticated researcher job ownership.
- Recorded the test baseline on Python 3.15 (see [`blast-verification-pr.md`](blast-verification-pr.md)).
- Completed a first-party external-database research pass; see [`../research/plant-database-feature-comparison.md`](../research/plant-database-feature-comparison.md). Unverifiable sources remain labelled candidates.

## Phase 1: BLAST+ (execution repaired; see status below)

- NCBI BLAST+ executes all five standard programs against real 2.17.0+ binaries.
- DIAMOND `blastp` is retained as an explicitly selected backend; both engines remain available in the API, client, frontend and MCP contracts.
- Immutable `makeblastdb`/`blastdbcmd` index catalog with additive migrations `0050`/`0051`.
- Program-specific parameter validation shared by API and worker; argument-array-only execution with resource caps.
- Two access modes: authenticated account jobs (`/blast`) and capability-authorized anonymous jobs (`/search/blast`), both over the same outbox/worker pipeline.
- Real nucleotide and protein integration searches, index construction, PostgreSQL HSP persistence, duplicate-delivery idempotency, cancellation, quota and release-isolation tests.
- External research report distinguishes verified observations from candidates; no dataset ingestion or license claims are made.

## Phase 2: gene center (next)

Compose sequence, annotation, homolog, expression, variant, phenotype and publication sections on the existing gene routes. Preserve assembly switching and evidence labels.

## Phase 3: comparative genomics

Import orthology/family snapshots with method metadata, add alignments and phylogenetic artifacts, then add JBrowse-backed synteny and conserved-block views.

## Phase 4: expression and phenotype

Expose study/sample metadata, units, tissue/stage/treatment filters, QTL/GWAS links and existing chart abstractions.

## Phase 5: licensed resources

Add PlantTFDB, PlantCARE, PlantCyc and optional GBIF adapters only after source terms, checksums and refresh owners are recorded.

## Phase 6: query/download polish

Extend the existing asynchronous download service with a no-SQL query builder, provenance manifests, cursor pagination, accessibility and performance gates.

Status (0056): provenance manifests and a whitelisted query builder are
implemented. `download_files` and `variant_exports` carry nullable
`sha256`/`license`/`generated_at`/`source_ref`; the worker records the digest
of the exact uploaded bytes; `GET /variants/export/{id}/manifest` is the
owner-scoped citable record, and `POST /exports/query` submits whitelisted
filters through the existing outbox/export pipeline. A legacy artifact with
no checksum returns `sha256: null` with `sha256_state: not_recorded`.
Filters with no backing query capability (gene_list/species/biotype/GO/KEGG/
expression threshold/homolog species) and formats with no artifact builder
(FASTA/GFF3/GTF) are refused explicitly, not silently dropped or claimed.

### Phase 1 status: repaired but incomplete

The NCBI execution slice landed unreachable: `ncbi_blast.py` did not parse
(Python-2 `except A, B:`), and the worker whitelisted `blastp` for every engine,
so four of the five advertised programs were refused. Both are fixed and the
five programs now pass real-binary searches — see
[runtime repair evidence](blast-ncbi-runtime-repair-pr.md).

Entry-point parity (branch `feat/blast-access-parity`, verified by the gates
listed below; nothing here is claimed on the strength of a mocked response
alone):

- Program vocabulary: `tasks/blast.py` holds `ENGINE_PROGRAMS`, the per-engine
  sets (`diamond` = `blastp`, `ncbi_blast` = all five), and keeps the historical
  `ALLOWED_PROGRAMS` union for vocabulary probes. The DIAMOND-only set stays
  addressable as `DIAMOND_PROGRAMS`, so it can no longer be misread as the
  platform's program list.
- Worker split: `apps/worker/src/soymutdb_worker/ncbi_blast.py` runs all five
  programs with fixed argv, resource limits and provenance; `tasks/blast.py`
  keeps DIAMOND as an explicit `blastp` backend.
- Access parity: the anonymous route surfaced validation failures through
  `Alert title=`, which AntD 6 does not render, so every client-side rejection
  was silent. Fixed; the signed-in route now shares the same FASTA rule.
- Raw-result download: the anonymous page offered the presigned artifact, the
  signed-in page did not. Both now offer it as tab-separated aligner output
  (`outfmt 6`), and neither renders a link when the job has no stored artifact.

Phase 1 items that were listed here as open have since landed; the list is
rewritten rather than deleted so a reader can tell what changed:

| Item | State | Where |
| --- | --- | --- |
| Asynchronous `makeblastdb` build/publication in the worker, with catalog build states | done | `apps/worker/src/soymutdb_worker/tasks/blast_index.py`, migration `0052` |
| Admin enable/disable control for an index | **still open** | no HTTP route toggles `blast_databases.is_active`; only the worker's publish path writes it |
| Protein-hit → transcript/gene resolution before genome-browser links | done | `apps/worker/src/soymutdb_worker/blast_genome_resolution.py`, `BlastService.resolve_genome_target`, `routes/blast.tsx` |
| Five-program UI wiring on `/blast` | done | `apps/web/src/routes/blast.tsx` (program selector filtered by engine, engine selector disabling DIAMOND for non-`blastp`) |
| Cancellation, retry and download-expiry coverage on the NCBI path | done | `apps/worker/tests/test_blast_cancel_retry_expiry.py::test_ncbi_jobs_are_guarded_before_the_engine_runs`, `apps/api/tests/test_blast_cancel_retry.py` |

Two caveats on that table, both of which the repository has already been wrong
about once:

- the resolution path is scoped in the *relation query*, not after it. A
  transcript id and an alias are strings that v4 and v5 can both carry, so
  collecting candidates first and filtering by assembly later leaves the
  contract standing on one downstream condition. It is now joined and filtered
  inside each relation query, and
  `test_blast_genome_resolution.py::test_a_relation_of_another_assembly_is_never_a_candidate`
  fails if that scoping is removed;
- the NCBI coverage above is the *guard* (cancelled and past-deadline jobs never
  reach `get_ncbi_db_path` or the aligner). It does not assert a real NCBI
  binary produced a result; that remains the opt-in real-binary suite's job.

Verification environment for the numbers this document reports: Python 3.15.2
via `uv`, no PostgreSQL server and no NCBI BLAST+/DIAMOND binaries in the
sandbox. `apps/api` therefore runs against its fakes and reports
`2469 passed, 25 skipped, 0 failed` with 389 `DockerException` errors from the
testcontainers fixtures; the real-binary and PostgreSQL integration suites stay
opt-in and are the ones CI must run.

## Current PR boundary

## Delivery notes

Earlier slices were delivered as separate commits on `main`: anonymous
capability authorization, catalog/index preparation, and NCBI execution. This
PR closes the verification gap: it makes the opt-in real-binary tests reliable
offline, aligns the architecture/roadmap documents with the implemented state,
records a first-party research ledger, and reports actual pass counts. It does
not complete the four Phase 1 items listed above, and does not replace the
existing delivery pipeline or add a second job queue/storage backend.

---

## Rust bio-core 0.1.2 — re-phased slice (2026-11-05)

The 2026-11-05 Rust-core spec is a design proposal, not a delivered state.  The
phases below were re-cut by *file ownership* rather than by feature noun, so each
PR is independently buildable and no two parallel agents write the same file.
Every phase is one PR; the chain is `#83 → #96 → #101 → #105`.

| Phase | PR | Content | Verification |
| --- | --- | --- | --- |
| R1 | #83 | `packages/bio-core` crate (Rust-Bio / noodles / rust-lapper / bio-seq / PyO3), `Cargo.lock` + pinned toolchain, golden + adversarial Rust tests, `scripts/verify-bio-core.sh`, `bio-core` CI job in the shared dispatcher + both providers | 41 Rust tests, cp315 wheel + import smoke, 9 wheel pytest, 36/36 turbo, 87 contracts |
| R2 | #96 | `/tools/sequence/*` 7 compute endpoints + `capabilities`, Pydantic limits, fail-closed bridge, OpenAPI/`openapi.d.ts` regeneration | 10 API tests, `check-contract.sh` EXIT 0, 36/36 turbo |
| R3 | #101 | `/tools/intervals/overlap` over published genes, `/tools/sequence/inspect`, `SOYMUTDB_BIO_ENGINE` fail-closed toggle | 16 API tests, 0 removed / 0 changed / 10 added OpenAPI paths |
| R4 | #105 | wheel installation into the backend test venv, `smoke.sh` static+runtime wheel gates, full regression, architecture doc; wheel built once in the `bio-core` job, consumed (not rebuilt) by `api-tests` | below |

### R4 verification (this PR)

Run on the merged chain with CPython 3.15.2 / Rust 1.99.1 / pydantic 2.14.1:

- `bash scripts/verify-bio-core.sh` — PASS (fmt, clippy, 41 Rust tests, wheel, import, 9 pytest)
- `pytest apps/api/tests/test_sequence_tools.py apps/api/tests/test_interval_overlap.py -q` — 16 passed
- `pnpm turbo run lint typecheck test --force` — 36/36
- `python3 -m unittest scripts.test_ci_job_contracts scripts.test_site_artifact_isolation` — 87 passed
- `bash scripts/smoke.sh --profile contracts` — PASS (includes `check_bio_core_wheel.py --static`)
- `SOYMUTDB_API_PYTHON=… bash packages/api-client/scripts/check-contract.sh` — OK, visibility PASS
- `ruff check` on every changed Python file — clean

Not run here (prerequisite missing, reported honestly): `--profile runtime`
needs a disposable PostgreSQL + API venv; `--profile images` needs a Docker
daemon; Playwright E2E needs browsers.  A missing prerequisite is `SKIPPED`,
never a pass.

### Still not implemented

- Wheel shipped inside `infra/docker/Dockerfile.api` / `.worker` runtime images
  (needs a Rust builder stage + SHA-256 verified install + multi-arch wheels).
- `/tools/sequence/batch` async jobs, CDS phase/negative-strand assembly,
  GFF3 Parent association, VCF/BCF/BAM/CRAM adapters, non-standard NCBI
  translation tables, interval index cache with release/assembly invalidation.
- Frontend `/tools/sequence` page (owned by @npc/CodeBuddy(deepseek-v4.1-flash)).
- Fuzz / property / benchmark gates; `cargo audit` / `cargo deny` in the release lane.

Do not describe any of the above as complete until a PR links a passing test.


### R6 — bio-core 供应链与多架构证据（独立 PR）

`cargo audit` / `cargo deny` 与多架构 ABI/platform tag 台账不再挂在
"Still not implemented" 里：它们落在唯一带 Rust 工具链的 bio-core job 和
`docs/dev/bio-core-wheel-abi-tags.md`，由 `smoke.sh --profile contracts` 的
源码守卫 + 合成负例套件钉住。两个架构的 OCI 真编译与镜像 smoke 仍归 CI，
本仓库不代签。

R6 首轮 CI 起连续挂在供应链 lane 上，接线缺陷已在同一源分支逐层收掉：
`2a4fcfcc`…`e444eaf6` 修掉「兄弟进程不继承 `CARGO_HOME`/PATH」、把
cargo-audit 抬到 0.22.2、并让失败路径打印证据；`2649f71f` 把 cargo-deny 抬到
0.18.9 —— `cnb-qf2-1k6kc4hoo` 那次静默 exit 1 的真因是它自己的 CVSS 4.0
解析墙，不是缺配置。本轮补上解析器修好之后的下一层：新增
`packages/bio-core/deny.toml`，把 cargo-deny 从「空 license allowlist + 维护
告警被 `--deny warnings` 升级成错误」变成一份逐项写死、随 `Cargo.lock` 评审
的策略。真漏洞仍 fail-closed；三个无修复版本的传递 unmaintained crate 用
`unmaintained = "transitive"` 显式限定范围，不假装修好。

第三层是判定本身：原 heredoc 把 `vulnerabilities.found`（布尔）当漏洞数、
用 stdout 子串判 deny、且无视两个扫描器的退出码，三种形状都能在绿套件下
签发 `passed` 报告，而 heredoc 不可 import 所以没有任何守卫能验证它。现收
成 `scripts/check_bio_core_supply_chain.py`（读 `count`/`list`、以退出码为
判据、空输出/畸形 JSON 一律 fail-closed）+ 15 条行为用例，脚本捕获
`AUDIT_RC`/`DENY_RC` 后调用；`deny.toml` 是 lint level 的唯一真相源，不再
加 `--deny warnings`。源码守卫与 contracts 层双重钉住，六组变异各自咬一层。
行为回归 + 变异验证见 `docs/dev/bio-core-wheel-abi-tags.md`。
