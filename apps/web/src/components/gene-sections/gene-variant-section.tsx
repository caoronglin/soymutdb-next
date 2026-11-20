/**
 * Variant totals block of the gene page.
 *
 * `by_impact` holds only the consequence classes the API actually counted: a
 * class missing from the map was not measured, which is not the same as a class
 * measured as zero. So the table lists what the map holds and never fills the
 * gap with a fabricated row — the void is the statement.
 *
 * `total` can only be `null` when the section is not imported, and that branch
 * never renders a number at all.
 */
import { Card, Empty, Table, Tag, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneVariantSection } from "@soymutdb/api-client";
import { EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GeneVariantSectionCardProps {
  section?: GeneVariantSection | null;
}

interface ImpactRow {
  impact: string;
  count: number;
}

export function GeneVariantSectionCard({ section }: GeneVariantSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.sections.variants.title");

  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice status={section.status} label={label} emptyMessage={t("genes.sections.variants.empty")} />
    );
  }

  const rows: ImpactRow[] = Object.entries(section.by_impact)
    .map(([impact, count]) => ({ impact, count }))
    .sort((left, right) => right.count - left.count || left.impact.localeCompare(right.impact));

  const columns: TableColumnsType<ImpactRow> = [
    {
      title: t("genes.sections.variants.impact"),
      dataIndex: "impact",
      key: "impact",
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.impact === "unknown" ? t("genes.sections.variants.unannotated") : row.impact}
        </span>
      ),
    },
    {
      title: t("genes.sections.variants.count"),
      dataIndex: "count",
      key: "count",
      align: "right",
      render: (_, row) => <span className="font-mono tabular-nums">{row.count.toLocaleString()}</span>,
    },
  ];

  return (
    <ScaleIn>
      <Card
        data-testid="gene-variant-section"
        title={<span className="text-base">{label}</span>}
        extra={
          section.total == null ? null : (
            <span className="text-sm text-muted-foreground">
              {t("genes.sections.variants.total")}:{" "}
              <span data-testid="gene-variant-total" className="font-mono tabular-nums">
                {section.total.toLocaleString()}
              </span>
            </span>
          )
        }
      >
        <div className="mb-3">
          <EvidenceLine evidence={section.status.evidence} />
        </div>
        {rows.length === 0 ? (
          <Empty description={t("genes.sections.variants.empty")} />
        ) : (
          <Table<ImpactRow>
            rowKey="impact"
            size="small"
            columns={columns}
            dataSource={rows}
            pagination={false}
          />
        )}
        <Tag className="mt-3 text-[10px]">{t("genes.evidence.kind.predicted")}</Tag>
      </Card>
    </ScaleIn>
  );
}
