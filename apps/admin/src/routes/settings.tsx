import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Save, Globe, Database, Mail, Shield, Eye } from "lucide-react";
import { http } from "@soymutdb/api-client";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  Input,
  Label,
  PageHeader,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Textarea,
  Badge,
} from "@soymutdb/ui";
import { ConfirmDialog } from "../components/confirm-dialog";

export default function SettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [saveTarget, setSaveTarget] = useState<string | null>(null);

  const [general, setGeneral] = useState({
    siteName: "SoyMutDB",
    siteDescription: "Comprehensive soybean mutant database for functional genomics research",
    defaultLanguage: "en",
    defaultTheme: "light",
  });

  const [data, setData] = useState({
    defaultAssembly: "Wm82v4.0",
    maxExportRecords: "10000",
    cacheTtlSeconds: "300",
    enableClickhouse: "true",
  });

  const [email, setEmail] = useState({
    smtpHost: "",
    smtpPort: "587",
    fromAddress: "noreply@soymutdb.org",
    enableNotifications: "true",
  });

  const [security, setSecurity] = useState({
    sessionTimeoutMinutes: "60",
    maxLoginAttempts: "5",
    requireTwoFactor: "false",
    passwordMinLength: "8",
  });

  const [cdn, setCdn] = useState({
    cdn_enabled: "false",
    gsap_url: "",
    lenis_url: "",
    echarts_url: "",
  });

  const [filePreview, setFilePreview] = useState({
    enabled: "true",
    max_size_mb: "10",
    enabled_formats: "fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt",
  });

  useEffect(() => {
    http.get("/admin/cdn-config").then((res: any) => {
      if (res) {
        setCdn({
          cdn_enabled: String(res.cdn_enabled ?? false),
          gsap_url: res.cdn_urls?.gsap ?? "",
          lenis_url: res.cdn_urls?.lenis ?? "",
          echarts_url: res.cdn_urls?.echarts ?? "",
        });
      }
    }).catch(() => {});
  }, []);

  useEffect(() => {
    http.get("/admin/settings/file_preview").then((res: any) => {
      if (res && typeof res === "object") {
        setFilePreview({
          enabled: String(res.enabled ?? "true"),
          max_size_mb: String(res.max_size_mb ?? "10"),
          enabled_formats: String(res.enabled_formats ?? "fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt"),
        });
      }
    }).catch(() => {});
  }, []);

  const saveMutation = useMutation({
    mutationFn: async (params: { section: string; values: Record<string, string> }) => {
      return http.put(`/admin/settings/${params.section}`, {
        json: params.values,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      setSaveTarget(null);
    },
  });

  const handleSave = (section: string, values: Record<string, string>) => {
    setSaveTarget(section);
    saveMutation.mutate({ section, values });
  };

  const cdnMutation = useMutation({
    mutationFn: async () => {
      return http.put("/admin/cdn-config", {
        json: {
          cdn_enabled: cdn.cdn_enabled === "true",
          cdn_urls: {
            gsap: cdn.gsap_url || undefined,
            lenis: cdn.lenis_url || undefined,
            echarts: cdn.echarts_url || undefined,
          },
        },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      setSaveTarget("cdn");
    },
  });

  const handleCdnSave = () => {
    cdnMutation.mutate();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="System Settings"
        description="Configure global platform settings. Changes require administrator approval."
      />

      {/* General */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="size-4 text-primary" />
            General
          </CardTitle>
          <CardDescription>Site-wide configuration</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="site-name">Site Name</Label>
              <Input
                id="site-name"
                value={general.siteName}
                onChange={(e) => setGeneral({ ...general, siteName: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="default-lang">Default Language</Label>
              <Select
                value={general.defaultLanguage}
                onValueChange={(v) => setGeneral({ ...general, defaultLanguage: v })}
              >
                <SelectTrigger id="default-lang">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="zh">中文</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="site-desc">Site Description</Label>
            <Textarea
              id="site-desc"
              value={general.siteDescription}
              onChange={(e) => setGeneral({ ...general, siteDescription: e.target.value })}
              rows={2}
            />
          </div>
          <div className="flex justify-end">
            <Button onClick={() => handleSave("general", general)}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Data */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Database className="size-4 text-primary" />
            Data & Storage
          </CardTitle>
          <CardDescription>Database and storage configuration</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="default-assembly">Default Assembly</Label>
              <Input
                id="default-assembly"
                value={data.defaultAssembly}
                onChange={(e) => setData({ ...data, defaultAssembly: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max-export">Max Export Records</Label>
              <Input
                id="max-export"
                type="number"
                value={data.maxExportRecords}
                onChange={(e) => setData({ ...data, maxExportRecords: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cache-ttl">Cache TTL (seconds)</Label>
              <Input
                id="cache-ttl"
                type="number"
                value={data.cacheTtlSeconds}
                onChange={(e) => setData({ ...data, cacheTtlSeconds: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>ClickHouse Analytics</Label>
              <div className="flex items-center gap-2 pt-2">
                <Badge variant={data.enableClickhouse === "true" ? "success" : "secondary"}>
                  {data.enableClickhouse === "true" ? "Enabled" : "Disabled"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setData({
                      ...data,
                      enableClickhouse: data.enableClickhouse === "true" ? "false" : "true",
                    })
                  }
                >
                  Toggle
                </Button>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => handleSave("data", data)}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Email */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Mail className="size-4 text-primary" />
            Email & Notifications
          </CardTitle>
          <CardDescription>SMTP configuration for system emails</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="smtp-host">SMTP Host</Label>
              <Input
                id="smtp-host"
                value={email.smtpHost}
                onChange={(e) => setEmail({ ...email, smtpHost: e.target.value })}
                placeholder="smtp.gmail.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="smtp-port">SMTP Port</Label>
              <Input
                id="smtp-port"
                type="number"
                value={email.smtpPort}
                onChange={(e) => setEmail({ ...email, smtpPort: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="from-addr">From Address</Label>
              <Input
                id="from-addr"
                type="email"
                value={email.fromAddress}
                onChange={(e) => setEmail({ ...email, fromAddress: e.target.value })}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => handleSave("email", email)}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Shield className="size-4 text-primary" />
            Security
          </CardTitle>
          <CardDescription>Authentication and access control</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="session-timeout">Session Timeout (minutes)</Label>
              <Input
                id="session-timeout"
                type="number"
                value={security.sessionTimeoutMinutes}
                onChange={(e) => setSecurity({ ...security, sessionTimeoutMinutes: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="max-login">Max Login Attempts</Label>
              <Input
                id="max-login"
                type="number"
                value={security.maxLoginAttempts}
                onChange={(e) => setSecurity({ ...security, maxLoginAttempts: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pw-min">Password Min Length</Label>
              <Input
                id="pw-min"
                type="number"
                value={security.passwordMinLength}
                onChange={(e) => setSecurity({ ...security, passwordMinLength: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Two-Factor Auth</Label>
              <div className="flex items-center gap-2 pt-2">
                <Badge variant={security.requireTwoFactor === "true" ? "success" : "secondary"}>
                  {security.requireTwoFactor === "true" ? "Required" : "Optional"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setSecurity({
                      ...security,
                      requireTwoFactor: security.requireTwoFactor === "true" ? "false" : "true",
                    })
                  }
                >
                  Toggle
                </Button>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => handleSave("security", security)}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* CDN Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Globe className="size-4 text-primary" />
            CDN Configuration
          </CardTitle>
          <CardDescription>External CDN URLs for frontend assets</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>CDN Enabled</Label>
              <div className="flex items-center gap-2 pt-2">
                <Badge variant={cdn.cdn_enabled === "true" ? "success" : "secondary"}>
                  {cdn.cdn_enabled === "true" ? "Enabled" : "Disabled"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setCdn({
                      ...cdn,
                      cdn_enabled: cdn.cdn_enabled === "true" ? "false" : "true",
                    })
                  }
                >
                  Toggle
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cdn-gsap">GSAP CDN URL</Label>
              <Input
                id="cdn-gsap"
                value={cdn.gsap_url}
                onChange={(e) => setCdn({ ...cdn, gsap_url: e.target.value })}
                placeholder="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cdn-lenis">Lenis CDN URL</Label>
              <Input
                id="cdn-lenis"
                value={cdn.lenis_url}
                onChange={(e) => setCdn({ ...cdn, lenis_url: e.target.value })}
                placeholder="https://unpkg.com/lenis@1.1.18/dist/lenis.min.js"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="cdn-echarts">ECharts CDN URL</Label>
              <Input
                id="cdn-echarts"
                value={cdn.echarts_url}
                onChange={(e) => setCdn({ ...cdn, echarts_url: e.target.value })}
                placeholder="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            CDN URLs are used at build time. Changes require a rebuild to take effect. For
            production, consider nginx edge caching as a fallback.
          </p>
          <div className="flex justify-end">
            <Button onClick={handleCdnSave}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* File Preview Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Eye className="size-4 text-primary" />
            {t("admin.file_preview")}
          </CardTitle>
          <CardDescription>Configure inline file preview behavior</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>{t("admin.file_preview_enabled")}</Label>
              <div className="flex items-center gap-2 pt-2">
                <Badge variant={filePreview.enabled === "true" ? "success" : "secondary"}>
                  {filePreview.enabled === "true" ? "Enabled" : "Disabled"}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    setFilePreview({
                      ...filePreview,
                      enabled: filePreview.enabled === "true" ? "false" : "true",
                    })
                  }
                >
                  Toggle
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="fp-max-size">{t("admin.file_preview_max_size")}</Label>
              <Input
                id="fp-max-size"
                type="number"
                min={1}
                max={100}
                value={filePreview.max_size_mb}
                onChange={(e) =>
                  setFilePreview({ ...filePreview, max_size_mb: e.target.value })
                }
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="fp-formats">{t("admin.file_preview_formats")}</Label>
              <Input
                id="fp-formats"
                value={filePreview.enabled_formats}
                onChange={(e) =>
                  setFilePreview({ ...filePreview, enabled_formats: e.target.value })
                }
                placeholder="fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt"
              />
              <p className="text-xs text-muted-foreground">
                Comma-separated list of supported file formats.
              </p>
            </div>
          </div>
          <div className="flex justify-end">
            <Button onClick={() => handleSave("file_preview", filePreview)}>
              <Save className="size-4" />
              Save Changes
            </Button>
          </div>
        </CardContent>
      </Card>

      {saveTarget && (
        <ConfirmDialog
          open={Boolean(saveTarget)}
          onOpenChange={(open) => !open && setSaveTarget(null)}
          title="Settings Saved"
          description={`The ${saveTarget} settings have been updated successfully.`}
          confirmLabel="OK"
          onConfirm={() => setSaveTarget(null)}
        />
      )}
    </div>
  );
}
