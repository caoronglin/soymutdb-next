import * as React from "react";
import type { Locale } from "antd/es/locale";
import i18n from "@soymutdb/i18n";
import { App as AntdApp, ConfigProvider, Watermark } from "./antd";
import { createAntdTheme, loadAntdLocale } from "./antd-theme";
import { useAnimation } from "./animation-context";
import { useTheme } from "./theme-provider";
import { IS_INTERNAL_SITE } from "./site-variant";

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
      <AntdApp>
        {/* The internal variant serves records that are not published yet. A
            watermark travelling with the page makes an accidental screenshot
            attributable, which is the standard handling for embargoed data. It
            is deliberately not a security boundary: the API enforces the role,
            and this only labels what a screenshot would carry. */}
        {IS_INTERNAL_SITE ? (
          <Watermark
            content={watermarkText(i18n.language)}
            gap={[120, 120]}
            rotate={-22}
            /* antd 6 has no `opacity` prop: the alpha lives in the font color,
               which keeps the mark legible without competing with the data. */
            font={{ fontSize: 14, color: "rgba(0, 0, 0, 0.11)" }}
          >
            {/* `Watermark` accepts no arbitrary DOM props, so the marker a test
                can assert on lives on a wrapper. */}
            <div data-testid="internal-watermark">{children}</div>
          </Watermark>
        ) : (
          children
        )}
      </AntdApp>
    </ConfigProvider>
  );
}

/**
 * Watermark copy: names the variant in the reader's language.
 *
 * A single word is used rather than a sentence because the mark repeats every
 * ~120 px; a long string would tile into an unreadable smear.
 */
function watermarkText(language: string): string {
  return language.toLowerCase().startsWith("zh") ? "未发布数据" : "UNPUBLISHED";
}
