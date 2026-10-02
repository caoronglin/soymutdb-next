import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  checkSpeciesInstanceHealth,
  createSpeciesInstance,
  deleteSpeciesInstance,
  listSpeciesInstances,
  updateSpeciesInstance,
  type SpeciesInstance,
} from "@soymutdb/api-client";
import { formatDate } from "@soymutdb/shared/format";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  PageContainer,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { ADMIN_INSTANCES_QUERY_KEY, useInstanceContext } from "../lib/instance-context-react";

interface InstanceFormValues {
  code: string;
  name: string;
  species: string;
  api_base_url: string;
  site_url: string;
  jbrowse_base_url: string;
  notes: string;
  is_enabled: boolean;
  is_local: boolean;
}

function safeUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? value : null;
  } catch {
    return null;
  }
}

export default function SpeciesInstancesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { currentInstance, isRemote, selectInstance } = useInstanceContext();
  const [form] = Form.useForm<InstanceFormValues>();
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [editingId, setEditingId] = React.useState<number | null>(null);
  const [editorIsLocal, setEditorIsLocal] = React.useState(false);
  const [deleteTarget, setDeleteTarget] = React.useState<SpeciesInstance | null>(null);
  const [checkingId, setCheckingId] = React.useState<number | null>(null);
  const [errorMessage, setErrorMessage] = React.useState("");
  const [noticeMessage, setNoticeMessage] = React.useState("");

  const query = useQuery({
    queryKey: ADMIN_INSTANCES_QUERY_KEY,
    queryFn: listSpeciesInstances,
    retry: false,
  });
  const instances = query.data?.items ?? [];

  const resetDraft = React.useCallback(() => {
    form.resetFields();
    form.setFieldsValue({
      code: "",
      name: "",
      species: "Glycine max",
      api_base_url: "",
      site_url: "",
      jbrowse_base_url: "",
      notes: "",
      is_enabled: true,
      is_local: false,
    });
  }, [form]);

  const openCreate = () => {
    setEditingId(null);
    setEditorIsLocal(false);
    resetDraft();
    setEditorOpen(true);
    setErrorMessage("");
    setNoticeMessage("");
  };

  const openEdit = (instance: SpeciesInstance) => {
    setEditingId(instance.id);
    setEditorIsLocal(instance.is_local);
    form.setFieldsValue({
      code: instance.code,
      name: instance.name,
      species: instance.species,
      api_base_url: instance.api_base_url,
      site_url: instance.portal_base_url ?? instance.site_url ?? "",
      jbrowse_base_url: instance.jbrowse_base_url ?? "",
      notes: instance.notes ?? "",
      is_enabled: instance.is_enabled,
      is_local: instance.is_local,
    });
    setEditorOpen(true);
    setErrorMessage("");
    setNoticeMessage("");
  };

  const closeEditor = () => {
    setEditorOpen(false);
    setEditingId(null);
  };

  const saveMutation = useMutation({
    mutationFn: async (values: InstanceFormValues) => {
      const fields = {
        name: values.name.trim(),
        species: values.species.trim(),
        api_base_url: values.api_base_url.trim(),
        site_url: values.site_url.trim() || null,
        jbrowse_base_url: values.jbrowse_base_url.trim() || null,
        notes: values.notes.trim() || null,
        is_enabled: values.is_enabled,
      };
      // `code` and `is_local` are registration-time identities. The update
      // endpoint does not accept identity changes for an existing instance.
      return editingId === null
        ? createSpeciesInstance({ code: values.code.trim(), is_local: values.is_local, ...fields })
        : updateSpeciesInstance(editingId, fields);
    },
    onSuccess: () => {
      closeEditor();
      setNoticeMessage(t("admin.instances.saveSuccess"));
      setErrorMessage("");
      void queryClient.invalidateQueries({ queryKey: ADMIN_INSTANCES_QUERY_KEY });
    },
    onError: () => {
      setNoticeMessage("");
      setErrorMessage(t("admin.instances.saveError"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteSpeciesInstance,
    onSuccess: () => {
      setDeleteTarget(null);
      setNoticeMessage(t("admin.instances.deleteSuccess"));
      setErrorMessage("");
      void queryClient.invalidateQueries({ queryKey: ADMIN_INSTANCES_QUERY_KEY });
    },
    onError: () => {
      setDeleteTarget(null);
      setNoticeMessage("");
      setErrorMessage(t("admin.instances.deleteError"));
    },
  });

  const healthMutation = useMutation({
    mutationFn: checkSpeciesInstanceHealth,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ADMIN_INSTANCES_QUERY_KEY });
    },
    onError: () => {
      setNoticeMessage("");
      setErrorMessage(t("admin.instances.healthError"));
    },
  });

  const stateLabel = (state: SpeciesInstance["connection_state"]) => {
    if (state === "healthy") return t("admin.instances.healthy");
    if (state === "unhealthy") return t("admin.instances.unreachable");
    if (state === "disabled") return t("admin.instances.disabled");
    if (state === "unconfigured") return t("admin.instances.unconfigured");
    return t("common.unknown");
  };

  const columns: TableColumnsType<SpeciesInstance> = [
    {
      title: t("admin.instances.name"),
      dataIndex: "name",
      key: "name",
      render: (_value, instance) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text strong>{instance.name}</Typography.Text>
          <Typography.Text code>{instance.code}</Typography.Text>
          <Space size={[4, 4]} wrap>
            {instance.is_local ? <Tag color="blue">{t("admin.instances.local")}</Tag> : null}
            {currentInstance?.code === instance.code ? <Tag color="green">{t("admin.instances.currentFlag")}</Tag> : null}
            {!instance.is_enabled ? <Tag>{t("admin.instances.disabled")}</Tag> : null}
          </Space>
        </Space>
      ),
    },
    { title: t("admin.instances.species"), dataIndex: "species", key: "species" },
    {
      title: t("admin.instances.apiUrl"),
      dataIndex: "api_base_url",
      key: "api_base_url",
      render: (value: string, instance) => {
        const portal = safeUrl(instance.portal_base_url ?? instance.site_url);
        return (
          <Space orientation="vertical" size={2}>
            <Typography.Text code copyable>{value}</Typography.Text>
            {portal ? (
              <a
                href={portal}
                target="_blank"
                rel="noopener noreferrer"
                data-testid={`instance-open-${instance.id}`}
              >
                {t("admin.instances.openPortal")}
              </a>
            ) : null}
          </Space>
        );
      },
    },
    {
      title: t("admin.instances.connection"),
      dataIndex: "connection_state",
      key: "connection_state",
      render: (state: SpeciesInstance["connection_state"]) => (
        <Tag color={state === "healthy" ? "green" : state === "unhealthy" ? "red" : "default"}>
          {stateLabel(state)}
        </Tag>
      ),
    },
    {
      title: t("admin.instances.lastChecked"),
      dataIndex: "last_checked_at",
      key: "last_checked_at",
      render: (value: string | null) => value ? formatDate(value) : "—",
    },
    {
      title: t("common.actions"),
      key: "actions",
      render: (_value, instance) => (
        <Space wrap size={[4, 4]}>
          <Button size="small" data-testid={`instance-edit-${instance.id}`} onClick={() => openEdit(instance)}>
            {t("common.edit")}
          </Button>
          <Button
            size="small"
            disabled={currentInstance?.code === instance.code}
            data-testid={`instance-select-${instance.id}`}
            onClick={() => selectInstance(instance.code)}
          >
            {currentInstance?.code === instance.code ? t("admin.instances.currentFlag") : t("admin.instances.setCurrent")}
          </Button>
          <Button
            size="small"
            loading={checkingId === instance.id}
            disabled={checkingId !== null && checkingId !== instance.id}
            data-testid={`instance-check-${instance.id}`}
            onClick={() => {
              setCheckingId(instance.id);
              healthMutation.mutate(instance.id, {
                onSettled: () => setCheckingId((current) => current === instance.id ? null : current),
              });
            }}
          >
            {t("admin.instances.checkConnection")}
          </Button>
          <Button
            size="small"
            danger
            disabled={instance.is_local}
            title={instance.is_local ? t("admin.instances.localHint") : undefined}
            data-testid={`instance-delete-${instance.id}`}
            onClick={() => setDeleteTarget(instance)}
          >
            {t("common.delete")}
          </Button>
        </Space>
      ),
    },
  ];

  const pageTitle = t("admin.instances.title", { defaultValue: "Species instances" });
  const description = t("admin.instances.description", { defaultValue: "Register database deployments and check their bounded health status." });

  return (
    <PageContainer
      title={pageTitle}
      subTitle={description}
      extra={[
        <Button key="create" type="primary" data-testid="instances-new" onClick={openCreate}>
          {t("admin.instances.create")}
        </Button>,
      ]}
    >
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <Card size="small">
          <Space orientation="vertical" size={6}>
            <Space wrap>
              <Typography.Text>{t("admin.instances.context")}: </Typography.Text>
              <Typography.Text strong data-testid="instances-current">{currentInstance?.name ?? "—"}</Typography.Text>
              {isRemote ? <Tag color="gold">{t("admin.instances.registrationOnly")}</Tag> : null}
            </Space>
            {isRemote ? (
              <Typography.Text type="warning" data-testid="instances-remote-disabled">
                {t("admin.instances.adminDisabled")}
              </Typography.Text>
            ) : null}
            <Typography.Text type="secondary" data-testid="instances-api-invariant">
              {t("admin.instances.apiInvariant")}
            </Typography.Text>
          </Space>
        </Card>

        {noticeMessage ? <Alert type="success" showIcon title={noticeMessage} data-testid="instances-notice" /> : null}
        {errorMessage ? <Alert type="error" showIcon title={errorMessage} role="alert" data-testid="instances-error" /> : null}

        {editorOpen ? (
          <Card
            title={editingId === null ? t("admin.instances.create") : t("admin.instances.edit")}
            extra={editingId !== null ? <Typography.Text code>#{editingId}</Typography.Text> : null}
            data-testid="instance-editor"
          >
            <Form<InstanceFormValues>
              form={form}
              layout="vertical"
              initialValues={{ species: "Glycine max", is_enabled: true, is_local: false }}
              onFinish={(values) => saveMutation.mutate(values)}
            >
              <div className="grid gap-x-4 sm:grid-cols-2">
                <Form.Item
                  label={t("admin.instances.code")}
                  name="code"
                  rules={[{ required: true }]}
                >
                  <Input disabled={editingId !== null} maxLength={32} data-testid="instance-code" />
                </Form.Item>
                <Form.Item label={t("admin.instances.name")} name="name" rules={[{ required: true }]}>
                  <Input maxLength={128} data-testid="instance-name" />
                </Form.Item>
                <Form.Item label={t("admin.instances.species")} name="species" rules={[{ required: true }]}>
                  <Input maxLength={128} data-testid="instance-species" />
                </Form.Item>
                <Form.Item label={t("admin.instances.apiUrl")} name="api_base_url" rules={[{ required: true, type: "url" }]}>
                  <Input data-testid="instance-api-url" />
                </Form.Item>
                <Form.Item label={t("admin.instances.portalUrl")} name="site_url" rules={[{ type: "url" }]}>
                  <Input data-testid="instance-site-url" />
                </Form.Item>
                <Form.Item label={t("admin.instances.jbrowseUrl")} name="jbrowse_base_url" rules={[{ type: "url" }]}>
                  <Input data-testid="instance-jbrowse-url" />
                </Form.Item>
                <Form.Item label={t("admin.instances.notes")} name="notes" className="sm:col-span-2">
                  <Input.TextArea rows={2} data-testid="instance-notes" />
                </Form.Item>
              </div>
              <Space wrap>
                <Form.Item name="is_enabled" valuePropName="checked" noStyle>
                  <Switch data-testid="instance-enabled" />
                </Form.Item>
                <Typography.Text>{t("admin.instances.enabled")}</Typography.Text>
                {editingId === null ? (
                  <>
                    <Form.Item name="is_local" valuePropName="checked" noStyle>
                      <Switch data-testid="instance-local" />
                    </Form.Item>
                    <Typography.Text>{t("admin.instances.local")}</Typography.Text>
                  </>
                ) : null}
              </Space>
              <Space orientation="vertical" size="small" style={{ display: "flex", marginTop: 16 }}>
                {editorIsLocal ? <Alert type="info" showIcon title={t("admin.instances.localHint")} data-testid="instance-local-hint" /> : null}
                {editingId === null && !editorIsLocal ? <Alert type="info" showIcon title={t("admin.instances.remoteHint")} data-testid="instance-remote-hint" /> : null}
                <Alert type="info" showIcon title={t("admin.instances.targetNote")} data-testid="instance-target-note" />
              </Space>
              <Space style={{ marginTop: 16 }}>
                <Button type="primary" htmlType="submit" loading={saveMutation.isPending} data-testid="instance-save">
                  {saveMutation.isPending ? t("common.loading") : t("common.save")}
                </Button>
                <Button htmlType="button" data-testid="instance-cancel" onClick={closeEditor}>
                  {t("common.cancel")}
                </Button>
              </Space>
            </Form>
          </Card>
        ) : null}

        {deleteTarget ? (
          <Alert
            type="error"
            showIcon
            data-testid="instance-delete-confirm"
            title={t("admin.instances.deleteConfirmTitle")}
            description={
              <Space orientation="vertical">
                <span>{t("admin.instances.deleteConfirmBody")}</span>
                <Typography.Text code>{deleteTarget.name} · {deleteTarget.code}</Typography.Text>
                <Space>
                  <Button
                    type="primary"
                    danger
                    size="small"
                    loading={deleteMutation.isPending}
                    data-testid="instance-delete-confirm-button"
                    onClick={() => deleteMutation.mutate(deleteTarget.id)}
                  >
                    {t("common.delete")}
                  </Button>
                  <Button size="small" data-testid="instance-delete-cancel" onClick={() => setDeleteTarget(null)}>
                    {t("common.cancel")}
                  </Button>
                </Space>
              </Space>
            }
          />
        ) : null}

        {query.isPending ? (
          <Card loading data-testid="instances-loading" />
        ) : query.isError ? (
          <Alert
            type="error"
            showIcon
            data-testid="instances-load-error"
            title={t("common.errorDescription")}
            action={<Button size="small" onClick={() => void query.refetch()} data-testid="instances-retry">{t("common.retry")}</Button>}
          />
        ) : instances.length === 0 ? (
          <Card><Typography.Text type="secondary" data-testid="instances-empty">{t("admin.instances.empty")}</Typography.Text></Card>
        ) : (
          <Card>
            <div data-testid="instances-table">
              <Table<SpeciesInstance>
                rowKey="id"
                dataSource={instances}
                columns={columns}
                pagination={{ pageSize: 10, showSizeChanger: true }}
                scroll={{ x: 1100 }}
                rowClassName={() => "instance-row"}
                onRow={() => ({ "data-testid": "instance-row" } as React.HTMLAttributes<HTMLTableRowElement>)}
              />
            </div>
          </Card>
        )}
      </Space>
    </PageContainer>
  );
}
