import { createRouter, createWebHistory, type RouteRecordRaw } from "vue-router";

import AboutView from "../views/AboutView.vue";
import AnalyticsView from "../views/AnalyticsView.vue";
import CompareView from "../views/CompareView.vue";
import AnalysesFastpView from "../views/AnalysesFastpView.vue";
import AnalysesJobView from "../views/AnalysesJobView.vue";
import AnalysesScanpyView from "../views/AnalysesScanpyView.vue";
import AnalysesView from "../views/AnalysesView.vue";
import BlastView from "../views/BlastView.vue";
import BrowserView from "../views/BrowserView.vue";
import DownloadsView from "../views/DownloadsView.vue";
import EnrichmentView from "../views/EnrichmentView.vue";
import ExpPatternView from "../views/ExpPatternView.vue";
import GbrowseView from "../views/GbrowseView.vue";
import GeneView from "../views/GeneView.vue";
import GenesListView from "../views/GenesListView.vue";
import GuideView from "../views/GuideView.vue";
import HelpView from "../views/HelpView.vue";
import Home from "../views/HomeView.vue";
import LoginView from "../views/LoginView.vue";
import MutantDetailView from "../views/MutantDetailView.vue";
import MutantsListView from "../views/MutantsListView.vue";
import NewsDetailView from "../views/NewsDetailView.vue";
import NewsListView from "../views/NewsListView.vue";
import PrimerView from "../views/PrimerView.vue";
import PublicationsView from "../views/PublicationsView.vue";
import SearchGenesView from "../views/SearchGenesView.vue";
import SearchLocationView from "../views/SearchLocationView.vue";
import SearchToolsView from "../views/SearchToolsView.vue";
import SearchView from "../views/SearchView.vue";
import SeedRequestView from "../views/SeedRequestView.vue";
import SeqFetchView from "../views/SeqFetchView.vue";
import SraView from "../views/SraView.vue";
import ToolsView from "../views/ToolsView.vue";
import VariantsView from "../views/VariantsView.vue";
import { PORTAL_ROUTES } from "./routes";

// Public-portal routes (Checkpoint B). Route metadata lives in ./routes.ts so
// the static-route generator can enumerate it without loading components.
// The release/assembly/site-variant context lives in query params + Pinia,
// never inferred from the host (DB-CORE-5/6).
const COMPONENTS = {
  home: Home,
  search: SearchView,
  "search-genes": SearchGenesView,
  "search-location": SearchLocationView,
  gene: GeneView,
  genes: GenesListView,
  mutants: MutantsListView,
  mutant: MutantDetailView,
  variants: VariantsView,
  downloads: DownloadsView,
  tools: ToolsView,
  seqfetch: SeqFetchView,
  exppattern: ExpPatternView,
  enrichment: EnrichmentView,
  news: NewsListView,
  "news-detail": NewsDetailView,
  browser: BrowserView,
  blast: BlastView,
  primer: PrimerView,
  gbrowse: GbrowseView,
  "search-tools": SearchToolsView,
  analyses: AnalysesView,
  "analyses-fastp": AnalysesFastpView,
  "analyses-scanpy": AnalysesScanpyView,
  "analyses-job": AnalysesJobView,
  sra: SraView,
  "seed-request": SeedRequestView,
  guide: GuideView,
  help: HelpView,
  about: AboutView,
  analytics: AnalyticsView,
  compare: CompareView,
  publications: PublicationsView,
  login: LoginView,
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
