/** Anonymous BLAST entry point.
 *
 * This route intentionally uses only the public BLAST capability endpoints.
 * The capability is held in React memory and is sent in X-Blast-Token; it is
 * never placed in a URL, query string, local storage, or auth refresh flow.
 *
 * Layout contract: one screen answers "what did I search, is it done, what came
 * back". Form, job status and results share a single card, so a reader never
 * switches tabs or drawers to find the outcome. Every control that changes the
 * query is on the form; the only steps after submitting are waiting and reading.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { CaretRightOutlined as Play, DownloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Flex,
  Form,
  Input,
  Result,
  Row,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import {
  getPublicBlastDatabases,
  getPublicBlastJob,
  getPublicBlastResults,
  submitPublicBlastJob,
  blastDownloadLink,
  blastEngineLabel,
  compatibleBlastDatabases,
  hasCompatibleBlastQueryAlphabet,
  validateBlastFastaStructure,
  BLAST_PROGRAMS,
  BLAST_PROGRAM_COMPATIBILITY,
  type BlastEngine,
  type BlastProgram,
  type BlastDatabase,
  type BlastHit,
  type BlastJob,
} from "@soymutdb/api-client";
import { useSiteContent } from "../../lib/site-content-react";
import { useReleaseId } from "../../lib/release-scope";

export const Route = createFileRoute("/search/blast")({ component: PublicBlastComponent });

const POLL_MS = 2_000;
const TERMINAL = new Set<BlastJob["status"]>(["completed", "failed", "cancelled", "expired"]);

/** FASTA records in the pasted query — reported next to the input so the
 *  reader can see what will actually be submitted without counting headers. */
function fastaRecordCount(sequence: string): number {
  const headers = sequence.split(/\r?\n/).filter((line) => line.trimStart().startsWith(">"));
  return headers.length || (sequence.trim() ? 1 : 0);
}

function PublicBlastComponent() {
  const { t } = useTranslation();
  const releaseId = useReleaseId();
  const { get } = useSiteContent();
  const [engine, setEngine] = React.useState<BlastEngine>("ncbi_blast");
  const [program, setProgram] = React.useState<BlastProgram>("blastp");
  const [database, setDatabase] = React.useState("");
  const [sequence, setSequence] = React.useState("");
  const [evalue, setEvalue] = React.useState("1e-5");
  const [maxHits, setMaxHits] = React.useState("50");
  /** Field-level problems: rendered next to the control they belong to. */
  const [errors, setErrors] = React.useState<Record<string, string>>({});
  /** Failures with no field to attach to (token, transport, expiry). */
  const [error, setError] = React.useState<string | null>(null);
  const [job, setJob] = React.useState<BlastJob | null>(null);
  const [accessToken, setAccessToken] = React.useState<string | null>(null);
  const [expiresAt, setExpiresAt] = React.useState<string | null>(null);

  const databasesQuery = useQuery({
    queryKey: ["public-blast-databases", releaseId],
    queryFn: getPublicBlastDatabases,
    staleTime: 30 * 60 * 1000,
  });
  const databases = compatibleBlastDatabases(databasesQuery.data ?? [], engine, program);
  React.useEffect(() => {
    setDatabase("");
  }, [releaseId, engine, program]);
  React.useEffect(() => {
    if (!database && databases.length) setDatabase(String(databases[0].id));
  }, [database, databases]);

  const selectedDatabase = databases.find((item) => String(item.id) === database);
  const [isSubmitting, setIsSubmitting] = React.useState(false);
  const [page, setPage] = React.useState(1);
  const [clock, setClock] = React.useState(() => Date.now());

  const submit = async () => {
    const found: Record<string, string> = {};
    if (!databases.find((item) => String(item.id) === database)) found.database = t("blastPublic.databaseRequired");
    if (!sequence.trim() || sequence.trim().length < 10) found.sequence = t("blastPublic.sequenceTooShort");
    if (engine === "diamond" && program !== "blastp") found.program = t("blastSearch.incompatible");
    if (
      !Number.isFinite(Number(evalue)) || Number(evalue) <= 0 || Number(evalue) > 1000 ||
      !Number.isInteger(Number(maxHits)) || Number(maxHits) < 1 || Number(maxHits) > 500
    ) found.parameters = t("blastSearch.invalidParameters");
    if (!found.sequence && !hasCompatibleBlastQueryAlphabet(sequence, program)) found.sequence = t("blastSearch.invalidAlphabet");
    // Several records are allowed; each still needs a header and a sequence.
    const fastaError = !found.sequence ? validateBlastFastaStructure(sequence) : null;
    if (fastaError) found.sequence = t(`blastSearch.fasta.${fastaError}`);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    const selected = databases.find((item) => String(item.id) === database)!;
    setIsSubmitting(true);
    setError(null);
    try {
      const response = await submitPublicBlastJob({ program, engine, database: selected.name, sequence, e_value: Number(evalue), max_hits: Number(maxHits) });
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
  // Anonymous downloads expire with the capability; drop the affordance instead
  // of offering a link that will 403. No artifact, no link.
  const download = currentJob && !expired ? blastDownloadLink(publicResults?.download_url, currentJob) : null;

  const reset = () => {
    setJob(null);
    setAccessToken(null);
    setExpiresAt(null);
    setError(null);
    setErrors({});
  };

  const columns: TableColumnsType<BlastHit> = [
    { title: t("blastSearch.queryId"), dataIndex: "query_id", key: "query_id", render: (value: string | null) => value ?? "—" },
    { title: t("blast.hitSubject"), dataIndex: "subject_id", key: "subject_id" },
    { title: t("blast.hitIdentity"), dataIndex: "percent_identity", key: "identity", render: (value: number) => `${value.toFixed(2)}%` },
    { title: t("blast.hitLength"), dataIndex: "alignment_length", key: "length" },
    { title: t("blast.hitEValue"), dataIndex: "evalue", key: "evalue" },
    { title: t("blast.hitScore"), dataIndex: "bit_score", key: "score" },
  ];

  const selectedName = selectedDatabase?.name ?? databases.find((item) => String(item.id) === database)?.name;
  const recordCount = fastaRecordCount(sequence);
  // Provenance of the selected reference, as one compact block instead of a
  // sentence that mixed five fields with separators.
  const provenanceItems: React.ComponentProps<typeof Descriptions>["items"] = selectedDatabase
    ? ([
        ["assembly", selectedDatabase.assembly_name],
        ["release", selectedDatabase.release_id == null ? null : String(selectedDatabase.release_id)],
        ["annotation", selectedDatabase.annotation_version],
        ["type", selectedDatabase.db_type],
        ["license", selectedDatabase.license],
      ] as const)
        .filter(([, value]) => value != null && value !== "")
        .map(([key, value]) => ({ key, label: key, children: String(value) }))
    : [];

  // One status block answers "is it done, and why not" without a second card.
  const statusItems: React.ComponentProps<typeof Descriptions>["items"] = currentJob
    ? ([
        ["blast.jobStatus", <Tag key="status" color={currentJob.status === "completed" ? "success" : currentJob.status === "failed" ? "error" : "processing"} className="m-0 uppercase">{currentJob.status}</Tag>],
        ["blast.engine", blastEngineLabel(currentJob.engine, t("blastSearch.engineUnknown"))],
        ["blast.searchType", currentJob.program],
        ["blast.database", selectedName ?? currentJob.database],
        ["blastPublic.release", currentJob.release_id == null ? null : String(currentJob.release_id)],
      ] as const)
        .filter(([, value]) => value != null && value !== "")
        .map(([label, value]) => ({ key: label, label: t(label), children: value as React.ReactNode }))
    : [];

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
          <Row gutter={[24, 0]}>
            <Col xs={24} md={8}>
              <Form.Item label={t("blastPublic.engine")}>
                <Select
                  aria-label={t("blastPublic.engine")}
                  value={engine}
                  onChange={(value: BlastEngine) => setEngine(value)}
                  options={[
                    { value: "ncbi_blast", label: t("blastSearch.engineNcbi") },
                    { value: "diamond", label: t("blastSearch.engineDiamondBlastp"), disabled: program !== "blastp" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                label={t("blastPublic.program")}
                help={errors.program}
                validateStatus={errors.program ? "error" : undefined}
              >
                <Select
                  aria-label={t("blastPublic.program")}
                  value={program}
                  onChange={(value: BlastProgram) => setProgram(value)}
                  options={BLAST_PROGRAMS
                    .filter((item) => engine === "ncbi_blast" || item.id === "blastp")
                    .map((item) => ({ value: item.id, label: item.label }))}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item
                label={t("blast.database")}
                htmlFor="public-blast-database"
                help={errors.database}
                validateStatus={errors.database ? "error" : undefined}
              >
                {databasesQuery.isLoading ? <Skeleton.Input active block /> : (
                  <Select
                    id="public-blast-database"
                    className="w-full"
                    value={database || undefined}
                    onChange={setDatabase}
                    status={errors.database ? "error" : undefined}
                    options={databases.map((item: BlastDatabase) => ({
                      value: String(item.id),
                      label: `${item.name}${item.assembly_name ? ` · ${item.assembly_name}` : ""}`,
                    }))}
                  />
                )}
              </Form.Item>
            </Col>
          </Row>

          {provenanceItems.length > 0 ? (
            <Descriptions
              className="mb-6"
              size="small"
              bordered
              column={{ xs: 1, sm: 2, md: 3, lg: 5 }}
              title={<span className="text-sm font-medium">{t("blastSearch.provenance")}</span>}
              items={provenanceItems}
            />
          ) : null}

          <Form.Item
            label={BLAST_PROGRAM_COMPATIBILITY[program].query === "prot" ? t("blastSearch.proteinInput") : t("blastSearch.nucleotideInput")}
            htmlFor="public-blast-sequence"
            help={errors.sequence}
            validateStatus={errors.sequence ? "error" : undefined}
            extra={
              recordCount > 0 && !errors.sequence ? (
                <Typography.Text type="secondary" className="text-xs">
                  {t("blastPublic.fastaDetected", { count: recordCount })}
                </Typography.Text>
              ) : null
            }
          >
            <Input.TextArea
              id="public-blast-sequence"
              value={sequence}
              onChange={(event) => setSequence(event.target.value)}
              autoSize={{ minRows: 6, maxRows: 14 }}
              status={errors.sequence ? "error" : undefined}
              className="font-mono text-sm"
              placeholder={t(BLAST_PROGRAM_COMPATIBILITY[program].query === "prot" ? "blastPublic.sequencePlaceholder" : "blastSearch.nucleotidePlaceholder")}
            />
          </Form.Item>

          <Row gutter={[24, 0]}>
            <Col xs={12} md={6}>
              <Form.Item
                label={t("blast.eValue")}
                htmlFor="public-blast-evalue"
                help={errors.parameters}
                validateStatus={errors.parameters ? "error" : undefined}
              >
                <Input
                  id="public-blast-evalue"
                  className="font-mono"
                  value={evalue}
                  status={errors.parameters ? "error" : undefined}
                  onChange={(event) => setEvalue(event.target.value)}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={6}>
              <Form.Item
                label={t("blast.maxHits")}
                htmlFor="public-blast-maxhits"
                help={errors.parameters ? " " : undefined}
                validateStatus={errors.parameters ? "error" : undefined}
              >
                <Input
                  id="public-blast-maxhits"
                  className="font-mono"
                  type="number"
                  min={1}
                  max={500}
                  value={maxHits}
                  status={errors.parameters ? "error" : undefined}
                  onChange={(event) => setMaxHits(event.target.value)}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label=" " colon={false}>
                <Typography.Text type="secondary" className="text-xs">{t("blast.parametersHint")}</Typography.Text>
              </Form.Item>
            </Col>
          </Row>

          <Flex wrap gap={12} align="center">
            <Button type="primary" htmlType="submit" size="large" loading={isSubmitting} disabled={Boolean(job && !expired)} icon={<Play aria-hidden />}>
              {t("blastPublic.submit")}
            </Button>
            {job ? <Button size="large" onClick={reset}>{t("blastPublic.newSearch")}</Button> : null}
          </Flex>
        </Form>
        {error ? (
          // Validation and submission failures go through `title`: AntD 6
          // dropped the legacy `message` rendering, so this is the only prop
          // that reaches the DOM.
          <Alert className="mt-4" type="error" showIcon title={error} />
        ) : null}
        {databasesQuery.isError ? <Alert className="mt-4" type="error" showIcon title={t("blastPublic.databasesFailed")} /> : null}
      </Card>

      {/* Outcome: status and results in one place, right under the form. */}
      {currentJob ? (
        <Card
          className="mt-6"
          title={<span className="text-base">{t("blastPublic.resultsFor", { job: currentJob.id.slice(0, 12) })}</span>}
          extra={
            download ? (
              <Button
                type="primary"
                icon={<DownloadOutlined aria-hidden />}
                href={download.href}
                download={download.filename}
                target="_blank"
                rel="noreferrer"
                title={t("blastPublic.artifactHint")}
              >
                {t("blastPublic.download")}
              </Button>
            ) : null
          }
        >
          {statusQuery.error ? (
            <Alert type="error" showIcon title={t("blastPublic.accessFailed")} />
          ) : expired ? (
            <Result status="warning" title={t("blastPublic.expired")} subTitle={t("blastPublic.expiredHint")} />
          ) : (
            <>
              <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} items={statusItems} />
              {currentJob.error_message ? (
                <Alert className="mt-4" type="error" showIcon title={currentJob.error_message} />
              ) : null}
              {(currentJob.status === "pending" || currentJob.status === "running") ? (
                <Typography.Text type="secondary" className="mt-4 block">{t("blastPublic.running")}</Typography.Text>
              ) : null}
              {currentJob.status === "completed" && !expired && !download ? (
                <Typography.Text type="secondary" className="mt-4 block text-xs">{t("blastPublic.noArtifact")}</Typography.Text>
              ) : null}
            </>
          )}

          {resultsQuery.error ? <Alert className="mt-4" type="error" showIcon title={t("blastPublic.accessFailed")} /> : null}
          {publicResults && publicResults.status !== "completed" && !resultsQuery.error && !expired ? (
            <Alert className="mt-4" type="info" showIcon title={t("blastPublic.resultsNotReady")} />
          ) : null}

          {currentJob.status === "completed" && publicResults?.status === "completed" && !expired && !requestError ? (
            resultsQuery.isLoading ? <Skeleton active /> : (publicResults.items?.length ?? 0) > 0 ? (
              <Table
                className="mt-4"
                scroll={{ x: "max-content" }}
                rowKey={(row) => `${row.query_id ?? ""}-${row.subject_id}-${row.hsp_num}`}
                columns={columns}
                dataSource={publicResults.items}
                pagination={{ current: page, pageSize: 25, total: publicResults.total, onChange: (nextPage) => setPage(nextPage) }}
              />
            ) : (
              <Empty className="mt-4" description={t("blast.noHits")} />
            )
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
