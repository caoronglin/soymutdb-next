/**
 * Backend-editable site-content hook/provider.
 *
 * This is PHASE 1 infrastructure. Phase 2 page-wiring agents consume it via
 * {@link useSiteContent} and MUST NOT change this contract.
 *
 * ---------------------------------------------------------------------------
 * CONTRACT (stable — do not break)
 * ---------------------------------------------------------------------------
 * `useSiteContent(): {`data`, `get`}`
 *   - `data?: Record<string,string>`  — the loaded public site-content map
 *     (flat content.* short keys, e.g. "hero.title"). Undefined while the
 *     query is pending/failed.
 *   - `get(key: string, fallback?: string): string`
 *       Reads `data[key]` when the loaded map has that key; otherwise uses
 *       the caller-supplied `fallback`; otherwise uses the built-in fallback
 *       map merged into the provider. It NEVER returns undefined — components
 *       can render the result directly.
 *
 * Usage required by phase-2 agents:
 *   `const { get } = useSiteContent();`
 *   `get("hero.title")`                      -> server-editable value,
 *                                                  or the provider default.
 *   `get("home.heroTitle", t("home.heroTitle"))`
 *                                             -> server-editable value when
 *                                                  set; otherwise the i18n
 *                                                  fallback for this locale.
 *
 * Note: the public endpoint returns a value for EVERY registered key (stored
 * value or its default), so `get` typically uses the server value once the
 * query resolves. Pass a locale-specific `t(...)` fallback so a page that
 * has not yet wired in content still renders pre-server-data (loading/error)
 * the same as today. If you need per-locale editable text, use two keys or
 * let the content value win (it is site-wide, not per-locale).
 */
import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { getSiteContent, type SiteContent } from "@soymutdb/api-client";
import { SITE_VARIANT } from "./site-variant";

/**
 * Built-in fallback values. They mirror the registered `content.*` defaults
 * in apps/api/app/core/settings_registry.py and equal the site's current
 * (default-language) rendered strings, so a fresh deployment renders
 * identically until an administrator edits them.
 */
export const SITE_CONTENT_DEFAULTS: Record<string, string> = {
  // hero
  "hero.eyebrow": "SOYMUTDB · MULTI-SPECIES",
  "hero.title": "Explore the Unknown Territories of Multi-Species Mutation",
  "hero.subtitle": "A next-generation multi-species mutation database — from genome to phenotype in one place.",
  "hero.searchPlaceholder": "Search a gene ID, locus or mutation…",
  "hero.image": "",
  // tool cards
  "tool.gene.label": "Gene ID Search",
  "tool.gene.desc": "Look up mutations by gene ID",
  "tool.gene.image": "",
  "tool.location.label": "Position Search",
  "tool.location.desc": "Look up by chromosome and locus",
  "tool.location.image": "",
  "tool.gbrowse.label": "JBrowse 2",
  "tool.gbrowse.desc": "Browse the genome in JBrowse 2",
  "tool.gbrowse.image": "",
  "tool.blast.label": "BLAST",
  "tool.blast.desc": "Find homologs by sequence alignment",
  "tool.blast.image": "",
  "tool.primer.label": "Primer Design",
  "tool.primer.desc": "Design and check PCR primers",
  "tool.primer.image": "",
  // search pages
  "search.genes.title": "Gene ID Search",
  "search.genes.subtitle": "Find genes by gene ID in a genome version",
  "search.genes.colAssembly": "Genome version",
  "search.genes.colChromosome": "Chromosome",
  "search.genes.colPosition": "Position",
  "search.genes.colMutation": "Mutation feature",
  "search.genes.colGeneId": "Gene ID",
  "search.genes.colGbrowse": "JBrowse 2",
  "search.location.title": "Physical Location Search",
  "search.location.subtitle": "Find variants and genes in a genomic region",
  "search.location.colAssembly": "Genome version",
  "search.location.colChromosome": "Chromosome",
  "search.location.colPosition": "Position",
  "search.location.colMutation": "Mutation feature",
  "search.location.colGeneId": "Gene ID",
  "search.location.colGbrowse": "JBrowse 2",
  // blast
  "blast.searchType": "BLAST Type",
  "blast.database": "Reference sequence type",
  "blast.databasePlaceholder": "Select a reference sequence type",
  "blast.input": "Input Sequence",
  "blast.inputSequence": "Input Sequence",
  "blast.sequencePlaceholder": "Paste sequence in FASTA format...",
  "blast.submit": "BLAST",
  "blast.eValue": "E-value threshold",
  "blast.maxHits": "Max hits",
  "blast.hitSequenceId": "Sequence ID",
  "blast.hitGeneId": "Gene ID",
  "blast.hitCoverage": "Coverage",
  "blast.hitEValue": "E-value",
  // help
  "help.gettingStarted": "Getting Started",
  "help.documentation": "Documentation",
  "help.contact": "Contact Support",
  "help.faq": "Frequently Asked Questions",
  "help.faq1.q": "How do I search for a gene?",
  "help.faq1.a": "Use the search bar at the top of any page, or visit the Genes page to filter by chromosome, biotype, or keyword. Gene IDs follow the Glyma.01G000100 format.",
  "help.faq2.q": "How do I download variant data?",
  "help.faq2.a": "Visit the Downloads page for the files currently published for a release. Check each item's format, assembly, release, and provenance metadata before using it in an analysis.",
  "help.faq3.q": "Can I request mutant seeds?",
  "help.faq3.a": "Open the Seed Request page to see whether requests are currently enabled and to review the eligibility and distribution terms shown during submission.",
  "help.faq4.q": "How do I cite SoyMutDB?",
  "help.faq4.a": "Use the citation and provenance metadata published with the exact data release you used. A journal citation or DOI is shown only after it has been verified by the project maintainers.",
  "help.faq5.q": "What genome assembly is used?",
  "help.faq5.a": "The assembly is part of the search, record, browser, and download context. Confirm the displayed assembly before comparing or combining genomic coordinates.",
  "help.faq6.q": "How often is the data updated?",
  "help.faq6.a": "Release versions and publication dates are announced on the News and Downloads pages. SoyMutDB does not promise a fixed release cadence on this Help page.",
  // generic ui
  "ui.searchButton": "Search",
  "ui.submit": "Submit",
  "ui.loading": "Loading...",
  "ui.errorRetry": "Retry",
  "ui.noResults": "No results found",
  "nav.home": "Home",
  "nav.search": "Search",
  "nav.tools": "Tools",
  "nav.latestNews": "Latest News",
  "nav.contact": "Contact",
  "nav.explore": "Explore",
  "nav.resources": "Resources",
  "nav.downloads": "Downloads",
  "nav.allTools": "All tools",
  "nav.genes": "Genes",
  "nav.variants": "Variants",
  "nav.browser": "Genome Browser",
  "nav.blast": "BLAST",
  "nav.analyses": "Analyze",
  "nav.sra": "SRA Browser",
  "nav.compare": "Compare",
  "nav.analytics": "Analytics",
  "nav.guide": "Guide",
  "nav.help": "Help",
  "nav.news": "News",
  "nav.publications": "Publications",
  "nav.seedRequest": "Seed Request",
  "nav.about": "About",
  "common.loading": "Loading...",
  "common.retry": "Retry",
  "common.submit": "Submit",
  "common.clear": "Clear",
  "common.reset": "Reset",
  "common.empty": "No data available",
  "common.error": "Error",
  "common.viewAll": "View All",
  "genes.title": "Gene Search",
  "genes.subtitle": "Browse gene models, annotations and homologs",
  "genes.colGeneId": "Gene ID",
  "genes.colChromosome": "Chromosome",
  "genes.colBiotype": "Biotype",
  "genes.colVariantCount": "Variant Count",
  "genes.colSymbol": "Symbol",
  "genes.colPosition": "Position",
  "variants.title": "Variant Search",
  "variants.subtitle": "Search and explore genomic variant information",
  "variants.colVariantId": "Variant ID",
  "variants.colChromosome": "Chromosome",
  "variants.colPosition": "Position",
  "variants.colRefAlt": "Ref→Alt",
  "variants.colVariantType": "Type",
  "variants.colImpact": "Impact",
  "variants.colGeneSymbol": "Gene Symbol",
  "guide.title": "NCBI Database Retrieval Operation Guide",
  "guide.subtitle": "Comprehensive guide for NCBI database retrieval including BLAST, Entrez, JBrowse, and E-utilities",
  "downloads.title": "Downloads",
  "downloads.subtitle": "Download genomic data and resources",
  "search.genes.assembly": "Genome version",
  "search.genes.assemblyPlaceholder": "Select a genome version",
  "search.genes.geneIdHint": "Multiple gene IDs are supported — one per line.",
  "search.genes.geneIdPlaceholder": "One gene ID per line, e.g. Glyma.01G000100",
  "search.location.assembly": "Genome version",
  "search.location.chromosome": "Chromosome",
  "search.location.start": "Start",
  "search.location.end": "End",
  "search.location.submit": "Search",
};

/** Internal starts with a distinct safe default copy before the authenticated
 * content request resolves. Administrators can replace every field per site.
 * Vite constant-folds this branch, so the external artifact does not carry the
 * internal default copy. */
const SITE_CONTENT_DEFAULTS_FOR_BUILD: Record<string, string> = __SOYMUTDB_INTERNAL_SITE__
  ? {
      ...SITE_CONTENT_DEFAULTS,
      "hero.eyebrow": "SOYMUTDB · INTERNAL RESEARCH",
      "hero.title": "Internal Research Workspace for SoyMutDB",
      "hero.subtitle": "A private workspace for curators and collaborators to review mutation data, releases, and analysis tools.",
      "nav.home": "Research Workspace",
      "nav.about": "Project Notes",
    }
  : SITE_CONTENT_DEFAULTS;

export interface SiteContentContextValue {
  /** The loaded site-content map, undefined while loading or on error. */
  data?: SiteContent;
  /** True while the initial content query is pending. */
  isPending: boolean;
  /** True when the content query failed (the hook still returns fallbacks). */
  isError: boolean;
  /**
   * Resolve a content key with an optional caller-provided fallback.
   * @param key      short content key, e.g. "hero.title"
   * @param fallback optional value used before data loads / when the key is
   *                 absent from the loaded map; falls back to the built-in
   *                 site-content defaults when omitted.
   * @returns the resolved string (never undefined).
   */
  get: (key: string, fallback?: string) => string;
}

const SiteContentContext = React.createContext<SiteContentContextValue | undefined>(
  undefined,
);

export function SiteContentProvider({ children }: { children: React.ReactNode }) {
  const query = useQuery({
    queryKey: ["site-content", SITE_VARIANT],
    queryFn: () => getSiteContent(SITE_VARIANT),
    staleTime: 60_000,
    retry: false,
  });

  const data = query.data;

  const get = React.useCallback(
    (key: string, fallback?: string): string => {
      const value = data?.[key];
      if (value !== undefined) return value;
      if (fallback !== undefined) return fallback;
      return SITE_CONTENT_DEFAULTS_FOR_BUILD[key] ?? "";
    },
    [data],
  );

  const value = React.useMemo<SiteContentContextValue>(
    () => ({ data, isPending: query.isPending, isError: query.isError, get }),
    [data, query.isPending, query.isError, get],
  );

  return (
    <SiteContentContext.Provider value={value}>
      {children}
    </SiteContentContext.Provider>
  );
}

export function useSiteContent(): SiteContentContextValue {
  const context = React.useContext(SiteContentContext);
  if (context === undefined) {
    throw new Error("useSiteContent must be used within a SiteContentProvider");
  }
  return context;
}
