/**
 * Three-pane Page Builder editor: palette (left), ordered tree (center),
 * schema-driven properties (right).
 *
 * All editing happens on an in-memory draft mirroring the ``PageDefinition``
 * contract; saving issues an optimistic ``updateDraft`` (409 on conflict).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Eye,
  Loader2,
  RotateCcw,
  RotateCw,
  Save,
  Send,
} from "lucide-react";
import { Link } from "@tanstack/react-router";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cn,
} from "../../lib/admin-ui";
import type {
  ComponentDescriptor,
  PageComponentNode,
  PageDefinitionTheme,
  PageDefinitionV2,
} from "@soymutdb/shared";
import { normalizePageDefinition } from "@soymutdb/shared";
import { pageBuilderApi } from "../../lib/page-builder-api";
import { buildPreviewDocument } from "../../lib/page-preview";
import {
  emptyHistory,
  pushHistory,
  redoHistory,
  undoHistory,
  type PageBuilderHistory,
} from "../../lib/page-builder-history";
import { ComponentPalette } from "./component-palette";
import { ComponentTree, type SelectionPath } from "./component-tree";
import { PropertyPanel } from "./property-panel";

interface PageBuilderEditorProps {
  pageId: string;
}

const PAGE_THEMES: Array<{ value: PageDefinitionTheme; label: string }> = [
  { value: "scientific-light", label: "Scientific Light" },
  { value: "scientific-dark", label: "Scientific Dark" },
  { value: "high-contrast", label: "High Contrast" },
  { value: "compact-data", label: "Compact Data" },
  { value: "print", label: "Print" },
];

const LAYOUT_DEVICES = ["desktop", "tablet", "mobile"] as const;

function emptyNode(type: string): PageComponentNode {
  return { type: type as PageComponentNode["type"], props: {} };
}

function getNode(root: PageComponentNode, path: number[]): PageComponentNode | null {
  let current: PageComponentNode | undefined = root;
  for (const idx of path) {
    const children: PageComponentNode[] | undefined = current?.children;
    if (!children || idx >= children.length) return null;
    current = children[idx];
  }
  return current ?? null;
}

/** Immutably set ``props`` on the node at ``path``. */
function setNodeProps(
  root: PageComponentNode,
  path: number[],
  props: Record<string, unknown>,
): PageComponentNode {
  if (path.length === 0) return { ...root, props };
  const idx = path[0];
  const children: PageComponentNode[] = root.children ? [...root.children] : [];
  const child = children[idx];
  if (!child) return root;
  children[idx] = setNodeProps(child, path.slice(1), props);
  return { ...root, children };
}

/** Immutably apply a function to the list of children at ``path``. */
function updateChildren(
  root: PageComponentNode,
  path: number[],
  fn: (children: PageComponentNode[]) => PageComponentNode[],
): PageComponentNode {
  if (path.length === 0) {
    return { ...root, children: fn(root.children ?? []) };
  }
  const idx = path[0];
  const children: PageComponentNode[] = root.children ? [...root.children] : [];
  const child = children[idx];
  if (!child) return root;
  children[idx] = updateChildren(child, path.slice(1), fn);
  return { ...root, children };
}

export function PageBuilderEditor({ pageId }: PageBuilderEditorProps) {
  const [draftOverride, setDraftOverride] = useState<{
    versionId: string;
    definition: PageDefinitionV2;
  } | null>(null);
  const [selectedPath, setSelectedPath] = useState<SelectionPath | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [history, setHistory] = useState<PageBuilderHistory>(emptyHistory);

  const { data: pageData, isLoading } = useQuery({
    queryKey: ["page-builder", pageId],
    queryFn: () => pageBuilderApi.get(pageId),
  });

  const { data: registryData } = useQuery({
    queryKey: ["page-builder-registry"],
    queryFn: () => pageBuilderApi.registry(),
    placeholderData: { components: [] },
  });

  const descriptors = useMemo(() => {
    const map = new Map<string, ComponentDescriptor>();
    for (const c of registryData?.components ?? []) map.set(c.renderer_key, c);
    return map;
  }, [registryData]);

  const latestVersion = useMemo(() => {
    const versions = pageData?.versions ?? [];
    return versions.length > 0 ? versions[0] : null;
  }, [pageData]);

  const latestVersionId = latestVersion?.id;
  const baselineDraft = useMemo(
    () => normalizePageDefinition(latestVersion?.definition),
    [latestVersion],
  );
  const draft =
    draftOverride && draftOverride.versionId === latestVersionId
      ? draftOverride.definition
      : baselineDraft;

  const updateDraft = (update: (current: PageDefinitionV2) => PageDefinitionV2) => {
    if (!draft || !latestVersionId) return;
    const current =
      draftOverride?.versionId === latestVersionId
        ? draftOverride.definition
        : draft;
    const next = update(current);
    setHistory((previous) => pushHistory(previous, current, next));
    setDraftOverride({ versionId: latestVersionId, definition: next });
  };

  const undo = () => {
    if (!draft || !latestVersionId) return;
    const result = undoHistory(history, draft);
    if (!result) return;
    setHistory(result.history);
    setDraftOverride({ versionId: latestVersionId, definition: result.draft });
  };

  const redo = () => {
    if (!draft || !latestVersionId) return;
    const result = redoHistory(history, draft);
    if (!result) return;
    setHistory(result.history);
    setDraftOverride({ versionId: latestVersionId, definition: result.draft });
  };

  const baseVersion = latestVersion?.version ?? 0;

  const saveMutation = useMutation({
    mutationFn: () =>
      pageBuilderApi.updateDraft(pageId, {
        base_version: baseVersion,
        definition: draft!,
      }),
    onSuccess: (newVersion) => {
      setMessage({ kind: "success", text: `Saved as version ${newVersion.version}.` });
    },
    onError: (err: unknown) => {
      const e = err as { status?: number; message?: string };
      setMessage({
        kind: "error",
        text:
          e?.status === 409
            ? "Version conflict — refresh and re-apply your changes."
            : (e?.message ?? "Save failed."),
      });
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => pageBuilderApi.preview(pageId, { definition: draft! }),
    onSuccess: (result) => {
      setMessage({
        kind: "success",
        text: `Preview valid (would become version ${result.version_preview}).`,
      });
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setMessage({ kind: "error", text: e?.message ?? "Preview invalid." });
    },
  });

  const publishMutation = useMutation({
    mutationFn: () => pageBuilderApi.publishRequest(pageId, {}),
    onSuccess: (result) => {
      setMessage({ kind: "success", text: `Publish requested (event ${result.event_id}).` });
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setMessage({ kind: "error", text: e?.message ?? "Publish request failed." });
    },
  });

  if (isLoading || (latestVersion && !draft)) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        <Loader2 className="inline size-4 animate-spin" /> Loading…
      </div>
    );
  }

  if (!latestVersion || !draft) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        Page not found or has no versions.
      </div>
    );
  }

  const selectedNode = selectedPath ? getNode(draft.root, selectedPath.path) : null;
  const selectedDescriptor = selectedNode ? descriptors.get(selectedNode.type) ?? null : null;

  const updateSelectedProps = (props: Record<string, unknown>) => {
    if (!selectedPath) return;
    updateDraft((current) => ({
      ...current,
      root: setNodeProps(current.root, selectedPath.path, props),
    }));
  };

  const updateTheme = (theme: PageDefinitionTheme) => {
    updateDraft((current) => ({ ...current, theme_id: theme }));
  };

  const updateLayout = (
    device: (typeof LAYOUT_DEVICES)[number],
    field: string,
    value: number | null,
  ) => {
    updateDraft((current) => ({
      ...current,
      layouts: {
        ...current.layouts,
        [device]: {
          ...current.layouts[device],
          [field]: value,
        },
      },
    }));
  };

  const addDataSource = () => {
    updateDraft((current) => ({
      ...current,
      data_sources: [
        ...current.data_sources,
        {
          id: `source-${Date.now()}`,
          kind: "dataset",
          config: {},
        },
      ],
    }));
  };

  const removeDataSource = (id: string) => {
    updateDraft((current) => ({
      ...current,
      data_sources: current.data_sources.filter((source) => source.id !== id),
    }));
  };

  const addChild = (type: string) => {
    updateDraft((current) => ({
      ...current,
      root: {
        ...current.root,
        children: [...(current.root.children ?? []), emptyNode(type)],
      },
    }));
  };

  const removeNode = (path: SelectionPath) => {
    // First pass supports single-level (root child) removal.
    if (path.path.length !== 1) {
      setMessage({ kind: "error", text: "Nested removal is not yet supported." });
      return;
    }
    const idx = path.path[0];
    updateDraft((current) => ({
      ...current,
      root: {
        ...current.root,
        children: (current.root.children ?? []).filter((_, i) => i !== idx),
      },
    }));
    setSelectedPath(null);
  };

  const reorder = (_children: PageComponentNode[], from: number, to: number) => {
    updateDraft((current) => ({
      ...current,
      root: updateChildren(current.root, [], (children) => arrayMove(children, from, to)),
    }));
  };

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/page-builder">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              Page Builder
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-xl font-semibold">
              {pageData?.route}
            </h2>
            <p className="text-sm text-muted-foreground">
              Latest version {baseVersion} · title key {pageData?.title_key}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={undo}
            disabled={history.past.length === 0}
            aria-label="Undo"
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={redo}
            disabled={history.future.length === 0}
            aria-label="Redo"
          >
            <RotateCw className="size-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setPreviewOpen(true);
              previewMutation.mutate();
            }}
            disabled={previewMutation.isPending}
          >
            <Eye className="size-4" />
            Preview
          </Button>
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !draft}
          >
            {saveMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Save className="size-4" />
            )}
            Save Draft
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => publishMutation.mutate()}
            disabled={publishMutation.isPending}
          >
            <Send className="size-4" />
            Publish
          </Button>
        </div>
      </div>

      {message ? (
        <div
          className={cn(
            "rounded-md border px-4 py-2 text-sm",
            message.kind === "success"
              ? "border-primary/30 bg-primary/10 text-primary"
              : "border-destructive/30 bg-destructive/10 text-destructive",
          )}
          role="status"
        >
          {message.text}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Theme</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Label htmlFor="page-theme">Page theme</Label>
            <Select
              value={draft.theme_id}
              onValueChange={(value) =>
                updateTheme(value as PageDefinitionTheme)
              }
            >
              <SelectTrigger id="page-theme">
                <SelectValue placeholder="Select theme" />
              </SelectTrigger>
              <SelectContent>
                {PAGE_THEMES.map((theme) => (
                  <SelectItem key={theme.value} value={theme.value}>
                    {theme.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Responsive Layout</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {LAYOUT_DEVICES.map((device) => (
              <div key={device} className="space-y-2">
                <Label htmlFor={`layout-${device}`} className="capitalize">
                  {device}
                </Label>
                <Input
                  id={`layout-${device}`}
                  type="number"
                  min={1}
                  max={24}
                  value={String(
                    draft.layouts[device]?.columns ?? "",
                  )}
                  onChange={(event) => {
                    const raw = event.target.value;
                    updateLayout(
                      device,
                      "columns",
                      raw === "" ? null : Number(raw),
                    );
                  }}
                />
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Data Sources</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {draft.data_sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No bounded data source bound to this page yet.
              </p>
            ) : (
              draft.data_sources.map((source) => (
                <div
                  key={source.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate">
                    {source.id} · {source.kind}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => removeDataSource(source.id)}
                  >
                    Remove
                  </Button>
                </div>
              ))
            )}
            <Button variant="outline" size="sm" onClick={addDataSource}>
              Add data source
            </Button>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-[240px_1fr_320px]">
        <ComponentPalette
          components={registryData?.components ?? []}
          onAdd={addChild}
        />
        <ComponentTree
          root={draft.root}
          descriptors={descriptors}
          selectedPath={selectedPath}
          onSelect={setSelectedPath}
          onRemoveNode={removeNode}
          onReorder={reorder}
        />
        <PropertyPanel
          component={selectedDescriptor}
          node={selectedNode ?? undefined}
          onChangeProps={updateSelectedProps}
        />
      </div>

      {previewOpen ? (
        <div className="rounded-lg border border-border bg-muted/30 p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Live Preview</h3>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPreviewOpen(false)}
            >
              Close
            </Button>
          </div>
          <iframe
            title="Page definition preview"
            sandbox=""
            srcDoc={buildPreviewDocument(draft)}
            className="h-[70vh] w-full rounded-md border border-border bg-background"
            data-testid="page-builder-preview"
          />
        </div>
      ) : null}
    </div>
  );
}

function arrayMove<T>(arr: T[], from: number, to: number): T[] {
  const next = arr.slice();
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

export default PageBuilderEditor;
