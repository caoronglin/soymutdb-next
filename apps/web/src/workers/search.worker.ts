/**
 * Search Web Worker — offloads large result-set filtering from the main thread.
 *
 * Messages:
 *   { type: 'filter', data: T[], query: string, fields?: (keyof T)[] }
 *     → posts back { type: 'result', requestId, results: T[] }
 *
 *   { type: 'sort', data: T[], field: keyof T, direction?: 'asc'|'desc' }
 *     → posts back { type: 'result', requestId, results: T[] }
 */

/// <reference lib="webworker" />

type WorkerMessage =
    | { type: 'filter'; requestId?: string | number; data: unknown[]; query: string; fields?: string[] }
    | { type: 'sort'; requestId?: string | number; data: unknown[]; field: string; direction?: 'asc' | 'desc' };

function normalize(v: unknown): string {
    if (v == null) return '';
    if (typeof v === 'string') return v.toLowerCase();
    if (typeof v === 'number' || typeof v === 'boolean') return String(v);
    try {
        return JSON.stringify(v).toLowerCase();
    } catch {
        return '';
    }
}

function filterData(data: unknown[], query: string, fields?: string[]): unknown[] {
    if (!query) return data;
    const q = query.toLowerCase().trim();
    if (!q) return data;
    return data.filter((item) => {
        if (fields && fields.length && item && typeof item === 'object') {
            return fields.some((f) => normalize((item as Record<string, unknown>)[f]).includes(q));
        }
        // Search all stringifiable fields
        return normalize(item).includes(q);
    });
}

function sortData(data: unknown[], field: string, direction: 'asc' | 'desc' = 'asc'): unknown[] {
    const dir = direction === 'desc' ? -1 : 1;
    return [...data].sort((a, b) => {
        const av = a && typeof a === 'object' ? (a as Record<string, unknown>)[field] : a;
        const bv = b && typeof b === 'object' ? (b as Record<string, unknown>)[field] : b;
        if (av == null && bv == null) return 0;
        if (av == null) return -1 * dir;
        if (bv == null) return 1 * dir;
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
        return String(av).localeCompare(String(bv)) * dir;
    });
}

self.addEventListener('message', (e: MessageEvent<WorkerMessage>) => {
    const { data } = e;
    const requestId = data.requestId ?? null;

    try {
        if (data.type === 'filter') {
            const t0 = performance.now();
            const results = filterData(data.data, data.query, data.fields);
            self.postMessage({
                type: 'result',
                requestId,
                results,
                meta: { count: results.length, elapsedMs: performance.now() - t0 },
            });
            return;
        }
        if (data.type === 'sort') {
            const t0 = performance.now();
            const results = sortData(data.data, data.field, data.direction);
            self.postMessage({
                type: 'result',
                requestId,
                results,
                meta: { count: results.length, elapsedMs: performance.now() - t0 },
            });
            return;
        }
    } catch (err) {
        self.postMessage({
            type: 'error',
            requestId,
            error: err instanceof Error ? err.message : String(err),
        });
    }
});

// Per-file typed export keeps TypeScript happy when importing as a module.
export {};
