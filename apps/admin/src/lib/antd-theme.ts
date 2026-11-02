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
export const ADMIN_PRIMARY_COLOR_STORAGE_KEY = "soymutdb-admin-primary-color";
export const ADMIN_PRIMARY_COLOR_EVENT = "soymutdb-admin-primary-color-changed";
export const ANTD_PRIMARY_OKLCH = BRAND_PRIMARY_OKLCH;
export const ANTD_PRIMARY_OKLCH_DARK = BRAND_PRIMARY_OKLCH_DARK;

const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;

export function isValidAdminPrimaryColor(value: string): boolean {
  return HEX_COLOR_RE.test(value);
}

export function readAdminPrimaryColor(): string {
  if (typeof localStorage === "undefined") return ANTD_PRIMARY_HEX;
  try {
    const stored = localStorage.getItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY);
    return stored && isValidAdminPrimaryColor(stored) ? stored.toLowerCase() : ANTD_PRIMARY_HEX;
  } catch {
    return ANTD_PRIMARY_HEX;
  }
}

export function saveAdminPrimaryColor(value: string): void {
  if (!isValidAdminPrimaryColor(value) || typeof localStorage === "undefined") return;
  const normalized = value.toLowerCase();
  try {
    localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, normalized);
  } catch {
    return;
  }
  window.dispatchEvent(new CustomEvent(ADMIN_PRIMARY_COLOR_EVENT, { detail: normalized }));
}

export function isAdminDark(): boolean {
  return typeof document !== "undefined" && document.documentElement.dataset.theme === "dark";
}

export function createAntdTheme(opts?: {
  dark?: boolean;
  motion?: EffectiveMotionMode;
  primaryColor?: string;
}): ThemeConfig {
  const dark = opts?.dark ?? false;
  const motion = opts?.motion ?? "standard";
  const primaryColor = opts?.primaryColor && isValidAdminPrimaryColor(opts.primaryColor)
    ? opts.primaryColor.toLowerCase()
    : ANTD_PRIMARY_HEX;
  const base = createSoyMutdbTheme(dark);
  const visiblePrimary = opts?.primaryColor
    ? primaryColor
    : dark
      ? ANTD_PRIMARY_OKLCH_DARK
      : ANTD_PRIMARY_OKLCH;

  return {
    ...base,
    token: {
      ...base.token,
      colorPrimary: primaryColor,
      colorInfo: primaryColor,
      colorLink: primaryColor,
      motion: motion !== "off",
      ...(motion === "minimal"
        ? {
            motionDurationFast: "0.08s",
            motionDurationMid: "0.1s",
            motionDurationSlow: "0.15s",
          }
        : {}),
    },
    components: {
      ...base.components,
      Button: { ...base.components?.Button, colorPrimary: visiblePrimary },
      Tag: { ...base.components?.Tag, colorPrimary: visiblePrimary },
      Menu: {
        ...base.components?.Menu,
        itemSelectedBg: visiblePrimary,
        itemSelectedColor: "#fff",
      },
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
