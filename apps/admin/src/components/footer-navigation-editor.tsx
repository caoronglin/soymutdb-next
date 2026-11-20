/**
 * Footer editor for one explicit site variant.
 *
 * The footer is already database-backed (`apps/api/app/core/footer_content.py`
 * owns the JSON shape and `GET /site/footer` serves it); until now it had no
 * admin surface at all. This editor reads and writes the same registered
 * settings document that endpoint reads (`footer_external` / `footer_internal`),
 * so there is no second footer contract to keep in sync:
 *
 *   * `navigation_json` — the bounded grouped-link document
 *   * `copyright_en` / `copyright_zh` — the copyright line per language
 *
 * The legacy single-language `copyright` key stays server-owned: it is only the
 * fallback the public site renders when a language-specific line is empty, so it
 * is shown here as the input placeholder instead of being editable twice.
 */
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
} from "@ant-design/icons";
import {
  adminSettingsApi,
  ApiError,
  type SettingValue,
  type SiteVariant,
} from "@soymutdb/api-client";
import {
  FOOTER_NAVIGATION_SCHEMA_VERSION,
  MAX_FOOTER_DESTINATION_LENGTH,
  MAX_FOOTER_GROUPS,
  MAX_FOOTER_LABEL_LENGTH,
  MAX_FOOTER_LINKS,
  countFooterLinks,
  isFooterSlug,
  parseFooterNavigationJson,
  serializeFooterNavigation,
  type FooterNavDocument,
  type FooterNavGroup,
  type FooterNavLink,
} from "@soymutdb/shared";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Flex,
  Input,
  ProCard,
  Space,
  Switch,
  Tag,
  Typography,
} from "@/lib/antd";
import { useTranslation } from "react-i18next";

const EMPTY_DOCUMENT: FooterNavDocument = {
  schema_version: FOOTER_NAVIGATION_SCHEMA_VERSION,
  groups: [],
};

/** Common first-party destinations offered as suggestions, not a whitelist. */
const DESTINATION_PRESETS = [
  "/genes",
  "/variants",
  "/mutants",
  "/browser",
  "/downloads",
  "/news",
  "/guide",
  "/help",
  "/about",
  "/seed-request",
];

type Translate = (key: string, options?: Record<string, unknown>) => string;

function destinationTarget(href: string): FooterNavLink["target"] {
  return href.startsWith("https://") ? "external" : "internal";
}

/**
 * Mirror of the server's destination rules so a rejected save is explained
 * before the round-trip instead of after it.
 */
function destinationError(link: FooterNavLink, t: Translate): string | null {
  const href = link.href;
  if (!href) return t("admin.siteAppearance.footer.error.noDestination", { label: link.label_en });
  if (href !== href.trim() || /\s/.test(href) || href.includes("\\")) {
    return t("admin.siteAppearance.footer.error.whitespace", { label: link.label_en });
  }
  if (href.startsWith("//")) {
    return t("admin.siteAppearance.footer.error.protocolRelative", { label: link.label_en });
  }
  if (link.target === "internal" && !href.startsWith("/")) {
    return t("admin.siteAppearance.footer.error.prefix", { label: link.label_en });
  }
  if (link.target === "external" && !href.startsWith("https://")) {
    return t("admin.siteAppearance.footer.error.httpsOnly", { label: link.label_en });
  }
  return null;
}

function newId(prefix: string): string {
  let attempt = Math.random().toString(36).slice(2, 8);
  if (!/^[a-z0-9]+$/.test(attempt)) attempt = "item";
  return `${prefix}-${attempt}`;
}

function emptyLink(order: number): FooterNavLink {
  return {
    id: newId("link"),
    label_en: "New link",
    label_zh: "新链接",
    target: "internal",
    href: "/",
    enabled: true,
    order,
  };
}

function emptyGroup(order: number): FooterNavGroup {
  return {
    id: newId("group"),
    title_en: "New group",
    title_zh: "新分组",
    enabled: true,
    order,
    links: [],
  };
}

/** Move one entry by `delta`, returning the same array when the move is a no-op. */
function moveEntry<T>(entries: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= entries.length) return entries;
  const next = [...entries];
  const [entry] = next.splice(index, 1);
  next.splice(target, 0, entry);
  return next;
}

function stringValue(value: SettingValue | undefined): string {
  return typeof value === "string" ? value : "";
}

export function FooterNavigationEditor({ variant }: { variant: SiteVariant }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { message } = App.useApp();
  const section = `footer_${variant}`;
  const settings = useQuery({
    queryKey: ["admin-settings", section],
    queryFn: () => adminSettingsApi.get(section),
  });
  const [document, setDocument] = React.useState<FooterNavDocument>(EMPTY_DOCUMENT);
  const [copyrightEn, setCopyrightEn] = React.useState("");
  const [copyrightZh, setCopyrightZh] = React.useState("");
  const [dirty, setDirty] = React.useState(false);
  const [baseVersion, setBaseVersion] = React.useState<number | null>(null);
  const initialized = React.useRef(false);

  React.useEffect(() => {
    if (settings.data) setBaseVersion(settings.data.version);
  }, [settings.data]);

  React.useEffect(() => {
    if (!settings.data || initialized.current) return;
    const values = settings.data.values;
    setDocument(parseFooterNavigationJson(stringValue(values.navigation_json)) ?? EMPTY_DOCUMENT);
    setCopyrightEn(stringValue(values.copyright_en));
    setCopyrightZh(stringValue(values.copyright_zh));
    setDirty(false);
    initialized.current = true;
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () => {
      if (baseVersion === null) {
        throw new Error(t("admin.siteAppearance.footer.error.notLoaded"));
      }
      if (document.groups.length > MAX_FOOTER_GROUPS) {
        throw new Error(
          t("admin.siteAppearance.footer.error.tooManyGroups", { max: MAX_FOOTER_GROUPS }),
        );
      }
      if (countFooterLinks(document) > MAX_FOOTER_LINKS) {
        throw new Error(
          t("admin.siteAppearance.footer.error.tooManyLinks", { max: MAX_FOOTER_LINKS }),
        );
      }
      const groupIds = new Set<string>();
      for (const group of document.groups) {
        if (!isFooterSlug(group.id)) {
          throw new Error(t("admin.siteAppearance.footer.error.invalidGroupId", { id: group.id }));
        }
        if (groupIds.has(group.id)) {
          throw new Error(t("admin.siteAppearance.footer.error.duplicateGroupId", { id: group.id }));
        }
        groupIds.add(group.id);
        for (const link of group.links) {
          if (!isFooterSlug(link.id)) {
            throw new Error(t("admin.siteAppearance.footer.error.invalidLinkId", { id: link.id }));
          }
          if (!link.label_en.trim() || !link.label_zh.trim()) {
            throw new Error(
              t("admin.siteAppearance.footer.error.blankLabel", { group: group.title_en }),
            );
          }
          const error = destinationError(link, t);
          if (error) throw new Error(error);
        }
      }
      return adminSettingsApi.patch(section, baseVersion, {
        navigation_json: serializeFooterNavigation(document),
        copyright_en: copyrightEn,
        copyright_zh: copyrightZh,
      });
    },
    onSuccess: (updated) => {
      setBaseVersion(updated.version);
      setDirty(false);
      message.success(t("admin.siteAppearance.footer.saved"));
      void queryClient.invalidateQueries({ queryKey: ["admin-settings", section] });
      void queryClient.invalidateQueries({ queryKey: ["site-footer"] });
    },
    onError: (error: unknown) => {
      if (error instanceof ApiError && error.status === 409) {
        message.warning(t("admin.siteAppearance.footer.conflict"));
        void queryClient.invalidateQueries({ queryKey: ["admin-settings", section] });
        return;
      }
      message.error(error instanceof Error ? error.message : t("admin.siteControl.saveFailed"));
    },
  });

  const updateGroup = (index: number, patch: Partial<FooterNavGroup>) => {
    setDocument({
      ...document,
      groups: document.groups.map((group, i) => (i === index ? { ...group, ...patch } : group)),
    });
    setDirty(true);
  };

  const updateLink = (groupIndex: number, linkIndex: number, patch: Partial<FooterNavLink>) => {
    const group = document.groups[groupIndex];
    updateGroup(groupIndex, {
      links: group.links.map((link, i) => (i === linkIndex ? { ...link, ...patch } : link)),
    });
  };

  if (settings.isError) {
    return (
      <Alert
        type="error"
        showIcon
        data-testid={`footer-${variant}-load-error`}
        title={t("admin.siteAppearance.footer.loadError")}
      />
    );
  }

  const legacyCopyright = stringValue(settings.data?.values.copyright);
  const linkCount = countFooterLinks(document);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {document.groups.length === 0 && !settings.isLoading ? (
        <Alert type="info" showIcon title={t("admin.siteAppearance.footer.empty")} />
      ) : null}
      {document.groups.map((group, groupIndex) => (
        <ProCard
          key={group.id}
          title={
            <Space>
              <Input
                aria-label={t("admin.siteAppearance.footer.groupEnTitleAria", {
                  index: groupIndex + 1,
                })}
                value={group.title_en}
                maxLength={MAX_FOOTER_LABEL_LENGTH}
                onChange={(event) => updateGroup(groupIndex, { title_en: event.target.value })}
                style={{ width: 180 }}
              />
              <Input
                aria-label={t("admin.siteAppearance.footer.groupZhTitleAria", {
                  index: groupIndex + 1,
                })}
                value={group.title_zh}
                maxLength={MAX_FOOTER_LABEL_LENGTH}
                onChange={(event) => updateGroup(groupIndex, { title_zh: event.target.value })}
                style={{ width: 150 }}
              />
              <Tag>{t("admin.siteAppearance.footer.linkCount", { count: group.links.length })}</Tag>
            </Space>
          }
          extra={
            <Space>
              <Switch
                aria-label={t("admin.siteAppearance.footer.groupEnabledAria", {
                  name: group.title_en,
                })}
                checked={group.enabled}
                onChange={(enabled) => updateGroup(groupIndex, { enabled })}
                checkedChildren={t("admin.siteAppearance.footer.on")}
                unCheckedChildren={t("admin.siteAppearance.footer.off")}
              />
              <Button
                size="small"
                icon={<ArrowUpOutlined />}
                aria-label={t("admin.siteAppearance.footer.moveGroupUpAria", {
                  name: group.title_en,
                })}
                disabled={groupIndex === 0}
                onClick={() =>
                  setDocument({ ...document, groups: moveEntry(document.groups, groupIndex, -1) })
                }
              />
              <Button
                size="small"
                icon={<ArrowDownOutlined />}
                aria-label={t("admin.siteAppearance.footer.moveGroupDownAria", {
                  name: group.title_en,
                })}
                disabled={groupIndex === document.groups.length - 1}
                onClick={() =>
                  setDocument({ ...document, groups: moveEntry(document.groups, groupIndex, 1) })
                }
              />
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                aria-label={t("admin.siteAppearance.footer.removeGroupAria", {
                  name: group.title_en,
                })}
                onClick={() => {
                  setDocument({
                    ...document,
                    groups: document.groups.filter((_, i) => i !== groupIndex),
                  });
                  setDirty(true);
                }}
              />
            </Space>
          }
        >
          <Flex vertical gap={8}>
            {group.links.map((link, linkIndex) => (
              <div
                key={link.id}
                className="grid grid-cols-12 items-center gap-2 rounded-md border border-border px-2 py-1"
              >
                <Input
                  className="col-span-2"
                  aria-label={t("admin.siteAppearance.footer.linkEnLabelAria", {
                    index: linkIndex + 1,
                    group: group.title_en,
                  })}
                  value={link.label_en}
                  maxLength={MAX_FOOTER_LABEL_LENGTH}
                  onChange={(event) =>
                    updateLink(groupIndex, linkIndex, { label_en: event.target.value })
                  }
                />
                <Input
                  className="col-span-2"
                  aria-label={t("admin.siteAppearance.footer.linkZhLabelAria", {
                    index: linkIndex + 1,
                    group: group.title_en,
                  })}
                  value={link.label_zh}
                  maxLength={MAX_FOOTER_LABEL_LENGTH}
                  onChange={(event) =>
                    updateLink(groupIndex, linkIndex, { label_zh: event.target.value })
                  }
                />
                <AutoComplete
                  className="col-span-5"
                  aria-label={t("admin.siteAppearance.footer.linkDestinationAria", {
                    index: linkIndex + 1,
                    group: group.title_en,
                  })}
                  value={link.href}
                  maxLength={MAX_FOOTER_DESTINATION_LENGTH}
                  placeholder={t("admin.siteAppearance.footer.destinationPlaceholder")}
                  options={(DESTINATION_PRESETS.includes(link.href)
                    ? DESTINATION_PRESETS
                    : [link.href, ...DESTINATION_PRESETS]
                  ).map((value) => ({ value }))}
                  filterOption={(input, option) =>
                    String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                  }
                  onChange={(value) => {
                    const href = String(value ?? "");
                    updateLink(groupIndex, linkIndex, { href, target: destinationTarget(href) });
                  }}
                  onBlur={() => {
                    const trimmed = link.href.trim();
                    if (trimmed !== link.href) {
                      updateLink(groupIndex, linkIndex, {
                        href: trimmed,
                        target: destinationTarget(trimmed),
                      });
                    }
                  }}
                />
                <Switch
                  className="col-span-1"
                  aria-label={t("admin.siteAppearance.footer.linkEnabledAria", {
                    label: link.label_en,
                  })}
                  size="small"
                  checked={link.enabled}
                  onChange={(enabled) => updateLink(groupIndex, linkIndex, { enabled })}
                />
                <Space className="col-span-2" size={2}>
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowUpOutlined />}
                    aria-label={t("admin.siteAppearance.footer.moveLinkUpAria", {
                      label: link.label_en,
                    })}
                    disabled={linkIndex === 0}
                    onClick={() =>
                      updateGroup(groupIndex, {
                        links: moveEntry(group.links, linkIndex, -1),
                      })
                    }
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<ArrowDownOutlined />}
                    aria-label={t("admin.siteAppearance.footer.moveLinkDownAria", {
                      label: link.label_en,
                    })}
                    disabled={linkIndex === group.links.length - 1}
                    onClick={() =>
                      updateGroup(groupIndex, {
                        links: moveEntry(group.links, linkIndex, 1),
                      })
                    }
                  />
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    aria-label={t("admin.siteAppearance.footer.removeLinkAria", {
                      label: link.label_en,
                    })}
                    onClick={() =>
                      updateGroup(groupIndex, {
                        links: group.links.filter((_, i) => i !== linkIndex),
                      })
                    }
                  />
                </Space>
              </div>
            ))}
          </Flex>
          <Button
            type="dashed"
            block
            icon={<PlusOutlined />}
            className="mt-3"
            disabled={linkCount >= MAX_FOOTER_LINKS}
            onClick={() =>
              updateGroup(groupIndex, { links: [...group.links, emptyLink(group.links.length)] })
            }
          >
            {t("admin.siteAppearance.footer.addLink")}
          </Button>
        </ProCard>
      ))}
      <Flex vertical gap={6}>
        <Typography.Text type="secondary">
          {t("admin.siteAppearance.footer.copyrightZh")}
        </Typography.Text>
        <Input
          aria-label={t("admin.siteAppearance.footer.copyrightZh")}
          placeholder={legacyCopyright}
          value={copyrightZh}
          onChange={(event) => {
            setCopyrightZh(event.target.value);
            setDirty(true);
          }}
        />
        <Typography.Text type="secondary">
          {t("admin.siteAppearance.footer.copyrightEn")}
        </Typography.Text>
        <Input
          aria-label={t("admin.siteAppearance.footer.copyrightEn")}
          placeholder={legacyCopyright}
          value={copyrightEn}
          onChange={(event) => {
            setCopyrightEn(event.target.value);
            setDirty(true);
          }}
        />
        <Typography.Text type="secondary" className="text-xs">
          {t("admin.siteAppearance.footer.copyrightHelp")}
        </Typography.Text>
      </Flex>
      <Space>
        <Button
          icon={<PlusOutlined />}
          disabled={document.groups.length >= MAX_FOOTER_GROUPS}
          onClick={() => {
            setDocument({
              ...document,
              groups: [...document.groups, emptyGroup(document.groups.length)],
            });
            setDirty(true);
          }}
        >
          {t("admin.siteAppearance.footer.addGroup")}
        </Button>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          loading={save.isPending}
          disabled={!dirty || settings.isLoading || baseVersion === null}
          onClick={() => save.mutate()}
        >
          {t("admin.siteAppearance.footer.save")}
        </Button>
        <Typography.Text type="secondary">
          {t("admin.siteAppearance.footer.linksUsed", {
            count: linkCount,
            max: MAX_FOOTER_LINKS,
          })}
        </Typography.Text>
      </Space>
    </Space>
  );
}