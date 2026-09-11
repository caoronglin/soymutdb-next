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
import { useSiteContent } from "../../lib/site-content";
import * as React from "react";
import { Alert, Button, Card, Empty, Form, Input, Select, Table, Tag, Typography, type TableColumnsType } from "@/lib/antd";
import { SearchOutlined } from "@ant-design/icons";
import {
  getAssemblies,
  getReleaseId,
  searchGenes,
  type GeneSummary,
  type AssemblyInfo,
} from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { compactGeneId, formatNumber } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
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
  const { get } = useSiteContent();
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
    queryKey: queryKeys.assemblies.all(),
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

  const releaseId = getReleaseId();
  const resultsQuery = useQuery({
    queryKey: queryKeys.genes.search({
      q: submitted?.q,
      assemblyId: submitted?.assemblyId,
      page,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      searchGenes({
        q: submitted?.q || undefined,
        assembly_id: submitted?.assemblyId || undefined,
        page,
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
      title: get("search.genes.colAssembly", t("search.genes.colAssembly")),
      dataIndex: "assembly",
      key: "assembly",
      render: () => (
        <span className="font-mono text-xs">{selectedAssembly?.name ?? "—"}</span>
      ),
    },
    {
      // 2. Chromosome
      title: get("search.genes.colChromosome", t("search.genes.colChromosome")),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      // 3. Position
      title: get("search.genes.colPosition", t("search.genes.colPosition")),
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
      title: get("search.genes.colMutation", t("search.genes.colMutation")),
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
      title: get("search.genes.colGeneId", t("search.genes.colGeneId")),
      dataIndex: "gene_id",
      key: "gene_id",
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          search={{ assembly: resolvedAssemblyId }}
          aria-label={t("search.genes.openGene", { geneId: row.gene_id })}
          className="link-underline font-mono text-sm font-medium text-primary"
        >
          {compactGeneId(row.gene_id, 18)}
        </Link>
      ),
    },
    {
      // 6. JBrowse 2 action (base-aware, new tab)
      title: get("search.genes.colGbrowse", t("search.genes.colGbrowse")),
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
        <p className="eyebrow">{get("search.genes.title", t("search.genes.title"))}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {get("search.genes.subtitle", t("search.genes.subtitle"))}
        </h2>

        <Card className="mt-6 max-w-3xl">
          <Form
            layout="inline"
            className="mt-6 flex flex-wrap items-end gap-x-4 gap-y-4"
            onFinish={submitInNewTab}
          >
            <Form.Item label={get("search.genes.assembly", t("search.genes.assembly"))} className="mb-0">
              <Select
                value={formAssemblyId}
                onChange={(v) => setAssemblyId(v)}
                placeholder={get("search.genes.assemblyPlaceholder", t("search.genes.assemblyPlaceholder"))}
                loading={assembliesQuery.isLoading}
                style={{ width: 220 }}
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
              {assembliesQuery.isError ? (
                <Alert
                  className="mt-2"
                  type="error"
                  showIcon
                  message={t("search.genes.assembliesUnavailable", { defaultValue: "Assembly list unavailable" })}
                />
              ) : null}
            </Form.Item>
            <Form.Item label={get("search.genes.geneId", t("search.genes.geneId"))} className="mb-0">
              <Input.TextArea
                rows={2}
                value={geneIdsRaw}
                onChange={(e) => setGeneIdsRaw(e.target.value)}
                placeholder={get("search.genes.geneIdPlaceholder", t("search.genes.geneIdPlaceholder"))}
                className="font-mono text-sm"
                style={{ width: 320 }}
                aria-label={get("search.genes.geneId", t("search.genes.geneId"))}
              />
            </Form.Item>
            <Form.Item className="mb-0">
              <Button
                type="primary"
                htmlType="submit"
                icon={<SearchOutlined aria-hidden />}
                loading={resultsQuery.isFetching}
              >
                {get("ui.searchButton", t("search.genes.submit"))}
              </Button>
            </Form.Item>
          </Form>
          <Typography.Text type="secondary" className="mt-2 block text-xs">
            {get("search.genes.geneIdHint", t("search.genes.geneIdHint"))}
          </Typography.Text>
        </Card>

        {submitted ? (
          <div className="mt-6" role="region" aria-label="Gene ID search results">
            <p className="mb-3 text-sm text-muted-foreground">
              {t("search.genes.resultsFor")}{" "}
              <span className="font-mono text-foreground">"{submitted.q}"</span>
              {" · "}
              {formatNumber(total)}
            </p>
            {resultsQuery.isError ? (
              <Alert
                type="error"
                showIcon
                message={t("search.genes.resultsUnavailable", { defaultValue: "Gene search unavailable" })}
                description={get("ui.errorRetry", t("search.genes.resultsRetry", { defaultValue: "The API did not return a result set. Please retry later." }))}
              />
            ) : (
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
                          {get("ui.noResults", t("search.genes.noResults"))}
                        </Typography.Text>
                      }
                    />
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
