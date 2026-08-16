# Immutable Multi-Target Static Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate one verified immutable static artifact and safely publish it to an Admin-selected local, GitHub Pages, or Cloudflare Pages target.

**Architecture:** A release-aware builder consumes immutable page definitions and module data, writes a fresh static tree plus manifest, runs security/link/hydration smoke checks, then invokes one publication adapter. A target-scoped lease and monotonic publication ID prevent stale jobs from replacing newer releases.

**Tech Stack:** FastAPI, Celery, PostgreSQL, Vite/React SSG, S3-compatible storage, GitHub Actions API, Cloudflare Pages API, Playwright, pytest.

---

## File Structure

- Create `apps/api/app/models/publication.py` and migration `0017_static_publications.py`.
- Create `apps/api/app/services/publication_service.py` and `publication_targets.py`.
- Create `apps/worker/src/soymutdb_worker/tasks/static_publish.py`.
- Create `apps/worker/src/soymutdb_worker/publication/{base,local,github_pages,cloudflare_pages}.py`.
- Extend `apps/api/app/services/content_snapshot_service.py` with release-aware snapshots.
- Extend `apps/web/scripts/ssg-content.ts` and add `apps/web/scripts/build-manifest.ts`, `validate-static-tree.ts`.
- Modify `.github/workflows/pages.yml`, `scripts/test_deployment_workflows.py`, `apps/web/vite.config.ts`, and `packages/api-client/src/client.ts`.
- Add API/worker tests for publication state, adapters, and stale-job rejection.

### Task 1: Add Publication Records And Target Configuration

- [ ] Add model tests for target-scoped monotonically increasing IDs, statuses, manifest digest, remote ID, previous publication, and rollback relation.
- [ ] Add `PublicationTarget` enum values `local`, `github_pages`, `cloudflare_pages` and a `StaticPublication` model with `requested`, `building`, `validating`, `deploying`, `published`, `failed`, `rolled_back` states.
- [ ] Store only target identifiers in the database. Read credentials from environment/secret configuration and redact them from API responses and audit logs.
- [ ] Add Admin endpoints to list configured targets, select one target per request, inspect evidence, and request rollback.
- [ ] Run migration and publication model tests.

### Task 2: Make Snapshots Release-Aware

- [ ] Add tests showing snapshot cache keys differ by `release_id` and `page_definition_version`.
- [ ] Change snapshot APIs/services to require an explicit release for builds; mutable active-release aliases may remain only for interactive public API reads.
- [ ] Include `release_id`, page version, source checksums, and generated timestamp in every snapshot.
- [ ] Invalidate only the mutable alias after pointer changes; immutable keys never expire due to content mutation.
- [ ] Run `apps/api/tests/test_content_snapshot.py` and cache tests.

### Task 3: Generate A Complete Immutable Static Tree

- [ ] Add SSG tests for attribute escaping, slug validation, URL protocol allowlist, JSON script escaping, removed-page cleanup, and deterministic manifests.
- [ ] Fix direct `cover_url` and slug interpolation in `apps/web/scripts/ssg-content.ts`; all attributes use a single escape helper and all URLs use a single validator.
- [ ] Build into `dist/releases/<release-id>/<manifest-digest>/` from an empty directory.
- [ ] Generate `manifest.json` containing every relative path and SHA-256, plus release/page/application metadata.
- [ ] Add `validate-static-tree.ts` to reject missing routes, unexpected files, unsafe markup, broken internal links, and hash mismatches.
- [ ] Run focused SSG tests and `pnpm --filter @soymutdb/web build` with a fixture snapshot.

### Task 4: Add Lease And Stale-Job Protection

- [ ] Test two publications for the same target: the later request wins even if the earlier worker finishes last.
- [ ] Acquire a target advisory lock or locked target row only for allocation/final promotion, not while performing network I/O.
- [ ] Before promotion, compare `publication_id` with the target's latest requested ID; mark stale jobs superseded without calling promote.
- [ ] Keep the currently published pointer unchanged on build, validation, or deployment failure.
- [ ] Run publication concurrency tests with two sessions.

### Task 5: Implement The Local Adapter

- [ ] Define the adapter protocol:

```python
class PublicationAdapter(Protocol):
    def stage(self, publication: StaticPublication, artifact: Path) -> DeploymentRef: ...
    def verify(self, deployment: DeploymentRef) -> ValidationEvidence: ...
    def promote(self, deployment: DeploymentRef) -> str: ...
    def rollback(self, remote_id: str) -> str: ...
```

- [ ] The local adapter copies to a new version directory, fsyncs files, verifies the manifest, and atomically replaces a `current` symlink with `os.replace`.
- [ ] Add tests using `tmp_path` proving failed staging and verification leave the old symlink unchanged.

### Task 6: Implement GitHub Pages Adapter

- [ ] Update `.github/workflows/pages.yml` to accept `workflow_dispatch` inputs `publication_id`, `artifact_url`, and `manifest_digest`.
- [ ] Workflow downloads the immutable artifact, verifies its digest, runs static smoke checks, creates one complete `gh-pages` commit, then updates the ref.
- [ ] API adapter dispatches the workflow, polls the run/deployment, records run and commit IDs, and reports failure without changing the database public pointer.
- [ ] Extend `scripts/test_deployment_workflows.py` to assert required inputs, digest verification, and that ref update occurs after smoke checks.
- [ ] Replace the Pages-self API URL with a configured real HTTPS API origin; fail the production build if it is absent.

### Task 7: Implement Cloudflare Pages Adapter

- [ ] Add HTTP-client tests with mocked Cloudflare responses for upload, deployment polling, promotion, failure, and rollback.
- [ ] Upload the immutable artifact to the configured project, wait for a successful deployment, verify the deployment URL and manifest, then promote the deployment.
- [ ] Store account/project identifiers separately from the API token and never accept them from TSV/page definitions.
- [ ] Treat global CDN propagation as eventually consistent and record the confirmed deployment ID/time.

### Task 8: Pin Dynamic Requests To The Static Release

- [ ] Embed release metadata in generated HTML and bootstrap data.
- [ ] Add an `X-SoyMutDB-Release` header or explicit `release_id` query parameter through `packages/api-client`; public query endpoints validate and honor it.
- [ ] Test that a static page generated for release A continues querying A after active release changes to B.
- [ ] Keep BLAST and JBrowse 2 release selection explicit but outside generic page-builder rendering.

### Task 9: Smoke, Rollback, And Phase Verification

- [ ] Add Playwright smoke for home, Gene ID, location, JBrowse launcher, BLAST launcher, and static/dynamic release consistency.
- [ ] Add rollback tests for each adapter using previously recorded immutable artifact/remote IDs.
- [ ] Run: `apps/api/.venv/bin/python -m pytest apps/api/tests/test_content_snapshot.py apps/api/tests/test_release_service.py apps/api/tests/test_static_publications.py -q`
- [ ] Run: `apps/api/.venv/bin/python -m pytest apps/worker/tests/test_static_publish.py apps/worker/tests/test_publication_adapters.py -q`
- [ ] Run: `apps/api/.venv/bin/python scripts/test_deployment_workflows.py`
- [ ] Run: `pnpm --filter @soymutdb/web build`

Expected: each target receives the same manifest; a failed or stale publication never replaces the current version; rollback restores a previously verified artifact.
