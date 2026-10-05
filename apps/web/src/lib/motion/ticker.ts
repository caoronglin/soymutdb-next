export type MotionSubscriber = (time: number) => void;
const subscribers = new Set<MotionSubscriber>();
let raf = 0;
let lastTick = 0;
let accumulator = 0;
const interval = 1000 / 30;
// The frame budget is accumulated from elapsed time rather than compared as
// `time - lastDispatch >= interval`. At 60Hz the gap between every second frame
// is 33.33333333333333, one ULP below `1000 / 30` (33.333333333333336), so that
// comparison was always false and the frame was dropped every time — the ticker
// settled at ~20fps while advertising 30. Accumulating real elapsed time removes
// the threshold a frame has to clear, so rounding in the constant can no longer
// swallow one. The remainder is carried so the long-run rate stays 30fps.
//
// `lastTick` tracks the previous frame and `accumulator` the time owed since
// the last dispatch. The first frame is handled apart from the rest: its
// timestamp is measured from navigation start, so folding it into the
// accumulator would bill the ticker for the whole page load. It is compared
// against the interval instead, which keeps both documented first-frame
// behaviours (a frame inside the window is dropped, one past it is delivered)
// and leaves no residue for the next frame to trip over.
//
// Steady state clears the accumulator on dispatch rather than taking a
// modulus. A modulus hands the leftover back: a 50ms frame leaves
// `50 % 33.33 = 16.67` credit, and the very next 16.67ms frame then clears the
// interval again, so two dispatches land 16.67ms apart — the contract the
// throttle exists to enforce. A frame that ran long is behind, not a
// prepayment, so nothing is carried.
//
// The epsilon is 1ns against a 33ms interval. Without it the sum of two 60Hz
// gaps lands one ULP short of `1000 / 30` and the pair is dropped, which is the
// same defect in the opposite direction.
const FRAME_EPSILON = 1e-6;
function schedule() { if (!raf && subscribers.size && typeof window !== "undefined" && !document.hidden) raf = window.requestAnimationFrame(tick); }
function tick(time: number) { raf = 0; if (typeof document !== "undefined" && document.hidden) return; if (!lastTick) { lastTick = time; if (time >= interval) subscribers.forEach((fn) => fn(time)); else accumulator = time; schedule(); return; } accumulator += time - lastTick; lastTick = time; if (accumulator + FRAME_EPSILON >= interval) { accumulator = 0; subscribers.forEach((fn) => fn(time)); } schedule(); }
function visibilityChanged() { if (typeof document === "undefined") return; if (document.hidden) { if (raf) cancelAnimationFrame(raf); raf = 0; } else schedule(); }
if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
export function subscribeMotion(fn: MotionSubscriber): () => void { subscribers.add(fn); schedule(); return () => { subscribers.delete(fn); if (!subscribers.size && raf) { cancelAnimationFrame(raf); raf = 0; } }; }
export function __resetMotionTickerForTests() { subscribers.clear(); if (raf && typeof window !== "undefined") window.cancelAnimationFrame(raf); raf = 0; lastTick = 0; accumulator = 0; }
