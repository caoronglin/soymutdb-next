/**
 * BLAST route — sequence homology search form + recent jobs.
 *
 * AntD 5 migration (A1): Card/Form/Select/Input/List/Tag/Alert replace the
 * frozen shared UI components. TanStack Query data flow and zod
 * validation logic unchanged.
 *
 * The recent-jobs list is a native <ul>/<li>: AntD 6 deprecated List and the
 * rows are plain markup, so no AntD replacement component is involved.
 *
 * Completed jobs expose a results table. "JBrowse 2" resolves an exact gene
 * in the job's release/assembly before same-tab navigation to its genomic
 * interval; DIAMOND protein-space coordinates are never used as genome bp.
 *
 * The "JBrowse 2" link carries the job's own release next to its assembly:
 * the hit coordinates belong to the release the job searched, so the genome
 * browser must read that release's assembly list and tracks. A job that
 * states no such context gets no link and a visible reason instead.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { CaretRightOutlined as Play, ExperimentOutlined as FlaskConical } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Result,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  getBlastDatabases,
  submitBlastJob,
  getBlastJobs,
  getBlastHits,
  resolveBlastHitGenomeTarget,
  type BlastHit,
  BLAST_PROGRAMS,
  apiBaseUrl,
  getAccessToken,
  type BlastJob,
} from "@soymutdb/api-client";
import { FadeUp } from "../components/route-motion";
import { useSiteContent } from "../lib/site-content-react";
import { grantsResearcher, useCurrentUser } from "../lib/use-current-user";
import { resolveAppUrl } from "../lib/deployment";
import { useReleaseId } from "../lib/release-scope";
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

/** The release and assembly a job's hits belong to. */
type JobContext = {
  /** The job's own release id, as the string the deep link carries. */
  release: string;
  /** The assembly the job's database belongs to. */
  assembly: string;
};

// The only executable program is DIAMOND blastp (protein vs protein). The
// API still reports the wider BlastProgram vocabulary for jobs stored before
// the engine was reduced, so history rendering must keep using those labels.
const BLAST_PROGRAM = BLAST_PROGRAMS[0];

const blastSchema = z.object({
  program: z.string().min(1),
  database: z.string().min(1),
  sequence: z.string().min(10, "Sequence must be at least 10 characters"),
  e_value: z.number().min(0).default(1e-5),
  max_hits: z.number().int().min(1).max(1000).default(50),
});

/**
 * Client-side FASTA structure check (defence in depth on top of backend
 * validation). Accepts a plain sequence or one-or-more FASTA records; rejects
 * a `>` header with no following sequence and non-sequence characters.
 *
 * @returns an error message, or null when the input is acceptable.
 */
function validateFastaStructure(input: string): string | null {
  const hasHeader = />/.test(input.trim());
  if (!hasHeader) return null; // plain sequence — backend validates.
  const lines = input.split(/\r?\n/).map((l) => l.trim());
  let currentHasHeader = false;
  let currentHasSeq = false;
  let sawAny = false;
  for (const line of lines) {
    if (!line) continue;
    if (line.startsWith(">")) {
      if (currentHasHeader && !currentHasSeq) {
        return "FASTA header without a sequence";
      }
      currentHasHeader = true;
      currentHasSeq = false;
      sawAny = true;
    } else {
      // Sequence line — allow letters and common gap/stop symbols.
      if (currentHasHeader && !/[^A-Za-z*.-]/.test(line.replace(/\s+/g, ""))) {
        currentHasSeq = true;
      } else if (!currentHasHeader) {
        return "Sequence data before a FASTA header";
      }
    }
  }
  if (sawAny && !currentHasSeq) {
    return "FASTA header without a sequence";
  }
  return null;
}

/** Extract the ID from the first FASTA header of a submitted query, if any. */
function fastaHeaderId(sequence: string | null | undefined): string | undefined {
  const seq = sequence?.trim();
  if (!seq) return undefined;
  const header = seq.split(/\r?\n/).find((line) => line.trimStart().startsWith(">"));
  return header ? header.slice(1).trim().split(/\s+/)[0] : undefined;
}

function BlastComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const queryClient = useQueryClient();
  // /blast is a prerendered, sitemapped public route: an anonymous visitor must
  // be able to read the form and the database list. Only the per-account job
  // history needs a session, so the session is read first and every
  // authenticated call is gated on it. Requesting /blast/jobs while anonymous
  // returns 401, which the api-client turns into a global logout event — that
  // bounced the whole page to /login and made the published route unreachable.
  const { user, isLoading: currentUserLoading } = useCurrentUser();
  const isSignedIn = user != null;
  // The API remains the authority, but avoid presenting an action that the
  // current session can never authorize. Anonymous visitors retain the
  // public database/form experience; researcher-capable users retain submit.
  const canSubmit = user != null && grantsResearcher(user);
  // Defaults to blastp: protein/protein is the only program this deployment
  // executes, and DIAMOND is the only aligner behind it.
  const [form, setForm] = React.useState({
    program: "blastp",
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

  const databases = (databasesQuery.data ?? []);
  const activeDatabases = databases.filter((d) => d.is_active);

  const databaseOptions: { value: string; label: React.ReactNode; disabled?: boolean }[] =
    databasesQuery.isLoading
      ? [{ value: "__loading__", label: get("ui.loading", t("common.loading")), disabled: true }]
      : activeDatabases.length === 0
        ? [{ value: "__empty__", label: get("ui.noResults", t("blast.noDatabases")), disabled: true }]
        : activeDatabases.map((d) => ({
            value: String(d.id),
            label: (
              <span className="flex items-center gap-2">
                <span>{d.name}</span>
                {d.assembly_name ? (
                  <span className="text-xs text-muted-foreground">· {d.assembly_name}</span>
                ) : null}
                {d.assembly_is_default ? (
                  <Tag className="m-0 text-[9px] uppercase">{t("blast.defaultTag")}</Tag>
                ) : null}
              </span>
            ),
          }));

  // Default to the database flagged as the assembly default (fallback: first active).
  React.useEffect(() => {
    if (form.database) return;
    const active = (databasesQuery.data ?? []).filter((d) => d.is_active);
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
    enabled: isSignedIn,
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
    // EventSource cannot carry an Authorization header, so an anonymous stream
    // would 401 and reconnect forever. Subscribe only for a known session.
    if (!isSignedIn) {
      setSseAvailable(false);
      return;
    }
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
  }, [queryClient, isSignedIn]);

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
    const fastaError = validateFastaStructure(parsed.data.sequence);
    if (fastaError) {
      setErrors({ sequence: fastaError });
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
    setForm({ program: "blastp", database: "", sequence: "", e_value: "1e-5", max_hits: "50" });

  const jobs = jobsQuery.data?.items ?? [];

  // -------------------------------------------------------------------------
  // Hits table (completed jobs) — with JBrowse 2 / gene-search cross links
  // -------------------------------------------------------------------------
  const navigate = useNavigate();
  const [selectedJob, setSelectedJob] = React.useState<BlastJob | null>(null);

  const hitsQuery = useQuery({
    queryKey: ["blast-hits", selectedJob?.id],
    queryFn: async () => {
      const res = await getBlastHits(selectedJob!.id, { limit: 100, offset: 0 });
      return res.items ?? [];
    },
    enabled: selectedJob != null,
    staleTime: 60_000,
  });

  /**
   * The release/assembly context a job's hits belong to.
   *
   * The job carries its own provenance — the release and assembly of the
   * database it searched — so a job submitted against release A keeps
   * release A after the active release moved to B: the hit coordinates are
   * A's coordinates.
   *
   * The currently listed databases are deliberately NOT used as a substitute.
   * That list belongs to the active release, and a database name that exists
   * in both releases would re-label an old job with the new release's
   * assembly — exactly the "old results, new coordinates" mix-up the release
   * contract forbids.
   *
   * `null` means "no trustworthy context": the caller must then offer no
   * link instead of guessing one.
   */
  const contextForJob = (job: BlastJob): JobContext | null => {
    const { release_id: releaseId } = job;
    const assembly = job.assembly_name?.trim();
    if (releaseId == null || !Number.isInteger(releaseId) || releaseId < 1) return null;
    if (!assembly) return null;
    return { release: String(releaseId), assembly };
  };

  const currentRelease = useReleaseId();
  const [resolvingHit, setResolvingHit] = React.useState<string | null>(null);
  const [navigationError, setNavigationError] = React.useState<string | null>(null);
  const navigationAttempt = React.useRef(0);
  React.useEffect(() => {
    navigationAttempt.current += 1;
    setResolvingHit(null);
    setNavigationError(null);
    return () => { navigationAttempt.current += 1; };
  }, [selectedJob?.id]);
  const openGenomeBrowser = async (job: BlastJob, hit: BlastHit) => {
    const attempt = ++navigationAttempt.current;
    setResolvingHit(hit.subject_id);
    setNavigationError(null);
    try {
      const target = await resolveBlastHitGenomeTarget(job, hit.subject_id);
      if (attempt !== navigationAttempt.current) return;
      if (!target) {
        setNavigationError(t("blast.jbrowse.unavailable"));
        return;
      }
      // Same-tab navigation avoids popup blockers after the async lookup.
      await navigate({ to: "/browser", search: target });
    } catch {
      if (attempt === navigationAttempt.current) setNavigationError(t("blast.jbrowse.resolveFailed"));
    } finally {
      if (attempt === navigationAttempt.current) setResolvingHit(null);
    }
  };

  const hits = hitsQuery.data ?? [];
  const inputSequenceId = selectedJob ? fastaHeaderId(selectedJob.query_sequence) : undefined;
  const hitsColumns: TableColumnsType<BlastHit> = [
    {
      // Wireframe: 基因组版本 (assembly) — shown with the release the job was
      // computed against, so a reader can tell which release the hit belongs
      // to before following any link.
      title: t("search.genes.colAssembly"),
      key: "assembly",
      width: 160,
      render: () => {
        const context = selectedJob ? contextForJob(selectedJob) : null;
        if (!context) {
          return <span className="font-mono text-xs text-muted-foreground">—</span>;
        }
        return (
          <span className="font-mono text-xs text-muted-foreground">
            {context.assembly}
            <span className="block text-[10px]">
              {`${t("search.releaseLabel")} ${context.release}`}
            </span>
          </span>
        );
      },
    },
    {
      // Wireframe: 输入序列ID (query FASTA header id, same for every hit)
      title: get("blast.hitSequenceId", t("blast.hitSequenceId")),
      key: "subject",
      width: 160,
      render: () => (
        <span className="font-mono text-xs font-medium">{inputSequenceId ?? "—"}</span>
      ),
    },
    {
      // Wireframe: 覆盖度 (coverage/identity)
      title: get("blast.hitCoverage", t("blast.hitCoverage")),
      dataIndex: "percent_identity",
      key: "identity",
      width: 110,
      render: (_, hit) => {
        const identity = hit.percent_identity;
        return identity != null ? (
          <span className="font-mono text-xs">{identity.toFixed(1)}%</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
    {
      // The alignment coordinates are amino-acid positions of the subject
      // protein. They are deliberately labelled as protein coordinates: they
      // are not genome positions, and the genome browser link below resolves
      // the gene itself rather than these offsets.
      title: get("blast.hitProteinCoords", t("blast.hitProteinCoords")),
      key: "proteinCoords",
      width: 150,
      render: (_, hit) => (
        <span className="font-mono text-xs">
          {hit.subject_start}-{hit.subject_end}
        </span>
      ),
    },
    {
      // Wireframe: E值
      title: get("blast.hitEValue", t("blast.hitEValue")),
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
      // Wireframe: 基因ID (button → gene ID search)
      title: get("blast.hitGeneId", t("blast.hitGeneId")),
      key: "gene",
      width: 180,
      render: (_, hit) => {
        const geneId = hit.subject_id;
        const context = selectedJob ? contextForJob(selectedJob) : null;
        const canSearch = context != null && context.release === currentRelease;
        // The identifier is shown whole. It used to go through
        // `compactGeneId(geneId, 18)`, which cut `Glyma.066015200`-length and
        // longer accessions with an ellipsis — the one string on this row a
        // reader needs in full to verify the hit. The column is wide enough for
        // the common cases and the button wraps for the rest.
        return (
          <Button
            size="small"
            className="h-auto whitespace-normal break-all py-1 text-left font-mono text-xs"
            title={canSearch ? geneId : t("blast.geneSearchReleaseMismatch")}
            disabled={!geneId || !canSearch}
            onClick={() => {
              if (!geneId || !context || !canSearch) return;
              navigate({
                to: "/search/genes",
                search: { q: geneId, assembly: context.assembly, run: true },
              });
            }}
          >
            {geneId ?? t("blast.actions.geneSearch")}
          </Button>
        );
      },
    },
    {
      // Wireframe: Gbrowse (button → browser new page)
      title: t("blast.actions.gbrowse"),
      key: "gbrowse",
      width: 140,
      render: (_, hit) => {
        const context = selectedJob ? contextForJob(selectedJob) : null;
        return (
          <Button
            size="small"
            data-testid="blast-gbrowse-link"
            disabled={!context || !hit.subject_id?.trim() || resolvingHit != null}
            loading={resolvingHit === hit.subject_id}
            onClick={() => { if (selectedJob) void openGenomeBrowser(selectedJob, hit); }}
            title={context ? undefined : t("browser.contextMissingDescription")}
          >
            {t(resolvingHit === hit.subject_id ? "blast.jbrowse.resolving" : "blast.actions.gbrowse")}
          </Button>
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

        <Card className="mt-8">
          <Card.Meta
            title={
              <span className="flex items-center gap-2">
                <FlaskConical className="size-5 text-primary" aria-hidden />
                {t("blast.title")}
              </span>
            }
            description={
              <Typography.Text type="secondary">{t("blast.desc")}</Typography.Text>
            }
          />
          {/* Label-above, two columns. The previous horizontal layout pinned a
              6/24 label column inside a 768px card, which left every control
              roughly 570px wide no matter how wide the viewport got — the page
              looked small on a wide screen because it was.

              The wrapper div carries `mt-6`, not the <form>: antd's cssinjs
              injects `:where(.css-x).ant-form{margin:0}` at runtime, into the
              head *after* Tailwind's stylesheet. Same specificity, later wins,
              so a spacing utility on an antd element root is a silent no-op. */}
          <div className="mt-6">
          <Form layout="vertical" onFinish={onSubmit}>
            <div className="grid gap-x-6 md:grid-cols-2">
            <Form.Item
              label={get("blast.searchType", t("blast.searchType"))}
              htmlFor="program"
              help={errors.program ?? undefined}
              validateStatus={errors.program ? "error" : undefined}
            >
              {/* One executable program, so a dropdown would be a control that
                  cannot change anything. A read-only value states the contract
                  without inviting a click. */}
              <div
                id="program"
                data-testid="blast-program"
                className="flex h-8 items-center gap-2 rounded-md border border-input bg-muted/40 px-3 text-sm"
              >
                <span className="font-medium">{BLAST_PROGRAM.label}</span>
                <span className="text-xs text-muted-foreground">
                  {t("blast.proteinOnlyHint")}
                </span>
              </div>
            </Form.Item>

            <Form.Item
              label={get("blast.database", t("blast.database"))}
              htmlFor="database"
              help={errors.database ?? undefined}
              validateStatus={errors.database ? "error" : undefined}
            >
              <Select
                id="database"
                data-testid="blast-database"
                size="large"
                value={form.database}
                onChange={(v) => setForm((f) => ({ ...f, database: v }))}
                placeholder={t("blast.referencePlaceholder")}
                options={databaseOptions}
              />
            </Form.Item>

            </div>

            <Form.Item
              label={get("blast.input", t("blast.inputSequence"))}
              htmlFor="sequence"
              help={errors.sequence ?? undefined}
              validateStatus={errors.sequence ? "error" : undefined}
            >
              <Input.TextArea
                id="sequence"
                data-testid="blast-sequence"
                size="large"
                value={form.sequence}
                onChange={(e) => setForm((f) => ({ ...f, sequence: e.target.value }))}
                placeholder={get("blast.sequencePlaceholder", t("blast.sequencePlaceholder"))}
                className="min-h-[160px] font-mono text-sm"
              />
            </Form.Item>

            <div className="grid gap-x-6 md:grid-cols-2">
            <Form.Item label={t("blast.eValue")} htmlFor="e_value" style={{ marginBottom: 0 }}>
              <Input
                id="e_value"
                size="large"
                value={form.e_value}
                onChange={(e) => setForm((f) => ({ ...f, e_value: e.target.value }))}
                className="font-mono"
                style={{ maxWidth: 320 }}
              />
            </Form.Item>

            <Form.Item label={t("blast.maxHits")} htmlFor="max_hits" style={{ marginBottom: 0 }}>
              <Input
                id="max_hits"
                type="number"
                size="large"
                value={form.max_hits}
                onChange={(e) => setForm((f) => ({ ...f, max_hits: e.target.value }))}
                className="font-mono"
                style={{ maxWidth: 320 }}
              />
            </Form.Item>

            </div>

            <Form.Item style={{ marginTop: 24, marginBottom: 0 }}>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="primary"
                  htmlType="submit"
                  size="large"
                  data-testid="blast-submit"
                  loading={submitMutation.isPending}
                  disabled={!canSubmit}
                  title={!isSignedIn ? t("blast.submitRequiresLogin") : !canSubmit ? t("blast.submitRequiresResearcher") : undefined}
                  icon={<Play className="size-4" aria-hidden />}
                >
                  {get("blast.submit", t("blast.submit"))}
                </Button>
                <Button size="large" onClick={clearForm}>{t("blast.clear")}</Button>
              </div>
            </Form.Item>

            {!currentUserLoading && !canSubmit ? (
              <Form.Item className="mb-0 mt-4">
                <Alert
                  type="info"
                  showIcon
                  message={isSignedIn ? t("blast.submitRequiresResearcher") : t("blast.submitRequiresLogin")}
                />
              </Form.Item>
            ) : null}

            {submitMutation.isError ? (
              <Form.Item className="mb-0 mt-4">
                <Alert
                  type="error"
                  showIcon
                  title={get("ui.errorRetry", t("blast.submitFailed", { message: (submitMutation.error as Error).message }))}
                />
              </Form.Item>
            ) : null}
          </Form>
          </div>
        </Card>

        <Card
          className="mt-6"
          title={<span className="text-base">{t("blast.myJobs")}</span>}
          extra={
            isSignedIn ? (
              <Typography.Text type="secondary">{t("blast.jobHistory")}</Typography.Text>
            ) : null
          }
        >
          {currentUserLoading ? (
            <Skeleton active paragraph={{ rows: 2 }} title={false} />
          ) : !isSignedIn ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                <span className="text-sm text-muted-foreground">
                  {t("blast.noJobsAnonymous")}
                </span>
              }
            >
              <Button
                type="primary"
                href={resolveAppUrl(import.meta.env.BASE_URL, "/login")}
              >
                {t("auth.login")}
              </Button>
            </Empty>
          ) : jobsQuery.isLoading ? (
            <Skeleton active paragraph={{ rows: 3 }} title={false} />
          ) : jobs.length === 0 ? (
            <Empty description={get("ui.noResults", t("blast.noJobs"))} />
          ) : (
            // Native <ul>/<li> rather than AntD 6's deprecated List. The
            // empty state is the sibling branch above, so this list is only
            // reached with at least one job.
            <ul className="m-0 list-none p-0">
              {jobs.map((job) => (
                <li key={job.id} className="py-3">
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
                </li>
              ))}
            </ul>
          )}
        </Card>

        {/* Hits table for the selected completed job — with JBrowse 2 /
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
            {/*
              A job that states no release/assembly context cannot offer a
              trustworthy genome-browser link. The state is announced instead
              of silently dropping the column, so the reader knows the link is
              unavailable rather than missing.
            */}
            {selectedJob && !contextForJob(selectedJob) ? (
              <Alert
                className="mb-4"
                type="warning"
                showIcon
                title={t("browser.contextMissingTitle")}
                description={t("browser.contextMissingDescription")}
              />
            ) : null}
            {navigationError ? <Alert className="mb-4" type="error" showIcon title={navigationError} /> : null}
            {hitsQuery.isLoading ? (
              <Skeleton active paragraph={{ rows: 4 }} title={false} />
            ) : hitsQuery.isError ? (
              <div role="alert">
                <Result
                  status="error"
                  title={t("blast.hitsLoadError")}
                  extra={
                    <Button loading={hitsQuery.isFetching} onClick={() => void hitsQuery.refetch()}>
                      {t("common.retry")}
                    </Button>
                  }
                />
              </div>
            ) : hits.length === 0 ? (
              <Empty description={get("ui.noResults", t("blast.noHits"))} />
            ) : (
              <Table<BlastHit>
                rowKey={(hit) => String(hit.hsp_num)}
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
