/**
 * SeqFetch tool — batch gene FASTA extraction, or single region extraction.
 *
 * Two modes (mutually exclusive, matching POST /api/v1/tools/seqfetch):
 * - "genes": up to 200 gene IDs → genomic-span FASTA for each found gene.
 * - "region": assembly + `chr:start-end` interval → single FASTA record.
 *
 * Results larger than 10 MiB come back as a pre-signed download_url instead
 * of inline text.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { DeploymentUnitOutlined, CaretRightOutlined, DownloadOutlined, LoadingOutlined, RedoOutlined } from "@ant-design/icons";
import { Breadcrumb, Button, Card, Empty, Input, Result, Select, Tabs, Tag, Typography } from "@/lib/antd";
import { useToast } from "../../lib/toast";
import { queryKeys } from "../../lib/query-keys";
import { seqFetchGenes, seqFetchRegion, getAssemblies, type SeqFetchResponse } from "./api";

export const Route = createFileRoute("/tools/seqfetch")({
  component: SeqFetchComponent,
});

type Mode = "genes" | "region";

/** Cap for the inline FASTA preview — beyond this only the tail is shown. */
const PREVIEW_MAX_LINES = 120;

function parseGenes(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;]+/)
        .map((g) => g.trim())
        .filter(Boolean),
    ),
  ];
}

function SeqFetchComponent() {
  return <SeqFetchInner />;
}

function SeqFetchInner() {
  const { t } = useTranslation();
  const { success, error } = useToast();

  const [mode, setMode] = React.useState<Mode>("genes");
  const [genesRaw, setGenesRaw] = React.useState("");
  const [assembly, setAssembly] = React.useState("");
  const [chromosome, setChromosome] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<SeqFetchResponse | null>(null);

  const assembliesQuery = useQuery({
    queryKey: queryKeys.assemblies.all(),
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });

  // Preselect the default assembly when the list arrives.
  React.useEffect(() => {
    if (assembly) return;
    const list = assembliesQuery.data ?? [];
    const def = list.find((a) => a.is_default) ?? list[0];
    if (def) setAssembly(def.name);
  }, [assembliesQuery.data, assembly]);

  const fetchMutation = useMutation({
    mutationFn: () => {
      if (mode === "genes") {
        return seqFetchGenes(parseGenes(genesRaw));
      }
      return seqFetchRegion(assembly, `${chromosome}:${start}-${end}`);
    },
    onSuccess: (data) => {
      setResult(data);
      success(
        t("tools.seqfetch.toastDone"),
        t("tools.seqfetch.toastDoneDesc", { count: data.count }),
      );
    },
    onError: (err: Error) => {
      error(t("tools.seqfetch.toastFailed"), err.message);
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (mode === "genes") {
      const genes = parseGenes(genesRaw);
      if (genes.length === 0) errs.genes = t("tools.seqfetch.errorGenesEmpty");
      else if (genes.length > 200) errs.genes = t("tools.seqfetch.errorGenesMax");
    } else {
      if (!assembly) errs.assembly = t("tools.seqfetch.errorAssembly");
      const s = Number(start);
      const en = Number(end);
      if (!chromosome.trim()) errs.chromosome = t("tools.seqfetch.errorChromosome");
      if (!Number.isInteger(s) || s < 1) errs.start = t("tools.seqfetch.errorCoord");
      if (!Number.isInteger(en) || en < s) errs.end = t("tools.seqfetch.errorCoord");
    }
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;
    setResult(null);
    fetchMutation.mutate();
  };

  const onClear = () => {
    setGenesRaw("");
    setChromosome("");
    setStart("");
    setEnd("");
    setFieldErrors({});
    setResult(null);
    fetchMutation.reset();
  };

  const missing = result?.missing ?? [];

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.seqfetch.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card shadow-sm">
            <DeploymentUnitOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={2} style={{ margin: 0 }}>
              {t("tools.seqfetch.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.seqfetch.subtitle")}
            </Typography.Paragraph>
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card
          title={
            <>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {t("tools.seqfetch.formTitle")}
              </Typography.Title>
              <Typography.Text type="secondary">{t("tools.seqfetch.formDesc")}</Typography.Text>
            </>
          }
        >
          <form onSubmit={onSubmit} className="grid gap-5">
            <Tabs
              activeKey={mode}
              onChange={(key) => {
                setMode(key as Mode);
                setFieldErrors({});
              }}
              items={[
                {
                  key: "genes",
                  label: t("tools.seqfetch.modeGenes"),
                  children: (
                    <div className="grid gap-2">
                      <label htmlFor="sf-genes" className="text-sm font-medium">
                        {t("tools.seqfetch.genesLabel")}
                      </label>
                      <Input.TextArea
                        id="sf-genes"
                        value={genesRaw}
                        onChange={(e) => setGenesRaw(e.target.value)}
                        placeholder={t("tools.seqfetch.genesPlaceholder")}
                        className="min-h-[150px] font-mono text-sm"
                        aria-invalid={!!fieldErrors.genes}
                      />
                      <p className="text-xs text-muted-foreground">{t("tools.seqfetch.genesHint")}</p>
                      {fieldErrors.genes ? (
                        <p className="text-xs text-destructive">{fieldErrors.genes}</p>
                      ) : null}
                    </div>
                  ),
                },
                {
                  key: "region",
                  label: t("tools.seqfetch.modeRegion"),
                  children: (
                    <div className="grid gap-4">
                      <div className="grid gap-2">
                        <label htmlFor="sf-assembly" className="text-sm font-medium">
                          {t("tools.seqfetch.assemblyLabel")}
                        </label>
                        <Select
                          id="sf-assembly"
                          value={assembly || undefined}
                          onChange={setAssembly}
                          placeholder={t("tools.seqfetch.assemblyPlaceholder")}
                          options={
                            (
                              assembliesQuery.isLoading
                                ? [{ value: "__loading__", label: t("common.loading"), disabled: true }]
                                : (assembliesQuery.data ?? []).map((a) => ({
                                    value: a.name,
                                    label: a.is_default ? `${a.name} · ${t("tools.seqfetch.default")}` : a.name,
                                  }))
                            ) as { value: string; label: string; disabled?: boolean }[]
                          }
                        />
                        {fieldErrors.assembly ? (
                          <p className="text-xs text-destructive">{fieldErrors.assembly}</p>
                        ) : null}
                      </div>

                      <div className="grid gap-4 sm:grid-cols-[1fr_auto_auto] sm:items-end">
                        <div className="grid gap-2">
                          <label htmlFor="sf-chr" className="text-sm font-medium">
                            {t("tools.seqfetch.chromosomeLabel")}
                          </label>
                          <Input
                            id="sf-chr"
                            value={chromosome}
                            onChange={(e) => setChromosome(e.target.value)}
                            placeholder="chr1"
                            className="font-mono"
                            aria-invalid={!!fieldErrors.chromosome}
                          />
                          {fieldErrors.chromosome ? (
                            <p className="text-xs text-destructive">{fieldErrors.chromosome}</p>
                          ) : null}
                        </div>
                        <div className="grid gap-2">
                          <label htmlFor="sf-start" className="text-sm font-medium">
                            {t("tools.seqfetch.startLabel")}
                          </label>
                          <Input
                            id="sf-start"
                            type="number"
                            min={1}
                            value={start}
                            onChange={(e) => setStart(e.target.value)}
                            className="font-mono"
                            aria-invalid={!!fieldErrors.start}
                          />
                          {fieldErrors.start ? (
                            <p className="text-xs text-destructive">{fieldErrors.start}</p>
                          ) : null}
                        </div>
                        <div className="grid gap-2">
                          <label htmlFor="sf-end" className="text-sm font-medium">
                            {t("tools.seqfetch.endLabel")}
                          </label>
                          <Input
                            id="sf-end"
                            type="number"
                            min={1}
                            value={end}
                            onChange={(e) => setEnd(e.target.value)}
                            className="font-mono"
                            aria-invalid={!!fieldErrors.end}
                          />
                          {fieldErrors.end ? (
                            <p className="text-xs text-destructive">{fieldErrors.end}</p>
                          ) : null}
                        </div>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {t("tools.seqfetch.regionHint", { region: `${chromosome || "chr1"}:${start || "1000"}-${end || "2000"}` })}
                      </p>
                    </div>
                  ),
                },
              ]}
            />

            <div className="flex flex-wrap gap-2">
              <Button type="primary" htmlType="submit" disabled={fetchMutation.isPending}>
                {fetchMutation.isPending ? (
                  <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                ) : (
                  <CaretRightOutlined className="size-4" aria-hidden />
                )}
                {t("tools.seqfetch.submit")}
              </Button>
              <Button htmlType="button" onClick={onClear}>
                <RedoOutlined className="size-4" aria-hidden />
                {t("common.clear")}
              </Button>
            </div>
          </form>
        </Card>

        <div className="grid gap-6">
          {fetchMutation.isError ? (
            <Result
              status="error"
              title={t("tools.seqfetch.errorTitle")}
              subTitle={(fetchMutation.error as Error).message}
              extra={
                <Button type="primary" onClick={() => fetchMutation.mutate()}>
                  {t("common.retry")}
                </Button>
              }
            />
          ) : null}

          {!result && !fetchMutation.isError ? (
            <Card>
              <Empty
                description={
                  <>
                    <p className="font-medium">{t("tools.seqfetch.emptyTitle")}</p>
                    <p className="text-sm text-muted-foreground">{t("tools.seqfetch.emptyDesc")}</p>
                  </>
                }
              />
            </Card>
          ) : null}

          {result ? (
            <Card
              title={
                <>
                  <Typography.Title level={5} style={{ margin: 0 }}>
                    <span className="flex flex-wrap items-center gap-2">
                      {t("tools.seqfetch.resultTitle")}
                      <Tag>{t("tools.seqfetch.countLabel", { count: result.count })}</Tag>
                      {result.truncated ? <Tag>{t("tools.seqfetch.truncated")}</Tag> : null}
                    </span>
                  </Typography.Title>
                  <Typography.Text type="secondary">{t("tools.seqfetch.resultDesc")}</Typography.Text>
                </>
              }
            >
              <div className="grid gap-4">
                {result.sequence ? (
                  <FastaPreview
                    fasta={result.sequence}
                    maxLines={PREVIEW_MAX_LINES}
                    truncatedLabel={t("tools.seqfetch.previewTruncated", {
                      shown: PREVIEW_MAX_LINES,
                      total: result.sequence.split("\n").length,
                    })}
                  />
                ) : result.download_url ? (
                  <Empty
                    description={
                      <>
                        <p className="font-medium">{t("tools.seqfetch.largeTitle")}</p>
                        <p className="text-sm text-muted-foreground">{t("tools.seqfetch.largeDesc")}</p>
                      </>
                    }
                  >
                    <a href={result.download_url} download>
                      <Button icon={<DownloadOutlined aria-hidden />}>{t("tools.seqfetch.download")}</Button>
                    </a>
                  </Empty>
                ) : null}

                {result.download_url ? (
                  <a href={result.download_url} download>
                    <Button icon={<DownloadOutlined aria-hidden />} className="w-full">
                      {t("tools.seqfetch.downloadFasta")}
                    </Button>
                  </a>
                ) : null}

                {missing.length > 0 ? (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                    <p className="text-sm font-medium">{t("tools.seqfetch.missingTitle")}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {missing.map((g) => (
                        <Tag key={g} className="font-mono text-[11px]">
                          {g}
                        </Tag>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/**
 * FASTA text preview — monospace block, line-count truncated with a note.
 */
function FastaPreview({
  fasta,
  maxLines,
  truncatedLabel,
}: {
  fasta: string;
  maxLines: number;
  truncatedLabel: string;
}) {
  const lines = fasta.split("\n");
  const over = lines.length > maxLines;
  const shown = over ? lines.slice(0, maxLines) : lines;
  return (
    <div className="grid gap-2">
      <pre
        className="max-h-[420px] overflow-auto rounded-xl border border-border bg-muted/30 p-4 font-mono text-xs leading-relaxed"
        data-testid="seqfetch-fasta-preview"
      >
        {shown.join("\n")}
        {over ? "\n…" : ""}
      </pre>
      {over ? <p className="text-xs text-muted-foreground">{truncatedLabel}</p> : null}
    </div>
  );
}
