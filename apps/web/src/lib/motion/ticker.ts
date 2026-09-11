export type MotionSubscriber = (time: number) => void;
const subscribers = new Set<MotionSubscriber>();
let raf = 0;
let last = 0;
const interval = 1000 / 30;
function schedule() { if (!raf && subscribers.size && typeof window !== "undefined" && !document.hidden) raf = window.requestAnimationFrame(tick); }
function tick(time: number) { raf = 0; if (typeof document !== "undefined" && document.hidden) return; if (time - last < interval) { schedule(); return; } last = time; subscribers.forEach((fn) => fn(time)); schedule(); }
function visibilityChanged() { if (typeof document === "undefined") return; if (document.hidden) { if (raf) cancelAnimationFrame(raf); raf = 0; } else schedule(); }
if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
export function subscribeMotion(fn: MotionSubscriber): () => void { subscribers.add(fn); schedule(); return () => { subscribers.delete(fn); if (!subscribers.size && raf) { cancelAnimationFrame(raf); raf = 0; } }; }
export function __resetMotionTickerForTests() { subscribers.clear(); if (raf && typeof window !== "undefined") window.cancelAnimationFrame(raf); raf = 0; last = 0; }
