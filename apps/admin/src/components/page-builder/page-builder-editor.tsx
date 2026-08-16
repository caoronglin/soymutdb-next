/**
 * Three-pane Page Builder editor: palette (left), ordered tree (center),
 * schema-driven properties (right).
 *
 * All editing happens on an in-memory draft mirroring the ``PageDefinition``
 * contract; saving issues an optimistic ``updateDraft`` (409 on conflict).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, Eye, Loader2, Save, Send } from "lucide-react";
import { Link } from "@tanstack/react-router";
import { Button, cn } from "@soymutdb/ui";
import type {
  ComponentDescriptor,
  PageComponentNode,
  PageDefinition,
} from "@soymutdb/shared";
import { pageBuilderApi } from "../../lib/page-builder-api";
import { ComponentPalette } from "./component-palette";
import { ComponentTree, type SelectionPath } from "./component-tree";
import { PropertyPanel } from "./property-panel";

interface PageBuilderEditorProps {
  pageId: string;
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
  const [draft, setDraft] = useState<PageDefinition | null>(null);
  const [selectedPath, setSelectedPath] = useState<SelectionPath | null>(null);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

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

  // Initialise the draft from the latest version exactly once.
  const [initialized, setInitialized] = useState(false);
  if (!initialized && latestVersion && !draft) {
    setDraft(latestVersion.definition as PageDefinition);
    setInitialized(true);
  }

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
    setDraft((d) =>
      d ? { ...d, root: setNodeProps(d.root, selectedPath.path, props) } : d,
    );
  };

  const addChild = (type: string) => {
    setDraft((d) =>
      d
        ? {
            ...d,
            root: { ...d.root, children: [...(d.root.children ?? []), emptyNode(type)] },
          }
        : d,
    );
  };

  const removeNode = (path: SelectionPath) => {
    // First pass supports single-level (root child) removal.
    if (path.path.length !== 1) {
      setMessage({ kind: "error", text: "Nested removal is not yet supported." });
      return;
    }
    const idx = path.path[0];
    setDraft((d) =>
      d
        ? {
            ...d,
            root: {
              ...d.root,
              children: (d.root.children ?? []).filter((_, i) => i !== idx),
            },
          }
        : d,
    );
    setSelectedPath(null);
  };

  const reorder = (_children: PageComponentNode[], from: number, to: number) => {
    setDraft((d) =>
      d
        ? {
            ...d,
            root: updateChildren(d.root, [], (c) => arrayMove(c, from, to)),
          }
        : d,
    );
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
            variant="outline"
            size="sm"
            onClick={() => previewMutation.mutate()}
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
