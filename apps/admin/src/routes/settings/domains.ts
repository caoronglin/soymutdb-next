export const SETTINGS_DOMAINS = [
  "site",
  "appearance",
  "integrations",
  "security",
  "localization",
  "advanced",
] as const;

export type SettingsDomain = (typeof SETTINGS_DOMAINS)[number];

export interface SettingsDomainMeta {
  title: string;
  description: string;
  revisionSections: Array<{ id: string; label: string }>;
}

export const SETTINGS_DOMAIN_META: Record<SettingsDomain, SettingsDomainMeta> = {
  site: {
    title: "Site information",
    description: "Name, public content, homepage, and footer details.",
    revisionSections: [
      { id: "general", label: "General" },
      { id: "about_external", label: "About (external)" },
      { id: "home_external", label: "Homepage (external)" },
      { id: "content_external", label: "Site content (external)" },
      { id: "footer_external", label: "Footer (external)" },
    ],
  },
  appearance: { title: "Appearance", description: "Theme colour and public presentation defaults.", revisionSections: [{ id: "general", label: "General" }] },
  integrations: { title: "Integrations", description: "External delivery and service configuration.", revisionSections: [] },
  security: { title: "Security", description: "Session and account protection settings.", revisionSections: [{ id: "security", label: "Security" }] },
  localization: {
    title: "Localization",
    description: "Default language and site-variant content.",
    revisionSections: [
      { id: "general", label: "General" },
      { id: "about_external", label: "About (external)" },
      { id: "about_internal", label: "About (internal)" },
      { id: "home_external", label: "Homepage (external)" },
      { id: "home_internal", label: "Homepage (internal)" },
    ],
  },
  advanced: {
    title: "Advanced",
    description: "Data, notification, and file-preview configuration.",
    revisionSections: [
      { id: "data", label: "Data and storage" },
      { id: "email", label: "Email and notifications" },
      { id: "file_preview", label: "File preview" },
    ],
  },
};

export type SettingsCard =
  | "general"
  | "variant"
  | "about"
  | "home"
  | "data"
  | "email"
  | "security"
  | "filePreview"
  | "content"
  | "footer";

export const SETTINGS_CARD_DOMAINS: Record<SettingsCard, SettingsDomain[]> = {
  general: ["site", "appearance", "localization"],
  variant: ["site", "localization"],
  about: ["site"],
  home: ["site"],
  data: ["advanced"],
  email: ["advanced"],
  security: ["security"],
  filePreview: ["advanced"],
  content: ["site"],
  footer: ["site"],
};
