import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * Gene ID search — second-level catalog of the /search portal.
 *
 * URL-backed and shareable (Phase 4): the result view reads `q`, `assembly`,
 * and `run` search params. A parameterized URL restores the form state and
 * runs once; the form submit opens a new tab via
 * `window.open(router.buildLocation(...).href, "_blank", "noopener")`.
 *
 * Result columns follow the approved reference order:
 *   Genome assembly → Chromosome → Position → Mutation feature → Gene ID →
 *   JBrowse 2 action.
 */
import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../../lib/site-content-react";
import * as React from "react";
import { Alert, Button, Empty, Flex, Input, Select, Table, Tag, Typography, type TableColumnsType } from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  isTestDataPreviewAssembly,
  listTestDataPreviewMutationSitesForGene,
  searchGenes,
  type GeneSummary,
  type AssemblyInfo,
  type TestDataPreviewMutationSite,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { formatNumber } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
import { buildJbrowseLocusUrl } from "../../lib/deployment";
import { resolveSearchAssembly } from "../../lib/search-assembly";
import { useReleaseId } from "../../lib/release-scope";

/**
 * One rendered result row: a source mutation-site row joined to its catalogue
 * gene. Either half may be absent — a source row can point at a gene outside the
 * current catalogue page, and a catalogue gene can have no source row.
 */
interface MergedResultRow {
  key: string;
  site: TestDataPreviewMutationSite | null;
  gene: GeneSummary | null;
  /**
   * The token the operator actually typed that produced this row.
   *
   * `site.gene_id` is the *record's* accession; a search can be spelled with a
   * bare locus name, one of the three homolog accessions, or the full versioned
   * accession, and all of them resolve to the same source row. Without this the
   * table cannot answer "which of my inputs found this", which is the first
   * thing an operator checks when one of several IDs comes back empty.
   */
  queryGeneId: string;
}

interface GeneSearchParams {
  q?: string;
  assembly?: string;
  run?: boolean;
}

export const Route = createFileRoute("/search/genes")({
  component: GeneIdSearchComponent,
  validateSearch: (search: Record<string, unknown>): GeneSearchParams => ({
    q: search.q ? String(search.q) : undefined,
    assembly: search.assembly ? String(search.assembly) : undefined,
    run: search.run === "1" || search.run === 1 || search.run === true,
  }),
});

const PAGE_SIZE = 20;

/**
 * Half-width of the window the locus picker opens on an insertion site: 10 kb
 * upstream and downstream of the site, per the operator's convention. It is a
 * URL parameter rather than a constant in the browser page so a link can ask
 * for a different window without a code change.
 */
const INSERTION_FLANK_BP = 10_000;

interface Submitted {
  q: string;
  assemblyId: string;
}

function GeneIdSearchComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const router = useRouter();
  // A release may be published while this route stays mounted. Subscribe to
  // ReleaseScopeProvider so query keys and JBrowse deep links are repinned
  // atomically, rather than capturing a stale getReleaseId() snapshot.
  const releaseId = useReleaseId();
  const { q: urlQ, assembly: urlAssembly, run } = Route.useSearch();
  const [geneIdsRaw, setGeneIdsRaw] = React.useState(() => urlQ ?? "");
  const [page, setPage] = React.useState(1);

  const assembliesQuery = useQuery(assembliesQueryOptions({
    releaseId,
    siteVariant: SITE_VARIANT,
  }));
  const assemblies = assembliesQuery.data;

  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  // Preselect the URL assembly when present; otherwise use the configured
  // default (or first) assembly. These are derived values, not state that
  // needs a follow-up effect after the assemblies request resolves.
  const urlAssemblyInfo = resolveSearchAssembly(assemblies, urlAssembly);
  const urlAssemblyId = urlAssemblyInfo ? String(urlAssemblyInfo.id) : undefined;
  const formAssemblyId = assemblyId ?? urlAssemblyId;

  // History navigation must override a prior unsubmitted local assembly choice.
  React.useEffect(() => {
    setAssemblyId(undefined);
  }, [urlAssembly]);

  // The route is updated in place now, so the submitted context follows the
  // live URL rather than a mount-time snapshot: a second search on this page
  // must replace the first result set instead of keeping the stale one.
  const submitted: Submitted | null = React.useMemo(() => {
    const q = urlQ?.trim();
    if (!q) return null;
    if (!(run === true || urlAssembly != null)) return null;
    if (urlAssemblyId === undefined) return null;
    return { q, assemblyId: urlAssemblyId };
  }, [urlQ, urlAssembly, run, urlAssemblyId]);

  // Keep the field in step with the URL so a shared link and a repeat search
  // both show the identifier that is actually being searched.
  React.useEffect(() => {
    if (urlQ == null) return;
    setGeneIdsRaw((prev) => (prev === urlQ ? prev : urlQ));
  }, [urlQ]);

  // A new query starts on its first page.
  React.useEffect(() => {
    setPage(1);
  }, [urlQ, urlAssembly]);
  // Once a search is submitted, its assembly is the result context. This
  // keeps the request, result label, and JBrowse deep link aligned even if
  // the form state changes later.
  const resolvedAssemblyId = submitted?.assemblyId ?? formAssemblyId;
  const selectedAssembly: AssemblyInfo | undefined = assemblies?.find(
    (a) => String(a.id) === String(resolvedAssemblyId),
  );

  const resultsQuery = useQuery({
    queryKey: queryKeys.genes.search({
      q: submitted?.q,
      assemblyId: submitted?.assemblyId,
      page: 1,
      pageSize: PAGE_SIZE,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      searchGenes({
        q: submitted?.q || undefined,
        assembly_id: submitted?.assemblyId || undefined,
        page: 1,
        page_size: PAGE_SIZE,
      } as Parameters<typeof searchGenes>[0]),
    enabled: submitted != null,
    // Keep previous rows only while the biological/deployment context is
    // unchanged (same query + assembly); a context switch must never present
    // old-context rows as new-context results. Page changes share the cache.
    placeholderData: (prev, prevQuery) => {
      const prevKey = prevQuery?.queryKey as readonly unknown[] | undefined;
      const sameContext =
        prevKey != null &&
        (prevKey[3] ?? null) === (submitted?.q ?? null) &&
        (prevKey[4] ?? null) === (submitted?.assemblyId ?? null);
      return sameContext ? prev : undefined;
    },
  });

  const data = resultsQuery.data?.items ?? [];
  const total = resultsQuery.data?.total ?? 0;

  // The operator's own source rows for the searched gene IDs. Queried per exact
  // ID (the field accepts several) and via the gene relation rather than a
  // coordinate interval, because 13% of rows sit outside their gene's range.
  const previewSitesQuery = useQuery({
    queryKey: ["search-preview-mutation-sites", releaseId, SITE_VARIANT, submitted?.assemblyId, submitted?.q, resultsQuery.dataUpdatedAt],
    queryFn: async () => {
      // Only what the operator typed. Matching is exact by design, so the
      // catalogue's fuzzy result must not widen it: searching a bare locus name
      // like `Glyma.01G000100` resolves to nothing here even though the
      // catalogue search page finds the gene. What does resolve is a full
      // accession or any of the three homolog accessions.
      const geneIds = [...new Set((submitted?.q ?? "").split(/[\s,]+/).filter(Boolean))];
      const pages = await Promise.all(
        geneIds.map(async (geneId) => ({
          geneId,
          sites: await listTestDataPreviewMutationSitesForGene(geneId, 1000),
        })),
      );
      // The typed value and the resolved accession are usually the same locus
      // spelled differently (bare name vs versioned accession), so both queries
      // return the same source rows. Deduplicate on the source key, otherwise one
      // record renders twice. The first input that found a row keeps credit for
      // it, which is what the "搜索基因" column reports back.
      const seen = new Map<string, { site: TestDataPreviewMutationSite; queryGeneId: string }>();
      for (const { geneId, sites } of pages) {
        for (const site of sites) {
          if (!seen.has(site.source_site_key)) {
            seen.set(site.source_site_key, { site, queryGeneId: geneId });
          }
        }
      }
      return [...seen.values()];
    },
    // Wait for the catalogue result so the resolved accessions are known; a
    // preview API failure is an error, not an empty dataset.
    // Unpublished preview rows are pinned to one assembly by the API client.
    // Do not present their source coordinates as results for another genome.
    enabled: Boolean(submitted?.q) && !resultsQuery.isLoading && isTestDataPreviewAssembly(selectedAssembly?.name),
    retry: false,
  });
  const previewSites = previewSitesQuery.data ?? [];

  // The result table IS the operator's source table: one row per source record,
  // joined to its catalogue row so assembly context and the JBrowse entry live
  // on the row itself.
  //
  // Catalogue genes WITHOUT a source row are deliberately omitted. A broad query
  // such as "Gl" matches tens of thousands of genes of which almost none carry
  // source data, and padding the table with blank rows would bury the handful
  // that do. No source rows therefore means an empty result, shown as 0.
  const mergedRows = React.useMemo<MergedResultRow[]>(() => {
    const byGene = new Map(data.map((gene) => [gene.gene_id, gene]));
    return previewSites.map(({ site, queryGeneId }) => ({
      key: `site:${site.source_site_key}`,
      site,
      gene: byGene.get(site.gene_id) ?? null,
      queryGeneId,
    }));
  }, [data, previewSites]);

  // A genome-version context is mandatory: without it the request would be
  // ambiguous across the v4/v5 coordinate namespaces. The control therefore
  // reports "not yet selectable" instead of silently discarding the submit.
  const assemblyContextReady = formAssemblyId !== undefined;
  // Search updates this page in place: the route re-reads its own search
  // params and `submitted` derives from them, so results refresh without
  // opening a new tab or window.
  const submit = () => {
    // Single-line field: accept IDs separated by pasted newlines, commas or
    // spaces and normalise them into one space-delimited query.
    const q = geneIdsRaw.trim().replace(/[\s,]+/g, " ");
    if (!q || !formAssemblyId) return;
    void router.navigate({
      to: "/search/genes",
      search: { q, assembly: formAssemblyId, run: true },
    });
  };


  // The operator's own column order, with the catalogue context (assembly
  // version, JBrowse entry) folded into the same row instead of a second table.
  const mergedColumns: TableColumnsType<MergedResultRow> = [
    {
      // The operator's own input, left of everything the record says about
      // itself: a multi-ID search returns one block of rows per input, and this
      // is the column that says which input produced the row.
      title: t("genes.mutationSites.queryGene", { defaultValue: "搜索基因" }),
      key: "query_gene_id",
      width: 220,
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.queryGeneId }}
          search={{ assembly: resolvedAssemblyId }}
          aria-label={t("search.genes.openGene", { geneId: row.queryGeneId })}
          className="link-underline font-mono text-xs font-medium"
          title={row.queryGeneId}
        >
          {row.queryGeneId}
        </Link>
      ),
    },
    {
      title: t("genes.mutationSites.siteKey", { defaultValue: "突变体系（株系母+位置）" }),
      key: "source_site_key",
      render: (_, row) => {
        if (!row.site) return <span className="text-muted-foreground">—</span>;
        // The locus picker: opens the portal's own genome view centred on the
        // insertion site, 10 kb up and downstream, instead of the JBrowse 2
        // service. The site key stays the label so the row is still readable
        // when JavaScript has not run.
        const chromosome = row.site.chromosome;
        return (
          <Link
            to="/genome-view"
            search={{
              // The locus route types `assembly` as a number because the API
              // takes one; the catalogue's own assembly id travels as a string.
              assembly:
                resolvedAssemblyId != null && resolvedAssemblyId !== ""
                  ? Number(resolvedAssemblyId)
                  : undefined,
              chromosome,
              position: row.site.position,
              flank: INSERTION_FLANK_BP,
            }}
            className="link-underline font-mono text-xs font-medium text-primary"
            title={t("genes.mutationSites.openLocus", {
              defaultValue: "在基因组视图中打开该插入位点（上下游各 10 kb）",
            })}
            aria-label={t("genes.mutationSites.openLocus", {
              defaultValue: "在基因组视图中打开该插入位点（上下游各 10 kb）",
            })}
          >
            {row.site.source_site_key}
          </Link>
        );
      },
    },
    {
      title: t("genes.mutationSites.chromosome", { defaultValue: "染色体号" }),
      key: "chromosome",
      width: 100,
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.site?.chromosome ?? row.gene?.chromosome ?? "—"}
        </span>
      ),
    },
    {
      title: t("genes.mutationSites.position", { defaultValue: "位点" }),
      key: "position",
      align: "right",
      width: 120,
      render: (_, row) =>
        row.site ? (
          <span className="font-mono text-xs">{formatNumber(row.site.position)}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: t("genes.mutationSites.confidence", { defaultValue: "可信度" }),
      key: "confidence",
      width: 90,
      render: (_, row) =>
        row.site ? (
          <Tag color={row.site.confidence === "H" ? "green" : "default"}>
            {row.site.confidence === "H" ? "高" : "低"}
          </Tag>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: t("genes.mutationSites.geneId", { defaultValue: "基因号" }),
      key: "gene_id",
      render: (_, row) => {
        const geneId = row.site?.gene_id ?? row.gene?.gene_id;
        if (!geneId) return <span className="text-muted-foreground">—</span>;
        return (
          <Link
            to="/genes/$geneId"
            params={{ geneId }}
            search={{ assembly: resolvedAssemblyId }}
            aria-label={t("search.genes.openGene", { geneId })}
            className="link-underline font-mono text-xs font-medium text-primary"
            title={geneId}
          >
            {geneId}
          </Link>
        );
      },
    },
    {
      title: t("genes.mutationSites.feature", { defaultValue: "特征" }),
      key: "feature",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.site?.feature ?? "—"}</span>
      ),
    },
    {
      title: t("genes.mutationSites.available", { defaultValue: "可获得" }),
      key: "available",
      width: 100,
      render: (_, row) =>
        row.site ? (
          <Tag color={row.site.available ? "green" : "default"}>
            {row.site.available ? "是" : "否"}
          </Tag>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    // The W82_V2 / W82_V4 / DN53_V1 homolog accessions are deliberately NOT
    // columns. They are alternate identifiers for the same locus, so they exist
    // to make a search hit, not to be read off the page.
    {
      // Catalogue context folded in from the gene result.
      title: get("search.genes.colAssembly", t("search.genes.colAssembly")),
      key: "assembly",
      width: 150,
      render: () => <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>,
    },
    {
      title: get("search.genes.colGbrowse", t("search.genes.colGbrowse")),
      key: "jbrowse",
      width: 140,
      render: (_, row, index) => {
        const chromosome = row.gene?.chromosome ?? row.site?.chromosome;
        const start = row.gene?.start_pos;
        const end = row.gene?.end_pos;
        const locus =
          chromosome && start != null && end != null
            ? `${chromosome}:${start}-${end}`
            : row.site
              ? `${row.site.chromosome}:${row.site.position}-${row.site.position}`
              : null;
        return (
          <Button
            size="small"
            data-testid={`jbrowse-link-${index}`}
            disabled={!selectedAssembly || !locus}
            href={
              selectedAssembly && locus
                ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
                    assembly: selectedAssembly.name,
                    locus,
                    release: releaseId ?? undefined,
                  }).href
                : undefined
            }
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("search.genes.openBrowser")}
          </Button>
        );
      },
    },
  ];

  return (
    <FadeUp>
      <div className="py-6">
        <h1 className="eyebrow">{get("search.genes.title", t("search.genes.title"))}</h1>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {get("search.genes.subtitle", t("search.genes.subtitle"))}
        </h2>

        {/* One compact control row: label / assembly / label / identifier /
            submit. antd's `Space` keeps every control on the same baseline, so
            the row no longer depends on flex alignment of mixed heights. */}
        <div className="mt-6 rounded-xl border border-border/70 bg-card p-4 sm:p-5" data-testid="search-genes-form">
          {/* `Flex`, not `Space`: a Space item is an inline-flex box that does
              not grow, so `width: 100%` inside it resolved against an
              already-collapsed box and the identifier field rendered 180px
              wide however large `maxWidth` was. A flex item can actually take
              the remaining space, which is what makes the row adapt.

              Two nesting levels on purpose: `gap={8}` binds each label to its
              own control, `gap={20}` separates the two groups. With a single
              gap the "基因 ID" label sat 12px from the assembly Select and read
              as that control's caption. */}
          <Flex wrap align="center" gap={20}>
            <Flex wrap align="center" gap={8} className="w-full min-w-0 sm:w-auto">
              <label
                htmlFor="genes-assembly"
                className="whitespace-nowrap text-sm text-muted-foreground"
              >
                {get("search.genes.assembly", t("search.genes.assembly"))}
              </label>
              <Select
                id="genes-assembly"
                value={formAssemblyId}
                onChange={(v) => setAssemblyId(v)}
                placeholder={get("search.genes.assemblyPlaceholder", t("search.genes.assemblyPlaceholder"))}
                loading={assembliesQuery.isLoading}
                data-testid="search-genes-assembly"
                size="large"
                style={{ width: "min(280px, 100%)" }}
                options={assemblies?.map((a) => ({
                  value: String(a.id),
                  label: (
                    <span className="flex items-center gap-2">
                      <span>{a.name}</span>
                      {a.is_default ? (
                        <Tag className="m-0 text-[9px] uppercase">{t("home.defaultAssembly")}</Tag>
                      ) : null}
                    </span>
                  ),
                })) ?? []}
              />
            </Flex>
            <Flex
              wrap
              align="center"
              gap={8}
              // The group takes the leftover row width, so the identifier field
              // tracks the viewport instead of stopping at a fixed 560px.
              style={{ flex: "1 1 360px", minWidth: 0 }}
            >
              <span className="whitespace-nowrap text-sm text-muted-foreground">
                {get("search.genes.geneId", t("search.genes.geneId"))}
              </span>
              {/* A textarea, not a single-line input: the field accepts several
                  identifiers and operators paste them one per line. Enter submits,
                  Shift+Enter inserts a newline. */}
              <Input.TextArea
                value={geneIdsRaw}
                onChange={(e) => setGeneIdsRaw(e.target.value)}
                onPressEnter={(event) => {
                  if (!event.shiftKey) {
                    event.preventDefault();
                    submit();
                  }
                }}
                placeholder={get("search.genes.geneIdPlaceholder", t("search.genes.geneIdPlaceholder"))}
                className="font-mono"
                autoSize={{ minRows: 2, maxRows: 6 }}
                // Grows into the leftover row space, but never below a width
                // that still shows a full accession; wraps to its own line when
                // the row runs out.
                style={{ flex: "1 1 220px", minWidth: 0 }}
                data-testid="search-genes-input"
                aria-label={get("search.genes.geneId", t("search.genes.geneId"))}
              />
            </Flex>
            <Button
              type="primary"
              size="large"
              onClick={submit}
              data-testid="search-genes-submit"
              icon={<SearchOutlined aria-hidden />}
              loading={resultsQuery.isFetching}
              disabled={!assemblyContextReady}
              title={assemblyContextReady ? undefined : t("home.assembliesUnavailable")}
            >
              {get("ui.searchButton", t("search.genes.submit"))}
            </Button>
          </Flex>
          <Typography.Text type="secondary" className="mt-2 block text-xs">
            {get("search.genes.geneIdHint", t("search.genes.geneIdHint"))}
          </Typography.Text>
          {assembliesQuery.isError || (urlAssembly && assemblies && !urlAssemblyInfo) ? (
            <Alert
              className="mt-3"
              type="error"
              showIcon
              title={t(urlAssembly && !urlAssemblyInfo && assemblies ? "search.assemblyUnavailable" : "home.assembliesUnavailable")}
            />
          ) : null}
        </div>

        {submitted ? (
          <div className="mt-6 rounded-xl border border-border/70 bg-card p-4 sm:p-5" role="region" aria-label={t("search.genes.resultsAria")}>
            <p className="mb-3 text-sm text-muted-foreground">
              {t("search.genes.resultsFor")}{" "}
              <span className="font-mono text-foreground">"{submitted.q}"</span>
              {" · "}
              {/* The count is the source-record count, because that is what the
                  table below shows. The catalogue match count is not displayed:
                  a broad query can match tens of thousands of genes and still
                  have nothing to show. */}
              <span data-testid="search-genes-site-total" className="font-mono text-foreground">
                {formatNumber(mergedRows.length)}
              </span>
              <span data-testid="search-genes-total" className="hidden font-mono">
                {formatNumber(total)}
              </span>
            </p>
            {!isTestDataPreviewAssembly(selectedAssembly?.name) ? (
              <Alert type="warning" showIcon title={t("search.genes.previewAssemblyMismatch", {
                defaultValue: "Source mutation-site preview data belong only to the unpublished Gmax_880_v6.0 assembly; they cannot be shown under another assembly.",
              })} />
            ) : resultsQuery.isError || previewSitesQuery.isError ? (
              <Alert
                type="error"
                showIcon
                title={t("search.genes.resultsUnavailable")}
                description={get("ui.errorRetry", t("search.genes.resultsRetry"))}
              />
            ) : (
              // One table: the source mutation-site rows with the catalogue
              // context folded into each row. `search-genes-mutation-sites`
              // aliases the same node so existing selectors keep resolving.
              <div
                className="-mx-4 overflow-x-auto sm:mx-0"
                data-testid="search-genes-table"
                data-mutation-sites-table={previewSites.length > 0 ? "true" : undefined}
              >
                <Table<MergedResultRow>
                  rowKey="key"
                  size={previewSites.length > 0 ? "small" : "middle"}
                  bordered={previewSites.length > 0}
                  columns={mergedColumns}
                  dataSource={mergedRows}
                  loading={resultsQuery.isLoading || previewSitesQuery.isLoading}
                  pagination={{
                    current: page,
                    pageSize: PAGE_SIZE,
                    total: mergedRows.length,
                    showSizeChanger: false,
                    showTotal: (n, range) =>
                      `${formatNumber(range[0])}–${formatNumber(range[1])} of ${formatNumber(n)}`,
                    onChange: (p) => setPage(p),
                  }}
                  scroll={{ x: "max-content" }}
                  locale={{
                    emptyText: (
                      <div data-testid="search-genes-empty">
                        <Empty
                          description={
                            <Typography.Text type="secondary">
                              {get("ui.noResults", t("search.genes.noResults"))}
                            </Typography.Text>
                          }
                        />
                      </div>
                    ),
                  }}
                />
              </div>
            )}
          </div>
        ) : null}
      </div>
    </FadeUp>
  );
}
