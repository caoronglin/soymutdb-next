# ADR-0007: Supported deployment architectures

Status: Accepted

Date: 2026-09-20

Decision source: Gate A (`docs/ops/gate-a-decision-brief-2026-09-20.md`).

## Context

The repo builds amd64/arm64 images and validates on kind/kubernetes; the Rust
evaluation flagged arm64 toolchain cost, and ClickHouse cluster topology is still
unconfirmed (RUNTIME_ONLY, pending a ClickHouse instance). Dual-architecture
builds and scans are already a CI critical-path cost. Evidence:
`docs/ops/phase-0-fact-baseline-2026-09-20.md` §CONTEXT/§CH.

## Decision

Define a per-service architecture matrix rather than "everything dual-arch":

- **Stateless / frontend artifacts** (web, admin, jbrowse, api image): amd64 +
  arm64 first-class.
- **Heavy stateful services** (PostgreSQL, ClickHouse, worker compute): amd64 is
  the primary target; arm64 only where a concrete need is shown.
- **ClickHouse topology**: single-node for dev/validation; cluster topology is a
  separate, evidence-gated decision (see ADR-DATA-02 implementation).

This matrix is the input to CI matrix scoping and to any future native-code
target (e.g., a Rust ingest kernel's required build targets).

## Consequences

- CI can scope arm64 + kind to stateless/frontend and to `main`/scheduled runs,
  reducing PR critical path without dropping coverage.
- Phase 5 capacity targets and Phase R (optional Rust PoC) inherit this arch
  matrix.
- Rejected: full-stack dual-arch as a blanket rule (cost already shown to be a
  bottleneck).
