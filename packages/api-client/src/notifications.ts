/**
 * Notifications API client (D2) — personal, per-user, authenticated reads.
 *
 * Three endpoints, all gated only by "authenticated" (`get_current_user`), so
 * every call goes through the coordinated `authRequest`/`http` channel: the
 * Bearer header is attached and an expired access token is refreshed once.
 *
 *   GET  /notifications?limit=20        -> NotificationListResponse
 *   GET  /notifications/unread-count    -> UnreadCountResponse
 *   POST /notifications/read            -> MarkReadResponse
 *
 * The payload shapes are owned by the generated OpenAPI contract
 * (`NotificationResponse` / `NotificationListResponse` / `UnreadCountResponse`
 * / `MarkReadResponse`) — never re-declared here.
 */
import { http } from "./auth";
import type { components } from "./generated/openapi";

/** One list entry. */
export type NotificationItem = components["schemas"]["NotificationResponse"];

/** List page plus the two counters (`total` is the full set, not the page). */
export type NotificationList = components["schemas"]["NotificationListResponse"];

/** Unread badge payload. */
export type NotificationUnreadCount = components["schemas"]["UnreadCountResponse"];

/** Result of a mark-read call: how many rows actually flipped. */
export type NotificationMarkReadResult = components["schemas"]["MarkReadResponse"];

/** Server default and the ceiling the API advertises (`ge=1, le=50`). */
export const NOTIFICATION_PAGE_LIMIT = 20;

/**
 * List the caller's notifications, unread first, newest first.
 *
 * `limit` is clamped client-side to the contract's `1..50` range so a bad
 * caller value never provokes a 422.
 */
export function listNotifications(limit: number = NOTIFICATION_PAGE_LIMIT): Promise<NotificationList> {
    const bounded = Math.min(50, Math.max(1, Math.trunc(limit)));
    return http.get<NotificationList>("/notifications", { params: { limit: bounded } });
}

/** Unread count for the header badge. */
export function fetchUnreadCount(): Promise<NotificationUnreadCount> {
    return http.get<NotificationUnreadCount>("/notifications/unread-count");
}

/**
 * Mark notifications read — either an explicit id subset or everything.
 *
 * The server rejects a payload that carries neither selector, so the caller
 * must pass at least one; `ids` is forwarded verbatim (ids are always scoped to
 * the caller server-side, so a foreign id is ignored rather than an error).
 */
export function markNotificationsRead(
    request: { ids?: string[]; all?: boolean } = {},
): Promise<NotificationMarkReadResult> {
    return http.post<NotificationMarkReadResult>("/notifications/read", {
        json: { ids: request.ids, all: request.all ?? false },
    });
}
