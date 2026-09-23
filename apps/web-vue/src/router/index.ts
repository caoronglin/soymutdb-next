import { createRouter, createWebHistory } from "vue-router";

import GeneView from "../views/GeneView.vue";
import DownloadsView from "../views/DownloadsView.vue";
import Home from "../views/HomeView.vue";
import MutantDetailView from "../views/MutantDetailView.vue";
import MutantsListView from "../views/MutantsListView.vue";
import SearchView from "../views/SearchView.vue";
import VariantsView from "../views/VariantsView.vue";

// Public-portal routes (Checkpoint B). Routes are migrated page-by-page in
// later commits; this establishes the router + deep-link semantics. The
// release/assembly/site-variant context lives in query params + Pinia, never
// inferred from the host (DB-CORE-5/6).
export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: "/", name: "home", component: Home },
    { path: "/search", name: "search", component: SearchView },
    { path: "/genes/:geneId", name: "gene", component: GeneView },
    { path: "/mutants", name: "mutants", component: MutantsListView },
    { path: "/mutants/:publicId", name: "mutant", component: MutantDetailView },
    { path: "/variants", name: "variants", component: VariantsView },
    { path: "/downloads", name: "downloads", component: DownloadsView },
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("../views/NotFoundView.vue"),
    },
  ],
});
