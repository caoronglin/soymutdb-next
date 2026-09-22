/**
 * Framework-neutral design tokens (Phase C seam; plan §7).
 *
 * The single source of truth for the brand primitives shared by the React
 * portal (AntD theme + Tailwind), the Vue facade (@soymutdb/ui-vue) and the
 * future Vue app (Tailwind). Values are the SoyMutDB brand oklch family; adding
 * a token here makes it available to every renderer without duplication.
 */
export const brandTokens = {
  /** Primary brand color (oklch), light. */
  primary: "oklch(0.46 0.13 152)",
  /** Primary brand color (oklch), dark (lifted for contrast). */
  primaryDark: "oklch(0.70 0.12 151)",
  /** Base radius (rem), matches the AntD token. */
  radius: 10,
  /** Font stack shared by body/display text. */
  fontFamily:
    'system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif',
} as const;

export type BrandTokens = typeof brandTokens;

/** CSS custom properties for the token set, for Tailwind/CSS consumers. */
export function brandCssVariables(prefix = "smdb"): Record<string, string> {
  return {
    [`--${prefix}-primary`]: brandTokens.primary,
    [`--${prefix}-primary-dark`]: brandTokens.primaryDark,
    [`--${prefix}-radius`]: `${brandTokens.radius / 16}rem`,
    [`--${prefix}-font`]: brandTokens.fontFamily,
  };
}
