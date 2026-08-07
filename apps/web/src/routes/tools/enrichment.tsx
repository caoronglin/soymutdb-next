/**
 * Enrichment tool — GO/KEGG hypergeometric enrichment for a gene list.
 *
 * POST /api/v1/tools/enrichment: terms filtered by raw p_threshold, sorted
 * by q-value ascending, capped at max_terms (default 20). Member genes per
 * term are capped at 20 server-side.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Network, Play, Loader2, RotateCcw } from "lucide-react";
import {
  PageHeader,
  Card,
  CardHeader,
  CardContent,
  CardTitle,
  CardDescription,
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
  DataTable,
  ErrorState,
  EmptyState,
  ToastProvider,
  useToast,
} from "@soymutdb/ui";
import { runEnrichment, type EnrichmentResponse } from "./api";

export const Route = createFileRoute("/tools/enrichment")({
  component: EnrichmentComponent,
});

const MAX_INPUT_GENES = 500;

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

function fmtP(v: number): string {
  if (v === 0) return "0";
  if (v < 0.001) return v.toExponential(2);
  return v.toFixed(4);
}

function EnrichmentComponent() {
  return (
    <ToastProvider>
      <EnrichmentInner />
    </ToastProvider>
  );
}

function EnrichmentInner() {
  const { t } = useTranslation();
  const { success, error } = useToast();

  const [genesRaw, setGenesRaw] = React.useState("");
  const [ontology, setOntology] = React.useState<"go" | "kegg">("go");
  const [pThreshold, setPThreshold] = React.useState("0.05");
  const [fieldErrors, setFieldErrors] = React.useState<Record<string, string>>({});
  const [result, setResult] = React.useState<EnrichmentResponse | null>(null);

  const enrichMutation = useMutation({
    mutationFn: () =>
      runEnrichment({
        genes: parseGenes(genesRaw),
        ontology,
        p_threshold: Number(pThreshold),
        max_terms: 50,
      }),
    onSuccess: (data) => {
      setResult(data);
      success(
        t("tools.enrichment.toastDone"),
        t("tools.enrichment.toastDoneDesc", { count: data.terms?.length ?? 0 }),
      );
    },
    onError: (err: Error) => {
      error(t("tools.enrichment.toastFailed"), err.message);
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs: Record<string, string> = {};
    const genes = parseGenes(genesRaw);
    if (genes.length === 0) errs.genes = t("tools.enrichment.errorGenesEmpty");
    else if (genes.length > MAX_INPUT_GENES) errs.genes = t("tools.enrichment.errorGenesMax");
    const p = Number(pThreshold);
    if (!Number.isFinite(p) || p <= 0 || p > 1) errs.p = t("tools.enrichment.errorP");
    setFieldErrors(errs);
    if (Object.keys(errs).length > 0) return;
    setResult(null);
    enrichMutation.mutate();
  };

  const onClear = () => {
    setGenesRaw("");
    setOntology("go");
    setPThreshold("0.05");
    setFieldErrors({});
    setResult(null);
    enrichMutation.reset();
  };

  const terms = result?.terms ?? [];

  return (
    <div className="container-prose section-rhythm">
      <PageHeader
        icon={Network}
        title={t("tools.enrichment.title")}
        description={t("tools.enrichment.subtitle")}
        breadcrumb={[
          { label: t("tools.title"), href: "/tools" },
          { label: t("tools.enrichment.title") },
        ]}
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t("tools.enrichment.formTitle")}</CardTitle>
            <CardDescription>{t("tools.enrichment.formDesc")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="grid gap-5">
              <div className="grid gap-2">
                <Label htmlFor="en-genes">{t("tools.enrichment.genesLabel")}</Label>
                <Textarea
                  id="en-genes"
                  value={genesRaw}
                  onChange={(e) => setGenesRaw(e.target.value)}
                  placeholder={t("tools.enrichment.genesPlaceholder")}
                  className="min-h-[150px] font-mono text-sm"
                  aria-invalid={!!fieldErrors.genes}
                />
                <p className="text-xs text-muted-foreground">{t("tools.enrichment.genesHint")}</p>
                {fieldErrors.genes ? (
                  <p className="text-xs text-destructive">{fieldErrors.genes}</p>
                ) : null}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="en-ontology">{t("tools.enrichment.ontologyLabel")}</Label>
                  <Select value={ontology} onValueChange={(v) => setOntology(v as "go" | "kegg")}>
                    <SelectTrigger id="en-ontology">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="go">GO</SelectItem>
                      <SelectItem value="kegg">KEGG</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="en-p">{t("tools.enrichment.pLabel")}</Label>
                  <Input
                    id="en-p"
                    type="number"
                    min={0.000001}
                    max={1}
                    step="0.01"
                    value={pThreshold}
                    onChange={(e) => setPThreshold(e.target.value)}
                    className="font-mono"
                    aria-invalid={!!fieldErrors.p}
                  />
                  {fieldErrors.p ? (
                    <p className="text-xs text-destructive">{fieldErrors.p}</p>
                  ) : null}
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={enrichMutation.isPending}>
                  {enrichMutation.isPending ? (
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                  ) : (
                    <Play className="size-4" aria-hidden />
                  )}
                  {t("tools.enrichment.submit")}
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
          {enrichMutation.isError ? (
            <ErrorState
              title={t("tools.enrichment.errorTitle")}
              message={(enrichMutation.error as Error).message}
              onRetry={() => enrichMutation.mutate()}
              retryLabel={t("common.retry")}
            />
          ) : null}

          {!result && !enrichMutation.isError ? (
            <Card>
              <CardContent className="p-6">
                <EmptyState
                  mode="empty"
                  title={t("tools.enrichment.emptyTitle")}
                  description={t("tools.enrichment.emptyDesc")}
                />
              </CardContent>
            </Card>
          ) : null}

          {result ? (
            <Card>
              <CardHeader>
                <CardTitle>{t("tools.enrichment.summaryTitle")}</CardTitle>
                <CardDescription>
                  {t("tools.enrichment.summaryDesc", {
                    input: result.input_genes,
                    background: result.background_genes,
                  })}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{result.ontology.toUpperCase()}</Badge>
                  <Badge variant="secondary">
                    {t("tools.enrichment.termsBadge", { count: terms.length })}
                  </Badge>
                </div>
                {result.message ? (
                  <p className="rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                    {result.message}
                  </p>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10">
          {terms.length === 0 ? (
            <EmptyState
              mode="filtered"
              icon={Network}
              title={t("tools.enrichment.noTermsTitle")}
              description={t("tools.enrichment.noTermsDesc")}
            />
          ) : (
            <Card>
              <CardHeader>
                <CardTitle>{t("tools.enrichment.resultsTitle")}</CardTitle>
                <CardDescription>{t("tools.enrichment.resultsDesc")}</CardDescription>
              </CardHeader>
              <CardContent>
                <DataTable
                  ariaLabel={t("tools.enrichment.resultsTitle")}
                  rowKey={(row) => row.id}
                  data={terms}
                  responsive
                  columns={[
                    {
                      key: "term",
                      header: t("tools.enrichment.colTerm"),
                      cell: (row) => (
                        <div className="min-w-0">
                          <p className="font-mono text-xs font-medium">{row.id}</p>
                          <p className="truncate text-xs text-muted-foreground">{row.name}</p>
                        </div>
                      ),
                    },
                    {
                      key: "p",
                      header: t("tools.enrichment.colP"),
                      align: "right",
                      cell: (row) => <span className="font-mono text-xs">{fmtP(row.p_value)}</span>,
                    },
                    {
                      key: "q",
                      header: t("tools.enrichment.colQ"),
                      align: "right",
                      cell: (row) => <span className="font-mono text-xs">{fmtP(row.q_value)}</span>,
                    },
                    {
                      key: "gene_count",
                      header: t("tools.enrichment.colGenes"),
                      align: "right",
                      cell: (row) => (
                        <span className="font-mono text-xs">{row.gene_count}</span>
                      ),
                    },
                    {
                      key: "members",
                      header: t("tools.enrichment.colMembers"),
                      cell: (row) => (
                        <div className="flex max-w-[420px] flex-wrap gap-1">
                          {row.genes.map((g) => (
                            <Badge
                              key={g}
                              variant="secondary"
                              className="font-mono text-[10px]"
                            >
                              {g}
                            </Badge>
                          ))}
                        </div>
                      ),
                    },
                  ]}
                />
              </CardContent>
            </Card>
          )}
        </section>
      ) : null}
    </div>
  );
}
