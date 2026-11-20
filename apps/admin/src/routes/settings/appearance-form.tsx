import { BgColorsOutlined, SaveOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Button, ColorPicker, Input, ProCard, Typography } from "@/lib/antd";
import {
  ANTD_PRIMARY_HEX,
  isValidAdminPrimaryColor,
  readAdminPrimaryColor,
  saveAdminPrimaryColor,
} from "@/lib/antd-theme";

type GeneralSettings = Record<string, unknown>;

function normalizedColor(value: unknown): string {
  const candidate = String(value ?? readAdminPrimaryColor());
  return isValidAdminPrimaryColor(candidate) ? candidate.toLowerCase() : ANTD_PRIMARY_HEX;
}

export function AppearanceSettingsForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [pendingColor, setPendingColor] = useState<string | null>(null);
  const [identity, setIdentity] = useState({ siteName: "", siteDescription: "" });
  const query = useQuery({
    queryKey: ["admin-settings", "general"],
    queryFn: () => http.get<GeneralSettings>("/admin/settings/general"),
  });
  // The site name and description used to live on `/settings/site`, which now
  // redirects here. Editing them on the page they actually reach is the
  // difference between a setting and a dead field.
  useEffect(() => {
    if (!query.data) return;
    setIdentity({
      siteName: String(query.data.siteName ?? ""),
      siteDescription: String(query.data.siteDescription ?? ""),
    });
  }, [query.data]);
  const currentColor = pendingColor ?? normalizedColor(query.data?.primaryColor);
  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        ...(query.data ?? {}),
        primaryColor: currentColor,
        ...identity,
      };
      return http.put("/admin/settings/general", { json: payload });
    },
    onSuccess: () => {
      saveAdminPrimaryColor(currentColor);
      setPendingColor(null);
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", "general"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });

  return (
    <ProCard>
      <div className="space-y-4">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <BgColorsOutlined className="size-4 text-primary" aria-hidden />
            {t("admin.settings.appearanceForm.title", { defaultValue: "Appearance" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("admin.settings.appearanceForm.description", {
              defaultValue: "Configure the administrator interface primary colour.",
            })}
          </Typography.Text>
        </div>
        {query.isLoading ? <p role="status">{t("admin.settings.appearanceForm.loading", { defaultValue: "Loading appearance settings…" })}</p> : null}
        {query.isError ? <p role="alert" className="text-destructive">
            {t("admin.settings.appearanceForm.loadError", { defaultValue: "Unable to load appearance settings." })}
          </p> : null}
        {!query.isLoading && !query.isError ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-dashed border-border bg-muted/20 p-4">
              <div className="min-w-0">
                <p className="font-medium">{t("admin.settings.appearanceForm.primaryColor", { defaultValue: "Primary color" })}</p>
                <p className="text-sm text-muted-foreground">
                  {t("admin.settings.appearanceForm.primaryColorHelp", {
                    defaultValue: "Controls Ant Design buttons, links, tags, and selected states.",
                  })}
                </p>
              </div>
              <ColorPicker
                value={currentColor}
                format="hex"
                showText
                aria-label={t("admin.settings.appearanceForm.primaryColor", { defaultValue: "Primary color" })}
                onChangeComplete={(color) => setPendingColor(color.toHexString())}
              />
            </div>
            <div className="space-y-3 rounded-lg border border-border bg-card p-4">
              <div>
                <p className="font-medium">{t("admin.settings.siteForm.title", { defaultValue: "Site information" })}</p>
                <p className="text-sm text-muted-foreground">
                  {t("admin.settings.siteForm.description", {
                    defaultValue: "Configure the public site identity and default language.",
                  })}
                </p>
              </div>
              <label className="block space-y-1.5">
                <span className="text-sm">{t("admin.settings.siteForm.siteName", { defaultValue: "Site Name" })}</span>
                <Input
                  value={identity.siteName}
                  onChange={(event) =>
                    setIdentity((current) => ({ ...current, siteName: event.target.value }))
                  }
                />
              </label>
              <label className="block space-y-1.5">
                <span className="text-sm">{t("admin.settings.siteForm.siteDescription", { defaultValue: "Site Description" })}</span>
                <Input.TextArea
                  value={identity.siteDescription}
                  rows={2}
                  onChange={(event) =>
                    setIdentity((current) => ({ ...current, siteDescription: event.target.value }))
                  }
                />
              </label>
            </div>
            <div className="flex justify-end">
              <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
                <SaveOutlined aria-hidden className="size-4" />
                {t("admin.settings.appearanceForm.save", { defaultValue: "Save appearance" })}
              </Button>
            </div>
          </>
        ) : null}
        {saveMutation.isError ? <p role="alert" className="text-destructive">
            {t("admin.settings.appearanceForm.saveError", { defaultValue: "Unable to save appearance settings." })}
          </p> : null}
        {saveMutation.isSuccess ? <p role="status" className="text-success">
            {t("admin.settings.appearanceForm.saved", { defaultValue: "Appearance saved." })}
          </p> : null}
      </div>
    </ProCard>
  );
}
