import { WarningOutlined, CloseOutlined, CheckOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, PageContainer, ProCard, Tag, Typography } from "@/lib/antd";
import { capabilitiesApi, type FeatureDefinitionResponse } from "@soymutdb/api-client";
import { resolvePluginState } from "../lib/capability-state";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function FeaturesPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [toggleFailure, setToggleFailure] = useState<{ key: string; reason: string } | null>(null);
  const featuresQuery = useQuery({
    queryKey: ["admin-features"],
    queryFn: capabilitiesApi.adminGet,
  });
  const pluginsQuery = useQuery({
    queryKey: ["public-capabilities"],
    queryFn: capabilitiesApi.get,
    staleTime: 30_000,
  });
  const mutation = useMutation({
    mutationFn: (feature: FeatureDefinitionResponse) =>
      capabilitiesApi.adminUpdate({ [feature.key]: !feature.enabled }),
    onSuccess: (_data, feature) => {
      setToggleFailure(null);
      // The public capability snapshot is a different cache entry from the
      // admin registry, and it is read with a 30 s stale window by this screen
      // and by the import page. Without this invalidation a capability that
      // was just disabled keeps being offered for up to half a minute.
      void queryClient.invalidateQueries({ queryKey: ["admin-features"] });
      void queryClient.invalidateQueries({ queryKey: ["public-capabilities"] });
      message.success(
        t("admin.ops.toggleFeatureUpdated", {
          key: feature.key,
          defaultValue: "The {{key}} feature flag was updated.",
        }),
      );
    },
    onError: (error, feature) => {
      const reason = error instanceof Error ? error.message : String(error);
      setToggleFailure({ key: feature.key, reason });
      message.error(
        t("admin.ops.toggleFeatureFailed", {
          key: feature.key,
          defaultValue: "The {{key}} feature flag could not be updated.",
        }),
      );
    },
  });

  return (
    <PageContainer
      title={t("admin.ops.featureFlagsTitle", { defaultValue: "Feature Flags" })}
      subTitle={t("admin.ops.featureFlagsSubtitle", { defaultValue: "Enable or disable registered capabilities atomically. Disabling rejects new requests and does not kill running jobs." })}
    >
      <div className="space-y-6">
        {featuresQuery.error ? (
          <ProCard>
            <div role="alert" className="flex items-center gap-2 p-4 text-sm text-destructive">
              <WarningOutlined className="size-4" /> {t("admin.ops.loadFeatureFlagsFailed", { defaultValue: "Failed to load feature flags." })}
            </div>
          </ProCard>
        ) : null}
        {toggleFailure ? (
          <div
            role="alert"
            data-testid="feature-toggle-error"
            className="flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
          >
            <WarningOutlined className="mt-0.5 size-4 shrink-0" />
            <div>
              <p>
                {t("admin.ops.toggleFeatureFailed", {
                  key: toggleFailure.key,
                  defaultValue: "The {{key}} feature flag could not be updated.",
                })}
              </p>
              {toggleFailure.reason ? (
                <p className="mt-1 text-xs">
                  {t("common.errorReason", {
                    reason: toggleFailure.reason,
                    defaultValue: "Server response: {{reason}}",
                  })}
                </p>
              ) : null}
            </div>
          </div>
        ) : null}
        <ProCard>
          <Typography.Title level={5}>{t("admin.ops.registeredCapabilities", { defaultValue: "Registered capabilities" })}</Typography.Title>
          <div className="space-y-3">
            {featuresQuery.isPending ? (
              <p role="status" className="text-sm text-muted-foreground">{t("admin.ops.loadingFeatureFlags", { defaultValue: "Loading feature flags…" })}</p>
            ) : null}
            {featuresQuery.isSuccess && featuresQuery.data.features.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("admin.ops.noRegisteredFeatures", { defaultValue: "No registered feature flags." })}</p>
            ) : null}
            {(featuresQuery.data?.features ?? []).map((feature) => (
              <div key={feature.key} className="flex items-center justify-between gap-4 rounded-lg border p-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <code className="text-sm">{feature.key}</code>
                    {feature.public ? <Tag color="default">{t("admin.ops.badgePublic", { defaultValue: "public" })}</Tag> : <Tag color="default">{t("admin.ops.badgeInternal", { defaultValue: "internal" })}</Tag>}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{feature.description}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{t("admin.ops.disableBehavior", { defaultValue: "disable: {{behavior}}", behavior: feature.disable_behavior })}</p>
                </div>
                <Button
                  type={feature.enabled ? "primary" : "default"}
                  size="small"
                  disabled={featuresQuery.isPending || mutation.isPending}
                  onClick={() => mutation.mutate(feature)}
                  aria-label={t("admin.ops.toggleFeatureAria", { defaultValue: "{{action}} {{key}}", action: feature.enabled ? t("admin.ops.disable", { defaultValue: "Disable" }) : t("admin.ops.enable", { defaultValue: "Enable" }), key: feature.key })}
                >
                  {feature.enabled ? <CheckOutlined className="mr-1 size-4" /> : <CloseOutlined className="mr-1 size-4" />}
                  {feature.enabled ? t("admin.ops.enabled", { defaultValue: "Enabled" }) : t("admin.ops.disabled", { defaultValue: "Disabled" })}
                </Button>
              </div>
            ))}
          </div>
        </ProCard>

        <ProCard>
          <Typography.Title level={5}>{t("admin.ops.pluginRuntime", { defaultValue: "Plugin runtime" })}</Typography.Title>
          <div className="space-y-3">
            {pluginsQuery.isPending ? (
              <p role="status" className="text-sm text-muted-foreground">{t("admin.ops.loadingPluginStatus", { defaultValue: "Loading plugin status…" })}</p>
            ) : null}
            {pluginsQuery.isError ? (
              <div
                role="alert"
                aria-label={t("admin.ops.pluginStatusUnavailable", { defaultValue: "Plugin status unavailable" })}
                className="flex items-center gap-2 text-sm text-destructive"
              >
                <WarningOutlined className="size-4" /> {t("admin.ops.loadPluginStatusFailed", { defaultValue: "Unable to load plugin status." })}
              </div>
            ) : null}
            {pluginsQuery.isSuccess
              ? Array.from(new Set(["jbrowse", ...Object.keys(pluginsQuery.data.plugins ?? {})])).map(
                  (key) => {
                    const plugin = pluginsQuery.data.plugins?.[key];
                    const status = resolvePluginState(
                      { plugins: pluginsQuery.data.plugins },
                      key,
                    );
                    return (
                      <div
                        key={key}
                        className="flex items-center justify-between gap-4 rounded-lg border p-3"
                      >
                        <div className="min-w-0">
                          <code className="text-sm">{key}</code>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {status.reason ?? t("admin.ops.pluginReady", { defaultValue: "ready" })}
                          </p>
                        </div>
                        <Tag color={status.state === "available" ? "green" : "default"}>
                          {status.state === "available" ? t("admin.ops.available", { defaultValue: "Available" }) : t("admin.ops.unavailable", { defaultValue: "Unavailable" })}
                        </Tag>
                        {plugin?.version ? (
                          <span className="text-xs text-muted-foreground">v{plugin.version}</span>
                        ) : null}
                      </div>
                    );
                  },
                )
              : null}
          </div>
        </ProCard>
      </div>
    </PageContainer>
  );
}
