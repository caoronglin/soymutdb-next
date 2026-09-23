import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import DownloadsView from "../views/DownloadsView.vue";
import GeneView from "../views/GeneView.vue";
import Home from "../views/HomeView.vue";
import MutantDetailView from "../views/MutantDetailView.vue";
import MutantsListView from "../views/MutantsListView.vue";
import SearchView from "../views/SearchView.vue";
import VariantsView from "../views/VariantsView.vue";
import { PORTAL_ROUTES } from "./routes";

// Public-portal routes (Checkpoint B). Route metadata lives in ./routes.ts so
// the static-route generator can enumerate it without loading components.
// The release/assembly/site-variant context lives in query params + Pinia,
// never inferred from the host (DB-CORE-5/6).
const COMPONENTS = {
  home: Home,
  search: SearchView,
  gene: GeneView,
  mutants: MutantsListView,
  mutant: MutantDetailView,
  variants: VariantsView,
  downloads: DownloadsView,
} as const;

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    ...PORTAL_ROUTES.map(
      (route): RouteRecordRaw => ({
        path: route.path,
        name: route.name,
        component: COMPONENTS[route.componentKey],
        // Spread into a fresh literal: vue-router's RouteMeta is an index
        // signature type, which a named interface does not satisfy directly.
        meta: { ...route.meta },
      }),
    ),
    {
      path: "/:pathMatch(.*)*",
      name: "not-found",
      component: () => import("../views/NotFoundView.vue"),
    },
  ],
});
