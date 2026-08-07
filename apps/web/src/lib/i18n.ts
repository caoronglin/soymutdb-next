/**
 * i18n bootstrap — initializes i18next with the detected language and exposes
 * a small hook wrapper for language switching.
 */
import { initI18n, setLanguage, detectLanguage, type SupportedLanguage } from "@soymutdb/i18n";
import i18n from "@soymutdb/i18n";
import { useTranslation } from "react-i18next";

let initialized = false;

/**
 * App-level translation keys that are not part of the shared
 * @soymutdb/i18n package resources (the package is shared/read-only for this
 * task, so new portal-only strings are merged in at runtime instead).
 */
const EXTRA_RESOURCES: Record<string, Record<string, Record<string, string>>> = {
  en: {
    browser: {
      back: "Back",
      stillLoading: "Still loading…",
      stillLoadingDesc:
        "The JBrowse 2 genome browser at {{url}} is taking longer than expected. You can keep waiting, retry, or open it in a new tab.",
      retry: "Retry",
      openInNewTab: "Open in new tab",
      loadError: "The genome browser could not be loaded.",
      loadErrorDetail:
        "The JBrowse 2 service at {{url}} could not be reached. This may be a temporary connectivity issue or the service may not be deployed yet.",
    },
  },
  zh: {
    browser: {
      back: "返回",
      stillLoading: "仍在加载…",
      stillLoadingDesc:
        "位于 {{url}} 的 JBrowse 2 基因组浏览器响应时间较长。您可以继续等待、重试，或在新标签页中打开。",
      retry: "重试",
      openInNewTab: "在新标签页中打开",
      loadError: "无法加载基因组浏览器。",
      loadErrorDetail:
        "无法连接到位于 {{url}} 的 JBrowse 2 服务。这可能是暂时性网络问题，或该服务尚未部署。",
    },
  },
};

export function initI18nOnce(): void {
    if (initialized) return;
    initI18n(detectLanguage());
    for (const [lng, bundle] of Object.entries(EXTRA_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle);
    }
    initialized = true;
}

export function useI18n() {
    const { t, i18n } = useTranslation();
    const change = (lang: SupportedLanguage) => setLanguage(lang);
    return { t, i18n, changeLanguage: change, currentLanguage: i18n.language as SupportedLanguage };
}

export { detectLanguage, type SupportedLanguage };
