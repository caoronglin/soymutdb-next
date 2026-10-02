# Desktop Toolbox Spike Boundary

> **已归档（2026-10-01）**：2026-08 设计波次与旧基线快照。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md；门户布局以 `docs/superpowers/specs/2026-08-14-public-web-layout-alignment-design.md` 为准。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../ARCHIVE.md)。

**Status:** proposed future work; documentation-only boundary

## Decision

A local-first bioinformatics toolbox, if pursued, will be developed in a **separate future repository or dedicated worktree**. It is not part of the current SoyMutDB web portal, admin, API, deployment, or workspace. No integration is authorized until the decision criteria below are met.

The candidate stack is Tauri 2, Rust for local algorithms, React + TypeScript + the workspace-native Ant Design v6 for the UI. Vue compatibility is limited to framework-neutral contracts and design tokens; it does not imply that React components are reusable in Vue. Go is deferred and, if ever needed, must be an explicitly sandboxed external component rather than an MVP dependency.

## Scope and non-goals

**In scope:** user-selected local sequence files, offline local computation, optional read-only HTTPS access to a pinned SoyMutDB API contract, and OS-native packaging.

**Out of scope:** modifying `apps/web`, `apps/admin`, the API, OpenAPI contract, Docker/Compose, deployment configuration, or the pnpm/Rust workspace; bundling SoyMutDB datasets; admin capabilities; plugins; arbitrary command execution; browser-cookie authentication; automatic updates; and large-file IPC.

## Four-function MVP spike

The isolated spike must contain only these user-visible functions:

1. Open a user-selected FASTA file through a native dialog.
2. Parse it in Rust with bounded, streaming input and show a sequence summary.
3. Run one deterministic local sequence analysis (motif scan or restriction-site scan).
4. Export a small result report through a native save dialog.

Use job IDs, cancellation, bounded progress events, and summary/paged results. Do not move file content, whole genomes, or large result sets through Tauri IPC. The spike must demonstrate that local inputs are never sent over the network.

## Contract boundaries

| Boundary | Authority | Rule |
| --- | --- | --- |
| SoyMutDB remote API | FastAPI OpenAPI and generated `@soymutdb/api-client` types | Keep using the existing OpenAPI generation/check workflow; pin a tested API revision. |
| Desktop local IPC | Versioned Rust request/result DTOs and generated TypeScript bindings | Separate contract namespace, stable error codes, schema snapshots, and compatibility tests. |
| File access | Native dialog plus least-privilege Tauri capabilities | Accept only user-approved file tokens/paths; canonicalize paths and reject scope escape/symlink surprises. |

IPC commands must be versioned (for example, `tool.run.v1`), accept validated options rather than shell fragments, and return references, summaries, or pages instead of unbounded data.

## Privacy, security, and authentication

- Local-tool mode is offline-capable and must default to no telemetry, upload, or sequence-content logging. Redact paths and identifiers from diagnostics where possible.
- Use restrictive Tauri capabilities; do not broadly enable filesystem, process, shell, or network plugins. Apply size, CPU, memory, cancellation, and output limits.
- Any future external executable requires an allowlist, fixed argument construction, provenance/SBOM review, sandboxing, and license review.
- A configurable remote server is a trust boundary: require HTTPS by default, explicit server trust/configuration, API version/capability checks, and no privileged implicit requests.
- Authentication is deliberately outside the spike. Existing browser-oriented cookies, CORS, CSRF-origin checks, and same-site assumptions must not be weakened for desktop use. A later design must choose and test a dedicated device/OAuth-style flow or a narrowly scoped credential broker using OS keychain storage.

## Release and installer integrity

Build and test artifacts on native Windows, macOS, and Linux CI runners. Initial deliverables may include signed Windows installer/portable ZIP, signed and notarized macOS application archive, and a tested Linux AppImage and/or `.deb`. Publish checksums, SBOMs, build provenance, third-party notices, and platform signing evidence with each release.

Auto-update is deferred: it requires protected signing keys, signed metadata, rollback/revocation procedures, and an incident response owner. “Portable” is best-effort only; OS caches, quarantine metadata, keychains, logs, and temporary files can outlive the application directory.

## Validation matrix before integration

| Check | Evidence required | Status |
| --- | --- | --- |
| [ ] Isolation | Separate repository/worktree; no changes to SoyMutDB application, API, deployment, or workspace files | pending |
| [ ] Local privacy | Packet/log test proves FASTA content never leaves the machine in local mode | pending |
| [ ] IPC safety | Versioned schemas, invalid-input tests, cancellation, bounded event/result payloads | pending |
| [ ] File safety | Native approval, least-privilege scope, canonical-path/symlink and oversized-input tests | pending |
| [ ] Algorithm correctness | Deterministic fixtures and independently reviewed expected results | pending |
| [ ] Remote compatibility | Read-only call against a pinned OpenAPI snapshot; no server security-policy changes | pending |
| [ ] Authentication | Separate approved design and end-to-end security tests, if login is proposed | pending |
| [ ] Packaging | Native OS build/install/smoke tests for Windows, macOS, and Linux | pending |
| [ ] Release integrity | Signature/notarization where applicable, checksums, SBOM, provenance, notices, and key ownership | pending |
| [ ] Licensing | Review Rust/JS dependencies, bundled tools, fonts, reference data, and attribution obligations | pending |

## Integration decision

Integration with SoyMutDB may be considered only after every matrix item is evidenced, the desktop compatibility surface is explicitly documented, security and licensing review approve the artifacts, and maintainers approve a narrowly scoped integration ADR. Until then, the deployed web portal remains the product baseline.
