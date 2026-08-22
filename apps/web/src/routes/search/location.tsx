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
} from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  searchRegionVariants,
  getAssemblies,
  getAssemblyChromosomes,
  type VariantSummary,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { formatNumber, compactGeneId } from "../../lib/format";
import { buildJbrowseLocusUrl } from "../../lib/deployment";

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

const MAX_RESULTS = 1000;

interface RegionQuery {
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
}

function LocationSearchComponent() {
  const { t } = useTranslation();
  const router = useRouter();
  const { assembly: urlAssembly, chromosome: urlChromosome, start: urlStart, end: urlEnd, run } =
    Route.useSearch();
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

  const chromosomesQuery = useQuery({
    queryKey: ["assembly-chromosomes", assemblyId],
    queryFn: () => getAssemblyChromosomes(assemblyId!),
    enabled: Boolean(assemblyId),
    staleTime: 30 * 60 * 1000,
  });
  const chromosomes = chromosomesQuery.data ?? [];

  React.useEffect(() => {
    if (chromosome && !chromosomes.some((item) => item.name === chromosome)) {
      setChromosome(undefined);
    }
  }, [chromosome, chromosomes]);

  // Deep link: restore form state from URL once assemblies/chromosomes load.
  const restoredRef = React.useRef(false);
  React.useEffect(() => {
    if (restoredRef.current) return;
    // Resolve assembly id from URL name/id.
    if (urlAssembly && assemblies.length > 0) {
      const match = assemblies.find((a) => String(a.id) === urlAssembly || a.name === urlAssembly);
      if (match) setAssemblyId(String(match.id));
    }
    if (urlChromosome) setChromosome(urlChromosome);
    if (urlStart != null) setStart(urlStart);
    if (urlEnd != null) setEnd(urlEnd);
  }, [urlAssembly, urlChromosome, urlStart, urlEnd, assemblies]);

  const autoRun = (assembly: string, chr: string, s: number, e: number): RegionQuery | null => {
    if (s < 1 || e < s) return null;
    return { assembly, chromosome: chr, start: s, end: e };
  };

  // Auto-submit once when `run=1` arrives with a complete, valid region.
  React.useEffect(() => {
    if (restoredRef.current) return;
    if (run !== true) return;
    const assembly = selectedAssembly?.name;
    if (!assembly || !urlChromosome || urlStart == null || urlEnd == null) return;
    const query = autoRun(assembly, urlChromosome, urlStart, urlEnd);
    if (!query) return;
    restoredRef.current = true;
    setSubmitted(query);
  }, [run, selectedAssembly, urlChromosome, urlStart, urlEnd]);

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

  const submitInNewTab = () => {
    if (!selectedAssembly || !chromosome || start == null || end == null) return;
    if (start < 1 || end < start) return;
    const location = router.buildLocation({
      to: "/search/location",
      search: { assembly: selectedAssembly.name, chromosome, start, end, run: true },
    });
    window.open(location.href, "_blank", "noopener");
  };

  const columns: TableColumnsType<VariantSummary> = [
    {
      // 1. Genome assembly
      title: t("search.location.colAssembly"),
      dataIndex: "assembly",
      key: "assembly",
      render: () => <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>,
    },
    {
      // 2. Chromosome
      title: t("search.location.colChromosome"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      // 3. Position
      title: t("search.location.colPosition"),
      dataIndex: "position",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {row.chromosome}:{formatNumber(row.position)}
        </span>
      ),
    },
    {
      // 4. Mutation feature
      title: t("search.location.colMutation"),
      dataIndex: "mutation",
      key: "mutation",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.impact ?? row.variant_type ?? "—"}</span>
      ),
    },
    {
      // 5. Gene ID (linked to detail when present)
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
      // 6. JBrowse 2 action (base-aware, new tab)
      title: t("search.location.colGbrowse"),
      dataIndex: "gbrowse",
      key: "gbrowse",
      render: (_, row) => (
        <Button
          size="small"
          disabled={!selectedAssembly}
          href={
            selectedAssembly
              ? buildJbrowseLocusUrl(import.meta.env.BASE_URL, {
                  assembly: selectedAssembly.name,
                  locus: `${row.chromosome}:${row.position}-${row.position}`,
                }).href
              : undefined
          }
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("search.location.openBrowser")}
        </Button>
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
          <Form layout="vertical" onFinish={submitInNewTab}>
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
                    loading={chromosomesQuery.isLoading}
                    options={chromosomes.map((item) => ({
                      value: item.name,
                      label: item.name,
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
            <div className="-mx-4 overflow-x-auto sm:mx-0">
              <Table<VariantSummary>
                rowKey="variant_id"
                columns={columns}
                dataSource={data}
                loading={regionQuery.isLoading}
                pagination={
                  data.length > 25 ? { pageSize: 25, showSizeChanger: false } : false
                }
                scroll={{ x: 720 }}
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
          </div>
        ) : null}
      </div>
    </FadeUp>
  );
}
