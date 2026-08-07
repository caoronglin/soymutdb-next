/**
 * useAnalysisUpload — presigned-upload → submit pipeline for analysis jobs.
 *
 * Flow (per Wave 1 contract, implemented in W3-A's api-client `analyses.ts`):
 *   1. `requestUpload(filename, size)` → `{ upload_url, object_key }`
 *   2. binary PUT straight to MinIO via the presigned URL (XHR for progress;
 *      no custom headers so the presign signature stays valid), then
 *   3. `submitAnalysis(type, { inputObjects, params })` → `{ job_id }`.
 *
 * Total progress is a size-weighted average across files. Any failure aborts
 * the pipeline and surfaces a toast + `error` state.
 */

import * as React from "react";
import { requestUpload, submitAnalysis, type AnalysisType } from "@soymutdb/api-client";
import { useToast } from "@soymutdb/ui";
import { recordRecentJob } from "./analyses-local";

export type UploadPhase = "idle" | "uploading" | "submitting" | "done";

export interface AnalysisUploadState {
  phase: UploadPhase;
  /** Overall progress 0–100 (size-weighted across files). */
  progress: number;
  error: string | null;
}

/** Binary PUT with upload progress. No custom headers (keeps presign valid). */
function putWithProgress(
  url: string,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new Error(`Upload failed (HTTP ${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload failed — network error"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(file);
  });
}

export function useAnalysisUpload(opts: {
  type: AnalysisType;
  onSubmitted: (jobId: string) => void;
}) {
  const { error: toastError } = useToast();
  const [state, setState] = React.useState<AnalysisUploadState>({
    phase: "idle",
    progress: 0,
    error: null,
  });
  const busy = state.phase === "uploading" || state.phase === "submitting";

  const reset = React.useCallback(() => {
    setState({ phase: "idle", progress: 0, error: null });
  }, []);

  const uploadFiles = React.useCallback(
    async (files: File[], params: Record<string, unknown>) => {
      if (files.length === 0) {
        setState((s) => ({ ...s, error: "Select at least one file first." }));
        return;
      }
      setState({ phase: "uploading", progress: 0, error: null });
      const totalBytes = files.reduce((sum, f) => sum + f.size, 0);
      let uploadedBytes = 0;

      try {
        // 1. Presign every file first (fail fast before any bytes move).
        const presigned = await Promise.all(
          files.map((f) =>
            requestUpload(f.name, f.size, f.type || undefined).then((res) => ({
              file: f,
              uploadUrl: res.upload_url,
              objectKey: res.object_key,
            })),
          ),
        );

        // 2. Upload each file straight to MinIO, tracking size-weighted progress.
        const objectKeys: string[] = [];
        for (const item of presigned) {
          await putWithProgress(item.uploadUrl, item.file, (ratio) => {
            setState((s) => {
              const current = uploadedBytes + item.file.size * ratio;
              return {
                ...s,
                progress: Math.min(99, Math.round((current / totalBytes) * 100)),
              };
            });
          });
          uploadedBytes += item.file.size;
          objectKeys.push(item.objectKey);
        }

        // 3. Submit the job.
        setState({ phase: "submitting", progress: 100, error: null });
        const res = await submitAnalysis(opts.type, {
          inputObjects: objectKeys,
          params,
        });
        recordRecentJob(res.job_id);
        setState({ phase: "done", progress: 100, error: null });
        opts.onSubmitted(res.job_id);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Analysis submission failed";
        setState({ phase: "idle", progress: 0, error: message });
        toastError("Submission failed", message);
      }
    },
    [opts.type, opts.onSubmitted, toastError],
  );

  return { ...state, busy, uploadFiles, reset };
}
