/**
 * @soymutdb/ui-vue — the framework-facing design-system facade (plan §7 / D4).
 *
 * Business code (apps/web, apps/admin) MUST import UI primitives from here,
 * never from `antdv-next` directly. This is the single seam that binds us to
 * Antdv Next 1.x: an upstream minor/major change surfaces as a facade
 * contract-test failure first, before it can ripple through every page.
 *
 * The design tokens (brand colors, radii, motion) are shared through
 * @soymutdb/design-tokens; the AntD-specific ThemeConfig is assembled here so a
 * future break pins to one place.
 */
import { theme as antdTheme, type ThemeConfig } from "antdv-next";

import { brandTokens } from "./design-tokens";

export {
  Button,
  Card,
  ConfigProvider,
  Input,
  Layout,
  Result,
  Space,
  Tag,
  Typography,
} from "antdv-next";

/**
 * Hex seed handed to AntD's token derivation.
 *
 * AntD derives its whole colour ramp with tinycolor, which cannot parse oklch:
 * feeding it `oklch(...)` silently produces a broken (near-black) primary. The
 * React portal documented exactly this trap and seeded with hex, then overrode
 * the user-visible tokens at component level. See
 * `d3904c2105f34e5d74f3ae3a163d6b25f075bf64:apps/web/src/lib/antd-theme.ts`.
 */
export const BRAND_PRIMARY_HEX = "#2f6f4f";
/** oklch primary shared with Tailwind's --primary (same brand hue family). */
export const BRAND_PRIMARY_OKLCH = "oklch(0.46 0.13 152)";
/** Dark-mode primary: lifted for contrast on the dark surfaces. */
export const BRAND_PRIMARY_OKLCH_DARK = "oklch(0.55 0.14 152)";

export type { ThemeConfig };

/**
 * Build the ConfigProvider theme. Business code passes a dark flag; the token
 * values stay here so every surface renders the same brand green.
 */
export function createThemeConfig(opts: { dark?: boolean }): ThemeConfig {
  const dark = opts.dark ?? false;
  const primaryOklch = dark ? BRAND_PRIMARY_OKLCH_DARK : BRAND_PRIMARY_OKLCH;

  return {
    algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      // Hex only: this value feeds tinycolor's derivation chain.
      colorPrimary: BRAND_PRIMARY_HEX,
      colorInfo: BRAND_PRIMARY_HEX,
      colorLink: BRAND_PRIMARY_HEX,
      fontFamily: brandTokens.fontFamily,
      // Heading scale shared with the portal's type tokens.
      fontSizeHeading1: 40,
      fontSizeHeading2: 30,
      fontSizeHeading3: 24,
      fontSizeHeading4: 20,
      fontSizeHeading5: 16,
      borderRadius: brandTokens.radius,
    },
    components: {
      // The high-traffic tokens take the exact brand oklch, because a derived
      // ramp from the hex seed lands a few ΔE away from Tailwind's --primary.
      Button: { colorPrimary: primaryOklch },
      Tag: { colorPrimary: primaryOklch },
      Menu: { itemSelectedBg: primaryOklch, itemSelectedColor: "#fff" },
    },
  };
}

export * from "./design-tokens";
