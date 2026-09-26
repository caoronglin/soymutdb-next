/**
 * Build-time feature gating for portal routes.
 *
 * Gating keys off the route's ``componentKey``, not its ``name``: the GBrowse
 * route is named ``search-gbrowse`` but its component key is ``gbrowse``, so a
 * name-based check silently missed it in a core-only deployment.
 *
 * Kept free of component imports so it can be unit-tested without loading the
 * whole view tree (the router imports every view).
 */

export const JBROWSE_COMPONENT_KEYS: ReadonlySet<string> = new Set(["browser", "gbrowse"]);

/** True when a route's backing service is disabled in this deployment. */
export function isFeatureGated(componentKey: string, jbrowseEnabled: boolean): boolean {
  return !jbrowseEnabled && JBROWSE_COMPONENT_KEYS.has(componentKey);
}
