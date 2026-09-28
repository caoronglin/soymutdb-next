/**
 * Admin TanStack Query client — React-baseline defaults (query-client parity).
 *
 * The React console built its client with one explicit policy: admin metadata is
 * stable for the length of a session, so it disabled refetch-on-focus, kept a
 * 30s stale window, and retried a failure exactly once. The Vue cutover
 * constructed `new QueryClient()`, which restores TanStack's own defaults
 * instead: staleTime 0, refetch-on-focus on, and three delayed retries for every
 * error.
 *
 * That regression is user-visible: with the API unreachable, a query spends
 * seconds in `isPending` through the retry backoff, so a page shows "loading"
 * instead of its error state, and every route re-fetches when the tab regains
 * focus. This module is the single construction site so the policy cannot drift
 * per view again.
 */
import { ApiError } from "@soymutdb/api-client";
import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30 * 1000,
        gcTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // A 4xx cannot succeed on retry (the request was rejected, not
          // unlucky); a 5xx or a transport failure may. One retry, as in the
          // React baseline.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 1;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}
