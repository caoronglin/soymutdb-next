# Repository Guidelines

## Project Structure & Module Organization

This is a pnpm/Turbo monorepo. Frontend applications live in `apps/web` (public React/Vite SSG portal), `apps/admin`, and `apps/jbrowse`; Python services are in `apps/api`, `apps/worker`, and `apps/mcp-server`. Shared TypeScript packages are under `packages/`, with the API/worker job contract in `packages/jobs-py`. Python tests are in each service’s `tests/` directory; frontend unit tests are colocated near source; browser tests are in `e2e/tests`. Deployment, Docker, Nginx, ClickHouse, and monitoring assets are in `deploy/` and `infra/`. Read `docs/dev/` for architecture and deployment contracts.

## Build, Test, and Development Commands

Use Node.js 20+ and the pinned pnpm version (`pnpm@11.21.0`). Install dependencies with `pnpm install`.

```bash
pnpm dev:web                                      # public portal
pnpm dev:admin                                    # admin console
docker compose -f docker-compose.dev.yml up -d    # local data services
pnpm build                                        # Turbo build
pnpm lint && pnpm typecheck                       # JS quality gates
pnpm test                                         # workspace Vitest tests
cd apps/api && .venv/bin/python -m pytest tests -q
cd apps/worker && .venv/bin/python -m pytest tests -q
cd e2e && npx playwright test                      # Playwright smoke/E2E
```

## Coding Style & Naming Conventions

Follow `.editorconfig`: use two-space indentation for TypeScript, JSON, and YAML, and four spaces for Python. Use lowercase route/module filenames, `PascalCase` React components, and `camelCase` variables/functions. ESLint uses the root `eslint.config.js`; Python uses Ruff with a 100-character limit and import sorting (`I`). Keep API/OpenAPI contracts authoritative, route frontend data through service clients, and do not commit generated `dist/`, cache, or secret files.

## Testing Guidelines

Use Vitest for TypeScript unit tests, pytest for API/worker/shared-Python tests, and Playwright specs (`*.spec.ts`) for browser flows. Python tests follow `test_*.py` and `test_*` naming. Add regression coverage for behavior changes; no minimum coverage threshold is configured. Run the narrowest relevant suite locally, then the corresponding root quality gates before submitting.

## Commit & Pull Request Guidelines

Follow the history’s Conventional Commit pattern, for example `feat(features): add capability gate` or `fix(import): reject malformed uploads`. PRs should explain the change and validation performed, link an issue when applicable, include screenshots or recordings for UI changes, and call out migrations, environment variables, deployment changes, or security-sensitive behavior. Keep generated artifacts and unrelated refactors out of focused PRs.

## Security & Configuration Tips

Keep credentials in environment variables or deployment secrets; never commit `.env` files or tokens. Treat `infra/`, `deploy/`, database migrations, authentication, HTML sanitization, and publication/release logic as high-impact areas and include targeted tests plus deployment/health-check validation when changing them.
