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
import * as React from "react";
import { Button, Card, Empty, Form, Input, Select, Table, Tag, Typography, type TableColumnsType } from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  searchGenes,
  getAssemblies,
  type GeneSummary,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { compactGeneId, formatNumber } from "../../lib/format";
import { buildJbrowseLocusUrl } from "../../lib/deployment";

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

interface Submitted {
  q: string;
  assemblyId: string;
}

function GeneIdSearchComponent() {
  const { t } = useTranslation();
  const router = useRouter();
  const { q: urlQ, assembly: urlAssembly, run } = Route.useSearch();
  // This route intentionally consumes its URL once. Capturing the initial
  // values keeps later form edits from re-running a shared deep link.
  const [initialSearch] = React.useState(() => ({
    q: urlQ,
    assembly: urlAssembly,
    run,
  }));
  const initialQuery = initialSearch.q?.trim();
  const [geneIdsRaw, setGeneIdsRaw] = React.useState(
    () => (initialSearch.run || initialSearch.assembly ? initialQuery ?? "" : initialSearch.q ?? ""),
  );
  const [page, setPage] = React.useState(1);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data;

  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  // Preselect the URL assembly when present; otherwise use the configured
  // default (or first) assembly. These are derived values, not state that
  // needs a follow-up effect after the assemblies request resolves.
  const defaultAssembly = assemblies?.find((assembly) => assembly.is_default) ?? assemblies?.[0];
  const defaultAssemblyId = defaultAssembly ? String(defaultAssembly.id) : undefined;
  const linkedAssembly = initialSearch.assembly
    ? assemblies?.find(
        (assembly) =>
          String(assembly.id) === initialSearch.assembly || assembly.name === initialSearch.assembly,
      )
    : undefined;
  const linkedAssemblyId = linkedAssembly ? String(linkedAssembly.id) : undefined;
  const initialAssemblyId = linkedAssemblyId ?? defaultAssemblyId;
  const formAssemblyId = assemblyId ?? initialAssemblyId;

  // Deep links run at most once from their initial URL values. The submitted
  // context remains separate from the editable form selection so result
  // labels and JBrowse links remain aligned with the original request.
  const submitted: Submitted | null =
    initialQuery &&
    (initialSearch.run === true || initialSearch.assembly != null) &&
    initialAssemblyId !== undefined
      ? {
          q: initialQuery,
          assemblyId: initialAssemblyId,
        }
      : null;
  // Once a search is submitted, its assembly is the result context. This
  // keeps the request, result label, and JBrowse deep link aligned even if
  // the form state changes later.
  const resolvedAssemblyId = submitted?.assemblyId ?? formAssemblyId;
  const selectedAssembly: AssemblyInfo | undefined = assemblies?.find(
    (a) => String(a.id) === String(resolvedAssemblyId),
  );

  const resultsQuery = useQuery({
    queryKey: ["search-genes", submitted?.q, submitted?.assemblyId, page],
    queryFn: () =>
      searchGenes({
        q: submitted?.q || undefined,
        assembly_id: submitted?.assemblyId || undefined,
        page,
        page_size: PAGE_SIZE,
      } as Parameters<typeof searchGenes>[0]),
    enabled: submitted != null,
    placeholderData: (prev) => prev,
  });

  const data = resultsQuery.data?.items ?? [];
  const total = resultsQuery.data?.total ?? 0;

  const submitInNewTab = () => {
    const q = geneIdsRaw.trim();
    if (!q || !formAssemblyId) return;
    const location = router.buildLocation({
      to: "/search/genes",
      search: { q, assembly: formAssemblyId, run: true },
    });
    window.open(location.href, "_blank", "noopener");
  };


  const columns: TableColumnsType<GeneSummary> = [
    {
      // 1. Genome assembly
      title: t("search.genes.colAssembly"),
      dataIndex: "assembly",
      key: "assembly",
      render: () => (
        <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>
      ),
    },
    {
      // 2. Chromosome
      title: t("search.genes.colChromosome"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      // 3. Position
      title: t("search.genes.colPosition"),
      dataIndex: "position",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.chromosome}:{formatNumber(row.start_pos)}-{formatNumber(row.end_pos)}
        </span>
      ),
    },
    {
      // 4. Mutation feature
      title: t("search.genes.colMutation"),
      dataIndex: "variant_count",
      key: "mutation",
      render: (_, row) =>
        row.variant_count != null ? (
          <span className="font-mono text-xs">
            {t("search.genes.mutations", { count: row.variant_count })}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      // 5. Gene ID (linked to detail)
      title: t("search.genes.colGeneId"),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          aria-label={t("search.genes.openGene", { geneId: row.gene_id })}
          className="link-underline font-mono text-sm font-medium text-primary"
        >
          {compactGeneId(row.gene_id, 18)}
        </Link>
      ),
    },
    {
      // 6. JBrowse 2 action (base-aware, new tab)
      title: t("search.genes.colGbrowse"),
      dataIndex: "jbrowse",
      key: "jbrowse",
      render: (_, row) => (
        <Button
          size="small"
          disabled={!selectedAssembly}
          href={
            selectedAssembly
              ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
                  assembly: selectedAssembly.name,
                  locus: `${row.chromosome}:${row.start_pos}-${row.end_pos}`,
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

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.genes.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.genes.subtitle")}
        </h2>

        <Card className="mt-6 max-w-3xl">
          <Form layout="vertical" onFinish={submitInNewTab}>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <Form.Item label={t("search.genes.assembly")} className="mb-0">
                <Select
                  value={formAssemblyId}
                  onChange={(v) => setAssemblyId(v)}
                  placeholder={t("search.genes.assemblyPlaceholder")}
                  loading={assembliesQuery.isLoading}
                  options={assemblies?.map((a) => ({
                    value: String(a.id),
                    label: (
                      <span className="flex items-center gap-2">
                        <span>{a.name}</span>
                        {a.is_default ? (
                          <Tag className="m-0 text-[9px] uppercase">Default</Tag>
                        ) : null}
                      </span>
                    ),
                  })) ?? []}
                />
              </Form.Item>
              <Form.Item label={t("search.genes.geneId")} className="mb-0">
                <Input.TextArea
                  rows={2}
                  value={geneIdsRaw}
                  onChange={(e) => setGeneIdsRaw(e.target.value)}
                  placeholder={t("search.genes.geneIdPlaceholder")}
                  className="font-mono text-sm"
                  aria-label={t("search.genes.geneId")}
                />
              </Form.Item>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button
                type="primary"
                htmlType="submit"
                icon={<SearchOutlined aria-hidden />}
                loading={resultsQuery.isFetching}
              >
                {t("search.genes.submit")}
              </Button>
              <Typography.Text type="secondary" className="text-xs">
                {t("search.genes.geneIdHint")}
              </Typography.Text>
            </div>
          </Form>
        </Card>

        {submitted ? (
          <div className="mt-6" role="region" aria-label="Gene ID search results">
            <p className="mb-3 text-sm text-muted-foreground">
              {t("search.genes.resultsFor")}{" "}
              <span className="font-mono text-foreground">"{submitted.q}"</span>
              {" · "}
              {formatNumber(total)}
            </p>
            <div className="-mx-4 overflow-x-auto sm:mx-0">
              <Table<GeneSummary>
                rowKey="gene_id"
                columns={columns}
                dataSource={data}
                loading={resultsQuery.isLoading}
                pagination={{
                  current: page,
                  pageSize: PAGE_SIZE,
                  total,
                  showSizeChanger: false,
                  showTotal: (n, range) =>
                    `${formatNumber(range[0])}–${formatNumber(range[1])} of ${formatNumber(n)}`,
                  onChange: (p) => setPage(p),
                }}
                scroll={{ x: 720 }}
                locale={{
                  emptyText: (
                    <Empty
                      description={
                        <Typography.Text type="secondary">
                          {t("search.genes.noResults")}
                        </Typography.Text>
                      }
                    />
                  ),
                }}
              />
            </div>
          </div>
        ) : null}
      </div>
    </FadeUp>
  );
}
