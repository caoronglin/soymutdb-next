import { createRouter, createWebHistory } from "vue-router";

import GeneView from "../views/GeneView.vue";
import Home from "../views/HomeView.vue";
import SearchView from "../views/SearchView.vue";

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
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("../views/NotFoundView.vue"),
    },
  ],
});
