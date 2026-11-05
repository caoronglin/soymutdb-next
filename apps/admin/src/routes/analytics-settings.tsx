import { BarChartOutlined, CopyOutlined, CheckOutlined, ExportOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, PageContainer, ProCard, Tag, Typography } from "@/lib/antd";
const ENV_VAR = "VITE_CLOUDFLARE_ANALYTICS_TOKEN";
const BEACON_ORIGIN = "https://static.cloudflareinsights.com/beacon.min.js";
const CF_DASHBOARD_ANALYTICS_URL =
  "https://dash.cloudflare.com/?to=/:account/web-analytics";

/**
 * Analytics Settings (C3) — documentation-only configuration page for
 * Cloudflare Web Analytics.
 *
 * The beacon token is a build-time VITE_* variable injected into the portal
 * HTML (apps/web, see `config/config.ts` build-time headScripts). This
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
    { title: t("admin.analyticsSettings.step1Title", { defaultValue: "Create a Web Analytics site" }), desc: t("admin.analyticsSettings.step1Desc", { defaultValue: "Cloudflare Dashboard → Analytics & Logs → Web Analytics → Add a site. Pick the portal domain (e.g. www.example.com). No DNS/proxy change is required — the beacon works on any static host." }) },
    { title: t("admin.analyticsSettings.step2Title", { defaultValue: "Copy the beacon token" }), desc: t("admin.analyticsSettings.step2Desc", { defaultValue: "Open the installation snippet of the new site and copy the token from data-cf-beacon (a short hex string)." }) },
    { title: t("admin.analyticsSettings.step3Title", { defaultValue: "Set the Pages environment variable" }), desc: t("admin.analyticsSettings.step3Desc", { defaultValue: "In the soymutdb-web Pages project: Settings → Environment variables → Add variable VITE_CLOUDFLARE_ANALYTICS_TOKEN with the token value (Production and Preview), then redeploy." }) },
    { title: t("admin.analyticsSettings.step4Title", { defaultValue: "Redeploy" }), desc: t("admin.analyticsSettings.step4Desc", { defaultValue: "Trigger a new production deployment so the token is baked into the built index.html. Older deployments created before the variable was added contain no beacon." }) },
    { title: t("admin.analyticsSettings.step5Title", { defaultValue: "Verify" }), desc: t("admin.analyticsSettings.step5Desc", { defaultValue: "Open the portal and view the page source: it should contain static.cloudflareinsights.com/beacon.min.js. Traffic then appears in Cloudflare Dashboard → Web Analytics (may take a few minutes)." }) },
  ];

  return (
    <PageContainer
      title={t("admin.analyticsSettings.title", { defaultValue: "Analytics Settings" })}
      subTitle={t("admin.analyticsSettings.description", { defaultValue: "Visitor statistics for the public portal via Cloudflare Web Analytics." })}
    >
      <div className="space-y-6">
        {/* Overview */}
        <ProCard>

            <Typography.Title level={5}>
              <BarChartOutlined className="size-4 text-primary" />
              {t("admin.analyticsSettings.overviewTitle", { defaultValue: "Overview" })}
            </Typography.Title>
            <Typography.Text type="secondary">{t("admin.analyticsSettings.overviewDesc", { defaultValue: "Cloudflare Web Analytics is a free, privacy-first, cookie-free traffic analytics service. The portal (apps/web) loads it through a single static JavaScript beacon embedded at build time — no Workers, KV or D1 involved, so the deployment stays pure static hosting." })}</Typography.Text>

          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <Tag color="success">{t("admin.analyticsSettings.badgeCloudflare", { defaultValue: "Cloudflare Web Analytics" })}</Tag>
              <Tag color="default">{t("admin.analyticsSettings.badgeBeacon", { defaultValue: "Beacon (static JS)" })}</Tag>
              <Tag color="default">{t("admin.analyticsSettings.badgeBuildTimeInjection", { defaultValue: "Build-time injection" })}</Tag>
              <Tag color="default">{t("admin.analyticsSettings.badgeCookieFree", { defaultValue: "Cookie-free" })}</Tag>
            </div>
            <p className="text-sm text-muted-foreground">{t("admin.analyticsSettings.beaconNote", { defaultValue: "Only the public portal (apps/web) loads the beacon; this admin console and the JBrowse app do not." })}</p>
            <div className="flex items-center gap-3">
              <Button

                size="small"
                onClick={() => window.open(CF_DASHBOARD_ANALYTICS_URL, "_blank", "noopener,noreferrer")}
              >
                <ExportOutlined className="size-4" />
                {t("admin.analyticsSettings.dashboardLink", { defaultValue: "Open Cloudflare Dashboard" })}
              </Button>
            </div>
          </div>
        </ProCard>

        {/* Configuration steps */}
        <ProCard>

            <Typography.Title level={5}>
              <InfoCircleOutlined className="size-4 text-primary" />
              {t("admin.analyticsSettings.configTitle", { defaultValue: "Configuration" })}
            </Typography.Title>
            <Typography.Text type="secondary">{t("admin.analyticsSettings.configDesc", { defaultValue: "The beacon token is a VITE_* variable injected at BUILD time into the portal HTML. This page is a documentation-only interface: it does not store the token, does not call the backend, and cannot change the running site." })}</Typography.Text>

          <div className="space-y-5">
            {/* Environment variable name (copyable) */}
            <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {t("admin.analyticsSettings.envVar", { defaultValue: "Environment variable" })}
                </p>
                <code className="block truncate font-mono text-sm">{ENV_VAR}</code>
                <p className="mt-1 text-xs text-muted-foreground">{t("admin.analyticsSettings.envVarHelp", { defaultValue: "Set it in the Cloudflare Pages project \"soymutdb-web\" → Settings → Environment variables, for both Production and Preview. Values cannot be read back from the dashboard after saving." })}</p>
              </div>
              <Button  size="small" onClick={copyEnvVar} aria-live="polite">
                {copied ? <CheckOutlined className="size-4 text-emerald-500" /> : <CopyOutlined className="size-4" />}
                {copied ? t("admin.analyticsSettings.copied", { defaultValue: "Copied" }) : t("admin.analyticsSettings.copy", { defaultValue: "Copy" })}
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
        </ProCard>

        {/* Injection status detection */}
        <ProCard>

            <Typography.Title level={5}>
              <BarChartOutlined className="size-4 text-primary" />
              {t("admin.analyticsSettings.statusTitle", { defaultValue: "Injection status" })}
            </Typography.Title>
            <Typography.Text type="secondary">{t("admin.analyticsSettings.statusDesc", { defaultValue: "The token is injected into the portal HTML at build time, so this page cannot detect the current injection state at runtime (the admin bundle never carries the value). Use the checks below instead." })}</Typography.Text>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Tag color="default">{t("admin.analyticsSettings.badgeBuildTime", { defaultValue: "Build-time" })}</Tag>
              <Tag color="default">{t("admin.analyticsSettings.badgeRuntimeDetection", { defaultValue: "Runtime detection: N/A" })}</Tag>
            </div>
            <div className="rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs">
              {BEACON_ORIGIN}
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              <li>{t("admin.analyticsSettings.statusHint1", { defaultValue: "Open the portal in a browser → View page source (Ctrl/Cmd+U) → search for \"cloudflareinsights\". Found means the beacon is injected in the current deployment." })}</li>
              <li>{t("admin.analyticsSettings.statusHint2", { defaultValue: "Or check Cloudflare Dashboard → Web Analytics: if the site shows traffic shortly after a deployment, the beacon is working." })}</li>
            </ul>
          </div>
        </ProCard>

        {/* Legacy self-hosted analytics note */}
        <ProCard>

            <Typography.Title level={5}>
              <BarChartOutlined className="size-4 text-primary" />
              {t("admin.analyticsSettings.legacyTitle", { defaultValue: "Legacy self-hosted analytics" })}
            </Typography.Title>
            <Typography.Text type="secondary">{t("admin.analyticsSettings.legacyDesc", { defaultValue: "The native PostgreSQL analytics endpoints (/analytics, /stats) and the portal /analytics page remain available for on-site data; Cloudflare Web Analytics is the primary visitor-statistics channel." })}</Typography.Text>

        </ProCard>
      </div>
    </PageContainer>
  );
}
