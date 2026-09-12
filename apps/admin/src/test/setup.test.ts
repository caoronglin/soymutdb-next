/**
 * Contract tests for the shared Vitest setup (`src/test/setup.ts`).
 *
 * The suite deliberately declares NO `afterEach` of its own. Every assertion
 * below therefore runs against the teardown the shared setup installs, which is
 * the teardown the other 47 spec files in this workspace also get. A test that
 * reimplemented the teardown inline, or that only grepped for the string
 * `vi.unstubAllGlobals()`, would keep passing after the real setup regressed.
 *
 * Why this matters, from a real CNB build:
 *
 *     ReferenceError: window is not defined
 *       at resolveUpdatePriority (react-dom/cjs/react-dom-client...:1308)
 *       at requestUpdateLane
 *       at dispatchSetState
 *       at Timeout._onTimeout (@rc-component/util/lib/hooks/useDelayState.js:39)
 *     This error originated in "src/components/file-upload.test.tsx"
 *     Test Files 47 passed (47) | Tests 119 passed (119) | Errors 1 error
 *
 * Every assertion in the suite passed and the build still failed. `vi.stubGlobal`
 * records its replacement, and until something walks that registry back the
 * replacement outlives the test that asked for it. `vi.restoreAllMocks()` does
 * not walk it -- it only undoes `vi.spyOn` -- so the stub leaked into whatever
 * ran next, and react-dom blew up on a global that had been removed instead of
 * restored.
 */
import { describe, expect, it, vi } from "vitest";

describe("shared Vitest teardown", () => {
  it("installs a stub on a global that did not exist", () => {
    vi.stubGlobal("__soymutdbProbe", { ok: true });
    // `vi.stubGlobal` records the ORIGINAL descriptor and installs a
    // `value`-carrying one. That shadowing descriptor is the leak: restoring it
    // to `value: undefined` would leave the name shadowed, not absent.
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, "__soymutdbProbe");
    expect(descriptor?.value).toEqual({ ok: true });
  });

  it("does not see the previous test's stub", () => {
    // The global is back to genuinely absent -- not merely `undefined`.
    expect(Object.getOwnPropertyDescriptor(globalThis, "__soymutdbProbe")).toBeUndefined();
    expect("__soymutdbProbe" in globalThis).toBe(false);
  });

  it("replaces a global that jsdom does define", () => {
    vi.stubGlobal("crypto", { subtle: { digest: vi.fn() } });
    expect(vi.isMockFunction(globalThis.crypto.subtle.digest)).toBe(true);
  });

  it("sees the un-stubbed crypto again", () => {
    // The point of the teardown: a later test must get the real global back,
    // not a mock left over from an earlier one.
    expect(vi.isMockFunction(globalThis.crypto.subtle.digest)).toBe(false);
  });

  it("stubs a global whose name is a substring of another", () => {
    // Cheap insurance that the registry keys stubs by exact name: a teardown
    // that restored too much (or prefix-matched) would silently drop real
    // globals and reproduce the same class of failure.
    vi.stubGlobal("__soymutdbProbe__", "stubbed");
  });

  it("has dropped that global too", () => {
    expect("__soymutdbProbe__" in globalThis).toBe(false);
    expect("__soymutdbProbe" in globalThis).toBe(false);
    expect(typeof globalThis.crypto).toBe("object");
  });

  it("undoes a spy without leaving it in place", () => {
    const spy = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(vi.isMockFunction(console.warn)).toBe(true);
    expect(spy).toBeDefined();
  });

  it("has unwrapped the spy", () => {
    expect(vi.isMockFunction(console.warn)).toBe(false);
  });
});
