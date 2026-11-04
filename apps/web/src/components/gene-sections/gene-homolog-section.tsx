/**
 * Homolog block of the gene page.
 *
 * Every row is evidence *transferred* from another locus — the record describes
 * a gene in another species, never this gene. The badge is therefore constant
 * (the API sets `kind: "transferred"` and this card never overrides it) and the
 * section-level provenance line says where the transfer came from.
 *
 * This block replaces the old `/genes/{id}/homologs` request for the same
 * reason it exists: one section, one source.
 */
import { Card, Empty, Table, Tag, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneHomologRecord, GeneHomologSection } from "@soymutdb/api-client";
import { EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GeneHomologSectionCardProps {
  section?: GeneHomologSection | null;
}

export function GeneHomologSectionCard({ section }: GeneHomologSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.tabs.homologs");

  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice status={section.status} label={label} emptyMessage={t("genes.homologs.no_data")} />
    );
  }

  const columns: TableColumnsType<GeneHomologRecord> = [
    {
      title: t("genes.homologs.species"),
      dataIndex: "homolog_species",
      key: "homolog_species",
    },
    {
      title: t("genes.homologs.gene_id"),
      dataIndex: "homolog_gene_id",
      key: "homolog_gene_id",
      render: (_, row) => <span className="font-mono text-xs">{row.homolog_gene_id}</span>,
    },
    {
      title: t("genes.homologs.type"),
      dataIndex: "homolog_type",
      key: "homolog_type",
      render: (_, row) => <Tag className="m-0 text-[10px]">{row.homolog_type}</Tag>,
    },
    {
      title: t("genes.homologs.source"),
      dataIndex: "source",
      key: "source",
      // The import has no method column today; an absent value stays absent.
      render: (_, row) => row.source ?? "—",
    },
  ];

  return (
    <ScaleIn>
      <Card data-testid="gene-homolog-section" title={<span className="text-base">{label}</span>}>
        <div className="mb-3">
          <EvidenceLine evidence={section.status.evidence} />
        </div>
        <Table<GeneHomologRecord>
          rowKey={(row) => `${row.homolog_species}-${row.homolog_gene_id}`}
          size="small"
          columns={columns}
          dataSource={section.records}
          pagination={false}
          locale={{ emptyText: <Empty description={t("genes.homologs.no_data")} /> }}
        />
      </Card>
    </ScaleIn>
  );
}
