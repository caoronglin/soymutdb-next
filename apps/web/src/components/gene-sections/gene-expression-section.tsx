/**
 * Expression block of the gene page.
 *
 * Reads `gene.expression_section` instead of a second `/genes/{id}/expression`
 * request: the detail response already carries the block with its status, and
 * two requests for one dataset is how the two drift apart.
 *
 * `tpm` / `fpkm` are independently optional — a snapshot may carry one unit and
 * not the other — so an absent value renders an em dash, never `0.00`. That is
 * the same rule the section applies at the row level, applied at the value
 * level: "not measured" is not "measured as nothing".
 */
import type { ReactNode } from "react";
import { Card, Empty, Skeleton, Table, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneExpressionRecord, GeneExpressionSection } from "@soymutdb/api-client";
import { EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GeneExpressionSectionCardProps {
  section?: GeneExpressionSection | null;
  /** The section is a suggestion source once loaded; keep it unrendered until then. */
  loading?: boolean;
  /** Chart slot, rendered only when the section is available. */
  chart?: ReactNode;
}

function formatValue(value: number | null): string {
  return value == null ? "—" : value.toFixed(2);
}

export function GeneExpressionSectionCard({
  section,
  loading = false,
  chart,
}: GeneExpressionSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.tabs.expression");

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice status={section.status} label={label} emptyMessage={t("genes.expression.no_data")} />
    );
  }

  const columns: TableColumnsType<GeneExpressionRecord> = [
    { title: t("genes.expression.library"), dataIndex: "library_name", key: "library_name" },
    { title: t("genes.expression.tissue"), dataIndex: "tissue", key: "tissue" },
    { title: t("genes.expression.treatment"), dataIndex: "treatment", key: "treatment" },
    {
      title: t("genes.expression.fpkm"),
      dataIndex: "fpkm",
      key: "fpkm",
      align: "right",
      render: (_, row) => <span className="font-mono tabular-nums">{formatValue(row.fpkm)}</span>,
    },
    {
      title: t("genes.expression.tpm"),
      dataIndex: "tpm",
      key: "tpm",
      align: "right",
      render: (_, row) => <span className="font-mono tabular-nums">{formatValue(row.tpm)}</span>,
    },
  ];

  return (
    <ScaleIn>
      <div data-testid="gene-expression-section" className="space-y-6">
        {chart ? <div data-testid="gene-expression-chart">{chart}</div> : null}
        <Card>
          <div className="mb-3">
            <EvidenceLine evidence={section.status.evidence} />
          </div>
          <Table<GeneExpressionRecord>
            rowKey="library_id"
            size="small"
            columns={columns}
            dataSource={section.records}
            pagination={false}
            locale={{ emptyText: <Empty description={t("genes.expression.no_data")} /> }}
          />
        </Card>
      </div>
    </ScaleIn>
  );
}
