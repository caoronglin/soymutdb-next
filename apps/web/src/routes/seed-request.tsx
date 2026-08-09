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
import { Alert, Button, Form, Input, Result, Typography, type FormProps } from "antd";
import { SendOutlined } from "@ant-design/icons";
import { FadeUp } from "../components/route-motion";
import { secureHttp } from "../lib/api";

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

      <div className="mt-8 max-w-2xl rounded-xl border border-border bg-card p-6">
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
      </div>
    </div>
  );
}
