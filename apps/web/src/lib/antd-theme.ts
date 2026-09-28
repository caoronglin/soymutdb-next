import {
  BRAND_PRIMARY_HEX,
  BRAND_PRIMARY_OKLCH,
  BRAND_PRIMARY_OKLCH_DARK,
  createSoyMutdbTheme,
  type ThemeConfig,
} from "@soymutdb/ui-react";
import type { Locale } from "antd/es/locale";
import type { EffectiveMotionMode } from "./motion-policy";

export const ANTD_PRIMARY_HEX = BRAND_PRIMARY_HEX;
export const ANTD_PRIMARY_OKLCH = BRAND_PRIMARY_OKLCH;
export const ANTD_PRIMARY_OKLCH_DARK = BRAND_PRIMARY_OKLCH_DARK;
export const ANTD_FONT_FAMILY = '"HarmonyOS Sans SC", ui-sans-serif, system-ui, sans-serif';

/** Ant Design theme uses the shared SoyMutDB tokens plus the app motion policy. */
export function createAntdTheme(opts?: {
  dark?: boolean;
  motion?: EffectiveMotionMode;
}): ThemeConfig {
  const dark = opts?.dark ?? false;
  const motion = opts?.motion ?? "standard";
  const base = createSoyMutdbTheme(dark);
  return {
    ...base,
    token: {
      ...base.token,
      motion: motion !== "off",
      ...(motion === "minimal"
        ? {
            motionDurationFast: "0.08s",
            motionDurationMid: "0.1s",
            motionDurationSlow: "0.15s",
          }
        : {}),
    },
  };
}

export async function loadAntdLocale(lng: string): Promise<Locale> {
  if (lng.toLowerCase().startsWith("zh")) {
    const [locale] = await Promise.all([
      import("antd/locale/zh_CN"),
      import("dayjs/locale/zh-cn"),
    ]);
    return locale.default;
  }
  const [locale] = await Promise.all([
    import("antd/locale/en_US"),
    import("dayjs/locale/en"),
  ]);
  return locale.default;
}
