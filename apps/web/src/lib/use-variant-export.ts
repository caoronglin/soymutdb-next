/**
 * Variant export lifecycle for the portal.
 *
 * One owner for the submit → poll → download chain. The portal offers the
 * chain in more than one place (the variants workspace and the downloads
 * catalogue), and a second copy of this logic would be a second place where
 * the ownership rules drift: an export belongs to the account that requested
 * it, a finished artifact is downloaded through a short-lived signed link,
 * and a late response must never be applied to a different session.
 *
 * The rules implemented here:
 *
 * - The submitted export is a server-side record. Its state is polled, not
 *   guessed, and the polling stops as soon as the record reaches a final
 *   state — or the lookup fails, which means the record is gone or belongs
 *   to another account.
 * - Every response is tagged with the session that requested it. A logout, an
 *   expiry or an account switch invalidates the in-flight work: the portal
 *   must not keep showing, polling or downloading the previous account's
 *   export.
 * - The download link is fetched on demand and opened immediately. It is
 *   short-lived, so it is never cached or reused across sessions.
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  createVariantExport,
  getVariantExportDownload,
  getVariantExportStatus,
} from "@soymutdb/api-client";
import { queryKeys } from "../lib/query-keys";
import { useSession } from "./session-context";

/** The artifact formats the export endpoint accepts. */
export type VariantExportFormat = "tsv" | "vcf" | "csv" | "json" | "bed";

/**
 * How long the portal keeps polling an export that has not reached a final
 * state.
 *
 * An export is a background job; a large one legitimately takes a while. But
 * polling forever hides a stuck record behind an endless "preparing" line, so
 * the portal stops after this window and offers an explicit re-check instead.
 */
const EXPORT_POLL_DEADLINE_MS = 10 * 60 * 1000;

/**
 * The filter fields the export endpoint understands.
 *
 * The values are the ones the API documents; `undefined` entries are removed
 * by the client before the request is sent, so a filter the user did not set
 * cannot narrow the artifact by accident.
 */
export interface VariantExportFilters {
  assembly?: string;
  chromosome?: string;
  impact?: string;
  variant_type?: string;
  mutant_line_public_id?: string;
  limit?: number;
}

type VariantExportSubmitState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; message: string }
  | { status: "error"; message: string };

interface UseVariantExportOptions {
  /**
   * The single assembly namespace the artifact is built from.
   *
   * The endpoint refuses a request that cannot be bound to exactly one
   * assembly, so an empty value disables the submission rather than sending
   * a request that would mix namespaces.
   */
  assemblyKey: string;
  /** The filters the artifact is built from. */
  filters?: VariantExportFilters;
  /** Artifact format; defaults to the tab-separated variant table. */
  format?: VariantExportFormat;
  /** Whether the artifact is compressed; defaults to true. */
  compress?: boolean;
  /** The message shown when the download link could not be fetched. */
  downloadErrorFallback?: string;
  /**
   * How long the automatic polling may continue, in milliseconds.
   *
   * The default is ten minutes; the override exists so the behaviour can be
   * exercised without waiting ten minutes.
   */
  pollDeadlineMs?: number;
}

interface UseVariantExportResult {
  /** The state of the submission request itself. */
  submitState: VariantExportSubmitState;
  /** The id of the submitted export record, if one was accepted. */
  exportId: string | undefined;
  /** The state of the export record on the server. */
  exportStatus: string | undefined;
  /** Why the export failed, when the server said so. */
  exportErrorMessage: string | null | undefined;
  /** Why the download link could not be fetched. */
  downloadError: string | undefined;
  /**
   * True when the export has not reached a final state within the polling
   * window: the portal stopped polling and waits for an explicit re-check.
   */
  pollExpired: boolean;
  /** Submit an export. Resolves when the request was accepted or refused. */
  requestExport: () => Promise<void>;
  /** Fetch and open the signed download link of a finished export. */
  downloadExport: () => Promise<void>;
  /**
   * Ask the server for the export's state once more.
   *
   * Used after the polling window closed: the portal stopped polling, and
   * the visitor decides whether to look again instead of the page doing it
   * forever.
   */
  checkAgain: () => void;
}

export function useVariantExport({
  assemblyKey,
  filters,
  format = "tsv",
  compress = true,
  downloadErrorFallback = "The export could not be downloaded",
  pollDeadlineMs = EXPORT_POLL_DEADLINE_MS,
}: UseVariantExportOptions): UseVariantExportResult {
  const { sessionId, status: sessionStatus } = useSession();
  const [submitState, setSubmitState] = React.useState<VariantExportSubmitState>({ status: "idle" });
  const [exportId, setExportId] = React.useState<string | undefined>(undefined);
  const [downloadError, setDownloadError] = React.useState<string | undefined>(undefined);
  const [pollExpired, setPollExpired] = React.useState(false);
  // Logout/expiry deliberately do not increment sessionId. Both dimensions
  // define ownership; in-flight continuations must also respect this boundary.
  const exportScope = `${sessionId}:${sessionStatus}`;
  const lastSessionRef = React.useRef(exportScope);
  const requestVersion = React.useRef(0);
  // When the accepted export was submitted. It bounds the automatic polling:
  // a record that never reaches a final state must not keep the portal
  // polling forever.
  const submittedAtRef = React.useRef<number | null>(null);

  const exportStatusQuery = useQuery({
    queryKey: queryKeys.variants.export(exportId ?? null, sessionId),
    queryFn: () => getVariantExportStatus(exportId as string),
    enabled: Boolean(exportId) && sessionStatus === "authenticated"
      && lastSessionRef.current === exportScope,
    // Poll only while the export is still in flight; a final state — or a
    // failed lookup (the record is gone, or it belongs to another account)
    // — stops the polling.
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (query.state.status === "error") return false;
      if (status === "succeeded" || status === "failed") return false;
      if (
        submittedAtRef.current !== null
        && Date.now() - submittedAtRef.current > pollDeadlineMs
      ) {
        return false;
      }
      return 3000;
    },
    retry: false,
  });
  const exportStatus = exportStatusQuery.data?.status;

  // The export record belongs to the account that requested it: when the
  // session changes, the previous account's export must stop being polled.
  React.useLayoutEffect(() => {
    if (lastSessionRef.current === exportScope) return;
    lastSessionRef.current = exportScope;
    requestVersion.current += 1;
    setExportId(undefined);
    setSubmitState({ status: "idle" });
    setDownloadError(undefined);
    submittedAtRef.current = null;
  }, [exportScope]);

  React.useEffect(() => () => {
    // Unmount invalidates both submitted requests and pending signed links.
    requestVersion.current += 1;
  }, []);

  const requestExport = async () => {
    if (!assemblyKey) return;
    const version = ++requestVersion.current;
    const isCurrent = () => requestVersion.current === version
      && lastSessionRef.current === exportScope;
    setSubmitState({ status: "loading" });
    setExportId(undefined);
    setDownloadError(undefined);
    submittedAtRef.current = null;
    try {
      const response = (await createVariantExport({
        format,
        compress,
        filters: { ...filters, assembly: assemblyKey },
      })) as { message?: string; status?: string; export_id?: string };
      if (!isCurrent()) return;
      setExportId(response.export_id);
      submittedAtRef.current = Date.now();
      setSubmitState({
        status: "success",
        message: response.message
          ?? (response.export_id ? `Export ${response.export_id} submitted` : "Export submitted"),
      });
    } catch (error) {
      if (!isCurrent()) return;
      setSubmitState({
        status: "error",
        message: error instanceof Error ? error.message : "Export request failed",
      });
    }
  };

  const downloadExport = async () => {
    if (!exportId) return;
    const version = requestVersion.current;
    const isCurrent = () => requestVersion.current === version
      && lastSessionRef.current === exportScope;
    setDownloadError(undefined);
    try {
      const link = await getVariantExportDownload(exportId);
      if (!isCurrent()) return;
      const anchor = document.createElement("a");
      anchor.href = link.download_url;
      anchor.rel = "noopener noreferrer";
      anchor.target = "_blank";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (error) {
      if (!isCurrent()) return;
      setDownloadError(
        error instanceof Error ? error.message : downloadErrorFallback,
      );
    }
  };

  // True when the export has not reached a final state within the polling
  // window. The portal then stops polling and says so, instead of showing an
  // endless "preparing" line for a record that may never resolve.
  //
  // The window is a timer, not a value read during render: a render only
  // happens when something changed, and the deadline passing is a change the
  // visitor has to see.
  React.useEffect(() => {
    if (!exportId) {
      setPollExpired(false);
      return;
    }
    if (exportStatus === "succeeded" || exportStatus === "failed") {
      setPollExpired(false);
      return;
    }
    const submittedAt = submittedAtRef.current;
    if (submittedAt === null) return;
    const remaining = pollDeadlineMs - (Date.now() - submittedAt);
    if (remaining <= 0) {
      setPollExpired(true);
      return;
    }
    const timer = setTimeout(() => setPollExpired(true), remaining);
    return () => clearTimeout(timer);
  }, [exportId, exportStatus, pollDeadlineMs]);

  return {
    submitState,
    exportId,
    exportStatus,
    exportErrorMessage: exportStatusQuery.data?.error_message,
    downloadError,
    pollExpired,
    requestExport,
    downloadExport,
    checkAgain: () => {
      void exportStatusQuery.refetch();
    },
  };
}
