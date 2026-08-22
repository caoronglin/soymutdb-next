/** Typed client for deployment-installed, signed plugin administration. */

import { http } from "./auth";
import type { PluginCapability } from "./capabilities";

export interface PluginApiCompatibility {
  minimum: string;
  maximum_exclusive: string;
}

export interface PluginRoute {
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
}

export interface PluginResourceLimits {
  max_concurrency: number;
  memory_mb: number;
  timeout_seconds: number;
}

export interface PluginHealthcheck {
  path: string;
  interval_seconds: number;
  timeout_seconds: number;
}

/** Non-sensitive manifest projection. Signatures and config values stay server-side. */
export interface PluginManifestMetadata {
  manifest_version: 1;
  key: string;
  version: string;
  api_compatibility: PluginApiCompatibility;
  license: string;
  config_schema: Record<string, unknown>;
  routes: PluginRoute[];
  task_queues: string[];
  resource_limits: PluginResourceLimits;
  healthcheck: PluginHealthcheck;
  assemblies: string[];
  uninstall_semantics:
    | "disable_only"
    | "retain_data"
    | "deployment_purge_required";
}

export interface AdminPluginResponse {
  key: string;
  status: PluginCapability;
  manifest: PluginManifestMetadata | null;
}

export interface AdminPluginsResponse {
  plugins: Record<string, AdminPluginResponse>;
}

export const adminPluginsApi = {
  list() {
    return http.get<AdminPluginsResponse>("/admin/plugins");
  },
  get(key: string) {
    return http.get<AdminPluginResponse>(
      `/admin/plugins/${encodeURIComponent(key)}`,
    );
  },
  setEnabled(key: string, enabled: boolean) {
    return http.patch<AdminPluginResponse>(
      `/admin/plugins/${encodeURIComponent(key)}/state`,
      { json: { enabled } },
    );
  },
};
