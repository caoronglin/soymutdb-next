import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SaveOutlined } from "@ant-design/icons";
import {
  adminSettingsApi,
  ApiError,
  capabilitiesApi,
} from "@soymutdb/api-client";
import {
  App,
  Button,
  Flex,
  PageContainer,
  ProCard,
  Segmented,
  Space,
  Switch,
  Typography,
} from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { InternalSiteOverride } from "@/components/internal-site-override";
import { VariantNavigationEditor } from "@/components/variant-navigation-editor";

const DATABASE_KINDS = [
  {
    value: "genome",
    labelKey: "admin.siteControl.dbKind.genome",
    descriptionKey: "admin.siteControl.dbKind.genomeDescription",
  },
  {
    value: "gene_ontology",
    labelKey: "admin.siteControl.dbKind.geneOntology",
    descriptionKey: "admin.siteControl.dbKind.geneOntologyDescription",
  },
  {
    value: "transcription_factor",
    labelKey: "admin.siteControl.dbKind.transcriptionFactor",
    descriptionKey: "admin.siteControl.dbKind.transcriptionFactorDescription",
  },
] as const;

type DatabaseKind = (typeof DATABASE_KINDS)[number]["value"];

function DatabaseKindCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const settings = useQuery({
    queryKey: ["admin-settings", "general"],
    queryFn: () => adminSettingsApi.get("general"),
  });
  const [kind, setKind] = React.useState<DatabaseKind>("genome");

  React.useEffect(() => {
    const stored = settings.data?.values.databaseKind;
    if (typeof stored === "string" && DATABASE_KINDS.some((entry) => entry.value === stored)) {
      setKind(stored as DatabaseKind);
    }
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => {
      if (!settings.data) throw new Error(t("admin.siteControl.nav.error.notLoaded"));
      return adminSettingsApi.patch("general", settings.data.version, { databaseKind: kind });
    },
    onSuccess: () => {
      message.success(t("admin.siteControl.dbType.saved"));
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", "general"] });
      void queryClient.invalidateQueries({ queryKey: ["site-profile"] });
      void queryClient.invalidateQueries({ queryKey: ["site-branding"] });
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        message.warning(t("admin.siteControl.conflict"));
        void queryClient.invalidateQueries({ queryKey: ["admin-settings", "general"] });
        return;
      }
      message.error(error instanceof Error ? error.message : t("admin.siteControl.saveFailed"));
    },
  });

  const selected = DATABASE_KINDS.find((entry) => entry.value === kind);
  return (
    <ProCard title={t("admin.siteControl.dbType.cardTitle")}>
      <Typography.Paragraph type="secondary">
        {t("admin.siteControl.dbType.description")}
      </Typography.Paragraph>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <Segmented
          block
          value={kind}
          options={DATABASE_KINDS.map((entry) => ({
            value: entry.value,
            label: t(entry.labelKey),
          }))}
          onChange={(value) => setKind(value as DatabaseKind)}
        />
        <Typography.Text type="secondary">
          {selected ? t(selected.descriptionKey) : null}
        </Typography.Text>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={save.isPending}
          disabled={settings.isLoading}
          onClick={() => save.mutate()}
        >
          {t("admin.siteControl.dbType.save")}
        </Button>
      </Space>
    </ProCard>
  );
}

function FeatureAvailabilityCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const features = useQuery({
    queryKey: ["admin-features"],
    queryFn: () => capabilitiesApi.adminGet(),
  });
  const [draft, setDraft] = React.useState<Record<string, boolean>>({});

  React.useEffect(() => {
    if (!features.data) return;
    setDraft(
      Object.fromEntries(features.data.features.map((feature) => [feature.key, feature.enabled])),
    );
  }, [features.data]);

  const save = useMutation({
    mutationFn: () => capabilitiesApi.adminUpdate(draft),
    onSuccess: () => {
      message.success(t("admin.siteControl.features.saved"));
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["site-navigation"] });
      void queryClient.invalidateQueries({ queryKey: ["site-profile"] });
    },
    onError: (error: unknown) => {
      message.error(error instanceof Error ? error.message : t("admin.siteControl.saveFailed"));
    },
  });

  return (
    <ProCard
      title={t("admin.siteControl.features.cardTitle")}
      extra={
        <Button
          type="primary"
          loading={save.isPending}
          disabled={features.isLoading || features.data === undefined}
          onClick={() => save.mutate()}
        >
          {t("admin.siteControl.features.save")}
        </Button>
      }
    >
      <Typography.Paragraph type="secondary">
        {t("admin.siteControl.features.description")}
      </Typography.Paragraph>
      <Flex vertical gap={8}>
        {features.data?.features.map((feature) => (
          <Flex key={feature.key} align="center" justify="space-between" gap={12}>
            <Flex vertical>
              <Typography.Text strong>{feature.key}</Typography.Text>
              <Typography.Text type="secondary">
                {t(`admin.siteControl.features.${feature.key.replace(/\./g, "_")}`, {
                  defaultValue: feature.description,
                })}
              </Typography.Text>
            </Flex>
            <Switch
              aria-label={t("admin.siteControl.features.enableAria", { feature: feature.key })}
              checked={draft[feature.key] ?? feature.enabled}
              onChange={(enabled) => setDraft({ ...draft, [feature.key]: enabled })}
            />
          </Flex>
        ))}
      </Flex>
    </ProCard>
  );
}

export default function SiteControlPage() {
  const { t } = useTranslation();
  return (
    <PageContainer
      title={t("admin.siteControl.title")}
      subTitle={t("admin.siteControl.subtitle")}
    >
      <Flex vertical gap={16}>
        <DatabaseKindCard />
        <FeatureAvailabilityCard />
        <ProCard title={t("admin.siteControl.nav.cardTitle")}>
          <VariantNavigationEditor variant="external" />
          <InternalSiteOverride>
            <VariantNavigationEditor variant="internal" />
          </InternalSiteOverride>
        </ProCard>
      </Flex>
    </PageContainer>
  );
}
