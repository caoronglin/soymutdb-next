# SoyMutDB optimization intent

## Requested outcome
Improve SoyMutDB’s CMS publishing/import path, file preview, upload and chart performance, search/static delivery, and operational reliability. Keep a future local-first desktop bioinformatics toolbox isolated from this web monorepo.

## Scope and safety boundaries
- Secure editor-reviewed WeChat/X-MOL article previews; never automatically publish imported content.
- Preserve server-side rich-text sanitization, exact external-host allowlists, source provenance attestation, and public visibility rules.
- Make browser preview/download behavior conservative for binary or compressed inputs.
- Improve backend cache/outbox/deployment behavior only through focused, test-backed changes.
- Keep public API compatibility unless an explicit migration and client change are included.

## Non-goals
- No Tauri/Rust/Go integration into this monorepo.
- No Vue embedding, unsupported Ant Design ProComponents, browser credential scraping, general SSRF proxying, or broad worktree cleanup.

## Baseline read set
- `AGENTS.md` (repo conventions, test commands, security-sensitive areas)
- Existing news import, API client, preview, cache, chart, upload, and test files in the affected slices.
- Current dirty worktree is authoritative and must be preserved outside each slice.

## Impact and risk hints
This work touches public-content authorization, external fetch boundaries, caching, browser file handling, and deployment-adjacent code. Each slice requires focused regression evidence; container/runtime validation is not assumed when Docker is unavailable.
