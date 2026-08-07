/**
 * BLAST route — sequence homology search form + recent jobs.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { FlaskConical, Play, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Textarea, Button, Label, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Input, Badge } from "@soymutdb/ui";
import { getBlastDatabases, submitBlastJob, getBlastJobs, BLAST_PROGRAMS } from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { z } from "zod";

export const Route = createFileRoute("/blast")({
  component: BlastComponent,
});

const blastSchema = z.object({
  program: z.string().min(1),
  database: z.string().min(1),
  sequence: z.string().min(10, "Sequence must be at least 10 characters"),
  e_value: z.number().min(0).default(1e-5),
  max_hits: z.number().int().min(1).max(1000).default(50),
});

function BlastComponent() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = React.useState({
    program: "blastn",
    database: "",
    sequence: "",
    e_value: "1e-5",
    max_hits: "50",
  });
  const [errors, setErrors] = React.useState<Record<string, string>>({});

  const databasesQuery = useQuery({
    queryKey: ["blast-databases"],
    queryFn: getBlastDatabases,
    staleTime: 30 * 60 * 1000,
  });

  const jobsQuery = useQuery({
    queryKey: ["blast-jobs"],
    queryFn: () => getBlastJobs({ page: 1, page_size: 5 }),
    staleTime: 30_000,
  });

  const submitMutation = useMutation({
    mutationFn: submitBlastJob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["blast-jobs"] });
      setForm((f) => ({ ...f, sequence: "" }));
    },
  });

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = blastSchema.safeParse({
      program: form.program,
      database: form.database,
      sequence: form.sequence,
      e_value: Number(form.e_value),
      max_hits: Number(form.max_hits),
    });
    if (!parsed.success) {
      const fieldErrors: Record<string, string> = {};
      for (const issue of parsed.error.issues) {
        fieldErrors[issue.path[0] as string] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    setErrors({});
    submitMutation.mutate(parsed.data);
  };

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("blast.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("blast.subtitle")}</h1>
      </FadeUp>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FlaskConical className="size-5 text-primary" aria-hidden />
              {t("blast.title")}
            </CardTitle>
            <CardDescription>Submit a sequence for homology search</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="grid gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="program">{t("blast.searchType")}</Label>
                  <Select value={form.program} onValueChange={(v) => setForm((f) => ({ ...f, program: v }))}>
                    <SelectTrigger id="program"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {BLAST_PROGRAMS.map((p) => (
                        <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="database">{t("blast.database")}</Label>
                  <Select value={form.database} onValueChange={(v) => setForm((f) => ({ ...f, database: v }))}>
                    <SelectTrigger id="database"><SelectValue placeholder="Select database" /></SelectTrigger>
                    <SelectContent>
                      {databasesQuery.data?.filter((d) => d.is_active).map((d) => (
                        <SelectItem key={d.id} value={d.id}>{d.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {errors.database ? <p className="text-xs text-destructive">{errors.database}</p> : null}
                </div>
              </div>

              <div className="grid gap-2">
                <Label htmlFor="sequence">{t("blast.inputSequence")}</Label>
                <Textarea
                  id="sequence"
                  value={form.sequence}
                  onChange={(e) => setForm((f) => ({ ...f, sequence: e.target.value }))}
                  placeholder={t("blast.sequencePlaceholder")}
                  className="min-h-[160px] font-mono text-sm"
                  aria-invalid={!!errors.sequence}
                />
                {errors.sequence ? <p className="text-xs text-destructive">{errors.sequence}</p> : null}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="grid gap-2">
                  <Label htmlFor="e_value">{t("blast.eValue")}</Label>
                  <Input id="e_value" value={form.e_value} onChange={(e) => setForm((f) => ({ ...f, e_value: e.target.value }))} className="font-mono" />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor="max_hits">{t("blast.maxHits")}</Label>
                  <Input id="max_hits" type="number" value={form.max_hits} onChange={(e) => setForm((f) => ({ ...f, max_hits: e.target.value }))} className="font-mono" />
                </div>
              </div>

              <div className="flex gap-2">
                <Button type="submit" disabled={submitMutation.isPending}>
                  {submitMutation.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
                  {t("blast.submit")}
                </Button>
                <Button type="button" variant="outline" onClick={() => setForm({ program: "blastn", database: "", sequence: "", e_value: "1e-5", max_hits: "50" })}>
                  {t("blast.clear")}
                </Button>
              </div>
              {submitMutation.isError ? (
                <p className="text-sm text-destructive">Failed to submit: {(submitMutation.error as Error).message}</p>
              ) : null}
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("blast.myJobs")}</CardTitle>
            <CardDescription>{t("blast.jobHistory")}</CardDescription>
          </CardHeader>
          <CardContent>
            {jobsQuery.isLoading ? (
              <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
            ) : jobsQuery.data?.items.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("blast.noJobs")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {jobsQuery.data?.items.map((job) => (
                  <li key={job.id} className="flex items-center justify-between gap-3 rounded-lg border p-3">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs">{job.id.slice(0, 12)}…</p>
                      <p className="text-xs text-muted-foreground">{job.program} · {job.database}</p>
                    </div>
                    <Badge variant={job.status === "completed" ? "default" : "secondary"} className="text-[10px] uppercase">
                      {job.status}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
