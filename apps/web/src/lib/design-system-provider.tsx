import * as React from "react";
import type { Locale } from "antd/es/locale";
import i18n from "@soymutdb/i18n";
import { App as AntdApp, ConfigProvider } from "./antd";
import { createAntdTheme, loadAntdLocale } from "./antd-theme";
import { useAnimation } from "./animation-context";
import { useTheme } from "./theme-provider";

/** One AntD 6-compatible boundary for locale, tokens, theme and motion. */
export function DesignSystemProvider({ children }: { children: React.ReactNode }) {
  const { theme: colorTheme } = useTheme();
  const { intensity: motion } = useAnimation();
  const [locale, setLocale] = React.useState<Locale | null>(null);

  React.useEffect(() => {
    let active = true;
    const apply = (language: string) => {
      void loadAntdLocale(language).then((nextLocale) => {
        if (active) setLocale(nextLocale);
      });
    };
    apply(i18n.language);
    i18n.on("languageChanged", apply);
    return () => {
      active = false;
      i18n.off("languageChanged", apply);
    };
  }, []);

  const theme = React.useMemo(
    () => createAntdTheme({ dark: colorTheme === "dark", motion }),
    [colorTheme, motion],
  );

  return (
    <ConfigProvider
      componentSize="middle"
      locale={locale ?? undefined}
      theme={theme}
      variant="outlined"
    >
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
