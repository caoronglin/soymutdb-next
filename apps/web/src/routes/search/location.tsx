/**
 * Physical location search — second-level catalog of the /search portal
 * (PPTX V2 slide 4). Form: genome version + chromosome + start–end interval.
 * Queries GET /variants/region (assembly name) and renders the portal table
 * layout: the gene ID acts as the row title (first column, linked to
 * /genes/{id} when present) followed by the five PPTX columns — genome
 * version / chromosome / mutation feature / Gbrowse / position.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  Button,
  Card,
  Empty,
  Form,
  InputNumber,
  Select,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  searchRegionVariants,
  getAssemblies,
  type VariantSummary,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES, formatNumber, compactGeneId } from "../../lib/format";

export const Route = createFileRoute("/search/location")({
  component: LocationSearchComponent,
});

const MAX_RESULTS = 1000;

interface RegionQuery {
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
}

function LocationSearchComponent() {
  const { t } = useTranslation();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  const [chromosome, setChromosome] = React.useState<string | undefined>(undefined);
  const [start, setStart] = React.useState<number | null>(null);
  const [end, setEnd] = React.useState<number | null>(null);
  const [submitted, setSubmitted] = React.useState<RegionQuery | null>(null);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];
  const selectedAssembly: AssemblyInfo | undefined = assemblies.find(
    (a) => String(a.id) === String(assemblyId),
  );

  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId]);

  const regionQuery = useQuery({
    queryKey: ["search-region-variants", submitted],
    queryFn: () =>
      searchRegionVariants({
        assembly: submitted!.assembly,
        chromosome: submitted!.chromosome,
        start: submitted!.start,
        end: submitted!.end,
        max_results: MAX_RESULTS,
      }),
    enabled: submitted != null,
    placeholderData: (prev) => prev,
  });

  const data = regionQuery.data ?? [];

  const onSubmit = () => {
    if (!selectedAssembly || !chromosome || start == null || end == null) return;
    if (start < 1 || end < start) return;
    setSubmitted({
      assembly: selectedAssembly.name,
      chromosome,
      start,
      end,
    });
  };

  const columns: TableColumnsType<VariantSummary> = [
    {
      // Gene ID as row title — linked to the gene detail page when present.
      title: t("search.location.colGeneId"),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) =>
        row.gene_id ? (
          <Link
            to="/genes/$geneId"
            params={{ geneId: row.gene_id }}
            aria-label={t("search.location.openGene", { geneId: row.gene_id })}
            className="link-underline font-mono text-sm font-medium text-primary"
          >
            {compactGeneId(row.gene_id, 18)}
          </Link>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: t("search.location.colAssembly"),
      dataIndex: "assembly",
      key: "assembly",
      render: () => (
        <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>
      ),
    },
    {
      title: t("search.location.colChromosome"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.chromosome}</span>
      ),
    },
    {
      title: t("search.location.colMutation"),
      dataIndex: "mutation",
      key: "mutation",
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.impact ?? row.variant_type ?? "—"}
        </span>
      ),
    },
    {
      title: t("search.location.colGbrowse"),
      dataIndex: "gbrowse",
      key: "gbrowse",
      render: (_, row) => (
        <Button
          size="small"
          disabled={!selectedAssembly}
          href={
            selectedAssembly
              ? `/browser?assembly=${encodeURIComponent(selectedAssembly.name)}&locus=${encodeURIComponent(
                  `${row.chromosome}:${row.position}-${row.position}`,
                )}`
              : undefined
          }
          target="_blank"
          rel="noreferrer"
        >
          {t("search.location.openBrowser")}
        </Button>
      ),
    },
    {
      title: t("search.location.colPosition"),
      dataIndex: "position",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.chromosome}:{formatNumber(row.position)}
        </span>
      ),
    },
  ];

  const formValid =
    Boolean(selectedAssembly) &&
    Boolean(chromosome) &&
    start != null &&
    end != null &&
    start >= 1 &&
    end >= start;

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.location.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.location.subtitle")}
        </h2>

        <Card className="mt-6 max-w-3xl">
          <Form layout="vertical" onFinish={onSubmit}>
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <Form.Item label={t("search.location.assembly")} className="mb-0">
                <Select
                  value={assemblyId}
                  onChange={(v) => setAssemblyId(v)}
                  placeholder={t("search.location.assemblyPlaceholder")}
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
              <div className="grid gap-4 sm:grid-cols-[1fr_120px_120px]">
                <Form.Item label={t("search.location.chromosome")} className="mb-0">
                  <Select
                    value={chromosome}
                    onChange={(v) => setChromosome(v)}
                    options={SOYBEAN_CHROMOSOMES.map((c) => ({
                      value: c,
                      label: c,
                    }))}
                    showSearch
                  />
                </Form.Item>
                <Form.Item label={t("search.location.start")} className="mb-0">
                  <InputNumber
                    value={start}
                    onChange={setStart}
                    min={1}
                    className="w-full"
                    placeholder="1"
                    aria-label={t("search.location.start")}
                  />
                </Form.Item>
                <Form.Item label={t("search.location.end")} className="mb-0">
                  <InputNumber
                    value={end}
                    onChange={setEnd}
                    min={1}
                    className="w-full"
                    placeholder="2000"
                    aria-label={t("search.location.end")}
                  />
                </Form.Item>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button
                type="primary"
                htmlType="submit"
                icon={<SearchOutlined aria-hidden />}
                disabled={!formValid}
                loading={regionQuery.isFetching}
              >
                {t("search.location.submit")}
              </Button>
              <Typography.Text type="secondary" className="text-xs">
                {t("search.location.formatHint")}
              </Typography.Text>
            </div>
          </Form>
        </Card>

        {submitted ? (
          <div className="mt-6" role="region" aria-label="Region search results">
            <p className="mb-3 text-sm text-muted-foreground">
              {t("search.location.found", { count: data.length })}
            </p>
            <Table<VariantSummary>
              rowKey="variant_id"
              columns={columns}
              dataSource={data}
              loading={regionQuery.isLoading}
              pagination={
                data.length > 25
                  ? { pageSize: 25, showSizeChanger: false }
                  : false
              }
              locale={{
                emptyText: (
                  <Empty
                    description={
                      <Typography.Text type="secondary">
                        {t("search.location.noResults")}
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
