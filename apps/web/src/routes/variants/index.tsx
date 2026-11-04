import { assembliesQueryOptions } from "../../lib/query-options";
/**
 * Variants index route — advanced filter + cursor-based pagination.
 *
 * AntD 5 migration (A1): DataTable → Table, FilterBar → inline Form,
 * PageHeader → Typography. TanStack Query data flow and URL search state
 * (chromosome / variant_type / impact / page) unchanged.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../../lib/site-content-react";
import {
  CheckOutlined,
  CopyOutlined,
  LeftOutlined,
  ReloadOutlined,
  RightOutlined,
} from "@ant-design/icons";
import {
  Button,
  Empty,
  Form,
  Result,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  searchVariants,
  type VariantImpact,
  type VariantSummary,
  type VariantType,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { VariantExportControls } from "../../components/variant-export-controls";
import { SOYBEAN_CHROMOSOMES, formatPosition } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assemblyOptionLabel, resolveAssemblyParam } from "../../lib/assembly-selection";
import { useReleaseId } from "../../lib/release-scope";

const VARIANT_TYPES = ["SNP", "INS", "DEL", "MNV", "SV"] as const satisfies readonly VariantType[];
const IMPACTS = ["HIGH", "MODERATE", "LOW", "MODIFIER"] as const satisfies readonly VariantImpact[];

export const Route = createFileRoute("/variants/")({
  component: VariantsComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: String(search.assembly ?? ""),
    chromosome: String(search.chromosome ?? ""),
    variant_type: VARIANT_TYPES.includes(search.variant_type as VariantType)
      ? (search.variant_type as VariantType)
      : ("" as const),
    impact: IMPACTS.includes(search.impact as VariantImpact)
      ? (search.impact as VariantImpact)
      : ("" as const),
    mutant_line_public_id:
      typeof search.mutant_line_public_id === "string" ? search.mutant_line_public_id : "",
    cursor: search.cursor ? String(search.cursor) : undefined,
  }),
});

const PAGE_SIZE = 25;

function VariantsComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const search = Route.useSearch();
  const navigate = useNavigate();

  // Cursor-history stack for page-like prev/next navigation. `undefined`
  // represents the first page (no cursor). Pushed on "Next", popped on
  // "Previous". Reset whenever a filter/sort changes the underlying query.
  const [cursorStack, setCursorStack] = React.useState<Array<string | undefined>>([
    undefined,
  ]);
  const prevCursor = cursorStack.length > 1 ? cursorStack[cursorStack.length - 2] : undefined;
  const atFirstPage = search.cursor == null;
  // The release is read reactively: a plain module read captured a snapshot
  // that no release switch could invalidate, so the page would keep its
  // query key bound to a release the tab no longer follows.
  const releaseId = useReleaseId();
  const assembliesQuery = useQuery(assembliesQueryOptions({
    releaseId,
    siteVariant: SITE_VARIANT,
  }));
  const assemblies = assembliesQuery.data ?? [];
  const defaultAssembly = assemblies.find((assembly) => assembly.is_default);
  const assemblyResolution = search.assembly
    ? resolveAssemblyParam(assemblies, search.assembly)
    : defaultAssembly
      ? { status: "resolved" as const, assembly: defaultAssembly, via: "id" as const }
      : { status: "absent" as const };
  const selectedAssembly = assemblyResolution.status === "resolved" ? assemblyResolution.assembly : undefined;
  const assemblyName = selectedAssembly?.name ?? "";
  const filterSignature = [
    search.assembly,
    search.chromosome,
    search.variant_type,
    search.impact,
    search.mutant_line_public_id,
    releaseId,
    SITE_VARIANT,
  ].join("|");
  const previousFilterSignature = React.useRef(filterSignature);
  React.useEffect(() => {
    if (previousFilterSignature.current !== filterSignature) {
      setCursorStack([undefined]);
      previousFilterSignature.current = filterSignature;
    }
  }, [filterSignature]);

  const query = useQuery({
    queryKey: queryKeys.variants.list({
      assemblyId: selectedAssembly ? String(selectedAssembly.id) : null,
      releaseId,
      siteVariant: SITE_VARIANT,
      page: cursorStack.length - 1,
      cursor: search.cursor,
      chromosome: search.chromosome || null,
      impact: search.impact || null,
      variantType: search.variant_type || null,
      mutantLinePublicId: search.mutant_line_public_id || null,
    }),
    queryFn: () =>
      searchVariants({
        assembly: assemblyName || undefined,
        chromosome: search.chromosome || undefined,
        variant_type: search.variant_type ? search.variant_type : undefined,
        impact: search.impact ? search.impact : undefined,
        mutant_line_public_id: search.mutant_line_public_id || undefined,
        cursor: search.cursor,
        limit: PAGE_SIZE,
      }),
    enabled: Boolean(selectedAssembly),
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total_count ?? null;
  const columns: TableColumnsType<VariantSummary> = [
    {
      title: get("variants.variantId", t("variants.variantId")),
      dataIndex: "variant_id",
      key: "variant_id",
      // The full identifier is the row's public identity: an A/B consensus id
      // is 20+ characters and a truncated one can no longer be searched,
      // copied or pasted anywhere. It wraps instead of being cut.
      render: (_, row) => (
        <span className="inline-flex items-start gap-1">
          <span className="font-mono text-xs break-all" data-testid="variant-id">
            {row.variant_id}
          </span>
          <CopyIdentifier value={row.variant_id} />
        </span>
      ),
    },
    {
      // The assembly the row was read from. The page queries one assembly at
      // a time, but the row states its own namespace — the label comes from
      // the row, never from an assumed page scope.
      title: get("variants.assembly", t("variants.assembly")),
      dataIndex: "assembly",
      key: "assembly",
      render: (_, row) =>
        row.assembly ? (
          <span className="font-mono text-xs break-all" data-testid="variant-assembly">
            {row.assembly}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: get("variants.chromosomeLabel", t("variants.chromosomeLabel")),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: get("variants.positionLabel", t("variants.positionLabel")),
      dataIndex: "position",
      key: "position",
      align: "right",
      render: (_, row) => <span className="font-mono text-xs">{formatPosition(row.position)}</span>,
    },
    {
      title: "Ref→Alt",
      dataIndex: "ref_allele",
      key: "ref_alt",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.ref_allele}→{row.alt_allele}</span>
      ),
    },
    {
      title: get("variants.variantTypeLabel", t("variants.variantTypeLabel")),
      dataIndex: "variant_type",
      key: "variant_type",
      render: (_, row) => (
        <Tag className="font-mono text-[10px]">{row.variant_type}</Tag>
      ),
    },
    {
      title: get("variants.impactLabel", t("variants.impactLabel")),
      dataIndex: "impact",
      key: "impact",
      render: (_, row) =>
        row.impact ? <ImpactBadge impact={row.impact} /> : <span className="text-muted-foreground">—</span>,
    },
    {
      title: get("variants.geneSymbol", t("variants.geneSymbol")),
      dataIndex: "gene_symbol",
      key: "gene_symbol",
      render: (_, row) =>
        row.gene_symbol ? (
          <span className="font-mono text-xs">{row.gene_symbol}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];


  const activeFilters = [search.assembly, search.chromosome, search.variant_type, search.impact, search.mutant_line_public_id].filter(Boolean).length;
  const reset = () =>
    navigate({
      to: "/variants",
      search: { assembly: search.assembly, chromosome: "", variant_type: "", impact: "", mutant_line_public_id: "", cursor: undefined },
    });

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow">{get("variants.title", t("variants.title"))}</p>
            <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
              {get("variants.subtitle", t("variants.subtitle"))}
            </h1>
          </div>
          <VariantExportControls
            assemblyKey={assemblyName}
            filters={{
              chromosome: search.chromosome || undefined,
              impact: search.impact || undefined,
              variant_type: search.variant_type || undefined,
              mutant_line_public_id: search.mutant_line_public_id || undefined,
            }}
            submitLabel={get("variants.export", t("variants.export"))}
          />
        </div>
        <Form layout="inline" className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-4">
          <Form.Item
            label={get("variants.assembly", t("search.genes.assembly"))}
            htmlFor="variant-assembly"
            className="mb-0"
          >
            <Select
              id="variant-assembly"
              value={selectedAssembly ? String(selectedAssembly.id) : undefined}
              onChange={(value) =>
                navigate({ to: "/variants", search: { ...search, assembly: value, cursor: undefined } })
              }
              loading={assembliesQuery.isLoading}
              disabled={assembliesQuery.isError}
              placeholder={t("search.genes.assemblyPlaceholder")}
              style={{ width: 190 }}
              options={assemblies.map((assembly) => ({
                value: String(assembly.id),
                label: assemblyOptionLabel(assembly),
              }))}
            />
          </Form.Item>
          <Form.Item
            label={get("variants.chromosome", t("variants.chromosome"))}
            htmlFor="variant-chromosome"
            className="mb-0"
          >
            <Select
              id="variant-chromosome"
              value={search.chromosome || "all"}
              onChange={(v) =>
                navigate({ to: "/variants", search: { ...search, chromosome: v === "all" ? "" : v, cursor: undefined } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: get("variants.allChromosomes", t("variants.allChromosomes")) },
                ...SOYBEAN_CHROMOSOMES.map((c) => ({ value: c, label: c })),
              ]}
            />
          </Form.Item>
          <Form.Item
            label={get("variants.variantType", t("variants.variantType"))}
            htmlFor="variant-type"
            className="mb-0"
          >
            <Select<"all" | VariantType>
              id="variant-type"
              value={search.variant_type || "all"}
              onChange={(v) =>
                navigate({
                  to: "/variants",
                  search: {
                    ...search,
                    variant_type: v === "all" ? ("" as const) : (v as VariantType),
                    cursor: undefined,
                  },
                })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: get("variants.allTypes", t("variants.allTypes")) },
                ...VARIANT_TYPES.map((v) => ({ value: v, label: v })),
              ]}
            />
          </Form.Item>
          <Form.Item
            label={get("variants.impact", t("variants.impact"))}
            htmlFor="variant-impact"
            className="mb-0"
          >
            <Select<"all" | VariantImpact>
              id="variant-impact"
              value={search.impact || "all"}
              onChange={(v) =>
                navigate({
                  to: "/variants",
                  search: {
                    ...search,
                    impact: v === "all" ? ("" as const) : (v as VariantImpact),
                    cursor: undefined,
                  },
                })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: get("variants.allImpacts", t("variants.allImpacts")) },
                ...IMPACTS.map((i) => ({ value: i, label: i })),
              ]}
            />
          </Form.Item>
          {search.mutant_line_public_id ? (
            <Form.Item className="mb-0">
              <Tag
                closable
                onClose={() => navigate({ to: "/variants", search: { ...search, mutant_line_public_id: "", cursor: undefined } })}
              >
                {t("mutants.detail.variantFilter", { id: search.mutant_line_public_id })}
              </Tag>
            </Form.Item>
          ) : null}
          <Form.Item className="mb-0">
            <Button icon={<ReloadOutlined />} onClick={reset} disabled={activeFilters === 0}>
              {t("common.clear")}
            </Button>
          </Form.Item>
        </Form>

        {assemblyResolution.status === "unknown" || assemblyResolution.status === "ambiguous" ? (
          <Empty
            className="mt-6"
            data-testid="variants-unknown-assembly"
            description={
              assemblyResolution.status === "ambiguous"
                ? t("search.ambiguousAssembly", { matches: assemblyResolution.matches.map(assemblyOptionLabel).join(", ") })
                : t("search.assemblyUnavailable")
            }
          />
        ) : null}

        <div className="mt-4" role="region" aria-label={t("variants.resultsAria")}>
          {query.isError ? (
            <div role="alert">
              <Result
                status="error"
                title={t("variants.loadError")}
                extra={
                  <Button loading={query.isFetching} onClick={() => void query.refetch()}>
                    {t("common.retry")}
                  </Button>
                }
              />
            </div>
          ) : (
            <>
              {releaseId ? (
                <Typography.Text
                  type="secondary"
                  className="mb-2 block text-xs"
                  data-testid="variant-release-scope"
                >
                  {`${t("search.releaseLabel")}: ${releaseId}`}
                </Typography.Text>
              ) : null}
              <Table<VariantSummary>
                // `variant_id` is release-scoped, not canonical: the same
                // number can name another record in another release, and the
                // identifier column already prints it. Keying on it alone would
                // let a cross-release or cross-assembly page collide and have
                // React silently reuse a row. This is row stability for this
                // page only; canonical identity is a separate, larger job.
                //
                // The assembly is a serialized part rather than a separator:
                // `assembly` is nullable, and `""` is a distinct value from
                // absent. A `?? ""` fallback folds both into one key, and since
                // keys are strings, `["a","b"]` joined by ":" could spell a
                // neighbour's key. `JSON.stringify` keeps `null` and `""` apart.
                rowKey={(row) => JSON.stringify([row.variant_id, row.assembly ?? null])}
                onRow={() =>
                  ({ "data-testid": "variant-row" }) as React.HTMLAttributes<HTMLElement>
                }
                columns={columns}
                dataSource={data}
                loading={query.isLoading}
                pagination={false}
                // A wide result table must stay readable on a phone: the table
                // takes its natural width and the region scrolls sideways
                // instead of squeezing the identifier column into an
                // unreadable stub.
                scroll={{ x: "max-content" }}
                locale={{
                  emptyText: (
                    <Empty
                      description={
                        <Typography.Text type="secondary">
                          {get("variants.noResults", t("variants.noResults"))}
                          <br />
                          <span className="text-xs">{t("common.noResults")}</span>
                        </Typography.Text>
                      }
                    />
                  ),
                }}
              />
              <nav aria-label={t("common.pagination")}>
                <Space className="mt-3" size="small">
                  <Button
                    size="small"
                    icon={<LeftOutlined />}
                    disabled={atFirstPage}
                    onClick={() => {
                      navigate({ to: "/variants", search: { ...search, cursor: prevCursor } });
                      setCursorStack((stack) => (stack.length > 1 ? stack.slice(0, -1) : stack));
                    }}
                  >
                    {t("common.previous")}
                  </Button>
                  <Button
                    size="small"
                    icon={<RightOutlined />}
                    iconPlacement="end"
                    disabled={!query.data?.has_more || !query.data?.next_cursor}
                    onClick={() => {
                      const next = query.data?.next_cursor;
                      if (!next) return;
                      setCursorStack((stack) => [...stack, next]);
                      navigate({ to: "/variants", search: { ...search, cursor: next } });
                    }}
                  >
                    {t("common.next")}
                  </Button>
                  {total != null ? (
                    <Typography.Text type="secondary" className="text-xs">
                      {t("variants.totalCount", { count: total })}
                    </Typography.Text>
                  ) : null}
                </Space>
              </nav>
            </>
          )}
        </div>
      </div>
    </FadeUp>
  );
}

/**
 * Copy an identifier to the clipboard.
 *
 * The identifier is long and wraps inside its cell, so selecting it by hand
 * is error-prone. A denied clipboard is not an error the user has to solve:
 * the value stays visible and selectable as plain text.
 */
function CopyIdentifier({ value }: { value: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = React.useState(false);
  React.useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);
  const copy = async () => {
    try {
      if (!navigator.clipboard) return;
      await navigator.clipboard.writeText(value);
      setCopied(true);
    } catch {
      // Clipboard access denied: the identifier stays selectable as text.
    }
  };
  return (
    <button
      type="button"
      className="shrink-0 text-muted-foreground hover:text-foreground"
      aria-label={copied ? `${t("common.copied")} ${value}` : `${t("common.copy")} ${value}`}
      onClick={() => void copy()}
    >
      {copied ? <CheckOutlined aria-hidden /> : <CopyOutlined aria-hidden />}
    </button>
  );
}

function ImpactBadge({ impact }: { impact: string }) {
  const tone = impact === "HIGH" ? "high" : impact === "MODERATE" ? "moderate" : impact === "LOW" ? "low" : "modifier";
  const color = `var(--impact-${tone})`;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      <span className="font-mono">{impact}</span>
    </span>
  );
}
