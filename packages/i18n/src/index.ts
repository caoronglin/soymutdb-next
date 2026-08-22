import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en/common.json";
import zh from "./locales/zh/common.json";

export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

/** Detect the user's preferred language from localStorage or the browser. */
export function detectLanguage(): SupportedLanguage {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  const stored = localStorage.getItem("soymutdb_lang");
  if (stored && SUPPORTED_LANGUAGES.includes(stored as SupportedLanguage)) {
    return stored as SupportedLanguage;
  }
  const nav = navigator.language.toLowerCase();
  if (nav.startsWith("zh")) return "zh";
  return DEFAULT_LANGUAGE;
}

/** Persist the active language and update the document language attribute. */
export function setLanguage(lang: SupportedLanguage): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("soymutdb_lang", lang);
  document.documentElement.lang = lang;
  i18n.changeLanguage(lang);
}

/** Initialize i18next. Call once in the app entry before rendering. */
export function initI18n(lang: SupportedLanguage = detectLanguage()): typeof i18n {
  if (!i18n.isInitialized) {
    i18n.use(initReactI18next).init({
      initImmediate: false,
      resources: {
        en: { translation: en, common: en },
        zh: { translation: zh, common: zh },
      },
      lng: lang,
      fallbackLng: DEFAULT_LANGUAGE,
      defaultNS: "common",
      ns: ["common"],
      interpolation: {
        escapeValue: false,
      },
      react: {
        useSuspense: false,
      },
    });
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang;
  }
  return i18n;
}

export default i18n;
export { en, zh };
