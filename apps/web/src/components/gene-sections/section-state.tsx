/**
 * The one place a gene-detail section decides what "nothing here" looks like.
 *
 * A gene page renders six optional blocks, each carrying a `SectionStatus`. The
 * three states are three different scientific statements and must never
 * collapse into one another:
 *
 * - `available` — rows exist, render them.
 * - `empty` — the snapshot is loaded for this release and this gene has no
 *   rows in it. An empty state, not an error.
 * - `not_imported` — the release holds no snapshot at all. Saying "this gene
 *   has no GO terms" here would be a false claim about the gene.
 *
 * `status.count` is `null` when the source is absent, and no branch below
 * prints it. A keyed reason (e.g. `annotation_set_missing`) is shown verbatim
 * so a client can act on it instead of matching prose.
 */
import { Alert, Empty, Tag } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import type { GeneSectionStatus } from "@soymutdb/api-client";

export interface SectionNoticeProps {
  status: GeneSectionStatus;
  /** Already-localised name of the data, e.g. "GO / KEGG". */
  label: string;
  /** Section-specific `empty` sentence; falls back to a generic one. */
  emptyMessage?: string;
}

/** Rendered for `empty` / `not_imported`; `available` is the caller's business. */
export function SectionNotice({ status, label, emptyMessage }: SectionNoticeProps) {
  const { t } = useTranslation();
  const reason = status.reason ? (
    <Tag data-testid="gene-section-reason" className="font-mono text-[10px]">
      {t("genes.sections.state.reason", { reason: status.reason })}
    </Tag>
  ) : null;

  if (status.state === "available") {
    // Only reachable through a status/rows mismatch (a bug upstream, not a data
    // state): say so instead of rendering a count that does not match the rows.
    return (
      <Empty
        data-testid="gene-section-unreported"
        description={t("genes.sections.state.unreported", { section: label })}
      />
    );
  }

  const notImported = status.state === "not_imported";
  return (
    <div data-testid={`gene-section-${notImported ? "not-imported" : "empty"}`}>
      <Alert
        type={notImported ? "warning" : "info"}
        showIcon
        title={
          notImported
            ? t("genes.sections.state.notImported", { section: label })
            : (emptyMessage ?? t("genes.sections.state.empty", { section: label }))
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>
              {notImported
                ? t("genes.sections.state.notImportedHint")
                : t("genes.sections.state.emptyHint")}
            </span>
            {reason}
          </span>
        }
      />
    </div>
  );
}

/**
 * The status itself is optional on the wire: an older API build omits the block
 * rather than sending an empty list. That is not "this gene has none" either,
 * and it is not an error — say exactly that.
 */
export function SectionMissing({ label }: { label: string }) {
  const { t } = useTranslation();
  return (
    <Empty
      data-testid="gene-section-unreported"
      description={t("genes.sections.state.unreported", { section: label })}
    />
  );
}
