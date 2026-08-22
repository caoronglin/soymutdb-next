import { Link } from "@tanstack/react-router";
import { FileArchive, FileText, ScrollText, Settings } from "lucide-react";
import { PageHeader } from "../lib/admin-ui";

const resources = [
  { to: "/imports", label: "Imports", description: "Monitor submitted data import tasks.", icon: FileArchive },
  { to: "/content", label: "Content", description: "Manage published scientific content.", icon: FileText },
  { to: "/audit", label: "Audit", description: "Inspect administrator activity and changes.", icon: ScrollText },
  { to: "/settings", label: "Settings", description: "Review system and integration settings.", icon: Settings },
] as const;

export default function ResourceCatalogPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Resource Catalog" description="A second-level map of the real admin resources." />
      <div className="rounded-xl border border-border bg-card p-5 text-sm text-muted-foreground">
        Resource management is being rebuilt around backend-backed workflows. The links below are the currently available destinations.
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {resources.map(({ to, label, description, icon: Icon }) => (
          <Link key={to} to={to} className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/50 hover:bg-accent">
            <Icon className="mb-4 size-5 text-primary" aria-hidden />
            <h2 className="font-medium text-foreground">{label}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{description}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
