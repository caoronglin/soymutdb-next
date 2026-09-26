// @vitest-environment jsdom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { nextTick } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  BRIDGE_SOURCE_BROWSER,
  BRIDGE_SOURCE_JBROWSE,
  BRIDGE_VERSION,
} from "@soymutdb/shared/jbrowse-bridge";

vi.mock("@soymutdb/ui-vue", () => ({
  ConfigProvider: { template: "<div><slot /></div>" },
  createThemeConfig: () => ({}),
  Button: { template: "<button><slot /></button>" },
}));

vi.mock("../components/PortalLayout.vue", () => ({
  default: { template: "<div><slot /></div>" },
}));

import BrowserView from "./BrowserView.vue";
import { setLanguage } from "../lib/i18n";

const JBROWSE_BASE = "https://jbrowse.example.org";
// Kept in sync with READY_TIMEOUT_MS in BrowserView.vue.
const READY_TIMEOUT_MS = 15_000;

interface BridgeEnvelope {
  source: string;
  version: unknown;
  type: string;
  payload?: unknown;
}

const mounted: VueWrapper[] = [];

afterEach(() => {
  for (const wrapper of mounted.splice(0)) wrapper.unmount();
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

beforeEach(() => {
  setLanguage("en");
  vi.stubEnv("VITE_JBROWSE_BASE_URL", JBROWSE_BASE);
});

async function mountBrowser(
  query: Record<string, string> = {},
): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/browser", name: "browser", component: BrowserView },
      { path: "/:pathMatch(.*)*", component: BrowserView },
    ],
  });
  await router.push({ path: "/browser", query });
  await router.isReady();
  const wrapper = mount(BrowserView, {
    attachTo: document.body,
    global: { plugins: [createPinia(), router] },
  });
  mounted.push(wrapper);
  await nextTick();
  return { wrapper, router };
}

function frameOf(wrapper: VueWrapper): HTMLIFrameElement {
  return wrapper.get('[data-testid="browser-iframe"]').element as HTMLIFrameElement;
}

function postBridge(wrapper: VueWrapper, data: BridgeEnvelope, origin = JBROWSE_BASE): void {
  const frame = frameOf(wrapper);
  window.dispatchEvent(
    new MessageEvent("message", {
      data,
      origin,
      source: frame.contentWindow as unknown as MessageEventSource,
    }),
  );
}

function readyEnvelope(overrides: Partial<BridgeEnvelope> = {}): BridgeEnvelope {
  return {
    source: BRIDGE_SOURCE_JBROWSE,
    version: BRIDGE_VERSION,
    type: "ready",
    payload: { assembly: "Wm82.a4.v1", locus: "chr01:1-1000" },
    ...overrides,
  };
}

interface PostTarget {
  postMessage: (message: unknown, targetOrigin: string) => void;
}

function capturePosts(wrapper: VueWrapper) {
  const target = frameOf(wrapper).contentWindow as unknown as PostTarget;
  const posts: { message: unknown; targetOrigin: string }[] = [];
  const original = target.postMessage;
  target.postMessage = (message: unknown, targetOrigin: string) => {
    posts.push({ message, targetOrigin });
  };
  return {
    posts,
    restore: () => {
      target.postMessage = original;
    },
  };
}

describe("BrowserView portal embed", () => {
  it("loads the frame from the canonical origin with the portal origin attached", async () => {
    const { wrapper } = await mountBrowser({ locus: "chr01:1-1000" });
    const frame = frameOf(wrapper);
    const src = new URL(frame.src);
    expect(src.origin).toBe(new URL(JBROWSE_BASE).origin);
    expect(src.searchParams.get("portalOrigin")).toBe(window.location.origin);
    expect(src.searchParams.get("locus")).toBe("chr01:1-1000");
    expect(frame.getAttribute("src")).toContain("portalOrigin");
  });

  it("only marks the frame ready after a validated ready handshake", async () => {
    const { wrapper } = await mountBrowser({ locus: "chr01:1-1000" });
    const posts = capturePosts(wrapper);

    expect(wrapper.find('[data-testid="browser-loading"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(false);

    postBridge(wrapper, readyEnvelope());
    await nextTick();

    expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="browser-loading"]').exists()).toBe(false);
    expect(posts.posts).toHaveLength(1);
    expect(posts.posts[0].targetOrigin).toBe(new URL(JBROWSE_BASE).origin);
    expect(posts.posts[0].message).toMatchObject({
      source: BRIDGE_SOURCE_BROWSER,
      version: BRIDGE_VERSION,
      type: "init",
    });
    posts.restore();
  });

  it("rejects a ready message from any other origin and never logs its payload", async () => {
    const { wrapper } = await mountBrowser();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const posts = capturePosts(wrapper);

    postBridge(
      wrapper,
      readyEnvelope({ payload: { locus: "MUT-PUB-0001", internal_id: "INT-0001" } }),
      "https://evil.example.org",
    );
    await nextTick();

    expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="browser-loading"]').exists()).toBe(true);
    expect(posts.posts).toHaveLength(0);
    const logged = warn.mock.calls.flat().map(String).join(" ");
    expect(logged).toContain("https://evil.example.org");
    expect(logged).not.toContain("MUT-PUB-0001");
    expect(logged).not.toContain("INT-0001");
    posts.restore();
  });

  it("rejects ready envelopes with the wrong source, version or type", async () => {
    const { wrapper } = await mountBrowser();
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const posts = capturePosts(wrapper);

    const invalid: BridgeEnvelope[] = [
      { source: BRIDGE_SOURCE_BROWSER, version: BRIDGE_VERSION, type: "ready" },
      { source: "soymutdb-other", version: BRIDGE_VERSION, type: "ready" },
      { source: BRIDGE_SOURCE_JBROWSE, version: 2, type: "ready" },
      { source: BRIDGE_SOURCE_JBROWSE, version: "1", type: "ready" },
      { source: BRIDGE_SOURCE_JBROWSE, version: BRIDGE_VERSION, type: "init" },
      { source: BRIDGE_SOURCE_JBROWSE, version: BRIDGE_VERSION, type: "not-a-bridge-type" },
    ];

    for (const data of invalid) {
      postBridge(wrapper, data);
      await nextTick();
      expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(false);
    }
    expect(posts.posts).toHaveLength(0);
    posts.restore();
  });

  it("flips loading to the timeout error state when no handshake arrives", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountBrowser();

    expect(wrapper.find('[data-testid="browser-timeout"]').exists()).toBe(false);
    vi.advanceTimersByTime(READY_TIMEOUT_MS);
    await nextTick();

    expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(false);
    const timeout = wrapper.get('[data-testid="browser-timeout"]');
    expect(timeout.attributes("role")).toBe("alert");
    expect(wrapper.find('[data-testid="browser-retry"]').exists()).toBe(true);
  });

  it("re-runs the handshake on retry and accepts the next validated ready", async () => {
    vi.useFakeTimers();
    const { wrapper } = await mountBrowser();

    vi.advanceTimersByTime(READY_TIMEOUT_MS);
    await nextTick();
    const before = frameOf(wrapper);

    await wrapper.get('[data-testid="browser-retry"]').trigger("click");
    await nextTick();
    expect(wrapper.find('[data-testid="browser-timeout"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="browser-loading"]').exists()).toBe(true);
    expect(frameOf(wrapper)).not.toBe(before);

    postBridge(wrapper, readyEnvelope());
    await nextTick();
    expect(wrapper.find('[data-testid="browser-ready"]').exists()).toBe(true);
  });

  it("resolves a same-origin base against the portal without a configured origin", async () => {
    vi.stubEnv("VITE_JBROWSE_BASE_URL", "");
    const { wrapper } = await mountBrowser({ locus: "chr01:1-5" });
    const src = new URL(frameOf(wrapper).src);
    expect(src.origin).toBe(window.location.origin);
    expect(src.pathname).toBe("/jbrowse");
    expect(src.searchParams.get("portalOrigin")).toBe(window.location.origin);
  });

  it("keeps record identifiers out of the frame URL and rewrites unknown query keys away", async () => {
    const { wrapper, router } = await mountBrowser({
      locus: "chr01:1-1000",
      mutant: "MUT-PUB-0001",
      internal_id: "INT-0001",
    });
    expect(frameOf(wrapper).src).not.toContain("MUT-PUB-0001");
    expect(frameOf(wrapper).src).not.toContain("INT-0001");

    await wrapper.get('[data-testid="browser-locus-input"]').setValue("chr05:1-100");
    await wrapper.get("form").trigger("submit");
    await flushPromises();

    expect(router.currentRoute.value.query).toEqual({ locus: "chr05:1-100" });
    expect(router.currentRoute.value.query.mutant).toBeUndefined();
    expect(router.currentRoute.value.query.internal_id).toBeUndefined();
  });
});
