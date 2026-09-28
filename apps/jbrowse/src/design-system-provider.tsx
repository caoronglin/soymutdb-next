import * as React from "react";
import { AntdApp, ConfigProvider, createSoyMutdbTheme } from "@soymutdb/ui-react";
import type { Locale } from "antd/es/locale";
import i18n from "@soymutdb/i18n";

function isDark(): boolean {
    return (
        typeof document !== "undefined" &&
        document.documentElement.getAttribute("data-theme") === "dark"
    );
}

async function loadLocale(language: string): Promise<Locale> {
    return language.toLowerCase().startsWith("zh")
        ? (await import("antd/locale/zh_CN")).default
        : (await import("antd/locale/en_US")).default;
}

/** AntD 6 boundary shared by every standalone JBrowse surface. */
export function DesignSystemProvider({ children }: { children: React.ReactNode }) {
    const [dark, setDark] = React.useState(isDark);
    const [locale, setLocale] = React.useState<Locale>();
    const [motion, setMotion] = React.useState(() => {
        if (typeof window === "undefined") return true;
        const saveData = (
            navigator as Navigator & { connection?: { saveData?: boolean } }
        ).connection?.saveData;
        return !saveData && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    });

    React.useEffect(() => {
        let active = true;
        const applyLocale = (language: string) => {
            void loadLocale(language).then((next) => {
                if (active) setLocale(next);
            });
        };
        applyLocale(i18n.language);
        i18n.on("languageChanged", applyLocale);
        return () => {
            active = false;
            i18n.off("languageChanged", applyLocale);
        };
    }, []);

    React.useEffect(() => {
        const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
        const updateMotion = () => {
            const saveData = (
                navigator as Navigator & { connection?: { saveData?: boolean } }
            ).connection?.saveData;
            if (saveData || reduced.matches) setMotion(false);
        };
        const observer = new MutationObserver(() => setDark(isDark()));
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["data-theme"],
        });
        reduced.addEventListener?.("change", updateMotion);
        return () => {
            observer.disconnect();
            reduced.removeEventListener?.("change", updateMotion);
        };
    }, []);

    const theme = React.useMemo(() => {
        const base = createSoyMutdbTheme(dark);
        return { ...base, token: { ...base.token, motion } };
    }, [dark, motion]);

    return (
        <ConfigProvider locale={locale} theme={theme} componentSize="middle">
            <AntdApp>{children}</AntdApp>
        </ConfigProvider>
    );
}
