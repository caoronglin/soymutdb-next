// @vitest-environment jsdom
/**
 * Tests for PortalNotificationBell.
 *
 * `@soymutdb/api-client` is mocked at the module boundary (transport covered
 * separately) and `useCurrentUser` is mocked so a test can be anonymous or
 * signed in without a live session.
 */
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { computed, nextTick, ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchUnreadCount,
  listNotifications,
  markNotificationsRead,
  type CurrentUser,
  type NotificationItem,
} from "@soymutdb/api-client";

import PortalNotificationBell from "./PortalNotificationBell.vue";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
}));

vi.mock("@soymutdb/api-client", () => ({
  fetchUnreadCount: vi.fn(),
  listNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
}));

const signedIn = ref(false);

vi.mock("../lib/current-user", () => ({
  useCurrentUser: () => ({
    user: computed<CurrentUser | null>(() => (signedIn.value ? ({ id: "u1" } as CurrentUser) : null)),
    isResearcher: computed(() => signedIn.value),
    isLoading: computed(() => false),
  }),
}));

const mockedUnread = vi.mocked(fetchUnreadCount);
const mockedList = vi.mocked(listNotifications);
const mockedMark = vi.mocked(markNotificationsRead);

function item(over: Partial<NotificationItem> & { id: string }): NotificationItem {
  return {
    type: "blast_completed",
    title: `title-${over.id}`,
    body: `body-${over.id}`,
    link: null,
    read_at: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function mountBell(): VueWrapper {
  return mount(PortalNotificationBell, {
    attachTo: document.body,
    global: {
      plugins: [
        [VueQueryPlugin, { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }],
      ],
    },
  });
}

const toggle = (w: VueWrapper) => w.get('[data-testid="portal-notifications-toggle"]');

async function openPanel(wrapper: VueWrapper) {
  await toggle(wrapper).trigger("click");
  await flushPromises();
  await nextTick();
}

beforeEach(() => {
  document.body.innerHTML = "";
  signedIn.value = false;
  mockedUnread.mockReset().mockResolvedValue({ unread_count: 0 });
  mockedList.mockReset();
  mockedList.mockResolvedValue({ items: [], total: 0, unread_count: 0 });
  mockedMark.mockReset().mockResolvedValue({ marked: 1 });
});

describe("PortalNotificationBell — anonymous", () => {
  it("renders nothing at all", async () => {
    const wrapper = mountBell();
    await flushPromises();

    expect(wrapper.find('[data-testid="portal-notifications-toggle"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(false);
    expect(mockedUnread).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("renders the bell once a user appears", async () => {
    const wrapper = mountBell();
    await flushPromises();
    signedIn.value = true;
    await flushPromises();

    expect(wrapper.find('[data-testid="portal-notifications-toggle"]').exists()).toBe(true);
    wrapper.unmount();
  });
});

describe("PortalNotificationBell — signed in", () => {
  it("shows the unread badge and hides it at zero", async () => {
    signedIn.value = true;
    mockedUnread.mockResolvedValue({ unread_count: 4 });
    const wrapper = mountBell();
    await flushPromises();

    const badge = wrapper.get('[data-testid="portal-notifications-count"]');
    expect(badge.text()).toBe("4");
    expect(toggle(wrapper).attributes("aria-label")).toContain("4");
    wrapper.unmount();
  });

  it("omits the badge when there is nothing unread", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();

    expect(wrapper.find('[data-testid="portal-notifications-count"]').exists()).toBe(false);
    expect(toggle(wrapper).attributes("aria-expanded")).toBe("false");
    wrapper.unmount();
  });

  it("opens the panel and lists rows unread-first, then newest-first", async () => {
    signedIn.value = true;
    mockedList.mockResolvedValue({
      items: [
        item({ id: "read-new", read_at: "2026-01-01T00:00:00Z", created_at: "2026-03-01T00:00:00Z" }),
        item({ id: "unread-old", created_at: "2026-01-01T00:00:00Z" }),
        item({ id: "unread-new", created_at: "2026-02-01T00:00:00Z" }),
      ],
      total: 3,
      unread_count: 2,
    });
    const wrapper = mountBell();
    await flushPromises();
    expect(mockedList).not.toHaveBeenCalled();

    await openPanel(wrapper);

    const rows = wrapper.findAll('[data-testid="portal-notification-row"]');
    expect(rows).toHaveLength(3);
    expect(rows.map((row) => row.get("span.text-sm").text())).toEqual([
      "title-unread-new",
      "title-unread-old",
      "title-read-new",
    ]);
    expect(toggle(wrapper).attributes("aria-expanded")).toBe("true");
    expect(wrapper.get('[data-testid="portal-notifications-panel"]').attributes("role")).toBe("menu");
    wrapper.unmount();
  });

  it("shows the localized type title when the server title is blank", async () => {
    signedIn.value = true;
    mockedList.mockResolvedValue({
      items: [item({ id: "n1", type: "blast_failed", title: "  " })],
      total: 1,
      unread_count: 1,
    });
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    // i18n-core owns `notifications.blastFailed`; the en value is asserted.
    expect(wrapper.get('[data-testid="portal-notification-row"]').text()).toContain("BLAST job failed");
    wrapper.unmount();
  });

  it("marks one row read on click when it is unread", async () => {
    signedIn.value = true;
    mockedList.mockResolvedValue({ items: [item({ id: "n1" })], total: 1, unread_count: 1 });
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    await wrapper.get('[data-testid="portal-notification-row"]').trigger("click");
    await flushPromises();

    expect(mockedMark).toHaveBeenCalledWith({ ids: ["n1"] });
    wrapper.unmount();
  });

  it("does not re-mark an already read row", async () => {
    signedIn.value = true;
    mockedList.mockResolvedValue({
      items: [item({ id: "n1", read_at: "2026-01-01T00:00:00Z" })],
      total: 1,
      unread_count: 0,
    });
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    await wrapper.get('[data-testid="portal-notification-row"]').trigger("click");
    await flushPromises();
    expect(mockedMark).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("marks all read from the header action and disables it at zero", async () => {
    signedIn.value = true;
    mockedUnread.mockResolvedValue({ unread_count: 3 });
    mockedList.mockResolvedValue({ items: [item({ id: "n1" })], total: 1, unread_count: 3 });
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    const markAll = wrapper.get('[data-testid="portal-notifications-mark-all"]');
    expect(markAll.attributes("disabled")).toBeUndefined();
    await markAll.trigger("click");
    await flushPromises();

    expect(mockedMark).toHaveBeenCalledWith({ all: true });
    wrapper.unmount();
  });

  it("disables mark-all when everything is read", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="portal-notifications-mark-all"]').attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("shows the empty state", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="portal-notifications-empty"]').text()).not.toBe("");
    wrapper.unmount();
  });

  it("shows an error state (not the empty state) when the list fails", async () => {
    signedIn.value = true;
    mockedList.mockRejectedValue(new Error("boom"));
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    expect(wrapper.get('[data-testid="portal-notifications-error"]').text()).not.toBe("");
    expect(wrapper.find('[data-testid="portal-notifications-empty"]').exists()).toBe(false);
    wrapper.unmount();
  });
});

describe("PortalNotificationBell — a11y", () => {
  it("closes on Escape and restores focus to the trigger", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);
    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(true);

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await nextTick();

    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(false);
    expect(document.activeElement).toBe(toggle(wrapper).element);
    wrapper.unmount();
  });

  it("closes on an outside pointerdown but stays open on an inside one", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    document.body.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    await nextTick();
    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(false);

    await openPanel(wrapper);
    wrapper
      .get('[data-testid="portal-notifications-panel"]')
      .element.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    await nextTick();
    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("toggles closed from the trigger and reports aria-expanded", async () => {
    signedIn.value = true;
    const wrapper = mountBell();
    await flushPromises();
    await openPanel(wrapper);

    await toggle(wrapper).trigger("click");
    await nextTick();
    expect(toggle(wrapper).attributes("aria-expanded")).toBe("false");
    expect(wrapper.find('[data-testid="portal-notifications-panel"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
