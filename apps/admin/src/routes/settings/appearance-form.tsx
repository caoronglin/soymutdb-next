import { BgColorsOutlined, SaveOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { Button, Card, ColorPicker, Typography } from "@/lib/antd";
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
  const queryClient = useQueryClient();
  const [pendingColor, setPendingColor] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["admin-settings", "general"],
    queryFn: () => http.get<GeneralSettings>("/admin/settings/general"),
  });
  const currentColor = pendingColor ?? normalizedColor(query.data?.primaryColor);
  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = { ...(query.data ?? {}), primaryColor: currentColor };
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
    <Card>
      <div className="space-y-4">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2 text-base">
            <BgColorsOutlined className="size-4 text-primary" aria-hidden />
            Appearance
          </Typography.Title>
          <Typography.Text type="secondary">Configure the administrator interface primary colour.</Typography.Text>
        </div>
        {query.isLoading ? <p role="status">Loading appearance settings…</p> : null}
        {query.isError ? <p role="alert" className="text-destructive">Unable to load appearance settings.</p> : null}
        {!query.isLoading && !query.isError ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-dashed border-border bg-muted/20 p-4">
              <div className="min-w-0">
                <p className="font-medium">Primary color</p>
                <p className="text-sm text-muted-foreground">Controls Ant Design buttons, links, tags, and selected states.</p>
              </div>
              <ColorPicker
                value={currentColor}
                format="hex"
                showText
                aria-label="Primary color"
                onChangeComplete={(color) => setPendingColor(color.toHexString())}
              />
            </div>
            <div className="flex justify-end">
              <Button onClick={() => saveMutation.mutate()} loading={saveMutation.isPending}>
                <SaveOutlined aria-hidden className="size-4" />
                Save appearance
              </Button>
            </div>
          </>
        ) : null}
        {saveMutation.isError ? <p role="alert" className="text-destructive">Unable to save appearance settings.</p> : null}
        {saveMutation.isSuccess ? <p role="status" className="text-success">Appearance saved.</p> : null}
      </div>
    </Card>
  );
}
