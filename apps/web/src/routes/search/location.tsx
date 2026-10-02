/**
 * Physical location search — second-level catalog of the /search portal.
 *
 * URL-backed and shareable (Phase 4): reads `assembly`, `chromosome`,
 * `start`, `end`, and `run` search params. A parameterized URL restores form
 * state and runs once; the form submit opens a parameterized `/search/location`
 * URL in a new tab with `noopener`.
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
import {
  Alert,
  Button,
  Empty,
  Flex,
  InputNumber,
  Select,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  searchTestDataPreviewMutationSites,
  getAssemblies,
  getAssemblyChromosomes,
  getReleaseId,
  type TestDataPreviewMutationSite,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { formatNumber } from "../../lib/format";
import { buildJbrowseLocusUrl } from "../../lib/deployment";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
import { resolveSearchAssembly } from "../../lib/search-assembly";

interface LocationSearchParams {
  assembly?: string;
  chromosome?: string;
  start?: number;
  end?: number;
  run?: boolean;
}

export const Route = createFileRoute("/search/location")({
  component: LocationSearchComponent,
  validateSearch: (search: Record<string, unknown>): LocationSearchParams => ({
    assembly: search.assembly ? String(search.assembly) : undefined,
    chromosome: search.chromosome ? String(search.chromosome) : undefined,
    start: search.start != null && search.start !== "" ? Number(search.start) : undefined,
    end: search.end != null && search.end !== "" ? Number(search.end) : undefined,
    run: search.run === "1" || search.run === 1 || search.run === true,
  }),
});

interface RegionQuery {
  assembly: string;
  assemblyId: string;
  chromosome: string;
  start: number;
  end: number;
}

function LocationSearchComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const router = useRouter();
  const releaseId = getReleaseId();
  const { assembly: urlAssembly, chromosome: urlChromosome, start: urlStart, end: urlEnd, run } =
    Route.useSearch();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  const [chromosome, setChromosome] = React.useState<string | undefined>(undefined);
  const [start, setStart] = React.useState<number | null>(null);
  const [end, setEnd] = React.useState<number | null>(null);
  const [submitted, setSubmitted] = React.useState<RegionQuery | null>(null);

  const assembliesQuery = useQuery({
    queryKey: queryKeys.assemblies.list({ releaseId, siteVariant: SITE_VARIANT }),
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = React.useMemo(() => assembliesQuery.data ?? [], [assembliesQuery.data]);
  const selectedAssembly: AssemblyInfo | undefined = assemblies.find(
    (a) => String(a.id) === String(assemblyId),
  );
  const linkedAssembly = resolveSearchAssembly(assemblies, urlAssembly);
  const resultAssembly = assemblies.find((a) => String(a.id) === submitted?.assemblyId);

  React.useEffect(() => {
    if (assemblyId || urlAssembly || assemblies.length === 0) return;
    const def = resolveSearchAssembly(assemblies);
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId, urlAssembly]);

  const chromosomesQuery = useQuery({
    queryKey: queryKeys.assemblies.chromosomes(assemblyId, { releaseId, siteVariant: SITE_VARIANT }),
    queryFn: () => getAssemblyChromosomes(assemblyId!),
    enabled: Boolean(assemblyId),
    staleTime: 30 * 60 * 1000,
  });
  const chromosomes = React.useMemo(
    () => chromosomesQuery.data ?? [],
    [chromosomesQuery.data],
  );

  React.useEffect(() => {
    // Prune only after the chromosome list has actually arrived. Running this
    // against the initial empty list wiped a deep-linked chromosome, leaving
    // the control blank (and submit disabled) while the results below still
    // rendered from the URL values.
    if (!chromosomesQuery.isSuccess) return;
    if (chromosome && !chromosomes.some((item) => item.name === chromosome)) {
      setChromosome(undefined);
    }
  }, [chromosome, chromosomes, chromosomesQuery.isSuccess]);

  // Deep link: restore form state from URL once assemblies/chromosomes load.
  const restoredRef = React.useRef(false);
  React.useEffect(() => {
    if (restoredRef.current) return;
    // Resolve the explicit URL assembly without substituting a default version.
    if (urlAssembly && linkedAssembly) setAssemblyId(String(linkedAssembly.id));
    if (urlChromosome) setChromosome(urlChromosome);
    if (urlStart != null) setStart(urlStart);
    if (urlEnd != null) setEnd(urlEnd);
  }, [urlAssembly, urlChromosome, urlStart, urlEnd, linkedAssembly]);

  const autoRun = (assembly: AssemblyInfo, chr: string, s: number, e: number): RegionQuery | null => {
    if (!Number.isSafeInteger(s) || !Number.isSafeInteger(e) || s < 1 || e < s) return null;
    return { assembly: assembly.name, assemblyId: String(assembly.id), chromosome: chr, start: s, end: e };
  };

  // Auto-submit once when `run=1` arrives with a complete, valid region.
  React.useEffect(() => {
    if (restoredRef.current) return;
    if (run !== true) return;
    if (!selectedAssembly || !urlChromosome || urlStart == null || urlEnd == null) return;
    if (urlAssembly && String(selectedAssembly.id) !== urlAssembly && selectedAssembly.name !== urlAssembly) return;
    if (!chromosomes.some((item) => item.name === urlChromosome)) return;
    const query = autoRun(selectedAssembly, urlChromosome, urlStart, urlEnd);
    if (!query) return;
    restoredRef.current = true;
    setSubmitted(query);
  }, [run, selectedAssembly, urlAssembly, urlChromosome, urlStart, urlEnd, chromosomes]);

  // The operator's own source records for the interval. The region-variant
  // projection is a separate store that is often empty for these coordinates,
  // while the uploaded table has rows at exactly the coordinates a person
  // searches for, so that table is what this page shows.
  const sitesQuery = useQuery({
    queryKey: ["search-region-preview-sites", submitted],
    queryFn: () =>
      searchTestDataPreviewMutationSites({
        chromosome: submitted!.chromosome,
        start: submitted!.start,
        end: submitted!.end,
        limit: 1000,
      }),
    enabled: submitted != null,
    // A missing preview route (non-local deployment) is a normal answer here.
    retry: false,
  });
  const sites = sitesQuery.data?.items ?? [];

  const siteColumns: TableColumnsType<TestDataPreviewMutationSite> = [
    {
      title: t("genes.mutationSites.siteKey", { defaultValue: "突变体系（株系母+位置）" }),
      dataIndex: "source_site_key",
      key: "source_site_key",
      render: (_, row) => <span className="font-mono text-xs">{row.source_site_key}</span>,
    },
    {
      title: t("genes.mutationSites.chromosome", { defaultValue: "染色体号" }),
      dataIndex: "chromosome",
      key: "chromosome",
      width: 100,
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: t("genes.mutationSites.position", { defaultValue: "位点" }),
      dataIndex: "position",
      key: "position",
      align: "right",
      width: 120,
      render: (_, row) => <span className="font-mono text-xs">{formatNumber(row.position)}</span>,
    },
    {
      title: t("genes.mutationSites.confidence", { defaultValue: "可信度" }),
      dataIndex: "confidence",
      key: "confidence",
      width: 90,
      render: (_, row) => (
        <Tag color={row.confidence === "H" ? "green" : "default"}>
          {row.confidence === "H" ? "高" : "低"}
        </Tag>
      ),
    },
    {
      title: t("genes.mutationSites.geneId", { defaultValue: "基因号" }),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          search={{ assembly: assemblyId }}
          title={row.gene_id}
          className="link-underline whitespace-nowrap font-mono text-xs font-medium text-primary"
        >
          {row.gene_id}
        </Link>
      ),
    },
    {
      title: t("genes.mutationSites.feature", { defaultValue: "特征" }),
      dataIndex: "feature",
      key: "feature",
      render: (_, row) => <span className="font-mono text-xs">{row.feature}</span>,
    },
    {
      title: t("genes.mutationSites.available", { defaultValue: "可获得" }),
      dataIndex: "available",
      key: "available",
      width: 100,
      render: (_, row) => (
        <Tag color={row.available ? "green" : "default"}>{row.available ? "是" : "否"}</Tag>
      ),
    },
    {
      title: get("search.genes.colGbrowse", t("search.location.colGbrowse")),
      key: "jbrowse",
      width: 140,
      render: (_, row, index) => (
        <Button
          size="small"
          data-testid={`jbrowse-link-${index}`}
          disabled={!resultAssembly}
          href={
            resultAssembly
              ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
                  assembly: resultAssembly.name,
                  locus: `${row.chromosome}:${row.position}-${row.position}`,
                  release: releaseId ?? undefined,
                }).href
              : undefined
          }
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("search.genes.openBrowser")}
        </Button>
      ),
    },
  ];

  // Search updates this page in place: the region is applied to the local
  // result state immediately, while `replace` keeps the URL shareable without
  // stacking a history entry per submit.
  const submit = () => {
    if (!selectedAssembly || !chromosome || start == null || end == null) return;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 1 || end < start) return;
    setSubmitted({
      assembly: selectedAssembly.name,
      assemblyId: String(selectedAssembly.id),
      chromosome,
      start,
      end,
    });
    void router.navigate({
      to: "/search/location",
      search: { assembly: selectedAssembly.name, chromosome, start, end, run: true },
      replace: true,
    });
  };


  const formValid =
    Boolean(selectedAssembly) &&
    Boolean(chromosome) &&
    start != null &&
    end != null &&
    Number.isSafeInteger(start) &&
    Number.isSafeInteger(end) &&
    start >= 1 &&
    end >= start;

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{get("search.location.title", t("search.location.title"))}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {get("search.location.subtitle", t("search.location.subtitle"))}
        </h2>

        {/* One compact control row: assembly / chromosome / start / end /
            submit. Each label is wrapped together with its control in a
            non-shrinking group, so a wrap can only happen *between* fields —
            `Space wrap` used to break the label away from its input and leave
            the tail of the row clipped. */}
        <div className="mt-6" data-testid="location-form">
          {/* `gap={20}` between groups, `gap={8}` inside one: a single 12px gap
              made four fields read as one long undifferentiated row. Every
              group is `shrink-0` because these are fixed-width coordinate
              inputs; a wrap is only ever allowed between groups. */}
          <Flex wrap align="center" gap={20}>
            <Flex align="center" gap={8} className="shrink-0">
            <span className="whitespace-nowrap text-sm text-muted-foreground">
              {get("search.location.assembly", t("search.location.assembly"))}
            </span>
            <Select
              value={assemblyId}
              onChange={(v) => setAssemblyId(v)}
              placeholder={get("search.location.assemblyPlaceholder", t("search.location.assemblyPlaceholder"))}
              loading={assembliesQuery.isLoading}
              data-testid="location-assembly"
              size="large"
              style={{ width: 260 }}
              options={assemblies.map((a) => ({
                value: String(a.id),
                label: (
                  <span className="flex items-center gap-2">
                    <span>{a.name}</span>
                    {a.is_default ? (
                      <Tag className="m-0 text-[9px] uppercase">{t("home.defaultAssembly")}</Tag>
                    ) : null}
                  </span>
                ),
              }))}
            />
            </Flex>

            <Flex align="center" gap={8} className="shrink-0">
            <span className="whitespace-nowrap text-sm text-muted-foreground">
              {get("search.location.chromosome", t("search.location.chromosome"))}
            </span>
            <Select
              value={chromosome}
              onChange={(v) => setChromosome(v)}
              loading={chromosomesQuery.isLoading}
              data-testid="location-chromosome"
              size="large"
              style={{ width: 150 }}
              options={chromosomes.map((item) => ({ value: item.name, label: item.name }))}
              showSearch
            />
            </Flex>

            <Flex align="center" gap={8} className="shrink-0">
            <span className="whitespace-nowrap text-sm text-muted-foreground">
              {get("search.location.start", t("search.location.start"))}
            </span>
            <InputNumber
              value={start}
              onChange={setStart}
              min={1}
              size="large"
              style={{ width: 130 }}
              placeholder="1"
              data-testid="location-start"
              aria-label={get("search.location.start", t("search.location.start"))}
            />
            </Flex>

            <Flex align="center" gap={8} className="shrink-0">
            <span className="whitespace-nowrap text-sm text-muted-foreground">
              {get("search.location.end", t("search.location.end"))}
            </span>
            <InputNumber
              value={end}
              onChange={setEnd}
              min={1}
              size="large"
              style={{ width: 130 }}
              placeholder="2000"
              data-testid="location-end"
              aria-label={get("search.location.end", t("search.location.end"))}
            />
            </Flex>

            <Button
              type="primary"
              size="large"
              onClick={submit}
              data-testid="location-submit"
              icon={<SearchOutlined aria-hidden />}
              disabled={!formValid}
              loading={sitesQuery.isFetching}
            >
              {get("search.location.submit", t("search.location.submit"))}
            </Button>
          </Flex>
          <Typography.Text type="secondary" className="mt-2 block text-xs">
            {get("search.location.formatHint", t("search.location.formatHint"))}
          </Typography.Text>
          {assembliesQuery.isError || (urlAssembly && assemblies.length > 0 && !linkedAssembly) ? (
            <Alert
              className="mt-3"
              type="error"
              showIcon
              title={t(urlAssembly && !linkedAssembly && assemblies.length > 0 ? "search.assemblyUnavailable" : "home.assembliesUnavailable")}
            />
          ) : null}
          {chromosomesQuery.isError ? (
            <Alert
              className="mt-3"
              type="error"
              showIcon
              title={t("search.location.chromosomesUnavailable")}
            />
          ) : null}
        </div>

        {submitted ? (
          <div className="mt-6" role="region" aria-label={t("search.location.resultsAria")}>
            <p className="mb-3 text-sm text-muted-foreground">
              {t("search.location.found", { count: sites.length })}
            </p>
            {sitesQuery.isError ? (
              <Alert
                type="error"
                showIcon
                title={t("search.location.resultsUnavailable")}
                description={get("ui.errorRetry", t("search.location.resultsRetry"))}
              />
            ) : (
              <div
                className="-mx-4 overflow-x-auto sm:mx-0"
                data-testid="location-table"
                data-preview-sites={sites.length > 0 ? "true" : undefined}
              >
                <Table<TestDataPreviewMutationSite>
                  rowKey="source_site_key"
                  size="small"
                  bordered
                  columns={siteColumns}
                  dataSource={sites}
                  loading={sitesQuery.isLoading}
                  pagination={
                    sites.length > 25 ? { pageSize: 25, showSizeChanger: false } : false
                  }
                  scroll={{ x: "max-content" }}
                  locale={{
                    emptyText: (
                      <div data-testid="location-empty">
                        <Empty
                          description={
                            <Typography.Text type="secondary">
                              {get("ui.noResults", t("search.location.noResults"))}
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
