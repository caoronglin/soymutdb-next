// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { registerServiceWorker, type ServiceWorkerNavigator } from "./service-worker";

/**
 * The registrar is the only portal code that touches `navigator.serviceWorker`.
 * `import.meta.env.PROD` is false inside Vitest, so every case injects the
 * decision that cannot be rewritten at runtime; the default-`navigator` and
 * default-`location` paths are covered with `vi.stubGlobal`.
 */

const fakeRegistration = { scope: "http://localhost/soymutdb-next/" } as ServiceWorkerRegistration;

function navigatorWith(
  register: (url: string) => Promise<ServiceWorkerRegistration>,
): ServiceWorkerNavigator {
  return { serviceWorker: { register } };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("registerServiceWorker", () => {
  it("does not register in development builds", () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);

    return registerServiceWorker({ enabled: false, nav: navigatorWith(register) }).then((handle) => {
      expect(register).not.toHaveBeenCalled();
      expect(handle).toBeUndefined();
    });
  });

  it("registers in production, resolving sw.js against the deployment base", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);
    // No `nav` passed: exercises the `navigator` default.
    vi.stubGlobal("navigator", { serviceWorker: { register } });

    const handle = await registerServiceWorker({ enabled: true, base: "/soymutdb-next/" });

    expect(register).toHaveBeenCalledTimes(1);
    expect(register).toHaveBeenCalledWith("/soymutdb-next/sw.js");
    expect(handle).toBe(fakeRegistration);
  });

  it("falls back to the origin root for a rooted deployment", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);

    await registerServiceWorker({ enabled: true, base: "/", nav: navigatorWith(register) });

    expect(register).toHaveBeenCalledWith("/sw.js");
  });

  it("normalizes a base without a trailing slash", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);

    await registerServiceWorker({ enabled: true, base: "/soymutdb-next", nav: navigatorWith(register) });

    expect(register).toHaveBeenCalledWith("/soymutdb-next/sw.js");
  });

  it("resolves (never rejects) and warns when register() rejects", async () => {
    const failure = new Error("SecurityError");
    const register = vi.fn(async (_url: string) => {
      throw failure;
    });
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(
      registerServiceWorker({ enabled: true, nav: navigatorWith(register) }),
    ).resolves.toBeUndefined();

    expect(warn).toHaveBeenCalledWith("[service-worker] registration failed", failure);
  });

  it("is a no-op when navigator has no serviceWorker (unsupported / private mode)", async () => {
    // No `serviceWorker` key at all: exercises the capability guard with no throw.
    vi.stubGlobal("navigator", {});

    await expect(registerServiceWorker({ enabled: true })).resolves.toBeUndefined();
  });

  it("is a no-op on a non-http(s) protocol", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);

    await registerServiceWorker({
      enabled: true,
      nav: navigatorWith(register),
      loc: { protocol: "file:" },
    });

    expect(register).not.toHaveBeenCalled();
  });

  it("registers by default when PROD is set and VITE_SW_ENABLED is not false", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    vi.stubEnv("PROD", true);
    vi.stubEnv("VITE_SW_ENABLED", "");

    await registerServiceWorker({ base: "/soymutdb-next/" });

    expect(register).toHaveBeenCalledWith("/soymutdb-next/sw.js");
  });

  it("honors the VITE_SW_ENABLED=false kill switch", async () => {
    const register = vi.fn(async (_url: string) => fakeRegistration);
    vi.stubGlobal("navigator", { serviceWorker: { register } });
    vi.stubEnv("PROD", true);
    vi.stubEnv("VITE_SW_ENABLED", "false");

    await registerServiceWorker({ base: "/soymutdb-next/" });

    expect(register).not.toHaveBeenCalled();
  });
});
