# ADR-0010: hold the remaining frontend/runtime major upgrades in this release

Status: accepted (2026-10-18); **partially superseded** — vitest 5 + vite 8
were taken by ADR-0011, zod 4 and pdfjs 6 were taken by ADR-0013/ADR-0014
(pdfjs after its worker pipeline was fixed), and i18next 26 + react-i18next 17
were taken by ADR-0012; ADR-0015 takes the dnd-kit sortable row and records the
upstream blockers that keep TypeScript 7, jbrowse major and redis-py 8 held.
Context: the platform recently took the safe upgrade lane — React/React-DOM
19.3.0 → 19.3.1, `@tanstack/react-query` 5.104.x, tiptap 3.32.0, turbo 2.11.8,
eslint 10.13.0, FastAPI 0.143.3, SQLAlchemy 2.1.5, httpx2 — and the tree is
green on every gate (API 2447, worker 659, scripts 517, workspace 36/36, knip
exit 0, artifact/a11y gates, Playwright public/internal/primer suites). The
remaining outdated dependencies are all **major** jumps that change build,
test or runtime contracts, not patch drift:

| Package | Current | Next major | Why holding |
| --- | --- | --- | --- |
| `typescript` | 5.9.3 | 7.x (native compiler preview) | Not a drop-in: changes build/emit and type-checking behaviour across every workspace package; must wait for a stable release plus tsc API support in Umi's toolchain. |
| `vite` | 6.4.3 | 8.x | Production web/admin builds run through Umi (webpack); Vite only drives dev server/test tooling. Upgrading it alone buys no user-facing value while `@umijs/max` pins its own peer graph. |
| `vitest` | 3.2.7 | 5.x | Major changes to config resolution, pool/fork defaults and jsdom integration. This is the substrate for 1071 unit tests; migrating it must be its own change with the whole suite green before and after. |
| `zod` | 3.24.x | 4.x | Breaking schema API (`error`/`message`, coercion, issue paths) used by form validation; a silent runtime difference here would validate the wrong thing. |
| `pdfjs-dist` | 4.10.x | 6.x | Major worker/asset layout and API changes; the viewer is pinned by CSP `worker-src`/`script-src` and by the file-viewer's lazy chunk contract. Requires an artifact-level verification pass, not a package bump. |
| `i18next` / `react-i18next` | 24.2.x / 15.4.x | 26.x / 17.x | Breaking init/type options across three apps plus `packages/i18n-core`; the locale-key contract checks (parity, purity, visible-i18n) are the acceptance gate and must be re-baselined deliberately. |
| `@dnd-kit/core` | 6.3.x | 10.x | Admin drag-and-drop (imports, field ordering) is one of the few bespoke interactive surfaces; the major changes event/measuring APIs. Needs a browser-driven test first. |
| `@jbrowse/react-linear-genome-view` | 2.17.x | next major | jbrowse is a separate build/deploy boundary; its artifact build already cannot run in the DSH sandbox (esbuild process quota), so its upgrade must be validated in CI, not here. |
| `redis` (Python client) | 6.4.0 | 8.x | Shared by API cache and Celery broker; the major changes connection/retry semantics that the fail-closed rate limiter and cache degradation paths depend on. |

Decision: hold these majors for this release. The project ships patch/minor
updates only; every held package keeps its current pin and the platform contract
tests continue to assert that pin.

Consequences:

* no user-facing regression risk from a build-system rewrite in a release whose
  remaining work is verification and cutover readiness;
* the upgrade work is not lost — each row above names its acceptance gate, so a
  future upgrade PR follows the same evidence standard as the patch wave;
* the workspace must keep the pins truthful: `scripts/test_platform_delivery_contracts.py`
  and the lockfiles are the source of truth, and a dependency out of that table
  without a new ADR is a review finding;
* TypeScript 7 in particular may arrive with the native compiler becoming the
  default `tsc`; the migration will need a dedicated branch that keeps
  `pnpm typecheck` green across all workspaces before any runtime change lands.

Follow-up (ordered by risk, each its own PR with full gates):
1. `vitest` 5 + `vite` 8 together (same tooling graph).
2. `i18next`/`react-i18next` with the locale contract suites.
3. `zod` 4 and `pdfjs-dist` 6 (forms and file viewer respectively).
4. `@dnd-kit/core` and the jbrowse major, both browser-verified.
5. `typescript` 7 and `redis` 8 last.
