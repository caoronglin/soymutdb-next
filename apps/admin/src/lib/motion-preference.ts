/**
 * Admin motion preference.
 *
 * The portal has owned a motion policy since 2026-09 (`resolveMotionDecision`),
 * with intensity control, device-adaptive downgrades and reduced-motion
 * compliance. The console had none, so every transition ran at Ant Design's
 * default regardless of `prefers-reduced-motion`.
 *
 * The console deliberately neither reads nor persists a stored preference:
 * it is a separate origin from the portal, so the portal's localStorage value
 * is not reachable here, and an admin-only stored preference would silently
 * outlive the session that set it. What it does honour is the OS-level
 * `prefers-reduced-motion` signal, resolved through the same shared policy as
 * the portal. Anything stronger is a settings feature, not a silent default.
 */
import * as React from "react";
import {
  resolveMotionDecision,
  type EffectiveMotionMode,
  type MotionPreference,
} from "@soymutdb/ui-react";

const LISTENER = "(prefers-reduced-motion: reduce)";

/** Read the OS-level reduced-motion setting, reacting to later changes. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = React.useState(
    () => typeof window !== "undefined" && window.matchMedia(LISTENER).matches,
  );

  React.useEffect(() => {
    const query = window.matchMedia(LISTENER);
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

export interface AdminMotion {
  /** What the user asked for, before accessibility overrides. */
  preference: MotionPreference;
  /** What actually applies; `off` wins over any stored preference. */
  effective: EffectiveMotionMode;
}

export function useAdminMotion(): AdminMotion {
  const reduced = useReducedMotion();
  const decision = resolveMotionDecision("auto", { reduced });
  return { preference: decision.requested, effective: decision.effective };
}
