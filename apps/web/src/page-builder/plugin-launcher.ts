/** Pure, fail-closed resolution for plugin launchers rendered by a page. */

import {
  getPluginAvailability,
  type PluginCapability,
} from "@soymutdb/api-client";

export interface PluginLauncherState {
  available: boolean;
  href: string | null;
  reason: string | null;
}

function isHttpsUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return (
      url.protocol === "https:" &&
      Boolean(url.hostname) &&
      !url.username &&
      !url.password &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
}

export function resolvePluginLauncher(
  capability: PluginCapability | undefined,
  assembly: string,
): PluginLauncherState {
  const availability = getPluginAvailability(capability);
  if (!availability.available || !capability) {
    return { available: false, href: null, reason: availability.reason };
  }
  if (!capability.assemblies.includes(assembly)) {
    return {
      available: false,
      href: null,
      reason: "assembly_mismatch",
    };
  }
  if (!capability.public_url || !isHttpsUrl(capability.public_url)) {
    return {
      available: false,
      href: null,
      reason: capability.public_url
        ? "insecure_public_url"
        : "missing_public_url",
    };
  }
  return {
    available: true,
    href: capability.public_url,
    reason: null,
  };
}

/**
 * Resolve a first-party visual plugin. Unlike an external launcher, an
 * embedded graph has no public URL or assembly affinity, but it must still
 * respect every server-owned availability state.
 */
export function resolveEmbeddedPlugin(
  capability: PluginCapability | undefined,
): PluginLauncherState {
  const availability = getPluginAvailability(capability);
  return {
    available: availability.available,
    href: null,
    reason: availability.reason,
  };
}
