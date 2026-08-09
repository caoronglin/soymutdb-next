/**
 * Gene ID search — second-level catalog of the /search portal (PPTX V2
 * slide 2/3). Form: genome version select (GET /genes/assemblies, default =
 * is_default) + multi-line gene ID input. Results use the portal table
 * layout: the gene ID acts as the row title (first column, linked to
 * /genes/{id}) followed by the five PPTX columns — genome version /
 * chromosome / mutation feature / Gbrowse / position.
 *
 * A `?q=` search param (e.g. from the BLAST result "gene search" cross
 * link) pre-fills the input and submits automatically once the assembly
 * is known.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Button, Card, Empty, Form, Input, Select, Table, Tag, Typography, type TableColumnsType } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  searchGenes,
  getAssemblies,
  type GeneSummary,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { compactGeneId, formatNumber } from "../../lib/format";

export const Route = createFileRoute("/search/genes")({
  component: GeneIdSearchComponent,
});

const PAGE_SIZE = 20;

interface Submitted {
  q: string;
  assemblyId: string;
}

function GeneIdSearchComponent() {
  const { t } = useTranslation();
  const { q: urlQ } = Route.useSearch();
  const [geneIdsRaw, setGeneIdsRaw] = React.useState(urlQ ?? "");
  const [submitted, setSubmitted] = React.useState<Submitted | null>(null);
  const [page, setPage] = React.useState(1);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];

  // Preselect the default assembly (is_default) — fallback to the first.
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  const selectedAssembly: AssemblyInfo | undefined = assemblies.find(
    (a) => String(a.id) === String(assemblyId),
  );
  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId]);

  // Deep link: `?q=` (BLAST cross-link) pre-fills the input and submits once
  // the assembly is loaded. Only the initial URL value triggers this.
  const autoSubmittedRef = React.useRef(false);
  React.useEffect(() => {
    if (autoSubmittedRef.current) return;
    const trimmed = urlQ?.trim();
    if (!trimmed || !assemblyId) return;
    autoSubmittedRef.current = true;
    setGeneIdsRaw(trimmed);
    setSubmitted({ q: trimmed, assemblyId });
    setPage(1);
  }, [urlQ, assemblyId]);

  const resultsQuery = useQuery({
    queryKey: ["search-genes", submitted, page],
    queryFn: () =>
      searchGenes({
        q: submitted?.q || undefined,
        assembly_id: submitted?.assemblyId || undefined,
        page,
        page_size: PAGE_SIZE,
      }),
    enabled: submitted != null,
    placeholderData: (prev) => prev,
  });

  const data = resultsQuery.data?.items ?? [];
  const total = resultsQuery.data?.total ?? 0;

  const onSubmit = () => {
    const q = geneIdsRaw.trim();
    if (!q || !assemblyId) return;
    setSubmitted({ q, assemblyId });
    setPage(1);
  };

  const columns: TableColumnsType<GeneSummary> = [
    {
      // Gene ID as row title — linked to the gene detail page (PPTX).
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
      title: t("search.genes.colAssembly"),
      dataIndex: "assembly",
      key: "assembly",
      render: () => (
        <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>
      ),
    },
    {
      title: t("search.genes.colChromosome"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.chromosome}</span>
      ),
    },
    {
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
      title: t("search.genes.colGbrowse"),
      dataIndex: "gbrowse",
      key: "gbrowse",
      render: (_, row) => (
        <Button
          size="small"
          disabled={!selectedAssembly}
          href={
            selectedAssembly
              ? `/browser?assembly=${encodeURIComponent(selectedAssembly.name)}&locus=${encodeURIComponent(
                  `${row.chromosome}:${row.start_pos}-${row.end_pos}`,
                )}`
              : undefined
          }
          target="_blank"
          rel="noreferrer"
        >
          {t("search.genes.openBrowser")}
        </Button>
      ),
    },
    {
      title: t("search.genes.colPosition"),
      dataIndex: "position",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.chromosome}:{formatNumber(row.start_pos)}-{formatNumber(row.end_pos)}
        </span>
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
          <Form layout="vertical" onFinish={onSubmit}>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <Form.Item label={t("search.genes.assembly")} className="mb-0">
                <Select
                  value={assemblyId}
                  onChange={(v) => setAssemblyId(v)}
                  placeholder={t("search.genes.assemblyPlaceholder")}
                  loading={assembliesQuery.isLoading}
                  options={assemblies.map((a) => ({
                    value: String(a.id),
                    label: (
                      <span className="flex items-center gap-2">
                        <span>{a.name}</span>
                        {a.is_default ? (
                          <Tag className="m-0 text-[9px] uppercase">Default</Tag>
                        ) : null}
                      </span>
                    ),
                  }))}
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
        ) : null}
      </div>
    </FadeUp>
  );
}
