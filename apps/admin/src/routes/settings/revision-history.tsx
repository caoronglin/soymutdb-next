import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { adminSettingsApi, type SettingsHistoryItem } from "@soymutdb/api-client";
import { Button, Card, Input, Select, Typography } from "@/lib/antd";
import { ConfirmDialog } from "@/components/confirm-dialog";

export interface SettingsHistorySection {
  id: string;
  label: string;
}

export function SettingsRevisionHistory({ sections }: { sections: SettingsHistorySection[] }) {
  const queryClient = useQueryClient();
  const [section, setSection] = useState(sections[0]?.id ?? "");
  const [target, setTarget] = useState<SettingsHistoryItem | null>(null);
  const [reason, setReason] = useState("");
  const historyQuery = useQuery({
    queryKey: ["admin-settings-history", section],
    queryFn: () => adminSettingsApi.history(section),
    enabled: Boolean(section),
  });
  const rollbackMutation = useMutation({
    mutationFn: (item: SettingsHistoryItem) =>
      adminSettingsApi.rollback(section, {
        expected_version: historyQuery.data?.current_version ?? 0,
        target_version: item.version,
        reason: reason.trim(),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["admin-settings-history", section] });
      void queryClient.invalidateQueries({ queryKey: ["admin-settings"] });
      setTarget(null);
      setReason("");
    },
  });

  if (!sections.length) return null;
  const currentVersion = historyQuery.data?.current_version ?? 0;
  return (
    <Card className="border-dashed">
      <div className="space-y-4">
        <div>
          <Typography.Title level={5}>Revision history</Typography.Title>
          <Typography.Text type="secondary">Review a domain section before restoring an earlier audited snapshot.</Typography.Text>
        </div>
        <label className="block space-y-1.5">
          <span className="text-sm font-medium">Section</span>
          <Select value={section} onChange={setSection} className="w-full">
            {sections.map((item) => <Select.Option key={item.id} value={item.id}>{item.label}</Select.Option>)}
          </Select>
        </label>
        {historyQuery.isLoading ? <p role="status">Loading revision history…</p> : null}
        {historyQuery.isError ? <p role="alert" className="text-destructive">Unable to load revision history.</p> : null}
        {!historyQuery.isLoading && !historyQuery.isError && historyQuery.data?.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No revisions have been recorded for this section.</p>
        ) : null}
        <ol className="space-y-2" aria-label="Revision history">
          {(historyQuery.data?.items ?? []).map((item) => (
            <li key={item.version} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-border p-3">
              <div className="text-sm">
                <p className="font-medium">v{item.version} {item.version === currentVersion ? "(current)" : ""}</p>
                <p className="text-muted-foreground">{item.action} · {new Date(item.created_at).toLocaleString()}</p>
                {item.reason ? <p className="text-muted-foreground">Reason: {item.reason}</p> : null}
              </div>
              <Button type="default" danger onClick={() => setTarget(item)} disabled={item.version === currentVersion}>
                Restore v{item.version}
              </Button>
            </li>
          ))}
        </ol>
      </div>
      {target ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => { if (!open) { setTarget(null); setReason(""); } }}
          title={`Restore ${section} to v${target.version}?`}
          description="This creates a new audited revision from the selected snapshot. The current values remain available in history."
          confirmLabel="Restore revision"
          severity="destructive"
          confirmPhrase="ROLLBACK"
          loading={rollbackMutation.isPending}
          onConfirm={() => { if (reason.trim()) rollbackMutation.mutate(target); }}
        >
          <label className="block space-y-1.5">
            <span className="text-sm font-medium">Reason for restoration</span>
            <Input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={512} placeholder="Required audit reason" />
          </label>
          {rollbackMutation.error ? <p role="alert" className="mt-2 text-sm text-destructive">Unable to restore this revision. Refresh history and retry if the version changed.</p> : null}
        </ConfirmDialog>
      ) : null}
    </Card>
  );
}
