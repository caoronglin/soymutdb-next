/**Client for server-owned public/admin feature capabilities.*/

import { http } from "./client";

export interface PluginCapability {
  version: string | null;
  installed: boolean;
  enabled: boolean;
  configured: boolean;
  healthy: boolean;
  public_url: string | null;
  assemblies: string[];
  reason: string | null;
}

export interface DatabaseCapabilities {
  authoritative: "postgresql";
  analytics: "postgresql" | null;
}

/** Summary embedded in the public capabilities payload, not the endpoint response. */
export interface SequenceCapabilitiesSummary {
  available: boolean;
  engine: string | null;
  engine_version: string | null;
  reason: string | null;
  max_inline_sequence: number;
  max_pattern: number;
  max_hits: number;
  k_range: number[];
  genetic_codes: number[];
  coordinate_system_internal: string;
  coordinate_system_public: string;
  programs: string[];
  formats: string[];
}

export interface PublicCapabilitiesResponse {
  version: number;
  features: Record<string, boolean>;
  plugins: Record<string, PluginCapability>;
  databases: DatabaseCapabilities;
  sequence: SequenceCapabilitiesSummary;
}

export interface PluginAvailability {
  available: boolean;
  reason: string | null;
}

/**
 * Resolve the server-owned plugin state into a stable UI/task-dispatch guard.
 * The ordered checks match the API's fail-closed lifecycle semantics.
 */
export function getPluginAvailability(
  capability: PluginCapability | undefined,
): PluginAvailability {
  if (!capability?.installed) {
    return { available: false, reason: "not_installed" };
  }
  if (!capability.enabled) {
    return { available: false, reason: "plugin_disabled" };
  }
  if (!capability.configured) {
    return { available: false, reason: "not_configured" };
  }
  if (!capability.healthy) {
    return {
      available: false,
      reason: capability.reason || "plugin_unhealthy",
    };
  }
  return { available: true, reason: null };
}

export interface FeatureDefinitionResponse {
  key: string;
  enabled: boolean;
  default: boolean;
  public: boolean;
  description: string;
  disable_behavior: string;
}

export interface AdminFeaturesResponse {
  version: number;
  features: FeatureDefinitionResponse[];
}

export const capabilitiesApi = {
  get() {
    return http.get<PublicCapabilitiesResponse>("/capabilities");
  },
  adminGet() {
    return http.get<AdminFeaturesResponse>("/admin/features");
  },
  adminUpdate(features: Record<string, boolean>) {
    return http.put<AdminFeaturesResponse>("/admin/features", { json: { features } });
  },
};
