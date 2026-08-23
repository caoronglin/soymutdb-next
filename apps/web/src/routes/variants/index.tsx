/**
 * Variants index route — advanced filter + cursor-based pagination.
 *
 * AntD 5 migration (A1): DataTable → Table, FilterBar → inline Form,
 * PageHeader → Typography. TanStack Query data flow and URL search state
 * (chromosome / variant_type / impact / page / sort_by / sort_dir) unchanged.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
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
  type TableProps,
} from "@/lib/antd";
import { searchVariants, type VariantSummary } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES, formatPosition } from "../../lib/format";

export const Route = createFileRoute("/variants/")({
  component: VariantsComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    chromosome: String(search.chromosome ?? ""),
    variant_type: String(search.variant_type ?? ""),
    impact: String(search.impact ?? ""),
    cursor: search.cursor ? String(search.cursor) : undefined,
    sort_by: String(search.sort_by ?? "position"),
    sort_dir: (search.sort_dir as "asc" | "desc") ?? "asc",
  }),
});

const VARIANT_TYPES = ["SNP", "INS", "DEL", "MNV", "SV"];
const IMPACTS = ["HIGH", "MODERATE", "LOW", "MODIFIER"];
const PAGE_SIZE = 25;

interface SortState {
  sort_by: string;
  sort_dir: "asc" | "desc";
}

function VariantsComponent() {
  const { t } = useTranslation();
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

  const query = useQuery({
    queryKey: ["variants", search],
    queryFn: () =>
      searchVariants({
        chromosome: search.chromosome || undefined,
        variant_type: search.variant_type ? [search.variant_type] : undefined,
        impact: search.impact ? [search.impact] : undefined,
        cursor: search.cursor,
        limit: PAGE_SIZE,
        sort_by: search.sort_by,
        sort_dir: search.sort_dir,
      }),
    placeholderData: (prev) => prev,
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total_count ?? null;

  const currentSort: SortState = { sort_by: search.sort_by, sort_dir: search.sort_dir };

  const columns: TableColumnsType<VariantSummary> = [
    {
      title: "Variant ID",
      dataIndex: "variant_id",
      key: "variant_id",
      render: (_, row) => <span className="font-mono text-xs">{row.variant_id.slice(0, 12)}…</span>,
    },
    {
      title: t("variants.chromosomeLabel"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: t("variants.positionLabel"),
      dataIndex: "position",
      key: "position",
      sorter: true,
      sortOrder:
        currentSort.sort_by === "position"
          ? currentSort.sort_dir === "asc"
            ? "ascend"
            : "descend"
          : null,
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
      title: t("variants.variantTypeLabel"),
      dataIndex: "variant_type",
      key: "variant_type",
      render: (_, row) => (
        <Tag className="font-mono text-[10px]">{row.variant_type}</Tag>
      ),
    },
    {
      title: t("variants.impactLabel"),
      dataIndex: "impact",
      key: "impact",
      render: (_, row) =>
        row.impact ? <ImpactBadge impact={row.impact} /> : <span className="text-muted-foreground">—</span>,
    },
    {
      title: t("variants.geneSymbol"),
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

  const handleTableChange: TableProps<VariantSummary>["onChange"] = (
    _pagination,
    _filters,
    sorter,
  ) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const next: SortState | null =
      s && s.order
        ? { sort_by: String(s.field), sort_dir: s.order === "ascend" ? "asc" : "desc" }
        : null;
    // Pagination-triggered onChange reports the unchanged sort — ignore it.
    if (
      next
        ? next.sort_by === currentSort.sort_by && next.sort_dir === currentSort.sort_dir
        : currentSort.sort_by === "position" && currentSort.sort_dir === "asc"
    ) {
      return;
    }
    navigate({
      to: "/variants",
      search: next
        ? { ...search, ...next, cursor: undefined }
        : { ...search, sort_by: "position", sort_dir: "asc", cursor: undefined },
    });
  };

  const activeFilters = [search.chromosome, search.variant_type, search.impact].filter(Boolean).length;
  const reset = () =>
    navigate({
      to: "/variants",
      search: { chromosome: "", variant_type: "", impact: "", cursor: undefined, sort_by: "position", sort_dir: "asc" },
    });

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="eyebrow">{t("variants.title")}</p>
            <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
              {t("variants.subtitle")}
            </h1>
          </div>
          <Button icon={<Download className="size-4" aria-hidden />}>
            {t("variants.export")}
          </Button>
        </div>

        <Form layout="inline" className="mt-8 flex flex-wrap items-end gap-x-4 gap-y-4">
          <Form.Item label={t("variants.chromosome")} className="mb-0">
            <Select
              value={search.chromosome || "all"}
              onChange={(v) =>
                navigate({ to: "/variants", search: { ...search, chromosome: v === "all" ? "" : v, cursor: undefined } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: t("variants.allChromosomes") },
                ...SOYBEAN_CHROMOSOMES.map((c) => ({ value: c, label: c })),
              ]}
            />
          </Form.Item>
          <Form.Item label={t("variants.variantType")} className="mb-0">
            <Select
              value={search.variant_type || "all"}
              onChange={(v) =>
                navigate({ to: "/variants", search: { ...search, variant_type: v === "all" ? "" : v, cursor: undefined } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: t("variants.allTypes") },
                ...VARIANT_TYPES.map((v) => ({ value: v, label: v })),
              ]}
            />
          </Form.Item>
          <Form.Item label={t("variants.impact")} className="mb-0">
            <Select
              value={search.impact || "all"}
              onChange={(v) =>
                navigate({ to: "/variants", search: { ...search, impact: v === "all" ? "" : v, cursor: undefined } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: t("variants.allImpacts") },
                ...IMPACTS.map((i) => ({ value: i, label: i })),
              ]}
            />
          </Form.Item>
          <Form.Item className="mb-0">
            <Button icon={<ReloadOutlined />} onClick={reset} disabled={activeFilters === 0}>
              {t("common.clear")}
            </Button>
          </Form.Item>
        </Form>

        <div className="mt-4" role="region" aria-label="Variant search results">
          <Table<VariantSummary>
            rowKey="variant_id"
            columns={columns}
            dataSource={data}
            loading={query.isLoading}
            onChange={handleTableChange}
            pagination={false}
            locale={{
              emptyText: (
                <Empty
                  description={
                    <Typography.Text type="secondary">
                      {t("variants.noResults")}
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
