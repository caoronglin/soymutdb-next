/**
 * TanStack Query client — sensible staleTime / gcTime defaults for a
 * genomic data portal where variant/gene lists change infrequently.
 */
import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
    return new QueryClient({
        defaultOptions: {
            queries: {
                // Genomic metadata is stable across a session; refetch on focus is wasteful.
                staleTime: 5 * 60 * 1000,
                gcTime: 30 * 60 * 1000,
                refetchOnWindowFocus: false,
                retry: (failureCount, error) => {
                    // Don't retry 4xx — they won't succeed.
                    if (error instanceof Error && "status" in error) {
                        const status = (error as { status: number }).status;
                        if (status >= 400 && status < 500) return false;
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
