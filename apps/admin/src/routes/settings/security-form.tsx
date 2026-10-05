import { SafetyOutlined, SaveOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { Badge, Button, Input, ProCard, Typography } from "@/lib/antd";

type SecuritySettings = Record<string, unknown>;

interface SecurityFields {
  sessionTimeoutMinutes: string;
  maxLoginAttempts: string;
  passwordMinLength: string;
  requireTwoFactor: string;
}

function toSecurityFields(values: SecuritySettings | undefined): SecurityFields {
  return {
    sessionTimeoutMinutes: String(values?.sessionTimeoutMinutes ?? "60"),
    maxLoginAttempts: String(values?.maxLoginAttempts ?? "5"),
    passwordMinLength: String(values?.passwordMinLength ?? "8"),
    requireTwoFactor: String(values?.requireTwoFactor ?? "false"),
  };
}

export function SecuritySettingsForm() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["admin-settings", "security"],
    queryFn: () => http.get<SecuritySettings>("/admin/settings/security"),
  });
  const [fields, setFields] = useState<SecurityFields>(() => toSecurityFields(undefined));
  useEffect(() => {
    if (query.data) setFields(toSecurityFields(query.data));
  }, [query.data]);
  const saveMutation = useMutation({
    mutationFn: () => http.put("/admin/settings/security", { json: { ...(query.data ?? {}), ...fields } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", "security"] });
      void queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
    },
  });

  return (
    <ProCard>
      <div className="space-y-4">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <SafetyOutlined className="size-4 text-primary" aria-hidden />
            Security
          </Typography.Title>
          <Typography.Text type="secondary">Authentication and access-control settings.</Typography.Text>
        </div>
        {query.isLoading ? <p role="status">Loading security settings…</p> : null}
        {query.isError ? <p role="alert" className="text-destructive">Unable to load security settings.</p> : null}
        {!query.isLoading && !query.isError ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5"><span>Session Timeout (minutes)</span><Input type="number" value={fields.sessionTimeoutMinutes} onChange={(event) => setFields((current) => ({ ...current, sessionTimeoutMinutes: event.target.value }))} /></label>
              <label className="space-y-1.5"><span>Max Login Attempts</span><Input type="number" value={fields.maxLoginAttempts} onChange={(event) => setFields((current) => ({ ...current, maxLoginAttempts: event.target.value }))} /></label>
              <label className="space-y-1.5"><span>Password Min Length</span><Input type="number" value={fields.passwordMinLength} onChange={(event) => setFields((current) => ({ ...current, passwordMinLength: event.target.value }))} /></label>
              <div className="space-y-1.5"><span>Two-Factor Auth</span><div className="flex items-center gap-2 pt-2"><Badge color={fields.requireTwoFactor === "true" ? "success" : "secondary"}>{fields.requireTwoFactor === "true" ? "Required" : "Optional"}</Badge><Button type="default" size="small" onClick={() => setFields((current) => ({ ...current, requireTwoFactor: current.requireTwoFactor === "true" ? "false" : "true" }))}>Toggle</Button></div></div>
            </div>
            <div className="flex justify-end"><Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}><SaveOutlined aria-hidden className="size-4" />Save security</Button></div>
          </>
        ) : null}
        {saveMutation.isError ? <p role="alert" className="text-destructive">Unable to save security settings.</p> : null}
        {saveMutation.isSuccess ? <p role="status" className="text-success">Security settings saved.</p> : null}
      </div>
    </ProCard>
  );
}
