# ADR-0014: ship pdfjs-dist 6 after fixing the worker and build-path pipeline

Status: accepted (2026-10-18)
Context: ADR-0013 deferred the pdfjs-dist 4 → 6 upgrade because its two
artifact-level blockers were about the **build pipeline**, not the library:
the worker was loaded through Vite's `?url` convention that Umi/webpack does
not implement, and pdf.js's Node-only branch inlined `import.meta.url` as an
absolute `file:///…` build path. Both were fixed first, then the upgrade was
re-attempted and verified.

## Pipeline fixes (shipped first)

1. **Worker as a static asset.** `apps/web/scripts/sync-pdf-worker.mjs` copies
   the installed `pdfjs-dist/build/pdf.worker.min.mjs` into
   `apps/web/public/pdf.worker.min.mjs`; `build-sites.ts` runs it before both
   variant builds and `pnpm dev` chains it, so the file always matches the
   installed pdfjs version. The generated copy is gitignored. The viewer sets
   `GlobalWorkerOptions.workerSrc = ${import.meta.env.BASE_URL}pdf.worker.min.mjs`
   — same-origin under the external sub-path or the internal root — and the
   old `?url` dynamic import plus its ambient module declaration are gone.
2. **No build-machine paths in emitted bytes.** pdf.js has a Node-only branch
   (`process.getBuiltinModule("module").createRequire(import.meta.url)`);
   webpack inlined that `import.meta.url` as `file:///home/<builder>/…`. The Umi
   config now blank-defines `import.meta.url` (the branch never runs in a
   browser), and `scripts/check_artifact_build_paths.py` (+ 5 unit tests, wired
   into `verify-frontend-artifacts.sh`) fails the build when any artifact
   contains the repository root, `file:///` host paths, `/mnt/…`, `/home/<user>/…`,
   `/Users/…` or `C:\…\`.
3. **Module-worker MIME.** Browsers reject a module worker served as
   `application/octet-stream`; the container web nginx maps `.mjs` to
   `application/javascript` explicitly (the distro `mime.types` only maps
   `.js`) with a short cache since the worker filename is not content-hashed.
   The E2E static server and the dev preview server also map `.mjs`.

## pdfjs-dist 4.10.38 → 6.4.299 (shipped)

API migration (as prepared in ADR-0013):

* `PDFDocumentProxy.destroy()` removed → teardown destroys the
  `PDFDocumentLoadingTask`, which aborts the network requests and the worker;
* `RenderParameters.canvas` is required → `page.render({ canvas, viewport })`
  (the legacy `canvasContext` form would require `canvas: null`).

Evidence:

* `tsc --noEmit` clean; web suite **44 files / 373 tests** pass.
* Both variants contain `pdf.worker.min.mjs`; the artifact build-path guard
  passes on `dist/external`, `dist/internal` and `dist/admin`.
* Browser sanity against the built external artifact: worker fetched with
  `text/javascript; charset=utf-8` (1 264 143 bytes), the module worker starts
  and posts a message; no page errors beyond the known benign
  "frame-ancestors ignored in meta" console notice.
* Full gates recorded in `docs/dev/project-status.md` (workspace lint/typecheck/
  test, scripts, frozen lockfile, builds, artifact budgets, static/contracts
  smoke, browser a11y).

Consequences: the PDF viewer is on the current pdfjs major with a
webpack-compatible worker pipeline; artifact hygiene is enforced for every
frontend build; the next held items are dnd-kit, jbrowse major, TypeScript 7 and
redis-py 8. Rollback is the dependency pin plus the viewer file (the pipeline
fixes are independently valuable and stay).
