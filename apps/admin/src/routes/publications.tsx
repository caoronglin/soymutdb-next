/**
 * Admin Publications management — list + create/edit dialog.
 *
 * Driven by /api/v1/admin/publications. The Content tab "Publications"
 * sub-page links here for create/edit actions.
 */
import * as React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSearch } from "@tanstack/react-router";
import {
  Form,
  Input,
  InputNumber,
  Modal,
  Switch,
  App,
  Button,
  PageContainer,
  ProCard,
  Typography,
  Tag,
  Empty,
  Skeleton,
  Alert,
} from "@/lib/antd";
import { PlusOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import {
  listAdminPublications,
  createAdminPublication,
  updateAdminPublication,
  deleteAdminPublication,
  type PublicationCreate,
  type AdminPublication,
} from "@soymutdb/api-client";
import { ConfirmDialog } from "../components/confirm-dialog";

interface PublicationFormValues {
  id?: string;
  title: string;
  title_zh: string;
  authors: string;
  authors_zh: string;
  journal: string;
  year: number | null;
  doi: string;
  pmid: string;
  abstract: string;
  abstract_zh: string;
  is_featured: boolean;
}

function fromPublication(p: AdminPublication): PublicationFormValues {
  return {
    id: p.id,
    title: p.title,
    title_zh: p.title_zh ?? "",
    authors: p.authors,
    authors_zh: p.authors_zh ?? "",
    journal: p.journal ?? "",
    year: p.year ?? null,
    doi: p.doi ?? "",
    pmid: p.pmid ?? "",
    abstract: p.abstract ?? "",
    abstract_zh: p.abstract_zh ?? "",
    is_featured: p.is_featured,
  };
}

function emptyForm(): PublicationFormValues {
  return {
    title: "",
    title_zh: "",
    authors: "",
    authors_zh: "",
    journal: "",
    year: null,
    doi: "",
    pmid: "",
    abstract: "",
    abstract_zh: "",
    is_featured: false,
  };
}

function PublicationFormDialog({
  open,
  onClose,
  initial,
  onSubmit,
  loading,
}: {
  open: boolean;
  onClose: () => void;
  initial: PublicationFormValues;
  onSubmit: (values: PublicationFormValues) => void;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const [values, setValues] = React.useState<PublicationFormValues>(initial);

  const setField = <K extends keyof PublicationFormValues>(
    key: K,
    value: PublicationFormValues[K],
  ) => setValues((prev) => ({ ...prev, [key]: value }));

  const canSubmit = values.title.trim() !== "" && values.authors.trim() !== "" && !loading;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={initial.id ? t("admin.content.publication.editTitle", { defaultValue: "Edit publication" }) : t("admin.content.publication.newTitle", { defaultValue: "New publication" })}
      footer={null}
      width={720}
    >
      <Form layout="vertical" onFinish={() => onSubmit(values)}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Form.Item label={t("admin.content.publication.titleEn", { defaultValue: "Title (English) *" })} required>
            <Input value={values.title} onChange={(e) => setField("title", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.titleZh", { defaultValue: "Title (Chinese)" })}>
            <Input value={values.title_zh} onChange={(e) => setField("title_zh", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.authorsEn", { defaultValue: "Authors (English) *" })} required>
            <Input value={values.authors} onChange={(e) => setField("authors", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.authorsZh", { defaultValue: "Authors (Chinese)" })}>
            <Input value={values.authors_zh} onChange={(e) => setField("authors_zh", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.journal", { defaultValue: "Journal" })}>
            <Input value={values.journal} onChange={(e) => setField("journal", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.year", { defaultValue: "Year" })}>
            <InputNumber
              value={values.year ?? undefined}
              onChange={(v) => setField("year", v === null || v === undefined ? null : Number(v))}
              min={1000}
              max={3000}
              className="w-full"
            />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.doi", { defaultValue: "DOI" })}>
            <Input value={values.doi} onChange={(e) => setField("doi", e.target.value)} placeholder="10.xxxx/..." />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.pmid", { defaultValue: "PMID" })}>
            <Input value={values.pmid} onChange={(e) => setField("pmid", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.abstractEn", { defaultValue: "Abstract (English)" })} className="sm:col-span-2">
            <Input.TextArea rows={3} value={values.abstract} onChange={(e) => setField("abstract", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.abstractZh", { defaultValue: "Abstract (Chinese)" })} className="sm:col-span-2">
            <Input.TextArea rows={3} value={values.abstract_zh} onChange={(e) => setField("abstract_zh", e.target.value)} />
          </Form.Item>
          <Form.Item label={t("admin.content.publication.featured", { defaultValue: "Featured" })} valuePropName="checked">
            <Switch checked={values.is_featured} onChange={(c) => setField("is_featured", c)} />
          </Form.Item>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={onClose}>{t("admin.content.cancel", { defaultValue: "Cancel" })}</Button>
          <Button type="primary" htmlType="submit" loading={loading} disabled={!canSubmit}>
            { t("admin.content.save", { defaultValue: "Save" }) }
          </Button>
        </div>
      </Form>
    </Modal>
  );
}

export default function AdminPublicationsPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = React.useState(false);
  const [editing, setEditing] = React.useState<PublicationFormValues>(emptyForm());
  const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; title: string } | null>(null);
  const search = useSearch({ strict: false }) as { edit?: string };
  const editHandledRef = React.useRef<string | null>(null);


  const listQuery = useQuery({
    queryKey: ["admin-publications"],
    queryFn: () => listAdminPublications({ page: 1, page_size: 50 }),
  });

  // If the row Edit button navigated here with `?edit=<id>`, open the
  // dialog pre-populated with that publication's data once the list arrives.
  React.useEffect(() => {
    const editId = search.edit;
    if (!editId) return;
    if (editHandledRef.current === editId) return;
    const items = listQuery.data?.items ?? [];
    const target = items.find((p) => p.id === editId);
    if (!target) return;
    setEditing(fromPublication(target));
    setFormOpen(true);
    editHandledRef.current = editId;
  }, [search.edit, listQuery.data]);

  const createMutation = useMutation({
    mutationFn: (payload: PublicationCreate) => createAdminPublication(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-publications"] });
      message.success(t("admin.content.publication.created", { defaultValue: "Publication created" }));
      setFormOpen(false);
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      message.error(e?.message ?? t("admin.content.publication.createFailed", { defaultValue: "Failed to create publication" }));
    },
  });

  const updateMutation = useMutation({
    mutationFn: (params: { id: string; payload: Partial<PublicationCreate> }) =>
      updateAdminPublication(params.id, params.payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-publications"] });
      message.success(t("admin.content.publication.updated", { defaultValue: "Publication updated" }));
      setFormOpen(false);
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      message.error(e?.message ?? t("admin.content.publication.updateFailed", { defaultValue: "Failed to update publication" }));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteAdminPublication(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-publications"] });
      message.success(t("admin.content.publication.deleted", { defaultValue: "Publication deleted" }));
      setDeleteTarget(null);
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      message.error(e?.message ?? t("admin.content.publication.deleteFailed", { defaultValue: "Failed to delete publication" }));
    },
  });

  const items = listQuery.data?.items ?? [];

  const handleSubmit = (values: PublicationFormValues) => {
    const payload: PublicationCreate = {
      title: values.title.trim(),
      title_zh: values.title_zh.trim() || null,
      authors: values.authors.trim(),
      authors_zh: values.authors_zh.trim() || null,
      journal: values.journal.trim() || null,
      year: values.year,
      doi: values.doi.trim() || null,
      pmid: values.pmid.trim() || null,
      abstract: values.abstract.trim() || null,
      abstract_zh: values.abstract_zh.trim() || null,
      is_featured: values.is_featured,
    };
    if (values.id) {
      updateMutation.mutate({ id: values.id, payload });
    } else {
      createMutation.mutate(payload);
    }
  };

  return (
    <PageContainer
      title={t("admin.content.publication.title", { defaultValue: "Publications" })}
      subTitle={t("admin.content.publication.subtitle", { defaultValue: "Manage bilingual bibliography entries published to the public site." })}
      extra={[
        <Button
          key="new-publication"
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => { setEditing(emptyForm()); setFormOpen(true); }}
        >
          {t("admin.content.publication.new", { defaultValue: "New publication" })}
        </Button>,
      ]}
    >
      <div className="space-y-6">
        {listQuery.isError ? (
          <Alert
            type="error"
            showIcon
            title={t("admin.content.publication.loadError", { defaultValue: "Could not load publications" })}
          />
        ) : null}

        {listQuery.isPending ? (
          <Skeleton active paragraph={{ rows: 4 }} />
        ) : items.length === 0 ? (
          <Empty description={t("admin.content.publication.empty", { defaultValue: "No publications yet" })} />
        ) : (
          <div className="grid gap-3">
            {items.map((pub) => (
              <ProCard key={pub.id} size="small">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Typography.Text strong className="block">
                      {pub.title_zh ? `${pub.title} / ${pub.title_zh}` : pub.title}
                    </Typography.Text>
                    <Typography.Text type="secondary" className="block text-xs">
                      {pub.authors_zh ? `${pub.authors} / ${pub.authors_zh}` : pub.authors}
                    </Typography.Text>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                      {pub.journal ? <Tag>{pub.journal}</Tag> : null}
                      {pub.year ? <Tag color="blue">{pub.year}</Tag> : null}
                      {pub.doi ? <Tag color="cyan">{pub.doi}</Tag> : null}
                      {pub.is_featured ? <Tag color="gold">{t("admin.content.publication.featured", { defaultValue: "Featured" })}</Tag> : null}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => { setEditing(fromPublication(pub)); setFormOpen(true); }}
                      aria-label={t("admin.content.edit", { defaultValue: "Edit" })}
                    />
                    <Button
                      type="text"
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => setDeleteTarget({ id: pub.id, title: pub.title })}
                      aria-label={t("admin.content.delete", { defaultValue: "Delete" })}
                    />
                  </div>
                </div>
              </ProCard>
            ))}
          </div>
        )}

        <PublicationFormDialog
          key={editing.id ?? "new"}
          open={formOpen}
          onClose={() => { setFormOpen(false); }}
          initial={editing}
          onSubmit={handleSubmit}
          loading={createMutation.isPending || updateMutation.isPending}
        />

        <ConfirmDialog
          open={Boolean(deleteTarget)}
          onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
          title={t("admin.content.publication.deleteTitle", { defaultValue: "Delete publication" })}
          description={t("admin.content.publication.deleteConfirm", { defaultValue: "Delete \"{{title}}\"? This cannot be undone.", title: deleteTarget?.title ?? "" })}
          confirmLabel={t("admin.content.delete", { defaultValue: "Delete" })}
          severity="destructive"
          loading={deleteMutation.isPending}
          onConfirm={() => { if (deleteTarget) deleteMutation.mutate(deleteTarget.id); }}
        />
      </div>
    </PageContainer>
  );
}
