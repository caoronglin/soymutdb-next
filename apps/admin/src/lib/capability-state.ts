import {
  getPluginAvailability,
  type PluginCapability,
} from "@soymutdb/api-client";

export type FeatureCapabilityState =
  | "loading"
  | "error"
  | "unknown"
  | "enabled"
  | "disabled";

interface FeatureSnapshot {
  pending?: boolean;
  error?: boolean;
  features?: Record<string, boolean>;
}

export function resolveFeatureState(
  snapshot: FeatureSnapshot,
  key: string,
): FeatureCapabilityState {
  if (snapshot.pending) return "loading";
  if (snapshot.error) return "error";
  if (!snapshot.features || !(key in snapshot.features)) return "unknown";
  return snapshot.features[key] ? "enabled" : "disabled";
}

type PluginStateInput = Pick<
  PluginCapability,
  "installed" | "enabled" | "configured" | "healthy" | "reason"
>;

interface PluginSnapshot {
  pending?: boolean;
  error?: boolean;
  plugins?: Record<string, PluginStateInput>;
}

export interface PluginCapabilityState {
  state: "loading" | "error" | "available" | "unavailable";
  reason: string | null;
}

export function resolvePluginState(
  snapshot: PluginSnapshot,
  key: string,
): PluginCapabilityState {
  if (snapshot.pending) return { state: "loading", reason: null };
  if (snapshot.error) return { state: "error", reason: null };
  const availability = getPluginAvailability(
    snapshot.plugins?.[key] as PluginCapability | undefined,
  );
  return {
    state: availability.available ? "available" : "unavailable",
    reason: availability.reason,
  };
}
