# Isolated desktop toolbox spike — readiness audit

## Decision status
Conditionally ready for planning only. Any desktop spike must live in a separate repository, preferably with independently owned pnpm/Cargo workspaces, CI, capabilities, signing keys, and release policy. No Tauri, Rust application, Go binary, server authentication change, or web-monorepo runtime integration is authorized here.

Controlling authority: docs/design/desktop-toolbox-spike-boundary.md. The older docs/dev/desktop-client-plan.md proposes an in-monorepo desktop application and browser/server-auth changes; it is historical and conflicts with the current boundary.

## Recommended first spike
Run an external, network-disabled, unauthenticated local smoke workflow before any biology-facing feature:
1. Native open dialog selects a small harmless text or FASTA-shaped fixture.
2. Rust parses it as a bounded stream with fixed record and input-size limits.
3. A React 19 + TypeScript + Ant Design v6 UI displays summary-only data.
4. A cancellable job performs a deterministic non-biological transform, with bounded progress.
5. Native save dialog exports a small JSON/text report whose digest is verified.

Negative evidence must cover cancellation, malformed/oversized input, path-scope and symlink rejection, bounded events/results, and a packet/log test proving no network activity and no sequence-content logging. The later biology step may be a deterministic motif or restriction-site scan, but only with reviewed expected fixtures.

## Isolation rules
- Desktop IPC owns separate versioned DTOs, such as tool.run.v1, stable error codes, schema snapshots, and compatibility tests. It accepts validated options, never shell fragments, and returns summaries/pages/references rather than large payloads.
- File authority is the native dialog and restrictive Tauri capabilities. Canonicalize user-approved paths and reject scope escape and symlink surprises.
- Local mode defaults to no telemetry, upload, or sequence-content/path logging. Diagnostics redact identifiers where possible.
- A future remote API option must package a pinned API snapshot/types into the external repository. Do not import the private workspace as a runtime dependency.
- Authentication remains deferred. Existing browser cookie, CORS, CSRF-origin, and same-site behavior must not be weakened. Any later login needs a separately approved device/OAuth-style flow or an OS-keychain credential broker.

## Release readiness gap
The monorepo has useful contract, checksum, SBOM, and dependency-governance precedents, but no owned native desktop runner, installer build, signing/notarization, or install-smoke evidence. External CI must build/install/smoke Windows, macOS, and Linux artifacts, publish checksums/SBOM/provenance/notices, and establish signing-key custody and a release approver. Auto-update remains deferred.

## Human decisions before external implementation
1. Separate repository versus dedicated worktree, plus owner and security-response contact.
2. Initial supported OS/architecture and artifact formats.
3. Deterministic analysis choice and expected-results reviewer.
4. Signing/notarization key custody and release approval.
5. Local temporary-file/cache/crash-report retention policy.
6. Network-disabled local-only spike (recommended) versus a later pinned read-only endpoint list.

## Evidence sources
- docs/design/desktop-toolbox-spike-boundary.md
- package.json, pnpm-workspace.yaml, apps/web/package.json, apps/admin/package.json
- packages/api-client scripts for generation/check-contract and browser client/auth behavior
- apps/api browser-cookie and CSRF configuration
- .github/workflows/ci.yml, .github/workflows/baseline-validation.yml
- docs/ops/dependency-governance.md and production release/security documentation
