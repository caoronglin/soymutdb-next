/**
 * Provenance badges for scientific claims.
 *
 * A plant database page carries statements of very different weight: a measured
 * expression value, a curated GO term, an Augustus gene model, a motif
 * transferred from Arabidopsis. Rendering them identically is the single
 * easiest way for a database to publish a false claim, so the strength is
 * encoded in one place — this component — and every section reuses it.
 *
 * Colours come from antd theme tokens (no hardcoded hex): `error` is reserved
 * for nothing here on purpose, because "predicted" is not an error, it is a
 * weaker claim.
 */
import { Tag, Tooltip } from "@/lib/antd";
import type { ComponentProps } from "react";
import { useTranslation } from "react-i18next";
import type { EvidenceKind, EvidenceTag as EvidenceTagRecord } from "@soymutdb/api-client";

const KIND_COLOR: Record<EvidenceKind, ComponentProps<typeof Tag>["color"]> = {
  experimental: "green",
  curated: "blue",
  predicted: "gold",
  transferred: "purple",
  imported: "default",
  unknown: "default",
};

export interface EvidenceTagProps {
  evidence: EvidenceTagRecord;
  /** Hide the source string when the surrounding card already states it. */
  showSource?: boolean;
  className?: string;
}

export function EvidenceBadge({ evidence, showSource = true, className }: EvidenceTagProps) {
  const { t } = useTranslation();
  const hint = t(`genes.evidence.kindHint.${evidence.kind}`);
  return (
    <Tooltip title={hint}>
      <Tag color={KIND_COLOR[evidence.kind]} className={className} data-evidence-kind={evidence.kind}>
        {t(`genes.evidence.kind.${evidence.kind}`)}
        {showSource && evidence.source ? (
          <span className="ml-1 font-normal opacity-70">{evidence.source}</span>
        ) : null}
      </Tag>
    </Tooltip>
  );
}

/** Section-level provenance line: "Evidence: <badge> · source". */
export function EvidenceLine({ evidence }: { evidence: EvidenceTagRecord | null }) {
  const { t } = useTranslation();
  if (!evidence) {
    // No tag is not "unknown strength": it means the source record said
    // nothing, and the page must say exactly that rather than imply import.
    return <span className="text-sm text-muted-foreground">{t("genes.evidence.unknownSource")}</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span className="text-muted-foreground">{t("genes.evidence.label")}</span>
      <EvidenceBadge evidence={evidence} />
    </span>
  );
}
