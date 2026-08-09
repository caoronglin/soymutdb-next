/**
 * BLAST route — sequence homology search form + recent jobs.
 *
 * AntD 5 migration (A1): Card/Form/Select/Input/List/Tag/Alert replace the
 * frozen packages/ui components. TanStack Query data flow and zod
 * validation logic unchanged.
 *
 * Completed jobs expose a hits table (GET /blast/jobs/{id}/hits) with an
 * actions column: "Gbrowse" opens /browser at the hit's subject coordinates
 * (new tab) and "Gene search" deep-links /search/genes?q=<subject id>.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { FlaskConical, Play } from "lucide-react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  List,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  getBlastDatabases,
  submitBlastJob,
  getBlastJobs,
  getBlastHits,
  BLAST_PROGRAMS,
  apiBaseUrl,
  getAccessToken,
  type BlastJob,
} from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { ensurePermission, showNotification } from "../lib/use-browser-notifications";
import { z } from "zod";

export const Route = createFileRoute("/blast")({
  component: BlastComponent,
});

// D5 pilot: the job list prefers the server-push stream
// (GET /api/v1/jobs/events, SSE). Polling at this interval is the fallback
// that only runs while the stream is unavailable.
const POLL_INTERVAL_MS = 5_000;
const ACTIVE_STATUSES = new Set(["pending", "running"]);

/**
 * BlastDatabase response from the backend (GET /blast/databases) carries
 * assembly metadata — see apps/api/app/schemas/blast.py:
 * BlastDatabaseResponse { id, name, db_type, assembly_id, is_active,
 * assembly_name, assembly_version, assembly_is_default }.
 * The api-client type does not include these fields yet (Wave 2-D backend
 * change), so we extend it locally instead of touching packages/*.
 */
type BlastDatabaseWithAssembly = {
  id: number | string;
  name: string;
  is_active: boolean;
  assembly_name?: string | null;
  assembly_version?: string | null;
  assembly_is_default?: boolean | null;
};

/**
 * Loose hit type for the hits table. The backend returns `subject_*` fields
 * (apps/api/app/schemas/blast.py BlastHit) while the api-client BlastHit
 * type still uses the legacy `target_*` names — read both defensively
 * instead of touching packages/api-client.
 */
type BlastHitLoose = {
  id?: string | number;
  hsp_num?: number;
  subject_id?: string;
  subject_title?: string;
  target_id?: string;
  target_title?: string;
  percent_identity?: number;
  identity_percent?: number;
  alignment_length?: number;
  mismatches?: number;
  gap_opens?: number;
  query_start?: number;
  query_end?: number;
  subject_start?: number;
  subject_end?: number;
  target_start?: number;
  target_end?: number;
  evalue?: number;
  bit_score?: number;
  score?: number;
};

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

  const databases = (databasesQuery.data ?? []) as unknown as BlastDatabaseWithAssembly[];
  const activeDatabases = databases.filter((d) => d.is_active);

  const databaseOptions: { value: string; label: React.ReactNode; disabled?: boolean }[] =
    databasesQuery.isLoading
      ? [{ value: "__loading__", label: t("common.loading"), disabled: true }]
      : activeDatabases.length === 0
        ? [{ value: "__empty__", label: "No databases available", disabled: true }]
        : activeDatabases.map((d) => ({
            value: String(d.id),
            label: (
              <span className="flex items-center gap-2">
                <span>{d.name}</span>
                {d.assembly_name ? (
                  <span className="text-xs text-muted-foreground">· {d.assembly_name}</span>
                ) : null}
                {d.assembly_is_default ? (
                  <Tag className="m-0 text-[9px] uppercase">Default</Tag>
                ) : null}
              </span>
            ),
          }));

  // Default to the database flagged as the assembly default (fallback: first active).
  React.useEffect(() => {
    if (form.database) return;
    const active = (databasesQuery.data ?? []).filter((d) => d.is_active) as unknown as BlastDatabaseWithAssembly[];
    if (active.length === 0) return;
    const def = active.find((d) => d.assembly_is_default) ?? active[0];
    if (def) setForm((f) => ({ ...f, database: String(def.id) }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [databasesQuery.data]);

  const [sseAvailable, setSseAvailable] = React.useState(false);

  const jobsQuery = useQuery({
    queryKey: ["blast-jobs"],
    queryFn: () => getBlastJobs({ page: 1, page_size: 5 }),
    staleTime: 30_000,
    // D5 pilot: polling is the fallback — it runs only while the SSE stream
    // (GET /api/v1/jobs/events) is unavailable AND at least one job is still
    // active. The D2 notification effect below keeps working on refetches.
    refetchInterval: (query) => {
      if (sseAvailable) return false;
      const items = query.state.data?.items ?? [];
      return items.some((job) => ACTIVE_STATUSES.has(job.status))
        ? POLL_INTERVAL_MS
        : false;
    },
  });

  // D5 pilot: server-push job updates via SSE (GET /api/v1/jobs/events).
  // EventSource cannot set an Authorization header, so the in-memory access
  // token travels as a short-lived query parameter (never persisted). Any
  // stream failure closes the connection and falls back to polling; the
  // connection is closed again when the component unmounts.
  React.useEffect(() => {
    const token = getAccessToken();
    const url = new URL(`${apiBaseUrl}/jobs/events`, window.location.origin);
    if (token) url.searchParams.set("access_token", token);
    const es = new EventSource(url.toString());

    es.addEventListener("open", () => setSseAvailable(true));
    es.addEventListener("job_update", (event) => {
      try {
        const update = JSON.parse((event as MessageEvent).data) as {
          job_type?: string;
        };
        // Only blast updates concern this page; analysis/gwas updates are
        // ignored (their own pages will subscribe).
        if (update.job_type === "blast") {
          // Refresh immediately — covers the completed/failed transitions
          // this pilot targets.
          void queryClient.invalidateQueries({ queryKey: ["blast-jobs"] });
        }
      } catch {
        // Malformed frame — ignore; the polling fallback still refreshes.
      }
    });
    es.onerror = () => {
      // SSE unavailable (proxy, auth expiry, server restart): fall back to
      // polling and stop EventSource from reconnecting.
      es.close();
      setSseAvailable(false);
    };

    return () => {
      es.close();
      setSseAvailable(false);
    };
  }, [queryClient]);

  // D2 pilot: fire an OS-level browser notification when a job transitions
  // to completed while the user is watching (only after the first render,
  // so pre-existing completed jobs don't re-notify).
  const prevJobStatus = React.useRef<Map<string, string>>(new Map());
  React.useEffect(() => {
    const items = jobsQuery.data?.items ?? [];
    for (const job of items) {
      const prev = prevJobStatus.current.get(job.id);
      prevJobStatus.current.set(job.id, job.status);
      if (prev && prev !== "completed" && job.status === "completed") {
        showNotification(
          t("notifications.blastCompleted"),
          `${job.program} · ${job.database}`,
        );
      }
    }
  }, [jobsQuery.data, t]);

  const submitMutation = useMutation({
    mutationFn: submitBlastJob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["blast-jobs"] });
      setForm((f) => ({ ...f, sequence: "" }));
    },
  });

  const onSubmit = () => {
    // Request Notification permission inside this user gesture (browser
    // requirement) — fire-and-forget; denied is handled by the hook.
    void ensurePermission();
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
    // The select stores the database id; the backend accepts the database
    // *name* (or numeric database_id) — map back so the job carries a
    // plain identifier that resolves to an active whitelist entry.
    const selected = activeDatabases.find((d) => String(d.id) === parsed.data.database);
    submitMutation.mutate({
      ...parsed.data,
      database: selected?.name ?? parsed.data.database,
    });
  };

  const clearForm = () =>
    setForm({ program: "blastn", database: "", sequence: "", e_value: "1e-5", max_hits: "50" });

  const jobs = jobsQuery.data?.items ?? [];

  // -------------------------------------------------------------------------
  // Hits table (completed jobs) — with Gbrowse / gene-search cross links
  // -------------------------------------------------------------------------
  const navigate = useNavigate();
  const [selectedJob, setSelectedJob] = React.useState<BlastJob | null>(null);

  const hitsQuery = useQuery({
    queryKey: ["blast-hits", selectedJob?.id],
    queryFn: async () => {
      const res = await getBlastHits(selectedJob!.id, { page: 1, page_size: 100 });
      return (res.items ?? []) as unknown as BlastHitLoose[];
    },
    enabled: selectedJob != null,
    staleTime: 60_000,
  });

  // The job stores the database *name*; map back to its assembly for the
  // Gbrowse deep link (name match first, then id match).
  const assemblyForJob = (job: BlastJob): string | undefined => {
    const byName = databases.find((d) => d.name === job.database);
    if (byName?.assembly_name) return byName.assembly_name;
    const byId = databases.find((d) => String(d.id) === String(job.database));
    return byId?.assembly_name ?? undefined;
  };

  const hitSubjectId = (hit: BlastHitLoose): string | undefined =>
    hit.subject_id ?? hit.target_id;
  const hitStart = (hit: BlastHitLoose): number | undefined =>
    hit.subject_start ?? hit.target_start;
  const hitEnd = (hit: BlastHitLoose): number | undefined =>
    hit.subject_end ?? hit.target_end;

  /** /browser deep link for a hit, or null when coordinates are missing. */
  const browserUrlFor = (job: BlastJob, hit: BlastHitLoose): string | null => {
    const assembly = assemblyForJob(job);
    const chr = hitSubjectId(hit);
    const start = hitStart(hit);
    const end = hitEnd(hit);
    if (!assembly || !chr || start == null || end == null) return null;
    const params = new URLSearchParams({
      assembly,
      locus: `${chr}:${start}-${end}`,
    });
    return `/browser?${params.toString()}`;
  };

  const hits = hitsQuery.data ?? [];
  const hitsColumns: TableColumnsType<BlastHitLoose> = [
    {
      title: t("blast.hitSubject"),
      dataIndex: "subject_id",
      key: "subject",
      render: (_, hit) => {
        const id = hitSubjectId(hit);
        const title = hit.subject_title ?? hit.target_title;
        return (
          <span className="min-w-0">
            <span className="block truncate font-mono text-xs font-medium">{id ?? "—"}</span>
            {title ? (
              <span className="block truncate text-xs text-muted-foreground">{title}</span>
            ) : null}
          </span>
        );
      },
    },
    {
      title: t("blast.hitScore"),
      dataIndex: "bit_score",
      key: "score",
      width: 90,
      render: (_, hit) => {
        const score = hit.bit_score ?? hit.score;
        return score != null ? (
          <span className="font-mono text-xs">{score.toFixed(1)}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      title: t("blast.hitEValue"),
      dataIndex: "evalue",
      key: "evalue",
      width: 110,
      render: (_, hit) =>
        hit.evalue != null ? (
          <span className="font-mono text-xs">{hit.evalue.toExponential(2)}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: t("blast.hitIdentity"),
      dataIndex: "percent_identity",
      key: "identity",
      width: 100,
      render: (_, hit) => {
        const identity = hit.percent_identity ?? hit.identity_percent;
        return identity != null ? (
          <span className="font-mono text-xs">{identity.toFixed(1)}%</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      title: t("blast.hitLength"),
      dataIndex: "alignment_length",
      key: "length",
      width: 90,
      render: (_, hit) =>
        hit.alignment_length != null ? (
          <span className="font-mono text-xs">{hit.alignment_length}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      title: t("blast.hitSubjectCoords"),
      dataIndex: "subject_start",
      key: "subject_coords",
      width: 160,
      render: (_, hit) => {
        const chr = hitSubjectId(hit);
        const start = hitStart(hit);
        const end = hitEnd(hit);
        return start != null && end != null && chr ? (
          <span className="font-mono text-xs text-muted-foreground">
            {chr}:{start}-{end}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      title: t("common.actions"),
      key: "actions",
      width: 190,
      render: (_, hit) => {
        const browserUrl = selectedJob ? browserUrlFor(selectedJob, hit) : null;
        const geneId = hitSubjectId(hit);
        return (
          <Space size={4} wrap>
            <Button
              size="small"
              disabled={!browserUrl}
              href={browserUrl ?? undefined}
              target="_blank"
              rel="noreferrer"
            >
              {t("blast.actions.gbrowse")}
            </Button>
            <Button
              size="small"
              disabled={!geneId}
              onClick={() => {
                if (!geneId) return;
                navigate({
                  to: "/search/genes",
                  search: { q: geneId, tissue: undefined, treatment: undefined, min_fpkm: undefined },
                });
              }}
            >
              {t("blast.actions.geneSearch")}
            </Button>
          </Space>
        );
      },
    },
  ];

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <p className="eyebrow">{t("blast.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {t("blast.subtitle")}
        </h1>

        <Card className="mt-8 max-w-3xl">
          <Card.Meta
            title={
              <span className="flex items-center gap-2">
                <FlaskConical className="size-5 text-primary" aria-hidden />
                {t("blast.title")}
              </span>
            }
            description={<Typography.Text type="secondary">Submit a sequence for homology search</Typography.Text>}
          />
          <Form layout="vertical" onFinish={onSubmit} className="mt-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <Form.Item
                label={t("blast.searchType")}
                htmlFor="program"
                help={errors.program ?? undefined}
                validateStatus={errors.program ? "error" : undefined}
              >
                <Select
                  id="program"
                  value={form.program}
                  onChange={(v) => setForm((f) => ({ ...f, program: v }))}
                  options={BLAST_PROGRAMS.map((p) => ({ value: p.id, label: p.label }))}
                />
              </Form.Item>
              <Form.Item
                label={t("blast.database")}
                htmlFor="database"
                help={errors.database ?? undefined}
                validateStatus={errors.database ? "error" : undefined}
              >
                <Select
                  id="database"
                  value={form.database}
                  onChange={(v) => setForm((f) => ({ ...f, database: v }))}
                  placeholder="Select database"
                  options={databaseOptions}
                />
              </Form.Item>
            </div>

            <Form.Item
              label={t("blast.inputSequence")}
              htmlFor="sequence"
              help={errors.sequence ?? undefined}
              validateStatus={errors.sequence ? "error" : undefined}
            >
              <Input.TextArea
                id="sequence"
                value={form.sequence}
                onChange={(e) => setForm((f) => ({ ...f, sequence: e.target.value }))}
                placeholder={t("blast.sequencePlaceholder")}
                className="min-h-[160px] font-mono text-sm"
              />
            </Form.Item>

            <div className="grid gap-4 sm:grid-cols-2">
              <Form.Item label={t("blast.eValue")} htmlFor="e_value">
                <Input
                  id="e_value"
                  value={form.e_value}
                  onChange={(e) => setForm((f) => ({ ...f, e_value: e.target.value }))}
                  className="font-mono"
                />
              </Form.Item>
              <Form.Item label={t("blast.maxHits")} htmlFor="max_hits">
                <Input
                  id="max_hits"
                  type="number"
                  value={form.max_hits}
                  onChange={(e) => setForm((f) => ({ ...f, max_hits: e.target.value }))}
                  className="font-mono"
                />
              </Form.Item>
            </div>

            <div className="flex gap-2">
              <Button
                type="primary"
                htmlType="submit"
                loading={submitMutation.isPending}
                icon={<Play className="size-4" aria-hidden />}
              >
                {t("blast.submit")}
              </Button>
              <Button onClick={clearForm}>{t("blast.clear")}</Button>
            </div>
            {submitMutation.isError ? (
              <Alert
                type="error"
                showIcon
                className="mt-4"
                message={`Failed to submit: ${(submitMutation.error as Error).message}`}
              />
            ) : null}
          </Form>
        </Card>

        <Card
          className="mt-6"
          title={<span className="text-base">{t("blast.myJobs")}</span>}
          extra={<Typography.Text type="secondary">{t("blast.jobHistory")}</Typography.Text>}
        >
          {jobsQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 3 }} title={false} />
          ) : jobs.length === 0 ? (
            <Empty description={t("blast.noJobs")} />
          ) : (
            <List<BlastJob>
              dataSource={jobs}
              renderItem={(job) => (
                <List.Item key={job.id}>
                  <div className="flex w-full items-center justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs">{job.id.slice(0, 12)}…</p>
                      <p className="text-xs text-muted-foreground">{job.program} · {job.database}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <Tag
                        color={job.status === "completed" ? "success" : "default"}
                        className="m-0 text-[10px] uppercase"
                      >
                        {job.status}
                      </Tag>
                      {job.status === "completed" ? (
                        <Button
                          size="small"
                          type={selectedJob?.id === job.id ? "primary" : "default"}
                          onClick={() => setSelectedJob(job)}
                        >
                          {t("blast.viewResults")}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                </List.Item>
              )}
            />
          )}
        </Card>

        {/* Hits table for the selected completed job — with Gbrowse /
            gene-search cross links (PPTX V2). */}
        {selectedJob ? (
          <Card
            className="mt-6"
            title={<span className="text-base">{t("blast.resultsTitle")}</span>}
            extra={
              <Typography.Text type="secondary" className="font-mono">
                {selectedJob.id.slice(0, 12)}…
              </Typography.Text>
            }
          >
            {hitsQuery.isLoading ? (
              <Skeleton active paragraph={{ rows: 4 }} title={false} />
            ) : hits.length === 0 ? (
              <Empty description={t("blast.noHits")} />
            ) : (
              <Table<BlastHitLoose>
                rowKey={(hit) => String(hit.id ?? hit.hsp_num ?? 0)}
                columns={hitsColumns}
                dataSource={hits}
                loading={hitsQuery.isFetching}
                size="small"
                pagination={
                  hits.length > 25
                    ? { pageSize: 25, showSizeChanger: false }
                    : false
                }
                scroll={{ x: "max-content" }}
              />
            )}
          </Card>
        ) : null}
      </div>
    </FadeUp>
  );
}
