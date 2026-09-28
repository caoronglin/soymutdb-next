/**
 * Portal TanStack Query client — React-baseline defaults (query-client parity).
 *
 * The React portal built its client with `createQueryClient()`: genomic
 * metadata is stable across a session, so it disabled refetch-on-focus, kept a
 * five-minute stale window, and never retried 4xx (they cannot succeed). The
 * Vue cutover constructed `new QueryClient()`, which restores TanStack's
 * defaults instead: staleTime 0, refetch-on-focus on, and three delayed retries
 * for every failure.
 *
 * That regression is user-visible: with the API unreachable, a query spends
 * seconds in `isPending` through the retry backoff, so the home page shows
 * "loading" instead of its error state, and every route re-fetches on tab
 * focus. This module restores the React policy as the single construction site.
 */
import { ApiError } from "@soymutdb/api-client";
import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60 * 1000,
        gcTime: 30 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // A 4xx will never succeed on retry; a 5xx or a network failure may.
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false;
          }
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: {
        retry: false,
      },
    },
  });
}
