/** Framework-neutral SoyMutDB brand tokens used by the React design-system facade. */
export const brandTokens = {
  primary: "oklch(0.46 0.13 152)",
  primaryDark: "oklch(0.70 0.12 151)",
  radius: 10,
  fontFamily: '"HarmonyOS Sans SC", ui-sans-serif, system-ui, sans-serif',
} as const;

export type BrandTokens = typeof brandTokens;

export function brandCssVariables(prefix = "smdb"): Record<string, string> {
  return {
    [`--${prefix}-primary`]: brandTokens.primary,
    [`--${prefix}-primary-dark`]: brandTokens.primaryDark,
    [`--${prefix}-radius`]: `${brandTokens.radius / 16}rem`,
    [`--${prefix}-font`]: brandTokens.fontFamily,
  };
}
