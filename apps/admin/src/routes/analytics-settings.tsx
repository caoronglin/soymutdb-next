import { useState } from "react";
import { useTranslation } from "react-i18next";
import { BarChart3, Copy, Check, ExternalLink, Info } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  PageHeader,
} from "@soymutdb/ui";

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
      <PageHeader
        title={t("analyticsSettings.title")}
        description={t("analyticsSettings.description")}
      />

      {/* Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="size-4 text-primary" />
            {t("analyticsSettings.overviewTitle")}
          </CardTitle>
          <CardDescription>{t("analyticsSettings.overviewDesc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="success">Cloudflare Web Analytics</Badge>
            <Badge variant="secondary">Beacon (static JS)</Badge>
            <Badge variant="secondary">Build-time injection</Badge>
            <Badge variant="secondary">Cookie-free</Badge>
          </div>
          <p className="text-sm text-muted-foreground">{t("analyticsSettings.beaconNote")}</p>
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open(CF_DASHBOARD_ANALYTICS_URL, "_blank", "noopener,noreferrer")}
            >
              <ExternalLink className="size-4" />
              {t("analyticsSettings.dashboardLink")}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Configuration steps */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Info className="size-4 text-primary" />
            {t("analyticsSettings.configTitle")}
          </CardTitle>
          <CardDescription>{t("analyticsSettings.configDesc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Environment variable name (copyable) */}
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {t("analyticsSettings.envVar")}
              </p>
              <code className="block truncate font-mono text-sm">{ENV_VAR}</code>
              <p className="mt-1 text-xs text-muted-foreground">{t("analyticsSettings.envVarHelp")}</p>
            </div>
            <Button variant="outline" size="sm" onClick={copyEnvVar} aria-live="polite">
              {copied ? <Check className="size-4 text-emerald-500" /> : <Copy className="size-4" />}
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
        </CardContent>
      </Card>

      {/* Injection status detection */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="size-4 text-primary" />
            {t("analyticsSettings.statusTitle")}
          </CardTitle>
          <CardDescription>{t("analyticsSettings.statusDesc")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge variant="secondary">Build-time</Badge>
            <Badge variant="secondary">Runtime detection: N/A</Badge>
          </div>
          <div className="rounded-lg border border-border bg-muted/40 p-3 font-mono text-xs">
            {BEACON_ORIGIN}
          </div>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>{t("analyticsSettings.statusHint1")}</li>
            <li>{t("analyticsSettings.statusHint2")}</li>
          </ul>
        </CardContent>
      </Card>

      {/* Legacy self-hosted analytics note */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="size-4 text-primary" />
            {t("analyticsSettings.legacyTitle")}
          </CardTitle>
          <CardDescription>{t("analyticsSettings.legacyDesc")}</CardDescription>
        </CardHeader>
      </Card>
    </div>
  );
}
