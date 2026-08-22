export type MotionPreference = "auto" | "standard" | "minimal" | "off";
export type EffectiveMotionMode = Exclude<MotionPreference, "auto">;
export type MotionSessionCeiling = Exclude<EffectiveMotionMode, "off">;

export interface MotionSignals {
  reduced?: boolean;
  saveData?: boolean;
  lowResource?: boolean;
}

export interface MotionDecision {
  requested: MotionPreference;
  effective: EffectiveMotionMode;
  reason:
    | "auto"
    | "preference"
    | "reduced-motion"
    | "save-data"
    | "low-resource"
    | "session-downgrade";
}

/** Parse the persisted preference, including the previous normal vocabulary. */
export function parseMotionPreference(raw: string | null): MotionPreference {
  if (!raw) return "auto";
  try {
    const stored = JSON.parse(raw) as { intensity?: string; explicit?: boolean } | null;
    if (stored?.intensity && ["auto", "standard", "minimal", "off"].includes(stored.intensity)) {
      return stored.intensity as MotionPreference;
    }
    if (stored?.intensity === "normal" || stored?.intensity === "expressive") {
      return stored.explicit === false ? "auto" : "standard";
    }
  } catch {
    // Malformed storage is equivalent to no preference.
  }
  return "auto";
}

/** Keep Admin's AntD motion policy identical to the public application. */
export function resolveMotionDecision(
  requested: MotionPreference,
  signals: MotionSignals,
  sessionCeiling: MotionSessionCeiling = "standard",
): MotionDecision {
  if (signals.reduced) {
    return { requested, effective: "off", reason: "reduced-motion" };
  }
  if (requested === "off") {
    return { requested, effective: "off", reason: "preference" };
  }

  const preferred = requested === "auto" ? "standard" : requested;
  if (signals.saveData && preferred === "standard") {
    return { requested, effective: "minimal", reason: "save-data" };
  }
  if (signals.lowResource && preferred === "standard") {
    return { requested, effective: "minimal", reason: "low-resource" };
  }
  if (sessionCeiling === "minimal" && preferred === "standard") {
    return { requested, effective: "minimal", reason: "session-downgrade" };
  }
  return {
    requested,
    effective: preferred,
    reason: requested === "auto" ? "auto" : "preference",
  };
}
