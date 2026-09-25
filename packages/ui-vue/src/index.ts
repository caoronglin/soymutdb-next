/**
 * @soymutdb/ui-vue — the framework-facing design-system facade (plan §7 / D4).
 *
 * Business code (apps/web, the future admin) MUST import UI primitives from
 * here, never from `antdv-next` directly. This is the single seam that binds us
 * to Antdv Next 1.x: an upstream minor/major change surfaces as a facade
 * contract-test failure first, before it can ripple through every page.
 *
 * The design tokens (brand colors, radii, motion) are shared through
 * @soymutdb/design-tokens; the AntD-specific ThemeConfig is assembled here so a
 * future break pins to one place.
 */
import { theme as antdTheme, type ThemeConfig } from "antdv-next";

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

/** oklch primary seed shared with Tailwind's --primary (same brand hue family). */
export const BRAND_PRIMARY_OKLCH = "oklch(0.46 0.13 152)";

export type { ThemeConfig };

/**
 * Build the ConfigProvider theme. Business code passes a dark flag + the motion
 * mode chosen by the app's motion policy; the token values stay here.
 */
export function createThemeConfig(opts: { dark?: boolean }): ThemeConfig {
  return {
    algorithm: opts.dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: BRAND_PRIMARY_OKLCH,
      borderRadius: 10,
    },
  };
}

export * from "./design-tokens";
