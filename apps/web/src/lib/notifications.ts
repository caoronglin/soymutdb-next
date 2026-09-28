/**
 * Notifications composable — the portal bell's data layer.
 *
 * Mirrors the React baseline `notification-bell.tsx`
 * (d3904c2105f34e5d74f3ae3a163d6b25f075bf64): the unread count polls every
 * 30s, the list is fetched lazily while the popover is open, and marking read
 * invalidates both.
 *
 * Two deliberate adaptations from the baseline:
 *
 *  1. `enabled: Boolean(user)` on BOTH queries. The baseline let the list run
 *     for anonymous visitors once the popover was open; gating it too keeps a
 *     signed-out page from issuing a guaranteed-401 request (and a stray
 *     logout-free refresh attempt) on every open.
 *  2. Query keys follow the repo-wide `@soymutdb/query-keys` prefix convention
 *     but are declared here — see `notificationKeys` below for why.
 *
 * Anonymous sessions degrade quietly: `useCurrentUser()` resolves 401 to
 * `null` (no error state, no redirect), both queries stay disabled, and the
 * bell renders nothing.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/vue-query";
import { computed, toValue, type ComputedRef } from "vue";

import {
  fetchUnreadCount,
  listNotifications,
  markNotificationsRead,
  type NotificationItem,
} from "@soymutdb/api-client";

import { useCurrentUser } from "./current-user";

/**
 * Cache keys for the bell.
 *
 * `packages/query-keys` has no `notifications` group, and it is owned by
 * another workstream, so the group is declared here rather than by editing that
 * package. The shape still follows the central convention: a stable
 * `soymutdb/notifications` root so an owner-level `invalidateQueries` prefix
 * reaches every notification read.
 *
 * No site-variant / release / assembly segment is added on purpose: the
 * endpoints return the *caller's* rows, and the caller identity is already the
 * sole cache scope in this app (the portal is one variant per deployment).
 */
export const notificationKeys = {
  all: ["soymutdb", "notifications"] as const,
  list: (limit: number) => [...notificationKeys.all, "list", limit] as const,
  unreadCount: () => [...notificationKeys.all, "unread-count"] as const,
} as const;

/** Poll cadence for the badge (React baseline parity: 30s). */
export const UNREAD_POLL_INTERVAL_MS = 30_000;

/** Same staleness window the baseline used for both reads. */
const STALE_TIME_MS = 10_000;

export interface UseNotificationsResult {
  /** Recent notifications, unread first (server-ordered). */
  items: ComputedRef<NotificationItem[]>;
  /** Badge value; 0 while loading or anonymous. */
  unreadCount: ComputedRef<number>;
  /** Full-set counters from the list response (not just the fetched page). */
  total: ComputedRef<number>;
  isLoading: ComputedRef<boolean>;
  isError: ComputedRef<boolean>;
  isMarkingRead: ComputedRef<boolean>;
  /** Mark one id (or everything when `all`) read and refresh both reads. */
  markRead: (selector?: { ids?: string[]; all?: boolean }) => void;
  /** Re-run both reads after a failure. */
  refetch: () => void;
}

/**
 * Invalidate the whole notification group — list and badge together.
 *
 * Exported so a component can reuse the exact prefix instead of re-spelling it.
 */
export function invalidateNotifications(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: notificationKeys.all });
}

export function useNotifications(options: {
  /** Fetch the list only while the popover is open; the badge always runs. */
  listEnabled: () => boolean;
  limit?: number;
}): UseNotificationsResult {
  const queryClient = useQueryClient();
  const { user } = useCurrentUser();
  const limit = options.limit ?? 20;

  const signedIn = computed<boolean>(() => toValue(user) !== null);

  const unreadQuery = useQuery({
    queryKey: notificationKeys.unreadCount(),
    queryFn: fetchUnreadCount,
    // Anonymous: no polling at all, and no request that can only 401.
    enabled: signedIn,
    refetchInterval: UNREAD_POLL_INTERVAL_MS,
    staleTime: STALE_TIME_MS,
  });

  const listQuery = useQuery({
    queryKey: notificationKeys.list(limit),
    queryFn: () => listNotifications(limit),
    enabled: () => signedIn.value && options.listEnabled(),
    staleTime: STALE_TIME_MS,
  });

  const markReadMutation = useMutation({
    mutationFn: (selector: { ids?: string[]; all?: boolean }) =>
      markNotificationsRead(selector),
    onSuccess: () => invalidateNotifications(queryClient),
  });

  return {
    items: computed(() => toValue(listQuery.data)?.items ?? []),
    unreadCount: computed(() => toValue(unreadQuery.data)?.unread_count ?? 0),
    total: computed(() => toValue(listQuery.data)?.total ?? 0),
    isLoading: computed(() => toValue(listQuery.isPending)),
    isError: computed(() => toValue(listQuery.isError)),
    isMarkingRead: computed(() => toValue(markReadMutation.isPending)),
    markRead: (selector = {}) => markReadMutation.mutate(selector),
    refetch: () => {
      void unreadQuery.refetch();
      void listQuery.refetch();
    },
  };
}

export type { CurrentUser } from "./current-user";
export type { NotificationItem, NotificationList } from "@soymutdb/api-client";
