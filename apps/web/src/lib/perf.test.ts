import { afterEach, describe, expect, it, vi } from "vitest";
import { initPerfMonitoring } from "./perf";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("performance monitoring lifecycle", () => {
  it("removes every event listener when disposed", () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    const dispose = initPerfMonitoring({ sampleRate: 1 });
    const registered = add.mock.calls.filter(([type]) =>
      type === "visibilitychange" || type === "pagehide",
    );
    expect(registered).toHaveLength(4);
    dispose();
    for (const [type, callback] of registered) {
      expect(remove).toHaveBeenCalledWith(type, callback);
    }
  });

  it("reports the interaction duration without adding input delay twice", () => {
    const callbacks = new Map<string, (entries: PerformanceEntryList) => void>();
    class Observer {
      constructor(private readonly callback: (list: { getEntries(): PerformanceEntryList }) => void) {}
      observe({ type }: PerformanceObserverInit) {
        callbacks.set(type!, (entries) => this.callback({ getEntries: () => entries }));
      }
      disconnect() {}
    }
    vi.stubGlobal("PerformanceObserver", Observer);
    vi.spyOn(performance, "getEntriesByType").mockReturnValue([]);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    const onMetric = vi.fn();
    const dispose = initPerfMonitoring({ sampleRate: 1, onMetric });
    callbacks.get("event")!([
      { interactionId: 1, startTime: 100, processingStart: 150, duration: 240 },
    ] as unknown as PerformanceEntryList);
    window.dispatchEvent(new Event("visibilitychange"));
    expect(onMetric).toHaveBeenCalledWith({ name: "INP", value: 240, rating: "needs-improvement", id: undefined });
    dispose();
  });
});
