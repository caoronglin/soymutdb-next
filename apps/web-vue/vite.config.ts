import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Empty-shell bootstrap (Phase D, Checkpoint A). The portal variant is selected
// at build time via VITE_SITE_VARIANT (external/internal), mirroring the React
// portal — never inferred from host/cookies (DB-CORE-5). Routing, Pinia, Vue
// Query, the Antdv Next facade and design tokens land in subsequent commits.
export default defineConfig({
  plugins: [vue()],
  define: {
    __SITE_VARIANT__: JSON.stringify(process.env.VITE_SITE_VARIANT ?? "external"),
  },
});
