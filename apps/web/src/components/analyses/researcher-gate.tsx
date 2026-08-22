/**
 * ResearcherGate — route-level permission guard for the analyses module.
 *
 * Analyses endpoints require the researcher role or higher, so non-researcher
 * sessions render a "research access required" empty state instead of hiding
 * the routes (the routes stay crawlable/visible; only the content is gated).
 */

import * as React from "react";
import { Link } from "@tanstack/react-router";
import { ShieldAlert, LogIn } from "lucide-react";
import { LoadingState, EmptyState, Button } from "../../lib/web-ui";
import { useIsResearcher } from "../../lib/use-current-user";

export function ResearcherGate({ children }: { children: React.ReactNode }) {
  const { isResearcher, isLoading } = useIsResearcher();

  if (isLoading) {
    return <LoadingState label="Checking access…" variant="spinner" className="py-20" />;
  }

  if (!isResearcher) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Research access required"
        description="The Analyze module runs fastp / scanpy pipelines and is available to researcher accounts and above. Sign in with a researcher account to submit analysis jobs."
        action={
          <div className="flex flex-wrap items-center justify-center gap-3">
            <Button asChild size="sm">
              <Link to="/login">
                <LogIn className="size-4" aria-hidden />
                Sign in
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to="/">Back to home</Link>
            </Button>
          </div>
        }
      />
    );
  }

  return <>{children}</>;
}
