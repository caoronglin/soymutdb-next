// @vitest-environment jsdom
/**
 * Notification bell contract.
 *
 * The panel used to announce `role="menu"` around a plain list — a screen
 * reader announced a menu with no `menuitem` children — and it neither moved
 * focus into the panel nor returned it to the bell on close. These tests pin
 * the dialog semantics, the focus round-trip and the per-notification
 * "mark read" action that the API already supports (`POST /notifications/read`
 * with an explicit id subset).
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

const client = vi.hoisted(() => ({
  unreadCount: 2,
  notifications: [
    {
      id: "n-unread",
      title: "Import finished",
      body: "module_tsv import committed",
      link: "/imports",
      read_at: null,
      created_at: "2026-10-18T00:00:00Z",
    },
    {
      id: "n-read",
      title: "Release published",
      body: "",
      link: null,
      read_at: "2026-10-18T00:01:00Z",
      created_at: "2026-10-18T00:00:30Z",
    },
  ],
  markNotificationsRead: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      get: (url: string) => {
        if (url.includes("unread-count")) {
          return Promise.resolve({ unread_count: client.unreadCount });
        }
        return Promise.resolve({
          items: client.notifications,
          total: client.notifications.length,
          unread_count: client.unreadCount,
        });
      },
      post: vi.fn(() => Promise.resolve({ marked: 0 })),
    },
    markNotificationsRead: client.markNotificationsRead,
  };
});

const { NotificationBell } = await import("./admin-header");

afterEach(() => {
  cleanup();
  client.markNotificationsRead.mockReset();
});

function renderBell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <NotificationBell />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  client.unreadCount = 2;
  client.notifications = [
    {
      id: "n-unread",
      title: "Import finished",
      body: "module_tsv import committed",
      link: "/imports",
      read_at: null,
      created_at: "2026-10-18T00:00:00Z",
    },
    {
      id: "n-read",
      title: "Release published",
      body: "",
      link: null,
      read_at: "2026-10-18T00:01:00Z",
      created_at: "2026-10-18T00:00:30Z",
    },
  ];
});

describe("admin notification bell", () => {
  it("opens a labelled dialog, not an ARIA menu", async () => {
    renderBell();
    const bell = await screen.findByRole("button", { name: /Notifications \(2 unread\)/ });
    expect(bell.getAttribute("aria-haspopup")).toBe("dialog");

    fireEvent.click(bell);
    const dialog = await screen.findByRole("dialog", { name: "Notifications" });
    expect(dialog).toBeTruthy();
    expect(screen.queryByRole("menu")).toBeNull();
    expect(await screen.findByText("Import finished")).toBeTruthy();
    expect(screen.getByText("Release published")).toBeTruthy();
  });

  it("moves focus into the panel and returns it to the bell on Escape", async () => {
    renderBell();
    const bell = await screen.findByRole("button", { name: /Notifications \(2 unread\)/ });
    fireEvent.click(bell);
    const dialog = await screen.findByRole("dialog", { name: "Notifications" });
    await waitFor(() => expect(document.activeElement).toBe(dialog));

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(bell));
  });

  it("marks a single unread notification read through the id subset API", async () => {
    renderBell();
    fireEvent.click(await screen.findByRole("button", { name: /Notifications \(2 unread\)/ }));
    await screen.findByRole("dialog", { name: "Notifications" });

    // Only the unread row offers the affordance.
    const markButtons = await screen.findAllByRole("button", { name: /Mark as read:/ });
    expect(markButtons).toHaveLength(1);
    fireEvent.click(markButtons[0]);
    await waitFor(() =>
      expect(client.markNotificationsRead).toHaveBeenCalledWith({ ids: ["n-unread"] }),
    );
  });
});
