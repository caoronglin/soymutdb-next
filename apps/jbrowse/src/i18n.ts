/**
 * Vue i18n binding for the standalone JBrowse shell.
 *
 * The catalogs, language detection and the language type all come from
 * `@soymutdb/i18n-core`, the same framework-neutral package the portal uses.
 * `i18next` is not a declared dependency of this app, so `t` reads the catalog
 * directly instead of going through the i18next runtime; the observable shape
 * (a reactive language ref plus a plain `t` function) matches
 * `apps/web/src/lib/i18n.ts`.
 */
import { catalogs, detectLanguage, type SupportedLanguage } from "@soymutdb/i18n-core";
import { ref } from "vue";

/** Active language; reading it inside `t` is what makes translations reactive. */
export const currentLanguage = ref<SupportedLanguage>(detectLanguage());

/** App-only keys that are not part of the shared catalog. */
const EXTRA_RESOURCES: Record<SupportedLanguage, Record<string, string>> = {
  en: { "browser.backToPortal": "Back to portal" },
  zh: { "browser.backToPortal": "返回门户" },
};

function readCatalog(source: unknown, key: string): string | undefined {
  let current: unknown = source;
  for (const segment of key.split(".")) {
    if (typeof current !== "object" || current === null) return undefined;
    current = (current as Record<string, unknown>)[segment];
  }
  return typeof current === "string" ? current : undefined;
}

function translate(key: string): string {
  const language = currentLanguage.value;
  return (
    EXTRA_RESOURCES[language][key] ??
    readCatalog(catalogs[language], key) ??
    EXTRA_RESOURCES.en[key] ??
    readCatalog(catalogs.en, key) ??
    key
  );
}

/** Translate one key, interpolating `{{name}}` placeholders from `options`. */
export function t(key: string, options?: Record<string, unknown>): string {
  const template = translate(key);
  if (!options) return template;
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, name: string) =>
    String(options[name] ?? ""),
  );
}
