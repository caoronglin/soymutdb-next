/**
 * Primer design — second-level catalog of the /search portal (PPTX V2).
 *
 * Pure-frontend primer design: the target sequence is either pasted
 * directly or extracted from the reference via /tools/seqfetch
 * (seqFetchRegion), then designPrimerPair() slides 18-25 nt windows over
 * the 5'/3' thirds and ranks candidate pairs by Tm/GC/length/clamp.
 * Results are shown in a table with copy buttons and a JBrowse 2 link.
 *
 * No Primer3 backend is involved — this is a simplified heuristic tool;
 * the UI notes that wet-lab validation is still required.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "@/lib/antd";
import {
  CopyOutlined,
  ExperimentOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { getAssemblies, seqFetchRegion } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES } from "../../lib/format";
import {
  designPrimerPair,
  parseFasta,
  type PrimerPair,
} from "../../lib/primer-design";

export const Route = createFileRoute("/search/primer")({
  component: PrimerComponent,
});

function PrimerComponent() {
  const { t } = useTranslation();
  const [form] = Form.useForm<PrimerFormValues>();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);
  const [mode, setMode] = React.useState<"region" | "paste">("region");
  const [loading, setLoading] = React.useState(false);
  const [pairs, setPairs] = React.useState<PrimerPair[] | null>(null);
  const [source, setSource] = React.useState<{ assembly?: string; region?: string; length: number } | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];

  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId]);

  const assemblyName = assemblies.find((a) => String(a.id) === assemblyId)?.name;

  const onSubmit = async (values: PrimerFormValues) => {
    setLoading(true);
    setError(null);
    setPairs(null);
    setSource(null);
    try {
      let template = "";
      let region: string | undefined;
      if (mode === "paste") {
        template = values.sequence?.trim() ?? "";
        if (!template) {
          setError(t("search.primer.pasteRequired"));
          return;
        }
        const records = parseFasta(template);
        template = records.length > 0 ? records[0]!.sequence : template;
      } else {
        if (!assemblyName || !values.chromosome || !values.start || !values.end) {
          setError(t("search.primer.regionRequired"));
          return;
        }
        if (values.end - values.start > 10_000) {
          setError(t("search.primer.regionTooLong"));
          return;
        }
        region = `${values.chromosome}:${values.start}-${values.end}`;
        const res = await seqFetchRegion(assemblyName, region);
        if (res.sequence) {
          const records = parseFasta(res.sequence);
          template = records[0]?.sequence ?? "";
        } else if (res.download_url) {
          setError(t("search.primer.regionTooLarge"));
          return;
        }
        if (!template) {
          setError(t("search.primer.noSequence"));
          return;
        }
      }

      const result = designPrimerPair(template);
      setPairs(result);
      setSource({
        assembly: mode === "region" ? assemblyName : undefined,
        region,
        length: template.length,
      });
      if (result.length === 0) {
        message.warning(t("search.primer.noPairs"));
      }
    } catch {
      setError(t("search.primer.fetchFailed"));
    } finally {
      setLoading(false);
    }
  };

  const copySeq = async (seq: string) => {
    try {
      await navigator.clipboard.writeText(seq);
      message.success(t("search.primer.copied"));
    } catch {
      message.error(t("search.primer.copyFailed"));
    }
  };

  const columns = [
    {
      title: t("search.primer.pair"),
      dataIndex: "name",
      key: "name",
      width: 80,
      render: (_: unknown, __: unknown, index: number) => (
        <Typography.Text strong>F{index + 1}/R{index + 1}</Typography.Text>
      ),
    },
    {
      title: t("search.primer.seqF"),
      dataIndex: "forwardSeq",
      key: "forwardSeq",
      render: (_: unknown, pair: PrimerPair) => (
        <Space size={4}>
          <code className="font-mono text-xs break-all">{pair.forward.seq}</code>
          <Button
            size="small"
            type="text"
            icon={<CopyOutlined />}
            aria-label={t("search.primer.copy")}
            onClick={() => void copySeq(pair.forward.seq)}
          />
        </Space>
      ),
    },
    {
      title: t("search.primer.seqR"),
      dataIndex: "reverseSeq",
      key: "reverseSeq",
      render: (_: unknown, pair: PrimerPair) => (
        <Space size={4}>
          <code className="font-mono text-xs break-all">{pair.reverse.seq}</code>
          <Button
            size="small"
            type="text"
            icon={<CopyOutlined />}
            aria-label={t("search.primer.copy")}
            onClick={() => void copySeq(pair.reverse.seq)}
          />
        </Space>
      ),
    },
    {
      title: t("search.primer.tm"),
      dataIndex: "tm",
      key: "tm",
      width: 130,
      render: (_: unknown, pair: PrimerPair) => (
        <span className="tabular-nums">
          {pair.forward.tm}°C / {pair.reverse.tm}°C
        </span>
      ),
    },
    {
      title: t("search.primer.gc"),
      dataIndex: "gc",
      key: "gc",
      width: 90,
      render: (_: unknown, pair: PrimerPair) => (
        <span className="tabular-nums">
          {pair.forward.gc}% / {pair.reverse.gc}%
        </span>
      ),
    },
    {
      title: t("search.primer.product"),
      dataIndex: "productLen",
      key: "productLen",
      width: 90,
      render: (_: unknown, pair: PrimerPair) => (
        <span className="tabular-nums">{pair.productLen} bp</span>
      ),
    },
    {
      title: t("search.primer.clamp"),
      dataIndex: "clamp",
      key: "clamp",
      width: 90,
      render: (_: unknown, pair: PrimerPair) => (
        <Space size={4}>
          {pair.forward.clamp ? <Tag color="green">3′GC</Tag> : <Tag>—</Tag>}
          {pair.reverse.clamp ? <Tag color="green">3′GC</Tag> : <Tag>—</Tag>}
        </Space>
      ),
    },
    {
      title: t("search.primer.score"),
      dataIndex: "score",
      key: "score",
      width: 80,
      render: (_: unknown, pair: PrimerPair) => (
        <span className="tabular-nums">{pair.score}</span>
      ),
    },
    {
      title: t("search.primer.actions"),
      dataIndex: "actions",
      key: "actions",
      width: 120,
      render: (_: unknown, pair: PrimerPair) => (
        <Button
          size="small"
          type="link"
          disabled={!source?.region}
          onClick={() => {
            const locus = source?.region
              ? source.region
              : `${pair.forward.start}-${pair.reverse.end}`;
            const base = import.meta.env.BASE_URL ?? "/";
            window.open(
              `${base}browser?assembly=${encodeURIComponent(source?.assembly ?? "")}&locus=${encodeURIComponent(locus)}`,
              "_blank",
              "noopener",
            );
          }}
        >
          {t("search.primer.gbrowse")}
        </Button>
      ),
    },
  ];

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.primer.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.primer.subtitle")}
        </h2>

        <Alert
          className="mt-6 max-w-3xl"
          type="info"
          showIcon
          message={t("search.primer.disclaimer")}
          description={t("search.primer.desc")}
        />

        <Card className="mt-6 max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <ExperimentOutlined aria-hidden />
            </div>
            <Typography.Paragraph className="mb-0 text-muted-foreground">
              {t("search.primer.howItWorks")}
            </Typography.Paragraph>
          </div>

          <Form
            form={form}
            layout="vertical"
            className="mt-6"
            onFinish={onSubmit}
            initialValues={{ start: undefined, end: undefined }}
          >
            <Space direction="vertical" size="middle" className="w-full">
              <Space.Compact>
                <Button
                  type={mode === "region" ? "primary" : "default"}
                  onClick={() => setMode("region")}
                >
                  {t("search.primer.modeRegion")}
                </Button>
                <Button
                  type={mode === "paste" ? "primary" : "default"}
                  onClick={() => setMode("paste")}
                >
                  {t("search.primer.modePaste")}
                </Button>
              </Space.Compact>

              {mode === "region" ? (
                <div className="grid gap-4 sm:grid-cols-[240px_1fr_1fr_1fr]">
                  <Form.Item label={t("search.primer.assembly")} className="mb-0">
                    <Select
                      value={assemblyId}
                      onChange={(v) => setAssemblyId(v)}
                      placeholder={t("search.genes.assemblyPlaceholder")}
                      loading={assembliesQuery.isLoading}
                      options={assemblies.map((a) => ({
                        value: String(a.id),
                        label: (
                          <span className="flex items-center gap-2">
                            <span>{a.name}</span>
                            {a.is_default ? (
                              <Tag className="m-0 text-[9px] uppercase">Default</Tag>
                            ) : null}
                          </span>
                        ),
                      }))}
                    />
                  </Form.Item>
                  <Form.Item
                    label={t("search.primer.chromosome")}
                    name="chromosome"
                    rules={[{ required: true, message: t("search.primer.chromosomeRequired") }]}
                    className="mb-0"
                  >
                    <Select
                      options={SOYBEAN_CHROMOSOMES.map((c) => ({ value: c, label: c }))}
                      placeholder="chr01"
                    />
                  </Form.Item>
                  <Form.Item
                    label={t("search.primer.start")}
                    name="start"
                    rules={[{ required: true, message: t("search.primer.startRequired") }]}
                    className="mb-0"
                  >
                    <InputNumber min={1} className="w-full" placeholder="1" />
                  </Form.Item>
                  <Form.Item
                    label={t("search.primer.end")}
                    name="end"
                    rules={[{ required: true, message: t("search.primer.endRequired") }]}
                    className="mb-0"
                  >
                    <InputNumber min={1} className="w-full" placeholder="1000" />
                  </Form.Item>
                </div>
              ) : (
                <Form.Item
                  label={t("search.primer.sequence")}
                  name="sequence"
                  rules={[{ required: true, message: t("search.primer.pasteRequired") }]}
                  className="mb-0"
                >
                  <Input.TextArea
                    rows={6}
                    className="font-mono text-xs"
                    placeholder={t("search.primer.sequencePlaceholder")}
                  />
                </Form.Item>
              )}
            </Space>

            <Button
              type="primary"
              htmlType="submit"
              loading={loading}
              icon={<ReloadOutlined />}
              className="mt-4"
            >
              {t("search.primer.submit")}
            </Button>
          </Form>
        </Card>

        {error ? (
          <Alert type="error" showIcon message={error} className="mt-6 max-w-3xl" />
        ) : null}

        {loading ? (
          <Card className="mt-6 max-w-3xl">
            <Spin tip={t("search.primer.designing")}>
              <div className="h-16" />
            </Spin>
          </Card>
        ) : null}

        {pairs !== null && !loading ? (
          <Card
            className="mt-6 max-w-5xl"
            title={
              source
                ? `${source.assembly ?? ""} ${source.region ?? ""} · ${source.length} bp`
                : t("search.primer.results")
            }
            extra={
              source ? (
                <Link
                  to="/search/genes"
                  search={{ q: undefined, run: undefined }}
                >
                  {t("search.primer.geneSearch")}
                </Link>
              ) : null
            }
          >
            {pairs.length > 0 ? (
              <Table
                rowKey={(_, index) => String(index ?? 0)}
                columns={columns}
                dataSource={pairs}
                pagination={false}
                size="small"
                scroll={{ x: 900 }}
              />
            ) : (
              <Empty description={t("search.primer.noPairs")} />
            )}
          </Card>
        ) : null}
      </div>
    </FadeUp>
  );
}

interface PrimerFormValues {
  chromosome?: string;
  start?: number;
  end?: number;
  sequence?: string;
}
