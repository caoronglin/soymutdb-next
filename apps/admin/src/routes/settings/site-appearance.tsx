/**
 * The one appearance surface for the public site.
 *
 * Sections are grouped by the thing an operator wants to change — identity,
 * header, footer, images — not by site variant. The public site is what every
 * section edits; the internal deployment is a separate artifact and is reached
 * through one explicit override (`InternalSiteOverride`), never a peer tab.
 *
 * Every section writes an existing versioned settings document through
 * `adminSettingsApi` / the site-brand API. This page introduces no new endpoint
 * and no second copy of a content shape.
 */
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import type { SiteVariant } from "@soymutdb/api-client";
import { FooterNavigationEditor } from "@/components/footer-navigation-editor";
import { InternalSiteOverride } from "@/components/internal-site-override";
import { SiteBrandForm } from "@/components/site-brand-form";
import { VariantNavigationEditor } from "@/components/variant-navigation-editor";
import { Button, Flex, ProCard, Typography } from "@/lib/antd";

function BrandSection({ variant, testIdPrefix }: { variant: SiteVariant; testIdPrefix: string }) {
  const { t } = useTranslation();
  return (
    <ProCard title={t("admin.siteAppearance.brand.title", { defaultValue: "Brand and icon" })}>
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" className="!mb-0">
          {t("admin.siteAppearance.brand.description", {
            defaultValue:
              "The name and icon the public site shows in its header. The icon is a media-library asset.",
          })}
        </Typography.Paragraph>
        <SiteBrandForm variant={variant} testIdPrefix={testIdPrefix} />
      </Flex>
    </ProCard>
  );
}

function HeaderSection({ variant }: { variant: SiteVariant }) {
  const { t } = useTranslation();
  return (
    <ProCard title={t("admin.siteAppearance.header.title", { defaultValue: "Header navigation" })}>
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" className="!mb-0">
          {t("admin.siteAppearance.header.description", {
            defaultValue:
              "Groups and links in the public site header. A link can be gated on a feature flag, which hides it while the flag is off.",
          })}
        </Typography.Paragraph>
        <VariantNavigationEditor variant={variant} />
      </Flex>
    </ProCard>
  );
}

function FooterSection({ variant }: { variant: SiteVariant }) {
  const { t } = useTranslation();
  return (
    <ProCard title={t("admin.siteAppearance.footer.title", { defaultValue: "Footer" })}>
      <Flex vertical gap={12}>
        <Typography.Paragraph type="secondary" className="!mb-0">
          {t("admin.siteAppearance.footer.description", {
            defaultValue: "The footer link groups and copyright line the public site renders.",
          })}
        </Typography.Paragraph>
        <FooterNavigationEditor variant={variant} />
      </Flex>
    </ProCard>
  );
}

export function SiteAppearanceSections() {
  const { t } = useTranslation();
  return (
    <Flex vertical gap={16}>
      <BrandSection variant="external" testIdPrefix="site-appearance-brand" />
      <HeaderSection variant="external" />
      <FooterSection variant="external" />
      <ProCard title={t("admin.siteAppearance.media.title", { defaultValue: "Images and media" })}>
        <Flex vertical gap={12}>
          <Typography.Paragraph type="secondary" className="!mb-0">
            {t("admin.siteAppearance.media.description", {
              defaultValue:
                "Logos, banners and screenshots live in the media library, not on this page. Upload or re-use an asset there, then select it in a page or in the icon field above.",
            })}
          </Typography.Paragraph>
          <div>
            <Link to="/media" data-testid="site-appearance-media-link">
              <Button>
                {t("admin.siteAppearance.media.open", { defaultValue: "Open media library" })}
              </Button>
            </Link>
          </div>
        </Flex>
      </ProCard>
      <InternalSiteOverride>
        <BrandSection variant="internal" testIdPrefix="site-appearance-internal-brand" />
        <HeaderSection variant="internal" />
        <FooterSection variant="internal" />
      </InternalSiteOverride>
    </Flex>
  );
}