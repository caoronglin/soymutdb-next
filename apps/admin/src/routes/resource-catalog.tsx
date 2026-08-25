import { FileZipOutlined, FileTextOutlined, SnippetsOutlined, SettingOutlined } from "@ant-design/icons";
import { Link } from "@tanstack/react-router";
import { Card, Typography } from "@/lib/antd";
const resources = [
  { to: "/imports", label: "Imports", description: "Monitor submitted data import tasks.", icon: FileZipOutlined },
  { to: "/content", label: "Content", description: "Manage published scientific content.", icon: FileTextOutlined },
  { to: "/audit", label: "Audit", description: "Inspect administrator activity and changes.", icon: SnippetsOutlined },
  { to: "/settings", label: "SettingOutlined", description: "Review system and integration settings.", icon: SettingOutlined },
] as const;

export default function ResourceCatalogPage() {
  return (
    <div className="space-y-6">
      <div><Typography.Title level={2}>Resource Catalog</Typography.Title><Typography.Text type="secondary">A second-level map of the real admin resources.</Typography.Text></div>
      <div className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        Resource management is being rebuilt around backend-backed workflows. The links below are the currently available destinations.
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {resources.map(({ to, label, description, icon: Icon }) => (
          <Link key={to} to={to}><Card hoverable className="group h-full">
            <Icon className="mb-4 size-5 text-primary" aria-hidden />
            <h2 className="font-medium text-foreground">{label}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </Card></Link>
        ))}
      </div>
    </div>
  );
}
