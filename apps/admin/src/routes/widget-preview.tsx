import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import DOMPurify from "dompurify";
import {
  ArrowLeft,
  Code2,
  Loader2,
  Play,
  Timer,
} from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  Label,
  Badge,
} from "../lib/admin-ui";
import { widgetApi, type WidgetPreviewResponse } from "../lib/widget-api";

function isValidJson(s: string): boolean {
  if (!s.trim()) return true;
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
}

export default function WidgetPreviewPage() {
  const search = useSearch({ from: "/_auth/widget-preview" }) as { name?: string };
  const [selectedName, setSelectedName] = useState<string>(search.name ?? "");
  const [paramsJson, setParamsJson] = useState<string>("{}");
  const [previewResult, setPreviewResult] = useState<WidgetPreviewResponse | null>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [iframeHeight, setIframeHeight] = useState(300);

  const { data: widgetsData } = useQuery({
    queryKey: ["admin-widgets", 1, 200],
    queryFn: () => widgetApi.list({ page: 1, page_size: 200 }),
    placeholderData: { items: [], total: 0 },
  });
  const widgets = widgetsData?.items ?? [];

  // Sync selected widget from URL search param
  useEffect(() => {
    if (search.name && widgets.some((w) => w.name === search.name) && !selectedName) {
      setSelectedName(search.name);
    }
  }, [search.name, widgets, selectedName]);

  const previewMutation = useMutation({
    mutationFn: ({ name, params }: { name: string; params: Record<string, unknown> }) =>
      widgetApi.preview(name, { params }),
    onSuccess: (result) => {
      setPreviewResult(result);
    },
  });

  // When previewResult arrives, sanitize and write to iframe
  useEffect(() => {
    if (!previewResult || !iframeRef.current) return;
    const doc = iframeRef.current.contentDocument;
    if (!doc) return;
    const clean = DOMPurify.sanitize(previewResult.html, {
      ADD_TAGS: ["style"],
      ADD_ATTR: ["target"],
    });
    doc.open();
    doc.write(`<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Widget Preview</title>
<style>
  body { font-family: var(--font-sans, ui-sans-serif, system-ui, sans-serif); margin: 16px; color: #1a2b1a; background: #ffffff; }
</style>
</head>
<body>${clean}</body>
</html>`);
    doc.close();
    // Auto-size iframe to content
    const h = Math.max(150, Math.min(1200, doc.body.scrollHeight + 24));
    setIframeHeight(h);
  }, [previewResult]);

  const validJson = isValidJson(paramsJson);

  const handlePreview = () => {
    if (!selectedName || !validJson) return;
    const params = paramsJson.trim() ? (JSON.parse(paramsJson) as Record<string, unknown>) : {};
    previewMutation.mutate({ name: selectedName, params });
  };

  const selectedWidget = widgets.find((w) => w.name === selectedName);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/widgets">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              Widgets
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-2xl font-semibold">Widget Preview</h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              <Code2 className="size-3.5" />
              Test-render widgets in a sandboxed iframe with custom parameters.
            </p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        {/* Controls */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Preview Controls</CardTitle>
              <CardDescription>Select a widget and provide test parameters.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label>Widget</Label>
                <Select value={selectedName} onValueChange={setSelectedName}>
                  <SelectTrigger>
                    <SelectValue placeholder="Choose a widget…" />
                  </SelectTrigger>
                  <SelectContent>
                    {widgets.map((w) => (
                      <SelectItem key={w.name} value={w.name}>
                        {w.display_name}{" "}
                        <span className="ml-1 text-xs text-muted-foreground">
                          ({w.name})
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selectedWidget ? (
                  <div className="flex items-center gap-2 pt-1">
                    <Badge variant="outline" className="text-xs">
                      {selectedWidget.category}
                    </Badge>
                    <Badge
                      variant={selectedWidget.is_active ? "success" : "secondary"}
                      className="text-xs"
                    >
                      {selectedWidget.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </div>
                ) : null}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="params">Test Params (JSON)</Label>
                <Textarea
                  id="params"
                  rows={10}
                  className="font-mono text-xs"
                  value={paramsJson}
                  onChange={(e) => setParamsJson(e.target.value)}
                  placeholder='{\n  "limit": 5,\n  "show_chart": true\n}'
                />
                {!validJson ? (
                  <p className="text-xs text-destructive">Invalid JSON</p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Parameters passed to the widget renderer.
                  </p>
                )}
              </div>

              <Button
                className="w-full"
                onClick={handlePreview}
                disabled={!selectedName || !validJson || previewMutation.isPending}
              >
                {previewMutation.isPending ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Play className="size-4" />
                )}
                {previewMutation.isPending ? "Rendering…" : "Render Preview"}
              </Button>

              {previewMutation.error ? (
                <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-xs text-destructive">
                  {previewMutation.error instanceof Error
                    ? previewMutation.error.message
                    : "Preview failed"}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>

        {/* Preview pane */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <div>
                <CardTitle>Sandbox Preview</CardTitle>
                <CardDescription>
                  Rendered output — HTML is sanitized with DOMPurify.
                </CardDescription>
              </div>
              {previewResult ? (
                <div className="flex items-center gap-1.5 rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">
                  <Timer className="size-3" />
                  {previewResult.latency_ms} ms
                </div>
              ) : null}
            </CardHeader>
            <CardContent>
              <div className="overflow-hidden rounded-lg border border-border bg-background">
                <iframe
                  ref={iframeRef}
                  title="Widget Preview Sandbox"
                  sandbox="allow-same-origin"
                  className="w-full"
                  style={{ height: iframeHeight }}
                />
              </div>
              {!previewResult && !previewMutation.isPending ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  Select a widget and click <strong>Render Preview</strong> to see its output.
                </div>
              ) : null}
              {previewMutation.isPending ? (
                <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Rendering widget…
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
