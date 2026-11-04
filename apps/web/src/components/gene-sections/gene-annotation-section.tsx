/**
 * GO / KEGG annotation block of the gene page.
 *
 * Each row keeps the source's own evidence code (`IDA`, `IEA`, ...) verbatim
 * *and* the coarse evidence class the API derived from it. Both are shown: the
 * code is what a reviewer checks against the original snapshot, the badge is
 * what a reader compares across sections. Collapsing them would either hide the
 * provenance or invite the client to reimplement the mapping.
 *
 * A term with no code renders `unknown` — it never inherits the section's
 * strongest label.
 */
import { Card, Table, Tag, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneAnnotationSection, GeneAnnotationTerm } from "@soymutdb/api-client";
import { EvidenceBadge, EvidenceLine } from "@/components/evidence-tag";
import { ScaleIn } from "./animation";
import { SectionMissing, SectionNotice } from "./section-state";

export interface GeneAnnotationSectionCardProps {
  section?: GeneAnnotationSection | null;
}

export function GeneAnnotationSectionCard({ section }: GeneAnnotationSectionCardProps) {
  const { t } = useTranslation();
  const label = t("genes.sections.annotation.title");

  if (!section) return <SectionMissing label={label} />;
  if (section.status.state !== "available") {
    return (
      <SectionNotice
        status={section.status}
        label={label}
        emptyMessage={t("genes.sections.annotation.empty")}
      />
    );
  }

  const columns: TableColumnsType<GeneAnnotationTerm> = [
    {
      title: t("genes.sections.annotation.ontology"),
      dataIndex: "ontology",
      key: "ontology",
      width: 90,
      render: (_, row) => <Tag className="m-0 font-mono text-[10px] uppercase">{row.ontology}</Tag>,
    },
    {
      title: t("genes.sections.annotation.term"),
      dataIndex: "term_id",
      key: "term_id",
      render: (_, row) => <span className="font-mono text-xs">{row.term_id}</span>,
    },
    {
      title: t("genes.sections.annotation.termName"),
      dataIndex: "term_name",
      key: "term_name",
    },
    {
      title: t("genes.sections.annotation.evidenceCode"),
      dataIndex: "evidence_code",
      key: "evidence_code",
      // The code exactly as the snapshot carried it; em dash when absent, never
      // an empty cell that reads as "no evidence needed".
      render: (_, row) => (
        <span data-testid="annotation-evidence-code" className="font-mono text-xs">
          {row.evidence_code ?? "—"}
        </span>
      ),
    },
    {
      title: t("genes.evidence.label"),
      dataIndex: "kind",
      key: "kind",
      render: (_, row) => (
        <span data-testid="annotation-evidence-kind">
          <EvidenceBadge evidence={{ kind: row.kind, source: row.reference ?? "" }} showSource={false} />
        </span>
      ),
    },
  ];

  return (
    <ScaleIn>
      <Card
        data-testid="gene-annotation-section"
        title={<span className="text-base">{label}</span>}
        extra={section.source_name ? <Tag className="m-0 text-[10px]">{section.source_name}</Tag> : null}
      >
        <div className="mb-3 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <EvidenceLine evidence={section.status.evidence} />
          {section.source_version ? (
            <span className="font-mono text-xs">
              {t("genes.sections.annotation.snapshotVersion")}: {section.source_version}
            </span>
          ) : null}
        </div>
        <Table<GeneAnnotationTerm>
          rowKey={(row) => `${row.ontology}:${row.term_id}:${row.evidence_code ?? "-"}`}
          size="small"
          columns={columns}
          dataSource={section.terms}
          pagination={section.terms.length > 20 ? { pageSize: 20, showSizeChanger: false } : false}
          scroll={{ x: 720 }}
        />
      </Card>
    </ScaleIn>
  );
}
