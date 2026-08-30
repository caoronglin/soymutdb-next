import { SaveOutlined, GlobalOutlined, DatabaseOutlined, MailOutlined, SafetyOutlined, EyeOutlined, BgColorsOutlined } from "@ant-design/icons";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { adminSettingsApi, http, type SiteVariant } from "@soymutdb/api-client";
import { Typography, Button, Card, ColorPicker, Input, Select, Badge } from "@/lib/antd";
import { ConfirmDialog } from "../components/confirm-dialog";
import { RichEditor } from "../components/rich-editor/rich-editor";
import {
  ANTD_PRIMARY_HEX,
  isValidAdminPrimaryColor,
  readAdminPrimaryColor,
  saveAdminPrimaryColor,
} from "../lib/antd-theme";
import { SETTINGS_CARD_DOMAINS, type SettingsCard, type SettingsDomain } from "./settings/domains";

type SettingsSection =
  | "general"
  | "about"
  | "home"
  | "data"
  | "email"
  | "security"
  | "cdn"
  | "filePreview"
  | "footer"
  | "content";

const initialSettingsLoadState: Record<SettingsSection, boolean> = {
  general: false,
  about: false,
  data: false,
  email: false,
  security: false,
  cdn: false,
  filePreview: false,
  footer: false,
  home: false,
  content: false,
};

const initialSettingsLoadErrorState: Record<SettingsSection, boolean> = {
  general: false,
  about: false,
  data: false,
  email: false,
  security: false,
  cdn: false,
  filePreview: false,
  footer: false,
  home: false,
  content: false,
};

const settingsSectionLabels: Record<SettingsSection, string> = {
  general: "General settings",
  about: "About settings",
  home: "Homepage welcome settings",
  data: "Data & Storage settings",
  email: "Email & Notifications settings",
  security: "Security settings",
  cdn: "CDN Configuration settings",
  filePreview: "File Preview settings",
  footer: "Footer settings",
  content: "Site content settings",
};

const SITE_VARIANT_OPTIONS: Array<{ value: SiteVariant; label: string; description: string }> = [
  {
    value: "external",
    label: "External site",
    description: "Public-facing content served without authentication.",
  },
  {
    value: "internal",
    label: "Internal site",
    description: "Private content for authenticated viewers; deploy behind SSO or a private network.",
  },
];

type SiteContentBaseSection = "about" | "home" | "footer" | "content";

function siteVariantSection(base: SiteContentBaseSection, variant: SiteVariant): string {
  return base + "_" + variant;
}

type ContentArea = "hero" | "tools" | "search" | "blast" | "help" | "generic";

interface ContentField {
  key: string;
  area: ContentArea;
  label: string;
  textarea?: boolean;
  defaultValue: string;
  kind?: "string" | "color" | "integer" | "boolean" | "enum" | "email" | "url";
  allowedValues?: string[];
  maxLength?: number;
}

interface SettingsFieldSchema {
  kind: ContentField["kind"];
  default: string | number | boolean | null;
  allowed_values: string[];
  max_length: number;
}

interface SettingsSchemaResponse {
  sections?: Record<string, { fields?: Record<string, SettingsFieldSchema> }>;
}

/**
 * Content metadata is intentionally not duplicated here. The API registry is
 * authoritative for editable keys, defaults, kinds, and validation limits;
 * this UI only groups the returned keys for presentation.
 */

const CONTENT_AREA_LABELS: Record<ContentArea, string> = {
  hero: "Hero",
  tools: "Tool cards",
  search: "Search pages",
  blast: "BLAST",
  help: "Help",
  generic: "Generic UI",
};

const CONTENT_AREA_ORDER: ContentArea[] = ["hero", "tools", "search", "blast", "help", "generic"];

function isConfigurationRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function SettingsLoadError({ section }: { section: SettingsSection }) {
  const { t } = useTranslation();
  const sectionLabel = t(`admin.settings.section_${section}`, { defaultValue: settingsSectionLabels[section] });
  return (
    <p className="text-sm text-destructive" role="alert">
      {t("admin.settings.loadError", { defaultValue: "Unable to load {{section}}. Refresh the page and try again.", section: sectionLabel })}
    </p>
  );
}

export default function SettingsPage({ domain }: { domain?: SettingsDomain }) {
  const { t } = useTranslation();
  const isCardVisible = (card: SettingsCard) => !domain || SETTINGS_CARD_DOMAINS[card].includes(domain);
  const queryClient = useQueryClient();
  const [saveTarget, setSaveTarget] = useState<string | null>(null);
  const [sectionLoaded, setSectionLoaded] = useState(initialSettingsLoadState);
  const [sectionLoadError, setSectionLoadError] = useState(initialSettingsLoadErrorState);
  const [siteVariant, setSiteVariant] = useState<SiteVariant>("external");
  const aboutSection = siteVariantSection("about", siteVariant);
  const homeSection = siteVariantSection("home", siteVariant);
  const footerSection = siteVariantSection("footer", siteVariant);
  const contentSection = siteVariantSection("content", siteVariant);

  const [general, setGeneral] = useState({
    siteName: "SoyMutDB",
    siteDescription: "Comprehensive multi-species mutant database for functional genomics research (soybean as the first/default species)",
    defaultLanguage: "en",
    defaultTheme: "light",
    primaryColor: readAdminPrimaryColor(),
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
    enabled: false,
    url: "",
  });
  const [cdnVersion, setCdnVersion] = useState<number | null>(null);

  const [filePreview, setFilePreview] = useState({
    enabled: "true",
    max_size_mb: "10",
    enabled_formats: "fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt",
  });

  const [about, setAbout] = useState({
    title_en: "",
    title_zh: "",
    summary_en: "",
    summary_zh: "",
    content_en: "",
    content_zh: "",
  });

  const [home, setHome] = useState({
    welcome_en: "",
    welcome_zh: "",
  });

  const [footer, setFooter] = useState({
    contact_person: "联系人: 周玲",
    contact_phone: "电话: 025-84391957",
    contact_email: "电子邮件: zlingxiaoyao@163.com",
    copyright: "© {{year}} SoyMutDB. All rights reserved.",
    address: "地址: 南京市玄武区钟灵街50号 邮编210014",
  });

  const [siteContent, setSiteContent] = useState<Record<string, string>>({});
  const contentSchemaQuery = useQuery({
    queryKey: ["admin-settings-schema"],
    queryFn: () => http.get<SettingsSchemaResponse>("/admin/settings/schema"),
    staleTime: 5 * 60_000,
  });
  const contentFields = useMemo<ContentField[]>(() => {
    const fields = contentSchemaQuery.data?.sections?.[contentSection]?.fields;
    if (!fields) return [];
    return Object.entries(fields).map(([key, schema]) => {
      const area = key.split(".")[0];
      const safeArea: ContentArea = CONTENT_AREA_ORDER.includes(area as ContentArea)
        ? (area as ContentArea)
        : "generic";
      const defaultValue = schema.default == null ? "" : String(schema.default);
      return {
        key,
        area: safeArea,
        label: key,
        textarea: key.endsWith(".desc") || key.endsWith(".subtitle") || key.endsWith(".a") || key.endsWith(".q"),
        defaultValue,
        kind: schema.kind,
        allowedValues: schema.allowed_values,
        maxLength: schema.max_length,
      };
    });
  }, [contentSchemaQuery.data, contentSection]);

  const primaryColorPresets = useMemo(
    () => [
      {
        label: t("admin.settings.colorPresets", { defaultValue: "SoyMutDB palette" }),
        colors: [ANTD_PRIMARY_HEX, "#1677ff", "#722ed1", "#eb2f96", "#d4380d", "#08979c"],
      },
    ],
    [t],
  );

  useEffect(() => {
    http.get("/admin/settings/general").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, general: true }));
        return;
      }
      setGeneral({
        siteName: String(res.siteName ?? "SoyMutDB"),
        siteDescription: String(
          res.siteDescription ??
            "Comprehensive multi-species mutant database for functional genomics research (soybean as the first/default species)",
        ),
        defaultLanguage: String(res.defaultLanguage ?? "en"),
        defaultTheme: String(res.defaultTheme ?? "light"),
        primaryColor: (() => {
          const candidate = String(res.primaryColor ?? readAdminPrimaryColor());
          return isValidAdminPrimaryColor(candidate) ? candidate.toLowerCase() : ANTD_PRIMARY_HEX;
        })(),
      });
      const primaryColor = String(res.primaryColor ?? readAdminPrimaryColor());
      if (isValidAdminPrimaryColor(primaryColor)) saveAdminPrimaryColor(primaryColor);
      setSectionLoadError((errors) => ({ ...errors, general: false }));
      setSectionLoaded((loaded) => ({ ...loaded, general: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, general: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/data").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, data: true }));
        return;
      }
      setData({
        defaultAssembly: String(res.defaultAssembly ?? "Wm82v4.0"),
        maxExportRecords: String(res.maxExportRecords ?? "10000"),
        cacheTtlSeconds: String(res.cacheTtlSeconds ?? "300"),
        enableClickhouse: String(res.enableClickhouse ?? "true"),
      });
      setSectionLoadError((errors) => ({ ...errors, data: false }));
      setSectionLoaded((loaded) => ({ ...loaded, data: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, data: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/email").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, email: true }));
        return;
      }
      setEmail({
        smtpHost: String(res.smtpHost ?? ""),
        smtpPort: String(res.smtpPort ?? "587"),
        fromAddress: String(res.fromAddress ?? "noreply@soymutdb.org"),
        enableNotifications: String(res.enableNotifications ?? "true"),
      });
      setSectionLoadError((errors) => ({ ...errors, email: false }));
      setSectionLoaded((loaded) => ({ ...loaded, email: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, email: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/security").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, security: true }));
        return;
      }
      setSecurity({
        sessionTimeoutMinutes: String(res.sessionTimeoutMinutes ?? "60"),
        maxLoginAttempts: String(res.maxLoginAttempts ?? "5"),
        requireTwoFactor: String(res.requireTwoFactor ?? "false"),
        passwordMinLength: String(res.passwordMinLength ?? "8"),
      });
      setSectionLoadError((errors) => ({ ...errors, security: false }));
      setSectionLoaded((loaded) => ({ ...loaded, security: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, security: true }));
    });
  }, []);

  useEffect(() => {
    adminSettingsApi.get("cdn").then((document) => {
      setCdn({
        enabled: document.values.enabled === true,
        url: typeof document.values.url === "string" ? document.values.url : "",
      });
      setCdnVersion(document.version);
      setSectionLoadError((errors) => ({ ...errors, cdn: false }));
      setSectionLoaded((loaded) => ({ ...loaded, cdn: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, cdn: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/file_preview").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, filePreview: true }));
        return;
      }
      setFilePreview({
        enabled: String(res.enabled ?? "true"),
        max_size_mb: String(res.max_size_mb ?? "10"),
        enabled_formats: String(res.enabled_formats ?? "fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt"),
      });
      setSectionLoadError((errors) => ({ ...errors, filePreview: false }));
      setSectionLoaded((loaded) => ({ ...loaded, filePreview: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, filePreview: true }));
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    http.get("/admin/settings/" + aboutSection).then((res: unknown) => {
      if (cancelled) return;
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, about: true }));
        return;
      }
      setAbout({
        title_en: String(res.title_en ?? ""),
        title_zh: String(res.title_zh ?? ""),
        summary_en: String(res.summary_en ?? ""),
        summary_zh: String(res.summary_zh ?? ""),
        content_en: String(res.content_en ?? ""),
        content_zh: String(res.content_zh ?? ""),
      });
      setSectionLoadError((errors) => ({ ...errors, about: false }));
      setSectionLoaded((loaded) => ({ ...loaded, about: true }));
    }).catch(() => {
      if (!cancelled) setSectionLoadError((errors) => ({ ...errors, about: true }));
    });
    return () => { cancelled = true; };
  }, [aboutSection]);

  useEffect(() => {
    let cancelled = false;
    http.get("/admin/settings/" + footerSection).then((res: unknown) => {
      if (cancelled) return;
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, footer: true }));
        return;
      }
      setFooter({
        contact_person: String(res.contact_person ?? "联系人: 周玲"),
        contact_phone: String(res.contact_phone ?? "电话: 025-84391957"),
        contact_email: String(res.contact_email ?? "电子邮件: zlingxiaoyao@163.com"),
        copyright: String(res.copyright ?? "© {{year}} SoyMutDB. All rights reserved."),
        address: String(res.address ?? "地址: 南京市玄武区钟灵街50号 邮编210014"),
      });
      setSectionLoadError((errors) => ({ ...errors, footer: false }));
      setSectionLoaded((loaded) => ({ ...loaded, footer: true }));
    }).catch(() => {
      if (!cancelled) setSectionLoadError((errors) => ({ ...errors, footer: true }));
    });
    return () => { cancelled = true; };
  }, [footerSection]);

  useEffect(() => {
    let cancelled = false;
    http.get("/admin/settings/" + homeSection).then((res: unknown) => {
      if (cancelled) return;
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, home: true }));
        return;
      }
      setHome({
        welcome_en: String(res.welcome_en ?? ""),
        welcome_zh: String(res.welcome_zh ?? ""),
      });
      setSectionLoadError((errors) => ({ ...errors, home: false }));
      setSectionLoaded((loaded) => ({ ...loaded, home: true }));
    }).catch(() => {
      if (!cancelled) setSectionLoadError((errors) => ({ ...errors, home: true }));
    });
    return () => { cancelled = true; };
  }, [homeSection]);

  useEffect(() => {
    if (contentSchemaQuery.isError) return;
    const schemaFields = contentSchemaQuery.data?.sections?.[contentSection]?.fields;
    if (!schemaFields) return;
    let cancelled = false;
    http.get("/admin/settings/" + contentSection).then((res: unknown) => {
      if (cancelled) return;
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, content: true }));
        return;
      }
      const merged: Record<string, string> = {};
      for (const [key, schema] of Object.entries(schemaFields)) {
        const value = res[key];
        merged[key] = typeof value === "string" ? value : String(schema.default ?? "");
      }
      setSiteContent(merged);
      setSectionLoadError((errors) => ({ ...errors, content: false }));
      setSectionLoaded((loaded) => ({ ...loaded, content: true }));
    }).catch(() => {
      if (!cancelled) setSectionLoadError((errors) => ({ ...errors, content: true }));
    });
    return () => { cancelled = true; };
  }, [contentSchemaQuery.data, contentSchemaQuery.isError, contentSection]);

  const saveMutation = useMutation({
    mutationFn: async (params: { section: string; values: Record<string, string> }) => {
      return http.put(`/admin/settings/${params.section}`, {
        json: params.values,
      });
    },
    onSuccess: (_response, params) => {
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      setSaveTarget(params.section);
    },
  });

  const handleSave = (section: string, values: Record<string, string>) => {
    setSaveTarget(null);
    saveMutation.mutate({ section, values });
  };

  const cdnMutation = useMutation({
    mutationFn: async () => {
      if (cdnVersion === null) throw new Error("CDN settings have not loaded");
      return adminSettingsApi.patch("cdn", cdnVersion, {
        enabled: cdn.enabled,
        url: cdn.url,
      });
    },
    onSuccess: (document) => {
      setCdn({
        enabled: document.values.enabled === true,
        url: typeof document.values.url === "string" ? document.values.url : "",
      });
      setCdnVersion(document.version);
      queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      setSaveTarget("cdn");
    },
  });

  const handleCdnSave = () => {
    cdnMutation.mutate();
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div><Typography.Title level={2}>{t("admin.settings.title", { defaultValue: "System Settings" })}</Typography.Title><Typography.Text type="secondary">{t("admin.settings.subtitle", { defaultValue: "Configure global platform settings. Changes require administrator approval." })}</Typography.Text></div>

      {/* General */}
      <Card hidden={!isCardVisible("general")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.settings.generalSection", { defaultValue: "General" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.generalSubtitle", { defaultValue: "Site-wide configuration" })}</Typography.Text>
          {sectionLoadError.general && <SettingsLoadError section="general" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="site-name">{t("admin.settings.siteName", { defaultValue: "Site Name" })}</label>
              <Input
                id="site-name"
                value={general.siteName}
                onChange={(e) => setGeneral({ ...general, siteName: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="default-lang">{t("admin.settings.defaultLanguage", { defaultValue: "Default Language" })}</label>
              <Select
                value={general.defaultLanguage}
                onChange={(v) => setGeneral({ ...general, defaultLanguage: v })}
              >


                  <Select.Option value="en">{t("admin.settings.languageEnglish", { defaultValue: "English" })}</Select.Option>
                  <Select.Option value="zh">中文</Select.Option>

              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="site-desc">{t("admin.settings.siteDescription", { defaultValue: "Site Description" })}</label>
            <Input.TextArea
              id="site-desc"
              value={general.siteDescription}
              onChange={(e) => setGeneral({ ...general, siteDescription: e.target.value })}
              rows={2}
            />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-dashed border-border bg-muted/20 p-4">
            <div className="flex min-w-0 items-start gap-3">
              <BgColorsOutlined className="mt-0.5 text-primary" aria-hidden />
              <div className="min-w-0">
                <p className="font-medium">{t("admin.settings.primaryColor", { defaultValue: "Primary color" })}</p>
                <p className="text-sm text-muted-foreground">{t("admin.settings.primaryColorHint", { defaultValue: "Controls Ant Design buttons, links, tags, and selected states." })}</p>
              </div>
            </div>
            <ColorPicker
              value={general.primaryColor}
              format="hex"
              showText
              aria-label={t("admin.settings.primaryColor", { defaultValue: "Primary color" })}
              presets={primaryColorPresets}
              onChangeComplete={(color) => {
                const next = color.toHexString();
                setGeneral((current) => ({ ...current, primaryColor: next }));
                saveAdminPrimaryColor(next);
              }}
            />
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("general", general)}
              disabled={!sectionLoaded.general || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Explicit site variant selector */}
      <Card hidden={!isCardVisible("variant")} className="border-primary/20 bg-primary/[0.03]">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <Typography.Title level={5} className="mb-1 flex items-center gap-2 text-base">
              <GlobalOutlined className="size-4 text-primary" />
              {t("admin.settings.siteVariantTitle", { defaultValue: "Site variant content" })}
            </Typography.Title>
            <Typography.Text type="secondary">
              {t("admin.settings.siteVariantSubtitle", { defaultValue: "Choose which independently generated site you are editing. The choice is stored in a separate, audited settings namespace." })}
            </Typography.Text>
          </div>
          <div className="w-full shrink-0 sm:w-72">
            <label className="sr-only" htmlFor="site-variant">
              {t("admin.settings.siteVariantLabel", { defaultValue: "Site variant" })}
            </label>
            <Select
              id="site-variant"
              value={siteVariant}
              className="w-full"
              onChange={(value) => {
                const nextVariant = value as SiteVariant;
                setSiteVariant(nextVariant);
                setSectionLoaded((loaded) => ({ ...loaded, about: false, home: false, footer: false, content: false }));
                setSectionLoadError((errors) => ({ ...errors, about: false, home: false, footer: false, content: false }));
              }}
            >
              {SITE_VARIANT_OPTIONS.map((option) => (
                <Select.Option key={option.value} value={option.value}>
                  {option.value === "internal"
                    ? t("admin.settings.siteVariantInternal", { defaultValue: "Internal site" })
                    : t("admin.settings.siteVariantExternal", { defaultValue: "External site" })}
                </Select.Option>
              ))}
            </Select>
          </div>
        </div>
        <p className="mt-3 rounded-md border border-border/70 bg-background/70 p-3 text-xs text-muted-foreground" role="status">
          {siteVariant === "internal"
            ? t("admin.settings.internalSiteSecurityNotice", { defaultValue: "Internal content is authenticated and must be deployed behind SSO, Cloudflare Access, VPN, or a private network. This selector is not a substitute for network access control." })
            : t("admin.settings.externalSiteNotice", { defaultValue: "External content is public and can be cached by the edge after a successful audited save." })}
        </p>
      </Card>

      {/* About us content */}
      <Card hidden={!isCardVisible("about")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.about.title")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.about.description")}</Typography.Text>
          {sectionLoadError.about && <SettingsLoadError section="about" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="about-title-en">{t("admin.settings.titleEnglish", { defaultValue: "Title (English)" })}</label>
              <Input
                id="about-title-en"
                value={about.title_en}
                onChange={(e) => setAbout({ ...about, title_en: e.target.value })}
                placeholder={t("admin.settings.placeholderAboutTitle", { defaultValue: "About SoyMutDB" })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-title-zh">{t("admin.settings.titleChinese", { defaultValue: "Title (Chinese)" })}</label>
              <Input
                id="about-title-zh"
                value={about.title_zh}
                onChange={(e) => setAbout({ ...about, title_zh: e.target.value })}
                placeholder="关于我们"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-summary-en">{t("admin.settings.summaryEnglish", { defaultValue: "Summary (English)" })}</label>
              <Input.TextArea
                id="about-summary-en"
                value={about.summary_en}
                onChange={(e) => setAbout({ ...about, summary_en: e.target.value })}
                rows={2}
                placeholder={t("admin.settings.placeholderAboutSummary", { defaultValue: "Short introduction shown on the About page" })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-summary-zh">{t("admin.settings.summaryChinese", { defaultValue: "Summary (Chinese)" })}</label>
              <Input.TextArea
                id="about-summary-zh"
                value={about.summary_zh}
                onChange={(e) => setAbout({ ...about, summary_zh: e.target.value })}
                rows={2}
                placeholder="关于我们页面的简短介绍"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-content-en">{t("admin.settings.contentEnglishLabel", { defaultValue: "Content (English)" })}</label>
              <RichEditor
                value={about.content_en}
                onChange={(html) => setAbout({ ...about, content_en: html })}
                placeholder={t("admin.settings.placeholderAboutContentEnglish", { defaultValue: "Full page content in English (rich text / Markdown supported)" })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-content-zh">{t("admin.settings.contentChineseLabel", { defaultValue: "Content (Chinese)" })}</label>
              <RichEditor
                value={about.content_zh}
                onChange={(html) => setAbout({ ...about, content_zh: html })}
                placeholder="页面内容（中文，富文本 / Markdown 均可）"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave(aboutSection, about)}
              disabled={!sectionLoaded.about || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Homepage welcome content */}
      <Card hidden={!isCardVisible("home")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.settings.homeContentSection", { defaultValue: "Homepage welcome" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("admin.settings.homeContentSubtitle", { defaultValue: "Variant-specific bilingual welcome content for the generated homepage." })}
          </Typography.Text>
          {sectionLoadError.home && <SettingsLoadError section="home" />}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label htmlFor="home-welcome-en">{t("admin.settings.contentEnglishLabel", { defaultValue: "Content (English)" })}</label>
            <RichEditor
              value={home.welcome_en}
              onChange={(html) => setHome({ ...home, welcome_en: html })}
              placeholder={t("admin.settings.homeWelcomeEnglishPlaceholder", { defaultValue: "Welcome content in English" })}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="home-welcome-zh">{t("admin.settings.contentChineseLabel", { defaultValue: "Content (Chinese)" })}</label>
            <RichEditor
              value={home.welcome_zh}
              onChange={(html) => setHome({ ...home, welcome_zh: html })}
              placeholder={t("admin.settings.homeWelcomeChinesePlaceholder", { defaultValue: "首页欢迎内容（中文）" })}
            />
          </div>
        </div>
        <div className="flex justify-end">
          <Button
            onClick={() => handleSave(homeSection, home)}
            disabled={!sectionLoaded.home || saveMutation.isPending}
          >
            <SaveOutlined aria-hidden className="size-4" />
            {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
          </Button>
        </div>
      </Card>

      {/* Data */}
      <Card hidden={!isCardVisible("data")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <DatabaseOutlined className="size-4 text-primary" />
            {t("admin.settings.dataSection", { defaultValue: "Data & Storage" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.dataSubtitle", { defaultValue: "Database and storage configuration" })}</Typography.Text>
          {sectionLoadError.data && <SettingsLoadError section="data" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="default-assembly">{t("admin.settings.defaultAssembly", { defaultValue: "Default Assembly" })}</label>
              <Input
                id="default-assembly"
                value={data.defaultAssembly}
                onChange={(e) => setData({ ...data, defaultAssembly: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-export">{t("admin.settings.maxExportRecords", { defaultValue: "Max Export Records" })}</label>
              <Input
                id="max-export"
                type="number"
                value={data.maxExportRecords}
                onChange={(e) => setData({ ...data, maxExportRecords: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="cache-ttl">{t("admin.settings.cacheTtlSeconds", { defaultValue: "Cache TTL (seconds)" })}</label>
              <Input
                id="cache-ttl"
                type="number"
                value={data.cacheTtlSeconds}
                onChange={(e) => setData({ ...data, cacheTtlSeconds: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label>{t("admin.settings.clickhouseAnalytics", { defaultValue: "ClickHouse Analytics" })}</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={data.enableClickhouse === "true" ? "success" : "secondary"}>
                  {data.enableClickhouse === "true" ? t("admin.settings.enabled", { defaultValue: "Enabled" }) : t("admin.settings.disabled", { defaultValue: "Disabled" })}
                </Badge>
                <Button
                  type="default"
                  size="small"
                  onClick={() =>
                    setData({
                      ...data,
                      enableClickhouse: data.enableClickhouse === "true" ? "false" : "true",
                    })
                  }
                >
                  {t("admin.settings.toggle", { defaultValue: "Toggle" })}
                </Button>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("data", data)}
              disabled={!sectionLoaded.data || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Email */}
      <Card hidden={!isCardVisible("email")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <MailOutlined className="size-4 text-primary" />
            {t("admin.settings.emailSection", { defaultValue: "Email & Notifications" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.emailSubtitle", { defaultValue: "SMTP configuration for system emails" })}</Typography.Text>
          {sectionLoadError.email && <SettingsLoadError section="email" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="smtp-host">{t("admin.settings.smtpHost", { defaultValue: "SMTP Host" })}</label>
              <Input
                id="smtp-host"
                value={email.smtpHost}
                onChange={(e) => setEmail({ ...email, smtpHost: e.target.value })}
                placeholder={t("admin.settings.placeholderSmtpHost", { defaultValue: "smtp.gmail.com" })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="smtp-port">{t("admin.settings.smtpPort", { defaultValue: "SMTP Port" })}</label>
              <Input
                id="smtp-port"
                type="number"
                value={email.smtpPort}
                onChange={(e) => setEmail({ ...email, smtpPort: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="from-addr">{t("admin.settings.fromAddress", { defaultValue: "From Address" })}</label>
              <Input
                id="from-addr"
                type="email"
                value={email.fromAddress}
                onChange={(e) => setEmail({ ...email, fromAddress: e.target.value })}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("email", email)}
              disabled={!sectionLoaded.email || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Security */}
      <Card hidden={!isCardVisible("security")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <SafetyOutlined className="size-4 text-primary" />
            {t("admin.settings.securitySection", { defaultValue: "Security" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.securitySubtitle", { defaultValue: "Authentication and access control" })}</Typography.Text>
          {sectionLoadError.security && <SettingsLoadError section="security" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="session-timeout">{t("admin.settings.sessionTimeout", { defaultValue: "Session Timeout (minutes)" })}</label>
              <Input
                id="session-timeout"
                type="number"
                value={security.sessionTimeoutMinutes}
                onChange={(e) => setSecurity({ ...security, sessionTimeoutMinutes: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-login">{t("admin.settings.maxLoginAttempts", { defaultValue: "Max Login Attempts" })}</label>
              <Input
                id="max-login"
                type="number"
                value={security.maxLoginAttempts}
                onChange={(e) => setSecurity({ ...security, maxLoginAttempts: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="pw-min">{t("admin.settings.passwordMinLength", { defaultValue: "Password Min Length" })}</label>
              <Input
                id="pw-min"
                type="number"
                value={security.passwordMinLength}
                onChange={(e) => setSecurity({ ...security, passwordMinLength: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label>{t("admin.settings.twoFactorAuth", { defaultValue: "Two-Factor Auth" })}</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={security.requireTwoFactor === "true" ? "success" : "secondary"}>
                  {security.requireTwoFactor === "true" ? t("admin.settings.required", { defaultValue: "Required" }) : t("admin.settings.optional", { defaultValue: "Optional" })}
                </Badge>
                <Button
                  type="default"
                  size="small"
                  onClick={() =>
                    setSecurity({
                      ...security,
                      requireTwoFactor: security.requireTwoFactor === "true" ? "false" : "true",
                    })
                  }
                >
                  {t("admin.settings.toggle", { defaultValue: "Toggle" })}
                </Button>
              </div>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("security", security)}
              disabled={!sectionLoaded.security || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* CDN Configuration */}
      <Card hidden={!isCardVisible("cdn")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.settings.cdnSection", { defaultValue: "CDN Configuration" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.cdnSubtitle", { defaultValue: "External CDN URLs for frontend assets" })}</Typography.Text>
          {sectionLoadError.cdn && <SettingsLoadError section="cdn" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label>{t("admin.settings.cdnEnabled", { defaultValue: "CDN Enabled" })}</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={cdn.enabled ? "success" : "secondary"}>
                  {cdn.enabled ? t("admin.settings.enabled", { defaultValue: "Enabled" }) : t("admin.settings.disabled", { defaultValue: "Disabled" })}
                </Badge>
                <Button
                  type="default"
                  size="small"
                  onClick={() =>
                    setCdn({
                      ...cdn,
                      enabled: !cdn.enabled,
                    })
                  }
                >
                  {t("admin.settings.toggle", { defaultValue: "Toggle" })}
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="cdn-echarts">{t("admin.settings.echartsUrl", { defaultValue: "ECharts CDN URL" })}</label>
              <Input
                id="cdn-echarts"
                value={cdn.url}
                onChange={(e) => setCdn({ ...cdn, url: e.target.value })}
                placeholder={t("admin.settings.placeholderEchartsUrl", { defaultValue: "https://cdnjs.cloudflare.com/ajax/libs/echarts/5.5.1/echarts.min.js" })}
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            {t("admin.settings.cdnNote", { defaultValue: "CDN URLs are used at build time. Changes require a rebuild to take effect. For production, consider nginx edge caching as a fallback." })}
          </p>
          <div className="flex justify-end">
            <Button
              onClick={handleCdnSave}
              disabled={!sectionLoaded.cdn || cdnMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* File Preview Configuration */}
      <Card hidden={!isCardVisible("filePreview")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <EyeOutlined className="size-4 text-primary" />
            {t("admin.file_preview")}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.filePreviewSubtitle", { defaultValue: "Configure inline file preview behavior" })}</Typography.Text>
          {sectionLoadError.filePreview && <SettingsLoadError section="filePreview" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label>{t("admin.file_preview_enabled")}</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={filePreview.enabled === "true" ? "success" : "secondary"}>
                  {filePreview.enabled === "true" ? t("admin.settings.enabled", { defaultValue: "Enabled" }) : t("admin.settings.disabled", { defaultValue: "Disabled" })}
                </Badge>
                <Button
                  type="default"
                  size="small"
                  onClick={() =>
                    setFilePreview({
                      ...filePreview,
                      enabled: filePreview.enabled === "true" ? "false" : "true",
                    })
                  }
                >
                  {t("admin.settings.toggle", { defaultValue: "Toggle" })}
                </Button>
              </div>
            </div>
            <div className="space-y-1.5">
              <label htmlFor="fp-max-size">{t("admin.file_preview_max_size")}</label>
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
              <label htmlFor="fp-formats">{t("admin.file_preview_formats")}</label>
              <Input
                id="fp-formats"
                value={filePreview.enabled_formats}
                onChange={(e) =>
                  setFilePreview({ ...filePreview, enabled_formats: e.target.value })
                }
                placeholder="fasta,vcf,gff3,csv,tsv,png,jpg,svg,txt"
              />
              <p className="text-xs text-muted-foreground">
                {t("admin.settings.filePreviewFormatsHelp", { defaultValue: "Comma-separated list of supported file formats." })}
              </p>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("file_preview", filePreview)}
              disabled={!sectionLoaded.filePreview || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Site content (backend-editable frontend text + image URLs) */}
      <Card hidden={!isCardVisible("content")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.settings.siteContentSection", { defaultValue: "Site Content" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.siteContentSubtitle", { defaultValue: "Backend-editable frontend text and image URLs (served by GET /site/content)." })}</Typography.Text>
          {(sectionLoadError.content || contentSchemaQuery.isError) && <SettingsLoadError section="content" />}
        </div>
        <div className="space-y-4">
          {CONTENT_AREA_ORDER.map((area) => (
            <div key={area} className="space-y-3">
              <Typography.Title level={5} className="mb-1">{t(`admin.settings.contentArea_${area}`, { defaultValue: CONTENT_AREA_LABELS[area] })}</Typography.Title>
              <div className="grid gap-4 sm:grid-cols-2">
                {contentFields.filter((field) => field.area === area).map((field) => (
                  <div key={field.key} className="space-y-1.5">
                    <label htmlFor={`content-${field.key}`}>{t(`admin.settings.contentField_${field.key.replace(/\./g, "_")}`, { defaultValue: field.label })}</label>
                    {field.textarea ? (
                      <Input.TextArea
                        id={`content-${field.key}`}
                        rows={2}
                        value={siteContent[field.key] ?? ""}
                        onChange={(e) => setSiteContent({ ...siteContent, [field.key]: e.target.value })}
                      />
                    ) : (
                      <Input
                        id={`content-${field.key}`}
                        value={siteContent[field.key] ?? ""}
                        onChange={(e) => setSiteContent({ ...siteContent, [field.key]: e.target.value })}
                      />
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave(contentSection, siteContent)}
              disabled={!sectionLoaded.content || contentSchemaQuery.isPending || contentSchemaQuery.isError || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {/* Footer contact block */}
      <Card hidden={!isCardVisible("footer")}>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            {t("admin.settings.footerSection", { defaultValue: "Footer" })}
          </Typography.Title>
          <Typography.Text type="secondary">{t("admin.settings.footerSubtitle", { defaultValue: "Editable footer contact information" })}</Typography.Text>
          {sectionLoadError.footer && <SettingsLoadError section="footer" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-person">{t("admin.settings.contactPerson", { defaultValue: "Contact Person" })}</label>
              <Input
                id="footer-contact-person"
                value={footer.contact_person}
                onChange={(e) => setFooter({ ...footer, contact_person: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-phone">{t("admin.settings.contactPhone", { defaultValue: "Contact Phone" })}</label>
              <Input
                id="footer-contact-phone"
                value={footer.contact_phone}
                onChange={(e) => setFooter({ ...footer, contact_phone: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-email">{t("admin.settings.contactEmail", { defaultValue: "Contact Email" })}</label>
              <Input
                id="footer-contact-email"
                value={footer.contact_email}
                onChange={(e) => setFooter({ ...footer, contact_email: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-address">{t("admin.settings.address", { defaultValue: "Address" })}</label>
              <Input
                id="footer-address"
                value={footer.address}
                onChange={(e) => setFooter({ ...footer, address: e.target.value })}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="footer-copyright">{t("admin.settings.copyright", { defaultValue: "Copyright" })}</label>
              <Input
                id="footer-copyright"
                value={footer.copyright}
                onChange={(e) => setFooter({ ...footer, copyright: e.target.value })}
                placeholder={t("admin.settings.placeholderCopyright", { defaultValue: "© {{year}} SoyMutDB. All rights reserved." })}
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave(footerSection, footer)}
              disabled={!sectionLoaded.footer || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              {t("admin.settings.saveChanges", { defaultValue: "Save Changes" })}
            </Button>
          </div>
        </div>
      </Card>

      {saveTarget && (
        <ConfirmDialog
          open={Boolean(saveTarget)}
          onOpenChange={(open) => !open && setSaveTarget(null)}
          title={t("admin.settings.settingsSaved", { defaultValue: "Settings Saved" })}
          description={t("admin.settings.settingsSavedDesc", { defaultValue: "The {{section}} settings have been updated successfully.", section: saveTarget })}
          confirmLabel={t("admin.settings.ok", { defaultValue: "OK" })}
          onConfirm={() => setSaveTarget(null)}
        />
      )}
    </div>
  );
}
