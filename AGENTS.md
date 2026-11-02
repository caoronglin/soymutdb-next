# Repository Guidelines

## Project Structure & Module Organization

This is a pnpm/Turbo monorepo. Frontend applications live in `apps/web` (public React/Vite SSG portal), `apps/admin`, and `apps/jbrowse`; Python services are in `apps/api`, `apps/worker`, and `apps/mcp-server`. Shared TypeScript packages are under `packages/`, with the API/worker job contract in `packages/jobs-py`. Python tests are in each service’s `tests/` directory; frontend unit tests are colocated near source; browser tests are in `e2e/tests`. Deployment, Docker, Nginx, ClickHouse, and monitoring assets are in `deploy/` and `infra/`. Read `docs/dev/` for architecture and deployment contracts.

## Product and Data Invariants

SoyMutDB is a bioinformatics database first. Product work must preserve a database-oriented experience: prominent identifier search, filterable and paginated result sets, entity detail pages, stable links, and visible assembly, release, and provenance context. Marketing or editorial content may support these workflows but must not displace them. The normative behavior and test matrix are in `docs/dev/database-core-contract.md`.

PostgreSQL is authoritative for identities, relationships, releases, permissions, and workflow state. ClickHouse is an analytical projection for bulk variant facts; MinIO stores objects; Redis is disposable cache/broker state. Do not introduce another authoritative store or use SQLite for the production/full-development path.

Treat biological identity and genomic coordinates as explicit contracts:

- A mutant has a stable, unique `public_id` for public URLs and responses, and a separate private `internal_id`/persistence key. A storage column may remain named `id`, but public contracts must never expose or accept that key as the mutant's public identity. Do not derive one identifier from the other.
- New or changed API/client/search contracts must use audience-explicit names such as `public_id` and `internal_id`; do not add another ambiguous bare `id`. Published mutants require a non-null `public_id`; reassignment requires an audited migration and redirect/alias policy.
- External-site APIs and artifacts may search and return only released public records and public identifiers. An anonymous lookup by internal identifier must disclose neither the record nor whether it exists. Internal-identifier search requires authenticated internal authorization enforced by the API, not just hidden UI controls.
- Genes, variants, coordinates, aliases, and cross-version mappings are assembly-scoped. v4 and v5 are distinct coordinate/identifier namespaces, not interchangeable labels. Search requests and results must carry assembly identity/version; unscoped ambiguous matches must be returned as clearly labelled per-assembly results or rejected for disambiguation, never silently collapsed.
- Cross-version gene matches must come from an explicit, provenance-bearing alias/crosswalk relation. Never infer v4↔v5 equivalence from string similarity or coordinate coincidence.

The `external` and `internal` site variants are separate build/deployment security boundaries. Select the variant explicitly at build/runtime; never infer it from host, IP, cookies, or user agent. Keep artifacts, origins, CORS allowlists, service-worker namespaces, and caches separate. Cache keys for biological search must include site variant, release, assembly, query, and filters; internal responses are private and must not enter shared caches. Do not confuse site variants with federated search sources such as NCBI or UniProt.

## Delivery Pipeline

`.cnb.yml` is the authoritative delivery pipeline. The GitHub workflows under
`.github/workflows` are a mirror and must not grow logic of their own: every job
body calls a checked-in script so both providers execute identical bytes.

```
scripts/ci-job-steps.sh               job bodies (list / run <job>)
scripts/verify-frontend-artifacts.sh  frontend gates
scripts/verify-backend-tests.sh       API + worker gates
scripts/build-release-image.sh        build + runtime smoke + scan + SBOM + export
scripts/release-contract.golden.sh    merge + sign + attest + publish verified images
scripts/build-pages-artifact.sh       static site artifact
scripts/verify-pages-artifact.sh      publication-time byte verification
scripts/smoke.sh                      unified smoke layers
```

Rules enforced by `scripts/test_ci_job_contracts.py`:

- Adding build/test/scan logic to a workflow instead of a shared script fails.
- Image verification and image publication stay separate pipelines; the verifier
  holds no registry credentials and the publisher never rebuilds.
- Pull-request pipelines never hold release credentials.
- Node/pnpm/Python pins must agree across `.nvmrc`, `package.json`, `.cnb.yml`
  and the workflows.

Smoke testing: `bash scripts/smoke.sh [--profile contracts|static|runtime|e2e|images]`.
A layer whose prerequisites are missing is reported `SKIPPED` with the reason and
never counted as a pass.

See `docs/ops/ci-cd.md` (architecture and release flow) and
`docs/dev/pipeline-migration.md` (migration mapping and evidence).

## Build, Test, and Development Commands

Use Node.js 26 (`.nvmrc` pins 26.10.0 and `package.json` permits only `>=26 <27`), Python 3.14+, and the pinned pnpm version (`pnpm@12.5.1`). Install dependencies with `pnpm install`.

```bash
pnpm dev:web                                      # public portal
pnpm dev:admin                                    # admin console
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile core up --build  # Docker dev stack
pnpm build                                        # Turbo build
pnpm lint && pnpm typecheck                       # JS quality gates
pnpm test                                         # workspace Vitest tests
cd apps/api && .venv/bin/python -m pytest tests -q
cd apps/worker && .venv/bin/python -m pytest tests -q
python3 -m unittest scripts.test_site_artifact_isolation -v
cd e2e && npx playwright test                      # Playwright smoke/E2E
```

## Coding Style & Naming Conventions

Follow `.editorconfig`: use two-space indentation for TypeScript, JSON, and YAML, and four spaces for Python. Use lowercase route/module filenames, `PascalCase` React components, and `camelCase` variables/functions. ESLint uses the root `eslint.config.js`; Python uses Ruff with a 100-character limit and import sorting (`I`). Keep API/OpenAPI contracts authoritative, route frontend data through service clients, and do not commit generated `dist/`, cache, or secret files.

## Testing Guidelines

Use Vitest for TypeScript unit tests, pytest for API/worker/shared-Python tests, and Playwright specs (`*.spec.ts`) for browser flows. Python tests follow `test_*.py` and `test_*` naming. Add regression coverage for behavior changes; no minimum coverage threshold is configured. Run the narrowest relevant suite locally, then the corresponding root quality gates before submitting.

Changes to mutant identity, search, assemblies, releases, visibility, caching, or site variants must follow `docs/dev/database-core-contract.md`. At minimum, cover the external/internal × public/internal identifier × v4/v5 matrix at the appropriate unit, PostgreSQL integration, frontend, artifact, and E2E layers. Every public-boundary change requires a negative leakage test asserting that internal identifiers and unreleased records are absent from response bodies, URLs, client-visible logs, and `dist/external`.

Database migrations require upgrade/downgrade coverage and a PostgreSQL-backed test; API shape changes require OpenAPI/client contract validation. Dual-site behavior is not complete until both artifacts build and their access/cache policies are verified. Skipped or xfailed privacy, identity, or assembly-isolation scenarios do not satisfy the merge gate. Record exact commands and pass/fail counts in the PR.

## Toolchain Pins

| Component | Version | Declared in |
| --- | --- | --- |
| Node | 26.10.0 | `.nvmrc`, `.node-version`, `package.json`, `.cnb.yml` |
| pnpm | 12.5.1 | `package.json`, `.cnb.yml` |
| Python | 3.14 | `apps/*/pyproject.toml`, `.cnb.yml` |
| uv | 0.11.33 | Dockerfiles, governance pipeline |

## Commit & Pull Request Guidelines

Follow the history’s Conventional Commit pattern, for example `feat(features): add capability gate` or `fix(import): reject malformed uploads`. PRs should explain the change and validation performed, link an issue when applicable, include screenshots or recordings for UI changes, and call out migrations, environment variables, deployment changes, or security-sensitive behavior. Keep generated artifacts and unrelated refactors out of focused PRs.

## Security & Configuration Tips

Keep credentials in environment variables or deployment secrets; never commit `.env` files or tokens. Treat `infra/`, `deploy/`, database migrations, authentication, HTML sanitization, and publication/release logic as high-impact areas and include targeted tests plus deployment/health-check validation when changing them.
