import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ToggleLeft, ToggleRight } from "lucide-react";
import { Button, Badge, Card, CardContent, CardHeader, CardTitle, PageHeader } from "@soymutdb/ui";
import { capabilitiesApi, type FeatureDefinitionResponse } from "@soymutdb/api-client";

export default function FeaturesPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin-features"],
    queryFn: capabilitiesApi.adminGet,
  });
  const mutation = useMutation({
    mutationFn: (feature: FeatureDefinitionResponse) =>
      capabilitiesApi.adminUpdate({ [feature.key]: !feature.enabled }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-features"] }),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Feature Flags"
        description="Enable or disable registered capabilities atomically. Disabling rejects new requests and does not kill running jobs."
      />
      {error ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-4 text-sm text-destructive">
            <AlertTriangle className="size-4" /> Failed to load feature flags.
          </CardContent>
        </Card>
      ) : null}
      <Card>
        <CardHeader><CardTitle>Registered capabilities</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {(data?.features ?? []).map((feature) => (
            <div key={feature.key} className="flex items-center justify-between gap-4 rounded-lg border p-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <code className="text-sm">{feature.key}</code>
                  {feature.public ? <Badge variant="outline">public</Badge> : <Badge variant="secondary">internal</Badge>}
                </div>
                <p className="mt-1 text-sm text-muted-foreground">{feature.description}</p>
                <p className="mt-1 text-xs text-muted-foreground">disable: {feature.disable_behavior}</p>
              </div>
              <Button
                variant={feature.enabled ? "default" : "outline"}
                size="sm"
                disabled={isLoading || mutation.isPending}
                onClick={() => mutation.mutate(feature)}
                aria-label={`${feature.enabled ? "Disable" : "Enable"} ${feature.key}`}
              >
                {feature.enabled ? <ToggleRight className="mr-1 size-4" /> : <ToggleLeft className="mr-1 size-4" />}
                {feature.enabled ? "Enabled" : "Disabled"}
              </Button>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
