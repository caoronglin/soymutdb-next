/**
 * The primary-navigation editor for one explicit site variant.
 *
 * It is a component rather than part of a route because two pages mount it: the
 * site-appearance page (the one entry in the console sidebar) and the legacy
 * `/site-control` page that deep links still resolve to. Both must speak to the
 * same versioned settings document, so there is exactly one implementation.
 */
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { DeleteOutlined, HolderOutlined, PlusOutlined, SaveOutlined } from "@ant-design/icons";
import {
  adminSettingsApi,
  ApiError,
  capabilitiesApi,
  getSiteNavigation,
  type AdminFeaturesResponse,
  type SiteVariant,
} from "@soymutdb/api-client";
import {
  HEADER_NAVIGATION_SCHEMA_VERSION,
  MAX_HEADER_GROUPS,
  MAX_HEADER_LINKS,
  countHeaderLinks,
  isHeaderSlug,
  parseHeaderNavigationJson,
  serializeHeaderNavigation,
  type HeaderNavDocument,
  type HeaderNavGroup,
  type HeaderNavLink,
} from "@soymutdb/shared";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Flex,
  Input,
  ProCard,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
} from "@/lib/antd";
import { useTranslation } from "react-i18next";

const EMPTY_DOCUMENT: HeaderNavDocument = {
  schema_version: HEADER_NAVIGATION_SCHEMA_VERSION,
  groups: [],
};

/** Common first-party destinations offered as suggestions, not a whitelist. */
const DESTINATION_PRESETS = [
  "/search/genes",
  "/search/location",
  "/search/gbrowse",
  "/blast",
  "/genes",
  "/variants",
  "/mutants",
  "/browser",
  "/compare",
  "/analyses",
  "/tools",
  "/tools/enrichment",
  "/downloads",
  "/news",
  "/guide",
  "/help",
  "/about",
];

/**
 * The API requires the `target` discriminator to agree with the href shape:
 * origin-relative paths are internal, HTTPS URLs are external. The editor
 * derives it so an admin editing a destination cannot produce a document the
 * server rejects.
 */
function destinationTarget(href: string): HeaderNavLink["target"] {
  return href.startsWith("https://") ? "external" : "internal";
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

function destinationError(link: HeaderNavLink, t: Translate): string | null {
  const href = link.href;
  if (!href) return t("admin.siteControl.nav.error.noDestination", { label: link.label_en });
  if (href !== href.trim() || /\s/.test(href) || href.includes("\\")) {
    return t("admin.siteControl.nav.error.whitespace", { label: link.label_en });
  }
  if (href.startsWith("//")) {
    return t("admin.siteControl.nav.error.protocolRelative", { label: link.label_en });
  }
  if (!href.startsWith("/") && !href.startsWith("https://")) {
    return t("admin.siteControl.nav.error.prefix", { label: link.label_en });
  }
  return null;
}

function newId(prefix: string): string {
  let attempt = Math.random().toString(36).slice(2, 8);
  if (!/^[a-z0-9]+$/.test(attempt)) attempt = "item";
  return `${prefix}-${attempt}`;
}

function emptyLink(order: number): HeaderNavLink {
  return {
    id: newId("link"),
    label_en: "New link",
    label_zh: "新链接",
    target: "internal",
    href: "/",
    enabled: true,
    order,
    feature: null,
  };
}

function emptyGroup(order: number): HeaderNavGroup {
  return {
    id: newId("group"),
    title_en: "New group",
    title_zh: "新分组",
    enabled: true,
    order,
    links: [emptyLink(0)],
  };
}

function SortableGroupCard({
  group,
  index,
  featureKeys,
  onChange,
  onRemove,
  canRemove,
}: {
  group: HeaderNavGroup;
  index: number;
  featureKeys: string[];
  onChange: (next: HeaderNavGroup) => void;
  onRemove: () => void;
  canRemove: boolean;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: group.id });
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  const updateLink = (linkIndex: number, patch: Partial<HeaderNavLink>) => {
    onChange({
      ...group,
      links: group.links.map((link, i) => (i === linkIndex ? { ...link, ...patch } : link)),
    });
  };

  const handleLinkDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = group.links.findIndex((link) => link.id === active.id);
    const newIndex = group.links.findIndex((link) => link.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    onChange({
      ...group,
      links: arrayMove(group.links, oldIndex, newIndex).map((link, i) => ({
        ...link,
        order: i,
      })),
    });
  };

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.7 : 1,
      }}
    >
      <ProCard
        title={
          <Space>
            <span
              {...attributes}
              {...listeners}
              className="cursor-grab touch-none text-muted-foreground"
              aria-label={t("admin.siteControl.nav.reorderGroup", { name: group.title_en })}
            >
              <HolderOutlined />
            </span>
            <Input
              aria-label={t("admin.siteControl.nav.groupEnTitleAria", { index: index + 1 })}
              value={group.title_en}
              maxLength={80}
              onChange={(event) => onChange({ ...group, title_en: event.target.value })}
              style={{ width: 200 }}
            />
            <Input
              aria-label={t("admin.siteControl.nav.groupZhTitleAria", { index: index + 1 })}
              value={group.title_zh}
              maxLength={80}
              onChange={(event) => onChange({ ...group, title_zh: event.target.value })}
              style={{ width: 160 }}
            />
            <Tag>{t("admin.siteControl.nav.linkCount", { count: group.links.length })}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Switch
              checked={group.enabled}
              onChange={(enabled) => onChange({ ...group, enabled })}
              checkedChildren={t("admin.siteControl.nav.on")}
              unCheckedChildren={t("admin.siteControl.nav.off")}
            />
            <Button
              danger
              size="small"
              icon={<DeleteOutlined />}
              disabled={!canRemove}
              onClick={onRemove}
            />
          </Space>
        }
      >
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleLinkDragEnd}
        >
          <SortableContext
            items={group.links.map((link) => link.id)}
            strategy={verticalListSortingStrategy}
          >
            <Flex vertical gap={8}>
              {group.links.map((link, linkIndex) => (
                <SortableLinkRow
                  key={link.id}
                  link={link}
                  groupId={group.id}
                  index={linkIndex}
                  featureKeys={featureKeys}
                  onChange={(patch) => updateLink(linkIndex, patch)}
                  onRemove={() =>
                    onChange({
                      ...group,
                      links: group.links.filter((_, i) => i !== linkIndex),
                    })
                  }
                />
              ))}
            </Flex>
          </SortableContext>
        </DndContext>
        <Button
          type="dashed"
          block
          icon={<PlusOutlined />}
          className="mt-3"
          disabled={group.links.length >= MAX_HEADER_LINKS}
          onClick={() => onChange({ ...group, links: [...group.links, emptyLink(group.links.length)] })}
        >
          {t("admin.siteControl.nav.addLink")}
        </Button>
      </ProCard>
    </div>
  );
}

function SortableLinkRow({
  link,
  groupId,
  index,
  featureKeys,
  onChange,
  onRemove,
}: {
  link: HeaderNavLink;
  groupId: string;
  index: number;
  featureKeys: string[];
  onChange: (patch: Partial<HeaderNavLink>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: link.id,
  });
  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
      className="grid grid-cols-12 items-center gap-2 rounded-md border border-border px-2 py-1"
    >
      <span
        {...attributes}
        {...listeners}
        className="col-span-1 cursor-grab touch-none text-muted-foreground"
        aria-label={t("admin.siteControl.nav.reorderLink", { name: link.label_en })}
      >
        <HolderOutlined />
      </span>
      <Input
        className="col-span-2"
        aria-label={t("admin.siteControl.nav.linkEnLabelAria", { index: index + 1, group: groupId })}
        value={link.label_en}
        maxLength={80}
        onChange={(event) => onChange({ label_en: event.target.value })}
      />
      <Input
        className="col-span-2"
        aria-label={t("admin.siteControl.nav.linkZhLabelAria", { index: index + 1, group: groupId })}
        value={link.label_zh}
        maxLength={80}
        onChange={(event) => onChange({ label_zh: event.target.value })}
      />
      <AutoComplete
        className="col-span-3"
        aria-label={t("admin.siteControl.nav.linkDestinationAria", { index: index + 1, group: groupId })}
        value={link.href}
        placeholder={t("admin.siteControl.nav.destinationPlaceholder")}
        options={(DESTINATION_PRESETS.includes(link.href)
          ? DESTINATION_PRESETS
          : [link.href, ...DESTINATION_PRESETS]
        ).map((value) => ({ value }))}
        filterOption={(input, option) =>
          String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
        }
        onChange={(value) => {
          const href = String(value ?? "");
          onChange({ href, target: destinationTarget(href) });
        }}
        onBlur={() => {
          // The server rejects leading/trailing whitespace; trim when the
          // field loses focus rather than while the admin is still typing.
          const trimmed = link.href.trim();
          if (trimmed !== link.href) {
            onChange({ href: trimmed, target: destinationTarget(trimmed) });
          }
        }}
      />
      <Select
        className="col-span-2"
        aria-label={t("admin.siteControl.nav.linkGateAria", { index: index + 1, group: groupId })}
        allowClear
        placeholder={t("admin.siteControl.nav.noGate")}
        value={link.feature ?? undefined}
        options={featureKeys.map((key) => ({ value: key, label: key }))}
        onChange={(feature) => onChange({ feature: feature ?? null })}
      />
      <Switch
        aria-label={t("admin.siteControl.nav.linkEnabledAria", { index: index + 1, group: groupId })}
        size="small"
        checked={link.enabled}
        onChange={(enabled) => onChange({ enabled })}
      />
      <Button type="text" danger size="small" icon={<DeleteOutlined />} onClick={onRemove} />
    </div>
  );
}

export function VariantNavigationEditor({ variant }: { variant: SiteVariant }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const section = `header_${variant}`;
  const settings = useQuery({
    queryKey: ["admin-settings", section],
    queryFn: () => adminSettingsApi.get(section),
  });
  const features = useQuery({
    queryKey: ["admin-features"],
    queryFn: () => capabilitiesApi.adminGet(),
  });
  const seed = useQuery({
    queryKey: ["site-navigation", variant],
    queryFn: () => getSiteNavigation(variant),
    enabled: settings.isSuccess,
  });
  const [document, setDocument] = React.useState<HeaderNavDocument>(EMPTY_DOCUMENT);
  const [dirty, setDirty] = React.useState(false);
  const [baseVersion, setBaseVersion] = React.useState<number | null>(null);
  const initialized = React.useRef(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  // Track the server version independently of the document so a stale-version
  // 409 can recover by refetching without discarding the admin's unsaved edits.
  React.useEffect(() => {
    if (settings.data) setBaseVersion(settings.data.version);
  }, [settings.data]);

  React.useEffect(() => {
    if (!settings.data || initialized.current) return;
    const stored = settings.data.values.navigation_json;
    const parsed = parseHeaderNavigationJson(typeof stored === "string" ? stored : null);
    if (parsed) {
      setDocument(parsed);
      setDirty(false);
      initialized.current = true;
      return;
    }
    if (seed.data) {
      setDocument({
        schema_version: HEADER_NAVIGATION_SCHEMA_VERSION,
        groups: seed.data.groups.map((group, groupIndex) => ({
          id: group.id,
          title_en: group.title_en,
          title_zh: group.title_zh,
          enabled: group.enabled,
          order: group.order ?? groupIndex,
          links: group.links.map((link, linkIndex) => ({
            id: link.id,
            label_en: link.label_en,
            label_zh: link.label_zh,
            target: link.target,
            href: link.href,
            enabled: link.enabled,
            order: link.order ?? linkIndex,
            feature: link.feature ?? null,
          })),
        })),
      });
      setDirty(false);
      initialized.current = true;
    }
  }, [settings.data, seed.data]);

  const save = useMutation({
    mutationFn: () => {
      if (!settings.data || baseVersion === null) throw new Error(t("admin.siteControl.nav.error.notLoaded"));
      const total = countHeaderLinks(document);
      if (document.groups.length > MAX_HEADER_GROUPS) throw new Error(t("admin.siteControl.nav.error.tooManyGroups"));
      if (total > MAX_HEADER_LINKS) throw new Error(t("admin.siteControl.nav.error.tooManyLinks"));
      for (const group of document.groups) {
        if (!isHeaderSlug(group.id)) throw new Error(t("admin.siteControl.nav.error.invalidGroupId", { id: group.id }));
        for (const link of group.links) {
          if (!isHeaderSlug(link.id)) throw new Error(t("admin.siteControl.nav.error.invalidLinkId", { id: link.id }));
          const error = destinationError(link, t);
          // Throwing a string would collapse into the generic "Save failed"
          // branch below; wrap it so the admin sees the actual reason.
          if (error) throw new Error(error);
        }
      }
      return adminSettingsApi.patch(section, baseVersion, {
        navigation_json: serializeHeaderNavigation(document),
      });
    },
    onSuccess: (updated) => {
      setBaseVersion(updated.version);
      setDirty(false);
      message.success(t("admin.siteControl.nav.saved", { variant: t(`admin.siteControl.${variant}`) }));
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", section] });
      void queryClient.invalidateQueries({ queryKey: ["site-navigation"] });
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        message.warning(t("admin.siteControl.nav.conflict"));
        void queryClient.invalidateQueries({ queryKey: ["admin-settings", section] });
        return;
      }
      message.error(error instanceof Error ? error.message : t("admin.siteControl.saveFailed"));
    },
  });

  const handleGroupDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = document.groups.findIndex((group) => group.id === active.id);
    const newIndex = document.groups.findIndex((group) => group.id === over.id);
    if (oldIndex < 0 || newIndex < 0) return;
    setDocument({
      ...document,
      groups: arrayMove(document.groups, oldIndex, newIndex).map((group, i) => ({
        ...group,
        order: i,
      })),
    });
    setDirty(true);
  };

  if (settings.isError) {
    return <Alert type="error" message={t("admin.siteControl.nav.loadError")} />;
  }

  const featureKeys = (features.data as AdminFeaturesResponse | undefined)?.features.map(
    (feature) => feature.key,
  ) ?? [];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        message={t("admin.siteControl.nav.dragHint")}
      />
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleGroupDragEnd}
      >
        <SortableContext
          items={document.groups.map((group) => group.id)}
          strategy={verticalListSortingStrategy}
        >
          <Flex vertical gap={12}>
            {document.groups.map((group, index) => (
              <SortableGroupCard
                key={group.id}
                group={group}
                index={index}
                featureKeys={featureKeys}
                canRemove={document.groups.length > 1}
                onChange={(next) => {
                  setDocument({
                    ...document,
                    groups: document.groups.map((entry, i) => (i === index ? next : entry)),
                  });
                  setDirty(true);
                }}
                onRemove={() => {
                  setDocument({
                    ...document,
                    groups: document.groups.filter((_, i) => i !== index),
                  });
                  setDirty(true);
                }}
              />
            ))}
          </Flex>
        </SortableContext>
      </DndContext>
      <Space>
        <Button
          icon={<PlusOutlined />}
          disabled={document.groups.length >= MAX_HEADER_GROUPS}
          onClick={() => {
            setDocument({
              ...document,
              groups: [...document.groups, emptyGroup(document.groups.length)],
            });
            setDirty(true);
          }}
        >
          {t("admin.siteControl.nav.addGroup")}
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={save.isPending}
          disabled={!dirty || settings.isLoading || baseVersion === null}
          onClick={() => save.mutate()}
        >
          {t("admin.siteControl.nav.save", { variant: t(`admin.siteControl.${variant}`) })}
        </Button>
        <Typography.Text type="secondary">
          {t("admin.siteControl.nav.linksUsed", {
            count: countHeaderLinks(document),
            max: MAX_HEADER_LINKS,
          })}
        </Typography.Text>
      </Space>
      <Typography.Text type="secondary">
        {t("admin.siteControl.navHint", {
          defaultValue:
            "Internal and external sites keep separate navigation documents; the API never copies one variant into the other.",
        })}
      </Typography.Text>
    </Space>
  );
}

