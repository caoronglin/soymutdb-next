import { FileZipOutlined, FileTextOutlined, SnippetsOutlined, SettingOutlined } from "@ant-design/icons";
import { Link } from "@tanstack/react-router";
import { Card, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
const resources = [
  { to: "/imports", label: "Imports", description: "Monitor submitted data import tasks.", icon: FileZipOutlined },
  { to: "/content", label: "Content", description: "Manage published scientific content.", icon: FileTextOutlined },
  { to: "/audit", label: "Audit", description: "Inspect administrator activity and changes.", icon: SnippetsOutlined },
  { to: "/settings", label: "Settings", description: "Review system and integration settings.", icon: SettingOutlined },
] as const;

export default function ResourceCatalogPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>{t("admin.ops.resourceCatalogTitle", { defaultValue: "Resource Catalog" })}</Typography.Title><Typography.Text type="secondary">{t("admin.ops.resourceCatalogSubtitle", { defaultValue: "A second-level map of the real admin resources." })}</Typography.Text></div>
      <div className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        {t("admin.ops.resourceCatalogNote", { defaultValue: "Resource management is being rebuilt around backend-backed workflows. The links below are the currently available destinations." })}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {resources.map(({ to, label, description, icon: Icon }) => {
          const resourceId = to.replace(/\//g, "");
          const resourceLabel = t(`admin.ops.catalog_${resourceId}_label`, { defaultValue: label });
          const resourceDesc = t(`admin.ops.catalog_${resourceId}_desc`, { defaultValue: description });
          return (
          <Link key={to} to={to}><Card hoverable className="group h-full">
            <Icon className="mb-4 size-5 text-primary" aria-hidden />
            <h2 className="font-medium text-foreground">{resourceLabel}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{resourceDesc}</p>
          </Card></Link>
          );
        })}
      </div>
    </div>
  );
}
