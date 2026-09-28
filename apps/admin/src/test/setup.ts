import { expect, afterEach, vi } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

// Explicit registration — the "@testing-library/jest-dom/vitest" entry
// doesn't extend expect reliably under vitest 4.1.10 + forks pool.
expect.extend(matchers);

// AntD responsive components (ProTable/Grid) call window.matchMedia; jsdom
// does not implement it. Provide a minimal always-false mock.
if (!globalThis.ResizeObserver) {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverMock as typeof ResizeObserver;
}

if (!window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

afterEach(() => {
  // Order matters here, and so does the call that used to be missing.
  //
  // 1. Undo every `vi.stubGlobal`. `vi.restoreAllMocks()` deliberately does NOT
  //    touch the stub registry -- it only walks back `vi.spyOn` -- so a
  //    `stubGlobal` installed by one test (or one test file) survives into the
  //    next one. A stub whose value is `undefined` also *removes* the property
  //    instead of shadowing it, so the leak stays invisible until some later
  //    file trips over the hole. It did:
  //
  //        ReferenceError: window is not defined
  //          at resolveUpdatePriority (react-dom/cjs/react-dom-client...:1308)
  //          at requestUpdateLane
  //          at dispatchSetState
  //          at Timeout._onTimeout (@rc-component/util/lib/hooks/useDelayState.js:39)
  //        This error originated in "src/components/file-upload.test.tsx"
  //        Test Files 47 passed (47) | Tests 119 passed (119) | Errors 1 error
  //
  //    A fully green suite that still exits non-zero, blamed on a file whose own
  //    assertions had all passed. The global that react-dom frame needed had
  //    been removed by an *earlier* test.
  //
  // 2. `cleanup()` then unmounts the tree, disposing antd/rc state. Components
  //    such as `FileUpload` schedule a delay state update through
  //    `@rc-component/util`, whose deadline is rebased on every call. A
  //    reference sitting at "now" fires while the next test is already running,
  //    and a detached react-dom tree rendering against a torn-down global scope
  //    is exactly the crash above. Unmounting only after the globals are sound
  //    is what keeps that from happening.
  vi.unstubAllGlobals();
  cleanup();
  vi.restoreAllMocks();
});
