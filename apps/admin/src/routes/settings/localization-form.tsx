import { GlobalOutlined, SaveOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Button, ProCard, Select, Typography } from "@/lib/antd";

type GeneralSettings = Record<string, unknown>;

export function LocalizationSettingsForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-settings", "general"],
    queryFn: () => http.get<GeneralSettings>("/admin/settings/general"),
  });
  const [defaultLanguage, setDefaultLanguage] = useState("en");
  useEffect(() => {
    if (query.data) setDefaultLanguage(String(query.data.defaultLanguage ?? "en"));
  }, [query.data]);
  const saveMutation = useMutation({
    mutationFn: () => http.put("/admin/settings/general", {
      json: { ...(query.data ?? {}), defaultLanguage },
    }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", "general"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });

  return (
    <ProCard>
      <div className="space-y-4">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <GlobalOutlined className="size-4 text-primary" aria-hidden />
            {t("admin.settings.localizationForm.title", { defaultValue: "Localization" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            {t("admin.settings.localizationForm.description", {
              defaultValue: "Configure the default language used by the public site.",
            })}
          </Typography.Text>
        </div>
        {query.isLoading ? <p role="status">{t("admin.settings.localizationForm.loading", { defaultValue: "Loading localization settings…" })}</p> : null}
        {query.isError ? <p role="alert" className="text-destructive">
            {t("admin.settings.localizationForm.loadError", { defaultValue: "Unable to load localization settings." })}
          </p> : null}
        {!query.isLoading && !query.isError ? (
          <>
            <label className="block max-w-sm space-y-1.5">
              <span>{t("admin.settings.localizationForm.defaultLanguage", { defaultValue: "Default Language" })}</span>
              <Select
                value={defaultLanguage}
                onChange={setDefaultLanguage}
                className="w-full"
                options={[
                  { value: "en", label: "English" },
                  { value: "zh", label: "中文" },
                ]}
              />
            </label>
            <div className="flex justify-end">
              <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
                <SaveOutlined aria-hidden className="size-4" />
                {t("admin.settings.localizationForm.save", { defaultValue: "Save localization" })}
              </Button>
            </div>
          </>
        ) : null}
        {saveMutation.isError ? <p role="alert" className="text-destructive">
            {t("admin.settings.localizationForm.saveError", { defaultValue: "Unable to save localization settings." })}
          </p> : null}
        {saveMutation.isSuccess ? <p role="status" className="text-success">
            {t("admin.settings.localizationForm.saved", { defaultValue: "Localization saved." })}
          </p> : null}
      </div>
    </ProCard>
  );
}
