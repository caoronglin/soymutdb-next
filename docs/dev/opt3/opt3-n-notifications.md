# OPT3-N — Portal notification bell (React parity restore)

> **已归档（2026-10-01）**：优化 / 消融战役的逐轮记录（结论已并入现状与基线）。继任：docs/aegis/baseline/2026-10-01-react-only-baseline.md §5 的消融判定，以及仓库内现存的消融测试与守卫。仅供历史审计，**不得作为现状引用**；归档清单见 [`docs/ARCHIVE.md`](../../ARCHIVE.md)。

Status: implemented and verified.
Owner: frontend (Vue portal parity wave).
Baseline: `apps/web/src/components/notifications/notification-bell.tsx` @ `d3904c2105f34e5d74f3ae3a163d6b25f075bf64`.

## Why

The React portal rendered an in-app notification bell in the site header for
signed-in users; the Vue migration shipped no notification component and no
api-client wrapper at all. The backend endpoints were already complete and only
require "authenticated" (`get_current_user`, no RBAC gate):

- `GET  /api/v1/notifications?limit=20` → `{ items, total, unread_count }`
- `GET  /api/v1/notifications/unread-count` → `{ unread_count }`
- `POST /api/v1/notifications/read` body `{ ids?, all? }` → `{ marked }`

## What shipped

| Layer | File | Notes |
| --- | --- | --- |
| API client | `packages/api-client/src/notifications.ts` | `listNotifications`, `fetchUnreadCount`, `markNotificationsRead` over the coordinated `http` (authRequest) channel. Types come from the generated contract (`NotificationResponse`, …), never re-declared. |
| API client | `packages/api-client/src/notifications.test.ts` | URL/method/body/Bearer assertions, limit clamping, 401 propagation, single refresh retry. |
| api-client barrel | `packages/api-client/src/index.ts` | `export * from "./notifications"`. |
| Composable | `apps/web/src/lib/notifications.ts` | `useNotifications()`: list (`limit=20`, enabled only when the popover is open *and* a user exists), unread count (`refetchInterval: 30_000`, enabled only when signed in), mark-read mutation invalidating both. |
| Composable test | `apps/web/src/lib/notifications.test.ts` | Anonymous ⇒ no request; sign-in ⇒ request; 30s interval present; mark-read invalidates both keys. |
| Component | `apps/web/src/components/PortalNotificationBell.vue` | Signed-in-only bell + badge + overlay. |
| Component test | `apps/web/src/components/PortalNotificationBell.test.ts` | 15 jsdom tests. |
| Wiring | `apps/web/src/components/PortalHeader.vue` | Bell inserted in the right-hand icon cluster, immediately before the language switch. Existing test ids/nav/a11y untouched. |
| Test fixture | 4 `apps/web/src/views/Analyses*View.test.ts` | Their whole-module `vi.mock("@soymutdb/api-client")` factories needed the three notification functions, because `PortalHeader` now mounts the bell. |

## Deliberate adaptations vs the React baseline

1. **List `enabled` gate.** The baseline enabled the list on `!!user && open`;
   here it is `user && open` as well, but the unread count is `enabled: !!user`
   (baseline had that) and the list no longer fires for an open popover in an
   anonymous session.
2. **Relative time.** Baseline rendered `formatDate` (absolute "Jan 1, 2026");
   this renders `Intl.RelativeTimeFormat` ("3m ago"), per the parity brief.
3. **Query keys.** `packages/query-keys` has no `notifications` group, so
   `notificationKeys` is declared in `apps/web/src/lib/notifications.ts` under
   the same `soymutdb/...` root convention. No site-variant / release /
   assembly segment: notification rows are personal and per-user, so adding a
   cross-user cache scope would be wrong (and the caller identity is the only
   scope in a single-variant deployment).
4. **Markup/tokens.** The portal `@soymutdb/ui-vue` facade exports no
   Badge/Popover/List/Empty, so the structure and utility classes follow
   `apps/admin/src/components/AdminNotificationBell.vue` (same design tokens,
   custom overlay). Icons are inline SVG (no new dependency).
5. **a11y contract.** AntD's `Popover` supplied Escape/outside-click/focus for
   free in React; the Vue overlay implements them explicitly
   (`aria-expanded`, `role="menu"`, Escape closes + focus returns to the
   trigger, outside pointerdown closes).

## Anonymous degradation

`useCurrentUser()` already maps a 401 to `user = null` without an error state
and without a logout redirect. On top of that the bell returns nothing when
`user == null`, both queries stay `enabled: false`, and the 30s poll never
starts — so an anonymous page makes zero notification requests.

## i18n

Reuses the existing `notifications.*` namespace in `packages/i18n-core`
(coordinator-owned). The only key this work needs **added** is:

| key | zh | en |
| --- | --- | --- |
| `notifications.titleWithCount` | `消息通知（{{count}} 条未读）` | `Notifications ({{count}} unread)` |

Keys reused as-is: `notifications.title`, `notifications.empty`,
`notifications.markAllRead`, `notifications.blastCompleted`,
`notifications.blastFailed`, `notifications.analysisCompleted`,
`notifications.analysisFailed`, `notifications.gwasCompleted`,
`notifications.gwasFailed`, `common.loading`, `common.errorDescription`,
`common.retry`.

`type` → key mapping is `camelCase(type)` (e.g. `blast_completed` →
`notifications.blastCompleted`); unknown types fall back to the server-provided
`title`, then to the raw type string.

## Verification

- `pnpm --filter @soymutdb/api-client test` → 27 files / 146 tests, exit 0.
- `pnpm --filter @soymutdb/web test` → 50 files / 251 tests, exit 0
  (suite baseline at the start of this task was 46/201; +2 files here, the rest
  is a concurrent workstream — nothing was removed and every suite is green).
- `pnpm --filter @soymutdb/web exec vitest run src/lib/notifications.test.ts
  src/components/PortalNotificationBell.test.ts src/components/PortalHeader.test.ts`
  → 3 files / 31 tests, exit 0.
- `pnpm --filter @soymutdb/web typecheck` → exit 0.
- `pnpm --filter @soymutdb/web lint` → exit 0 (0 errors).
- `python3 scripts/check_visible_i18n.py` → `visible i18n OK`, exit 0.
- Playwright (`chromium`, dev server on 5173, `/auth/me` + notification routes
  faked): 21/21 checks passed — badge = N, unread-first ordering, mark-all POST
  `{all:true}`, per-row mark-read POST `{ids:[id]}` + link navigation, Escape +
  focus restore, empty state, error state, and anonymous bell-absent.
  Script: `.validation/verify-notifications-browser.cjs`.

### Browser caveat worth remembering

A Playwright route glob of `**/notifications**` also matches Vite's
`@fs/.../packages/api-client/src/notifications.ts` module request and answers
the ES module with JSON ("Expected a JavaScript-or-Wasm module script"). The
route must include `/api/v1`.
