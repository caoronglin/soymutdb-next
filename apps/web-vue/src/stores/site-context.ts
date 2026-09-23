// Client/deployment context store (Pinia: D2 state division — server data lives
// in TanStack Vue Query; Pinia holds the UI/deployment context). The site
// variant is the build-time constant, never inferred at runtime (DB-CORE-5).
// Navigation intentionally lives in components (useRouter), not here: importing
// the router instance would create a router -> view -> store -> router cycle.
import { defineStore } from "pinia";

export type SiteVariant = "external" | "internal";

export const useSiteContextStore = defineStore("site-context", {
  state: () => ({
    siteVariant: (import.meta.env.VITE_SITE_VARIANT ?? "external") as SiteVariant,
    releaseId: null as string | null,
    assemblyKey: null as string | null,
  }),
  getters: {
    isInternal(state): boolean {
      return state.siteVariant === "internal";
    },
  },
  actions: {
    setRelease(releaseId: string | null) {
      this.releaseId = releaseId;
    },
    setAssembly(assemblyKey: string | null) {
      this.assemblyKey = assemblyKey;
    },
  },
});
