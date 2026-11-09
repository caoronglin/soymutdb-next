import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  getAdminSiteBranding,
  patchAdminSiteBranding,
  type AdminSiteBranding,
  type SiteBrandingPatch,
  type SiteVariant,
} from "@soymutdb/api-client";
import { Alert, Button, Form, Input, PageContainer, ProCard, Segmented, Space, Typography } from "@/lib/antd";
import { MediaPicker } from "@/components/media-picker";
import { useTranslation } from "react-i18next";

const VARIANTS: readonly SiteVariant[] = ["external", "internal"];
interface BrandFormValues {
  name_zh: string;
  name_en: string;
  icon_url: string;
}

export default function SiteBrandSettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<BrandFormValues>();
  const iconValue = Form.useWatch("icon_url", form);
  const nameEnValue = Form.useWatch("name_en", form);
  const [variant, setVariant] = React.useState<SiteVariant>("external");
  const [iconDirty, setIconDirty] = React.useState(false);
  const [noticeMessage, setNoticeMessage] = React.useState("");
  const [conflictMessage, setConflictMessage] = React.useState("");
  const [errorMessage, setErrorMessage] = React.useState("");
  const hydratedVariant = React.useRef<SiteVariant | null>(null);
  const queryKey = ["admin", "site-brand", variant] as const;
  const query = useQuery({
    queryKey,
    queryFn: () => getAdminSiteBranding(variant),
    staleTime: 0,
    retry: false,
  });

  React.useEffect(() => {
    const brand = query.data;
    if (!brand || brand.variant !== variant || hydratedVariant.current === variant) return;
    form.setFieldsValue({
      name_zh: brand.values.name_zh,
      name_en: brand.values.name_en,
      icon_url: brand.values.icon_url ?? "",
    });
    hydratedVariant.current = variant;
    setIconDirty(false);
    setNoticeMessage("");
    setConflictMessage("");
    setErrorMessage("");
  }, [form, query.data, variant]);

  const saveMutation = useMutation({
    mutationFn: (draft: BrandFormValues) => {
      const values: SiteBrandingPatch = {
        name_zh: draft.name_zh.trim(),
        name_en: draft.name_en.trim(),
      };
      if (iconDirty) values.icon_url = draft.icon_url.trim() || null;
      return patchAdminSiteBranding(variant, query.data?.version ?? 0, values);
    },
    onSuccess: (brand: AdminSiteBranding) => {
      queryClient.setQueryData(queryKey, brand);
      form.setFieldsValue({
        name_zh: brand.values.name_zh,
        name_en: brand.values.name_en,
        icon_url: brand.values.icon_url ?? "",
      });
      setIconDirty(false);
      setNoticeMessage(t("admin.brand.saveSuccess"));
      setErrorMessage("");
      setConflictMessage("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "site-brand"] });
    },
    onError: (error: unknown) => {
      setNoticeMessage("");
      if (error instanceof ApiError && error.status === 409) {
        setConflictMessage(t("admin.brand.conflict"));
        void queryClient.invalidateQueries({ queryKey: ["admin", "site-brand"] });
      } else {
        setErrorMessage(t("admin.brand.saveError"));
      }
    },
  });

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
      {query.isPending ? (
        <ProCard loading data-testid="brand-loading" />
      ) : query.isError ? (
        <Alert
          type="error"
          showIcon
          data-testid="brand-load-error"
          title={t("admin.brand.loadError")}
          action={<Button size="small" onClick={() => void query.refetch()} data-testid="brand-retry">{t("common.retry")}</Button>}
        />
      ) : (
        <ProCard className="max-w-2xl">
          <Form<BrandFormValues>
            form={form}
            layout="vertical"
            onFinish={(values) => saveMutation.mutate(values)}
            onValuesChange={(changed: Partial<BrandFormValues>) => {
              if (Object.hasOwn(changed, "icon_url")) setIconDirty(true);
            }}
            data-testid="brand-form"
          >
            <Typography.Text type="secondary" className="mb-4 block text-xs">
              {t("admin.brand.version")}: {query.data?.version ?? 0}
            </Typography.Text>

            <Form.Item label={t("admin.brand.nameZh")} name="name_zh" rules={[{ required: true }]}>
              <Input maxLength={120} data-testid="brand-name-zh" />
            </Form.Item>
            <Form.Item label={t("admin.brand.nameEn")} name="name_en" rules={[{ required: true }]}>
              <Input maxLength={120} data-testid="brand-name-en" />
            </Form.Item>
            <Form.Item label={t("admin.brand.iconUrl")} name="icon_url" rules={[{ type: "url" }]}>
              <Input data-testid="brand-icon-url" />
            </Form.Item>
            <MediaPicker
              value={iconValue || null}
              previewUrl={iconValue || null}
              previewAlt={nameEnValue || t("admin.brand.preview")}
              purpose={null}
              onChange={(asset) => {
                form.setFieldValue("icon_url", asset?.public_url ?? "");
                setIconDirty(true);
              }}
            />
            <Typography.Text type="secondary" className="mb-3 block text-xs">
              {t("admin.brand.iconHelp")}
            </Typography.Text>

            <Space orientation="vertical" size="small" style={{ display: "flex", marginBottom: 16 }}>
              {noticeMessage ? <Alert type="success" showIcon title={noticeMessage} data-testid="brand-notice" /> : null}
              {conflictMessage ? <Alert type="warning" showIcon title={conflictMessage} data-testid="brand-conflict" /> : null}
              {errorMessage ? <Alert type="error" showIcon title={errorMessage} data-testid="brand-error" /> : null}
            </Space>

            <Button type="primary" htmlType="submit" loading={saveMutation.isPending} data-testid="brand-save">
              {saveMutation.isPending ? t("common.loading") : t("common.save")}
            </Button>
          </Form>
        </ProCard>
      )}
    </PageContainer>
  );
}
