/**
 * Admin table-view templates — configure the columns every portal table renders.
 *
 * One screen answers three operator needs from the product requirement:
 *
 * 1. choose which columns a table shows and in which order (the default hides
 *    the cross-assembly homolog columns; an operator adds them explicitly);
 * 2. save that layout as a named template, scoped by species, site variant and
 *    optionally release, and promote it to the default;
 * 3. register the deployed species databases so one console can point at more
 *    than one server.
 *
 * The list is the source of truth the public `/table-views/{kind}` endpoint
 * resolves; every mutation here is immediately visible on the portal.
 */
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Empty,
  Form,
  Input,
  PageContainer,
  ProCard,
  ProTable,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  type ProColumns,
} from "@/lib/antd";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import { PlusOutlined, SaveOutlined, DeleteOutlined, StarOutlined } from "@ant-design/icons";
import {
  TABLE_KINDS,
  createSpeciesInstance,
  createTableViewTemplate,
  deleteSpeciesInstance,
  deleteTableViewTemplate,
  listSpeciesInstances,
  listTableViewTemplates,
  updateSpeciesInstance,
  updateTableViewTemplate,
  type SpeciesInstance,
  type TableColumn,
  type TableKind,
  type TableViewTemplate,
} from "@soymutdb/api-client";

// Labels are i18n keys, not display text. A single `X / Y` string per label
// made the console read as two languages at once and never matched the active
// locale; each key now resolves to exactly the locale's own wording.
const KIND_LABEL_KEYS: Record<TableKind, string> = {
  mutation_sites: "admin.tableViews.kind.mutation_sites",
  variants: "admin.tableViews.kind.variants",
  genes: "admin.tableViews.kind.genes",
  mutant_lines: "admin.tableViews.kind.mutant_lines",
};

/** Candidate columns an operator can add; ``homolog:*`` is the opt-in family. */
const KNOWN_COLUMN_KEYS: Record<TableKind, Array<{ key: string; labelKey: string }>> = {
  mutation_sites: [
    { key: "mutant_line_name", labelKey: "admin.tableViews.column.mutant_line_name" },
    { key: "mutation_system", labelKey: "admin.tableViews.column.mutation_system" },
    { key: "chromosome", labelKey: "admin.tableViews.column.chromosome" },
    { key: "position", labelKey: "admin.tableViews.column.position" },
    { key: "confidence", labelKey: "admin.tableViews.column.confidence" },
    { key: "gene_id", labelKey: "admin.tableViews.column.gene_id" },
    { key: "feature", labelKey: "admin.tableViews.column.feature" },
    { key: "available", labelKey: "admin.tableViews.column.available" },
    // i18next reads `:` as a namespace separator, so the homolog family uses an
    // underscore here and the component maps the key back.
    { key: "homolog:W82_V2", labelKey: "admin.tableViews.column.homolog_W82_V2" },
    { key: "homolog:W82_V4", labelKey: "admin.tableViews.column.homolog_W82_V4" },
    { key: "homolog:DN53_V1", labelKey: "admin.tableViews.column.homolog_DN53_V1" },
  ],
  variants: [
    { key: "variant_id", labelKey: "admin.tableViews.column.variant_id" },
    { key: "chromosome", labelKey: "admin.tableViews.column.chromosome" },
    { key: "position", labelKey: "admin.tableViews.column.position" },
    { key: "ref", labelKey: "admin.tableViews.column.ref" },
    { key: "alt", labelKey: "admin.tableViews.column.alt" },
    { key: "variant_type", labelKey: "admin.tableViews.column.variant_type" },
    { key: "impact", labelKey: "admin.tableViews.column.impact" },
    { key: "gene_id", labelKey: "admin.tableViews.column.gene_id" },
  ],
  genes: [
    { key: "gene_id", labelKey: "admin.tableViews.column.gene_id" },
    { key: "symbol", labelKey: "admin.tableViews.column.symbol" },
    { key: "biotype", labelKey: "admin.tableViews.column.biotype" },
    { key: "chromosome", labelKey: "admin.tableViews.column.chromosome" },
    { key: "variant_count", labelKey: "admin.tableViews.column.variant_count" },
  ],
  mutant_lines: [
    { key: "public_id", labelKey: "admin.tableViews.column.public_id" },
    { key: "name", labelKey: "admin.tableViews.column.name" },
    { key: "mutagen", labelKey: "admin.tableViews.column.mutagen" },
    { key: "cultivar", labelKey: "admin.tableViews.column.cultivar" },
    { key: "generation", labelKey: "admin.tableViews.column.generation" },
  ],
};

interface InstanceFormValues {
  code: string;
  name: string;
  species: string;
  api_base_url: string;
  jbrowse_base_url?: string;
  portal_base_url?: string;
  is_local: boolean;
}

export default function TableViewsPage() {
  const { t, i18n } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();

  const [kind, setKind] = React.useState<TableKind>("mutation_sites");
  const [species, setSpecies] = React.useState("Glycine max");
  const [siteVariant, setSiteVariant] = React.useState<"external" | "internal">("external");
  const [draftName, setDraftName] = React.useState("");
  const [draftColumns, setDraftColumns] = React.useState<TableColumn[]>([]);
  const [draftActions, setDraftActions] = React.useState({ jbrowse: true, genome_preview: true });
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [editingReleaseId, setEditingReleaseId] = React.useState<string>("");
  const [instanceForm] = Form.useForm<InstanceFormValues>();

  const templatesQuery = useQuery({
    queryKey: ["admin", "table-views", kind],
    queryFn: () => listTableViewTemplates({ kind }),
    staleTime: 30_000,
  });
  const instancesQuery = useQuery({
    queryKey: ["admin", "species-instances"],
    queryFn: listSpeciesInstances,
    staleTime: 30_000,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["admin", "table-views"] });
    // The portal caches the resolved layout too; drop it so the change is
    // visible on the next page load.
    void queryClient.invalidateQueries({ queryKey: ["table-views"] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload = {
        name: draftName.trim() || `${t(KIND_LABEL_KEYS[kind])} ${templatesQuery.data?.total ?? 0 + 1}`,
        columns: draftColumns,
        actions: draftActions,
        release_id: editingReleaseId ? Number(editingReleaseId) : null,
      };
      if (editingId) return updateTableViewTemplate(editingId, payload);
      return createTableViewTemplate({
        kind,
        name: payload.name,
        species,
        site_variant: siteVariant,
        columns: payload.columns,
        actions: payload.actions,
      });
    },
    onSuccess: () => {
      message.success(t("common.success"));
      invalidate();
      setEditingId(null);
      setDraftName("");
    },
    onError: () => message.error(t("common.error")),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteTableViewTemplate(id),
    onSuccess: () => {
      message.success(t("common.success"));
      invalidate();
    },
    onError: () => message.error(t("common.error")),
  });

  const promoteMutation = useMutation({
    mutationFn: (id: number) => updateTableViewTemplate(id, { is_default: true }),
    onSuccess: () => {
      message.success(t("common.success"));
      invalidate();
    },
    onError: () => message.error(t("common.error")),
  });

  const instanceMutation = useMutation({
    mutationFn: (values: InstanceFormValues) =>
      createSpeciesInstance({
        code: values.code.trim(),
        name: values.name.trim(),
        species: values.species.trim(),
        api_base_url: values.api_base_url.trim(),
        jbrowse_base_url: values.jbrowse_base_url?.trim() || null,
        portal_base_url: values.portal_base_url?.trim() || null,
        is_local: values.is_local,
      }),
    onSuccess: () => {
      message.success(t("common.success"));
      instanceForm.resetFields();
      void queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] });
    },
    onError: () => message.error(t("common.error")),
  });

  const templates: TableViewTemplate[] = templatesQuery.data?.items ?? [];
  const instances: SpeciesInstance[] = instancesQuery.data?.items ?? [];
  const candidates = KNOWN_COLUMN_KEYS[kind];
  const selectedKeys = new Set(draftColumns.map((column) => column.key));
  // A template persists one label per locale, so both are resolved from the
  // resources rather than copied from whichever language the operator is in.
  const labelZh = i18n.getFixedT("zh");
  const labelEn = i18n.getFixedT("en");

  function startNew() {
    setEditingId(null);
    setDraftName("");
    setEditingReleaseId("");
    setDraftColumns(
      candidates.slice(0, 8).map((column) => ({
        key: column.key,
        label_zh: labelZh(column.labelKey),
        label_en: labelEn(column.labelKey),
        visible: true,
      })),
    );
    setDraftActions({ jbrowse: true, genome_preview: true });
  }

  function startEdit(template: TableViewTemplate) {
    setEditingId(template.id);
    setDraftName(template.name);
    setEditingReleaseId(template.release_id ? String(template.release_id) : "");
    setDraftColumns(template.columns);
    setDraftActions(template.actions);
  }

  // Both tables on this screen are editor surfaces, not read-only reports: every
  // row carries its own write action (edit / promote / delete / enable / unregister).
  // `editable: false` keeps ProTable's own cell editor out so the page's explicit
  // buttons remain the only mutation path.
  const templateColumns: ProColumns<TableViewTemplate>[] = [
    {
      title: t("admin.tableViews.columnName"),
      dataIndex: "name",
      key: "name",
      editable: false,
      render: (name) => <span className="font-medium">{name}</span>,
    },
    {
      title: t("admin.tableViews.instanceSpeciesVariant"),
      key: "scope",
      editable: false,
      render: (_, row) => (
        <Space size={4}>
          <Tag>{row.species}</Tag>
          <Tag color={row.site_variant === "internal" ? "gold" : "blue"}>
            {row.site_variant}
          </Tag>
          {row.release_id ? <Tag>release {row.release_id}</Tag> : <Tag>all releases</Tag>}
        </Space>
      ),
    },
    {
      title: t("admin.tableViews.columnsLabel"),
      key: "columns",
      editable: false,
      render: (_, row) => (
        <span className="font-mono text-xs">
          {row.columns
            .filter((column) => column.visible)
            .map((column) => column.key)
            .join(", ")}
        </span>
      ),
    },
    {
      title: t("admin.tableViews.columnDefault"),
      key: "is_default",
      editable: false,
      render: (_, row) => (row.is_default ? <Tag color="green">default</Tag> : null),
    },
    {
      title: t("admin.tableViews.actions"),
      key: "actions",
      editable: false,
      render: (_, row) => (
        <Space>
          <Button size="small" onClick={() => startEdit(row)}>
            {t("admin.tableViews.actionEdit")}
          </Button>
          {row.is_default ? null : (
            <Button
              size="small"
              icon={<StarOutlined />}
              loading={promoteMutation.isPending}
              onClick={() => promoteMutation.mutate(row.id)}
            >
              {t("admin.tableViews.actionSetDefault")}
            </Button>
          )}
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => deleteMutation.mutate(row.id)}
          >
            {t("admin.tableViews.actionDelete")}
          </Button>
        </Space>
      ),
    },
  ];

  const instanceColumns: ProColumns<SpeciesInstance>[] = [
    { title: "code", dataIndex: "code", key: "code", editable: false, render: (code) => <code>{code}</code> },
    { title: t("admin.tableViews.columnName"), dataIndex: "name", key: "name", editable: false },
    { title: t("admin.tableViews.species"), dataIndex: "species", key: "species", editable: false },
    { title: "API", dataIndex: "api_base_url", key: "api_base_url", editable: false, render: (url) => <code>{url}</code> },
    {
      title: t("admin.tableViews.local"),
      key: "is_local",
      editable: false,
      render: (_, row) => (row.is_local ? <Tag color="green">local</Tag> : null),
    },
    {
      title: t("admin.tableViews.actions"),
      key: "actions",
      editable: false,
      render: (_, row) => (
        <Space>
          <Switch
            size="small"
            checked={row.is_enabled}
            onChange={(checked) =>
              updateSpeciesInstance(row.id, { is_enabled: checked }).then(() =>
                queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] }),
              )
            }
          />
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() =>
              deleteSpeciesInstance(row.id).then(() =>
                queryClient.invalidateQueries({ queryKey: ["admin", "species-instances"] }),
              )
            }
          >
            {t("admin.tableViews.actionDelete")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <PageContainer title={t("admin.tableViews.title")}>
      <div className="space-y-6">
        <Alert
          type="info"
          showIcon
          title={t("admin.tableViews.bannerTitle")}
          description={t("admin.tableViews.bannerDescription")}
        />

        <ProCard
          size="small"
          title={t("admin.tableViews.tableLabel")}
          extra={
            <Space>
              <Select
                value={kind}
                style={{ width: 220 }}
                options={TABLE_KINDS.map((value) => ({ value, label: t(KIND_LABEL_KEYS[value]) }))}
                onChange={(value: TableKind) => setKind(value)}
              />
              <Select
                value={species}
                style={{ width: 160 }}
                options={[
                  { value: "Glycine max", label: "Glycine max" },
                  { value: "Zea mays", label: "Zea mays" },
                ]}
                onChange={(value: string) => setSpecies(value)}
              />
              <Select
                value={siteVariant}
                style={{ width: 140 }}
                options={[
                  { value: "external", label: "external" },
                  { value: "internal", label: "internal" },
                ]}
                onChange={(value: "external" | "internal") => setSiteVariant(value)}
              />
            </Space>
          }
        >
          {templatesQuery.isLoading ? (
            <Skeleton active />
          ) : templates.length === 0 ? (
            <Empty description={t("admin.tableViews.empty")} />
          ) : (
            <ProTable<TableViewTemplate>
              {...PRO_LIST_SHELL}
              rowKey="id"
              size="small"
              dataSource={templates}
              pagination={false}
              columns={templateColumns}
            />
          )}
        </ProCard>

        <ProCard size="small" title={t(editingId ? "admin.tableViews.editTemplate" : "admin.tableViews.newTemplate")}>
          <Form layout="vertical" onFinish={() => saveMutation.mutate()}>
            <Form.Item label={t("admin.tableViews.name")} required>
              <Input
                value={draftName}
                placeholder={t("admin.tableViews.namePlaceholder")}
                onChange={(event) => setDraftName(event.target.value)}
              />
            </Form.Item>
            <Form.Item label={t("admin.tableViews.columnsLabel")}>
              <div className="grid gap-2 sm:grid-cols-2">
                {draftColumns.map((column, index) => (
                  <Space key={column.key} size={8}>
                    <Checkbox
                      checked={column.visible}
                      onChange={(event) =>
                        setDraftColumns((previous) =>
                          previous.map((item, position) =>
                            position === index ? { ...item, visible: event.target.checked } : item,
                          ),
                        )
                      }
                    />
                    <span className="text-sm">{column.label_zh}</span>
                    <Button
                      size="small"
                      type="text"
                      disabled={index === 0}
                      onClick={() =>
                        setDraftColumns((previous) => {
                          const next = [...previous];
                          const [moved] = next.splice(index, 1);
                          next.splice(index - 1, 0, moved);
                          return next;
                        })
                      }
                    >
                      ↑
                    </Button>
                    <Button
                      size="small"
                      type="text"
                      disabled={index === draftColumns.length - 1}
                      onClick={() =>
                        setDraftColumns((previous) => {
                          const next = [...previous];
                          const [moved] = next.splice(index, 1);
                          next.splice(index + 1, 0, moved);
                          return next;
                        })
                      }
                    >
                      ↓
                    </Button>
                    <Button
                      size="small"
                      type="text"
                      danger
                      onClick={() =>
                        setDraftColumns((previous) => previous.filter((_, position) => position !== index))
                      }
                    >
                      ×
                    </Button>
                  </Space>
                ))}
              </div>
            </Form.Item>
            <Form.Item label={t("admin.tableViews.addColumns")}>
              <Space wrap>
                {candidates
                  .filter((column) => !selectedKeys.has(column.key))
                  .map((column) => (
                    <Button
                      key={column.key}
                      size="small"
                      onClick={() =>
                        setDraftColumns((previous) => [
                          ...previous,
                          {
                            key: column.key,
                            label_zh: labelZh(column.labelKey),
                            label_en: labelEn(column.labelKey),
                            visible: true,
                          },
                        ])
                      }
                    >
                      + {t(column.labelKey)}
                    </Button>
                  ))}
              </Space>
            </Form.Item>
            <Form.Item label={t("admin.tableViews.trailingActions")}>
              <Space>
                <Switch
                  checked={draftActions.jbrowse}
                  checkedChildren="JBrowse 2"
                  unCheckedChildren="JBrowse 2"
                  onChange={(checked) => setDraftActions((previous) => ({ ...previous, jbrowse: checked }))}
                />
                <Switch
                  checked={draftActions.genome_preview}
                  checkedChildren={t("admin.tableViews.genePreview")}
                  unCheckedChildren={t("admin.tableViews.genePreview")}
                  onChange={(checked) =>
                    setDraftActions((previous) => ({ ...previous, genome_preview: checked }))
                  }
                />
              </Space>
            </Form.Item>
            <Form.Item label={t("admin.tableViews.releaseLabel")}>
              <Input
                value={editingReleaseId}
                placeholder={t("admin.tableViews.releasePlaceholder")}
                onChange={(event) => setEditingReleaseId(event.target.value)}
              />
            </Form.Item>
            <Space>
              <Button
                type="primary"
                htmlType="submit"
                icon={<SaveOutlined />}
                loading={saveMutation.isPending}
                disabled={draftColumns.length === 0}
              >
                {t("admin.tableViews.saveTemplate")}
              </Button>
              <Button onClick={startNew} icon={<PlusOutlined />}>
                {t("admin.tableViews.create")}
              </Button>
            </Space>
          </Form>
        </ProCard>

        <ProCard size="small" title={t("admin.tableViews.instancesTitle")}>
          <Alert
            type="info"
            showIcon
            title={t("admin.tableViews.instancesBanner")}
            style={{ marginBottom: 12 }}
          />
          {instancesQuery.isLoading ? (
            <Skeleton active />
          ) : (
            <ProTable<SpeciesInstance>
              {...PRO_LIST_SHELL}
              rowKey="id"
              size="small"
              dataSource={instances}
              pagination={false}
              columns={instanceColumns}
            />
          )}

          <Form
            form={instanceForm}
            layout="vertical"
            className="mt-4"
            initialValues={{ is_local: false }}
            onFinish={(values: InstanceFormValues) => instanceMutation.mutate(values)}
          >
            <Space wrap align="start">
              <Form.Item name="code" label="code" rules={[{ required: true }]}>
                <Input placeholder="soy" />
              </Form.Item>
              <Form.Item name="name" label={t("admin.tableViews.instanceName")} rules={[{ required: true }]}>
                <Input placeholder="Soybean" />
              </Form.Item>
              <Form.Item name="species" label={t("admin.tableViews.instanceSpecies")} rules={[{ required: true }]}>
                <Input placeholder="Glycine max" />
              </Form.Item>
              <Form.Item name="api_base_url" label="API origin" rules={[{ required: true }]}>
                <Input placeholder="https://api.example.org" />
              </Form.Item>
              <Form.Item name="jbrowse_base_url" label="JBrowse origin">
                <Input placeholder="https://jbrowse.example.org" />
              </Form.Item>
              <Form.Item name="portal_base_url" label="Portal origin">
                <Input placeholder="https://portal.example.org" />
              </Form.Item>
              <Form.Item name="is_local" label={t("admin.tableViews.instanceLocal")} valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item label=" ">
                <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={instanceMutation.isPending}>
                  {t("admin.tableViews.registerInstance")}
                </Button>
              </Form.Item>
            </Space>
          </Form>
        </ProCard>
      </div>
    </PageContainer>
  );
}
