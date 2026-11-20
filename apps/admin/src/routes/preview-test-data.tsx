/**
 * Local unpublished test-data preview — operator maintenance page.
 *
 * The catalogue pages render this same source table read-only. The one field an
 * operator maintains by hand is `可获得` (availability); everything else comes
 * from the uploaded table and is rewritten on the next import, which is why the
 * backend carries the stored availability value across a re-import.
 *
 * The API route behind this page is loopback-only and dev-only, so the page is
 * a developer tool rather than a general administration surface.
 */
import * as React from "react";
import {
  Alert,
  Button,
  Input,
  InputNumber,
  PageContainer,
  ProCard,
  ProTable,
  Space,
  Switch,
  Tag,
  Typography,
  type ProColumns,
} from "@/lib/antd";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import {
  searchTestDataPreviewMutationSites,
  updateTestDataPreviewMutationSite,
  type TestDataPreviewMutationSite,
} from "@soymutdb/api-client";
import { useTranslation } from "react-i18next";

const DEFAULT_LIMIT = 200;

/**
 * Confidence badge: `H` is high-confidence, anything else is low.
 *
 * Resolved through the locale keys (`admin.previewTestData.confidenceHigh` /
 * `.confidenceLow`) rather than an inline zh/en pair, so the two words live in
 * the same catalog as the rest of the console.
 */
function confidenceKey(confidence: string): { key: string; fallback: string } {
  return confidence === "H"
    ? { key: "admin.previewTestData.confidenceHigh", fallback: "High" }
    : { key: "admin.previewTestData.confidenceLow", fallback: "Low" };
}

export default function PreviewTestDataPage() {
  const { t } = useTranslation();
  const [chromosome, setChromosome] = React.useState("Gm01");
  const [start, setStart] = React.useState<number | null>(1);
  const [end, setEnd] = React.useState<number | null>(2000000000);
  const [applied, setApplied] = React.useState<{
    chromosome: string;
    start: number;
    end: number;
  } | null>(null);
  const [rows, setRows] = React.useState<TestDataPreviewMutationSite[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [savingKey, setSavingKey] = React.useState<string | null>(null);

  const load = React.useCallback(async (query: { chromosome: string; start: number; end: number }) => {
    setLoading(true);
    setError(null);
    try {
      const response = await searchTestDataPreviewMutationSites({
        chromosome: query.chromosome,
        start: query.start,
        end: query.end,
        limit: DEFAULT_LIMIT,
      });
      setRows(response.items);
      setApplied(query);
    } catch (cause) {
      setRows([]);
      setApplied(null);
      setError(
        cause instanceof Error
          ? cause.message
          : t("admin.previewTestData.loadError", {
              defaultValue: "Unable to load preview data. This endpoint is only served on a local dev machine.",
            }),
      );
    } finally {
      setLoading(false);
    }
    // `t` is a real dependency: the fallback message is localized, and i18next
    // hands out a new `t` when the language changes.
  }, [t]);

  const submit = () => {
    if (!chromosome || start == null || end == null || start < 1 || end < start) return;
    void load({ chromosome, start, end });
  };

  const toggleAvailable = async (row: TestDataPreviewMutationSite, next: boolean) => {
    setSavingKey(row.source_site_key);
    setError(null);
    try {
      const updated = await updateTestDataPreviewMutationSite(row.source_site_key, {
        available: next,
      });
      setRows((prev) =>
        prev.map((item) => (item.source_site_key === row.source_site_key ? updated : item)),
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : t("admin.previewTestData.saveError", { defaultValue: "Unable to save the availability flag." }),
      );
    } finally {
      setSavingKey(null);
    }
  };

  /**
   * `editable: false` is the contract guard for this page (design §3.4).
   *
   * The single field an operator may write here is `available`; every other
   * column is owned by the uploaded source table and is rewritten on the next
   * import. ProTable's cell editor is opt-in per column and is the one default
   * that would silently widen that contract, so no column opts in — the only
   * write path stays the `Switch` in the `available` column's `render`.
   */
  const columns: ProColumns<TestDataPreviewMutationSite>[] = [
    {
      title: t("admin.previewTestData.columnSiteKey", { defaultValue: "Mutation site (line parent + position)" }),
      dataIndex: "source_site_key",
      key: "source_site_key",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.source_site_key}</span>,
    },
    { title: t("admin.previewTestData.columnChromosome", { defaultValue: "Chromosome" }), dataIndex: "chromosome", key: "chromosome", width: 100, editable: false },
    {
      title: t("admin.previewTestData.columnPosition", { defaultValue: "Position" }),
      dataIndex: "position",
      key: "position",
      width: 120,
      align: "right",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.position.toLocaleString()}</span>,
    },
    {
      title: t("admin.previewTestData.columnConfidence", { defaultValue: "Confidence" }),
      dataIndex: "confidence",
      key: "confidence",
      width: 90,
      editable: false,
      render: (_, row) => (
        <Tag color={row.confidence === "H" ? "green" : "default"}>
          {t(confidenceKey(row.confidence).key, { defaultValue: confidenceKey(row.confidence).fallback })}
        </Tag>
      ),
    },
    {
      title: t("admin.previewTestData.columnGene", { defaultValue: "Gene" }),
      dataIndex: "gene_id",
      key: "gene_id",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.gene_id}</span>,
    },
    {
      title: t("admin.previewTestData.columnFeature", { defaultValue: "Feature" }),
      dataIndex: "feature",
      key: "feature",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.feature}</span>,
    },
    {
      title: t("admin.previewTestData.columnAvailable", { defaultValue: "Available" }),
      dataIndex: "available",
      key: "available",
      width: 130,
      editable: false,
      render: (_, row) => (
        <Space size={6}>
          <Switch
            size="small"
            checked={row.available}
            loading={savingKey === row.source_site_key}
            onChange={(checked) => void toggleAvailable(row, checked)}
            aria-label={t("admin.previewTestData.toggleAria", {
              key: row.source_site_key,
              defaultValue: "Toggle availability for {{key}}",
            })}
          />
          <span className="text-xs text-muted-foreground">
            {row.available
              ? t("admin.previewTestData.yes", { defaultValue: "Yes" })
              : t("admin.previewTestData.no", { defaultValue: "No" })}
          </span>
        </Space>
      ),
    },
    ...(["gene_v2", "gene_v4", "gene_dn53"] as const).map((field) => ({
      title: (
        <span className="whitespace-nowrap">
          {field === "gene_v2" ? "W82_V2" : field === "gene_v4" ? "W82_V4" : "DN53_V1"}
        </span>
      ),
      dataIndex: field,
      key: field,
      editable: false as const,
      render: (_: unknown, row: TestDataPreviewMutationSite) =>
        row[field] ? (
          <span className="font-mono text-xs">{row[field]}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    })),
  ];

  return (
    <PageContainer
      title={t("admin.previewTestData.title", { defaultValue: "Test data preview" })}
      subTitle={t("admin.previewTestData.subtitle", {
        defaultValue: "Unpublished test data on this machine. Only availability can be edited here; it survives a re-import.",
      })}
    >
      <ProCard>
        <Space wrap align="center" size={12}>
          <span className="text-sm text-muted-foreground">{t("admin.previewTestData.columnChromosome", { defaultValue: "Chromosome" })}</span>
          <Input
            value={chromosome}
            onChange={(event) => setChromosome(event.target.value)}
            style={{ width: 120 }}
            placeholder="Gm01"
          />
          <span className="text-sm text-muted-foreground">{t("admin.previewTestData.start", { defaultValue: "Start" })}</span>
          <InputNumber
            value={start}
            onChange={setStart}
            min={1}
            style={{ width: 150 }}
            placeholder="1"
          />
          <span className="text-sm text-muted-foreground">{t("admin.previewTestData.end", { defaultValue: "End" })}</span>
          <InputNumber
            value={end}
            onChange={setEnd}
            min={1}
            style={{ width: 170 }}
            placeholder="2000000000"
          />
          <Button type="primary" onClick={submit} loading={loading}>
            {t("admin.previewTestData.query", { defaultValue: "Query" })}
          </Button>
        </Space>
      </ProCard>

      {error ? (
        <Alert
          className="mt-4"
          type="error"
          showIcon
          title={t("admin.previewTestData.loadFailedTitle", { defaultValue: "Load failed" })}
          description={error}
        />
      ) : null}

      {applied ? (
        <ProCard className="mt-4">
          <Typography.Text type="secondary" className="text-sm">
            {applied.chromosome}:{applied.start.toLocaleString()}-
            {applied.end.toLocaleString()} ·{" "}
            {t("admin.previewTestData.resultCount", { count: rows.length, defaultValue: "{{count}} rows" })}
          </Typography.Text>
          <ProTable<TestDataPreviewMutationSite>
            {...PRO_LIST_SHELL}
            className="mt-3"
            size="small"
            bordered
            rowKey="source_site_key"
            loading={loading}
            columns={columns}
            dataSource={rows}
            scroll={{ x: "max-content" }}
            pagination={{ pageSize: 20, showSizeChanger: false }}
          />
        </ProCard>
      ) : null}
    </PageContainer>
  );
}
