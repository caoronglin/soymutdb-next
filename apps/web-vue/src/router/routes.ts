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
  componentKey: "home" | "search" | "gene" | "mutants" | "mutant" | "variants" | "downloads";
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
      description: "Search genes, variants, mutant lines, publications, and federated sources.",
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
] as const;
