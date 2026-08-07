/**
 * i18n bootstrap — initializes i18next with the detected language and exposes
 * a small hook wrapper for language switching.
 */
import { initI18n, setLanguage, detectLanguage, type SupportedLanguage } from "@soymutdb/i18n";
import { useTranslation } from "react-i18next";

let initialized = false;

export function initI18nOnce(): void {
    if (initialized) return;
    initI18n(detectLanguage());
    initialized = true;
}

export function useI18n() {
    const { t, i18n } = useTranslation();
    const change = (lang: SupportedLanguage) => setLanguage(lang);
    return { t, i18n, changeLanguage: change, currentLanguage: i18n.language as SupportedLanguage };
}

export { detectLanguage, type SupportedLanguage };
