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

/** Optional adapter for translating fallback copy when a locale key is absent.
 * The core ships no network translator or credentials; applications may
 * register a same-origin server-backed provider. Until then the original text
 * is returned unchanged, so translation never blocks a page.
 */
export interface AutoTranslationRequest {
  text: string;
  sourceLanguage?: string;
  targetLanguage: SupportedLanguage;
  namespace?: string;
  key?: string;
}

export interface AutoTranslationProvider {
  translate(request: AutoTranslationRequest): Promise<string | null | undefined>;
}

let autoTranslationProvider: AutoTranslationProvider | undefined;

export function configureAutoTranslationProvider(
  provider: AutoTranslationProvider | undefined,
): void {
  autoTranslationProvider = provider;
}

export async function translateFallback(
  request: AutoTranslationRequest,
): Promise<string> {
  if (!autoTranslationProvider || !request.text.trim()) return request.text;
  try {
    const translated = await autoTranslationProvider.translate(request);
    return typeof translated === "string" && translated.trim()
      ? translated
      : request.text;
  } catch {
    // An optional translation service must never take down core UI.
    return request.text;
  }
}

export const DEFAULT_LANGUAGE: SupportedLanguage = "en";

export const catalogs = { en, zh } as const;

/** Detect the user's preferred language from localStorage or the browser. */
export function detectLanguage(): SupportedLanguage {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  // Storage can be absent (SSR/node), blocked by policy, or exposed only as a
  // bare global (jsdom). Read whichever binding exists and let a failure fall
  // through to the navigator hint instead of breaking the page.
  const storage: Pick<Storage, "getItem"> | undefined =
    typeof globalThis.localStorage !== "undefined" ? globalThis.localStorage : window.localStorage;
  let stored: string | null;
  try {
    stored = storage?.getItem("soymutdb_lang") ?? null;
  } catch {
    stored = null;
  }
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
