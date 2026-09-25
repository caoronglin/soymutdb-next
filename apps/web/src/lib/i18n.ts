/**
 * Framework-neutral i18n bootstrap for the Vue portal.
 *
 * `@soymutdb/i18n-core` owns the catalogs, the language metadata and the base
 * i18next options; this module only adds the Vue glue: a `currentLanguage` ref
 * the header can switch, and a `t` function that reads it.
 *
 * `t` is a plain function, not a `computed`. A computed ref would unwrap when
 * read from a slot's render context (`_ctx.t` returns the ref *value*), so
 * `t.value(...)` inside a layout slot silently calls `undefined`. Reading
 * `currentLanguage` inside `t` gives the same reactivity without that trap.
 */
import i18next from "i18next";
import { ref } from "vue";

import {
  buildBaseI18nOptions,
  detectLanguage,
  SUPPORTED_LANGUAGES,
  type SupportedLanguage,
} from "@soymutdb/i18n-core";

export type { SupportedLanguage };
export { SUPPORTED_LANGUAGES };

const initialLanguage = detectLanguage();
void i18next.init(buildBaseI18nOptions(initialLanguage));

export const currentLanguage = ref<SupportedLanguage>(initialLanguage);

/** Translate one key. Re-renders the caller when the language changes. */
export function t(key: string, options?: Record<string, unknown>): string {
  // Reading the ref is the reactive dependency: a language switch re-runs
  // every render that called `t`, so no manual cache invalidation is needed.
  const language = currentLanguage.value;
  if (i18next.resolvedLanguage !== language) void i18next.changeLanguage(language);
  return i18next.t(key, { ...(options ?? {}), lng: language } as never) as unknown as string;
}

export function setLanguage(language: SupportedLanguage) {
  currentLanguage.value = language;
  try {
    (
      typeof globalThis.localStorage !== "undefined"
        ? globalThis.localStorage
        : window.localStorage
    )?.setItem("soymutdb_lang", language);
  } catch {
    // Storage can be blocked; the in-memory selection still applies.
  }
}

export function toggleLanguage() {
  setLanguage(currentLanguage.value === "zh" ? "en" : "zh");
}
