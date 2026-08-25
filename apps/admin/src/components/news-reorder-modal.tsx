/**
 * Featured-order reorder modal (B3) — drag-and-drop (dnd-kit, already a
 * workspace dep) over the published articles, then PATCH /admin/news/reorder
 * with the full ordering. `featured_sort` is assigned sequentially (0-based);
 * the homepage shows the top 5.
 *
 * Note: the reorder endpoint requires every referenced id to exist (404
 * otherwise), so only rows fetched from the list are submitted.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Modal, Space, Typography } from "../lib/antd";
import { HolderOutlined, LoadingOutlined } from "@ant-design/icons";
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
import { listNews, reorderNews, type NewsSummary } from "@soymutdb/api-client";

export interface NewsReorderModalProps {
  open: boolean;
  onClose: () => void;
  /** Called after a successful reorder so the table refreshes. */
  onSaved: () => void;
}

interface SortableRowProps {
  article: NewsSummary;
}

function SortableRow({ article }: SortableRowProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: article.id });
  return (
    <li
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.6 : 1,
      }}
      className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2"
    >
      <span
        {...attributes}
        {...listeners}
        className="cursor-grab touch-none text-muted-foreground"
        aria-label="drag"
      >
        <HolderOutlined />
      </span>
      <span className="min-w-0 flex-1 truncate text-sm">
        {article.title_zh ? `${article.title_en} / ${article.title_zh}` : article.title_en}
      </span>
      <Typography.Text type="secondary" className="shrink-0 font-mono text-xs">
        #{article.featured_sort}
      </Typography.Text>
    </li>
  );
}

export function NewsReorderModal({ open, onClose, onSaved }: NewsReorderModalProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [articles, setArticles] = useState<NewsSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 4 } }));

  useEffect(() => {
    if (!open) return;
    let disposed = false;
    setLoading(true);
    listNews(undefined, 1, 200)
      .then((res) => {
        if (!disposed) setArticles(res.items);
      })
      .catch(() => {
        /* keep empty list — modal shows the empty hint */
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [open]);

  const onDragEnd = useCallback((event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setArticles((prev) => {
      const from = prev.findIndex((a) => a.id === active.id);
      const to = prev.findIndex((a) => a.id === over.id);
      if (from < 0 || to < 0) return prev;
      return arrayMove(prev, from, to);
    });
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    try {
      await reorderNews(
        articles.map((article, index) => ({
          id: Number(article.id),
          featured_sort: index,
        })),
      );
      message.success(t("admin.news.messages.reorderSuccess"));
      onSaved();
      onClose();
    } catch (err) {
      message.error(
        `${t("admin.news.messages.reorderError")}: ${err instanceof Error ? err.message : String(err)}`,
      );
    } finally {
      setSaving(false);
    }
  }, [articles, message, t, onSaved, onClose]);

  return (
    <Modal
      open={open}
      title={t("admin.news.reorder.title")}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>{t("admin.news.form.cancel")}</Button>
          <Button type="primary" loading={saving} disabled={articles.length === 0} onClick={save}>
            {t("admin.news.reorder.save")}
          </Button>
        </Space>
      }
    >
      <Alert type="info" showIcon message={t("admin.news.reorder.hint")} style={{ marginBottom: 16 }} />
      {loading ? (
        <Typography.Text type="secondary">
          <LoadingOutlined /> {t("admin.news.loading")}
        </Typography.Text>
      ) : articles.length === 0 ? (
        <Typography.Text type="secondary">{t("admin.news.reorder.empty")}</Typography.Text>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
          <SortableContext items={articles.map((a) => a.id)} strategy={verticalListSortingStrategy}>
            <ul className="max-h-96 space-y-2 overflow-y-auto pr-1">
              {articles.map((article) => (
                <SortableRow key={article.id} article={article} />
              ))}
            </ul>
          </SortableContext>
        </DndContext>
      )}
    </Modal>
  );
}
