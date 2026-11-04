/**
 * Ortholog/paralog block for one gene.
 *
 * `relationship_type` is printed exactly as the source classified it —
 * `one_to_one`, `one_to_many`, `many_to_many`. It is not translated, softened,
 * or re-derived: the three describe genuinely different cardinalities, and a
 * reader who needs to know whether a gene has one counterpart or several must
 * not be handed a fuzzy synonym.
 *
 * Nothing here ranks or filters by similarity. `OrthologRecord` carries no
 * e-value or bit score by design — orthology is the source's claim, not a
 * measurement this page can make.
 */
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Table, Tag, type TableColumnsType } from "@/lib/antd";
import { getGeneOrthologs, type OrthologRecord } from "@soymutdb/api-client";
import { EvidenceBadge } from "../evidence-tag";
import { ComparativeStateNotice } from "./coverage-states";
import { cn } from "../../lib/cn";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

export function OrthologTable({ records }: { records: OrthologRecord[] }) {
  const { t } = useTranslation();
  const columns: TableColumnsType<OrthologRecord> = [
    {
      title: t("comparative.orthologs.gene"),
      dataIndex: "counterpart_gene_id",
      key: "counterpart_gene_id",
      render: (_, row) => (
        <span className="font-mono text-xs">{row.counterpart_gene_id}</span>
      ),
    },
    {
      title: t("comparative.orthologs.species"),
      key: "counterpart_species",
      render: (_, row) =>
        row.counterpart_species ?? <span className="text-muted-foreground">—</span>,
    },
    {
      title: t("comparative.orthologs.type"),
      key: "relationship_type",
      render: (_, row) => (
        <Tag className="m-0 font-mono text-xs" data-relationship-type={row.relationship_type}>
          {row.relationship_type}
        </Tag>
      ),
    },
    {
      title: t("comparative.orthologs.method"),
      key: "method",
      render: (_, row) =>
        row.method ? <span className="font-mono text-xs">{row.method}</span> : <span className="text-muted-foreground">—</span>,
    },
    {
      title: t("comparative.orthologs.source"),
      key: "evidence",
      render: (_, row) => <EvidenceBadge evidence={row.evidence} />,
    },
  ];

  return (
    <Table<OrthologRecord>
      rowKey={(row) => `${row.counterpart_species ?? "unknown"}-${row.counterpart_gene_id}`}
      size="small"
      columns={columns}
      dataSource={records}
      pagination={records.length > 20 ? { pageSize: 20 } : false}
      scroll={{ x: 700 }}
      locale={{ emptyText: t("comparative.orthologs.empty") }}
    />
  );
}

export interface OrthologSectionProps {
  geneId: string;
  assemblyId?: string;
  className?: string;
}

/**
 * Honours the record's own `state`: `no_data` and `not_imported` mean different
 * things and are reported as such, never as an empty table.
 */
export function GeneOrthologSection({ geneId, assemblyId, className }: OrthologSectionProps) {
  const { t } = useTranslation();
  const releaseId = useReleaseId();
  // Search params carry the assembly as a string; the API takes a numeric id, so
  // parse it once here and keep the raw string out of the request.
  const numericAssemblyId =
    assemblyId && Number.isFinite(Number(assemblyId)) ? Number(assemblyId) : null;
  const orthologsQuery = useQuery({
    queryKey: [
      ...queryKeys.comparative.all(),
      "gene-orthologs",
      geneId,
      numericAssemblyId,
      releaseId,
      SITE_VARIANT,
    ] as const,
    queryFn: () => getGeneOrthologs(geneId, { assembly_id: numericAssemblyId }),
    enabled: Boolean(geneId),
  });

  const data = orthologsQuery.data;
  return (
    <div className={cn("space-y-3", className)} data-testid="gene-orthologs">
      <p className="text-xs text-muted-foreground">{t("comparative.orthologs.hint")}</p>
      {orthologsQuery.isError ? (
        // A failed read is not "the source has no rows": say the read failed.
        <p className="text-sm text-muted-foreground">{t("comparative.orthologs.loadError")}</p>
      ) : data ? (
        data.state === "available" ? (
          <OrthologTable records={data.records} />
        ) : (
          <ComparativeStateNotice state={data.state} />
        )
      ) : null}
    </div>
  );
}
