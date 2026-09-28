import i18next, { type i18n as I18nInstance } from "i18next";
import { initReactI18next } from "react-i18next";
import {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  configureAutoTranslationProvider,
  translateFallback,
  buildBaseI18nOptions,
  detectLanguage,
  en,
  zh,
  type SupportedLanguage,
  type AutoTranslationProvider,
  type AutoTranslationRequest,
} from "@soymutdb/i18n-core";

/**
 * React adapter for the framework-neutral `@soymutdb/i18n-core`.
 *
 * The catalogs, supported languages, language detection and the base i18next
 * options live in the neutral core so a future Vue app can share them; this
 * module only adds the react-i18next glue and owns the shared singleton. New
 * code should import framework-neutral pieces from `@soymutdb/i18n-core`
 * directly and only import this module for the React wiring.
 */

// Re-export the framework-neutral surface so existing `@soymutdb/i18n` imports
// (web, admin, jbrowse) keep working unchanged.
export {
  DEFAULT_LANGUAGE,
  SUPPORTED_LANGUAGES,
  configureAutoTranslationProvider,
  translateFallback,
  buildBaseI18nOptions,
  detectLanguage,
  en,
  zh,
  type SupportedLanguage,
  type AutoTranslationProvider,
  type AutoTranslationRequest,
};

/** Initialize i18next + react-i18next. Call once in the app entry before rendering. */
export function initI18n(lang: SupportedLanguage = detectLanguage()): I18nInstance {
  if (!i18next.isInitialized) {
    i18next.use(initReactI18next).init({
      ...buildBaseI18nOptions(lang),
      react: { useSuspense: false },
    });
  }
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang;
  }
  return i18next;
}

/** Persist the active language and update the document language attribute. */
export function setLanguage(lang: SupportedLanguage): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("soymutdb_lang", lang);
  document.documentElement.lang = lang;
  i18next.changeLanguage(lang);
}

export default i18next;
