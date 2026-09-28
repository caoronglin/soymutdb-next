/**
 * App-level i18n keys for the standalone JBrowse app.
 *
 * The shared @soymutdb/i18n package resources cover the portal, but the
 * package is shared/read-only for this task, so app-only strings are merged
 * into the i18next singleton at runtime. Must be called after initI18n().
 */
import i18n from "@soymutdb/i18n";

const EXTRA_RESOURCES: Record<string, Record<string, Record<string, string>>> = {
    en: {
        browser: {
            backToPortal: "Back to portal",
        },
    },
    zh: {
        browser: {
            backToPortal: "返回门户",
        },
    },
};

export function addJbrowseI18nResources(): void {
    for (const [lng, bundle] of Object.entries(EXTRA_RESOURCES)) {
        i18n.addResourceBundle(lng, "common", bundle);
    }
}
