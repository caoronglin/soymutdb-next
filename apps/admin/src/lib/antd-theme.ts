/**
 * AntD 6-compatible theme wiring for SoyMutDB Admin.
 *
 * 与 apps/web/src/lib/antd-theme.ts 同一策略（docs/design/upgrade-plan.md
 * §二 + oracle 修正）：
 *
 * - OKLCH 覆盖方案：`colorPrimary` 只喂 hex seed `#2f6f4f`（tinycolor 生成链
 *   不报错），用户可见高频 token（Button/Tag/Menu 选中态）用 components 级
 *   `oklch(0.46 0.13 152)` 覆盖，暗色单独覆盖。ΔE < 1 验收由 G1 取色比对。
 * - motion 由 DesignSystemProvider 的统一决策传入；off 关闭 AntD motion，
 *   minimal 缩短 timing token，standard 使用默认时序。
 * - 字体：HarmonyOS Sans SC（与 Tailwind --font-sans 同源）。
 * - 暗色：跟随 admin 现有 `data-theme` 属性（admin-header 切换），
 *   AntdProvider（main.tsx）用 MutationObserver 监听并重建 theme。
 * - i18n locale（oracle 遗漏 #1）：按 i18next `languageChanged` 事件驱动
 *   ConfigProvider locale prop（组件接线在 main.tsx 的 AntdProvider）；locale
 *   包按需 import（约 8KB）。
 *
 * 注意：本文件为纯 .ts（无 JSX），Provider 组件在 main.tsx（.tsx）。
 */
import { theme as antdTheme, type ThemeConfig } from "./antd";
import type { Locale } from "antd/es/locale";
import type { EffectiveMotionMode } from "./motion-policy";

/** hex seed —— 只用于 tinycolor 生成链，避免 oklch 解析失败。 */
export const ANTD_PRIMARY_HEX = "#2f6f4f";
export const ADMIN_PRIMARY_COLOR_STORAGE_KEY = "soymutdb-admin-primary-color";
export const ADMIN_PRIMARY_COLOR_EVENT = "soymutdb-admin-primary-color-changed";

const HEX_COLOR_RE = /^#[0-9a-f]{6}$/i;

export function isValidAdminPrimaryColor(value: string): boolean {
    return HEX_COLOR_RE.test(value);
}

export function readAdminPrimaryColor(): string {
    if (typeof localStorage === "undefined") return ANTD_PRIMARY_HEX;
    try {
        const stored = localStorage.getItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY);
        return stored && isValidAdminPrimaryColor(stored)
            ? stored.toLowerCase()
            : ANTD_PRIMARY_HEX;
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
/** 亮色下用户可见高频 token 的 OKLCH 值（与 Tailwind --primary 同色系）。 */
export const ANTD_PRIMARY_OKLCH = "oklch(0.46 0.13 152)";
/** 暗色下单独覆盖（略提亮保证可读性）。 */
export const ANTD_PRIMARY_OKLCH_DARK = "oklch(0.55 0.14 152)";

export const ANTD_FONT_FAMILY =
    '"HarmonyOS Sans SC", ui-sans-serif, system-ui, sans-serif';

/** Admin 暗色开关 —— 由 admin-header 维护 `data-theme` 属性。 */
export function isAdminDark(): boolean {
    if (typeof document === "undefined") return false;
    return document.documentElement.getAttribute("data-theme") === "dark";
}

/**
 * 构建 ConfigProvider theme。
 *
 * @param opts.dark 暗色：algorithm 切 darkAlgorithm + 独立 OKLCH 覆盖。
 * @param opts.primaryColor Admin 选择的 6 位十六进制主色。
 */
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
    const primaryOklch = dark ? ANTD_PRIMARY_OKLCH_DARK : ANTD_PRIMARY_OKLCH;
    const primaryVisibleColor = opts?.primaryColor ? primaryColor : primaryOklch;
    const minimalMotion = motion === "minimal";

    return {
        algorithm: dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
            // hex seed —— oklch 值只出现在 components 级覆盖里
            colorPrimary: primaryColor,
            colorInfo: primaryColor,
            colorLink: primaryColor,
            fontFamily: ANTD_FONT_FAMILY,
            // §二 字号映射：display/h1/h2 仍走 Tailwind；AntD heading 显式映射
            fontSizeHeading1: 40, // 2.5rem (h1)
            fontSizeHeading2: 30, // 1.875rem (h2)
            fontSizeHeading3: 24, // 1.5rem (h3)
            fontSizeHeading4: 20, // 1.25rem
            fontSizeHeading5: 16, // 1rem
            borderRadius: 10,
            // reduced-motion（oracle R2）：motion:false 时 antd 的 getAliasToken
            // 会把 motionDurationFast/Mid/Slow 与 motionUnit 全部归零
            motion: motion !== "off",
            ...(minimalMotion
                ? {
                    motionDurationFast: "0.08s",
                    motionDurationMid: "0.1s",
                    motionDurationSlow: "0.15s",
                }
                : {}),
        },
        components: {
            // 高频组件优先使用 Admin 选择的颜色；未选择时保持亮/暗默认方案。
            Button: { colorPrimary: primaryVisibleColor },
            Tag: { colorPrimary: primaryVisibleColor },
            Menu: {
                itemSelectedBg: primaryVisibleColor,
                itemSelectedColor: "#fff",
            },
        },
    };
}

/**
 * 按需加载 AntD + dayjs locale（约 8KB）。
 *
 * TODO(路由级懒加载)：可在路由 loader 中预载对应 locale，将「事件驱动加载」
 * 升级为「路由驱动加载」。
 */
export async function loadAntdLocale(lng: string): Promise<Locale> {
    const normalized = lng.toLowerCase();
    if (normalized.startsWith("zh")) {
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
