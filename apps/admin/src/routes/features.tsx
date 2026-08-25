import { WarningOutlined, CloseOutlined, CheckOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Typography } from "@/lib/antd";
import { capabilitiesApi, type FeatureDefinitionResponse } from "@soymutdb/api-client";
import { resolvePluginState } from "../lib/capability-state";

export default function FeaturesPage() {
  const queryClient = useQueryClient();
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-features"] }),
  });

  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>"Feature Flags"</Typography.Title><Typography.Text type="secondary">"Enable or disable registered capabilities atomically. Disabling rejects new requests and does not kill running jobs."</Typography.Text></div>
      {featuresQuery.error ? (
        <Card>
          <div role="alert" className="flex items-center gap-2 p-4 text-sm text-destructive">
            <WarningOutlined className="size-4" /> Failed to load feature flags.
          </div>
        </Card>
      ) : null}
      <Card>
        <Typography.Title level={5}>Registered capabilities</Typography.Title>
        <div className="space-y-3">
          {featuresQuery.isPending ? (
            <p role="status" className="text-sm text-muted-foreground">Loading feature flags…</p>
          ) : null}
          {featuresQuery.isSuccess && featuresQuery.data.features.length === 0 ? (
            <p className="text-sm text-muted-foreground">No registered feature flags.</p>
          ) : null}
          {(featuresQuery.data?.features ?? []).map((feature) => (
            <div key={feature.key} className="flex items-center justify-between gap-4 rounded-lg border p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <code className="text-sm">{feature.key}</code>
                  {feature.public ? <Badge >public</Badge> : <Badge >internal</Badge>}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{feature.description}</p>
                <p className="mt-1 text-xs text-muted-foreground">disable: {feature.disable_behavior}</p>
              </div>
              <Button
                type={feature.enabled ? "primary" : "default"}
                size="small"
                disabled={featuresQuery.isPending || mutation.isPending}
                onClick={() => mutation.mutate(feature)}
                aria-label={`${feature.enabled ? "Disable" : "Enable"} ${feature.key}`}
              >
                {feature.enabled ? <CheckOutlined className="mr-1 size-4" /> : <CloseOutlined className="mr-1 size-4" />}
                {feature.enabled ? "Enabled" : "Disabled"}
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <Typography.Title level={5}>Plugin runtime</Typography.Title>
        <div className="space-y-3">
          {pluginsQuery.isPending ? (
            <p role="status" className="text-sm text-muted-foreground">Loading plugin status…</p>
          ) : null}
          {pluginsQuery.isError ? (
            <div
              role="alert"
              aria-label="Plugin status unavailable"
              className="flex items-center gap-2 text-sm text-destructive"
            >
              <WarningOutlined className="size-4" /> Unable to load plugin status.
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
                          {status.reason ?? "ready"}
                        </p>
                      </div>
                      <Badge color={status.state === "available" ? "green" : "default"}>
                        {status.state === "available" ? "Available" : "Unavailable"}
                      </Badge>
                      {plugin?.version ? (
                        <span className="text-xs text-muted-foreground">v{plugin.version}</span>
                      ) : null}
                    </div>
                  );
                },
              )
            : null}
        </div>
      </Card>
    </div>
  );
}
