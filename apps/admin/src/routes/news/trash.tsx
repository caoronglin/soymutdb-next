import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "@tanstack/react-router";
import dayjs from "dayjs";
import { App, Button, Input, Modal, PageContainer, ProTable, Space, Tag, type ProColumns } from "../../lib/antd";
import { PRO_LIST_SHELL } from "../../components/pro-table-shell";
import { listDeletedAdminNews, purgeNews, restoreNews, type DeletedAdminNewsItem } from "@soymutdb/api-client";

const statusColor: Record<DeletedAdminNewsItem["status"], string> = { draft: "default", published: "success", archived: "warning" };

export default function NewsTrashPage() {
  const { t } = useTranslation(); const { message } = App.useApp(); const router = useRouter();
  const [items, setItems] = useState<DeletedAdminNewsItem[]>([]); const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1); const [pageSize, setPageSize] = useState(10); const [loading, setLoading] = useState(true);
  const [purging, setPurging] = useState<DeletedAdminNewsItem | null>(null); const [slug, setSlug] = useState("");
  const load = useCallback(async () => { setLoading(true); try { const data = await listDeletedAdminNews({ page, page_size: pageSize }); setItems(data.items); setTotal(data.total); } catch { message.error(t("admin.news.trash.loadError")); } finally { setLoading(false); } }, [message, page, pageSize, t]);
  useEffect(() => { void load(); }, [load]);
  const restore = (record: DeletedAdminNewsItem) => Modal.confirm({ title: t("admin.news.trash.restoreTitle"), content: t("admin.news.trash.restoreContent", { title: record.title_en }), onOk: async () => { try { await restoreNews(record.id); message.success(t("admin.news.trash.restoreSuccess")); await load(); } catch { message.error(t("admin.news.trash.restoreError")); } } });
  // Read-only list: restore and purge are explicit, confirmed actions, so no
  // column opts into ProTable's editor. Pagination stays the server-side
  // `listDeletedAdminNews({ page, page_size })` contract.
  const columns: ProColumns<DeletedAdminNewsItem>[] = [
    { title: t("admin.news.columns.id"), dataIndex: "id", width: 70, editable: false }, { title: t("admin.news.columns.title"), dataIndex: "title_en", editable: false, render: (_, r) => r.title_zh ? <>{r.title_en} / {r.title_zh}</> : r.title_en },
    { title: t("admin.news.trash.slug"), dataIndex: "slug", editable: false }, { title: t("admin.news.columns.category"), dataIndex: "category", editable: false, render: (_, r) => r.category ?? "—" },
    { title: t("admin.news.columns.status"), dataIndex: "status", editable: false, render: (_, r) => <Tag color={statusColor[r.status]}>{t(`admin.news.status.${r.status}`)}</Tag> },
    { title: t("admin.news.columns.publishedAt"), dataIndex: "published_at", editable: false, render: (_, r) => r.published_at ? dayjs(r.published_at).format("YYYY-MM-DD HH:mm") : "—" },
    { title: t("admin.news.trash.deletedAt"), dataIndex: "deleted_at", editable: false, render: (_, r) => dayjs(r.deleted_at).format("YYYY-MM-DD HH:mm") },
    { title: t("admin.news.columns.actions"), key: "actions", editable: false, render: (_, r) => <Space><Button onClick={() => restore(r)}>{t("admin.news.trash.restore")}</Button><Button danger onClick={() => { setSlug(""); setPurging(r); }}>{t("admin.news.trash.purge")}</Button></Space> },
  ];
  return <div className="route-fade-in"><PageContainer title={t("admin.news.trash.title")} extra={[<Button key="back" onClick={() => router.navigate({ to: "/news" })}>{t("admin.news.backToList")}</Button>]}><ProTable {...PRO_LIST_SHELL} rowKey="id" columns={columns} dataSource={items} loading={loading} locale={{ emptyText: t("admin.news.trash.empty") }} pagination={{ current: page, pageSize, total, onChange: (next, size) => { setPage(next); setPageSize(size); } }} /></PageContainer><Modal open={purging !== null} title={t("admin.news.trash.purgeTitle")} okButtonProps={{ danger: true, disabled: slug !== purging?.slug }} okText={t("admin.news.trash.purge")} onCancel={() => setPurging(null)} onOk={async () => { if (!purging) return; try { await purgeNews(purging.id); setPurging(null); message.success(t("admin.news.trash.purgeSuccess")); await load(); } catch { message.error(t("admin.news.trash.purgeError")); } }}><p>{t("admin.news.trash.purgeContent", { slug: purging?.slug })}</p><Input value={slug} onChange={e => setSlug(e.target.value)} placeholder={purging?.slug} aria-label={t("admin.news.trash.slug")} /></Modal></div>;
}
