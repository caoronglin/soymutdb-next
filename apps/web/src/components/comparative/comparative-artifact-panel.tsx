/**
 * MSA / phylogenetic tree panel for one gene family.
 *
 * An alignment is a job, not a value: the API answers 202 with a pending
 * artifact, the worker computes it, and the result is only ever valid for the
 * exact member set hashed into `input_sha256`. Three consequences are encoded
 * here:
 *
 * - the input hash and the frozen member count are always displayed next to the
 *   result, so a finished alignment is never read as describing the family's
 *   current membership;
 * - `download_url === null` renders no link at all. A `<a href={null}>` is a
 *   dead link wearing a button, and a dead download is worse than no download;
 * - `failed` shows `error_message` verbatim. The worker writes actionable text
 *   ("mafft is not installed on this worker"); paraphrasing it would cost the
 *   operator the one sentence that tells them what to fix.
 *
 * Polling stops on a terminal state, after a deadline, and when the component
 * unmounts (leaving the page) — `refetchInterval` alone still leaves an in-flight
 * request behind on navigation.
 */
import * as React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "@/lib/antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import {
  getArtifact,
  requestArtifact,
  type ArtifactKind,
  type ArtifactState,
} from "@soymutdb/api-client";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

const POLL_INTERVAL_MS = 3_000;
/** Wall-clock ceiling: a stuck job must not poll a page forever. */
const POLL_DEADLINE_MS = 5 * 60_000;

const ACTIVE_STATES: ReadonlySet<ArtifactState> = new Set<ArtifactState>(["pending", "running"]);

/** Methods the API allowlist accepts, split by artifact type. */
export const ARTIFACT_METHODS: Record<ArtifactKind, readonly string[]> = {
  msa: ["mafft", "muscle"],
  tree: ["iqtree", "fasttree"],
};

/** The poll must end on any state the worker will not move away from. */
export function isTerminalArtifactState(state: ArtifactState | undefined): boolean {
  return state === "succeeded" || state === "failed";
}

function StateTag({ state }: { state: ArtifactState }) {
  const { t } = useTranslation();
  if (state === "succeeded") {
    return (
      <Tag color="success" className="m-0 gap-1" data-artifact-state="succeeded">
        <CheckCircleOutlined className="size-3" aria-hidden />
        {t("analyses.job.statusSucceeded")}
      </Tag>
    );
  }
  if (state === "failed") {
    return (
      <Tag color="error" className="m-0 gap-1" data-artifact-state="failed">
        <CloseCircleOutlined className="size-3" aria-hidden />
        {t("analyses.job.statusFailed")}
      </Tag>
    );
  }
  return (
    <Tag color="processing" className="m-0 gap-1" data-artifact-state={state}>
      <LoadingOutlined className="size-3 animate-spin" aria-hidden />
      {state}
    </Tag>
  );
}

export interface ComparativeArtifactPanelProps {
  familyId: number;
  assemblyId?: number | null;
  /** Injected in tests so a whole poll cycle runs without fake timers. */
  pollIntervalMs?: number;
  pollDeadlineMs?: number;
}

export function ComparativeArtifactPanel({
  familyId,
  assemblyId,
  pollIntervalMs = POLL_INTERVAL_MS,
  pollDeadlineMs = POLL_DEADLINE_MS,
}: ComparativeArtifactPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const releaseId = useReleaseId();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState<ArtifactKind | null>(null);
  const [requestError, setRequestError] = React.useState<string | null>(null);
  const [timedOut, setTimedOut] = React.useState(false);
  const deadline = React.useRef<number | null>(null);
  const mounted = React.useRef(true);

  React.useEffect(() => {
    mounted.current = true;
    return () => {
      // Leaving the page stops the poll: the callback aborts further refetches
      // and the error is swallowed instead of surfacing on an unmounted tree.
      mounted.current = false;
    };
  }, []);

  const artifactQuery = useQuery({
    queryKey: queryKeys.comparative.artifact(jobId, releaseId, SITE_VARIANT),
    queryFn: () => getArtifact(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      if (!jobId || !mounted.current) return false;
      if (isTerminalArtifactState(query.state.data?.state)) return false;
      if (timedOut) return false;
      const startedAt = deadline.current;
      if (startedAt !== null && Date.now() - startedAt >= pollDeadlineMs) return false;
      return pollIntervalMs;
    },
  });

  const artifact = artifactQuery.data;

  // Deadline bookkeeping: one timer per submitted job, cleared on unmount so a
  // navigated-away page leaves nothing behind to fire.
  React.useEffect(() => {
    if (!jobId) return;
    deadline.current = Date.now();
    const timer = setTimeout(() => {
      if (mounted.current) setTimedOut(true);
    }, pollDeadlineMs);
    return () => {
      clearTimeout(timer);
      deadline.current = null;
    };
  }, [jobId, pollDeadlineMs]);

  const submit = async (nextKind: ArtifactKind) => {
    setSubmitting(nextKind);
    setRequestError(null);
    setTimedOut(false);
    try {
      const pending = await requestArtifact({
        family_id: familyId,
        artifact_type: nextKind,
        method: ARTIFACT_METHODS[nextKind][0],
        assembly_id: assemblyId ?? undefined,
      });
      if (!mounted.current) return;
      // Seed the cache with the 202 body so the panel does not flash "no data"
      // between submission and the first poll.
      queryClient.setQueryData(
        queryKeys.comparative.artifact(pending.job_id, releaseId, SITE_VARIANT),
        pending,
      );
      setJobId(pending.job_id);
    } catch (error) {
      if (mounted.current) {
        setRequestError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (mounted.current) setSubmitting(null);
    }
  };

  const frozenMembers = artifact?.input_member_ids?.length ?? null;

  return (
    <Card
      className="mt-4"
      data-testid="comparative-artifacts"
      title={t("comparative.detail.artifactsTitle")}
      extra={
        <Space size="small">
          <Button
            data-testid="request-msa"
            loading={submitting === "msa"}
            disabled={submitting !== null && submitting !== "msa"}
            onClick={() => void submit("msa")}
          >
            {t("comparative.detail.requestMsa")}
          </Button>
          <Button
            data-testid="request-tree"
            loading={submitting === "tree"}
            disabled={submitting !== null && submitting !== "tree"}
            onClick={() => void submit("tree")}
          >
            {t("comparative.detail.requestTree")}
          </Button>
        </Space>
      }
    >
      <p className="text-xs text-muted-foreground">{t("comparative.detail.artifactsNote")}</p>

      {requestError ? (
        <Alert
          className="mt-3"
          type="error"
          showIcon
          title={t("comparative.detail.requestFailed")}
          description={<span className="font-mono text-xs">{requestError}</span>}
          data-testid="artifact-request-error"
        />
      ) : null}

      {!jobId ? null : artifactQuery.isLoading && !artifact ? (
        <Skeleton active className="mt-4" paragraph={{ rows: 3 }} title={false} />
      ) : artifactQuery.isError && !artifact ? (
        <Alert
          className="mt-4"
          type="error"
          showIcon
          title={t("comparative.detail.loadError")}
        />
      ) : artifact ? (
        <div className="mt-4 space-y-3" data-testid="artifact-body">
          <div className="flex flex-wrap items-center gap-2">
            <Tag className="m-0 font-mono text-xs uppercase">{artifact.artifact_type}</Tag>
            <Tag className="m-0 font-mono text-xs">{artifact.method}</Tag>
            <StateTag state={artifact.state} />
            {ACTIVE_STATES.has(artifact.state) ? (
              <span className="text-xs text-muted-foreground">{t("comparative.detail.polling")}</span>
            ) : null}
          </div>

          {/* The hash and the frozen member count travel with the result: an
              alignment says nothing about members added after it ran. */}
          <Descriptions
            size="small"
            column={1}
            items={[
              {
                key: "input_sha256",
                label: t("comparative.detail.inputSha"),
                children: (
                  <span className="break-all font-mono text-xs" data-testid="artifact-input-sha">
                    {artifact.input_sha256}
                  </span>
                ),
              },
              {
                key: "input_members",
                label: t("comparative.detail.inputMembers"),
                children: (
                  <span className="font-mono text-xs tabular-nums" data-testid="artifact-input-members">
                    {frozenMembers === null ? "—" : frozenMembers}
                  </span>
                ),
              },
            ]}
          />

          {artifact.state === "failed" ? (
            // Verbatim: the worker's own sentence names the missing binary.
            <Alert
              type="error"
              showIcon
              title={t("analyses.job.statusFailed")}
              description={
                <Typography.Paragraph className="mb-0 font-mono text-xs" data-testid="artifact-error">
                  {artifact.error_message ?? t("common.noData")}
                </Typography.Paragraph>
              }
            />
          ) : null}

          {artifact.state === "succeeded" ? (
            artifact.download_url ? (
              <Button
                type="primary"
                icon={<DownloadOutlined className="size-4" aria-hidden />}
                href={artifact.download_url}
                target="_blank"
                rel="noreferrer"
                data-testid="artifact-download"
              >
                {t("comparative.detail.download")}
              </Button>
            ) : (
              // No URL, no button: a link with a null href is not a download.
              <p className="text-xs text-muted-foreground" data-testid="artifact-download-missing">
                {t("comparative.detail.downloadUnavailable")}
              </p>
            )
          ) : null}

          {timedOut && ACTIVE_STATES.has(artifact.state) ? (
            <Alert
              type="warning"
              showIcon
              title={t("comparative.detail.pollTimedOut", {
                seconds: Math.round(pollDeadlineMs / 1000),
              })}
              data-testid="artifact-poll-timeout"
            />
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
