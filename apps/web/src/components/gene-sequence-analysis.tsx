/**
 * Per-molecule analysis actions for the gene sequence panel.
 *
 * The sequence tools are public, stateless utilities: they take text and answer
 * numbers or alignments. They were reachable only from their own page, so a
 * reader looking at a gene's residues had to copy the sequence out, navigate,
 * and paste it back. This component closes that gap: the actions appear on the
 * molecule you are already looking at.
 *
 * Which actions appear is decided by the molecule, not by a fixed menu:
 *
 * - a protein gets molecular weight / isoelectric point (ProtParam);
 * - a nucleotide sequence gets base composition, and Tm only when it is short
 *   enough to be a primer — a 50 kb genomic span has no meaningful Tm, and
 *   offering the button would invite a misleading number;
 * - reverse complement is offered for nucleotides, since that is the single
 *   most common "I need the other strand" step.
 *
 * Every call is explicit and on demand. Nothing here runs on mount: a gene page
 * must not fire four compute requests to render a tab.
 */
import * as React from "react";
import { Alert, Button, Descriptions, Space, Tag, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import {
  sequenceApi,
  type GeneSequenceAvailability,
  type MeltingTempResponse,
  type ProteinPropertiesResponse,
  type SequenceStatsResponse,
} from "@soymutdb/api-client";

/** Longest oligo the thermodynamic Tm tables describe as a primer. */
const MAX_PRIMER_LENGTH = 200;

type AnalysisResult =
  | { kind: "protein"; payload: ProteinPropertiesResponse }
  | { kind: "stats"; payload: SequenceStatsResponse }
  | { kind: "melting"; payload: MeltingTempResponse };

type AnalysisKind = AnalysisResult["kind"];

export interface SequenceAnalysisProps {
  molecule: GeneSequenceAvailability["molecule"];
  sequence: string;
}

export function SequenceAnalysis({ molecule, sequence }: SequenceAnalysisProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = React.useState<AnalysisKind | null>(null);
  const [result, setResult] = React.useState<AnalysisResult | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const isProtein = molecule === "protein";
  const isPrimerLength = sequence.length <= MAX_PRIMER_LENGTH;
  // The reverse complement of a protein is meaningless; the API rejects it.
  const canReverseComplement = !isProtein;

  const run = React.useCallback(
    async (kind: AnalysisKind, call: () => Promise<AnalysisResult["payload"]>) => {
      setBusy(kind);
      setError(null);
      try {
        const payload = await call();
        setResult({ kind, payload } as AnalysisResult);
      } catch (cause) {
        // The kernel's code rides in `details.code`; the outer code is always
        // `validation_error`, which does not tell the reader what to change.
        const message =
          cause instanceof Error && cause.message
            ? cause.message
            : t("genes.sequences.analysis.failed");
        setError(message);
      } finally {
        setBusy(null);
      }
    },
    [t],
  );

  const analyseProtein = () =>
    void run("protein", () => sequenceApi.proteinProperties({ protein: sequence }));
  const analyseStats = () =>
    void run("stats", () => sequenceApi.stats({ sequence }));
  const analyseMelting = () =>
    void run("melting", () => sequenceApi.meltingTemp({ sequence }));

  return (
    <div className="mt-2 space-y-2" data-testid={`sequence-analysis-${molecule}`}>
      <Space wrap size="small">
        {isProtein ? (
          <Button size="small" loading={busy === "protein"} onClick={analyseProtein}>
            {t("genes.sequences.analysis.proteinProperties")}
          </Button>
        ) : (
          <>
            <Button size="small" loading={busy === "stats"} onClick={analyseStats}>
              {t("genes.sequences.analysis.composition")}
            </Button>
            {isPrimerLength ? (
              <Button size="small" loading={busy === "melting"} onClick={analyseMelting}>
                {t("genes.sequences.analysis.meltingTemp")}
              </Button>
            ) : null}
            {canReverseComplement ? (
              <ReverseComplementAction sequence={sequence} />
            ) : null}
          </>
        )}
      </Space>

      {error ? <Alert type="error" showIcon title={error} /> : null}
      {result?.kind === "protein" ? <ProteinResult payload={result.payload} /> : null}
      {result?.kind === "stats" ? <StatsResult payload={result.payload} /> : null}
      {result?.kind === "melting" ? <MeltingResult payload={result.payload} /> : null}
    </div>
  );
}

function ReverseComplementAction({ sequence }: { sequence: string }) {
  const { t } = useTranslation();
  const [reversed, setReversed] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = await sequenceApi.reverseComplement({ sequence });
      setReversed(payload.sequence);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("genes.sequences.analysis.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Button size="small" loading={busy} onClick={() => void run()}>
        {t("genes.sequences.analysis.reverseComplement")}
      </Button>
      {error ? <Alert type="error" showIcon title={error} /> : null}
      {reversed ? (
        <div className="w-full">
          <Typography.Text type="secondary" className="text-xs">
            {t("genes.sequences.analysis.reverseComplementLabel")}
          </Typography.Text>
          <pre
            data-testid="sequence-reverse-complement"
            className="mt-1 max-h-40 overflow-auto break-all whitespace-pre-wrap font-mono text-xs"
          >
            {reversed}
          </pre>
        </div>
      ) : null}
    </>
  );
}

function ProteinResult({ payload }: { payload: ProteinPropertiesResponse }) {
  const { t } = useTranslation();
  return (
    <Descriptions
      size="small"
      column={2}
      bordered
      data-testid="sequence-protein-properties"
      items={[
        {
          key: "length",
          label: t("genes.sequences.analysis.residues"),
          children: payload.length.toLocaleString(),
        },
        {
          key: "mw",
          label: t("genes.sequences.analysis.molecularWeight"),
          children: payload.molecular_weight.toLocaleString(),
        },
        {
          key: "pi",
          label: t("genes.sequences.analysis.isoelectricPoint"),
          children: payload.isoelectric_point,
        },
        {
          key: "gravy",
          label: t("genes.sequences.analysis.gravy"),
          children: payload.gravy,
        },
        {
          key: "instability",
          label: t("genes.sequences.analysis.instabilityIndex"),
          children: payload.instability_index,
        },
        {
          key: "aromaticity",
          label: t("genes.sequences.analysis.aromaticity"),
          children: payload.aromaticity,
        },
      ]}
    />
  );
}

function StatsResult({ payload }: { payload: SequenceStatsResponse }) {
  const { t } = useTranslation();
  return (
    <Descriptions
      size="small"
      column={2}
      bordered
      data-testid="sequence-stats"
      items={[
        {
          key: "length",
          label: t("genes.sequences.analysis.bases"),
          children: payload.length.toLocaleString(),
        },
        {
          key: "gc",
          label: t("genes.sequences.analysis.gcFraction"),
          children: `${(payload.gc_fraction * 100).toFixed(2)}%`,
        },
        {
          key: "at",
          label: "A+T",
          children: payload.at_count.toLocaleString(),
        },
        {
          key: "ambiguous",
          label: t("genes.sequences.analysis.ambiguous"),
          children: payload.ambiguous_count.toLocaleString(),
        },
      ]}
    />
  );
}

function MeltingResult({ payload }: { payload: MeltingTempResponse }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="sequence-melting-temp">
      <Tag color="blue">{payload.melting_temp_c} °C</Tag>
      <Typography.Text type="secondary" className="text-xs">
        {t("genes.sequences.analysis.meltingMethod", { method: payload.method })} ·{" "}
        {t("genes.sequences.analysis.gcFraction")} {(payload.gc_fraction * 100).toFixed(1)}%
      </Typography.Text>
    </div>
  );
}
