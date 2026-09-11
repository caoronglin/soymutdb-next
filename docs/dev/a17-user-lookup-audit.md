# A-17 Admin command palette · user lookup decision

**Decision:** Do not add an Admin user-search endpoint at this time.

## Evidence

- The Admin frontend exposes no user-management route or workflow. Its authenticated identity model contains only the current operator username in `apps/admin/src/lib/auth-context.tsx` (lines 11–14, 71–82, 103–109).
- The Admin router does not register a users/roles route; its command palette can therefore not navigate to a legitimate user-management destination.
- The API registers no user-list or user-search endpoint. `UserListResponse` in `apps/api/app/schemas/auth.py` is schema-only; the API client has no corresponding method.
- The only existing user-read endpoint is `GET /api/v1/auth/me`, which is correctly limited to the authenticated caller. Repurposing it or adding a public `/users` lookup would broaden PII exposure without an approved workflow.
- The new palette's live lookup uses only the existing public, bounded gene catalogue endpoint `GET /api/v1/genes` through `searchGenes({ q, limit: 5 })`; it does not query user data.

## Revisit criteria

Create a user lookup only alongside an approved Admin user-management screen or another named, RBAC-protected workflow. It must be a dedicated `GET /api/v1/admin/users/search` endpoint, require authenticated administrator authorization, accept a bounded query and `limit <= 20`, return only the data required by the UI, and ship with 401/403/validation/pagination/PII-contract tests plus an API-client method. Do not implement a public user directory.
