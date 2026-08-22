import { describe, expect, it } from "vitest";
import { parseMotionPreference, resolveMotionDecision } from "../motion-policy";

describe("motion policy", () => {
  it("forces reduced-motion and an explicit off preference to off", () => {
    expect(resolveMotionDecision("standard", { reduced: true })).toMatchObject({
      effective: "off",
      reason: "reduced-motion",
    });
    expect(resolveMotionDecision("off", {})).toMatchObject({
      effective: "off",
      reason: "preference",
    });
  });

  it("degrades auto and standard on constrained sessions without elevating minimal", () => {
    expect(resolveMotionDecision("auto", { saveData: true }).effective).toBe("minimal");
    expect(resolveMotionDecision("standard", { lowResource: true }).effective).toBe("minimal");
    expect(
      resolveMotionDecision("minimal", { saveData: false, lowResource: false }).effective,
    ).toBe("minimal");
  });

  it("uses standard motion for an unconstrained auto session", () => {
    expect(resolveMotionDecision("auto", {}).effective).toBe("standard");
  });

  it("honors a session downgrade ceiling after resource pressure clears", () => {
    expect(resolveMotionDecision("standard", {}, "minimal")).toMatchObject({
      effective: "minimal",
      reason: "session-downgrade",
    });
  });

  it("reads current and legacy stored preferences safely", () => {
    expect(parseMotionPreference('{"intensity":"off"}')).toBe("off");
    expect(parseMotionPreference('{"intensity":"normal","explicit":true}')).toBe("standard");
    expect(parseMotionPreference('{"intensity":"normal","explicit":false}')).toBe("auto");
    expect(parseMotionPreference("not json")).toBe("auto");
  });
});
