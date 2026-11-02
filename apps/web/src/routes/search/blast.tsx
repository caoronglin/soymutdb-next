/** Anonymous BLAST entry point.
 *
 * This route intentionally uses only the public BLAST capability endpoints.
 * The capability is held in React memory and is sent in X-Blast-Token; it is
 * never placed in a URL, query string, local storage, or auth refresh flow.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { CaretRightOutlined as Play, DownloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Form, Input, Result, Select, Skeleton, Table, Tag, Typography, type TableColumnsType } from "@/lib/antd";
import {
  getPublicBlastDatabases,
  getPublicBlastJob,
  getPublicBlastResults,
  submitPublicBlastJob,
  type BlastDatabase,
  type BlastHit,
  type BlastJob,
} from "@soymutdb/api-client";
import { useSiteContent } from "../../lib/site-content-react";
import { useReleaseId } from "../../lib/release-scope";

export const Route = createFileRoute("/search/blast")({ component: PublicBlastComponent });

const POLL_MS = 2_000;
const TERMINAL = new Set<BlastJob["status"]>(["completed", "failed", "cancelled", "expired"]);

function PublicBlastComponent() {
  const { t } = useTranslation();
  const releaseId = useReleaseId();
  const { get } = useSiteContent();
  const [database, setDatabase] = React.useState("");
  const [sequence, setSequence] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [job, setJob] = React.useState<BlastJob | null>(null);
  const [accessToken, setAccessToken] = React.useState<string | null>(null);
  const [expiresAt, setExpiresAt] = React.useState<string | null>(null);

  const databasesQuery = useQuery({
    queryKey: ["public-blast-databases", releaseId],
    queryFn: getPublicBlastDatabases,
    staleTime: 30 * 60 * 1000,
  });
  const databases = (databasesQuery.data ?? []).filter((item) => item.is_active && item.db_type === "prot");
  React.useEffect(() => {
    setDatabase("");
  }, [releaseId]);
  React.useEffect(() => {
    if (!database && databases.length) setDatabase(String(databases[0].id));
  }, [database, databases]);

  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [clock, setClock] = React.useState(() => Date.now());

  const submit = async () => {
    const selected = databases.find((item) => String(item.id) === database);
    if (!selected) { setError(t("blastPublic.databaseRequired")); return; }
    if (!sequence.trim() || sequence.trim().length < 10) { setError(t("blastPublic.sequenceRequired")); return; }
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await submitPublicBlastJob({ program: "blastp", database: selected.name, sequence, e_value: 1e-5, max_hits: 50 });
      setJob(response.job);
      setAccessToken(response.access_token);
      setExpiresAt(response.expires_at);
      setPage(1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("blastPublic.submitFailed"));
    } finally {
      setIsSubmitting(false);
    }
  };

  React.useEffect(() => {
    if (!expiresAt) return;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [expiresAt]);

  const expiredByClock = expiresAt != null && Date.parse(expiresAt) <= clock;
  const statusQuery = useQuery({
    queryKey: ["public-blast-job", job?.id],
    queryFn: () => getPublicBlastJob(job!.id, accessToken!),
    enabled: Boolean(job && accessToken && !TERMINAL.has(job.status) && !expiredByClock),
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const status = query.state.data?.status ?? job?.status;
      return status && TERMINAL.has(status) ? false : POLL_MS;
    },
    retry: false,
  });
  const currentJob = statusQuery.data ?? job;
  const resultsQuery = useQuery({
    queryKey: ["public-blast-results", currentJob?.id, page],
    queryFn: () => getPublicBlastResults(currentJob!.id, accessToken!, { limit: 25, offset: (page - 1) * 25 }),
    enabled: Boolean(currentJob && accessToken && currentJob.status === "completed" && !expiredByClock),
    retry: false,
  });
  const publicResults = resultsQuery.data;
  const requestError = statusQuery.error ?? resultsQuery.error;
  const resultExpired = publicResults?.status === "expired";
  const expired = currentJob?.status === "expired" || resultExpired || expiredByClock;

  const reset = () => {
    setJob(null);
    setAccessToken(null);
    setExpiresAt(null);
    setError(null);
  };

  const columns: TableColumnsType<BlastHit> = [
    { title: t("blast.hitSubject"), dataIndex: "subject_id", key: "subject_id" },
    { title: t("blast.hitIdentity"), dataIndex: "percent_identity", key: "identity", render: (value: number) => `${value.toFixed(2)}%` },
    { title: t("blast.hitLength"), dataIndex: "alignment_length", key: "length" },
    { title: t("blast.hitEValue"), dataIndex: "evalue", key: "evalue" },
    { title: t("blast.hitScore"), dataIndex: "bit_score", key: "score" },
  ];

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-6">
        <p className="eyebrow">{t("blastPublic.eyebrow")}</p>
        <h1 className="text-3xl font-semibold">{t("blastPublic.title")}</h1>
        <Typography.Text type="secondary">{get("blastPublic.subtitle", t("blastPublic.subtitle"))}</Typography.Text>
        <div className="mt-3"><Link to="/blast">{t("blastPublic.loginWorkflow")}</Link></div>
      </div>
      <Card title={t("blastPublic.formTitle")}>
        <Form layout="vertical" onFinish={() => void submit()}>
          <Form.Item label={t("blast.database")} htmlFor="public-blast-database" required>
            {databasesQuery.isLoading ? <Skeleton.Input active /> : (
              <Select id="public-blast-database" className="w-full" value={database || undefined} onChange={setDatabase} options={databases.map((item: BlastDatabase) => ({ value: String(item.id), label: `${item.name}${item.assembly_name ? ` · ${item.assembly_name}` : ""}` }))} />
            )}
          </Form.Item>
          <Form.Item label={t("blast.inputSequence")} htmlFor="public-blast-sequence" required>
            <Input.TextArea id="public-blast-sequence" value={sequence} onChange={(event) => setSequence(event.target.value)} rows={8} placeholder={t("blastPublic.sequencePlaceholder")} />
          </Form.Item>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="primary" htmlType="submit" loading={isSubmitting} disabled={Boolean(job && !expired)} icon={<Play aria-hidden />}>
              {t("blastPublic.submit")}
            </Button>
            {job ? <Button onClick={reset}>{t("blastPublic.newSearch")}</Button> : null}
          </div>
        </Form>
        {error ? <Alert className="mt-4" type="error" showIcon title={error} /> : null}
        {databasesQuery.isError ? <Alert className="mt-4" type="error" showIcon title={t("blastPublic.databasesFailed")} /> : null}
      </Card>

      {currentJob ? (
        <Card className="mt-6" title={t("blastPublic.statusTitle")}>
          {statusQuery.error ? <Alert type="error" showIcon title={t("blastPublic.accessFailed")} /> : expired ? <Result status="warning" title={t("blastPublic.expired")} subTitle={t("blastPublic.expiredHint")} /> : (
            <div className="flex items-center gap-3">
              <Tag color={currentJob.status === "completed" ? "success" : currentJob.status === "failed" ? "error" : "processing"}>{currentJob.status}</Tag>
              {currentJob.status === "pending" || currentJob.status === "running" ? <Typography.Text type="secondary">{t("blastPublic.running")}</Typography.Text> : null}
              {currentJob.assembly_name ? <Typography.Text type="secondary">{currentJob.assembly_name}{currentJob.release_id ? ` · ${t("blastPublic.release")} ${currentJob.release_id}` : ""}</Typography.Text> : null}
              {currentJob.error_message ? <Typography.Text type="danger">{currentJob.error_message}</Typography.Text> : null}
            </div>
          )}
        </Card>
      ) : null}

      {resultsQuery.error ? <Alert className="mt-6" type="error" showIcon title={t("blastPublic.accessFailed")} /> : null}
      {publicResults && publicResults.status !== "completed" && !resultsQuery.error && !expired ? <Alert className="mt-6" type="info" showIcon title={t("blastPublic.resultsNotReady")} /> : null}

      {currentJob?.status === "completed" && publicResults?.status === "completed" && !expired && !requestError ? (
        <Card className="mt-6" title={t("blastPublic.resultsTitle")} extra={publicResults?.download_url ? <Button type="link" icon={<DownloadOutlined />} href={publicResults.download_url} target="_blank" rel="noreferrer">{t("blastPublic.download")}</Button> : null}>
          {resultsQuery.isLoading ? <Skeleton active /> : publicResults?.items?.length ? <Table scroll={{ x: "max-content" }} rowKey={(row) => `${row.subject_id}-${row.hsp_num}`} columns={columns} dataSource={publicResults.items} pagination={{ current: page, pageSize: 25, total: publicResults.total, onChange: (nextPage) => setPage(nextPage) }} /> : <Empty description={t("blast.noHits")} />}
        </Card>
      ) : null}
    </div>
  );
}
