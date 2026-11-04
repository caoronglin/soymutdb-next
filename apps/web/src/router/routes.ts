/**
 * Portal route metadata (pure data — no component imports).
 *
 * The SPA router binds components in `index.ts`; this table is also imported by
 * the static-route generator (`scripts/generate-static-routes.ts`) and its
 * tests, so it must stay free of `.vue` imports that a plain tsx process cannot
 * load.
 *
 * `meta.prerender` marks routes that get their own directory `index.html` at
 * build time (static hosting then serves them directly instead of relying on a
 * SPA fallback). Dynamic routes (`:param`) never prerender. `meta.sitemap`
 * marks publicly indexable routes; the internal site variant never emits a
 * sitemap.
 */

export interface PortalRouteMeta {
  /** Page <title> written into the prerendered HTML. */
  title: string;
  /** Optional <meta name="description">. */
  description?: string;
  /** Generate `<path>/index.html` at build time. */
  prerender?: boolean;
  /** Include in the external sitemap.xml. */
  sitemap?: boolean;
}

export interface PortalRouteDefinition {
  path: string;
  name: string;
  componentKey:
    | "home"
    | "search"
    | "search-location"
    | "search-genes"
    | "gene"
    | "genes"
    | "mutants"
    | "mutant"
    | "variants"
    | "downloads"
    | "tools"
    | "seqfetch"
    | "exppattern"
    | "enrichment"
    | "news"
    | "news-detail"
    | "browser"
    | "blast"
    | "primer"
    | "gbrowse"
    | "search-tools"
    | "analyses"
    | "analyses-fastp"
    | "analyses-scanpy"
    | "analyses-job"
    | "sra"
    | "seed-request"
    | "guide"
    | "help"
    | "about"
    | "publications"
    | "login"
    | "analytics"
    | "comparative"
    | "family"
    | "compare";
  meta: PortalRouteMeta;
}

export const PORTAL_ROUTES: readonly PortalRouteDefinition[] = [
  {
    path: "/",
    name: "home",
    componentKey: "home",
    meta: {
      title: "SoyMutDB — Soybean Mutant Database",
      description: "Search soybean genes, variants, and mutant lines across assemblies and releases.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/search",
    name: "search",
    componentKey: "search",
    meta: {
      title: "Search — SoyMutDB",
      description: "Search genes, variants, mutant lines, and publications.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/genes/:geneId",
    name: "gene",
    componentKey: "gene",
    meta: { title: "Gene — SoyMutDB" },
  },
  {
    path: "/mutants",
    name: "mutants",
    componentKey: "mutants",
    meta: {
      title: "Mutant lines — SoyMutDB",
      description: "Browse released soybean mutant lines by public identifier.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/mutants/:publicId",
    name: "mutant",
    componentKey: "mutant",
    meta: { title: "Mutant line — SoyMutDB" },
  },
  {
    path: "/variants",
    name: "variants",
    componentKey: "variants",
    meta: {
      title: "Variants — SoyMutDB",
      description: "Explore variants by assembly-scoped region and impact filters.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/downloads",
    name: "downloads",
    componentKey: "downloads",
    meta: {
      title: "Downloads — SoyMutDB",
      description: "Download released SoyMutDB data files through short-lived presigned URLs.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/genes",
    name: "genes",
    componentKey: "genes",
    meta: {
      title: "Genes — SoyMutDB",
      description: "Browse released gene models by chromosome, biotype and symbol.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/search/genes",
    name: "search-genes",
    componentKey: "search-genes",
    meta: {
      title: "Gene ID search — SoyMutDB",
      description: "Find a gene by public identifier inside one genome assembly.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/search/location",
    name: "search-location",
    componentKey: "search-location",
    meta: {
      title: "Location search — SoyMutDB",
      description: "List variants and genes inside one 1-based inclusive genomic region.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/search/gbrowse",
    name: "search-gbrowse",
    componentKey: "gbrowse",
    meta: {
      title: "JBrowse 2 — SoyMutDB",
      description: "Open the JBrowse 2 genome browser for a selected assembly.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/search/primer",
    name: "search-primer",
    componentKey: "primer",
    meta: {
      title: "Primer design — SoyMutDB",
      description: "Design heuristic primer pairs for a region of one assembly.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/search/blast",
    name: "search-blast",
    componentKey: "blast",
    meta: { title: "BLAST — SoyMutDB" },
  },
  {
    path: "/search/tools",
    name: "search-tools",
    componentKey: "search-tools",
    // A real catalog page, so it needs its own document. Without prerender the
    // title above was never delivered: only prerendered routes get an
    // index.html, so a crawler and a no-JS client both saw the site default.
    meta: {
      title: "Search tools — SoyMutDB",
      description: "Browse the analysis tools that complement identifier and location search.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/browser",
    name: "browser",
    componentKey: "browser",
    meta: {
      title: "Genome browser — SoyMutDB",
      description: "Explore released variants in genomic context through JBrowse 2.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/blast",
    name: "blast",
    componentKey: "blast",
    meta: {
      title: "BLAST — SoyMutDB",
      description: "Search sequences against the activated reference databases.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/analyses",
    name: "analyses",
    componentKey: "analyses",
    meta: {
      title: "Analyses — SoyMutDB",
      description: "Run read QC and single-cell clustering on your own data.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/analyses/fastp",
    name: "analyses-fastp",
    componentKey: "analyses-fastp",
    meta: { title: "fastp — SoyMutDB" },
  },
  {
    path: "/analyses/scanpy",
    name: "analyses-scanpy",
    componentKey: "analyses-scanpy",
    meta: { title: "scanpy — SoyMutDB" },
  },
  {
    path: "/analyses/:jobId",
    name: "analyses-job",
    componentKey: "analyses-job",
    meta: { title: "Analysis job — SoyMutDB" },
  },
  {
    path: "/sra",
    name: "sra",
    componentKey: "sra",
    meta: {
      title: "SRA browser — SoyMutDB",
      description: "Federated SRA run metadata lookups.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/seed-request",
    name: "seed-request",
    componentKey: "seed-request",
    meta: {
      title: "Seed request — SoyMutDB",
      description: "Request seed material for released mutant lines.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/guide",
    name: "guide",
    componentKey: "guide",
    meta: {
      title: "Guide — SoyMutDB",
      description: "How to retrieve records, coordinates and releases.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/help",
    name: "help",
    componentKey: "help",
    meta: {
      title: "Help — SoyMutDB",
      description: "Usage contract, identifiers, assemblies, releases and FAQ.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/analytics",
    name: "analytics",
    componentKey: "analytics",
    meta: {
      title: "Analytics — SoyMutDB",
      description: "Aggregate views of variant density, types, impact and discovery trend.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    // Gene-family browser. `/compare` below is *variant* comparison and is a
    // different feature entirely — do not merge the two entries.
    path: "/comparative",
    name: "comparative",
    componentKey: "comparative",
    meta: {
      title: "Comparative genomics — SoyMutDB",
      description:
        "Browse gene families and orthologous groups with their source method, version and per-species coverage.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/comparative/:familyId",
    name: "family",
    componentKey: "family",
    meta: { title: "Gene family — SoyMutDB" },
  },
  {
    path: "/compare",
    name: "compare",
    componentKey: "compare",
    meta: {
      title: "Variant comparison — SoyMutDB",
      description: "Compare released variants side by side by their public ids.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/about",
    name: "about",
    componentKey: "about",
    meta: {
      title: "About — SoyMutDB",
      description: "About the SoyMutDB soybean mutant database.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/publications",
    name: "publications",
    componentKey: "publications",
    meta: {
      title: "Publications — SoyMutDB",
      description: "Publications citing or describing SoyMutDB.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/login",
    name: "login",
    componentKey: "login",
    meta: {
      title: "Sign in — SoyMutDB",
      description: "Sign in to an internal SoyMutDB account.",
      prerender: true,
      sitemap: false,
    },
  },
  {
    path: "/tools",
    name: "tools",
    componentKey: "tools",
    meta: {
      title: "Research tools — SoyMutDB",
      description: "Assembly-aware sequence and analysis tools for SoyMutDB data.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/tools/seqfetch",
    name: "seqfetch",
    componentKey: "seqfetch",
    meta: {
      title: "Sequence fetch — SoyMutDB",
      description: "Extract FASTA sequences from an explicit assembly by gene accession or genomic region.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/tools/exppattern",
    name: "exppattern",
    componentKey: "exppattern",
    meta: {
      title: "Expression pattern — SoyMutDB",
      description: "Compare gene expression across libraries within one genome assembly.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/tools/enrichment",
    name: "enrichment",
    componentKey: "enrichment",
    meta: {
      title: "Enrichment analysis — SoyMutDB",
      description: "Run GO or KEGG enrichment analysis within a selected genome assembly.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/news",
    name: "news",
    componentKey: "news",
    meta: {
      title: "News — SoyMutDB",
      description: "Announcements, updates, and news from the SoyMutDB project.",
      prerender: true,
      sitemap: true,
    },
  },
  {
    path: "/news/:slug",
    name: "news-article",
    componentKey: "news-detail",
    meta: { title: "News article — SoyMutDB" },
  },
] as const;
