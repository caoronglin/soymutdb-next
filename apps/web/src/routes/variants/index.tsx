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
import { DownloadOutlined as Download, LeftOutlined, ReloadOutlined, RightOutlined } from "@ant-design/icons";
import {
  Button,
  Empty,
  Form,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  createVariantExport,
  getAssemblies,
  getReleaseId,
  searchVariants,
  type VariantImpact,
  type VariantSummary,
  type VariantType,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES, formatPosition } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assemblyOptionLabel, resolveAssemblyParam } from "../../lib/assembly-selection";

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
  const assembliesQuery = useQuery({
    queryKey: ["assemblies", getReleaseId(), SITE_VARIANT],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];
  const defaultAssembly = assemblies.find((assembly) => assembly.is_default);
  const assemblyResolution = search.assembly
    ? resolveAssemblyParam(assemblies, search.assembly)
    : defaultAssembly
      ? { status: "resolved" as const, assembly: defaultAssembly, via: "id" as const }
      : { status: "absent" as const };
  const selectedAssembly = assemblyResolution.status === "resolved" ? assemblyResolution.assembly : undefined;
  const assemblyName = selectedAssembly?.name ?? "";
  const releaseId = getReleaseId();
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
  const [exportState, setExportState] = React.useState<
    { status: "idle" } | { status: "loading" } | { status: "success"; message: string } | { status: "error"; message: string }
  >({ status: "idle" });

  const requestExport = async () => {
    if (!selectedAssembly) return;
    setExportState({ status: "loading" });
    try {
      const response = (await createVariantExport({
        format: "tsv",
        compress: true,
        filters: {
          assembly: assemblyName,
          chromosome: search.chromosome || undefined,
          impact: search.impact || undefined,
          variant_type: search.variant_type || undefined,
          mutant_line_public_id: search.mutant_line_public_id || undefined,
          limit: 200,
        },
      })) as { message?: string; status?: string; export_id?: string };
      setExportState({
        status: "success",
        message: response.message ?? (response.export_id ? `Export ${response.export_id} submitted` : "Export submitted"),
      });
    } catch (error) {
      setExportState({ status: "error", message: error instanceof Error ? error.message : "Export request failed" });
    }
  };

  const columns: TableColumnsType<VariantSummary> = [
    {
      title: get("variants.variantId", "Variant ID"),
      dataIndex: "variant_id",
      key: "variant_id",
      render: (_, row) => <span className="font-mono text-xs">{row.variant_id.slice(0, 12)}…</span>,
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
          <Button
            icon={<Download className="size-4" aria-hidden />}
            onClick={() => void requestExport()}
            loading={exportState.status === "loading"}
            disabled={!selectedAssembly || assemblyResolution.status !== "resolved"}
          >
            {get("variants.export", t("variants.export"))}
          </Button>
        </div>
        {exportState.status === "success" || exportState.status === "error" ? (
          <Typography.Paragraph
            className="mt-3"
            type={exportState.status === "error" ? "danger" : "secondary"}
            data-testid="variant-export-status"
          >
            {exportState.message}
          </Typography.Paragraph>
        ) : null}

        <Form layout="inline" className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-4">
          <Form.Item label={get("variants.assembly", t("search.genes.assembly"))} className="mb-0">
            <Select
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
          <Form.Item label={get("variants.chromosome", t("variants.chromosome"))} className="mb-0">
            <Select
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
          <Form.Item label={get("variants.variantType", t("variants.variantType"))} className="mb-0">
            <Select<"all" | VariantType>
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
          <Form.Item label={get("variants.impact", t("variants.impact"))} className="mb-0">
            <Select<"all" | VariantImpact>
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
                ? `Assembly name matches several versions: ${assemblyResolution.matches.map(assemblyOptionLabel).join(", ")}. Select a version.`
                : "The requested assembly is unavailable; no variant query was sent."
            }
          />
        ) : null}

        <div className="mt-4" role="region" aria-label="Variant search results">
          <Table<VariantSummary>
            rowKey="variant_id"
            columns={columns}
            dataSource={data}
            loading={query.isLoading}
            pagination={false}
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
              iconPosition="end"
              disabled={!query.data?.has_more || !query.data?.next_cursor}
              onClick={() => {
                const next = query.data?.next_cursor;
                if (!next) return;
                setCursorStack((stack) => [...stack, search.cursor]);
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
        </div>
      </div>
    </FadeUp>
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
