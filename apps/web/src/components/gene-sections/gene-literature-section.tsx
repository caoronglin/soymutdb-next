/**
 * Literature block of the gene page.
 *
 * Today the API answers `not_imported` with the reason
 * `gene_literature_link_missing`: the schema has no gene -> publication
 * relation yet. This card renders exactly that sentence and an empty state — it
 * does not fall back to unrelated publications, and it does not print a count.
 * When the relation lands, only the API changes and rows appear here.
 */
import { Card, Empty, Table, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneLiteratureRecord, GeneLiteratureSection } from "@soymutdb/api-client";
import { EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GeneLiteratureSectionCardProps {
  section?: GeneLiteratureSection | null;
}

export function GeneLiteratureSectionCard({ section }: GeneLiteratureSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.sections.literature.title");

  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice
        status={section.status}
        label={label}
        emptyMessage={t("genes.sections.literature.empty")}
      />
    );
  }

  const columns: TableColumnsType<GeneLiteratureRecord> = [
    { title: t("genes.sections.literature.titleColumn"), dataIndex: "title", key: "title" },
    {
      title: t("genes.sections.literature.authors"),
      dataIndex: "authors",
      key: "authors",
      render: (_, row) => row.authors ?? "—",
    },
    {
      title: t("genes.sections.literature.journal"),
      dataIndex: "journal",
      key: "journal",
      render: (_, row) => row.journal ?? "—",
    },
    {
      title: t("genes.sections.literature.year"),
      dataIndex: "year",
      key: "year",
      align: "right",
      render: (_, row) =>
        row.year == null ? (
          "—"
        ) : (
          <span className="font-mono tabular-nums">{row.year}</span>
        ),
    },
    {
      title: t("genes.sections.literature.identifier"),
      key: "identifier",
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.doi ?? row.pmid ?? "—"}
        </span>
      ),
    },
  ];

  return (
    <ScaleIn>
      <Card data-testid="gene-literature-section" title={<span className="text-base">{label}</span>}>
        <div className="mb-3">
          <EvidenceLine evidence={section.status.evidence} />
        </div>
        <Table<GeneLiteratureRecord>
          rowKey={(row) => row.doi ?? row.pmid ?? row.title}
          size="small"
          columns={columns}
          dataSource={section.records}
          pagination={false}
          scroll={{ x: 800 }}
          locale={{ emptyText: <Empty description={t("genes.sections.literature.empty")} /> }}
        />
      </Card>
    </ScaleIn>
  );
}
