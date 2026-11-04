/**
 * Presence rendering for comparative genomics.
 *
 * This file exists because of one sentence in the client contract
 * (`api-client/src/comparative.ts`): `member_count: null` is not a measured
 * zero. Three states must be visually and textually distinct:
 *
 * - `available`    the species contributed members; show the count.
 * - `no_data`      the source has no row for this species. Show a phrase, never
 *                  a number. Rendering `null` as `0` publishes a measurement the
 *                  source never made.
 * - `not_imported` this release never imported the family's snapshot at all. A
 *                  different claim from `no_data`, so it gets different words and
 *                  a different colour.
 *
 * Colours come from Tailwind semantic classes so the two states stay
 * distinguishable in light and dark themes without hardcoded hex.
 */
import { Card, Empty, Table, Tag, type TableColumnsType } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { CheckCircleOutlined, MinusCircleOutlined, QuestionCircleOutlined } from "@ant-design/icons";
import type { ComparativeState, SpeciesCoverage } from "@soymutdb/api-client";
import { cn } from "../../lib/cn";

/** Tone per state. `not_imported` is deliberately not the same colour as `no_data`. */
const STATE_TONE: Record<ComparativeState, { tag: string; icon: React.ComponentType<{ className?: string }> }> = {
  available: { tag: "green", icon: CheckCircleOutlined },
  no_data: { tag: "default", icon: MinusCircleOutlined },
  not_imported: { tag: "orange", icon: QuestionCircleOutlined },
};

export function coverageLabelKey(state: ComparativeState): string {
  return `comparative.coverage.${state}`;
}

/**
 * The member count for one coverage row, or `null` when the source reported
 * no count.
 *
 * Returns `null` — never `0` — for `no_data`/`not_imported`, even if a server
 * sends `0` with one of those states, because that combination is exactly the
 * false measurement this component exists to prevent.
 */
export function coverageCount(state: ComparativeState, memberCount: number | null): number | null {
  if (state !== "available") return null;
  return memberCount ?? null;
}

export function CoverageStateTag({ state }: { state: ComparativeState }) {
  const { t } = useTranslation();
  const tone = STATE_TONE[state] ?? STATE_TONE.no_data;
  const Icon = tone.icon;
  return (
    <Tag color={tone.tag} className="m-0 gap-1" data-coverage-state={state}>
      <Icon className="size-3" aria-hidden />
      {t(coverageLabelKey(state))}
    </Tag>
  );
}

export function CoverageTable({ coverage }: { coverage: SpeciesCoverage[] }) {
  const { t } = useTranslation();
  const columns: TableColumnsType<SpeciesCoverage> = [
    { title: t("comparative.coverage.species"), dataIndex: "species", key: "species" },
    {
      title: t("comparative.coverage.state"),
      key: "state",
      render: (_, row) => <CoverageStateTag state={row.state} />,
    },
    {
      title: t("comparative.coverage.members"),
      key: "member_count",
      align: "right",
      render: (_, row) => {
        const count = coverageCount(row.state, row.member_count);
        // A dash, not a zero: the cell must not read as "measured, none found".
        return count === null ? (
          <span className="text-muted-foreground" data-testid={`coverage-count-${row.species}`}>
            —
          </span>
        ) : (
          <span className="font-mono tabular-nums" data-testid={`coverage-count-${row.species}`}>
            {count.toLocaleString("en-US")}
          </span>
        );
      },
    },
  ];

  if (coverage.length === 0) {
    return <Empty description={t("comparative.list.empty")} className="py-8" />;
  }

  return (
    <Table<SpeciesCoverage>
      rowKey="species"
      size="small"
      columns={columns}
      dataSource={coverage}
      pagination={false}
      data-testid="comparative-coverage"
    />
  );
}

/**
 * Banner for a scope the source does not cover.
 *
 * Used where the family's own state (not a per-species row) is the thing being
 * reported: `no_data` and `not_imported` must not collapse into one message.
 */
export function ComparativeStateNotice({
  state,
  className,
}: {
  state: ComparativeState;
  className?: string;
}) {
  const { t } = useTranslation();
  if (state === "available") return null;
  // Not-imported is amber (`impact-moderate`), no-data is neutral grey. Two
  // different claims, two different colours — sharing one banner would erase
  // the distinction the contract insists on.
  const tone =
    state === "not_imported"
      ? "border-impact-moderate/40 bg-impact-moderate/10"
      : "border-border bg-muted text-muted-foreground";
  const hintKey =
    state === "not_imported" ? "comparative.coverage.not_importedHint" : "comparative.coverage.no_dataHint";
  return (
    <Card className={cn(tone, className)} data-comparative-state={state}>
      <p className="text-sm font-medium">{t(coverageLabelKey(state))}</p>
      <p className="mt-1 text-xs opacity-80">{t(hintKey)}</p>
    </Card>
  );
}
