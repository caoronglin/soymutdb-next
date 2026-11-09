/**
 * Sequence toolkit — the Rust bio-core endpoints as a browser tool.
 *
 * These operations share one page because they share one input box. Splitting
 * them into separate routes would make the user paste the same sequence again
 * and again, and the input is the expensive part.
 *
 * Three deliberate restraints, each of which the page states out loud:
 *
 * 1. **Nothing here is BLAST.** These operations only see text the caller
 *    supplied — no assembly, no release, no genome record — so no genomic
 *    coordinate or browser link is ever produced. An alignment score is a raw
 *    DP score, not an E-value.
 * 2. **An ORF is a hypothesis**, not a gene model and not evidence of
 *    expression.
 * 3. **A rejected request names what to fix.** The kernel's own code
 *    (invalid character / budget exceeded / unimplemented genetic code) is
 *    surfaced, because "something went wrong" tells the user nothing.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { LoadingOutlined, ThunderboltOutlined } from "@ant-design/icons";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Empty,
  Input,
  Segmented,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
} from "@/lib/antd";
import {
  countSequenceCharacters,
  isKernelUnavailable,
  sequenceApi,
  sequenceKernelCode,
  type AlignmentMode,
  type FormatInspectResponse,
  type KmerResponse,
  type MatchHit,
  type OrfResponse,
  type ReverseComplementResponse,
  type SequenceAlignResponse,
  type SequenceCapabilities,
  type SequenceFormat,
  type SequenceMatchResponse,
  type SequenceStatsResponse,
  type TranslateResponse,
} from "@soymutdb/api-client";
import { useSiteContent } from "../../lib/site-content-react";

export const Route = createFileRoute("/tools/sequence")({
  component: SequenceToolComponent,
});

const OPERATIONS = [
  "reverseComplement",
  "match",
  "stats",
  "translate",
  "kmers",
  "orfs",
  "align",
  "inspect",
] as const;

type Operation = (typeof OPERATIONS)[number];

/** Which operations need a second sequence box. */
const NEEDS_SECOND_INPUT: ReadonlySet<Operation> = new Set<Operation>(["match", "align"]);

const INSPECT_FORMATS: SequenceFormat[] = ["fasta", "fastq", "bed"];

type SequenceResult =
  | { op: "reverseComplement"; payload: ReverseComplementResponse }
  | { op: "match"; payload: SequenceMatchResponse }
  | { op: "stats"; payload: SequenceStatsResponse }
  | { op: "translate"; payload: TranslateResponse }
  | { op: "kmers"; payload: KmerResponse }
  | { op: "orfs"; payload: OrfResponse }
  | { op: "align"; payload: SequenceAlignResponse }
  | { op: "inspect"; payload: FormatInspectResponse };

function SequenceToolComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();

  const [operation, setOperation] = React.useState<Operation>("reverseComplement");
  const [sequence, setSequence] = React.useState("");
  const [second, setSecond] = React.useState("");
  const [pattern, setPattern] = React.useState("");
  const [matchMode, setMatchMode] = React.useState<"exact" | "approximate">("exact");
  const [alignMode, setAlignMode] = React.useState<AlignmentMode>("local");
  const [k, setK] = React.useState(4);
  const [geneticCode, setGeneticCode] = React.useState(1);
  const [frame, setFrame] = React.useState(0);
  const [minOrfLen, setMinOrfLen] = React.useState(90);
  const [inspectFormat, setInspectFormat] = React.useState<SequenceFormat>("fasta");
  const [result, setResult] = React.useState<SequenceResult | null>(null);

  const capabilitiesQuery = useQuery({
    queryKey: ["tools", "sequence", "capabilities"],
    queryFn: () => sequenceApi.capabilities(),
    staleTime: 5 * 60_000,
  });

  const capabilities: SequenceCapabilities | undefined = capabilitiesQuery.data;
  const kernelAvailable = capabilities?.available ?? true;

  const mutation = useMutation({
    mutationFn: async (): Promise<SequenceResult> => {
      switch (operation) {
        case "reverseComplement":
          return { op: operation, payload: await sequenceApi.reverseComplement({ sequence }) };
        case "match":
          return {
            op: operation,
            payload: await sequenceApi.match({
              pattern: pattern.trim(),
              target: { kind: "inline", sequence },
              mode: matchMode,
              max_edits: matchMode === "approximate" ? 1 : 0,
            }),
          };
        case "stats":
          return { op: operation, payload: await sequenceApi.stats({ sequence }) };
        case "translate":
          return {
            op: operation,
            payload: await sequenceApi.translate({ sequence, genetic_code_id: geneticCode, frame }),
          };
        case "kmers":
          return { op: operation, payload: await sequenceApi.kmers({ sequence, k }) };
        case "orfs":
          return { op: operation, payload: await sequenceApi.orfs({ sequence, min_len: minOrfLen }) };
        case "align":
          return { op: operation, payload: await sequenceApi.align({ query: sequence, target: second, mode: alignMode }) };
        case "inspect":
          return {
            op: operation,
            payload: await sequenceApi.inspect(inspectFormat, toBase64(sequence)),
          };
      }
    },
    onSuccess: (payload) => setResult(payload),
    onError: () => setResult(null),
  });

  const kernelCode = sequenceKernelCode(mutation.error);
  const unavailable = isKernelUnavailable(mutation.error);

  const residueCount = countSequenceCharacters(sequence);
  const maxInline = capabilities?.max_inline_sequence ?? 1_048_576;
  const overBudget = residueCount > maxInline;

  const missingInput =
    sequence.trim() === "" ||
    (NEEDS_SECOND_INPUT.has(operation) && second.trim() === "") ||
    (operation === "match" && pattern.trim() === "");

  /** Why the Run button is disabled, in the user's words. Only the first applies. */
  let blockReason: string | null = null;
  if (missingInput) blockReason = t("tools.sequence.runDisabled");
  else if (overBudget) blockReason = t("tools.sequence.error.SEQUENCE_TOO_LONG");
  else if (!kernelAvailable) blockReason = t("tools.sequence.unavailable");

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/">{get("nav.home", t("nav.home"))}</Link> },
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.sequence.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">
            <ThunderboltOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={2} style={{ margin: 0 }}>
              {t("tools.sequence.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.sequence.subtitle")}
            </Typography.Paragraph>
          </div>
        </div>
      </header>

      {capabilitiesQuery.isLoading ? (
        <Skeleton active paragraph={{ rows: 3 }} className="mt-8" />
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <Card
            title={t("tools.sequence.inputTitle")}
            extra={
              capabilities ? (
                <Tag color={kernelAvailable ? "green" : "orange"}>
                  {kernelAvailable
                    ? t("tools.sequence.kernelReady", { version: capabilities.engine_version ?? "—" })
                    : t("tools.sequence.unavailableShort")}
                </Tag>
              ) : null
            }
          >
            <div className="flex flex-col gap-4">
              <Segmented
                aria-label={t("tools.sequence.operationAria")}
                block
                value={operation}
                onChange={(value) => {
                  setOperation(value as Operation);
                  setResult(null);
                  mutation.reset();
                }}
                options={OPERATIONS.map((op) => ({
                  value: op,
                  label: t(`tools.sequence.op.${op}`),
                }))}
              />

              {!kernelAvailable ? (
                <Alert
                  type="warning"
                  showIcon
                  title={t("tools.sequence.unavailableTitle")}
                  description={
                    capabilities?.reason
                      ? t("tools.sequence.unavailableReason", { reason: capabilities.reason })
                      : t("tools.sequence.unavailableDesc")
                  }
                />
              ) : null}

              <div>
                <Typography.Text strong>
                  {operation === "align"
                    ? t("tools.sequence.queryLabel")
                    : operation === "match"
                      ? t("tools.sequence.targetLabel")
                      : t("tools.sequence.sequenceLabel")}
                </Typography.Text>
                <Input.TextArea
                  className="mt-2"
                  value={sequence}
                  onChange={(event) => setSequence(event.target.value)}
                  placeholder={
                    operation === "inspect"
                      ? t("tools.sequence.inspectPlaceholder", { format: inspectFormat.toUpperCase() })
                      : t("tools.sequence.sequencePlaceholder")
                  }
                  autoSize={{ minRows: 5, maxRows: 12 }}
                  spellCheck={false}
                />
                <Typography.Text type="secondary" className="mt-1.5 block text-xs">
                  {operation === "inspect"
                    ? t("tools.sequence.inspectHint", { max: maxInline })
                    : t("tools.sequence.sequenceHint", { count: residueCount, max: maxInline })}
                </Typography.Text>
              </div>

              {operation === "match" ? (
                <div>
                  <Typography.Text strong>{t("tools.sequence.patternLabel")}</Typography.Text>
                  <Input
                    className="mt-2"
                    value={pattern}
                    onChange={(event) => setPattern(event.target.value)}
                    placeholder={t("tools.sequence.patternPlaceholder")}
                    spellCheck={false}
                  />
                  <Segmented
                    className="mt-3"
                    value={matchMode}
                    onChange={(value) => setMatchMode(value as "exact" | "approximate")}
                    options={[
                      { value: "exact", label: t("tools.sequence.matchExact") },
                      { value: "approximate", label: t("tools.sequence.matchApproximate") },
                    ]}
                  />
                </div>
              ) : null}

              {operation === "align" ? (
                <div>
                  <Typography.Text strong>{t("tools.sequence.targetLabel")}</Typography.Text>
                  <Input.TextArea
                    className="mt-2"
                    value={second}
                    onChange={(event) => setSecond(event.target.value)}
                    placeholder={t("tools.sequence.sequencePlaceholder")}
                    autoSize={{ minRows: 4, maxRows: 10 }}
                    spellCheck={false}
                  />
                  <Segmented
                    className="mt-3"
                    value={alignMode}
                    onChange={(value) => setAlignMode(value as AlignmentMode)}
                    options={[
                      { value: "local", label: t("tools.sequence.alignLocal") },
                      { value: "global", label: t("tools.sequence.alignGlobal") },
                      { value: "semiglobal", label: t("tools.sequence.alignSemiglobal") },
                    ]}
                  />
                </div>
              ) : null}

              {operation === "translate" ? (
                <div className="flex flex-wrap items-end gap-4">
                  <label className="flex flex-col gap-1.5">
                    <Typography.Text strong>{t("tools.sequence.geneticCodeLabel")}</Typography.Text>
                    <Select
                      style={{ minWidth: 220 }}
                      value={geneticCode}
                      onChange={setGeneticCode}
                      options={(capabilities?.genetic_codes ?? [1]).map((id) => ({
                        value: id,
                        label: t("tools.sequence.geneticCodeStandard", { id }),
                      }))}
                    />
                  </label>
                  <label className="flex flex-col gap-1.5">
                    <Typography.Text strong>{t("tools.sequence.frameLabel")}</Typography.Text>
                    <Select
                      style={{ minWidth: 120 }}
                      value={frame}
                      onChange={setFrame}
                      options={[0, 1, 2].map((value) => ({
                        value,
                        label: t("tools.sequence.frameOption", { frame: value }),
                      }))}
                    />
                  </label>
                </div>
              ) : null}

              {operation === "kmers" ? (
                <div className="flex flex-wrap items-end gap-4">
                  <label className="flex flex-col gap-1.5">
                    <Typography.Text strong>{t("tools.sequence.kLabel")}</Typography.Text>
                    <Select
                      style={{ minWidth: 120 }}
                      value={k}
                      onChange={setK}
                      options={rangeOf(capabilities?.k_range ?? [1, 32]).map((value) => ({
                        value,
                        label: String(value),
                      }))}
                    />
                  </label>
                  <Typography.Text type="secondary" className="pb-1 text-xs">
                    {t("tools.sequence.kHint", {
                      min: capabilities?.k_range?.[0] ?? 1,
                      max: capabilities?.k_range?.[1] ?? 32,
                    })}
                  </Typography.Text>
                </div>
              ) : null}

              {operation === "orfs" ? (
                <label className="flex flex-col gap-1.5">
                  <Typography.Text strong>{t("tools.sequence.minOrfLabel")}</Typography.Text>
                  <Select
                    style={{ minWidth: 200 }}
                    value={minOrfLen}
                    onChange={setMinOrfLen}
                    options={[30, 60, 90, 150, 300].map((value) => ({
                      value,
                      label: t("tools.sequence.minOrfOption", { value }),
                    }))}
                  />
                </label>
              ) : null}

              {operation === "inspect" ? (
                <label className="flex flex-col gap-1.5">
                  <Typography.Text strong>{t("tools.sequence.inspectFormatLabel")}</Typography.Text>
                  <Segmented
                    value={inspectFormat}
                    onChange={(value) => setInspectFormat(value as SequenceFormat)}
                    options={INSPECT_FORMATS.map((fmt) => ({ value: fmt, label: fmt.toUpperCase() }))}
                  />
                </label>
              ) : null}

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="primary"
                  loading={mutation.isPending}
                  disabled={blockReason !== null}
                  onClick={() => mutation.mutate()}
                >
                  {mutation.isPending ? t("tools.sequence.running") : t("tools.sequence.run")}
                </Button>
                {blockReason ? (
                  <Typography.Text type="secondary" className="text-xs">
                    {blockReason}
                  </Typography.Text>
                ) : null}
              </div>
            </div>
          </Card>

          <Card title={t("tools.sequence.resultTitle")}>
            <ResultPanel
              result={result}
              pending={mutation.isPending}
              kernelCode={kernelCode}
              unavailable={unavailable}
              failed={mutation.isError}
              inspectFormat={inspectFormat}
            />
          </Card>
        </div>
      )}
    </div>
  );
}

function rangeOf(range: readonly number[]): number[] {
  const min = range[0] ?? 1;
  const max = Math.min(range[1] ?? 32, 32);
  const out: number[] = [];
  for (let value = min; value <= max; value += 1) out.push(value);
  return out;
}

/** Encode text as base64 without assuming a browser-only or node-only API. */
function toBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

interface ResultPanelProps {
  result: SequenceResult | null;
  pending: boolean;
  kernelCode: ReturnType<typeof sequenceKernelCode>;
  unavailable: boolean;
  /** The request failed, but not with a code the kernel produced. */
  failed: boolean;
  inspectFormat: SequenceFormat;
}

function ResultPanel({
  result,
  pending,
  kernelCode,
  unavailable,
  failed,
  inspectFormat,
}: ResultPanelProps) {
  const { t } = useTranslation();

  if (pending) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoadingOutlined aria-hidden /> {t("tools.sequence.running")}
      </div>
    );
  }

  if (unavailable) {
    return <Alert type="warning" showIcon title={t("tools.sequence.unavailableTitle")} description={t("tools.sequence.unavailableDesc")} />;
  }

  if (kernelCode) {
    return (
      <Alert
        type="error"
        showIcon
        title={t("tools.sequence.failedTitle")}
        description={
          <div className="flex flex-col gap-1">
            <span>{t(`tools.sequence.error.${kernelCode}`)}</span>
            <code className="text-xs opacity-70">{kernelCode}</code>
          </div>
        }
      />
    );
  }

  if (failed) {
    // Reached only when the failure carried no kernel code: a network error, a
    // rate limit, or the generic 500. Saying "enter a sequence" here would be a
    // lie about what happened.
    return (
      <Alert
        type="error"
        showIcon
        title={t("tools.sequence.failedTitle")}
        description={t("tools.sequence.error.unknown")}
      />
    );
  }

  if (!result) {
    return <Empty description={t("tools.sequence.emptyPrompt")} />;
  }

  switch (result.op) {
    case "reverseComplement": {
      const payload = result.payload;
      return (
        <div className="flex flex-col gap-2">
          <Typography.Text type="secondary" className="text-xs">
            {t("tools.sequence.revcompResultHint")}
          </Typography.Text>
          <pre className="overflow-x-auto rounded-lg border bg-muted/30 p-3 text-xs break-all whitespace-pre-wrap">
            {payload.sequence}
          </pre>
          <Typography.Text type="secondary" className="text-xs">
            {t("tools.sequence.resultLength", { length: payload.length })}
          </Typography.Text>
        </div>
      );
    }
    case "match": {
      const payload = result.payload;
      const columns = [
        { title: t("tools.sequence.colStart"), dataIndex: "start", width: 90 },
        { title: t("tools.sequence.colEnd"), dataIndex: "end", width: 90 },
        { title: t("tools.sequence.colStrand"), dataIndex: "strand", width: 80 },
        { title: t("tools.sequence.colEdits"), dataIndex: "edit_distance", width: 80 },
      ];
      return (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Tag>{t("tools.sequence.resultCount", { count: payload.count })}</Tag>
            <Tag>{payload.method}</Tag>
            <Tag>{payload.coordinate_system}</Tag>
          </div>
          {payload.limited ? <Alert type="info" showIcon title={t("tools.sequence.matchLimited")} /> : null}
          <Table<MatchHit>
            size="small"
            rowKey={(row) => `${row.start}-${row.end}-${row.strand}-${row.edit_distance}`}
            pagination={false}
            scroll={{ y: 340 }}
            columns={columns}
            dataSource={payload.matches}
            locale={{ emptyText: <Empty description={t("tools.sequence.noMatches")} /> }}
          />
        </div>
      );
    }
    case "stats": {
      const payload = result.payload;
      const rows: Array<[string, string]> = [
        [t("tools.sequence.statLength"), String(payload.length)],
        [t("tools.sequence.statGC"), payload.gc_fraction.toFixed(4)],
        [t("tools.sequence.statDenominator"), String(payload.denominator)],
        [t("tools.sequence.statAmbiguous"), String(payload.ambiguous_count)],
        [
          t("tools.sequence.statBases"),
          `${payload.a} / ${payload.c} / ${payload.g} / ${payload.t}`,
        ],
      ];
      return (
        <div className="flex flex-col gap-3">
          <dl className="grid grid-cols-1 gap-2 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-1.5">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-mono">{value}</dd>
              </div>
            ))}
          </dl>
          <Typography.Text type="secondary" className="text-xs">
            {t("tools.sequence.statDenominatorHint")}
          </Typography.Text>
        </div>
      );
    }
    case "translate": {
      const payload = result.payload;
      return (
        <div className="flex flex-col gap-2">
          <pre className="overflow-x-auto rounded-lg border bg-muted/30 p-3 text-xs break-all whitespace-pre-wrap">
            {payload.protein}
          </pre>
          <div className="flex flex-wrap gap-2">
            <Tag>{t("tools.sequence.translateCodons", { count: payload.codons })}</Tag>
            <Tag>{t("tools.sequence.translateTrailing", { count: payload.trailing_bases })}</Tag>
            <Tag>{t("tools.sequence.translateTable", { id: payload.genetic_code_id })}</Tag>
            <Tag>{t("tools.sequence.translateFrame", { frame: payload.frame })}</Tag>
          </div>
          {payload.warnings.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              title={t("tools.sequence.translateWarnings")}
              description={payload.warnings.join("; ")}
            />
          ) : null}
        </div>
      );
    }
    case "kmers": {
      const payload = result.payload;
      return (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Tag>{t("tools.sequence.kmerK", { k: payload.k })}</Tag>
            <Tag>{payload.canonical ? t("tools.sequence.kmerCanonical") : t("tools.sequence.kmerRaw")}</Tag>
            <Tag>{t("tools.sequence.kmerTotal", { count: payload.total_windows })}</Tag>
            <Tag>{t("tools.sequence.kmerValid", { count: payload.valid_windows })}</Tag>
            <Tag>{t("tools.sequence.kmerSkipped", { count: payload.skipped_windows })}</Tag>
            <Tag>{t("tools.sequence.kmerDistinct", { count: payload.distinct_kmers })}</Tag>
          </div>
          {payload.limited ? <Alert type="info" showIcon title={t("tools.sequence.kmerLimited")} /> : null}
          <Table
            size="small"
            rowKey={(row) => row.kmer}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            scroll={{ y: 300 }}
            columns={[
              { title: t("tools.sequence.colKmer"), dataIndex: "kmer" },
              { title: t("tools.sequence.colCount"), dataIndex: "count", width: 110 },
            ]}
            dataSource={payload.items}
            locale={{ emptyText: <Empty description={t("tools.sequence.kmerEmpty")} /> }}
          />
        </div>
      );
    }
    case "orfs": {
      const payload = result.payload;
      return (
        <div className="flex flex-col gap-3">
          <Alert type="info" showIcon title={t("tools.sequence.orfCaveat")} />
          <Table
            size="small"
            rowKey={(row) => `${row.strand}-${row.frame}-${row.start}-${row.end}`}
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            scroll={{ y: 300 }}
            columns={[
              { title: t("tools.sequence.colStart"), dataIndex: "start", width: 90 },
              { title: t("tools.sequence.colEnd"), dataIndex: "end", width: 90 },
              { title: t("tools.sequence.colStrand"), dataIndex: "strand", width: 80 },
              { title: t("tools.sequence.colFrame"), dataIndex: "frame", width: 80 },
            ]}
            dataSource={payload.candidates}
            locale={{ emptyText: <Empty description={t("tools.sequence.noOrfs")} /> }}
          />
        </div>
      );
    }
    case "align": {
      const payload = result.payload;
      const rows: Array<[string, string]> = [
        [t("tools.sequence.alignScore"), String(payload.score)],
        [t("tools.sequence.alignIdentity"), `${(payload.identity * 100).toFixed(2)}%`],
        [t("tools.sequence.alignQueryRange"), `${payload.query_range[0]}–${payload.query_range[1]}`],
        [t("tools.sequence.alignTargetRange"), `${payload.target_range[0]}–${payload.target_range[1]}`],
        [t("tools.sequence.colCigar"), payload.cigar],
        [t("tools.sequence.alignModeLabel"), payload.mode],
      ];
      return (
        <div className="flex flex-col gap-3">
          <Alert type="info" showIcon title={t("tools.sequence.alignCaveat")} />
          <dl className="grid grid-cols-1 gap-2 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-1.5">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-mono break-all text-right">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      );
    }
    case "inspect": {
      const payload = result.payload;
      return (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Tag>{payload.fmt.toUpperCase()}</Tag>
            <Tag color={payload.valid ? "green" : "red"}>
              {payload.valid ? t("tools.sequence.inspectValid") : t("tools.sequence.inspectInvalid")}
            </Tag>
            <Tag>{t("tools.sequence.inspectRecords", { count: payload.record_count })}</Tag>
            {payload.truncated ? <Tag color="orange">{t("tools.sequence.inspectTruncated")}</Tag> : null}
          </div>
          <pre className="max-h-72 overflow-auto rounded-lg border bg-muted/30 p-3 text-xs">
            {JSON.stringify(payload.records, null, 2)}
          </pre>
          <Typography.Text type="secondary" className="text-xs">
            {t("tools.sequence.inspectFormatHint", { format: inspectFormat.toUpperCase() })}
          </Typography.Text>
        </div>
      );
    }
  }
}
