/**
 * The motion policy is the single place that turns "what the user asked for"
 * plus "what the device can afford" into one effective mode. Every consumer
 * (`animation-context.tsx`, `view-transitions.ts`, `react-app.tsx`) routes
 * through `resolveMotionDecision`, so its ordering is a contract, not an
 * implementation detail: the `reduced` signal outranks an explicit "off"
 * request, and the three downgrade reasons are checked in a fixed order.
 *
 * `parseMotionPreference` is the migration seam for the retired Vue settings
 * vocabulary, so the legacy `normal` / `expressive` tokens are pinned here
 * along with their `explicit: false` opt-out.
 */
import { describe, expect, it } from "vitest";

import {
  parseMotionPreference,
  resolveMotionDecision,
  type MotionSessionCeiling,
  type MotionSignals,
} from "./motion-policy";

/** No signals set: every optional input absent, as callers do on a desktop. */
const NO_SIGNALS: MotionSignals = {};

describe("parseMotionPreference", () => {
  it("treats absent and empty storage as no preference", () => {
    expect(parseMotionPreference(null)).toBe("auto");
    expect(parseMotionPreference("")).toBe("auto");
  });

  it("reads every current-vocabulary value back verbatim", () => {
    for (const intensity of ["auto", "standard", "minimal", "off"] as const) {
      expect(parseMotionPreference(JSON.stringify({ intensity }))).toBe(intensity);
    }
  });

  it("maps the retired normal/expressive vocabulary onto standard", () => {
    expect(parseMotionPreference(JSON.stringify({ intensity: "normal" }))).toBe("standard");
    expect(parseMotionPreference(JSON.stringify({ intensity: "expressive" }))).toBe("standard");
  });

  it("honours the explicit:false opt-out on the legacy vocabulary", () => {
    expect(
      parseMotionPreference(JSON.stringify({ intensity: "normal", explicit: false })),
    ).toBe("auto");
    expect(
      parseMotionPreference(JSON.stringify({ intensity: "expressive", explicit: false })),
    ).toBe("auto");
  });

  it("falls back to auto for malformed, non-object and unknown payloads", () => {
    // Malformed JSON, a JSON null, a bare JSON string, an unrelated shape, a
    // missing intensity, and an unknown intensity token.
    expect(parseMotionPreference("{not json")).toBe("auto");
    expect(parseMotionPreference("null")).toBe("auto");
    expect(parseMotionPreference('"standard"')).toBe("auto");
    expect(parseMotionPreference("{}")).toBe("auto");
    expect(parseMotionPreference(JSON.stringify({ intensity: "ludicrous" }))).toBe("auto");
  });

  it("ignores explicit:false for a current-vocabulary value", () => {
    // The opt-out belongs to the legacy branch only: an explicit "off" must
    // stay off, or the user's choice would silently re-enable motion.
    expect(parseMotionPreference(JSON.stringify({ intensity: "off", explicit: false }))).toBe(
      "off",
    );
    expect(
      parseMotionPreference(JSON.stringify({ intensity: "standard", explicit: false })),
    ).toBe("standard");
  });
});

describe("resolveMotionDecision", () => {
  it("resolves auto to standard when nothing constrains it", () => {
    expect(resolveMotionDecision("auto", NO_SIGNALS)).toEqual({
      requested: "auto",
      effective: "standard",
      reason: "auto",
    });
  });

  it("reports an explicit preference under the preference reason", () => {
    expect(resolveMotionDecision("standard", NO_SIGNALS).reason).toBe("preference");
    expect(resolveMotionDecision("minimal", NO_SIGNALS)).toEqual({
      requested: "minimal",
      effective: "minimal",
      reason: "preference",
    });
  });

  it("honours an explicit off", () => {
    expect(resolveMotionDecision("off", NO_SIGNALS)).toEqual({
      requested: "off",
      effective: "off",
      reason: "preference",
    });
  });

  it("lets reduced-motion outrank even an explicit off", () => {
    // Accessibility is not a preference to be weighed against.
    expect(resolveMotionDecision("off", { reduced: true }).reason).toBe("reduced-motion");
    expect(resolveMotionDecision("standard", { reduced: true })).toEqual({
      requested: "standard",
      effective: "off",
      reason: "reduced-motion",
    });
  });

  it("downgrades standard to minimal on save-data, then low-resource", () => {
    expect(resolveMotionDecision("auto", { saveData: true })).toEqual({
      requested: "auto",
      effective: "minimal",
      reason: "save-data",
    });
    expect(resolveMotionDecision("auto", { lowResource: true })).toEqual({
      requested: "auto",
      effective: "minimal",
      reason: "low-resource",
    });
  });

  it("prefers save-data over low-resource when both are set", () => {
    // Ordering is a contract: the reason string is surfaced in the UI.
    expect(
      resolveMotionDecision("auto", { saveData: true, lowResource: true }).reason,
    ).toBe("save-data");
  });

  it("applies the session ceiling last, so it cannot mask a signal reason", () => {
    expect(resolveMotionDecision("auto", NO_SIGNALS, "minimal")).toEqual({
      requested: "auto",
      effective: "minimal",
      reason: "session-downgrade",
    });
    expect(
      resolveMotionDecision("auto", { saveData: true }, "minimal").reason,
    ).toBe("save-data");
  });

  it("never downgrades a mode that is already minimal", () => {
    // Every downgrade is guarded on `preferred === "standard"`, so an explicit
    // minimal request survives every signal.
    for (const signals of [
      { saveData: true },
      { lowResource: true },
    ] satisfies MotionSignals[]) {
      for (const ceiling of ["standard", "minimal"] satisfies MotionSessionCeiling[]) {
        expect(resolveMotionDecision("minimal", signals, ceiling)).toEqual({
          requested: "minimal",
          effective: "minimal",
          reason: "preference",
        });
      }
    }
  });

  it("defaults the session ceiling to standard when the caller omits it", () => {
    expect(resolveMotionDecision("auto", NO_SIGNALS).effective).toBe("standard");
    expect(resolveMotionDecision("standard", NO_SIGNALS, undefined).effective).toBe("standard");
  });

  it("always echoes the requested preference back to the caller", () => {
    for (const requested of ["auto", "standard", "minimal", "off"] as const) {
      expect(resolveMotionDecision(requested, { reduced: true }).requested).toBe(requested);
    }
  });
});
