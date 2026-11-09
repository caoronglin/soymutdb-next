/**
 * Page entrance choreography for the admin console.
 *
 * TweenOne (motion.ant.design's engine) plays the timeline; this module only
 * decides *what* the timeline is for the active motion mode, so the policy can
 * be unit-tested without mounting a DOM timeline.
 *
 * Standard mode lifts the page 6px while fading it in. Minimal mode is a pure
 * fade with no movement — cheaper to composite and easier to follow for users
 * who asked for less motion without asking for none. `off` returns `null`, and
 * the caller renders children without a wrapper at all.
 */
import type { EffectiveMotionMode } from "@soymutdb/ui-react";

export interface PageRevealKeyframe {
  opacity?: number;
  y?: number;
  duration: number;
  ease?: string;
}

export function pageRevealAnimation(mode: EffectiveMotionMode): PageRevealKeyframe[] | null {
  if (mode === "off") return null;
  if (mode === "minimal") {
    return [
      { opacity: 0, duration: 0 },
      { opacity: 1, duration: 120, ease: "linear" },
    ];
  }
  return [
    { opacity: 0, y: 6, duration: 0 },
    { opacity: 1, y: 0, duration: 260, ease: "easeOutQuad" },
  ];
}