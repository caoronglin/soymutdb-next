import * as React from "react";
import { App as AntdApp, ConfigProvider } from "./antd";
import type { Locale } from "antd/es/locale";
import i18n from "@soymutdb/i18n";
import { createAntdTheme, isAdminDark, loadAntdLocale } from "./antd-theme";
import {
  parseMotionPreference,
  resolveMotionDecision,
  type MotionPreference,
  type MotionSessionCeiling,
  type MotionSignals,
} from "./motion-policy";

const MOTION_STORAGE_KEY = "soymutdb-animation-prefs";

function readMotionPreference(): MotionPreference {
  if (typeof localStorage === "undefined") return "auto";
  try {
    return parseMotionPreference(localStorage.getItem(MOTION_STORAGE_KEY));
  } catch {
    // A malformed preference is equivalent to auto.
  }
  return "auto";
}

function readMotionSignals(reducedQuery?: MediaQueryList): MotionSignals {
  if (typeof navigator === "undefined") return {};
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection;
  return {
    reduced:
      reducedQuery?.matches ??
      (typeof window !== "undefined" &&
        window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true),
    saveData: connection?.saveData === true,
    lowResource:
      cores <= 4 ||
      memory <= 2 ||
      /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent),
  };
}

/** Admin counterpart of Web's single AntD design-system boundary. */
export function DesignSystemProvider({ children }: { children: React.ReactNode }) {
  const [preference] = React.useState(() => readMotionPreference());
  const [locale, setLocale] = React.useState<Locale | null>(null);
  const [environment, setEnvironment] = React.useState<{
    dark: boolean;
    signals: MotionSignals;
    ceiling: MotionSessionCeiling;
  }>(() => {
    const signals = readMotionSignals();
    return {
      dark: isAdminDark(),
      signals,
      ceiling: signals.saveData || signals.lowResource ? "minimal" : "standard",
    };
  });

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

  React.useEffect(() => {
    const reducedQuery = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const connection = (navigator as Navigator & {
      connection?: EventTarget & { saveData?: boolean };
    }).connection;
    const update = () => {
      const signals = readMotionSignals(reducedQuery);
      setEnvironment((previous) => ({
        dark: isAdminDark(),
        signals,
        ceiling:
          previous.ceiling === "minimal" || signals.saveData || signals.lowResource
            ? "minimal"
            : "standard",
      }));
    };
    const themeObserver = new MutationObserver(update);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    reducedQuery?.addEventListener?.("change", update);
    connection?.addEventListener?.("change", update);
    return () => {
      themeObserver.disconnect();
      reducedQuery?.removeEventListener?.("change", update);
      connection?.removeEventListener?.("change", update);
    };
  }, []);

  const motion = resolveMotionDecision(
    preference,
    environment.signals,
    environment.ceiling,
  ).effective;
  const theme = React.useMemo(
    () => createAntdTheme({ dark: environment.dark, motion }),
    [environment.dark, motion],
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
