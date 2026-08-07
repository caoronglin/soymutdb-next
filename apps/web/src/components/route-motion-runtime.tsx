import { MotionProvider, useLenis, type MotionConfig } from "@soymutdb/motion";

const CONFIG: MotionConfig = {
  duration: 300,
  durationFast: 200,
  durationSlow: 500,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  easingSpring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  stagger: 60,
  reduced: typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true,
};

function LenisBootstrap() {
  useLenis({ enabled: !CONFIG.reduced });
  return null;
}

export default function RouteMotionRuntime() {
  return <MotionProvider config={CONFIG}><LenisBootstrap /></MotionProvider>;
}
