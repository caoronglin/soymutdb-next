import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Phase D Checkpoint D: Vite 6 + Tailwind CSS 4 (@tailwindcss/vite) + the
// @soymutdb/ui-vue facade. The site variant stays a build-time define (DB-CORE-5).
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  define: {
    __SITE_VARIANT__: JSON.stringify(process.env.VITE_SITE_VARIANT ?? "external"),
  },
});
