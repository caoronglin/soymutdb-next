/**
 * Seed request route — public seed request contact form (D1).
 *
 * AntD 5 Form: name / email / institution / country / gene IDs (textarea,
 * parsed client-side, ≤ 200) / notes.  Submit → POST /api/v1/seed-requests;
 * success shows an AntD Result, failure an AntD Alert.  Layout follows the
 * tool pages' PageHeader style (eyebrow + h1, Tailwind skeleton).
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Alert, Button, Card, Form, Input, Result, Typography, type FormProps } from "@/lib/antd";
import { SendOutlined } from "@ant-design/icons";
import { FadeUp } from "../components/route-motion";
import { secureHttp } from "../lib/api";
import { useQuery } from "@tanstack/react-query";
import { fetchHomepageStats } from "@soymutdb/api-client";

export const Route = createFileRoute("/seed-request")({
  component: SeedRequestComponent,
});

/** Max gene IDs per request (mirrors the API's MAX_GENE_IDS). */
const MAX_GENE_IDS = 200;

interface SeedRequestFormValues {
  name: string;
  email: string;
  institution: string;
  country: string;
  geneIds: string;
  notes?: string;
}

interface SeedRequestResponse {
  id: string;
  status: string;
}

/** Parse the gene-ID textarea into a trimmed, deduped, capped list. */
function parseGeneIds(raw: string): string[] {
  return [
    ...new Set(
      raw
        .split(/[\s,;]+/)
        .map((g) => g.trim())
        .filter(Boolean),
    ),
  ];
}

function SeedRequestComponent() {
  const { t } = useTranslation();
  const [form] = Form.useForm<SeedRequestFormValues>();
  const [submitted, setSubmitted] = React.useState<SeedRequestResponse | null>(null);
  const [submitError, setSubmitError] = React.useState<string | null>(null);
  const [submitting, setSubmitting] = React.useState(false);
  const watchedGeneIds = Form.useWatch("geneIds", form) ?? "";
  const requestedGeneCount = parseGeneIds(watchedGeneIds).length;
  const overview = useQuery({
    queryKey: ["seed-request", "public-overview"],
    queryFn: fetchHomepageStats,
    staleTime: 60_000,
    retry: false,
  });

  const onFinish: FormProps<SeedRequestFormValues>["onFinish"] = async (values) => {
    setSubmitError(null);
    const geneIds = parseGeneIds(values.geneIds);
    if (geneIds.length === 0) {
      form.setFields([
        { name: "geneIds", errors: [t("seedRequest.errorNoGenes")] },
      ]);
      return;
    }
    if (geneIds.length > MAX_GENE_IDS) {
      form.setFields([
        {
          name: "geneIds",
          errors: [t("seedRequest.errorTooManyGenes", { max: MAX_GENE_IDS })],
        },
      ]);
      return;
    }
    setSubmitting(true);
    try {
      const response = await secureHttp.post<SeedRequestResponse>("/seed-requests", {
        json: {
          name: values.name,
          email: values.email,
          institution: values.institution,
          country: values.country,
          gene_ids: geneIds,
          notes: values.notes?.trim() || null,
        },
      });
      setSubmitted(response);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : String(err);
      setSubmitError(t("seedRequest.errorSubmit", { message }));
    } finally {
      setSubmitting(false);
    }
  };

  const resetForm = () => {
    form.resetFields();
    setSubmitted(null);
    setSubmitError(null);
  };

  if (submitted) {
    return (
      <div className="container-prose section-rhythm">
        <FadeUp>
          <p className="eyebrow">{t("seedRequest.title")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
            {t("seedRequest.subtitle")}
          </h1>
        </FadeUp>
        <div className="mt-8 max-w-2xl">
          <Result
            status="success"
            title={t("seedRequest.successTitle")}
            subTitle={t("seedRequest.successDesc")}
            extra={[
              <Button key="again" type="primary" onClick={resetForm}>
                {t("seedRequest.submitAnother")}
              </Button>,
            ]}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("seedRequest.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {t("seedRequest.subtitle")}
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-muted-foreground">
          {t("seedRequest.description")}
        </p>
      </FadeUp>

      <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,.85fr)]">
      <Card className="min-w-0 rounded-xl">
        {submitError ? (
          <Alert
            type="error"
            showIcon
            message={t("seedRequest.errorTitle")}
            description={submitError}
            className="mb-4"
          />
        ) : null}

        <Form<SeedRequestFormValues>
          form={form}
          layout="vertical"
          onFinish={onFinish}
          requiredMark="optional"
        >
          <div className="grid gap-0 sm:grid-cols-2 sm:gap-x-4">
            <Form.Item
              name="name"
              label={t("seedRequest.name")}
              rules={[{ required: true, message: t("seedRequest.errorName") }]}
            >
              <Input placeholder={t("seedRequest.namePlaceholder")} />
            </Form.Item>

            <Form.Item
              name="email"
              label={t("seedRequest.email")}
              rules={[
                { required: true, message: t("seedRequest.errorEmail") },
                { type: "email", message: t("seedRequest.errorEmailFormat") },
              ]}
            >
              <Input placeholder="you@example.org" />
            </Form.Item>
          </div>

          <Form.Item
            name="institution"
            label={t("seedRequest.institution")}
            rules={[{ required: true, message: t("seedRequest.errorInstitution") }]}
          >
            <Input placeholder={t("seedRequest.institutionPlaceholder")} />
          </Form.Item>

          <Form.Item
            name="country"
            label={t("seedRequest.country")}
            rules={[{ required: true, message: t("seedRequest.errorCountry") }]}
          >
            <Input placeholder={t("seedRequest.countryPlaceholder")} />
          </Form.Item>

          <Form.Item
            name="geneIds"
            label={t("seedRequest.geneIds")}
            rules={[{ required: true, message: t("seedRequest.errorNoGenes") }]}
            extra={t("seedRequest.geneIdsHint", { max: MAX_GENE_IDS })}
          >
            <Input.TextArea
              rows={5}
              className="font-mono text-sm"
              placeholder={t("seedRequest.geneIdsPlaceholder")}
            />
          </Form.Item>

          <Form.Item name="notes" label={t("seedRequest.notes")}>
            <Input.TextArea
              rows={3}
              placeholder={t("seedRequest.notesPlaceholder")}
            />
          </Form.Item>

          <Button
            type="primary"
            htmlType="submit"
            size="large"
            loading={submitting}
            icon={<SendOutlined />}
            className="mt-2"
          >
            {t("seedRequest.submit")}
          </Button>

          <Typography.Paragraph className="mt-6 mb-0 text-caption text-muted-foreground">
            {t("seedRequest.privacyNote")}
          </Typography.Paragraph>
        </Form>
      </Card>

      <aside aria-label={t("seedRequest.analysisTitle")}>
        <Card className="border-dashed bg-transparent/60 backdrop-blur-sm">
          <p className="eyebrow">{t("seedRequest.analysisEyebrow")}</p>
          <Typography.Title level={4} className="mt-2">{t("seedRequest.analysisTitle")}</Typography.Title>
          <Typography.Text type="secondary">{t("seedRequest.analysisDescription")}</Typography.Text>
          <div className="mt-6 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-border/70 bg-background/50 p-4">
              <div className="text-xs text-muted-foreground">{t("seedRequest.selectedGenes")}</div>
              <div className="mt-1 text-2xl font-semibold">{requestedGeneCount}<span className="text-sm text-muted-foreground"> / {MAX_GENE_IDS}</span></div>
            </div>
            <div className="rounded-lg border border-border/70 bg-background/50 p-4">
              <div className="text-xs text-muted-foreground">{t("seedRequest.availableGenes")}</div>
              <div className="mt-1 text-2xl font-semibold">{overview.data?.gene_count?.toLocaleString() ?? "—"}</div>
            </div>
            <div className="rounded-lg border border-border/70 bg-background/50 p-4">
              <div className="text-xs text-muted-foreground">{t("seedRequest.availableReleases")}</div>
              <div className="mt-1 text-2xl font-semibold">{overview.data?.release_count ?? "—"}</div>
            </div>
            <div className="rounded-lg border border-border/70 bg-background/50 p-4">
              <div className="text-xs text-muted-foreground">{t("seedRequest.mutantLines")}</div>
              <div className="mt-1 text-2xl font-semibold">{overview.data?.mutant_line_count?.toLocaleString() ?? "—"}</div>
            </div>
          </div>
          <div className="mt-5 rounded-lg bg-muted/40 p-4 text-sm text-muted-foreground">
            {t("seedRequest.analysisPrivacy")}
          </div>
          {overview.isError ? <button className="mt-3 text-xs text-muted-foreground underline" onClick={() => void overview.refetch()}>{t("common.retry")}</button> : null}
        </Card>
      </aside>
      </div>
    </div>
  );
}
