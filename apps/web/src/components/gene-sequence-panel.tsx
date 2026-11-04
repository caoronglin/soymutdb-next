/**
 * Sequences tab for the gene detail page.
 *
 * The platform holds coordinates and annotations, not residues, so the honest
 * answer for every molecule is "not imported". This panel renders that answer
 * explicitly instead of an empty table or a zero-length string: "no data" and
 * "we never stored it" are different statements, and only one of them is true
 * here.
 *
 * When a sequence store lands, `availability` flips to "available" and the same
 * panel renders the residues (with length and checksum) without a layout change.
 */
import { Alert, Card, Descriptions, Empty, Tag, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneSequenceAvailability } from "@soymutdb/api-client";

export interface GeneSequencePanelProps {
  sequences?: GeneSequenceAvailability[];
}

const MOLECULES: GeneSequenceAvailability["molecule"][] = [
  "genomic",
  "cds",
  "transcript",
  "protein",
];

export function GeneSequencePanel({ sequences }: GeneSequencePanelProps) {
  const { t } = useTranslation();
  const byMolecule = new Map((sequences ?? []).map((entry) => [entry.molecule, entry]));
  const anyAvailable = (sequences ?? []).some((entry) => entry.availability === "available");

  return (
    <Card title={<span className="text-base">{t("genes.sequences.title")}</span>}>
      {!anyAvailable ? (
        <Alert
          type="info"
          showIcon
          title={t("genes.sequences.unavailable")}
          description={t("genes.sequences.unavailableHint")}
          className="mb-4"
        />
      ) : null}

      {sequences === undefined ? (
        // An older API build without the field: say so rather than claim all
        // four molecules are unavailable.
        <Empty description={t("common.noData")} />
      ) : (
        <Descriptions
          size="small"
          column={1}
          bordered
          items={MOLECULES.map((molecule) => {
            const entry = byMolecule.get(molecule);
            return {
              key: molecule,
              label: t(`genes.sequences.molecule.${molecule}`),
              children: <SequenceValue entry={entry} />,
            };
          })}
        />
      )}
    </Card>
  );
}

function SequenceValue({ entry }: { entry?: GeneSequenceAvailability }) {
  const { t } = useTranslation();
  if (!entry) {
    return <Typography.Text type="secondary">{t("genes.sequences.unavailable")}</Typography.Text>;
  }
  if (entry.availability !== "available" || entry.sequence == null) {
    return (
      <span className="inline-flex items-center gap-2">
        <Tag data-testid="sequence-unavailable">{t("genes.sequences.unavailable")}</Tag>
        {entry.reason ? (
          <Typography.Text type="secondary" className="font-mono text-xs">
            {entry.reason}
          </Typography.Text>
        ) : null}
      </span>
    );
  }
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <Tag color="green">{t("genes.sequences.available")}</Tag>
        {entry.length != null ? (
          <span className="font-mono text-xs">
            {t("genes.sequences.length")}: {entry.length.toLocaleString()}
          </span>
        ) : null}
      </div>
      <pre className="max-h-64 overflow-auto break-all whitespace-pre-wrap font-mono text-xs">
        {entry.sequence}
      </pre>
    </div>
  );
}
