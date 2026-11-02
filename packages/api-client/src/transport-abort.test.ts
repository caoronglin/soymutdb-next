/**
 * Transport abort contract.
 *
 * requestResponse() owns a single AbortController because the per-request
 * timeout has to stay independent of the caller's own cancellation. The bug
 * this file locks down is that the internal controller.signal used to
 * overwrite the caller's signal when it was forwarded to fetch, so an
 * already-cancelled caller still dispatched a request and an in-flight
 * caller cancel never reached the network.
 *
 * The fetch mocks below behave like the platform (honour init.signal and
 * reject with an AbortError) so the assertions describe observable transport
 * behaviour rather than internal wiring.
 */

import { ApiError, isTimeoutError, request, requestBlob, withRetry } from "./client";

type FetchMock = ReturnType<typeof vi.fn>;

/** A fetch mock that settles normally as long as the signal stays live. */
function respondWhenLive(body: unknown = { data: "ok" }): FetchMock {
    return vi.fn((_url: unknown, init?: RequestInit) => {
        return new Promise<Response>((resolve, reject) => {
            const signal = init?.signal;
            if (signal?.aborted) {
                reject(new DOMException("Aborted", "AbortError"));
                return;
            }
            signal?.addEventListener(
                "abort",
                () => reject(new DOMException("Aborted", "AbortError")),
                { once: true },
            );
            resolve(
                new Response(JSON.stringify(body), {
                    status: 200,
                    headers: { "content-type": "application/json" },
                }),
            );
        });
    });
}

/** A fetch mock that never settles on its own; only an abort ends it. */
function hang(): FetchMock {
    return vi.fn((_url: unknown, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
            const signal = init?.signal;
            signal?.addEventListener(
                "abort",
                () => reject(new DOMException("Aborted", "AbortError")),
                { once: true },
            );
        });
    });
}

/** The signal the transport actually handed to fetch. */
function fetchSignal(mock: FetchMock): AbortSignal | null {
    const init = mock.mock.calls[0]?.[1] as RequestInit | undefined;
    return (init?.signal as AbortSignal | undefined) ?? null;
}

describe("caller cancellation", () => {
    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    it("does not dispatch a request when the caller signal is already aborted", async () => {
        const fetchMock = respondWhenLive();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        caller.abort();

        const error = await request("/genes", { signal: caller.signal }).catch((e) => e);

        expect(fetchMock).not.toHaveBeenCalled();
        expect(error).toBeInstanceOf(DOMException);
        expect((error as Error).name).toBe("AbortError");
        // A cancellation must never be reported as a retryable timeout.
        expect(error).not.toBeInstanceOf(ApiError);
        expect(isTimeoutError(error)).toBe(false);
    });

    it("propagates a caller-supplied abort reason instead of replacing it", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(respondWhenLive() as never);

        const reason = new DOMException("superseded", "AbortError");
        const caller = new AbortController();
        caller.abort(reason);

        await expect(request("/genes", { signal: caller.signal })).rejects.toBe(reason);
    });

    it("aborts an in-flight fetch when the caller cancels mid-request", async () => {
        const fetchMock = hang();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        // The catch handler is attached in the same task as the request so an
        // abort below can never surface as an unhandled rejection.
        const settled = request("/slow", {
            signal: caller.signal,
            timeoutMs: 30_000,
        }).catch((e) => e);

        // The transport owns the signal handed to fetch, and the caller's
        // cancel must reach it.
        const dispatched = fetchSignal(fetchMock);
        expect(dispatched).toBeInstanceOf(AbortSignal);
        expect(dispatched?.aborted).toBe(false);

        caller.abort();

        const error = await settled;
        expect(dispatched?.aborted).toBe(true);
        expect((error as Error).name).toBe("AbortError");
        expect(isTimeoutError(error)).toBe(false);
    });

    it("applies the same cancellation to streamed downloads", async () => {
        const fetchMock = hang();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        const settled = requestBlob("/exports/archive.tar", {
            signal: caller.signal,
        }).catch((e) => e);
        caller.abort();

        expect(await settled).toMatchObject({ name: "AbortError" });
        expect(fetchSignal(fetchMock)?.aborted).toBe(true);
    });

    it("never retries a cancelled request, even when marked idempotent", async () => {
        const fetchMock = hang();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        const settled = withRetry(() => request("/slow", { signal: caller.signal }), {
            idempotent: true,
            maxRetries: 2,
        }).catch((e) => e);

        caller.abort();

        expect(await settled).toMatchObject({ name: "AbortError" });
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("does not retry a caller cancellation whose reason resembles a network error", async () => {
        vi.useFakeTimers();
        const fetchMock = hang();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);
        const caller = new AbortController();
        const reason = new TypeError("operator cancelled");
        const operation = vi.fn(() => request("/slow", { signal: caller.signal }));
        const settled = withRetry(operation, { idempotent: true, maxRetries: 2 }).catch((e) => e);
        caller.abort(reason);
        await vi.advanceTimersByTimeAsync(2000);
        expect(await settled).toBe(reason);
        expect(operation).toHaveBeenCalledTimes(1);
    });

    it("does not leave a timer or signal listener when JSON serialization fails", async () => {
        vi.useFakeTimers();
        const caller = new AbortController();
        const add = vi.spyOn(caller.signal, "addEventListener");
        const fetchMock = respondWhenLive();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);
        const json: Record<string, unknown> = {};
        json.self = json;
        await expect(request("/imports", { json, signal: caller.signal })).rejects.toBeInstanceOf(TypeError);
        expect(add).not.toHaveBeenCalled();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(vi.getTimerCount()).toBe(0);
    });

    it("resolves normally while the caller signal stays live", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(respondWhenLive() as never);

        const caller = new AbortController();

        await expect(request("/genes", { signal: caller.signal })).resolves.toEqual({
            data: "ok",
        });
        // Cancelling afterwards is the caller's business; the transport must
        // not have left the caller's signal aborted on its own.
        expect(caller.signal.aborted).toBe(false);
    });
});

describe("timeout behaviour is preserved alongside a caller signal", () => {
    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    it("still reports GATEWAY_TIMEOUT when the timeout fires first", async () => {
        vi.useFakeTimers();
        const fetchMock = hang();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        const settled = request("/slow", {
            signal: caller.signal,
            timeoutMs: 50,
        }).catch((e) => e);

        await vi.advanceTimersByTimeAsync(50);

        const error = await settled;
        expect(error).toBeInstanceOf(ApiError);
        expect(error).toMatchObject({ status: 408, code: "GATEWAY_TIMEOUT" });
        expect(isTimeoutError(error)).toBe(true);
        // The dispatched fetch is genuinely torn down, not merely abandoned.
        expect(fetchSignal(fetchMock)?.aborted).toBe(true);
    });

    it("keeps the timeout verdict when the caller cancels after the timeout", async () => {
        vi.useFakeTimers();
        vi.spyOn(globalThis, "fetch").mockImplementation(hang() as never);

        const caller = new AbortController();
        const settled = request("/slow", {
            signal: caller.signal,
            timeoutMs: 50,
        }).catch((e) => e);

        await vi.advanceTimersByTimeAsync(50);
        caller.abort();

        expect(await settled).toMatchObject({ code: "GATEWAY_TIMEOUT" });
    });

    it("prefers the cancellation when the caller cancels first", async () => {
        vi.useFakeTimers();
        vi.spyOn(globalThis, "fetch").mockImplementation(hang() as never);

        const caller = new AbortController();
        const settled = request("/slow", {
            signal: caller.signal,
            timeoutMs: 50,
        }).catch((e) => e);

        caller.abort();
        await vi.advanceTimersByTimeAsync(50);

        expect(await settled).toMatchObject({ name: "AbortError" });
    });

    it("keeps a non-abort transport failure as NETWORK_ERROR with a caller signal", async () => {
        vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

        const caller = new AbortController();

        await expect(request("/offline", { signal: caller.signal })).rejects.toMatchObject({
            status: 0,
            code: "NETWORK_ERROR",
        });
    });
});

describe("forwarded abort listener is cleaned up", () => {
    afterEach(() => {
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    /** Track add/remove pairs on the caller's signal. */
    function trackListeners(signal: AbortSignal) {
        return {
            added: vi.spyOn(signal, "addEventListener"),
            removed: vi.spyOn(signal, "removeEventListener"),
        };
    }

    it("removes the listener after a successful request", async () => {
        const fetchMock = respondWhenLive();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        const { added, removed } = trackListeners(caller.signal);

        await request("/genes", { signal: caller.signal });

        expect(added).toHaveBeenCalledTimes(1);
        expect(added.mock.calls[0]?.[0]).toBe("abort");
        expect(removed).toHaveBeenCalledTimes(1);
        expect(removed.mock.calls[0]?.[1]).toBe(added.mock.calls[0]?.[1]);

        // Without the removal, this late cancel would abort a controller the
        // transport no longer owns.
        const dispatched = fetchSignal(fetchMock);
        caller.abort();
        expect(dispatched?.aborted).toBe(false);
    });

    it("removes the listener after a cancelled request", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(hang() as never);

        const caller = new AbortController();
        const { added, removed } = trackListeners(caller.signal);

        const settled = request("/slow", { signal: caller.signal }).catch((e) => e);
        caller.abort();
        expect(await settled).toMatchObject({ name: "AbortError" });

        expect(added).toHaveBeenCalledTimes(1);
        expect(removed).toHaveBeenCalledTimes(1);
        expect(removed.mock.calls[0]?.[1]).toBe(added.mock.calls[0]?.[1]);
    });

    it("removes the listener after a timeout and after a network failure", async () => {
        vi.useFakeTimers();
        vi.spyOn(globalThis, "fetch").mockImplementation(hang() as never);

        const timedOut = new AbortController();
        const timedOutTrack = trackListeners(timedOut.signal);
        const timeoutSettled = request("/slow", {
            signal: timedOut.signal,
            timeoutMs: 50,
        }).catch((e) => e);
        await vi.advanceTimersByTimeAsync(50);
        expect(await timeoutSettled).toMatchObject({ code: "GATEWAY_TIMEOUT" });
        expect(timedOutTrack.added).toHaveBeenCalledTimes(1);
        expect(timedOutTrack.removed).toHaveBeenCalledTimes(1);
        expect(timedOutTrack.removed.mock.calls[0]?.[1]).toBe(
            timedOutTrack.added.mock.calls[0]?.[1],
        );

        vi.useRealTimers();
        vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new TypeError("Failed to fetch"));

        const failed = new AbortController();
        const failedTrack = trackListeners(failed.signal);
        const failedSettled = request("/offline", { signal: failed.signal }).catch((e) => e);
        expect(await failedSettled).toMatchObject({ code: "NETWORK_ERROR" });
        expect(failedTrack.added).toHaveBeenCalledTimes(1);
        expect(failedTrack.removed).toHaveBeenCalledTimes(1);
        expect(failedTrack.removed.mock.calls[0]?.[1]).toBe(
            failedTrack.added.mock.calls[0]?.[1],
        );
    });

    it("adds no listener at all when the signal is already aborted", async () => {
        const fetchMock = respondWhenLive();
        vi.spyOn(globalThis, "fetch").mockImplementation(fetchMock as never);

        const caller = new AbortController();
        const { added, removed } = trackListeners(caller.signal);
        caller.abort();

        await expect(request("/genes", { signal: caller.signal })).rejects.toBeDefined();
        expect(fetchMock).not.toHaveBeenCalled();
        expect(added).not.toHaveBeenCalled();
        expect(removed).not.toHaveBeenCalled();
    });

    it("does not leak listeners across many sequential requests", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation(respondWhenLive() as never);

        const caller = new AbortController();
        const { added, removed } = trackListeners(caller.signal);

        for (let i = 0; i < 25; i += 1) {
            await request("/genes/" + i, { signal: caller.signal });
        }

        expect(added).toHaveBeenCalledTimes(25);
        expect(removed).toHaveBeenCalledTimes(25);
    });
});
