// @vitest-environment jsdom
/**
 * Contract coverage for the shared 30 FPS motion ticker.
 *
 * The module is a module-level singleton (one `Set` of subscribers, one rAF
 * handle, one throttle timestamp) and it registers its `visibilitychange`
 * listener as an import side effect. Two consequences shape this file:
 *
 * 1. Every case must run against a clean singleton, which is what
 *    `__resetMotionTickerForTests()` exists for. It is called in `afterEach`.
 * 2. The hook does **not** remove the `visibilitychange` listener, and the
 *    listener is registered at import scope. Re-importing the module with
 *    `vi.resetModules()` would stack a second listener that closes over its
 *    own state, so this file imports the module exactly once, at the top.
 *
 * rAF is driven by hand rather than by timers: the throttler's boundary is
 * `1000 / 30` ms against the timestamp the browser hands to the callback, so
 * the frame timestamp is an input to the contract, not wall-clock time.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __resetMotionTickerForTests, subscribeMotion } from "./ticker";

/** The throttler's minimum spacing, in ms. `1000 / 30` in the implementation. */
const INTERVAL = 1000 / 30;

type FrameCallback = (time: number) => void;

let pending = new Map<number, FrameCallback>();
let nextHandle = 1;
const requestAnimationFrameSpy = vi.fn((callback: FrameCallback) => {
  const handle = nextHandle++;
  pending.set(handle, callback);
  return handle;
});
const cancelAnimationFrameSpy = vi.fn((handle: number) => {
  pending.delete(handle);
});

/** Install the hand-driven rAF pair over the jsdom globals. */
function installRafStub(): void {
  pending = new Map();
  nextHandle = 1;
  requestAnimationFrameSpy.mockClear();
  cancelAnimationFrameSpy.mockClear();
  vi.stubGlobal("requestAnimationFrame", requestAnimationFrameSpy);
  vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrameSpy);
}

/** Number of frames the ticker is currently waiting to receive. */
function pendingFrames(): number {
  return pending.size;
}

/**
 * Deliver one animation frame at `time`, exactly as the browser would: the
 * queued callback is removed before it runs, and anything it re-requests lands
 * in the fresh queue.
 */
function flushFrame(time: number): void {
  const callbacks = [...pending.values()];
  pending.clear();
  for (const callback of callbacks) callback(time);
}

/** Shadow `document.hidden`, which jsdom exposes read-only off the prototype. */
function setDocumentHidden(hidden: boolean): void {
  Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
}

function restoreDocumentHidden(): void {
  delete (document as { hidden?: boolean }).hidden;
}

/** Flip visibility the way the browser does: set the flag, then fire the event. */
function changeVisibility(hidden: boolean): void {
  setDocumentHidden(hidden);
  document.dispatchEvent(new Event("visibilitychange"));
}

beforeEach(() => {
  installRafStub();
});

afterEach(() => {
  // Reset while the stub is still installed, so a stranded frame handle is
  // cancelled through the spy rather than the real jsdom rAF.
  __resetMotionTickerForTests();
  cancelAnimationFrameSpy.mockClear();
  pending = new Map();
  vi.unstubAllGlobals();
  restoreDocumentHidden();
  expect(document.hidden).toBe(false);
});

describe("subscription", () => {
  it("delivers the browser frame timestamp to a subscriber", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    flushFrame(1000);

    expect(seen).toEqual([1000]);
  });

  it("stops delivering after unsubscribe, even if a frame is still in flight", () => {
    const seen: number[] = [];
    const unsubscribe = subscribeMotion((time) => seen.push(time));

    flushFrame(1000);
    unsubscribe();
    // The handle was cancelled, so nothing is left to deliver.
    expect(pendingFrames()).toBe(0);
    flushFrame(1100);

    expect(seen).toEqual([1000]);
  });

  it("cancels the pending frame when the last subscriber leaves", () => {
    const unsubscribe = subscribeMotion(() => {});
    flushFrame(1000);
    const handle = requestAnimationFrameSpy.mock.results.at(-1)?.value as number;
    expect(pendingFrames()).toBe(1);

    unsubscribe();

    expect(cancelAnimationFrameSpy).toHaveBeenCalledWith(handle);
    expect(pendingFrames()).toBe(0);
  });

  it("keeps the loop running while any subscriber remains", () => {
    const first: number[] = [];
    const second: number[] = [];
    const dropFirst = subscribeMotion((time) => first.push(time));
    subscribeMotion((time) => second.push(time));

    flushFrame(1000);
    dropFirst();
    flushFrame(1100);

    expect(first).toEqual([1000]);
    expect(second).toEqual([1000, 1100]);
    expect(cancelAnimationFrameSpy).not.toHaveBeenCalled();
  });

  it("delivers the same timestamp to every subscriber in one dispatch", () => {
    const order: string[] = [];
    subscribeMotion(() => order.push("first"));
    subscribeMotion(() => order.push("second"));
    subscribeMotion(() => order.push("third"));

    flushFrame(1000);

    expect(order).toEqual(["first", "second", "third"]);
  });

  it("does not call a subscriber removed earlier in the same dispatch", () => {
    const seen: string[] = [];
    let dropSecond = (): void => {};
    subscribeMotion(() => {
      seen.push("first");
      dropSecond();
    });
    dropSecond = subscribeMotion(() => seen.push("second"));

    flushFrame(1000);

    // The set is iterated live, so `second` is skipped once it is deleted.
    expect(seen).toEqual(["first"]);
    // `first` never unsubscribed, so the loop is still wanted and re-arms.
    expect(pendingFrames()).toBe(1);

    flushFrame(1100);
    expect(seen).toEqual(["first", "first"]);
  });

  it("stops re-arming when the last subscriber leaves during a dispatch", () => {
    const seen: number[] = [];
    let unsubscribe = (): void => {};
    unsubscribe = subscribeMotion((time) => {
      seen.push(time);
      unsubscribe();
    });

    flushFrame(1000);

    expect(seen).toEqual([1000]);
    // The unsubscribe saw `raf === 0` (tick clears it first), so the guard
    // that normally cancels on an empty set found nothing to cancel; the set
    // is empty by the time `schedule()` runs, so nothing is re-armed either.
    expect(pendingFrames()).toBe(0);
  });

  /**
   * Current contract, and a hazard for future callers: `subscribers` is a
   * `Set`, so subscribing the same function reference twice registers it once
   * and the first unsubscribe tears the registration down for good. A caller
   * that holds a stable reference (a `useCallback`-stable handler, a bound
   * method) would silently go dead. The only production caller today,
   * `components/fluids/fluid-gradient.tsx`, passes a per-effect closure, so
   * this is latent rather than live. See the report.
   */
  it("collapses duplicate subscriptions of one function reference", () => {
    const seen: number[] = [];
    const shared = (time: number) => seen.push(time);
    const dropFirst = subscribeMotion(shared);
    const dropSecond = subscribeMotion(shared);

    flushFrame(1000);
    dropFirst();
    flushFrame(1100);
    dropSecond();

    expect(seen).toEqual([1000]);
  });
});

describe("30 FPS throttle", () => {
  it("does not re-dispatch inside the throttle window and resumes past it", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    flushFrame(1000);
    // 33ms is one millisecond short of `1000 / 30`; 34ms clears it.
    flushFrame(1033);
    flushFrame(1034);

    expect(seen).toEqual([1000, 1034]);
  });

  it("keeps re-arming while frames are dropped, so the loop never stalls", () => {
    subscribeMotion(() => {});
    flushFrame(1000);

    flushFrame(1004);

    expect(pendingFrames()).toBe(1);
  });

  it("never dispatches two frames closer than the throttle interval", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    for (let frame = 0; frame < 600; frame += 1) flushFrame(1000 + (frame * 1000) / 60);

    // The guarantee the throttle actually makes: no dispatch sooner than
    // `1000 / 30` after the previous one. Epsilon absorbs the float drift in
    // the frame timestamps.
    const gaps = seen.slice(1).map((time, index) => time - seen[index]);
    expect(Math.min(...gaps)).toBeGreaterThanOrEqual(INTERVAL - 1e-9);
  });

  /**
   * The rate this module advertises, asserted rather than assumed.
   *
   * This case used to pin the opposite. The old throttle compared
   * `time - lastDispatch >= interval`, and on a 60Hz grid the gap between every
   * second frame is 33.33333333333333 — one ULP *below* `1000 / 30` — so that
   * comparison was always false and the frame was dropped every time. The
   * ticker ran at ~20fps while documenting and naming itself 30.
   *
   * The bound stays loose on both sides because the exact count depends on where
   * the frame timestamps land relative to the interval, and real rAF timestamps
   * carry jitter a test should not try to model. What it pins is the *rate*: a
   * floor at 29 rules out the 20fps regression coming back, and the ceiling
   * rules out a fix that overshoots into a per-frame dispatch.
   */
  it("delivers ~30 dispatches per second on a 60 Hz display", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    for (let frame = 0; frame < 600; frame += 1) flushFrame(1000 + (frame * 1000) / 60);

    const elapsedSeconds = (seen[seen.length - 1] - seen[0]) / 1000;
    const effectiveFps = (seen.length - 1) / elapsedSeconds;

    expect(effectiveFps).toBeGreaterThan(29);
    expect(effectiveFps).toBeLessThan(31);
  });

  it("measures the gap between dispatches, not the gap between frames", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    for (let frame = 0; frame < 30; frame += 1) flushFrame(1000 + frame);
    flushFrame(1040);

    // A burst of 30 frames inside one window produces a single dispatch.
    expect(seen).toEqual([1000, 1040]);
  });

  /**
   * `last` is seeded to 0, so a ticker whose very first frame lands inside the
   * throttle window drops it and delivers on the next one. The rAF timestamp is
   * measured from the navigation start, so this only bites when a frame is
   * requested within ~33ms of load. Locked here because a test that flushes a
   * first frame at t=0 or t=16 would otherwise read as a broken ticker.
   */
  it("drops a first frame that lands inside the throttle window", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));

    flushFrame(16);
    expect(seen).toEqual([]);
    expect(pendingFrames()).toBe(1);

    flushFrame(34);
    expect(seen).toEqual([34]);
  });
});

describe("document visibility", () => {
  it("requests no frame at all while the document is hidden", () => {
    setDocumentHidden(true);

    subscribeMotion(() => {});

    expect(requestAnimationFrameSpy).not.toHaveBeenCalled();
    expect(pendingFrames()).toBe(0);
  });

  it("drops the frame if the document turned hidden before it landed", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    setDocumentHidden(true);

    flushFrame(1000);

    expect(seen).toEqual([]);
    // No re-arm: recovery is the visibilitychange listener's job, not tick's.
    expect(pendingFrames()).toBe(0);
  });

  it("cancels the in-flight frame when visibilitychange reports hidden", () => {
    subscribeMotion(() => {});
    flushFrame(1000);
    const handle = requestAnimationFrameSpy.mock.results.at(-1)?.value as number;

    changeVisibility(true);

    expect(cancelAnimationFrameSpy).toHaveBeenCalledWith(handle);
    expect(pendingFrames()).toBe(0);
  });

  it("resumes on the next frame after visibilitychange reports visible", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    changeVisibility(true);

    changeVisibility(false);
    flushFrame(1000);

    expect(seen).toEqual([1000]);
  });

  it("picks up a subscriber that arrived while hidden without re-subscribing", () => {
    changeVisibility(true);
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    expect(pendingFrames()).toBe(0);

    changeVisibility(false);
    flushFrame(1000);

    expect(seen).toEqual([1000]);
  });

  it("does not resume when nobody is subscribed", () => {
    changeVisibility(true);

    changeVisibility(false);

    expect(requestAnimationFrameSpy).not.toHaveBeenCalled();
  });

  it("resumes without a burst: the first frame back is throttled like any other", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    flushFrame(1000);
    changeVisibility(true);
    changeVisibility(false);

    // A long hidden gap clears the throttle, so exactly one dispatch lands.
    flushFrame(500_000);
    flushFrame(500_010);

    expect(seen).toEqual([1000, 500_000]);
  });
});

describe("__resetMotionTickerForTests", () => {
  it("cancels the pending frame and clears subscribers", () => {
    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    flushFrame(1000);
    const handle = requestAnimationFrameSpy.mock.results.at(-1)?.value as number;

    __resetMotionTickerForTests();

    expect(cancelAnimationFrameSpy).toHaveBeenCalledWith(handle);
    pending = new Map();
    flushFrame(1100);
    expect(seen).toEqual([1000]);
  });

  it("rewinds the throttle so the next subscriber starts from a clean ticker", () => {
    subscribeMotion(() => {});
    flushFrame(1000);
    __resetMotionTickerForTests();

    const seen: number[] = [];
    subscribeMotion((time) => seen.push(time));
    // Without the rewind, 1034 - 1000 = 34 would clear the window and the
    // throttled frame 16 below would not prove the reset at all.
    flushFrame(16);

    expect(seen).toEqual([]);
  });
});
