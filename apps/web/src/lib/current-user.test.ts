// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getCurrentUser = vi.fn();
vi.mock("@soymutdb/api-client", () => ({
  getCurrentUser: () => getCurrentUser(),
}));

import {
  __resetSessionStateForTests,
  isResearcher,
  markSessionEstablished,
  useCurrentUser,
  type CurrentUser,
  type UseCurrentUserResult,
} from "./current-user";

function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "u1",
    username: "rui",
    email: "rui@example.org",
    full_name: null,
    is_active: true,
    is_superuser: false,
    role_name: "viewer",
    joined_at: "2026-01-01T00:00:00Z",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Every role in the server's `RoleName` enum (apps/api/app/core/security.py:124). */
const ALL_SERVER_ROLES = [
  "viewer",
  "researcher",
  "curator",
  "data_manager",
  "track_manager",
  "blast_manager",
  "seed_manager",
  "content_editor",
  "auditor",
  "administrator",
] as const;

function mountComposable(): {
  result: { current: UseCurrentUserResult | null };
  wrapper: ReturnType<typeof mount>;
} {
  const result: { current: UseCurrentUserResult | null } = { current: null };
  const wrapper = mount(
    defineComponent({
      setup() {
        result.current = useCurrentUser();
        return () => h("div");
      },
    }),
    {
      global: {
        plugins: [
          [
            VueQueryPlugin,
            { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
          ],
        ],
      },
    },
  );
  return { result, wrapper };
}

describe("isResearcher", () => {
  beforeEach(() => {
    getCurrentUser.mockReset();
  });

  it("rejects a null user", () => {
    expect(isResearcher(null)).toBe(false);
  });

  it("rejects a role-less legacy row", () => {
    expect(isResearcher(makeUser({ role_name: null }))).toBe(false);
    expect(isResearcher(makeUser({ role_name: undefined }))).toBe(false);
  });

  it("trusts is_superuser even without a role_name", () => {
    expect(isResearcher(makeUser({ is_superuser: true, role_name: null }))).toBe(true);
  });

  // The server grants `researcher` to every role except `viewer` — see the
  // authorization table in apps/api/app/core/security.py:141-160
  // (`_COMMON_GRANTS` plus `_ROLE_GRANTS`). A client predicate looser than the
  // server only costs a re-check; looser-than-React is intentional because the
  // React baseline wrongly denied curator/data_manager and friends.
  it("matches the server grant table: every role except viewer grants researcher", () => {
    for (const role of ALL_SERVER_ROLES) {
      expect(isResearcher(makeUser({ role_name: role }))).toBe(role !== "viewer");
    }
  });

  it("admits each researcher-granting role explicitly", () => {
    const admitted = ALL_SERVER_ROLES.filter((role) => role !== "viewer");
    expect(admitted).toEqual([
      "researcher",
      "curator",
      "data_manager",
      "track_manager",
      "blast_manager",
      "seed_manager",
      "content_editor",
      "auditor",
      "administrator",
    ]);
    for (const role of admitted) {
      expect(isResearcher(makeUser({ role_name: role }))).toBe(true);
    }
    expect(isResearcher(makeUser({ role_name: "viewer" }))).toBe(false);
  });
});

describe("useCurrentUser", () => {
  beforeEach(() => {
    getCurrentUser.mockReset();
    __resetSessionStateForTests();
  });

  // Regression guard for the anonymous bounce: `GET /auth/me` rides the
  // auth-aware transport, whose unrefreshable 401 fires the global logout
  // handler, and `main.ts` redirects that to /login. Probing before a session
  // exists therefore threw every anonymous visitor off the public site.
  it("never probes /auth/me before a session is established", async () => {
    getCurrentUser.mockResolvedValue(makeUser({ role_name: "curator" }));

    const { result, wrapper } = mountComposable();
    await flushPromises();

    expect(getCurrentUser).not.toHaveBeenCalled();
    expect(result.current!.user.value).toBeNull();
    expect(result.current!.isResearcher.value).toBe(false);
    expect(result.current!.isLoading.value).toBe(false);
    wrapper.unmount();
  });

  it("starts probing once restoreSession reports a session", async () => {
    getCurrentUser.mockResolvedValue(makeUser({ role_name: "curator" }));

    const { result, wrapper } = mountComposable();
    // Anonymous first: no probe.
    await flushPromises();
    expect(getCurrentUser).not.toHaveBeenCalled();

    // `main.ts` flips this after a successful restoreSession().
    markSessionEstablished(true);
    await flushPromises();

    expect(getCurrentUser).toHaveBeenCalledTimes(1);
    expect(result.current!.user.value?.role_name).toBe("curator");
    expect(result.current!.isResearcher.value).toBe(true);
    wrapper.unmount();
  });

  it("resolves the researcher verdict while loading then settles", async () => {
    markSessionEstablished(true);
    getCurrentUser.mockResolvedValue(makeUser({ role_name: "curator" }));

    const { result, wrapper } = mountComposable();
    expect(result.current!.isLoading.value).toBe(true);

    await flushPromises();

    expect(getCurrentUser).toHaveBeenCalledTimes(1);
    expect(result.current!.isLoading.value).toBe(false);
    expect(result.current!.user.value?.role_name).toBe("curator");
    expect(result.current!.isResearcher.value).toBe(true);
    wrapper.unmount();
  });

  it("degrades a 401/network failure to the anonymous state without throwing", async () => {
    markSessionEstablished(true);
    getCurrentUser.mockRejectedValue(new Error("401 unauthorized"));

    const { result, wrapper } = mountComposable();
    await flushPromises();

    expect(result.current!.isLoading.value).toBe(false);
    expect(result.current!.user.value).toBeNull();
    expect(result.current!.isResearcher.value).toBe(false);
    // No error branch: the query resolved to null rather than rejecting.
    expect(wrapper.text()).toBe("");
    wrapper.unmount();
  });

  it("treats a viewer session as non-researcher", async () => {
    markSessionEstablished(true);
    getCurrentUser.mockResolvedValue(makeUser({ role_name: "viewer" }));

    const { result, wrapper } = mountComposable();
    await flushPromises();

    expect(result.current!.isResearcher.value).toBe(false);
    wrapper.unmount();
  });
});
