/**
 * Page Builder — visual editor.
 *
 * Three panes: the server registry palette, a drag-and-drop component canvas,
 * and a schema-driven property inspector. The registry returned by
 * `GET /admin/page-builder/registry` is the only source of component types and
 * `config_schema` shapes, so the editor can never invent a renderer the server
 * would reject. Saves go through `PUT /draft` (optimistic `base_version`),
 * preview snapshots through `POST /preview`, and publication uses the explicit
 * `POST /publish` step — nothing reaches the public site without it.
 */
import * as React from "react";
import dayjs from "dayjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowLeftOutlined,
  DeleteOutlined,
  EyeOutlined,
  HolderOutlined,
  PlusOutlined,
  SaveOutlined,
  SendOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Empty,
  Flex,
  Form,
  Input,
  InputNumber,
  Modal,
  PageContainer,
  ProCard,
  Select,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "@/lib/antd";
import { adminPageBuilderApi } from "@soymutdb/api-client";
import { MediaPicker } from "@/components/media-picker";
import {
  isLayoutContainer,
  normalizePageDefinition,
  type ComponentDescriptor,
  type PageComponentNode,
  type PageDefinitionV2,
  type PageDefinitionVersion,
} from "@soymutdb/shared";
import {
  PAGE_THEMES,
  appendChild,
  componentLabel,
  descriptorFor,
  emptyDefinition,
  enumValues,
  fieldKind,
  insertionTarget,
  listFields,
  moveChild,
  nodeAt,
  nodeFromDescriptor,
  pathEquals,
  removeAt,
  summarizeNode,
  updateAt,
  type NodePath,
  type SchemaField,
} from "./definition";

const { Text } = Typography;

/* ------------------------------------------------------------------ */
/* Palette                                                             */
/* ------------------------------------------------------------------ */

function PaletteItem({
  descriptor,
  onAdd,
}: {
  descriptor: ComponentDescriptor;
  onAdd: (descriptor: ComponentDescriptor) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onAdd(descriptor)}
      className="flex w-full items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-left text-sm transition hover:border-primary hover:bg-primary/5"
    >
      <span className="truncate">{descriptor.label}</span>
      <PlusOutlined className="text-xs text-muted-foreground" />
    </button>
  );
}

function Palette({
  registry,
  onAdd,
}: {
  registry: ComponentDescriptor[];
  onAdd: (descriptor: ComponentDescriptor) => void;
}) {
  const { t } = useTranslation();
  const containers = registry.filter((entry) => entry.is_layout_container);
  const content = registry.filter((entry) => !entry.is_layout_container);
  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-2">
      <div>
        <Text type="secondary" className="text-xs uppercase tracking-wide">
          {t("admin.pageBuilder.layouts", { defaultValue: "Layout" })}
        </Text>
        <div className="mt-2 flex flex-col gap-2">
          {containers.map((entry) => (
            <PaletteItem key={entry.renderer_key} descriptor={entry} onAdd={onAdd} />
          ))}
        </div>
      </div>
      <div>
        <Text type="secondary" className="text-xs uppercase tracking-wide">
          {t("admin.pageBuilder.components", { defaultValue: "Components" })}
        </Text>
        <div className="mt-2 flex flex-col gap-2">
          {content.map((entry) => (
            <PaletteItem key={entry.renderer_key} descriptor={entry} onAdd={onAdd} />
          ))}
        </div>
      </div>
      <Text type="secondary" className="text-xs">
        {t("admin.pageBuilder.paletteHint", {
          defaultValue:
            "Select a container in the canvas, then click a component to place it there. Without a container selection, components are added to the page root.",
        })}
      </Text>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Canvas                                                              */
/* ------------------------------------------------------------------ */

interface CanvasProps {
  root: PageComponentNode;
  registry: ComponentDescriptor[];
  selectedPath: NodePath | null;
  onSelect: (path: NodePath) => void;
  onTreeChange: (root: PageComponentNode) => void;
  readOnly?: boolean;
}

interface NodeCardProps extends CanvasProps {
  path: NodePath;
  handleProps?: {
    attributes: DraggableAttributes;
    listeners: DraggableSyntheticListeners;
  };
}

function NodeCard({
  root,
  path,
  registry,
  selectedPath,
  onSelect,
  onTreeChange,
  handleProps,
  readOnly,
}: NodeCardProps) {
  const { t } = useTranslation();
  const node = nodeAt(root, path);
  if (!node) return null;
  const container = isLayoutContainer(node.type);
  const selected = pathEquals(path, selectedPath);
  const children = node.children ?? [];

  return (
    <div
      className={`rounded-lg border bg-card ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
      onClick={(event) => {
        event.stopPropagation();
        onSelect(path);
      }}
    >
      <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
        {handleProps ? (
          <button
            type="button"
            aria-label={t("admin.pageBuilder.dragHandle", { defaultValue: "Drag to reorder" })}
            className="cursor-grab touch-none text-muted-foreground hover:text-foreground"
            {...handleProps.attributes}
            {...handleProps.listeners}
            onClick={(event) => event.stopPropagation()}
          >
            <HolderOutlined />
          </button>
        ) : null}
        <Tag color={container ? "geekblue" : "default"}>
          {componentLabel(registry, node.type)}
        </Tag>
        <Text type="secondary" ellipsis className="min-w-0 flex-1 text-xs">
          {summarizeNode(node)}
        </Text>
        {!readOnly && container ? (
          <Tooltip title={t("admin.pageBuilder.selectContainer", { defaultValue: "Select this container, then add a component" })}>
            <Button
              size="small"
              type="text"
              icon={<PlusOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onSelect(path);
              }}
            />
          </Tooltip>
        ) : null}
        {!readOnly && path.length > 0 ? (
          <Tooltip title={t("admin.pageBuilder.remove", { defaultValue: "Remove component" })}>
            <Button
              size="small"
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onTreeChange(removeAt(root, path));
                onSelect(path.slice(0, -1));
              }}
            />
          </Tooltip>
        ) : null}
      </div>
      {container ? (
        <div className="p-2">
          {children.length === 0 ? (
            <div className="rounded-md border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
              {t("admin.pageBuilder.emptyContainer", {
                defaultValue: "Empty container — select it from the palette.",
              })}
            </div>
          ) : (
            <SortableList
              root={root}
              parentPath={path}
              registry={registry}
              selectedPath={selectedPath}
              onSelect={onSelect}
              onTreeChange={onTreeChange}
              readOnly={readOnly}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}

function SortableNode({
  id,
  ...rest
}: NodeCardProps & { id: string }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id, disabled: rest.readOnly });
  return (
    <div
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 }}
      className="mb-2 last:mb-0"
    >
      <NodeCard {...rest} handleProps={{ attributes, listeners }} />
    </div>
  );
}

function SortableList({
  root,
  parentPath,
  registry,
  selectedPath,
  onSelect,
  onTreeChange,
  readOnly,
}: CanvasProps & { parentPath: NodePath }) {
  const parent = nodeAt(root, parentPath);
  const children = parent?.children ?? [];
  const ids = children.map((_, index) => String(index));
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  const onDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const from = Number(active.id);
    const to = Number(over.id);
    if (Number.isNaN(from) || Number.isNaN(to)) return;
    onTreeChange(moveChild(root, parentPath, from, to));
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        {children.map((_, index) => (
          <SortableNode
            key={ids[index]}
            id={ids[index]}
            root={root}
            path={[...parentPath, index]}
            registry={registry}
            selectedPath={selectedPath}
            onSelect={onSelect}
            onTreeChange={onTreeChange}
            readOnly={readOnly}
          />
        ))}
      </SortableContext>
    </DndContext>
  );
}

function Canvas(props: CanvasProps) {
  if (props.readOnly) {
    return (
      <div className="overflow-auto p-3">
        <NodeCard {...props} path={[]} />
      </div>
    );
  }
  return (
    <div className="h-full overflow-auto p-3" onClick={() => undefined}>
      <NodeCard {...props} path={[]} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Inspector                                                           */
/* ------------------------------------------------------------------ */

function JsonField({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = React.useState(() => JSON.stringify(value ?? null, null, 2));
  const [error, setError] = React.useState<string | null>(null);
  const incoming = JSON.stringify(value ?? null);
  React.useEffect(() => {
    // Only re-format when the parsed local text no longer matches the prop, so
    // typing (where the parent echoes our own parsed value back) keeps the
    // cursor position instead of reformatting on every keystroke.
    let local: string | null;
    try {
      local = JSON.stringify(JSON.parse(text));
    } catch {
      local = null;
    }
    if (local === null || local === incoming) return;
    setText(JSON.stringify(value ?? null, null, 2));
    setError(null);
  }, [incoming, text, value]);
  return (
    <>
      <Input.TextArea
        value={text}
        autoSize={{ minRows: 3, maxRows: 12 }}
        spellCheck={false}
        className="font-mono text-xs"
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            const parsed: unknown = JSON.parse(next);
            setError(null);
            onChange(parsed);
          } catch (parseError) {
            setError(parseError instanceof Error ? parseError.message : String(parseError));
          }
        }}
      />
      {error ? <Text type="danger" className="text-xs">Invalid JSON: {error}</Text> : null}
    </>
  );
}

const IMAGE_FIELD_NAMES = new Set(["image", "image_url", "src", "poster", "icon_url", "logo_url", "cover_url"]);

function SchemaFieldEditor({
  field,
  value,
  onChange,
}: {
  field: SchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const kind = fieldKind(field.schema);
  if (kind === "enum") {
    return (
      <Select
        value={typeof value === "string" ? value : undefined}
        options={enumValues(field.schema).map((option) => ({ value: option, label: option }))}
        onChange={(next) => onChange(next)}
        allowClear={!field.required}
        className="w-full"
      />
    );
  }
  if (kind === "boolean") {
    return <Switch checked={value === true} onChange={(next) => onChange(next)} />;
  }
  if (kind === "number") {
    return (
      <InputNumber
        value={typeof value === "number" ? value : undefined}
        min={typeof field.schema.minimum === "number" ? field.schema.minimum : undefined}
        max={typeof field.schema.maximum === "number" ? field.schema.maximum : undefined}
        step={field.schema.type === "integer" ? 1 : undefined}
        precision={field.schema.type === "integer" ? 0 : undefined}
        onChange={(next) => onChange(next ?? undefined)}
        className="w-full"
      />
    );
  }
  if (kind === "tags") {
    return (
      <Select
        mode="tags"
        value={Array.isArray(value) ? value : []}
        onChange={(next) => onChange(next)}
        tokenSeparators={[",", " "]}
        className="w-full"
      />
    );
  }
  if (kind === "json") {
    return <JsonField value={value} onChange={onChange} />;
  }
  const multiline = field.name === "content" || field.name === "description";
  if (multiline) {
    return (
      <Input.TextArea
        value={typeof value === "string" ? value : ""}
        autoSize={{ minRows: 3, maxRows: 10 }}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  if (IMAGE_FIELD_NAMES.has(field.name)) {
    const url = typeof value === "string" ? value : "";
    return (
      <div className="space-y-2">
        <MediaPicker
          value={url || null}
          previewUrl={url || null}
          previewAlt={field.name}
          purpose={null}
          onChange={(asset) => onChange(asset?.public_url ?? "")}
        />
        <Input
          value={url}
          placeholder="https://…"
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    );
  }
  return (
    <Input
      value={typeof value === "string" ? value : ""}
      maxLength={typeof field.schema.maxLength === "number" ? field.schema.maxLength : undefined}
      placeholder={typeof field.schema.pattern === "string" ? `pattern: ${field.schema.pattern}` : undefined}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function Inspector({
  definition,
  path,
  registry,
  onChange,
}: {
  definition: PageDefinitionV2;
  path: NodePath | null;
  registry: ComponentDescriptor[];
  onChange: (next: PageDefinitionV2) => void;
}) {
  const { t } = useTranslation();
  const node = path ? nodeAt(definition.root, path) : definition.root;
  const descriptor = node ? descriptorFor(registry, node.type) : undefined;
  const fields = React.useMemo(() => (descriptor ? listFields(descriptor) : []), [descriptor]);

  const updateProp = (name: string, value: unknown) => {
    if (!node) return;
    const target = path ?? [];
    onChange({
      ...definition,
      root: updateAt(definition.root, target, (current) => ({
        ...current,
        props: { ...current.props, [name]: value },
      })),
    });
  };

  const updateDefinitionJson = (value: unknown) => {
    const normalized = normalizePageDefinition(value);
    if (normalized) onChange(normalized);
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-auto p-2">
      <ProCard size="small" title={t("admin.pageBuilder.pageSettings", { defaultValue: "Page settings" })}>
        <Form layout="vertical">
          <Form.Item label={t("admin.pageBuilder.titleKey", { defaultValue: "Title key" })}>
            <Input
              value={definition.title_key ?? ""}
              onChange={(event) =>
                onChange({
                  ...definition,
                  title_key: event.target.value || undefined,
                })
              }
            />
          </Form.Item>
          <Form.Item label={t("admin.pageBuilder.theme", { defaultValue: "Theme" })}>
            <Select
              value={definition.theme_id}
              options={PAGE_THEMES.map((theme) => ({ value: theme, label: theme }))}
              onChange={(theme) => onChange({ ...definition, theme_id: theme })}
            />
          </Form.Item>
        </Form>
      </ProCard>

      <ProCard
        size="small"
        title={
          descriptor
            ? `${t("admin.pageBuilder.properties", { defaultValue: "Properties" })} · ${descriptor.label}`
            : t("admin.pageBuilder.properties", { defaultValue: "Properties" })
        }
      >
        {!node || !descriptor ? (
          <Empty description={t("admin.pageBuilder.noSelection", { defaultValue: "Select a component" })} />
        ) : fields.length === 0 ? (
          <Text type="secondary" className="text-xs">
            {t("admin.pageBuilder.noProps", { defaultValue: "This component has no configurable props." })}
          </Text>
        ) : (
          <Form layout="vertical">
            {fields.map((field) => (
              <Form.Item
                key={field.name}
                label={
                  <Space size={4}>
                    <span>{field.name}</span>
                    {field.required ? <Text type="danger">*</Text> : null}
                  </Space>
                }
              >
                <SchemaFieldEditor
                  field={field}
                  value={node.props[field.name]}
                  onChange={(value) => updateProp(field.name, value)}
                />
              </Form.Item>
            ))}
          </Form>
        )}
      </ProCard>

      <ProCard size="small" title={t("admin.pageBuilder.documentJson", { defaultValue: "Definition JSON" })}>
        <Text type="secondary" className="text-xs">
          {t("admin.pageBuilder.documentJsonHint", {
            defaultValue:
              "Advanced: edit data sources and responsive layouts directly. The server re-validates on save.",
          })}
        </Text>
        <div className="mt-2">
          <JsonField value={definition} onChange={updateDefinitionJson} />
        </div>
      </ProCard>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function PageBuilderEditorPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams({ strict: false }) as { pageId?: string };
  const pageId = params.pageId ?? "";
  const queryClient = useQueryClient();

  const pageQuery = useQuery({
    queryKey: ["page-builder", "page", pageId],
    queryFn: () => adminPageBuilderApi.page(pageId),
    enabled: Boolean(pageId),
  });
  const registryQuery = useQuery({
    queryKey: ["page-builder", "registry"],
    queryFn: () => adminPageBuilderApi.registry(),
    staleTime: 5 * 60_000,
  });

  const [definition, setDefinition] = React.useState<PageDefinitionV2 | null>(null);
  const [baseVersion, setBaseVersion] = React.useState(0);
  const [initialized, setInitialized] = React.useState(false);
  const [dirty, setDirty] = React.useState(false);
  const [selectedPath, setSelectedPath] = React.useState<NodePath | null>([]);
  const [previewDefinition, setPreviewDefinition] = React.useState<PageDefinitionV2 | null>(null);
  const [publishOpen, setPublishOpen] = React.useState(false);
  const [publishForm] = Form.useForm<{ reason?: string }>();

  const registry = registryQuery.data?.components ?? [];
  const page = pageQuery.data;
  const latestVersion: PageDefinitionVersion | undefined = page?.versions[0];

  React.useEffect(() => {
    setInitialized(false);
    setDefinition(null);
    setBaseVersion(0);
    setDirty(false);
    setSelectedPath([]);
  }, [pageId]);

  React.useEffect(() => {
    if (initialized || !page) return;
    const source = latestVersion ? normalizePageDefinition(latestVersion.definition) : null;
    setDefinition(source ?? emptyDefinition(page.title_key));
    setBaseVersion(latestVersion?.version ?? 0);
    setInitialized(true);
  }, [initialized, page, latestVersion]);

  const setTree = (next: PageDefinitionV2) => {
    setDefinition(next);
    setDirty(true);
  };

  const handleAdd = (descriptor: ComponentDescriptor) => {
    if (!definition) return;
    const target = insertionTarget(definition.root, selectedPath);
    const parent = nodeAt(definition.root, target);
    const index = parent?.children?.length ?? 0;
    const nextRoot = appendChild(definition.root, target, nodeFromDescriptor(descriptor));
    setTree({ ...definition, root: nextRoot });
    setSelectedPath([...target, index]);
  };

  const invalidatePage = () =>
    queryClient.invalidateQueries({ queryKey: ["page-builder", "page", pageId] });

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!definition) throw new Error("Nothing to save");
      return adminPageBuilderApi.saveDraft(pageId, {
        base_version: baseVersion,
        definition,
      });
    },
    onSuccess: async (version) => {
      setBaseVersion(version.version);
      setDirty(false);
      message.success(
        t("admin.pageBuilder.draftSaved", { defaultValue: "Draft v{{version}} saved.", version: version.version }),
      );
      await invalidatePage();
      await queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : String(error));
    },
  });

  const previewMutation = useMutation({
    mutationFn: async () => {
      if (!definition) throw new Error("Nothing to preview");
      return adminPageBuilderApi.preview(pageId, definition);
    },
    onSuccess: async (result) => {
      // Preview validates the payload but persists nothing, so the editor's
      // base version and dirty flag must stay exactly as they were; adopting
      // the preview number would make the next save fail with a 409 and
      // silently mark unsaved edits as clean.
      const preview = normalizePageDefinition(result.definition);
      setPreviewDefinition(preview);
      message.success(
        t("admin.pageBuilder.previewReady", {
          defaultValue: "Preview validated. Nothing was saved.",
        }),
      );
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : String(error));
    },
  });

  const publishMutation = useMutation({
    mutationFn: async (reason?: string) => {
      if (!definition) throw new Error("Nothing to publish");
      let versionId = latestVersion?.id;
      let savedBase: number | undefined;
      if (dirty) {
        const saved = await adminPageBuilderApi.saveDraft(pageId, {
          base_version: baseVersion,
          definition,
        });
        versionId = saved.id;
        savedBase = saved.version;
      }
      const result = await adminPageBuilderApi.publish(pageId, versionId, reason);
      return { result, savedBase };
    },
    onSuccess: async ({ result, savedBase }) => {
      // Publishing from unsaved edits first writes a new draft. Adopt its
      // number as the new base, otherwise the very next save would be sent
      // with the pre-publish base and fail with a 409.
      if (savedBase !== undefined) setBaseVersion(savedBase);
      setDirty(false);
      setPublishOpen(false);
      publishForm.resetFields();
      message.success(
        t("admin.pageBuilder.published", {
          defaultValue: "Published v{{version}}.",
          version: result.version,
        }),
      );
      await invalidatePage();
      await queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : String(error));
    },
  });

  const latestStatus = latestVersion?.status ?? "none";

  if (!pageId) {
    return (
      <PageContainer>
        <Alert type="error" message={t("admin.pageBuilder.missingPageId", { defaultValue: "Missing page id" })} />
      </PageContainer>
    );
  }

  if (pageQuery.isLoading || registryQuery.isLoading || !definition) {
    return (
      <PageContainer>
        {pageQuery.error || registryQuery.error ? (
          <Alert
            type="error"
            message={t("admin.pageBuilder.loadFailed", { defaultValue: "Failed to load the page definition." })}
            description={
              pageQuery.error instanceof Error
                ? pageQuery.error.message
                : registryQuery.error instanceof Error
                  ? registryQuery.error.message
                  : undefined
            }
          />
        ) : (
          <Flex justify="center" className="py-24">
            <Spin size="large" />
          </Flex>
        )}
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title={
        <Space>
          <Button
            type="text"
            icon={<ArrowLeftOutlined />}
            onClick={() => void router.navigate({ to: "/page-builder" })}
          />
          <span>{page?.route}</span>
          <Tag>v{latestVersion?.version ?? 0}</Tag>
          <Tag color={latestStatus === "published" ? "green" : latestStatus === "requested" ? "orange" : "default"}>
            {latestStatus}
          </Tag>
          {dirty ? <Tag color="blue">{t("admin.pageBuilder.unsaved", { defaultValue: "Unsaved" })}</Tag> : null}
        </Space>
      }
      subTitle={
        latestVersion
          ? t("admin.pageBuilder.lastEdited", {
              defaultValue: "Last edited {{when}}",
              when: dayjs(latestVersion.updated_at).format("YYYY-MM-DD HH:mm"),
            })
          : undefined
      }
      extra={[
        <Button
          key="preview"
          icon={<EyeOutlined />}
          loading={previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          {t("admin.pageBuilder.preview", { defaultValue: "Preview" })}
        </Button>,
        <Button
          key="save"
          icon={<SaveOutlined />}
          loading={saveMutation.isPending}
          disabled={!dirty}
          onClick={() => saveMutation.mutate()}
        >
          {t("admin.pageBuilder.saveDraft", { defaultValue: "Save draft" })}
        </Button>,
        <Button
          key="publish"
          type="primary"
          icon={<SendOutlined />}
          // A clean page whose newest version is already published has nothing
          // left to publish; the server would reject it. Editing first creates
          // a new draft, which is publishable again.
          disabled={!dirty && latestStatus === "published"}
          onClick={() => setPublishOpen(true)}
        >
          {t("admin.pageBuilder.publish", { defaultValue: "Publish" })}
        </Button>,
      ]}
    >
      <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)_360px]">
        <ProCard
          title={t("admin.pageBuilder.palette", { defaultValue: "Components" })}
          styles={{ body: { padding: 8, height: "calc(100vh - 220px)" } }}
        >
          <Palette registry={registry} onAdd={handleAdd} />
        </ProCard>
        <ProCard
          title={t("admin.pageBuilder.canvas", { defaultValue: "Canvas" })}
          styles={{ body: { padding: 0, height: "calc(100vh - 220px)" } }}
        >
          <Canvas
            root={definition.root}
            registry={registry}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            onTreeChange={(root) => setTree({ ...definition, root })}
          />
        </ProCard>
        <ProCard styles={{ body: { padding: 0, height: "calc(100vh - 220px)" } }}>
          <Tabs
            size="small"
            items={[
              {
                key: "inspector",
                label: t("admin.pageBuilder.inspector", { defaultValue: "Inspector" }),
                children: (
                  <Inspector
                    definition={definition}
                    path={selectedPath}
                    registry={registry}
                    onChange={setTree}
                  />
                ),
              },
            ]}
          />
        </ProCard>
      </div>

      <Modal
        title={t("admin.pageBuilder.previewTitle", { defaultValue: "Preview (validated definition)" })}
        open={previewDefinition !== null}
        onCancel={() => setPreviewDefinition(null)}
        footer={<Button onClick={() => setPreviewDefinition(null)}>{t("common.close", { defaultValue: "Close" })}</Button>}
        width={900}
        destroyOnHidden
      >
        {previewDefinition ? (
          <Canvas
            root={previewDefinition.root}
            registry={registry}
            selectedPath={null}
            onSelect={() => undefined}
            onTreeChange={() => undefined}
            readOnly
          />
        ) : null}
      </Modal>

      <Modal
        title={t("admin.pageBuilder.publishTitle", { defaultValue: "Publish page definition" })}
        open={publishOpen}
        onCancel={() => setPublishOpen(false)}
        onOk={() => {
          const reason = publishForm.getFieldValue("reason") as string | undefined;
          publishMutation.mutate(reason);
        }}
        confirmLoading={publishMutation.isPending}
        okText={t("admin.pageBuilder.publish", { defaultValue: "Publish" })}
      >
        <Alert
          type="info"
          showIcon
          className="mb-4"
          message={
            dirty
              ? t("admin.pageBuilder.publishSavesFirst", {
                  defaultValue: "Unsaved changes will be saved as a new draft, then published.",
                })
              : t("admin.pageBuilder.publishHint", {
                  defaultValue: "The public site serves the newest published version immediately.",
                })
          }
        />
        <Form form={publishForm} layout="vertical">
          <Form.Item name="reason" label={t("admin.pageBuilder.publishReason", { defaultValue: "Reason (optional)" })}>
            <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} />
          </Form.Item>
        </Form>
      </Modal>

      {nodeAt(definition.root, []) && definition.root.type === "columns" && (definition.root.children?.length ?? 0) === 0 ? (
        <Alert
          className="mt-4"
          type="info"
          showIcon
          message={t("admin.pageBuilder.getStarted", {
            defaultValue:
              "Start by selecting a component from the palette. The root is a columns container, so any component may be placed directly.",
          })}
        />
      ) : null}
    </PageContainer>
  );
}