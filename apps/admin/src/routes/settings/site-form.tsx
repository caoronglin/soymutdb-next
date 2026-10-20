import { GlobalOutlined, SaveOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { Button, Input, ProCard, Select, Typography } from "@/lib/antd";

type GeneralSettings = Record<string, unknown>;

interface SiteFields {
  siteName: string;
  siteDescription: string;
  defaultLanguage: string;
}

function toSiteFields(values: GeneralSettings | undefined): SiteFields {
  return {
    siteName: String(values?.siteName ?? "SoyMutDB"),
    siteDescription: String(values?.siteDescription ?? ""),
    defaultLanguage: String(values?.defaultLanguage ?? "en"),
  };
}

export function SiteSettingsForm() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-settings", "general"],
    queryFn: () => http.get<GeneralSettings>("/admin/settings/general"),
  });
  const [fields, setFields] = useState<SiteFields>(() => toSiteFields(undefined));
  useEffect(() => {
    if (query.data) setFields(toSiteFields(query.data));
  }, [query.data]);
  const saveMutation = useMutation({
    mutationFn: () => http.put("/admin/settings/general", { json: { ...(query.data ?? {}), ...fields } }),
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
            Site information
          </Typography.Title>
          <Typography.Text type="secondary">Configure the public site identity and default language.</Typography.Text>
        </div>
        {query.isLoading ? <p role="status">Loading site settings…</p> : null}
        {query.isError ? <p role="alert" className="text-destructive">Unable to load site settings.</p> : null}
        {!query.isLoading && !query.isError ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5">
                <span>Site Name</span>
                <Input value={fields.siteName} onChange={(event) => setFields((current) => ({ ...current, siteName: event.target.value }))} />
              </label>
              <label className="space-y-1.5">
                <span>Default Language</span>
                <Select
                  value={fields.defaultLanguage}
                  onChange={(value) => setFields((current) => ({ ...current, defaultLanguage: value }))}
                  options={[
                    { value: "en", label: "English" },
                    { value: "zh", label: "中文" },
                  ]}
                />
              </label>
            </div>
            <label className="block space-y-1.5">
              <span>Site Description</span>
              <Input.TextArea value={fields.siteDescription} rows={2} onChange={(event) => setFields((current) => ({ ...current, siteDescription: event.target.value }))} />
            </label>
            <div className="flex justify-end">
              <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
                <SaveOutlined aria-hidden className="size-4" />
                Save site information
              </Button>
            </div>
          </>
        ) : null}
        {saveMutation.isError ? <p role="alert" className="text-destructive">Unable to save site settings.</p> : null}
        {saveMutation.isSuccess ? <p role="status" className="text-success">Site information saved.</p> : null}
      </div>
    </ProCard>
  );
}
