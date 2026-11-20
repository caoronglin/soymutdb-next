import type { ReactNode } from "react";
// The package's `module` entry (`es/`) uses extensionless imports that the
// Vitest ESM loader cannot resolve; the CommonJS `lib/` build is the same code
// and resolves through Node's extension lookup.
import TweenOne from "rc-tween-one/lib/TweenOne";
import { useAdminMotion } from "../lib/motion-preference";
import { pageRevealAnimation } from "../lib/page-motion";

interface AdminPageTransitionProps {
  children: ReactNode;
  /**
   * Changes when the routed page changes. Remounting the wrapper is what
   * replays the entrance on navigation; the routed page itself mounts anew on
   * a route change anyway.
   */
  motionKey: string;
  className?: string;
}

/**
 * Page-level entrance for the console, driven by TweenOne and gated by the
 * console motion policy (`prefers-reduced-motion` → `off`). With motion off it
 * renders children directly: no wrapper, no transform, no timeline.
 */
export function AdminPageTransition({ children, motionKey, className }: AdminPageTransitionProps) {
  const { effective } = useAdminMotion();
  const animation = pageRevealAnimation(effective);
  if (animation === null) {
    return (
      <div key={motionKey} className={className}>
        {children}
      </div>
    );
  }
  return (
    <TweenOne key={motionKey} className={className} animation={animation} killPrevAnim>
      {children}
    </TweenOne>
  );
}