export const SETTINGS_DOMAINS = [
  "site",
  "appearance",
  "integrations",
  "security",
  "localization",
  "advanced",
] as const;

/**
 * The domains the settings hub offers as its own cards.
 *
 * `site` is not one of them: `/settings/site` redirects to
 * `/settings/appearance`, so a card for it opened the page the neighbouring
 * "Site appearance" card already opened. Two cards, one destination -- the
 * hub looked like it offered a choice it did not offer. The route stays
 * routable as an alias for existing deep links.
 */
export const SETTINGS_HUB_DOMAINS = SETTINGS_DOMAINS.filter(
  (domain) => domain !== "site",
);

export type SettingsDomain = (typeof SETTINGS_DOMAINS)[number];

export interface SettingsRevisionSection {
  id: string;
  /** Registered in both catalogs as `admin.settings.sections.<id>`. */
  label: string;
}

export interface SettingsDomainMeta {
  title: string;
  description: string;
  revisionSections: SettingsRevisionSection[];
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
  appearance: {
    title: "Site appearance",
    description: "Brand, header navigation, footer and media for the public site.",
    revisionSections: [
      { id: "general", label: "Admin console theme" },
      { id: "brand_external", label: "Brand (public site)" },
      { id: "header_external", label: "Header navigation (public site)" },
      { id: "footer_external", label: "Footer (public site)" },
    ],
  },
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
