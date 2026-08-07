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
import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Dna, Play, Download, Loader2, RotateCcw } from "lucide-react";
import {
  PageHeader,
  Card,
  CardHeader,
  CardContent,
  CardTitle,
  CardDescription,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Label,
  Textarea,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Button,
  Badge,
  ErrorState,
  EmptyState,
  ToastProvider,
  useToast,
} from "@soymutdb/ui";
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
  return (
    <ToastProvider>
      <SeqFetchInner />
    </ToastProvider>
  );
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
    queryKey: ["assemblies"],
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
      <PageHeader
        icon={Dna}
        title={t("tools.seqfetch.title")}
        description={t("tools.seqfetch.subtitle")}
        breadcrumb={[
          { label: t("tools.title"), href: "/tools" },
          { label: t("tools.seqfetch.title") },
        ]}
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t("tools.seqfetch.formTitle")}</CardTitle>
            <CardDescription>{t("tools.seqfetch.formDesc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="grid gap-5">
              <Tabs
                value={mode}
                onValueChange={(v) => {
                  setMode(v as Mode);
                  setFieldErrors({});
                }}
              >
                <TabsList>
                  <TabsTrigger value="genes">{t("tools.seqfetch.modeGenes")}</TabsTrigger>
                  <TabsTrigger value="region">{t("tools.seqfetch.modeRegion")}</TabsTrigger>
                </TabsList>

                <TabsContent value="genes" className="grid gap-2">
                  <Label htmlFor="sf-genes">{t("tools.seqfetch.genesLabel")}</Label>
                  <Textarea
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
                </TabsContent>

                <TabsContent value="region" className="grid gap-4">
                  <div className="grid gap-2">
                    <Label htmlFor="sf-assembly">{t("tools.seqfetch.assemblyLabel")}</Label>
                    <Select value={assembly} onValueChange={setAssembly}>
                      <SelectTrigger id="sf-assembly">
                        <SelectValue placeholder={t("tools.seqfetch.assemblyPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        {assembliesQuery.isLoading ? (
                          <SelectItem value="__loading__" disabled>
                            {t("common.loading")}
                          </SelectItem>
                        ) : (
                          (assembliesQuery.data ?? []).map((a) => (
                            <SelectItem key={a.id} value={a.name}>
                              {a.name}
                              {a.is_default ? ` · ${t("tools.seqfetch.default")}` : ""}
                            </SelectItem>
                          ))
                        )}
                      </SelectContent>
                    </Select>
                    {fieldErrors.assembly ? (
                      <p className="text-xs text-destructive">{fieldErrors.assembly}</p>
                    ) : null}
                  </div>

                  <div className="grid gap-4 sm:grid-cols-[1fr_auto_auto] sm:items-end">
                    <div className="grid gap-2">
                      <Label htmlFor="sf-chr">{t("tools.seqfetch.chromosomeLabel")}</Label>
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
                      <Label htmlFor="sf-start">{t("tools.seqfetch.startLabel")}</Label>
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
                      <Label htmlFor="sf-end">{t("tools.seqfetch.endLabel")}</Label>
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
                </TabsContent>
              </Tabs>

              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={fetchMutation.isPending}>
                  {fetchMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <Play className="size-4" aria-hidden />
                  )}
                  {t("tools.seqfetch.submit")}
                </Button>
                <Button type="button" variant="outline" onClick={onClear}>
                  <RotateCcw className="size-4" aria-hidden />
                  {t("common.clear")}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div className="grid gap-6">
          {fetchMutation.isError ? (
            <ErrorState
              title={t("tools.seqfetch.errorTitle")}
              message={(fetchMutation.error as Error).message}
              onRetry={() => fetchMutation.mutate()}
              retryLabel={t("common.retry")}
            />
          ) : null}

          {!result && !fetchMutation.isError ? (
            <Card>
              <CardContent className="p-6">
                <EmptyState
                  mode="empty"
                  title={t("tools.seqfetch.emptyTitle")}
                  description={t("tools.seqfetch.emptyDesc")}
                />
              </CardContent>
            </Card>
          ) : null}

          {result ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex flex-wrap items-center gap-2">
                  {t("tools.seqfetch.resultTitle")}
                  <Badge variant="secondary">{t("tools.seqfetch.countLabel", { count: result.count })}</Badge>
                  {result.truncated ? (
                    <Badge variant="secondary">{t("tools.seqfetch.truncated")}</Badge>
                  ) : null}
                </CardTitle>
                <CardDescription>{t("tools.seqfetch.resultDesc")}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4">
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
                  <EmptyState
                    mode="empty"
                    title={t("tools.seqfetch.largeTitle")}
                    description={t("tools.seqfetch.largeDesc")}
                    action={
                      <a href={result.download_url} download>
                        <Button>
                          <Download className="size-4" aria-hidden />
                          {t("tools.seqfetch.download")}
                        </Button>
                      </a>
                    }
                  />
                ) : null}

                {result.download_url ? (
                  <a href={result.download_url} download>
                    <Button variant="outline" className="w-full">
                      <Download className="size-4" aria-hidden />
                      {t("tools.seqfetch.downloadFasta")}
                    </Button>
                  </a>
                ) : null}

                {missing.length > 0 ? (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
                    <p className="text-sm font-medium">{t("tools.seqfetch.missingTitle")}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {missing.map((g) => (
                        <Badge key={g} variant="secondary" className="font-mono text-[11px]">
                          {g}
                        </Badge>
                      ))}
                    </div>
                  </div>
                ) : null}
              </CardContent>
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
