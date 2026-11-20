import * as React from "react";
import type { SiteVariant } from "@soymutdb/api-client";
import { PageContainer, ProCard, Segmented, Typography } from "@/lib/antd";
import { SiteBrandForm } from "@/components/site-brand-form";
import { useTranslation } from "react-i18next";

const VARIANTS: readonly SiteVariant[] = ["external", "internal"];

/**
 * `/settings/brand` is kept routable for existing deep links, but the console's
 * appearance surface is `/settings/appearance`: the identity form itself lives in
 * `components/site-brand-form.tsx` so both pages write the same document.
 */
export default function SiteBrandSettingsPage() {
  const { t } = useTranslation();
  const [variant, setVariant] = React.useState<SiteVariant>("external");

  return (
    <PageContainer
      title={t("admin.brand.title", { defaultValue: "Site branding" })}
      subTitle={t("admin.brand.description", { defaultValue: "Edit the independently versioned public and internal site identity." })}
      extra={[
        <div key="variants">
          <Segmented
            data-testid="brand-variant-switch"
            aria-label={t("admin.brand.title")}
            value={variant}
            onChange={(value) => setVariant(value as SiteVariant)}
            options={VARIANTS.map((option) => ({
              value: option,
              label: (
                <span data-testid={`brand-variant-${option}`}>
                  {option === "external" ? t("admin.brand.variantExternal") : t("admin.brand.variantInternal")}
                </span>
              ),
            }))}
          />
          <Typography.Text type="secondary" className="mt-2 block max-w-xl text-xs">
            {t("admin.brand.variantHint")}
          </Typography.Text>
        </div>,
      ]}
    >
      <ProCard className="max-w-2xl">
        <SiteBrandForm variant={variant} />
      </ProCard>
    </PageContainer>
  );
}