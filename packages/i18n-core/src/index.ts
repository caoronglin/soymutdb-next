/**
 * Framework-neutral i18n core (Phase C seam).
 *
 * Owns the locale catalogs and the language metadata both the React adapter
 * (`@soymutdb/i18n`) and the future Vue app consume. It has no framework
 * dependencies: the catalogs are plain JSON and the base options are a plain
 * object that any i18next integration (react-i18next, @panter/vue-i18next, …)
 * can extend.
 */
import en from "./locales/en/common.json";
import zh from "./locales/zh/common.json";

export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

export const catalogs = { en, zh } as const;

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

/**
 * Framework-neutral i18next init options (resources, namespaces, fallback).
 * A framework adapter adds its own glue (e.g. react-i18next's `react` block)
 * on top of this.
 */
export function buildBaseI18nOptions(lang: SupportedLanguage = DEFAULT_LANGUAGE) {
  return {
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
  } as const;
}

export { en, zh };
