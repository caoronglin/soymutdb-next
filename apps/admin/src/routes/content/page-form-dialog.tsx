import { SaveOutlined } from "@ant-design/icons";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Input, Modal, Select, Typography } from "@/lib/antd";
import type { PageFormDialogProps, PageFormValues, PageStatus, StaticPage } from "./pages-tab";

function getErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (err instanceof Error) return err.message;
  return t("admin.content.unknownError", { defaultValue: "An unknown error occurred" });
}

export function initPageFormValues(editing: StaticPage | null): PageFormValues {
  if (editing) {
    return { slug: editing.slug, title_en: editing.title_en, title_zh: editing.title_zh ?? "", content_en: editing.content_en, content_zh: editing.content_zh ?? "", summary: editing.summary ?? "", category: editing.category ?? "", sort_order: String(editing.sort_order ?? 0), status: editing.status === "published" ? "published" : "draft", edit_comment: "" };
  }
  return { slug: "", title_en: "", title_zh: "", content_en: "", content_zh: "", summary: "", category: "", sort_order: "0", status: "draft", edit_comment: "" };
}

export function PageFormDialog({
  editing,
  open,
  onOpenChange,
  onSubmit,
  loading,
  error,
}: PageFormDialogProps) {
  const { t } = useTranslation();
  const isEdit = editing !== null;
  const [values, setValues] = React.useState<PageFormValues>(() =>
    initPageFormValues(editing),
  );

  React.useEffect(() => {
    if (open) {
      setValues(initPageFormValues(editing));
    }
  }, [editing, open]);

  const setField = <K extends keyof PageFormValues>(
    key: K,
    val: PageFormValues[K],
  ) => {
    setValues((prev) => ({ ...prev, [key]: val }));
  };

  const canSubmit =
    values.title_en.trim() !== "" &&
    values.slug.trim() !== "" &&
    values.content_en.trim() !== "" &&
    !loading;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(values);
  };

  return (
    <Modal open={open} onCancel={() => onOpenChange(false)}>
      <div className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <div>
          <Typography.Title level={5}>{isEdit ? t("admin.content.editPageTitle", { defaultValue: "Edit Page" }) : t("admin.content.newPage", { defaultValue: "New Page" })}</Typography.Title>
          <Typography.Text type="secondary">
            {isEdit
              ? t("admin.content.editPageDesc", { defaultValue: 'Editing "{{title}}". Bilingual content (EN/ZH) supported.', title: editing?.title_en })
              : t("admin.content.newPageDesc", { defaultValue: "Create a new static page. Bilingual content (EN/ZH) supported." })}
          </Typography.Text>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-title-en">{t("admin.content.labelTitleEnglish", { defaultValue: "Title (English) *" })}</label>
              <Input
                id="page-title-en"
                value={values.title_en}
                onChange={(e) => setField("title_en", e.target.value)}
                placeholder={t("admin.content.placeholderTitleEnglish", { defaultValue: "Page title in English" })}
                required
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-title-zh">{t("admin.content.labelTitleChinese", { defaultValue: "Title (Chinese)" })}</label>
              <Input
                id="page-title-zh"
                value={values.title_zh}
                onChange={(e) => setField("title_zh", e.target.value)}
                placeholder="页面标题（中文）"
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-slug">{t("admin.content.labelSlug", { defaultValue: "Slug *" })}</label>
              <Input
                id="page-slug"
                value={values.slug}
                onChange={(e) => setField("slug", e.target.value)}
                placeholder="about-us"
                disabled={isEdit}
                required
              />
              {isEdit ? (
                <p className="text-xs text-muted-foreground">
                  {t("admin.content.slugReadonlyHint", { defaultValue: "Slug cannot be changed after creation." })}
                </p>
              ) : null}
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-category">{t("admin.content.labelCategory", { defaultValue: "Category" })}</label>
              <Input
                id="page-category"
                value={values.category}
                onChange={(e) => setField("category", e.target.value)}
                placeholder={t("admin.content.placeholderCategory", { defaultValue: "about, help, etc." })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="page-sort">{t("admin.content.labelSortOrder", { defaultValue: "Sort Order" })}</label>
              <Input
                id="page-sort"
                type="number"
                value={values.sort_order}
                onChange={(e) => setField("sort_order", e.target.value)}
                placeholder="0"
              />
            </div>
            {!isEdit ? (
              <div className="space-y-1.5">
                <label htmlFor="page-status">{t("admin.content.labelStatus", { defaultValue: "Status" })}</label>
                <Select
                  value={values.status}
                  onChange={(v) => setField("status", v as PageStatus)}
                >


                    <Select.Option value="draft">{t("admin.content.statusDraft", { defaultValue: "Draft" })}</Select.Option>
                    <Select.Option value="published">{t("admin.content.statusPublished", { defaultValue: "Published" })}</Select.Option>

                </Select>
              </div>
            ) : null}
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-summary">{t("admin.content.labelSummary", { defaultValue: "Summary" })}</label>
              <Input
                id="page-summary"
                value={values.summary}
                onChange={(e) => setField("summary", e.target.value)}
                placeholder={t("admin.content.placeholderSummary", { defaultValue: "Short summary for listings" })}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-content-en">{t("admin.content.labelContentEnglish", { defaultValue: "Content (English) *" })}</label>
              <Input.TextArea
                id="page-content-en"
                value={values.content_en}
                onChange={(e) => setField("content_en", e.target.value)}
                placeholder={t("admin.content.placeholderContentEnglish", { defaultValue: "Page content in English (Markdown supported)" })}
                className="min-h-[160px] font-mono text-sm"
                required
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-content-zh">{t("admin.content.labelContentChinese", { defaultValue: "Content (Chinese)" })}</label>
              <Input.TextArea
                id="page-content-zh"
                value={values.content_zh}
                onChange={(e) => setField("content_zh", e.target.value)}
                placeholder="页面内容（中文）"
                className="min-h-[160px] font-mono text-sm"
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label htmlFor="page-comment">{t("admin.content.labelEditComment", { defaultValue: "Edit Comment" })}</label>
              <Input
                id="page-comment"
                value={values.edit_comment}
                onChange={(e) => setField("edit_comment", e.target.value)}
                placeholder={
                  isEdit ? t("admin.content.placeholderDescribeRevision", { defaultValue: "Describe this revision" }) : t("admin.content.placeholderInitialVersionNote", { defaultValue: "Initial version note" })
                }
              />
              <p className="text-xs text-muted-foreground">
                {t("admin.content.editCommentHelp", { defaultValue: "Saved with the version history for tracking changes." })}
              </p>
            </div>
          </div>

          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {getErrorMessage(error, t)}
            </p>
          ) : null}

          <div>
            <Button
              type="default"
              onClick={() => onOpenChange(false)}
              disabled={loading}
            >
              {t("admin.content.cancel", { defaultValue: "Cancel" })}
            </Button>
            <Button htmlType="submit" disabled={!canSubmit}>
              {loading ? (
                t("admin.content.saving", { defaultValue: "Saving…" })
              ) : (
                <>
                  <SaveOutlined className="size-4" />
                  {isEdit ? t("admin.content.saveOutlinedChanges", { defaultValue: "Save Changes" }) : t("admin.content.createPage", { defaultValue: "Create Page" })}
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </Modal>
  );
}
