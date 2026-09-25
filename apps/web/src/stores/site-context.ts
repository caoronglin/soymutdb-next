// Client/deployment context store (Pinia: D2 state division — server data lives
// in TanStack Vue Query; Pinia holds the UI/deployment context). The site
// variant is validated at store creation and fails closed on an illegal value
// (DB-CORE-5). The release id mirrors the api-client's X-SoyMutDB-Release pin:
// setRelease updates both, so the release displayed and the release requested
// are always the same value.
// Navigation intentionally lives in components (useRouter), not here: importing
// the router instance would create a router -> view -> store -> router cycle.
import { defineStore } from "pinia";

import { applyDeploymentRelease, resolveInitialReleaseId, type SiteVariant } from "../lib/deployment";
import { resolveSiteVariant } from "../lib/site-variant";

export type { SiteVariant };

export const useSiteContextStore = defineStore("site-context", {
  state: () => ({
    siteVariant: resolveSiteVariant(import.meta.env.VITE_SITE_VARIANT),
    releaseId: resolveInitialReleaseId(import.meta.env.VITE_SOYMUTDB_RELEASE_ID),
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
      // Same value into the request header: the API request release must equal
      // the release the page renders (DB-CORE-6).
      applyDeploymentRelease(releaseId);
    },
    setAssembly(assemblyKey: string | null) {
      this.assemblyKey = assemblyKey;
    },
  },
});
