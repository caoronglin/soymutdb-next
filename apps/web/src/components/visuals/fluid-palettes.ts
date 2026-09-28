/**
 * Fluid palettes shared by `FluidGradient.vue` and the home hero.
 *
 * These live in a plain `.ts` module (not inside the SFC) because
 * `withDefaults(defineProps<...>(), {...})` is hoisted outside `setup()` and
 * therefore cannot reference a locally declared `const`.
 *
 * `HERO_PALETTES` is ported verbatim from the React baseline
 * (`apps/web/src/components/home/antd-home.tsx` at
 * d3904c2105f34e5d74f3ae3a163d6b25f075bf64). The first entry is the deep
 * science-green brand ramp used by the full-width hero.
 */
export const HERO_PALETTES: readonly string[][] = [
  ["#052a1f", "#0d4a37", "#1b7a52", "#2f9e6b", "#0c3326"],
  ["#171a3a", "#1a3870", "#2d5f9e", "#4a8ac4", "#0d1f4a"],
  ["#0f2b1f", "#0d4a37", "#1b6b4a", "#3f8f65", "#0a2b1a"],
];

/** Default palette for the full-width hero (React `HERO_PALETTES[0]`). */
export const DEFAULT_FLUID_COLORS = HERO_PALETTES[0];
