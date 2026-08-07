/**
 * Lazy search worker client — wraps the Web Worker in a Promise-based API
 * and falls back to in-thread processing when Workers are unsupported.
 *
 * The worker is only instantiated on the first call to `filterSearchResults`
 * or `sortResults`, keeping the initial bundle and startup cost minimal.
 */

type MessageType = 'filter' | 'sort';
interface WorkerRequest {
    type: MessageType;
    requestId: number;
    data: unknown[];
    query?: string;
    fields?: string[];
    field?: string;
    direction?: 'asc' | 'desc';
}

interface PendingRequest {
    resolve: (value: unknown[]) => void;
    reject: (reason: unknown) => void;
}

let worker: Worker | null = null;
let pending: Map<number, PendingRequest> | null = null;
let nextId = 1;
let fallbackMode = false;

function ensureWorker(): Worker | null {
    if (fallbackMode) return null;
    if (worker) return worker;
    if (typeof Worker === 'undefined') {
        fallbackMode = true;
        return null;
    }
    try {
        // Vite's ?worker import returns a constructor for a module worker.
        // We use a dynamic import so the worker is only fetched when needed.
        const url = new URL('../workers/search.worker.ts', import.meta.url);
        worker = new Worker(url, { type: 'module' });
        pending = new Map();
        worker.addEventListener('message', (e: MessageEvent) => {
            if (!pending) return;
            const { requestId, results, error } = e.data;
            const p = pending.get(requestId);
            if (!p) return;
            pending.delete(requestId);
            if (error) p.reject(new Error(error));
            else p.resolve(results as unknown[]);
        });
        worker.addEventListener('error', (err) => {
            console.error('[search-worker] worker error, falling back to main thread:', err);
            fallbackMode = true;
            worker?.terminate();
            worker = null;
            // Reject all pending
            pending?.forEach((p) => p.reject(new Error('Worker crashed')));
            pending = null;
        });
        return worker;
    } catch (err) {
        console.warn('[search-worker] failed to start worker, using main-thread fallback:', err);
        fallbackMode = true;
        return null;
    }
}

function request<T>(msg: Omit<WorkerRequest, 'requestId'>): Promise<T[]> {
    const w = ensureWorker();
    if (!w) {
        // Fallback: do the work synchronously on the main thread.
        return Promise.resolve(fallbackProcess(msg) as T[]);
    }
    return new Promise<T[]>((resolve, reject) => {
        const id = nextId++;
        pending!.set(id, { resolve: resolve as (v: unknown[]) => void, reject });
        w.postMessage({ ...msg, requestId: id });
    });
}

function fallbackProcess(msg: Omit<WorkerRequest, 'requestId'>): unknown[] {
    if (msg.type === 'filter') {
        const q = (msg.query ?? '').toLowerCase().trim();
        if (!q) return msg.data;
        return msg.data.filter((item) => {
            if (msg.fields?.length && item && typeof item === 'object') {
                return msg.fields.some((f) =>
                    String((item as Record<string, unknown>)[f] ?? '').toLowerCase().includes(q),
                );
            }
            return String(item).toLowerCase().includes(q);
        });
    }
    if (msg.type === 'sort') {
        const dir = msg.direction === 'desc' ? -1 : 1;
        return [...msg.data].sort((a, b) => {
            const av = a && typeof a === 'object' ? (a as Record<string, unknown>)[msg.field!] : a;
            const bv = b && typeof b === 'object' ? (b as Record<string, unknown>)[msg.field!] : b;
            if (av == null && bv == null) return 0;
            if (av == null) return -1 * dir;
            if (bv == null) return 1 * dir;
            if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
            return String(av).localeCompare(String(bv)) * dir;
        });
    }
    return msg.data;
}

/** Filter an array of items by a fuzzy text query. Offloaded to a worker when available. */
export function filterSearchResults<T>(
    data: T[],
    query: string,
    fields?: (keyof T & string)[],
): Promise<T[]> {
    return request<T>({ type: 'filter', data: data as unknown[], query, fields: fields as string[] | undefined });
}

/** Sort an array. Offloaded to a worker when available. */
export function sortResults<T>(
    data: T[],
    field: keyof T & string,
    direction: 'asc' | 'desc' = 'asc',
): Promise<T[]> {
    return request<T>({ type: 'sort', data: data as unknown[], field, direction });
}

/** Clean up the worker (e.g. on app hot-reload). */
export function terminateSearchWorker(): void {
    worker?.terminate();
    worker = null;
    pending = null;
}
