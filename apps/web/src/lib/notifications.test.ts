// @vitest-environment jsdom
/**
 * Tests for the notifications composable.
 *
 * `@soymutdb/api-client` is mocked at the module boundary (the transport is
 * covered by the api-client suite); `useCurrentUser` is mocked so the test can
 * flip between anonymous and signed-in without a live session.
 */
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { computed, defineComponent, h, nextTick, ref, type Ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchUnreadCount,
  listNotifications,
  markNotificationsRead,
  type CurrentUser,
} from "@soymutdb/api-client";

import { notificationKeys, useNotifications } from "./notifications";

vi.mock("@soymutdb/api-client", () => ({
  fetchUnreadCount: vi.fn(),
  listNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
}));

// `CurrentUser` is a type-only export; the factory above cannot re-export it,
// so the import is erased at runtime and vi.mock only needs the functions.
const mockedUnread = vi.mocked(fetchUnreadCount);
const mockedList = vi.mocked(listNotifications);
const mockedMark = vi.mocked(markNotificationsRead);

const signedIn = ref(false);

vi.mock("./current-user", () => ({
  useCurrentUser: () => ({
    user: computed<CurrentUser | null>(() => (signedIn.value ? ({ id: "u1" } as CurrentUser) : null)),
    isResearcher: computed(() => signedIn.value),
    isLoading: computed(() => false),
  }),
}));

function item(id: string, readAt: string | null = null) {
  return {
    id,
    type: "blast_completed",
    title: `t-${id}`,
    body: "b",
    link: null,
    read_at: readAt,
    created_at: "2026-01-01T00:00:00Z",
  };
}

/** Mount a probe component that exposes the composable result. */
function setup(options: { autoList?: Ref<boolean>; limit?: number } = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let api!: ReturnType<typeof useNotifications>;
  const Probe = defineComponent({
    setup() {
      api = useNotifications({
        listEnabled: () => options.autoList?.value ?? true,
        ...(options.limit != null ? { limit: options.limit } : {}),
      });
      return () => h("div");
    },
  });
  const wrapper = mount(Probe, {
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  });
  return { wrapper, queryClient, api: () => api };
}

beforeEach(() => {
  signedIn.value = false;
  mockedUnread.mockReset().mockResolvedValue({ unread_count: 0 });
  mockedList.mockReset().mockResolvedValue({ items: [], total: 0, unread_count: 0 });
  mockedMark.mockReset().mockResolvedValue({ marked: 1 });
});

describe("useNotifications — anonymous", () => {
  it("issues no request while signed out", async () => {
    const { api } = setup();
    await flushPromises();
    await nextTick();

    expect(mockedUnread).not.toHaveBeenCalled();
    expect(mockedList).not.toHaveBeenCalled();
    expect(api().unreadCount.value).toBe(0);
    expect(api().items.value).toEqual([]);
  });

  it("starts querying once a user appears", async () => {
    const { api } = setup();
    await flushPromises();
    signedIn.value = true;
    await flushPromises();
    await nextTick();

    // Turning `enabled` on can race the observer's initial tick with the
    // refetch triggered by the same render, so only the lower bound is stable.
    expect(mockedUnread.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(mockedList).toHaveBeenCalledWith(20);
    expect(api().isError.value).toBe(false);
  });
});

describe("useNotifications — signed in", () => {
  it("polls the unread count every 30s and not faster", async () => {
    signedIn.value = true;
    const { queryClient } = setup();
    await flushPromises();

    const cached = queryClient.getQueryCache().find({ queryKey: notificationKeys.unreadCount() });
    expect(cached).toBeDefined();
    // The cache stores the resolved options; `refetchInterval`/`enabled` are
    // part of the public option surface but absent from the erased QueryOptions.
    const options = cached?.options as { refetchInterval?: number; enabled?: boolean };
    expect(options.refetchInterval).toBe(30_000);
    expect(options.enabled).toBe(true);
  });

  it("fetches the list with the requested limit and exposes items/counters", async () => {
    signedIn.value = true;
    mockedList.mockResolvedValue({
      items: [item("n1"), item("n2", "2026-01-01T00:00:00Z")],
      total: 5,
      unread_count: 1,
    });
    mockedUnread.mockResolvedValue({ unread_count: 1 });

    const { api } = setup({ limit: 20 });
    await flushPromises();
    await nextTick();

    expect(mockedList).toHaveBeenCalledWith(20);
    expect(api().items.value).toHaveLength(2);
    expect(api().unreadCount.value).toBe(1);
    expect(api().total.value).toBe(5);
  });

  it("does not fetch the list until the popover asks for it", async () => {
    signedIn.value = true;
    const open = ref(false);
    setup({ autoList: open });
    await flushPromises();
    expect(mockedList).not.toHaveBeenCalled();

    open.value = true;
    await flushPromises();
    expect(mockedList).toHaveBeenCalledTimes(1);
  });

  it("markRead posts the selector and invalidates both queries", async () => {
    signedIn.value = true;
    const { api, queryClient } = setup();
    await flushPromises();
    expect(mockedList).toHaveBeenCalledTimes(1);

    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    api().markRead({ ids: ["n1"] });
    await flushPromises();

    expect(mockedMark).toHaveBeenCalledWith({ ids: ["n1"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: notificationKeys.all });
    // The invalidation refetches the active unread query...
    expect(mockedUnread.mock.calls.length).toBeGreaterThan(1);
  });

  it("markRead({ all: true }) is forwarded verbatim", async () => {
    signedIn.value = true;
    const { api } = setup();
    await flushPromises();

    api().markRead({ all: true });
    await flushPromises();
    expect(mockedMark).toHaveBeenCalledWith({ all: true });
  });
});

describe("notificationKeys", () => {
  it("shares one stable root so a prefix invalidation reaches every read", () => {
    expect(notificationKeys.all).toEqual(["soymutdb", "notifications"]);
    expect(notificationKeys.unreadCount()).toEqual(["soymutdb", "notifications", "unread-count"]);
    expect(notificationKeys.list(20)).toEqual(["soymutdb", "notifications", "list", 20]);
    // No site/release segment: notifications are per-user, not per-biological-context.
    expect(notificationKeys.list(20)).not.toContain("external");
  });
});
