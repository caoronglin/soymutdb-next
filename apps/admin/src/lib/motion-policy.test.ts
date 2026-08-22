import { describe, expect, it } from "vitest";
import { parseMotionPreference, resolveMotionDecision } from "./motion-policy";

describe("admin motion policy", () => {
  it("shares the auto, standard, minimal and off downgrade rules", () => {
    expect(resolveMotionDecision("auto", {}).effective).toBe("standard");
    expect(resolveMotionDecision("standard", { saveData: true }).effective).toBe("minimal");
    expect(resolveMotionDecision("minimal", {}).effective).toBe("minimal");
    expect(resolveMotionDecision("off", {}).effective).toBe("off");
    expect(resolveMotionDecision("standard", { reduced: true }).effective).toBe("off");
    expect(resolveMotionDecision("standard", {}, "minimal").effective).toBe("minimal");
    expect(parseMotionPreference('{"intensity":"minimal"}')).toBe("minimal");
  });
});
