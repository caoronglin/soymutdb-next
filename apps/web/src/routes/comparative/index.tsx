/**
 * Comparative genomics — gene family browser (`/comparative`).
 *
 * This is the gene-family entry point. `/compare` is variant comparison and has
 * nothing to do with this page; the two must not be merged.
 *
 * Every filter lives in the URL (`validateSearch`), so a view is deep-linkable
 * and shareable: a colleague opening the link sees the same assembly, level and
 * page this operator saw.
 */
import { assembliesQueryOptions } from "../../lib/query-options";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Button, Card, Empty, Select, Skeleton, Table, Tag, type TableColumnsType } from "@/lib/antd";
import { DeploymentUnitOutlined as Dna } from "@ant-design/icons";
import { listFamilies, type GeneFamily } from "@soymutdb/api-client";
import { EvidenceBadge } from "../../components/evidence-tag";
import { FadeUp } from "../../components/route-motion";
import { formatNumber } from "../../lib/format";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

const PAGE_SIZE = 20;

export type ComparativeLevel = "gene_family" | "gene_subfamily";

export interface ComparativeSearch {
  page: number;
  /** Assembly id as a string so an unset filter round-trips as ""; parsed on read. */
  assembly: string;
  level: ComparativeLevel | "";
}

/** Narrow the raw, possibly hostile search object into the typed filter state. */
export function validateComparativeSearch(search: Record<string, unknown>): ComparativeSearch {
  const rawPage = Number(search.page);
  const level = search.level;
  return {
    page: Number.isFinite(rawPage) && rawPage >= 1 ? Math.floor(rawPage) : 1,
    assembly: search.assembly ? String(search.assembly) : "",
    level: level === "gene_family" || level === "gene_subfamily" ? level : "",
  };
}

export const Route = createFileRoute("/comparative/")({
  component: ComparativeFamiliesComponent,
  validateSearch: validateComparativeSearch,
});

function ComparativeFamiliesComponent() {
  const { t } = useTranslation();
  const search = Route.useSearch() as ComparativeSearch;
  const navigate = Route.useNavigate();
  const releaseId = useReleaseId();
  const assemblyId = search.assembly ? Number(search.assembly) : null;

  const assembliesQuery = useQuery(
    assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );

  const familiesQuery = useQuery({
    queryKey: queryKeys.comparative.families({
      assemblyId,
      level: search.level || null,
      page: search.page,
      pageSize: PAGE_SIZE,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      listFamilies({
        assembly_id: assemblyId,
        level: search.level || undefined,
        page: search.page,
        page_size: PAGE_SIZE,
      }),
  });

  const families = familiesQuery.data?.items ?? [];
  const total = familiesQuery.data?.total ?? 0;

  const setSearch = (patch: Partial<ComparativeSearch>) => {
    // Any filter change restarts pagination: keeping page 4 of the previous
    // filter would show an empty table that reads as "no families exist".
    const next: ComparativeSearch = { ...search, page: 1, ...patch };
    void navigate({ to: "/comparative", search: next });
  };

  const columns: TableColumnsType<GeneFamily> = [
    {
      title: t("comparative.list.family"),
      key: "family",
      render: (_, row) => (
        <Link
          to="/comparative/$familyId"
          params={{ familyId: String(row.family_id) }}
          search={{ assembly: search.assembly }}
          className="link-underline font-mono text-xs"
        >
          {row.external_id}
        </Link>
      ),
    },
    { title: t("comparative.list.name"), dataIndex: "name", key: "name" },
    {
      title: t("comparative.list.members"),
      dataIndex: "member_count",
      key: "member_count",
      align: "right",
      render: (_, row) => (
        <span className="font-mono tabular-nums">{formatNumber(row.member_count)}</span>
      ),
    },
    {
      title: t("comparative.list.method"),
      key: "method",
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.method}
          {row.method_version ? <span className="text-muted-foreground"> v{row.method_version}</span> : null}
        </span>
      ),
    },
    {
      title: t("comparative.list.source"),
      key: "source",
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.source_name}
          <span className="text-muted-foreground"> {row.source_version}</span>
        </span>
      ),
    },
    {
      title: "",
      key: "evidence",
      render: (_, row) => <EvidenceBadge evidence={row.evidence} showSource={false} />,
    },
  ];

  return (
    <FadeUp>
      <div className="container-prose section-rhythm py-10">
        <p className="eyebrow">{t("nav.comparative")}</p>
        <h1 className="mt-2 font-display text-3xl font-semibold tracking-tight">
          {t("comparative.title")}
        </h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">{t("comparative.subtitle")}</p>

        <Card className="mt-6" data-testid="comparative-filters">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t("comparative.filters.assembly")}
              <Select
                data-testid="comparative-assembly"
                className="min-w-48"
                value={search.assembly || ""}
                onChange={(value: string) => setSearch({ assembly: value })}
                options={[
                  { value: "", label: t("comparative.filters.allAssemblies") },
                  ...(assembliesQuery.data ?? []).map((assembly) => ({
                    value: String(assembly.id),
                    label: `${assembly.name} (${assembly.species})`,
                  })),
                ]}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t("comparative.filters.level")}
              <Select
                data-testid="comparative-level"
                className="min-w-44"
                value={search.level || ""}
                onChange={(value: string) =>
                  setSearch({ level: value as ComparativeLevel | "" })
                }
                options={[
                  { value: "", label: t("comparative.filters.allLevels") },
                  { value: "gene_family", label: t("comparative.level.gene_family") },
                  { value: "gene_subfamily", label: t("comparative.level.gene_subfamily") },
                ]}
              />
            </label>
            {search.assembly || search.level ? (
              <Button
                size="small"
                onClick={() => setSearch({ assembly: "", level: "" })}
                data-testid="comparative-clear"
              >
                {t("comparative.filters.clear")}
              </Button>
            ) : null}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {t("comparative.filters.searchParamsNote")}
          </p>
        </Card>

        {familiesQuery.isLoading ? (
          <Skeleton active className="mt-6" paragraph={{ rows: 8 }} title={false} />
        ) : familiesQuery.isError ? (
          <Card className="mt-6">
            <Empty description={t("comparative.list.loadError")} className="py-8" />
          </Card>
        ) : families.length === 0 ? (
          // An absent family table is not "0 families": nothing was imported for
          // this scope, and the copy says so instead of printing a count.
          <Card className="mt-6" data-testid="comparative-empty">
            <Empty
              image={<Dna className="size-10 text-muted-foreground" aria-hidden />}
              description={
                <div className="space-y-1">
                  <p>{t("comparative.list.empty")}</p>
                  <p className="text-xs text-muted-foreground">
                    {t("comparative.list.emptyHint")}
                  </p>
                </div>
              }
              className="py-10"
            />
          </Card>
        ) : (
          <Card className="mt-6">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <Tag color="blue" className="m-0 font-mono text-xs">
                {t("comparative.list.total", { total: formatNumber(total) })}
              </Tag>
              <span className="text-xs text-muted-foreground">
                {t("comparative.list.pageInfo", {
                  page: search.page,
                  pages: Math.max(1, Math.ceil(total / PAGE_SIZE)),
                })}
              </span>
            </div>
            <Table<GeneFamily>
              rowKey="family_id"
              size="small"
              columns={columns}
              dataSource={families}
              pagination={{
                current: search.page,
                pageSize: PAGE_SIZE,
                total,
                showSizeChanger: false,
                onChange: (page) => void navigate({ to: "/comparative", search: { ...search, page } }),
              }}
              scroll={{ x: 800 }}
            />
          </Card>
        )}
      </div>
    </FadeUp>
  );
}
