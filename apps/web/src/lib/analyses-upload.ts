/**
 * useAnalysisUpload — checksum → presigned-upload → submit pipeline.
 *
 * Flow:
 *   1. Compute the SHA-256 required by the backend.
 *   2. Request a presigned multipart POST and upload it with XHR progress.
 *   3. Submit the returned object keys as an analysis job.
 *
 * Total progress is a size-weighted average across files. Any failure aborts
 * the pipeline and surfaces a toast + `error` state.
 */

import * as React from "react";
import { requestUpload, submitAnalysis, type AnalysisType } from "@soymutdb/api-client";
import { useToast } from "./toast";
import { IncrementalSha256, SHA256_CHUNK_BYTES } from "./incremental-sha256";

export type UploadPhase = "idle" | "uploading" | "submitting" | "done";

export interface AnalysisUploadState {
  phase: UploadPhase;
  /** Overall progress 0–100 (size-weighted across files). */
  progress: number;
  error: string | null;
}

export const MAX_ANALYSIS_FILE_BYTES = 500 * 1024 * 1024;

const SHA256_HEX_PATTERN = /^[0-9a-f]{64}$/;

function clampRatio(ratio: number): number {
  if (!Number.isFinite(ratio)) return 0;
  return Math.min(1, Math.max(0, ratio));
}

/**
 * Hash a File in bounded chunks so a browser never materializes the whole
 * server-accepted upload in JavaScript memory. The resulting lowercase hex
 * digest remains the value bound into the signed POST policy and checked by
 * object storage + the API at submission.
 */
export async function calculateFileSha256(file: File): Promise<string> {
  if (file.size > MAX_ANALYSIS_FILE_BYTES) {
    throw new Error(`File "${file.name}" exceeds the 500 MiB upload limit.`);
  }

  try {
    const hasher = new IncrementalSha256();
    for (let offset = 0; offset < file.size; offset += SHA256_CHUNK_BYTES) {
      const chunk = file.slice(offset, Math.min(offset + SHA256_CHUNK_BYTES, file.size));
      hasher.update(new Uint8Array(await chunk.arrayBuffer()));
    }
    const checksum = hasher.digestHex();

    if (!SHA256_HEX_PATTERN.test(checksum)) {
      throw new Error("Incremental SHA-256 returned an invalid digest");
    }
    return checksum;
  } catch (error) {
    const detail = error instanceof Error ? `: ${error.message}` : "";
    throw new Error(`Unable to calculate SHA-256 for "${file.name}"${detail}`, {
      cause: error,
    });
  }
}

/** Multipart POST with upload progress. The browser supplies the boundary. */
export function postWithProgress(
  url: string,
  uploadMethod: unknown,
  uploadFields: Record<string, string> | undefined,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<void> {
  if (uploadMethod !== "POST") {
    return Promise.reject(
      new Error(
        `Unsupported analysis upload method "${String(uploadMethod)}"; expected POST.`,
      ),
    );
  }

  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [name, value] of Object.entries(uploadFields ?? {})) {
      form.append(name, value);
    }
    // S3-compatible presigned POSTs require the binary part after all policy fields.
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      // loaded/total both include multipart framing; map that ratio onto the
      // logical file size later instead of comparing loaded with File.size.
      if (e.lengthComputable && e.total > 0) {
        onProgress(clampRatio(e.loaded / e.total));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(`Upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed — network error"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(form);
  });
}

export function calculateUploadProgress(input: {
  completedBytes: number;
  totalBytes: number;
  currentFileBytes: number;
  currentFileRatio: number;
  completedFiles: number;
  totalFiles: number;
}): number {
  const currentRatio = clampRatio(input.currentFileRatio);
  let ratio: number;

  if (input.totalBytes > 0) {
    ratio =
      (Math.max(0, input.completedBytes) +
        Math.max(0, input.currentFileBytes) * currentRatio) /
      input.totalBytes;
  } else if (input.totalFiles > 0) {
    // All files are empty: use completion count so progress remains finite.
    ratio = (Math.max(0, input.completedFiles) + currentRatio) / input.totalFiles;
  } else {
    return 0;
  }

  return Math.min(99, Math.max(0, Math.round(clampRatio(ratio) * 100)));
}

export function useAnalysisUpload(opts: {
  type: AnalysisType;
  onSubmitted: (jobId: string) => void;
}) {
  const { type, onSubmitted } = opts;
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
      let uploadedFiles = 0;

      try {
        // Hash sequentially so peak JavaScript memory remains bounded to one
        // fixed-size file slice while preserving the upload integrity contract.
        const checksums: string[] = [];
        for (const file of files) {
          checksums.push(await calculateFileSha256(file));
        }

        // Presign every file before any object-store bytes move.
        const presigned = await Promise.all(
          files.map((f, index) =>
            requestUpload(
              f.name,
              f.size,
              checksums[index]!,
              f.type || undefined,
            ).then((res) => ({
              file: f,
              uploadUrl: res.upload_url,
              uploadMethod: res.upload_method,
              uploadFields: res.upload_fields,
              objectKey: res.object_key,
            })),
          ),
        );

        // Upload sequentially, tracking logical bytes rather than multipart bytes.
        const objectKeys: string[] = [];
        for (const item of presigned) {
          await postWithProgress(
            item.uploadUrl,
            item.uploadMethod,
            item.uploadFields,
            item.file,
            (ratio) => {
              setState((s) => {
                return {
                  ...s,
                  progress: calculateUploadProgress({
                    completedBytes: uploadedBytes,
                    totalBytes,
                    currentFileBytes: item.file.size,
                    currentFileRatio: ratio,
                    completedFiles: uploadedFiles,
                    totalFiles: files.length,
                  }),
                };
              });
            },
          );
          uploadedBytes += item.file.size;
          uploadedFiles += 1;
          objectKeys.push(item.objectKey);
        }

        // Submit only after every object-store POST succeeds.
        setState({ phase: "submitting", progress: 100, error: null });
        const res = await submitAnalysis(type, {
          inputObjects: objectKeys,
          params,
        });
        setState({ phase: "done", progress: 100, error: null });
        onSubmitted(res.job_id);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Analysis submission failed";
        setState({ phase: "idle", progress: 0, error: message });
        toastError("Submission failed", message);
      }
    },
    [type, onSubmitted, toastError],
  );

  return { ...state, busy, uploadFiles, reset };
}
