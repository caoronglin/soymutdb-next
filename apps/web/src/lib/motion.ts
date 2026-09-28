/**
 * Portal motion runtime — the single source of truth for "may we animate?".
 *
 * The CSS side of the system is `style.css`'s `--anim-*` token block plus the
 * `Keyframes`/`View Transition` sections. This module is the runtime that was
 * missing after the React portal was retired: it decides *whether* motion may
 * run and exposes the *timings* straight from those CSS tokens, so CSS and JS
 * cannot drift into two duration vocabularies.
 *
 * Design rules:
 *  - Policy is one pure function (`resolveMotionDecision`) with no DOM access,
 *    so the accessibility contract is unit-testable without a browser.
 *  - `prefers-reduced-motion: reduce` and the persisted `off` preference both
 *    resolve to `off`; reduced motion always wins to honour the OS setting.
 *  - The resolved mode is mirrored onto `<html data-anim="...">`, which is the
 *    hook `style.css` already defines (`[data-anim="off"] *` kills every
 *    animation/transition, `[data-anim="minimal"]` shortens the tokens).
 *  - SSR / prerender safe: with no `window` everything resolves to `reduced`
 *    and no DOM API is touched.
 *
 * Nothing here is a third-party animation engine: bounded CSS transitions plus
 * the native View Transitions API only.
 */
import { computed, readonly, ref, watch, nextTick, type ComputedRef, type Ref } from "vue";

export type MotionPreference = "auto" | "standard" | "minimal" | "off";

/** The preference after policy resolution; `auto` only survives as a request. */
export type EffectiveMotionMode = Exclude<MotionPreference, "auto">;

export type MotionReason = "auto" | "preference" | "reduced-motion";

export interface MotionSignals {
  /** `prefers-reduced-motion: reduce`. */
  reduced: boolean;
}

export interface MotionDecision {
  requested: MotionPreference;
  effective: EffectiveMotionMode;
  /** True when the caller may play an entrance/route animation. */
  animate: boolean;
  reason: MotionReason;
}

/**
 * Resolve one monotonic motion decision.
 *
 * Pure: no DOM, no storage, no module state — the four reduced × preference
 * combinations are exactly the unit-test matrix.
 */
export function resolveMotionDecision({
  reduced,
  preference,
}: {
  reduced: boolean;
  preference: MotionPreference;
}): MotionDecision {
  if (reduced) {
    return { requested: preference, effective: "off", animate: false, reason: "reduced-motion" };
  }
  if (preference === "off") {
    return { requested: preference, effective: "off", animate: false, reason: "preference" };
  }
  // `minimal` still animates — it just resolves to the shorter CSS token set
  // via `data-anim="minimal"`; `auto` is the standard experience.
  const effective: EffectiveMotionMode = preference === "auto" ? "standard" : preference;
  return {
    requested: preference,
    effective,
    animate: true,
    reason: preference === "auto" ? "auto" : "preference",
  };
}

/** Parse the persisted preference; malformed storage behaves like `auto`. */
export function parseMotionPreference(raw: string | null): MotionPreference {
  if (!raw) return "auto";
  try {
    const stored = JSON.parse(raw) as { intensity?: string } | null;
    const intensity = stored?.intensity;
    if (
      intensity === "auto" ||
      intensity === "standard" ||
      intensity === "minimal" ||
      intensity === "off"
    ) {
      return intensity;
    }
  } catch {
    // Malformed storage is equivalent to no preference.
  }
  return "auto";
}

/** The `style.css` token names this module consumes. */
const TOKEN = {
  duration: "--anim-duration",
  durationFast: "--anim-duration-fast",
  durationSlow: "--anim-duration-slow",
  easing: "--anim-easing",
  easeSpring: "--anim-easing-spring",
  stagger: "--anim-stagger",
} as const;

export interface MotionTokens {
  durationMs: number;
  durationFastMs: number;
  durationSlowMs: number;
  staggerMs: number;
  easing: string;
  easingSpring: string;
}

/**
 * Hard fallbacks, used for SSR and for a browser that cannot resolve the
 * tokens. They intentionally mirror the `:root` block in `style.css`.
 */
const TOKEN_FALLBACKS: MotionTokens = {
  durationMs: 300,
  durationFastMs: 200,
  durationSlowMs: 500,
  staggerMs: 60,
  easing: "cubic-bezier(0.16, 1, 0.3, 1)",
  easingSpring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
};

/** Minimal structural shape of `CSSStyleDeclaration` so tests can inject one. */
export interface StyleReader {
  getPropertyValue(property: string): string;
}

function parseTimeMs(value: string, fallback: number): number {
  const match = /^\s*(-?\d*\.?\d+)(ms|s)\s*$/.exec(value);
  if (!match) return fallback;
  const amount = Number(match[1]);
  if (!Number.isFinite(amount)) return fallback;
  return match[2] === "s" ? amount * 1000 : amount;
}

/**
 * Read the `--anim-*` tokens off the document root.
 *
 * Reading live (instead of a build-time copy) means an active `data-anim`
 * switch — including the `minimal` token set — flows into JS automatically.
 */
export function readMotionTokens(styles?: StyleReader): MotionTokens {
  const reader =
    styles ??
    (typeof document !== "undefined" ? getComputedStyle(document.documentElement) : undefined);
  const read = (property: string): string => reader?.getPropertyValue(property) ?? "";
  return {
    durationMs: parseTimeMs(read(TOKEN.duration), TOKEN_FALLBACKS.durationMs),
    durationFastMs: parseTimeMs(read(TOKEN.durationFast), TOKEN_FALLBACKS.durationFastMs),
    durationSlowMs: parseTimeMs(read(TOKEN.durationSlow), TOKEN_FALLBACKS.durationSlowMs),
    staggerMs: parseTimeMs(read(TOKEN.stagger), TOKEN_FALLBACKS.staggerMs),
    easing: read(TOKEN.easing).trim() || TOKEN_FALLBACKS.easing,
    easingSpring: read(TOKEN.easeSpring).trim() || TOKEN_FALLBACKS.easingSpring,
  };
}

const STORAGE_KEY = "soymutdb-animation-prefs";
const REDUCED_QUERY = "(prefers-reduced-motion: reduce)";

function readStoredPreference(): MotionPreference {
  if (typeof window === "undefined") return "auto";
  try {
    return parseMotionPreference(window.localStorage.getItem(STORAGE_KEY));
  } catch {
    // Storage can be blocked (private mode); `auto` stays safe.
    return "auto";
  }
}

function readReducedSignal(): boolean {
  // SSR / prerender: no media query can be asked, and the static document must
  // render deterministically — reduced is the conservative answer.
  if (typeof window === "undefined") return true;
  return window.matchMedia?.(REDUCED_QUERY).matches ?? false;
}

// Module state, mirroring `lib/theme.ts`: one owner, no store.
const preference = ref<MotionPreference>(readStoredPreference());
const prefersReduced = ref<boolean>(readReducedSignal());
const decision = computed(() =>
  resolveMotionDecision({ reduced: prefersReduced.value, preference: preference.value }),
);

let stopWatch: (() => void) | null = null;
let detachMedia: (() => void) | null = null;

function applyMotionAttribute(mode: EffectiveMotionMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.anim = mode;
}

/**
 * Own the environment exactly once: mirror the resolved mode onto `<html>`,
 * and follow the OS reduced-motion setting for the lifetime of the page.
 */
function ensureMotionEnvironment(): void {
  if (typeof window === "undefined" || stopWatch) return;

  const media = window.matchMedia?.(REDUCED_QUERY);
  if (media) {
    prefersReduced.value = media.matches;
    const onChange = (): void => {
      prefersReduced.value = media.matches;
    };
    media.addEventListener?.("change", onChange);
    detachMedia = () => media.removeEventListener?.("change", onChange);
  }

  // `sync` so the `<html>` attribute is correct in the same task as the media
  // query change — an OS toggle must not wait for the next flush.
  stopWatch = watch(decision, (next) => applyMotionAttribute(next.effective), {
    immediate: true,
    flush: "sync",
  });
}

export interface UseMotion {
  /** True when no motion should play (reduced motion or the `off` preference). */
  reduced: ComputedRef<boolean>;
  /** Animations honoured from `--anim-duration`. */
  durationMs: ComputedRef<number>;
  /** Per-item offset from `--anim-stagger`, for staggered groups. */
  staggerMs: ComputedRef<number>;
  /** `--anim-easing`, for the rare JS-driven timing. */
  easing: ComputedRef<string>;
  preference: Readonly<Ref<MotionPreference>>;
  setPreference: (next: MotionPreference) => void;
}

export function setMotionPreference(next: MotionPreference): void {
  preference.value = next;
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ intensity: next }));
  } catch {
    // The in-memory selection still applies for this session.
  }
}

/**
 * The one composable components use. Calling it installs the environment on
 * first use (there is no provider to mount), then returns read-only state.
 */
export function useMotion(): UseMotion {
  ensureMotionEnvironment();
  const tokens = computed(() => readMotionTokens());
  return {
    reduced: computed(() => decision.value.effective === "off"),
    durationMs: computed(() => tokens.value.durationMs),
    staggerMs: computed(() => tokens.value.staggerMs),
    easing: computed(() => tokens.value.easing),
    preference: readonly(preference),
    setPreference: setMotionPreference,
  };
}

/** Structural host so tests can inject a fake document. */
export interface RouteMotionHost {
  startViewTransition?: (
    update: () => void | Promise<void>,
  ) => { finished?: Promise<unknown> } | undefined;
}

export interface RouteMotionRouter {
  afterEach(
    handler: (to: { fullPath: string }, from: { fullPath: string }) => void,
  ): () => void;
}

export function supportsViewTransitions(host?: RouteMotionHost | null): boolean {
  const target = host ?? (typeof document === "undefined" ? null : (document as RouteMotionHost));
  return typeof target?.startViewTransition === "function";
}

/**
 * Wrap route navigations in the native View Transitions API.
 *
 * `afterEach` is the only hook that can see the *old* DOM without holding the
 * navigation open: Vue Router has already updated `currentRoute` there but has
 * not flushed the DOM patch yet, so the browser snapshots the outgoing page,
 * the callback awaits `nextTick()` for the incoming one, and the browser
 * cross-fades. Nothing is awaited by the router, so a transition can never
 * block or fail a navigation.
 */
export function installRouteMotion(
  router: RouteMotionRouter,
  host: RouteMotionHost | null = typeof document === "undefined" ? null : (document as RouteMotionHost),
): () => void {
  ensureMotionEnvironment();
  return router.afterEach((to, from) => {
    if (!host || to.fullPath === from.fullPath) return;
    const start = host.startViewTransition;
    if (typeof start !== "function" || decision.value.effective === "off") return;
    // A hidden tab has no compositor frame to drive the pseudo-elements.
    if (typeof document !== "undefined" && document.hidden) return;
    try {
      const transition = start.call(host, () => nextTick()) as
        | { finished?: Promise<unknown> }
        | undefined;
      void transition?.finished?.catch(() => {
        // The visual transition is best-effort; the route already changed.
      });
    } catch {
      // Unsupported/polyfilled hosts must degrade to an instant swap.
    }
  });
}

/** Drop every listener and re-read the environment; used between tests. */
export function __resetMotionForTests(): void {
  stopWatch?.();
  stopWatch = null;
  detachMedia?.();
  detachMedia = null;
  preference.value = readStoredPreference();
  prefersReduced.value = readReducedSignal();
}
