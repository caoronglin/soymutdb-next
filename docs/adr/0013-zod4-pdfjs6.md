# ADR-0013: upgrade zod 3 → 4; defer pdfjs-dist 4 → 6

Status: accepted (2026-10-18); the pdfjs deferral was resolved by **ADR-0014**
(the worker/build-path pipeline was fixed and pdfjs 6 then shipped).
Context: ADR-0010's next item was "zod 4 and pdfjs 6 (forms and file viewer
respectively)". The repository has a single zod consumer (`apps/web`'s BLAST
form schema) and a single pdfjs consumer (the lazy PDF file viewer).

Decision: **take zod 4; keep pdfjs-dist 4**.

## zod 3.24 → 4.6.7 (taken)

The BLAST schema in `apps/web/src/routes/blast.tsx` uses only APIs whose
behavior is unchanged in v4 (`z.object`, `z.string().min(msg)`,
`z.number().int().min().max().default()`, `safeParse`, `error.issues`).
`tsc --noEmit`, the 373 web tests (44 files) and the production build pass with
no code change; the request/validation behavior is exercised by the existing
blast/search tests and the E2E public suite's BLAST coverage.

## pdfjs-dist 4.10.38 → 6.4.299 (deferred)

The v6 API migration itself is small and was implemented and type-checked:

* `PDFDocumentProxy.destroy()` was removed → teardown must call
  `PDFDocumentLoadingTask.destroy()`;
* `RenderParameters.canvas` is now required (`canvasContext` is legacy) →
  `page.render({ canvas, viewport })`.

Two artifact-level blockers made it unsafe to ship in this release, both
verified against a real `build:sites` artifact:

1. **Worker bundling.** The viewer loads the worker with
   `import("pdfjs-dist/build/pdf.worker.min.mjs?url")`. Umi/webpack does not
   implement the Vite `?url` convention, so the worker module is bundled as JS
   rather than emitted as an asset; the production artifact contains no worker
   chunk and the worker URL is not usable.
2. **Build-path leak.** pdfjs (4.10.38 and 6.4.299 alike) resolves module URLs
   with `new URL(".", import.meta.url)`. In Umi's non-ESM webpack output that
   `import.meta.url` is inlined as a `file:///…` build-machine path, which ends
   up in `dist/*/assets/*.async.js`. This is a **pre-existing defect** of the
   current pdfjs-4 integration (confirmed on the v4 build), not something v6
   introduced; the upgrade would not fix it and would add a broken worker on
   top.

The proper fix is a bundler-level task: emit the worker as a static asset
(copy `pdf.worker.min.mjs` into `apps/web/public/` or configure
`new Worker(new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url))`
in a webpack-compatible entry), point `GlobalWorkerOptions.workerSrc` at the
runtime base URL, keep `worker-src 'self' blob:` in the CSP, and add an
artifact guard that fails when absolute build paths appear in `dist`. That work
belongs with the Umi/webpack build configuration, not with a dependency bump.

Consequences:

* zod 4 is current and covered by typecheck/tests/build;
* pdfjs stays at 4.10.38 for this release; the known `file:///…` string in the
  PDF async chunk is recorded in `docs/dev/project-status.md` as a build defect
  to fix with the worker-asset work. It does not expose data (a local path in an
  inert code branch) but it must not survive into a release build.
* the next ADR-0010 items are dnd-kit, jbrowse major, TypeScript 7 and
  redis-py 8; the pdfjs upgrade rides with the worker-asset fix.
