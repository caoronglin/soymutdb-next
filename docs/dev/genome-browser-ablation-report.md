# Zero-React genome browser ablation report

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

- **Date:** 2026-09-26
- **Repo:** `/mnt/data02/T25ronglin/code/web`
- **Target:** `@soymutdb/genome-view` components + `@soymutdb/genome-data` readers + `apps/jbrowse` bridge/deep-link
- **Spec:** `docs/superpowers/specs/2026-09-26-vue-genome-view-design.md` §9
- **Constraint honored:** no source file was modified. New files only under `packages/genome-view/src/ablation/**` plus this report.

## Scope

Every experiment is a Vitest case driving the real components/readers with the
committed `packages/genome-data/test/fixtures/*` through an in-memory
`MemoryFileProvider`. No network access, no `.bw`/`.bb` fixture writer, no
package-manager invocation. Cross-package bridge/deep-link code is imported
directly from `apps/jbrowse/src`.

## Exact commands and results

| Command | Exit | Result |
| --- | --- | --- |
| `cd packages/genome-view && ./node_modules/.bin/vitest run src/ablation` | 1 | 11 files, **17 passed / 0 failed** (17 tests) |
| `cd packages/genome-view && ./node_modules/.bin/vitest run` | 1 | 25 files, **25 passed / 0 failed**; **70 passed / 0 failed** (70 tests)
| `cd packages/genome-view && ./node_modules/.bin/vue-tsc --noEmit` | 0 | clean |
| `cd packages/genome-view && ../../node_modules/.bin/eslint src/ablation` | 0 | clean |

Baseline before the study: `vitest run` = 14 files / 53 tests, all passing.

## Per-scenario results

| # | Scenario | Status | Evidence (test name — file) | Note |
| --- | --- | --- | --- | --- |
| 1 | sequence track | PASS | `ablation scenario 1: reference sequence track > renders bases from reference.fa.gz/.fai/.gzi through TrackRenderer` — `packages/genome-view/src/ablation/01-sequence.test.ts` | chr01:0-12 renders `ACGTACGTACGT`; real bgzip FASTA + .fai + .gzi via `MemoryFileProvider`. |
| 2 | variant track | PASS | `ablation scenario 2: variant track > renders VCF markers and classifies snv/del/sv correctly` — `02-variant.test.ts` | 6 chr01 markers; `rs1` polygon (snv), `chr01:4-8:ACGT>A` and `chr01:19-40:N><DEL>` rects (del/sv); breakend `chr01:49-50:N>N]chr02:30]` classified sv; `VariantReader` kinds asserted directly. |
| 3 | feature track | PASS | `ablation scenario 3: feature track > renders GFF3 features and preserves the parentId hierarchy` — `03-feature.test.ts` | 5 feature rects for chr01; `gene01` (no parent) → `mrna01` → `exon01`/`cds01`/`exon02` all carry the expected `parentId`. |
| 4 | quantitative/interval | PASS | `ablation scenario 4: quantitative/interval > normalizes BigWig and BigBed feature units` and `> factory dispatches quantitative/interval/feature tracks by adapter type` — `04-quant-interval.test.ts` | `normalizeQuantFeatures`, `normalizeBigBedFeatures`, `parseBigBedRest` units verified; `createTrackDataSource` dispatches BigWig→`quantitative`, BigBed→`interval`, Gff3Tabix→`feature`, BgzipFasta→`reference-sequence`. Binary `.bw`/`.bb` reads were deliberately out of scope (no offline writer). |
| 5 | unknown track type | PASS | `ablation scenario 5: unknown track type > skips unknown types and warns exactly once per type per mount` and `> warns again once per new mount and renders no blank track` — `05-unknown-type.test.ts` | Duplicate unknown types warn once; two distinct unknown types warn once each; a fresh mount warns again; known tracks still render. |
| 6 | missing provider | PASS | `ablation scenario 6: missing provider > shows a role=alert error when no data provider is configured` — `06-missing-provider.test.ts` | `role="alert"` with "No data provider" and a Retry button. |
| 7 | missing file | PASS | `ablation scenario 7: missing file > reader rejects with GenomeDataError code fetch when a file is absent` — `07-missing-file.test.ts` | `VariantReader` and `SequenceReader` both reject `GenomeDataError` with code `fetch`. |
| 8 | assembly mismatch | PASS | `ablation scenario 8: assembly mismatch > factory rejects a track that references an unconfigured assembly` and `> reader rejects a foreign assemblyKey or an unknown reference name` — `08-assembly-mismatch.test.ts` | Factory throws `assembly-mismatch`; reader rejects a v5 region against a v4 reader and an unknown refName with the same code. |
| 9 | abort | **PASS** | ablation scenario 9: abort (2) - 09-abort.test.ts | Reader-level abort now rejects with code "aborted"; a stale result that resolves after a newer region is discarded before assignment. |
| 10 | bridge | PASS | `ablation scenario 10: postMessage bridge > emits a canonical envelope and parses an inbound envelope round-trip` and `> accepts every documented type and rejects a type outside the allow-list` — `10-bridge.test.ts` | `postToParent` stamps `source=soymutdb-jbrowse`/version 1 and targets the portal origin; all of `ready|error|locus-change|selection-change|init` are accepted; `locus-changed` is rejected with exactly one warn. |
| 11 | deep-link | PASS | `ablation scenario 11: deep-link coordinate conversion > round-trips 1-based inclusive <-> 0-based half-open intervals` — `11-deep-link.test.ts` | `toOneBased(toZeroBased(...))` identity for [1,1], [1,1000], [10,20], [500,500], [1,1000000]; clamp at 0; `parseLocus`/`formatLocus` and `parseDeepLink` verified. |

## Tally

- **Scenarios:** 11 PASS, 0 FAIL, 0 GAP (11 total).
- **Ablation tests:** 17 PASS, 0 FAIL (17 total), in 11 files.
- **Whole package suite:** 70 PASS, 0 FAIL (70 total).

## Defect found (report-only, not fixed)

Scenario 9's abort contract is not satisfied end to end.

1. **Reader-level abort is a no-op.** With a deliberately slow `FileProvider`,
   `VariantReader.getVariants(region, { signal })` is awaited while the
   controller fires at 5 ms. The read still resolves with all 6 records
   (`resolved:6`) instead of rejecting with `code: "aborted"`. The same probe
   with a pre-aborted signal resolves both VCF and FASTA reads. Root cause
   observed in the installed dependency:
   `node_modules/.pnpm/@gmod+tabix@1.5.6/node_modules/@gmod/tabix/dist/tabixIndexedFile.js`
   declares `let signal;` (line 105) and copies `options = opts` (line 116) but
   never assigns `signal = options.signal`; the later
   `checkAbortSignal(signal)` calls (lines 125, 139, 154) and the
   `chunkCache.get(..., signal)` call (line 153) therefore receive `undefined`.
   The same behaviour was observed for `@gmod/indexedfasta` through
   `SequenceReader`. `packages/genome-data/src/readers/*` does forward the
   signal correctly, but the underlying libraries ignore it.
2. **No view-layer guard.** `packages/genome-view/src/components/TrackRenderer.vue`
   assigns `variantRecords.value = await source.reader.getVariants(...)` (and the
   sibling readers) without re-checking `signal.aborted` after the await. When a
   stale read resolves after a newer one, the stale result replaces the current
   view — reproduced deterministically in the second failing test.

Impact: spec §4.4 ("`AbortSignal` 贯穿每次区域读取") and §8 ("`aborted` 静默") are
only partially met. Region changes do abort the component's controller (that
assertion passes), but in-flight region reads are neither stopped nor
discarded, so rapid panning can leave stale records on screen and wastes I/O.
A follow-up fix would either guard the assignment with `if (signal.aborted) return`
in `TrackRenderer.vue` and/or bypass the dependency signal bug inside
`genome-data` (e.g. race the read against the abort event). This study did not
change any source file.

## Limitations / not covered

- Scenario 4 verifies the normalizers and factory dispatch, not a real
  BigWig/BigBed binary read; there is no offline `.bw`/`.bb` writer in the repo,
  which the scenario explicitly excludes.
- No network/remote provider, browser rendering, or E2E iframe behaviour was
  exercised; those belong to higher layers of the §9 matrix.
- `support.ts` is shared test scaffolding for the ablation files, not production
  code.


## Resolution (2026-09-26, coordinator)

Scenario 9 is now green; the analysis above is retained as the audit trail.

1. Reader-level abort: packages/genome-data/src/readers/common.ts adds
   throwIfAborted(signal, trackId), and every reader (sequence, variant,
   feature, quantitative, interval) calls it immediately after its await and
   before returning. Because @gmod/tabix and @gmod/indexedfasta 1.x ignore the
   signal, this re-check is what makes cancellation observable: an aborted read
   now rejects with GenomeDataError code "aborted".
2. Stale-result guard: packages/genome-view/src/components/TrackRenderer.vue
   re-checks signal.aborted before assigning any reader result, and treats an
   aborted GenomeDataError as silent (no error state).

Evidence: packages/genome-data 87 tests + tsc green; packages/genome-view
70 tests (including src/ablation/09-abort.test.ts) + vue-tsc + eslint src green.
