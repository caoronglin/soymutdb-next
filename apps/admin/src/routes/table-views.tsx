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
  Card,
  Checkbox,
  Empty,
  Form,
  Input,
  Select,
  Skeleton,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from "@/lib/antd";
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

const KIND_LABELS: Record<TableKind, string> = {
  mutation_sites: "突变位点表 / Mutation sites",
  variants: "变异表 / Variants",
  genes: "基因表 / Genes",
  mutant_lines: "株系表 / Mutant lines",
};

/** Candidate columns an operator can add; ``homolog:*`` is the opt-in family. */
const KNOWN_COLUMNS: Record<TableKind, Array<{ key: string; label: string }>> = {
  mutation_sites: [
    { key: "mutant_line_name", label: "株系 / Mutant line" },
    { key: "mutation_system", label: "突变体系（株系母+位置）" },
    { key: "chromosome", label: "染色体号" },
    { key: "position", label: "位点" },
    { key: "confidence", label: "可信度" },
    { key: "gene_id", label: "基因号" },
    { key: "feature", label: "特征" },
    { key: "available", label: "可获得" },
    { key: "homolog:W82_V2", label: "W82_V2（跨组装同源）" },
    { key: "homolog:W82_V4", label: "W82_V4（跨组装同源）" },
    { key: "homolog:DN53_V1", label: "DN53_V1（跨物种同源）" },
  ],
  variants: [
    { key: "variant_id", label: "Variant ID" },
    { key: "chromosome", label: "染色体号" },
    { key: "position", label: "位点" },
    { key: "ref", label: "参考等位" },
    { key: "alt", label: "替代等位" },
    { key: "variant_type", label: "类型" },
    { key: "impact", label: "影响" },
    { key: "gene_id", label: "基因号" },
  ],
  genes: [
    { key: "gene_id", label: "基因 ID" },
    { key: "symbol", label: "符号" },
    { key: "biotype", label: "类型" },
    { key: "chromosome", label: "染色体号" },
    { key: "variant_count", label: "变异数" },
  ],
  mutant_lines: [
    { key: "public_id", label: "株系" },
    { key: "name", label: "名称" },
    { key: "mutagen", label: "诱变剂" },
    { key: "cultivar", label: "品种" },
    { key: "generation", label: "世代" },
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
  const { t } = useTranslation();
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
        name: draftName.trim() || `${KIND_LABELS[kind]} ${templatesQuery.data?.total ?? 0 + 1}`,
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
  const candidates = KNOWN_COLUMNS[kind];
  const selectedKeys = new Set(draftColumns.map((column) => column.key));

  function startNew() {
    setEditingId(null);
    setDraftName("");
    setEditingReleaseId("");
    setDraftColumns(
      candidates.slice(0, 8).map((column) => ({
        key: column.key,
        label_zh: column.label,
        label_en: column.label,
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

  return (
    <div className="space-y-6 p-6">
      <Typography.Title level={3} style={{ margin: 0 }}>
        表格模板 / Table view templates
      </Typography.Title>
      <Alert
        type="info"
        showIcon
        title="列顺序、显隐与操作按钮都在此配置；跨组装同源列（W82_V2 / W82_V4 / DN53_V1）默认关闭，按需添加。"
        description="保存为模板后立即生效：门户按物种、站点变体与 release 解析这一列集合。"
      />

      <Card
        size="small"
        title="选择表 / Table"
        extra={
          <Space>
            <Select
              value={kind}
              style={{ width: 220 }}
              options={TABLE_KINDS.map((value) => ({ value, label: KIND_LABELS[value] }))}
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
          <Empty description="该表还没有模板，正在使用内置默认列。" />
        ) : (
          <Table<TableViewTemplate>
            rowKey="id"
            size="small"
            dataSource={templates}
            pagination={false}
            columns={[
              {
                title: "名称",
                dataIndex: "name",
                key: "name",
                render: (name: string) => <span className="font-medium">{name}</span>,
              },
              {
                title: "物种 / 变体",
                key: "scope",
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
                title: "列",
                key: "columns",
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
                title: "默认",
                key: "is_default",
                render: (_, row) => (row.is_default ? <Tag color="green">default</Tag> : null),
              },
              {
                title: "操作",
                key: "actions",
                render: (_, row) => (
                  <Space>
                    <Button size="small" onClick={() => startEdit(row)}>
                      编辑
                    </Button>
                    {row.is_default ? null : (
                      <Button
                        size="small"
                        icon={<StarOutlined />}
                        loading={promoteMutation.isPending}
                        onClick={() => promoteMutation.mutate(row.id)}
                      >
                        设为默认
                      </Button>
                    )}
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => deleteMutation.mutate(row.id)}
                    >
                      删除
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
      </Card>

      <Card size="small" title={editingId ? "编辑模板 / Edit template" : "新建模板 / New template"}>
        <Form layout="vertical" onFinish={() => saveMutation.mutate()}>
          <Form.Item label="名称" required>
            <Input
              value={draftName}
              placeholder="例如：突变位点（含同源列）"
              onChange={(event) => setDraftName(event.target.value)}
            />
          </Form.Item>
          <Form.Item label="列（按显示顺序；勾选控制显隐）">
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
          <Form.Item label="添加列">
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
                        { key: column.key, label_zh: column.label, label_en: column.label, visible: true },
                      ])
                    }
                  >
                    + {column.label}
                  </Button>
                ))}
            </Space>
          </Form.Item>
          <Form.Item label="尾部操作">
            <Space>
              <Switch
                checked={draftActions.jbrowse}
                checkedChildren="JBrowse 2"
                unCheckedChildren="JBrowse 2"
                onChange={(checked) => setDraftActions((previous) => ({ ...previous, jbrowse: checked }))}
              />
              <Switch
                checked={draftActions.genome_preview}
                checkedChildren="基因预览"
                unCheckedChildren="基因预览"
                onChange={(checked) =>
                  setDraftActions((previous) => ({ ...previous, genome_preview: checked }))
                }
              />
            </Space>
          </Form.Item>
          <Form.Item label="Release（留空=全部 release）">
            <Input
              value={editingReleaseId}
              placeholder="留空表示发布级默认"
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
              保存模板
            </Button>
            <Button onClick={startNew} icon={<PlusOutlined />}>
              新建
            </Button>
          </Space>
        </Form>
      </Card>

      <Card size="small" title="多物种实例 / Species instances">
        <Alert
          type="info"
          showIcon
          title="一个管理面板可管理多个物种库：在此登记每个实例的 API / JBrowse / 门户地址，数据仍留在各自实例内。"
          style={{ marginBottom: 12 }}
        />
        {instancesQuery.isLoading ? (
          <Skeleton active />
        ) : (
          <Table<SpeciesInstance>
            rowKey="id"
            size="small"
            dataSource={instances}
            pagination={false}
            columns={[
              { title: "code", dataIndex: "code", key: "code", render: (code: string) => <code>{code}</code> },
              { title: "名称", dataIndex: "name", key: "name" },
              { title: "物种", dataIndex: "species", key: "species" },
              { title: "API", dataIndex: "api_base_url", key: "api_base_url", render: (url: string) => <code>{url}</code> },
              {
                title: "本地",
                key: "is_local",
                render: (_, row) => (row.is_local ? <Tag color="green">local</Tag> : null),
              },
              {
                title: "操作",
                key: "actions",
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
                      删除
                    </Button>
                  </Space>
                ),
              },
            ]}
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
            <Form.Item name="name" label="名称" rules={[{ required: true }]}>
              <Input placeholder="Soybean" />
            </Form.Item>
            <Form.Item name="species" label="物种" rules={[{ required: true }]}>
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
            <Form.Item name="is_local" label="本机实例" valuePropName="checked">
              <Switch />
            </Form.Item>
            <Form.Item label=" ">
              <Button type="primary" htmlType="submit" icon={<PlusOutlined />} loading={instanceMutation.isPending}>
                登记实例
              </Button>
            </Form.Item>
          </Space>
        </Form>
      </Card>
    </div>
  );
}
