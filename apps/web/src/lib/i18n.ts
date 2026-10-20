/**
 * i18n bootstrap — initializes i18next with the detected language and exposes
 * a small hook wrapper for language switching.
 */
import {
  initI18n,
  setLanguage as setI18nLanguage,
  detectLanguage,
  type SupportedLanguage,
} from "@soymutdb/i18n";
import i18n from "@soymutdb/i18n";
import { useTranslation } from "react-i18next";

import { EXTRA_RESOURCES, HOME_RESOURCES, TOOLS_RESOURCES } from "./i18n-resources";

let initialized = false;


export function initI18nOnce(): void {
    if (initialized) return;
    initI18n(detectLanguage());
    for (const [lng, bundle] of Object.entries(EXTRA_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle, true);
        i18n.addResourceBundle(lng, "translation", bundle, true);
    }
    for (const [lng, bundle] of Object.entries(TOOLS_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle, true);
        i18n.addResourceBundle(lng, "translation", bundle, true);
    }
    for (const [lng, bundle] of Object.entries(HOME_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle, true);
        i18n.addResourceBundle(lng, "translation", bundle, true);
    }
    initialized = true;
}

function setLanguage(language: SupportedLanguage): void {
    initI18nOnce();
    setI18nLanguage(language);
}

export function useI18n() {
    const { t, i18n } = useTranslation();
    const change = (lang: SupportedLanguage) => setLanguage(lang);
    return { t, i18n, changeLanguage: change, currentLanguage: i18n.language as SupportedLanguage };
}

export { detectLanguage, type SupportedLanguage };
