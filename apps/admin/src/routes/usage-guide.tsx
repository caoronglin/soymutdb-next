import { useTranslation } from "react-i18next";
import { PageContainer } from "@/lib/antd";
import { AdminUsageGuide } from "../components/admin-usage-guide";
import type { AdminUsageGuideItem } from "../components/admin-usage-guide";

export default function UsageGuidePage() {
  const { t } = useTranslation();
  const items: AdminUsageGuideItem[] = [
    {
      key: "workflow",
      title: t("admin.usage.workflowTitle", { defaultValue: "Standard admin workflow" }),
      steps: [t("admin.usage.workflowStep1"), t("admin.usage.workflowStep2"), t("admin.usage.workflowStep3"), t("admin.usage.workflowStep4")],
      api: ["POST /auth/refresh", "GET|PUT /api/v1/admin/*"],
      tables: ["users", "audit_logs"],
      note: t("admin.usage.workflowNote"),
    },
    {
      key: "content",
      title: t("admin.usage.contentTitle", { defaultValue: "Content and publication workflow" }),
      steps: [t("admin.usage.contentStep1"), t("admin.usage.contentStep2"), t("admin.usage.contentStep3"), t("admin.usage.contentStep4")],
      api: ["GET|POST|PUT /admin/content/pages", "GET|POST|PUT|DELETE /admin/publications", "GET /content/snapshot"],
      tables: ["static_pages", "content_versions", "publications"],
      note: t("admin.usage.contentNote"),
    },
    {
      key: "data",
      title: t("admin.usage.dataTitle", { defaultValue: "Import, validation, and release workflow" }),
      steps: [t("admin.usage.dataStep1"), t("admin.usage.dataStep2"), t("admin.usage.dataStep3"), t("admin.usage.dataStep4")],
      api: ["POST /admin/imports", "POST /admin/releases", "POST /admin/releases/{id}/publish"],
      tables: ["import_tasks", "data_sets", "releases", "release_data_sets"],
      note: t("admin.usage.dataNote"),
    },
    {
      key: "performance",
      title: t("admin.usage.performanceTitle", { defaultValue: "Performance and failure boundaries" }),
      steps: [t("admin.usage.performanceStep1"), t("admin.usage.performanceStep2"), t("admin.usage.performanceStep3"), t("admin.usage.performanceStep4")],
      api: ["GET /admin/dashboard-*", "GET /admin/widgets/health"],
      tables: ["PostgreSQL indexes", "Redis widget cache"],
      note: t("admin.usage.performanceNote"),
    },
  ];
  return (
    <PageContainer title={t("admin.usage.title", { defaultValue: "Usage guide" })} subTitle={t("admin.usage.description")}>
      <AdminUsageGuide items={items} />
    </PageContainer>
  );
}
