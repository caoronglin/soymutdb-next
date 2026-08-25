import { BarChartOutlined, CopyOutlined, CheckOutlined, ExportOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge, Button, Card, Typography } from "@/lib/antd";
const ENV_VAR = "VITE_CLOUDFLARE_ANALYTICS_TOKEN";
const BEACON_ORIGIN = "https://static.cloudflareinsights.com/beacon.min.js";
const CF_DASHBOARD_ANALYTICS_URL =
  "https://dash.cloudflare.com/?to=/:account/web-analytics";

/**
 * Analytics Settings (C3) — documentation-only configuration page for
 * Cloudflare Web Analytics.
 *
 * The beacon token is a build-time VITE_* variable injected into the portal
 * HTML (apps/web, see vite.config.ts `cloudflareWebAnalytics` plugin). This
 * page deliberately does NOT store the token anywhere: it only documents how
 * to configure it in the Cloudflare Pages dashboard and how to verify the
 * injection, and links to the Cloudflare dashboard. No backend calls.
 */
export default function AnalyticsSettingsPage() {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  const copyEnvVar = async () => {
    try {
      await navigator.clipboard.writeText(ENV_VAR);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable (e.g. non-secure context) — no-op.
    }
  };

  const steps = [
    { title: t("analyticsSettings.step1Title"), desc: t("analyticsSettings.step1Desc") },
    { title: t("analyticsSettings.step2Title"), desc: t("analyticsSettings.step2Desc") },
    { title: t("analyticsSettings.step3Title"), desc: t("analyticsSettings.step3Desc") },
    { title: t("analyticsSettings.step4Title"), desc: t("analyticsSettings.step4Desc") },
    { title: t("analyticsSettings.step5Title"), desc: t("analyticsSettings.step5Desc") },
  ];

  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>{t("analyticsSettings.title")}</Typography.Title><Typography.Text type="secondary">{t("analyticsSettings.description")}</Typography.Text></div>

      {/* Overview */}
      <Card>

          <Typography.Title level={5}>
            <BarChartOutlined className="size-4 text-primary" />
            {t("analyticsSettings.overviewTitle")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("analyticsSettings.overviewDesc")}</Typography.Text>

        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge color="success">Cloudflare Web Analytics</Badge>
            <Badge >Beacon (static JS)</Badge>
            <Badge >Build-time injection</Badge>
            <Badge >Cookie-free</Badge>
          </div>
          <p className="text-sm text-muted-foreground">{t("analyticsSettings.beaconNote")}</p>
          <div className="flex items-center gap-3">
            <Button

              size="small"
              onClick={() => window.open(CF_DASHBOARD_ANALYTICS_URL, "_blank", "noopener,noreferrer")}
            >
              <ExportOutlined className="size-4" />
              {t("analyticsSettings.dashboardLink")}
            </Button>
          </div>
        </div>
      </Card>

      {/* Configuration steps */}
      <Card>

          <Typography.Title level={5}>
            <InfoCircleOutlined className="size-4 text-primary" />
            {t("analyticsSettings.configTitle")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("analyticsSettings.configDesc")}</Typography.Text>

        <div className="space-y-5">
          {/* Environment variable name (copyable) */}
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {t("analyticsSettings.envVar")}
              </p>
              <code className="block truncate font-mono text-sm">{ENV_VAR}</code>
              <p className="mt-1 text-xs text-muted-foreground">{t("analyticsSettings.envVarHelp")}</p>
            </div>
            <Button  size="small" onClick={copyEnvVar} aria-live="polite">
              {copied ? <CheckOutlined className="size-4 text-emerald-500" /> : <CopyOutlined className="size-4" />}
              {copied ? t("analyticsSettings.copied") : t("analyticsSettings.copy")}
            </Button>
          </div>

          {/* Steps */}
          <ol className="space-y-4">
            {steps.map((step, i) => (
              <li key={step.title} className="flex gap-3">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{step.title}</p>
                  <p className="text-sm text-muted-foreground">{step.desc}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </Card>

      {/* Injection status detection */}
      <Card>

          <Typography.Title level={5}>
            <BarChartOutlined className="size-4 text-primary" />
            {t("analyticsSettings.statusTitle")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("analyticsSettings.statusDesc")}</Typography.Text>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge >Build-time</Badge>
            <Badge >Runtime detection: N/A</Badge>
          </div>
          <div className="rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs">
            {BEACON_ORIGIN}
          </div>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>{t("analyticsSettings.statusHint1")}</li>
            <li>{t("analyticsSettings.statusHint2")}</li>
          </ul>
        </div>
      </Card>

      {/* Legacy self-hosted analytics note */}
      <Card>

          <Typography.Title level={5}>
            <BarChartOutlined className="size-4 text-primary" />
            {t("analyticsSettings.legacyTitle")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("analyticsSettings.legacyDesc")}</Typography.Text>

      </Card>
    </div>
  );
}
