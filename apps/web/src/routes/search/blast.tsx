/**
 * BLAST — compatibility redirect to the full form at /blast.
 *
 * The default/tool entry now points directly at /blast (Phase 4). This
 * /search/blast route is kept as a redirect so existing links keep working
 * instead of breaking.
 */
import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/search/blast")({
  beforeLoad: () => {
    throw redirect({ to: "/blast", replace: true });
  },
});
