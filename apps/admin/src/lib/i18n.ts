/**
 * i18n for the admin console.
 *
 * Same catalogs and same language metadata as the portal
 * (`@soymutdb/i18n-core`), wrapped for Vue. `t` is a plain function rather than
 * a computed ref: a computed unwraps when read from a slot's render context, so
 * `t.value(...)` inside a layout slot would call `undefined`.
 */
import i18next from "i18next";
import { ref } from "vue";

import { buildBaseI18nOptions, detectLanguage, type SupportedLanguage } from "@soymutdb/i18n-core";

const initialLanguage = detectLanguage();
void i18next.init(buildBaseI18nOptions(initialLanguage));

export const currentLanguage = ref<SupportedLanguage>(initialLanguage);

export function t(key: string, options?: Record<string, unknown>): string {
  const language = currentLanguage.value;
  if (i18next.resolvedLanguage !== language) void i18next.changeLanguage(language);
  return i18next.t(key, { ...(options ?? {}), lng: language } as never) as unknown as string;
}
