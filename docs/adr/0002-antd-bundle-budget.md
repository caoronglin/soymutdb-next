# ADR 0002 — Ant Design 6 bundle budget adjustment

Status: accepted
Date: 2026-08-21

## Context

The React 19 + Ant Design 6 migration merges all AntD and `rc-*` runtime
modules into one deterministic `antd` chunk. Splitting table internals into a
separate chunk previously produced an ES module initialization cycle
(`antd-data -> antd -> antd-data`) and a production blank-screen risk.

The measured production gzip size for the merged chunk is approximately
302 KB after the complete public portal build. The original 280 KB budget
therefore fails even though the main entry remains at approximately 159 KB
gzip.

## Decision

Keep the acyclic single AntD chunk and raise the hard bundle budget to
320 KB gzip. The 22 KB margin covers the observed AntD 6.6.1 runtime while
retaining an explicit upper bound. Import optimization or per-route lazy
loading is a future task and must not be mixed with this migration.

## Consequences

- CI continues to fail if the AntD chunk exceeds 320 KB.
- The `antd-*.js` chunk remains a deliberate, deterministic build artifact.
- A later optimization wave can lower the budget again after verifying that
  splitting or route-level loading does not reintroduce a chunk cycle.
