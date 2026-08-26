import { SaveOutlined, GlobalOutlined, DatabaseOutlined, MailOutlined, SafetyOutlined, EyeOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Typography, Button, Card, Input, Select, Badge } from "@/lib/antd";
import { ConfirmDialog } from "../components/confirm-dialog";
import { RichEditor } from "../components/rich-editor/rich-editor";

type SettingsSection =
  | "general"
  | "about"
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
  content: false,
};

const settingsSectionLabels: Record<SettingsSection, string> = {
  general: "General settings",
  about: "About settings",
  data: "Data & Storage settings",
  email: "Email & Notifications settings",
  security: "Security settings",
  cdn: "CDN Configuration settings",
  filePreview: "File Preview settings",
  footer: "Footer settings",
  content: "Site content settings",
};

type ContentArea = "hero" | "tools" | "search" | "blast" | "help" | "generic";

interface ContentField {
  key: string;
  area: ContentArea;
  label: string;
  textarea?: boolean;
  defaultValue: string;
}

/**
 * Registered content.* keys (short form, without the content. prefix) plus
 * the English default values. Mirrors apps/api/app/core/settings_registry.py
 * so a fresh deployment shows today's strings until an administrator edits.
 */
const CONTENT_FIELDS: ContentField[] = [
  { key: "hero.eyebrow", area: "hero", label: "Hero eyebrow", defaultValue: "SOYMUTDB · MULTI-SPECIES" },
  { key: "hero.title", area: "hero", label: "Hero title", defaultValue: "Explore the Unknown Territories of Multi-Species Mutation" },
  { key: "hero.subtitle", area: "hero", label: "Hero subtitle", textarea: true, defaultValue: "A next-generation multi-species mutation database — from genome to phenotype in one place." },
  { key: "hero.searchPlaceholder", area: "hero", label: "Search placeholder", defaultValue: "Search a gene ID, locus or mutation…" },
  { key: "hero.image", area: "hero", label: "Hero image URL", defaultValue: "" },
  { key: "tool.gene.label", area: "tools", label: "Gene tool label", defaultValue: "Gene ID Search" },
  { key: "tool.gene.desc", area: "tools", label: "Gene tool description", defaultValue: "Look up mutations by gene ID" },
  { key: "tool.gene.image", area: "tools", label: "Gene tool image URL", defaultValue: "" },
  { key: "tool.location.label", area: "tools", label: "Location tool label", defaultValue: "Position Search" },
  { key: "tool.location.desc", area: "tools", label: "Location tool description", defaultValue: "Look up by chromosome and locus" },
  { key: "tool.location.image", area: "tools", label: "Location tool image URL", defaultValue: "" },
  { key: "tool.gbrowse.label", area: "tools", label: "GBrowse tool label", defaultValue: "JBrowse 2" },
  { key: "tool.gbrowse.desc", area: "tools", label: "GBrowse tool description", defaultValue: "Browse the genome in JBrowse 2" },
  { key: "tool.gbrowse.image", area: "tools", label: "GBrowse tool image URL", defaultValue: "" },
  { key: "tool.blast.label", area: "tools", label: "BLAST tool label", defaultValue: "BLAST" },
  { key: "tool.blast.desc", area: "tools", label: "BLAST tool description", defaultValue: "Find homologs by sequence alignment" },
  { key: "tool.blast.image", area: "tools", label: "BLAST tool image URL", defaultValue: "" },
  { key: "tool.primer.label", area: "tools", label: "Primer tool label", defaultValue: "Primer Design" },
  { key: "tool.primer.desc", area: "tools", label: "Primer tool description", defaultValue: "Design and check PCR primers" },
  { key: "tool.primer.image", area: "tools", label: "Primer tool image URL", defaultValue: "" },
  { key: "search.genes.title", area: "search", label: "Gene search title", defaultValue: "Gene ID Search" },
  { key: "search.genes.subtitle", area: "search", label: "Gene search subtitle", defaultValue: "Find genes by gene ID in a genome version" },
  { key: "search.genes.colAssembly", area: "search", label: "Gene results column: genome version", defaultValue: "Genome version" },
  { key: "search.genes.colChromosome", area: "search", label: "Gene results column: chromosome", defaultValue: "Chromosome" },
  { key: "search.genes.colPosition", area: "search", label: "Gene results column: position", defaultValue: "Position" },
  { key: "search.genes.colMutation", area: "search", label: "Gene results column: mutation feature", defaultValue: "Mutation feature" },
  { key: "search.genes.colGeneId", area: "search", label: "Gene results column: gene ID", defaultValue: "Gene ID" },
  { key: "search.genes.colGbrowse", area: "search", label: "Gene results column: JBrowse 2", defaultValue: "JBrowse 2" },
  { key: "search.location.title", area: "search", label: "Location search title", defaultValue: "Physical Location Search" },
  { key: "search.location.subtitle", area: "search", label: "Location search subtitle", defaultValue: "Find variants and genes in a genomic region" },
  { key: "search.location.colAssembly", area: "search", label: "Location results column: genome version", defaultValue: "Genome version" },
  { key: "search.location.colChromosome", area: "search", label: "Location results column: chromosome", defaultValue: "Chromosome" },
  { key: "search.location.colPosition", area: "search", label: "Location results column: position", defaultValue: "Position" },
  { key: "search.location.colMutation", area: "search", label: "Location results column: mutation feature", defaultValue: "Mutation feature" },
  { key: "search.location.colGeneId", area: "search", label: "Location results column: gene ID", defaultValue: "Gene ID" },
  { key: "search.location.colGbrowse", area: "search", label: "Location results column: JBrowse 2", defaultValue: "JBrowse 2" },
  { key: "blast.searchType", area: "blast", label: "BLAST type label", defaultValue: "BLAST Type" },
  { key: "blast.database", area: "blast", label: "BLAST database label", defaultValue: "Reference sequence type" },
  { key: "blast.databasePlaceholder", area: "blast", label: "BLAST database placeholder", defaultValue: "Select a reference sequence type" },
  { key: "blast.input", area: "blast", label: "BLAST input label", defaultValue: "Input Sequence" },
  { key: "blast.inputSequence", area: "blast", label: "BLAST input sequence label", defaultValue: "Input Sequence" },
  { key: "blast.sequencePlaceholder", area: "blast", label: "BLAST sequence placeholder", textarea: true, defaultValue: "Paste sequence in FASTA format..." },
  { key: "blast.submit", area: "blast", label: "BLAST submit button", defaultValue: "BLAST" },
  { key: "blast.eValue", area: "blast", label: "BLAST E-value label", defaultValue: "E-value threshold" },
  { key: "blast.maxHits", area: "blast", label: "BLAST max hits label", defaultValue: "Max hits" },
  { key: "blast.hitSequenceId", area: "blast", label: "BLAST hit column: sequence ID", defaultValue: "Sequence ID" },
  { key: "blast.hitGeneId", area: "blast", label: "BLAST hit column: gene ID", defaultValue: "Gene ID" },
  { key: "blast.hitCoverage", area: "blast", label: "BLAST hit column: coverage", defaultValue: "Coverage" },
  { key: "blast.hitEValue", area: "blast", label: "BLAST hit column: E-value", defaultValue: "E-value" },
  { key: "help.gettingStarted", area: "help", label: "Help: getting started", defaultValue: "Getting Started" },
  { key: "help.documentation", area: "help", label: "Help: documentation", defaultValue: "Documentation" },
  { key: "help.contact", area: "help", label: "Help: contact", defaultValue: "Contact Support" },
  { key: "help.faq", area: "help", label: "Help: FAQ heading", defaultValue: "Frequently Asked Questions" },
  { key: "help.faq1.q", area: "help", label: "FAQ 1 question", defaultValue: "How do I search for a gene?" },
  { key: "help.faq1.a", area: "help", label: "FAQ 1 answer", textarea: true, defaultValue: "Use the search bar at the top of any page, or visit the Genes page to filter by chromosome, biotype, or keyword. Gene IDs follow the Glyma.01G000100 format." },
  { key: "help.faq2.q", area: "help", label: "FAQ 2 question", defaultValue: "How do I download variant data?" },
  { key: "help.faq2.a", area: "help", label: "FAQ 2 answer", textarea: true, defaultValue: "Visit the Downloads page for the files currently published for a release. Check each item's format, assembly, release, and provenance metadata before using it in an analysis." },
  { key: "help.faq3.q", area: "help", label: "FAQ 3 question", defaultValue: "Can I request mutant seeds?" },
  { key: "help.faq3.a", area: "help", label: "FAQ 3 answer", textarea: true, defaultValue: "Open the Seed Request page to see whether requests are currently enabled and to review the eligibility and distribution terms shown during submission." },
  { key: "help.faq4.q", area: "help", label: "FAQ 4 question", defaultValue: "How do I cite SoyMutDB?" },
  { key: "help.faq4.a", area: "help", label: "FAQ 4 answer", textarea: true, defaultValue: "Use the citation and provenance metadata published with the exact data release you used. A journal citation or DOI is shown only after it has been verified by the project maintainers." },
  { key: "help.faq5.q", area: "help", label: "FAQ 5 question", defaultValue: "What genome assembly is used?" },
  { key: "help.faq5.a", area: "help", label: "FAQ 5 answer", textarea: true, defaultValue: "The assembly is part of the search, record, browser, and download context. Confirm the displayed assembly before comparing or combining genomic coordinates." },
  { key: "help.faq6.q", area: "help", label: "FAQ 6 question", defaultValue: "How often is the data updated?" },
  { key: "help.faq6.a", area: "help", label: "FAQ 6 answer", textarea: true, defaultValue: "Release versions and publication dates are announced on the News and Downloads pages. SoyMutDB does not promise a fixed release cadence on this Help page." },
  { key: "ui.searchButton", area: "generic", label: "Search button text", defaultValue: "Search" },
  { key: "ui.submit", area: "generic", label: "Submit button text", defaultValue: "Submit" },
  { key: "ui.loading", area: "generic", label: "Loading text", defaultValue: "Loading..." },
  { key: "ui.errorRetry", area: "generic", label: "Error retry text", defaultValue: "Retry" },
  { key: "ui.noResults", area: "generic", label: "No results text", defaultValue: "No results found" },
];

const SITE_CONTENT_DEFAULTS: Record<string, string> = Object.fromEntries(
  CONTENT_FIELDS.map((field) => [field.key, field.defaultValue]),
);

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
  return (
    <p className="text-sm text-destructive" role="alert">
      Unable to load {settingsSectionLabels[section]}. Refresh the page and try again.
    </p>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [saveTarget, setSaveTarget] = useState<string | null>(null);
  const [sectionLoaded, setSectionLoaded] = useState(initialSettingsLoadState);
  const [sectionLoadError, setSectionLoadError] = useState(initialSettingsLoadErrorState);

  const [general, setGeneral] = useState({
    siteName: "SoyMutDB",
    siteDescription: "Comprehensive multi-species mutant database for functional genomics research (soybean as the first/default species)",
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
    echarts_url: "",
  });

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

  const [footer, setFooter] = useState({
    contact_person: "联系人: 周玲",
    contact_phone: "电话: 025-84391957",
    contact_email: "电子邮件: zlingxiaoyao@163.com",
    copyright: "© {{year}} SoyMutDB. All rights reserved.",
    address: "地址: 南京市玄武区钟灵街50号 邮编210014",
  });

  const [siteContent, setSiteContent] = useState<Record<string, string>>({
    ...SITE_CONTENT_DEFAULTS,
  });

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
      });
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
    http.get("/admin/cdn-config").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, cdn: true }));
        return;
      }
      const cdnUrls = Array.isArray(res.urls)
        ? res.urls.filter((url): url is string => typeof url === "string")
        : [];
      setCdn({
        cdn_enabled: String(res.enabled ?? false),
        echarts_url: cdnUrls[0] ?? "",
      });
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
    http.get("/admin/settings/about").then((res: unknown) => {
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
      setSectionLoadError((errors) => ({ ...errors, about: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/footer").then((res: unknown) => {
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
      setSectionLoadError((errors) => ({ ...errors, footer: true }));
    });
  }, []);

  useEffect(() => {
    http.get("/admin/settings/content").then((res: unknown) => {
      if (!isConfigurationRecord(res)) {
        setSectionLoadError((errors) => ({ ...errors, content: true }));
        return;
      }
      const merged: Record<string, string> = { ...SITE_CONTENT_DEFAULTS };
      for (const key of Object.keys(merged)) {
        const value = res[key];
        if (typeof value === "string") merged[key] = value;
      }
      setSiteContent(merged);
      setSectionLoadError((errors) => ({ ...errors, content: false }));
      setSectionLoaded((loaded) => ({ ...loaded, content: true }));
    }).catch(() => {
      setSectionLoadError((errors) => ({ ...errors, content: true }));
    });
  }, []);

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
      return http.put("/admin/cdn-config", {
        json: {
          enabled: cdn.cdn_enabled === "true",
          urls: cdn.echarts_url ? [cdn.echarts_url] : [],
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
      <div><Typography.Title level={2}>System Settings</Typography.Title><Typography.Text type="secondary">Configure global platform settings. Changes require administrator approval.</Typography.Text></div>

      {/* General */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            General
          </Typography.Title>
          <Typography.Text type="secondary">Site-wide configuration</Typography.Text>
          {sectionLoadError.general && <SettingsLoadError section="general" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="site-name">Site Name</label>
              <Input
                id="site-name"
                value={general.siteName}
                onChange={(e) => setGeneral({ ...general, siteName: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="default-lang">Default Language</label>
              <Select
                value={general.defaultLanguage}
                onChange={(v) => setGeneral({ ...general, defaultLanguage: v })}
              >


                  <Select.Option value="en">English</Select.Option>
                  <Select.Option value="zh">中文</Select.Option>

              </Select>
            </div>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="site-desc">Site Description</label>
            <Input.TextArea
              id="site-desc"
              value={general.siteDescription}
              onChange={(e) => setGeneral({ ...general, siteDescription: e.target.value })}
              rows={2}
            />
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("general", general)}
              disabled={!sectionLoaded.general || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* About us content */}
      <Card>
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
              <label htmlFor="about-title-en">Title (English)</label>
              <Input
                id="about-title-en"
                value={about.title_en}
                onChange={(e) => setAbout({ ...about, title_en: e.target.value })}
                placeholder="About SoyMutDB"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-title-zh">Title (Chinese)</label>
              <Input
                id="about-title-zh"
                value={about.title_zh}
                onChange={(e) => setAbout({ ...about, title_zh: e.target.value })}
                placeholder="关于我们"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-summary-en">Summary (English)</label>
              <Input.TextArea
                id="about-summary-en"
                value={about.summary_en}
                onChange={(e) => setAbout({ ...about, summary_en: e.target.value })}
                rows={2}
                placeholder="Short introduction shown on the About page"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="about-summary-zh">Summary (Chinese)</label>
              <Input.TextArea
                id="about-summary-zh"
                value={about.summary_zh}
                onChange={(e) => setAbout({ ...about, summary_zh: e.target.value })}
                rows={2}
                placeholder="关于我们页面的简短介绍"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="about-content-en">Content (English)</label>
              <RichEditor
                value={about.content_en}
                onChange={(html) => setAbout({ ...about, content_en: html })}
                placeholder="Full page content in English (rich text / Markdown supported)"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="about-content-zh">Content (Chinese)</label>
              <RichEditor
                value={about.content_zh}
                onChange={(html) => setAbout({ ...about, content_zh: html })}
                placeholder="页面内容（中文，富文本 / Markdown 均可）"
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("about", about)}
              disabled={!sectionLoaded.about || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* Data */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <DatabaseOutlined className="size-4 text-primary" />
            Data & Storage
          </Typography.Title>
          <Typography.Text type="secondary">DatabaseOutlined and storage configuration</Typography.Text>
          {sectionLoadError.data && <SettingsLoadError section="data" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="default-assembly">Default Assembly</label>
              <Input
                id="default-assembly"
                value={data.defaultAssembly}
                onChange={(e) => setData({ ...data, defaultAssembly: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-export">Max Export Records</label>
              <Input
                id="max-export"
                type="number"
                value={data.maxExportRecords}
                onChange={(e) => setData({ ...data, maxExportRecords: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="cache-ttl">Cache TTL (seconds)</label>
              <Input
                id="cache-ttl"
                type="number"
                value={data.cacheTtlSeconds}
                onChange={(e) => setData({ ...data, cacheTtlSeconds: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label>ClickHouse Analytics</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={data.enableClickhouse === "true" ? "success" : "secondary"}>
                  {data.enableClickhouse === "true" ? "Enabled" : "Disabled"}
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
                  Toggle
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
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* Email */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <MailOutlined className="size-4 text-primary" />
            Email & Notifications
          </Typography.Title>
          <Typography.Text type="secondary">SMTP configuration for system emails</Typography.Text>
          {sectionLoadError.email && <SettingsLoadError section="email" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="smtp-host">SMTP Host</label>
              <Input
                id="smtp-host"
                value={email.smtpHost}
                onChange={(e) => setEmail({ ...email, smtpHost: e.target.value })}
                placeholder="smtp.gmail.com"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="smtp-port">SMTP Port</label>
              <Input
                id="smtp-port"
                type="number"
                value={email.smtpPort}
                onChange={(e) => setEmail({ ...email, smtpPort: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="from-addr">From Address</label>
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
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* Security */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <SafetyOutlined className="size-4 text-primary" />
            Security
          </Typography.Title>
          <Typography.Text type="secondary">Authentication and access control</Typography.Text>
          {sectionLoadError.security && <SettingsLoadError section="security" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="session-timeout">Session Timeout (minutes)</label>
              <Input
                id="session-timeout"
                type="number"
                value={security.sessionTimeoutMinutes}
                onChange={(e) => setSecurity({ ...security, sessionTimeoutMinutes: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="max-login">Max Login Attempts</label>
              <Input
                id="max-login"
                type="number"
                value={security.maxLoginAttempts}
                onChange={(e) => setSecurity({ ...security, maxLoginAttempts: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="pw-min">Password Min Length</label>
              <Input
                id="pw-min"
                type="number"
                value={security.passwordMinLength}
                onChange={(e) => setSecurity({ ...security, passwordMinLength: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label>Two-Factor Auth</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={security.requireTwoFactor === "true" ? "success" : "secondary"}>
                  {security.requireTwoFactor === "true" ? "Required" : "Optional"}
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
                  Toggle
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
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* CDN Configuration */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            CDN Configuration
          </Typography.Title>
          <Typography.Text type="secondary">External CDN URLs for frontend assets</Typography.Text>
          {sectionLoadError.cdn && <SettingsLoadError section="cdn" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label>CDN Enabled</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={cdn.cdn_enabled === "true" ? "success" : "secondary"}>
                  {cdn.cdn_enabled === "true" ? "Enabled" : "Disabled"}
                </Badge>
                <Button
                  type="default"
                  size="small"
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
              <label htmlFor="cdn-echarts">ECharts CDN URL</label>
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
            <Button
              onClick={handleCdnSave}
              disabled={!sectionLoaded.cdn || cdnMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* File Preview Configuration */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <EyeOutlined className="size-4 text-primary" />
            {t("admin.file_preview")}
          </Typography.Title>
          <Typography.Text type="secondary">Configure inline file preview behavior</Typography.Text>
          {sectionLoadError.filePreview && <SettingsLoadError section="filePreview" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label>{t("admin.file_preview_enabled")}</label>
              <div className="flex items-center gap-2 pt-2">
                <Badge color={filePreview.enabled === "true" ? "success" : "secondary"}>
                  {filePreview.enabled === "true" ? "Enabled" : "Disabled"}
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
                  Toggle
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
                Comma-separated list of supported file formats.
              </p>
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("file_preview", filePreview)}
              disabled={!sectionLoaded.filePreview || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* Site content (backend-editable frontend text + image URLs) */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            Site Content
          </Typography.Title>
          <Typography.Text type="secondary">Backend-editable frontend text and image URLs (served by GET /site/content).</Typography.Text>
          {sectionLoadError.content && <SettingsLoadError section="content" />}
        </div>
        <div className="space-y-4">
          {CONTENT_AREA_ORDER.map((area) => (
            <div key={area} className="space-y-3">
              <Typography.Title level={5} className="mb-1">{CONTENT_AREA_LABELS[area]}</Typography.Title>
              <div className="grid gap-4 sm:grid-cols-2">
                {CONTENT_FIELDS.filter((field) => field.area === area).map((field) => (
                  <div key={field.key} className="space-y-1.5">
                    <label htmlFor={`content-${field.key}`}>{field.label}</label>
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
              onClick={() => handleSave("content", siteContent)}
              disabled={!sectionLoaded.content || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
      </Card>

      {/* Footer contact block */}
      <Card>
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" />
            Footer
          </Typography.Title>
          <Typography.Text type="secondary">Editable footer contact information</Typography.Text>
          {sectionLoadError.footer && <SettingsLoadError section="footer" />}
        </div>
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-person">Contact Person</label>
              <Input
                id="footer-contact-person"
                value={footer.contact_person}
                onChange={(e) => setFooter({ ...footer, contact_person: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-phone">Contact Phone</label>
              <Input
                id="footer-contact-phone"
                value={footer.contact_phone}
                onChange={(e) => setFooter({ ...footer, contact_phone: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-contact-email">Contact Email</label>
              <Input
                id="footer-contact-email"
                value={footer.contact_email}
                onChange={(e) => setFooter({ ...footer, contact_email: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="footer-address">Address</label>
              <Input
                id="footer-address"
                value={footer.address}
                onChange={(e) => setFooter({ ...footer, address: e.target.value })}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="footer-copyright">Copyright</label>
              <Input
                id="footer-copyright"
                value={footer.copyright}
                onChange={(e) => setFooter({ ...footer, copyright: e.target.value })}
                placeholder="© {{year}} SoyMutDB. All rights reserved."
              />
            </div>
          </div>
          <div className="flex justify-end">
            <Button
              onClick={() => handleSave("footer", footer)}
              disabled={!sectionLoaded.footer || saveMutation.isPending}
            >
              <SaveOutlined aria-hidden className="size-4" />
              Save Changes
            </Button>
          </div>
        </div>
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
