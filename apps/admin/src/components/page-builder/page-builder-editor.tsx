/**
 * Three-pane Page Builder editor: palette (left), ordered tree (center),
 * schema-driven properties (right).
 *
 * All editing happens on an in-memory draft mirroring the ``PageDefinition``
 * contract; saving issues an optimistic ``updateDraft`` (409 on conflict).
 */

import { ArrowLeftOutlined, EyeOutlined, LoadingOutlined, RedoOutlined, ReloadOutlined, SaveOutlined, SendOutlined } from "@ant-design/icons";
import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { cn } from "../../lib/cn";
import { Button, Card, Input, Select } from "@/lib/antd";
import type {
  ComponentDescriptor,
  PageComponentNode,
  PageDefinitionTheme,
  PageDefinitionV2,
} from "@soymutdb/shared";
import { normalizePageDefinition } from "@soymutdb/shared";
import { capabilitiesApi, getPluginAvailability } from "@soymutdb/api-client";
import { pageBuilderApi } from "../../lib/page-builder-api";
import { buildPreviewDocument } from "../../lib/page-preview";
import { moveTreeNode, removeTreeNode } from "../../lib/page-builder-tree";
import {
  emptyHistory,
  pushHistory,
  redoHistory,
  undoHistory,
  type PageBuilderHistory,
} from "../../lib/page-builder-history";
import { AdminUsageGuide } from "../admin-usage-guide";
import { ComponentPalette } from "./component-palette";
import { ComponentTree, type SelectionPath } from "./component-tree";
import { PropertyPanel } from "./property-panel";
import { ReleaseReadiness, type SchemaReadiness } from "./release-readiness";

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

const LAUNCHER_PLUGIN_KEYS: Record<string, string> = {
  blast_launcher: "blast",
  jbrowse_launcher: "jbrowse",
  ontology_relationship_graph: "ols4",
};

function requiredLauncherPlugins(root: PageComponentNode): string[] {
  const keys = new Set<string>();
  function walk(node: PageComponentNode): void {
    const plugin = LAUNCHER_PLUGIN_KEYS[node.type];
    if (plugin) keys.add(plugin);
    for (const child of node.children ?? []) walk(child);
  }
  walk(root);
  return [...keys].sort();
}

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

export function PageBuilderEditor({ pageId }: PageBuilderEditorProps) {
  const { t } = useTranslation();
  const [draftOverride, setDraftOverride] = useState<{
    versionId: string;
    definition: PageDefinitionV2;
  } | null>(null);
  const [selectedPath, setSelectedPath] = useState<SelectionPath | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [history, setHistory] = useState<PageBuilderHistory>(emptyHistory);
  const [schemaReadiness, setSchemaReadiness] = useState<SchemaReadiness>("not-run");
  const [responsiveReviewed, setResponsiveReviewed] = useState(false);
  const [pluginWarning, setPluginWarning] = useState<string | null>(null);

  const { data: pageData, isLoading } = useQuery({
    queryKey: ["page-builder", pageId],
    queryFn: () => pageBuilderApi.get(pageId),
  });

  const { data: registryData } = useQuery({
    queryKey: ["page-builder-registry"],
    queryFn: () => pageBuilderApi.registry(),
    placeholderData: { components: [] },
  });

  const capabilitiesQuery = useQuery({
    queryKey: ["public-capabilities"],
    queryFn: capabilitiesApi.get,
    staleTime: 30_000,
    retry: false,
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


  const launcherPlugins = useMemo(
    () => (draft ? requiredLauncherPlugins(draft.root) : []),
    [draft],
  );
  const pluginStatuses = useMemo(() => {
    if (!capabilitiesQuery.data) return [];
    return launcherPlugins.map((key) => ({ key, ...getPluginAvailability(capabilitiesQuery.data.plugins[key]) }));
  }, [capabilitiesQuery.data, launcherPlugins]);

  const updateDraft = (update: (current: PageDefinitionV2) => PageDefinitionV2) => {
    if (!draft || !latestVersionId) return;
    const current =
      draftOverride?.versionId === latestVersionId
        ? draftOverride.definition
        : draft;
    const next = update(current);
    setHistory((previous) => pushHistory(previous, current, next));
    setSchemaReadiness("not-run");
    setResponsiveReviewed(false);
    setPluginWarning(null);
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
      setMessage({ kind: "success", text: t("admin.builder.savedAsVersion", { defaultValue: "Saved as version {{version}}.", version: newVersion.version }) });
    },
    onError: (err: unknown) => {
      const e = err as { status?: number; message?: string };
      setMessage({
        kind: "error",
        text:
          e?.status === 409
            ? t("admin.builder.versionConflict", { defaultValue: "Version conflict — refresh and re-apply your changes." })
            : (e?.message ?? t("admin.builder.saveFailed", { defaultValue: "Save failed." })),
      });
    },
  });

  const previewMutation = useMutation({
    mutationFn: () => pageBuilderApi.preview(pageId, { definition: draft! }),
    onSuccess: (result) => {
      setSchemaReadiness("valid");
      setMessage({
        kind: "success",
        text: t("admin.builder.previewValid", { defaultValue: "Preview valid (would become version {{version}}).", version: result.version_preview }),
      });
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setSchemaReadiness("invalid");
      setMessage({ kind: "error", text: e?.message ?? t("admin.builder.previewInvalid", { defaultValue: "Preview invalid." }) });
    },
  });

  const publishMutation = useMutation({
    mutationFn: () => pageBuilderApi.publishRequest(pageId, {}),
    onSuccess: (result) => {
      setMessage({ kind: "success", text: t("admin.builder.publishRequested", { defaultValue: "Publish requested (event {{eventId}}).", eventId: result.event_id }) });
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      const text = e?.message ?? t("admin.builder.publishFailed", { defaultValue: "Publish request failed." });
      if (/plugin|launcher|blast|jbrowse/i.test(text)) setPluginWarning(text);
      setMessage({ kind: "error", text });
    },
  });

  if (isLoading || (latestVersion && !draft)) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        <LoadingOutlined className="inline size-4 animate-spin" /> {t("admin.builder.loading", { defaultValue: "Loading…" })}
      </div>
    );
  }

  if (!latestVersion || !draft) {
    return (
      <div className="p-6 text-sm text-muted-foreground">
        {t("admin.builder.pageNotFound", { defaultValue: "Page not found or has no versions." })}
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
    if (path.path.length === 0) return;
    updateDraft((current) => ({
      ...current,
      root: removeTreeNode(current.root, path.path),
    }));
    setSelectedPath(null);
  };

  const moveNode = (from: number[], over: number[]) => {
    if (from.length === 0 || over.length === 0 || from.join(".") === over.join(".")) return;
    updateDraft((current) => ({
      ...current,
      root: moveTreeNode(current.root, from, over, (type) => descriptors.get(type)?.is_layout_container === true),
    }));
  };

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/page-builder">
            <Button type="text" size="small">
              <ArrowLeftOutlined className="size-4" />
              {t("admin.builder.title", { defaultValue: "Page Builder" })}
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-xl font-semibold">
              {pageData?.route}
            </h2>
            <p className="text-sm text-muted-foreground">
              {t("admin.builder.latestVersionLine", { defaultValue: "Latest version {{version}} · title key {{titleKey}}", version: baseVersion, titleKey: pageData?.title_key })}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="text"
            size="small"
            onClick={undo}
            disabled={history.past.length === 0}
            aria-label={t("admin.builder.undo", { defaultValue: "Undo" })}
          >
            <RedoOutlined className="size-4" />
          </Button>
          <Button
            type="text"
            size="small"
            onClick={redo}
            disabled={history.future.length === 0}
            aria-label={t("admin.builder.redo", { defaultValue: "Redo" })}
          >
            <ReloadOutlined className="size-4" />
          </Button>
          <Button

            size="small"
            onClick={() => {
              setPreviewOpen(true);
              previewMutation.mutate();
            }}
            disabled={previewMutation.isPending}
          >
            <EyeOutlined className="size-4" />
            {t("admin.builder.preview", { defaultValue: "Preview" })}
          </Button>
          <Button
            size="small"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !draft}
          >
            {saveMutation.isPending ? (
              <LoadingOutlined className="size-4 animate-spin" />
            ) : (
              <SaveOutlined className="size-4" />
            )}
            {t("admin.builder.saveDraft", { defaultValue: "Save Draft" })}
          </Button>
          <Button

            size="small"
            onClick={() => publishMutation.mutate()}
            disabled={publishMutation.isPending}
          >
            <SendOutlined className="size-4" />
            {t("admin.builder.publish", { defaultValue: "Publish" })}
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

      <ReleaseReadiness
        schema={schemaReadiness}
        responsiveReviewed={responsiveReviewed}
        unsavedChanges={draftOverride !== null}
        pluginWarning={pluginWarning}
        pluginStatuses={pluginStatuses}
        pluginStatusUnavailable={launcherPlugins.length > 0 && capabilitiesQuery.isError}
        onResponsiveReviewedChange={setResponsiveReviewed}
      />

      <AdminUsageGuide
        items={[
          {
            key: "editor",
            title: t("admin.usage.builderTitle", { defaultValue: "Page template workflow" }),
            steps: [
              t("admin.usage.builderStep1", { defaultValue: "Choose a bounded template that matches the page purpose." }),
              t("admin.usage.builderStep2", { defaultValue: "Edit components through the server registry." }),
              t("admin.usage.builderStep3", { defaultValue: "Preview and fix responsive layout before saving." }),
              t("admin.usage.builderStep4", { defaultValue: "Publish after version and data sources are verified." }),
            ],
            api: ["GET /admin/page-builder/pages/{id}", "GET /admin/page-builder/registry", "PUT /admin/page-builder/pages/{id}/draft", "POST /admin/page-builder/pages/{id}/preview", "POST /admin/page-builder/pages/{id}/publish-request"],
            tables: ["page_definitions", "page_definition_versions", "outbox_events"],
            note: t("admin.usage.builderNote", { defaultValue: "Published versions are immutable; publish requests flow through the outbox." }),
          },
        ]}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={t("admin.builder.themeTitle", { defaultValue: "Theme" })}>
          <div className="space-y-3">
            <label htmlFor="page-theme" className="text-sm font-medium">{t("admin.builder.pageTheme", { defaultValue: "Page theme" })}</label>
            <Select
              id="page-theme"
              value={draft.theme_id}
              options={PAGE_THEMES.map((theme) => ({ value: theme.value, label: t(`admin.builder.theme_${theme.value.replace(/-/g, "_")}`, { defaultValue: theme.label }) }))}
              onChange={(value) => updateTheme(value as PageDefinitionTheme)}
              className="w-full"
            />
          </div>
        </Card>

        <Card title={t("admin.builder.responsiveLayoutTitle", { defaultValue: "Responsive Layout" })}>
          <div className="space-y-4">
            {LAYOUT_DEVICES.map((device) => (
              <div key={device} className="space-y-2">
                <label htmlFor={`layout-${device}`} className="capitalize text-sm font-medium">
                  {t(`admin.builder.device_${device.replace(/-/g, "_")}`, { defaultValue: device })}
                </label>
                <Input
                  id={`layout-${device}`}
                  type="number"
                  min={1}
                  max={24}
                  value={String(draft.layouts[device]?.columns ?? "")}
                  onChange={(event) => {
                    const raw = event.target.value;
                    updateLayout(device, "columns", raw === "" ? null : Number(raw));
                  }}
                />
              </div>
            ))}
          </div>
        </Card>

        <Card title={t("admin.builder.dataSourcesTitle", { defaultValue: "Data Sources" })}>
          <div className="space-y-2">
            {draft.data_sources.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t("admin.builder.noDataSources", { defaultValue: "No bounded data source bound to this page yet." })}
              </p>
            ) : (
              draft.data_sources.map((source) => (
                <div
                  key={source.id}
                  className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
                >
                  <span className="min-w-0 truncate">{source.id} · {source.kind}</span>
                  <Button type="text" size="small" onClick={() => removeDataSource(source.id)}>
                    {t("admin.builder.removeDataSource", { defaultValue: "Remove" })}
                  </Button>
                </div>
              ))
            )}
            <Button type="default" size="small" onClick={addDataSource}>
              {t("admin.builder.addDataSource", { defaultValue: "Add data source" })}
            </Button>
          </div>
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
          onMove={moveNode}
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
            <h3 className="text-sm font-semibold">{t("admin.builder.livePreview", { defaultValue: "Live Preview" })}</h3>
            <Button
              type="text"
              size="small"
              onClick={() => setPreviewOpen(false)}
            >
              {t("admin.builder.close", { defaultValue: "Close" })}
            </Button>
          </div>
          <iframe
            title={t("admin.builder.previewIframeTitle", { defaultValue: "Page definition preview" })}
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


export default PageBuilderEditor;
