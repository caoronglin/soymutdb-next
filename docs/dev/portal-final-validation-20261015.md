# Portal final validation — 2026-10-15

Scope: ECharts production-dependency retirement for the public portal plus the
dual-site SSG build, isolation gates and chart budget that the retirement had to
survive. Every number below was produced by the command printed next to it in
this session; nothing is carried over from an earlier run.

## 1. Was ECharts really unused?

Confirmed before deleting anything.

```
rg -n -i "echarts|zrender" apps/web packages/charts --glob '!**/node_modules/**' --glob '!**/dist/**'
```

The only production-reachable hit was `apps/web/src/lib/use-echarts.ts`. It had
**zero importers**: the sole other match was `portal-charts.test.tsx:502`, an
assertion that chart components do *not* reference it. The production chart
engine is AntV G2, reached through `packages/charts/src/g2-runtime.ts` via the
dynamic `import("./g2-runtime")` in `ChartCanvas.tsx`.

`@ant-design/plots` was a production dependency of `@soymutdb/charts` but is
imported only by `src/antv-react19.smoke.test.tsx`, so it was reclassified to
`devDependencies`. It was **not** deleted — the React 19 feasibility smoke still
runs against it.

## 2. Changes

| File | Change |
| --- | --- |
| `apps/web/src/lib/use-echarts.ts` | deleted (orphan, zero importers) |
| `apps/web/package.json` | dropped `echarts: catalog:` |
| `packages/charts/package.json` | dropped `echarts: catalog:`; `@ant-design/plots` moved to `devDependencies` |
| `apps/web/config/config.ts` | `charts` cache group narrowed to `@antv/*` + `@ant-design/plots/*` |
| `pnpm-workspace.yaml` | comments only — see the note below |
| `pnpm-lock.yaml` | 4 hunks, importers of `apps/web` and `packages/charts` only |
| `packages/charts/src/g2-runtime.test.ts` | 2 `TabularData` type errors fixed (added later, see §6) |

The `echarts: 5.5.1` **catalog entry was deliberately kept**. `apps/admin/package.json:41`
still declares `echarts: catalog:`, and that file belongs to another lane. A
catalog key cannot be removed while any importer still references it, so the
entry is now documented as residual instead of silently deleted. Removing it is
the correct follow-up once the admin console drops its declaration.

## 3. Commands and results

Environment: Node 26.10.0, `PATH=/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin:$PATH`,
`GOMAXPROCS=2 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=2`.

### Lockfile

```
pnpm install --frozen-lockfile --lockfile-only        # exit 0
```

The lockfile edit was hand-trimmed to the chart importers and then proved
consistent by that frozen check. A full `pnpm install --lockfile-only` was run
first and rejected as the deliverable: it also pulled `postcss 8.5.28 -> 8.5.30`
across ~500 lines, collateral drift from another lane's
`minimumReleaseAgeExclude` edit in `pnpm-workspace.yaml`, unrelated to charts.
For the same reason the `pnpm 12.5.1 -> 12.11.2` bump visible in `git diff`
**predates this work** — it was already in the working tree.

### Unit tests

```
cd packages/charts && node ./node_modules/vitest/vitest.mjs run --pool=forks --maxWorkers=1
```

`5 files, 84 tests passed`. Two stderr notes, both expected and unrelated:
jsdom cannot rasterise `HTMLCanvasElement`, and one `act(...)` advisory in
`ChartFigure.test.ts`. Neither is a failure and neither was silenced.

```
cd apps/web && node ./node_modules/vitest/vitest.mjs run --pool=forks --maxWorkers=1
```

`44 files, 371 tests passed`. No skips, no xfails.

### Typecheck

```
cd apps/web && node ./node_modules/typescript/bin/tsc --noEmit         # exit 0, 0 errors
cd packages/charts && node ./node_modules/typescript/bin/tsc --noEmit  # exit 0, 0 errors
```

`packages/charts` reported 2 pre-existing errors at `src/g2-runtime.test.ts:68-69`
when first measured. They were fixed after explicit authorization; see §6.

### Dual-site SSG build

```
cd apps/web && node ./node_modules/tsx/dist/cli.mjs scripts/build-sites.ts
```

`[sites] building external artifact` then `[sites] building internal artifact`,
ending `[sites] external and internal artifacts built`, exit 0, with no build
error lines.

Artifact check for the retired engine:

```
ls apps/web/dist/external/assets/ apps/web/dist/internal/assets/ | grep -icE 'echarts|zrender'   # 0
```

### Chart budget

```
bash scripts/check-bundle-size.sh apps/web/dist/external/assets
```

All cache groups `PASS`: entry 166/750KB, react 67/100KB, router 28/100KB,
ui 197/320KB, query 11/35KB, chunk caps all under 600KB, and
**charts 232KB/370KB** (`charts.a527256d.async.js`).

```
python3 scripts/chart_closure_budget.py --dist apps/web/dist/external   # exit 0
python3 scripts/chart_closure_budget.py --dist apps/web/dist/internal   # exit 0
```

Identical in both variants: closure of 691 modules, 32 JS assets verified by
sha256, and `PASS budget complete chart closure 331144 B <= 378880 B (370 KiB),
headroom 47736 B`. `PASS unassignedengine` reports **475 engine modules present,
475 attributed** — a surviving ECharts module would surface here as unassigned
and fail the gate, which is the direct proof the retirement is real and not
merely a deleted import statement.

### Artifact isolation

```
python3 -m unittest scripts.test_site_artifact_isolation -v   # Ran 11 tests — OK
bash scripts/check-production-artifact.sh apps/web/dist/external --allow-demo
```

`OK: (no forbidden placeholder / demo markers found)`, exit 0.

```
SOYMUTDB_SITE_VARIANTS_PREBUILT=1 bash scripts/verify-site-variant-artifacts.sh
```

Exit 0 — internal artifact noindex, internal free of the public snapshot,
external free of internal-only values, then
`OK: external artifact contains no supplied protected values`.

### Contract suites

```
python3 -m unittest scripts.test_chart_closure_budget scripts.test_framework_neutral_packages   # Ran 42 — OK
PYTHONPATH=scripts python3 -m pytest scripts/test_platform_delivery_contracts.py -q          # 37 passed
```

The delivery-contract module is pytest-style and collects **0 tests** under
`unittest`; running it with `unittest` would look like a silent pass. It pins the
`echarts: 5.5.1` and `@ant-design/plots: 2.6.8` catalog values, so it is the
direct regression net for this change and does pass.

```
pnpm --filter @soymutdb/charts --filter @soymutdb/web lint   # exit 0
```

0 errors, 6 warnings, all pre-existing in files unrelated to charts
(`gene-genome-view.tsx`, `analyses-i18n.test.ts`, `routes/genes/$geneId.tsx`,
`routes/search/genes.tsx`).

## 4. Known failures not caused by this change

| Gate | Result | Owner |
| --- | --- | --- |
| `python3 scripts/check_artifact_headers.py` | `4 file(s) checked`, 1 `FAIL` — `apps/admin/dist/_headers` contains sentinel `localhost` | admin console lane; the 3 portal `_headers` files passed |

The `packages/charts` typecheck entry from the first measurement pass has been
resolved and removed from this table; it is described in §6.

## 5. Environment note for the next run

`pnpm` on this host verifies its own npm release signature on every invocation,
so it needs registry reachability; inside the sandbox it hangs until timeout with
empty output rather than reporting a network error. Run it **escalated**.

Do **not** set `PNPM_HOME`/`XDG_CACHE_HOME` for ordinary commands. The
`.ai-memory/LOCAL-RUN-ENV.md` advice to export them applies to `pnpm dlx`, and
doing it for a normal install points pnpm at an empty store, which produces
`[ERROR] unable to open database file` and forces a re-download of the pinned
pnpm 12.11.2. With the default cache the same command finishes in ~3 s, because
the signature check result is cached in `~/.cache/pnpm/lockfile-verified.jsonl`.

Unrelated discovery: `/mnt/data02/T25ronglin/.miniforge3/envs/opencode/bin/pnpm`
is a **dangling symlink** to `../lib/node_modules/pnpm/pnpm`, a directory that
does not exist. Invoking it dies with no output and no exit code, which reads
like a hung command. The working binary is
`/mnt/data02/T25ronglin/.local/share/pnpm/lib/node_modules/pnpm/bin/pnpm.mjs`.

## 6. Follow-up: the two `TabularData` type errors

Granted separately, then done. Both errors were in `g2-runtime.test.ts:68-69`,
where the test calls the real G2 field encoder:

```
expect(encoder(options.encode.x)(options.data!)).toEqual(["A", "B"]);
expect(encoder(options.encode.y)(options.data!)).toEqual([3, 7]);
```

`CHART_LIBRARY["encode.field"]` is typed `(data: TabularData) => unknown`, and
the local assertion interface declared `data?: Array<Record<string, unknown>>`.
`unknown` is not assignable to G2's `Primitive`, hence the two errors. These
lines were pre-date this change, contain no ECharts reference, and had nothing
to do with the retirement — they were left alone during the first pass under the
no-scope-expansion constraint.

The fix is one annotation, chosen so no runtime code and no assertion changed:

```
import type { TabularData } from "@antv/g2/esm/runtime/types/common";
// ...
  data?: TabularData;
```

`options.data` is read at those two lines and nowhere else in the file, so the
local record type could be tightened without touching any other assertion. The
deep `@antv/g2/esm/...` specifier matches how `g2-runtime.ts` itself imports.

Re-measured after the fix:

```
cd packages/charts && node ./node_modules/typescript/bin/tsc --noEmit   # exit 0, 0 errors
cd packages/charts && node ./node_modules/vitest/vitest.mjs run --pool=forks --maxWorkers=1
pnpm --filter @soymutdb/charts lint                                      # exit 0
```

`Test Files 5 passed (5)`, `Tests 84 passed (84)`, with `src/g2-runtime.test.ts
(51 tests)` unchanged from before the edit. The 125 `expect(` calls in the file
are byte-identical; the change is type-level only.

## 7. Still pending, not yet actionable

The `echarts: 5.5.1` catalog entry and the corresponding `echarts`/`zrender`
lockfile entries are **still present on purpose**. `apps/admin/package.json:41`
still declares `echarts: catalog:`, and admin is another lane's file. Once that
declaration is gone, removing the catalog key plus the lockfile's `echarts` and
`zrender` package/snapshot entries is the last step of this retirement.

## 2026-10-16 收尾更新

Admin 最后一个 ECharts manifest 项已移除，catalog 与 pnpm lock 正常更新，
不再包含 ECharts/zrender。图表窄测重跑 84 passed。
Admin CSP finalizer 已按显式预览 origin 执行，
`python3 scripts/check_artifact_headers.py --require-dual` 四文件全部通过；
上文记录的 Admin localhost header 失败现已解决。
