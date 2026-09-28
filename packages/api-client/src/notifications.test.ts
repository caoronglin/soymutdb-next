/**
 * Tests for the notifications API functions.
 *
 * Asserts URL, method, query/body shape and Bearer attachment, plus the 401
 * propagation contract that lets the portal degrade to "anonymous" without a
 * redirect. `fetch` is mocked at the transport boundary.
 */
import { clearAuth, setAuthTokens } from "./client";
import {
  NOTIFICATION_PAGE_LIMIT,
  fetchUnreadCount,
  listNotifications,
  markNotificationsRead,
} from "./notifications";

const API_BASE = "/api/v1";

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lastFetchCall(): [string, RequestInit] {
  const calls = vi.mocked(fetch).mock.calls;
  return calls[calls.length - 1] as unknown as [string, RequestInit];
}

beforeEach(() => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse({}));
  setAuthTokens("test-token");
});

afterEach(() => {
  vi.restoreAllMocks();
  clearAuth();
});

describe("listNotifications", () => {
  it("GETs /notifications?limit=20 with Bearer and parses the page", async () => {
    const page = {
      items: [
        {
          id: "n1",
          type: "blast_completed",
          title: "BLAST finished",
          body: "Job done",
          link: "/analyses/1",
          read_at: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      total: 1,
      unread_count: 1,
    };
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse(page));

    const result = await listNotifications();

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${API_BASE}/notifications?limit=${NOTIFICATION_PAGE_LIMIT}`);
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(result).toEqual(page);
  });

  it("clamps an out-of-range limit into the contract's 1..50 window", async () => {
    await listNotifications(0);
    expect(lastFetchCall()[0]).toBe(`${API_BASE}/notifications?limit=1`);

    await listNotifications(500);
    expect(lastFetchCall()[0]).toBe(`${API_BASE}/notifications?limit=50`);
  });
});

describe("fetchUnreadCount", () => {
  it("GETs /notifications/unread-count with Bearer and parses the count", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ unread_count: 7 }));

    const result = await fetchUnreadCount();

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${API_BASE}/notifications/unread-count`);
    expect(init.method).toBe("GET");
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(result).toEqual({ unread_count: 7 });
  });
});

describe("markNotificationsRead", () => {
  it("POSTs ids to /notifications/read with Bearer and parses marked", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(jsonResponse({ marked: 1 }));

    const result = await markNotificationsRead({ ids: ["n1"] });

    const [url, init] = lastFetchCall();
    expect(url).toBe(`${API_BASE}/notifications/read`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ ids: ["n1"], all: false });
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-token");
    expect(result).toEqual({ marked: 1 });
  });

  it("defaults `all` to false and posts an all-selector when asked", async () => {
    await markNotificationsRead({});
    expect(JSON.parse(lastFetchCall()[1].body as string)).toEqual({
      ids: undefined,
      all: false,
    });

    await markNotificationsRead({ all: true });
    expect(JSON.parse(lastFetchCall()[1].body as string)).toEqual({
      ids: undefined,
      all: true,
    });
  });
});

describe("401 handling", () => {
  it("propagates the 401 when the refresh also fails (no redirect, no throw-away retry loop)", async () => {
    // First call: the read -> 401. Second: the refresh -> 401. Third: none
    // (refresh failed, so the read is not replayed).
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "no refresh" }, 401));

    await expect(fetchUnreadCount()).rejects.toMatchObject({ status: 401 });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  });

  it("retries the read once after a successful refresh", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "fresh" }))
      .mockResolvedValueOnce(jsonResponse({ unread_count: 3 }));

    await expect(fetchUnreadCount()).resolves.toEqual({ unread_count: 3 });
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3);
    expect(lastFetchCall()[0]).toBe(`${API_BASE}/notifications/unread-count`);
    expect(new Headers(lastFetchCall()[1].headers).get("Authorization")).toBe("Bearer fresh");
  });
});
