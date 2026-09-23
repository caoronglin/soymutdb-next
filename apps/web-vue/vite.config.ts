import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";

import { normalizeBasePath } from "./src/lib/base-path";
import { resolveSiteVariant } from "./src/lib/site-variant";

// Phase D Checkpoint D: Vite 6 + Tailwind CSS 4 (@tailwindcss/vite) + the
// @soymutdb/ui-vue facade. The site variant stays a build-time define (DB-CORE-5).
//
// `base` comes from the same VITE_BASE_URL the static artifact builder sets, so
// a subpath deployment (/soymutdb-next/) emits /soymutdb-next/assets/... asset
// URLs and import.meta.env.BASE_URL (which createWebHistory consumes) instead of
// rooting every URL at /. The React portal had this fix and the Vue shell was
// missing it.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, "");
  // Validate the site variant at config time: an illegal value must fail the
  // build, never become a third variant whose isInternal silently reads false
  // (DB-CORE-5). The runtime store repeats this check for non-Vite hosts.
  const siteVariant = resolveSiteVariant(env.VITE_SITE_VARIANT);
  return {
    base: normalizeBasePath(env.VITE_BASE_URL),
    plugins: [vue(), tailwindcss()],
    define: {
      __SITE_VARIANT__: JSON.stringify(siteVariant),
    },
  };
});
