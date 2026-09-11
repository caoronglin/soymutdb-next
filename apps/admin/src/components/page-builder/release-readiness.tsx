export type SchemaReadiness = "not-run" | "valid" | "invalid";

export interface ReleaseReadinessProps {
  schema: SchemaReadiness;
  responsiveReviewed: boolean;
  unsavedChanges: boolean;
  pluginWarning?: string | null;
  pluginStatuses?: Array<{ key: string; available: boolean; reason: string | null }>;
  pluginStatusUnavailable?: boolean;
  onResponsiveReviewedChange: (reviewed: boolean) => void;
}

interface Check {
  label: string;
  detail: string;
  state: "pass" | "warn" | "fail";
}

function CheckRow({ check }: { check: Check }) {
  const symbol = check.state === "pass" ? "✓" : check.state === "warn" ? "⚠" : "✗";
  const color = check.state === "pass" ? "text-primary" : check.state === "warn" ? "text-amber-700" : "text-destructive";
  return (
    <li className="flex gap-2">
      <span className={color} aria-hidden="true">{symbol}</span>
      <span><span className="font-medium">{check.label}</span><span className="text-muted-foreground"> — {check.detail}</span></span>
    </li>
  );
}

/** Shows advisory publication gates without changing the server publish contract. */
export function ReleaseReadiness({ schema, responsiveReviewed, unsavedChanges, pluginWarning, pluginStatuses = [], pluginStatusUnavailable = false, onResponsiveReviewedChange }: ReleaseReadinessProps) {
  const schemaCheck: Check = schema === "valid"
    ? { state: "pass", label: "Component schema", detail: "latest preview validation passed" }
    : schema === "invalid"
      ? { state: "fail", label: "Component schema", detail: "latest preview validation failed" }
      : { state: "warn", label: "Component schema", detail: "run Preview to validate this draft" };
  const responsiveCheck: Check = responsiveReviewed
    ? { state: "pass", label: "Responsive layouts", detail: "desktop, tablet, and mobile layouts reviewed" }
    : { state: "warn", label: "Responsive layouts", detail: "review all three layouts before publishing" };
  const draftCheck: Check = unsavedChanges
    ? { state: "fail", label: "Draft state", detail: "save current changes before publishing" }
    : { state: "pass", label: "Draft state", detail: "no unsaved local changes" };
  return (
    <section className="rounded-lg border border-border bg-muted/20 p-4" aria-labelledby="release-readiness-title">
      <h3 id="release-readiness-title" className="text-sm font-semibold">Release readiness</h3>
      <p className="mt-1 text-sm text-muted-foreground">These checks help catch common publication issues; server-side validation remains authoritative.</p>
      <ul className="mt-3 space-y-2 text-sm" aria-live="polite">
        <CheckRow check={schemaCheck} />
        <CheckRow check={responsiveCheck} />
        {pluginStatuses.map((plugin) => <CheckRow key={plugin.key} check={{ state: plugin.available ? "pass" : "warn", label: `Plugin ${plugin.key}`, detail: plugin.available ? "authoritative capability check passed" : plugin.reason ?? "unavailable" }} />)}
        {pluginStatusUnavailable && pluginStatuses.length === 0 ? <CheckRow check={{ state: "warn", label: "Plugin launcher", detail: "authoritative plugin status is unavailable; publish will validate" }} /> : null}
        {pluginWarning ? <CheckRow check={{ state: "warn", label: "Plugin launcher", detail: pluginWarning }} /> : null}
        <CheckRow check={draftCheck} />
      </ul>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={responsiveReviewed} onChange={(event) => onResponsiveReviewedChange(event.target.checked)} />
        I reviewed desktop, tablet, and mobile layouts
      </label>
    </section>
  );
}
