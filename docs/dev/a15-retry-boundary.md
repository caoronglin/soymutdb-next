# A-15 Retry Safety Boundary

## Scope

`packages/api-client` has two distinct retry surfaces. They must not be conflated.

## Coordinated authenticated transport

`authRequest` and `authRequestRaw` own refresh-on-401 and transient retry behavior. They automatically retry/replay exactly once only for methods the API contract treats as idempotent:

```text
GET, HEAD, OPTIONS, PUT, DELETE
```

They invoke:

```ts
withRetry(exec, { idempotent: true, maxRetries: 1 })
```

`POST` and `PATCH` run once. A token refresh failure or a 401 from either is returned to the caller; neither request is replayed automatically.

## Public `withRetry` compatibility API

`withRetry` remains a generic exported helper for existing callers. Its numeric form remains backward-compatible:

```ts
withRetry(operation, 1)
```

New transport code must use the explicit declaration form instead:

```ts
withRetry(operation, { idempotent: true, maxRetries: 1 })
```

The generic helper has no request method or endpoint context. Therefore it must not be introduced around mutations unless the caller has independently proven replay safety through a server-side idempotency contract (for example, a stable idempotency key and duplicate-safe handling).

## Rules for new callers

1. Prefer `authRequest` / `authApi` helpers for authenticated HTTP.
2. Do not wrap `POST` or `PATCH` with `withRetry` merely because a payload looks deterministic.
3. For `PUT` / `DELETE`, use coordinated transport so the method-safe replay policy remains centralized.
4. Add an explicit API contract and targeted tests before treating a new operation as replay-safe.
5. Never change the default public helper semantics without a migration for external callers.

## Regression evidence

- `packages/api-client/src/auth.test.ts`: a `PUT` replays once after refresh, while a `POST` is sent once and retains its original 401.
- `packages/api-client/src/client.test.ts`: explicit idempotent options and legacy numeric retry calls both remain supported.
