/**
 * Phenotype block of the gene page.
 *
 * The mutant line is identified by `mutant_public_id` only. The API's phenotype
 * records deliberately carry no internal row key, and this table must not grow
 * one — a phenotype row is a public statement about a published line, and the
 * internal key is not part of that statement. The display name is secondary, the
 * public id is the link target.
 */
import { Card, Empty, Table, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GenePhenotypeRecord, GenePhenotypeSection } from "@soymutdb/api-client";
import { EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GenePhenotypeSectionCardProps {
  section?: GenePhenotypeSection | null;
}

export function GenePhenotypeSectionCard({ section }: GenePhenotypeSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.sections.phenotype.title");

  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice
        status={section.status}
        label={label}
        emptyMessage={t("genes.sections.phenotype.empty")}
      />
    );
  }

  const columns: TableColumnsType<GenePhenotypeRecord> = [
    {
      title: t("genes.sections.phenotype.mutant"),
      dataIndex: "mutant_public_id",
      key: "mutant_public_id",
      render: (_, row) => (
        <span data-testid="phenotype-mutant" className="font-mono text-xs">
          {row.mutant_public_id}
        </span>
      ),
    },
    { title: t("genes.sections.phenotype.category"), dataIndex: "trait_category", key: "trait_category" },
    { title: t("genes.sections.phenotype.trait"), dataIndex: "trait_name", key: "trait_name" },
    {
      title: t("genes.sections.phenotype.value"),
      dataIndex: "trait_value",
      key: "trait_value",
      // A trait recorded without a value or unit stays that way.
      render: (_, row) =>
        row.trait_value == null ? (
          "—"
        ) : (
          <span className="font-mono text-xs">
            {row.trait_value}
            {row.unit ? ` ${row.unit}` : ""}
          </span>
        ),
    },
    {
      title: t("genes.sections.phenotype.method"),
      dataIndex: "measurement_method",
      key: "measurement_method",
      render: (_, row) => row.measurement_method ?? "—",
    },
  ];

  return (
    <ScaleIn>
      <Card data-testid="gene-phenotype-section" title={<span className="text-base">{label}</span>}>
        <div className="mb-3">
          <EvidenceLine evidence={section.status.evidence} />
        </div>
        <Table<GenePhenotypeRecord>
          rowKey={(row) => `${row.mutant_public_id}-${row.trait_category}-${row.trait_name}`}
          size="small"
          columns={columns}
          dataSource={section.records}
          pagination={false}
          scroll={{ x: 720 }}
          locale={{ emptyText: <Empty description={t("genes.sections.phenotype.empty")} /> }}
        />
      </Card>
    </ScaleIn>
  );
}
