import { Link } from "@tanstack/react-router";
import { SETTINGS_DOMAIN_META, SETTINGS_DOMAINS } from "./domains";

export default function SettingsOverviewPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">Choose a domain to edit and save independently.</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        {SETTINGS_DOMAINS.map((domain) => {
          const meta = SETTINGS_DOMAIN_META[domain];
          return (
            <Link
              key={domain}
              to={("/settings/" + domain) as "/settings/site"}
              className="rounded-lg border border-border bg-card p-5 transition-colors hover:border-primary hover:bg-accent"
            >
              <h2 className="font-medium">{meta.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{meta.description}</p>
            </Link>
          );
        })}
      </div>
      <Link to="/settings/legacy" className="text-sm text-primary hover:underline">
        Open the complete settings form
      </Link>
    </div>
  );
}