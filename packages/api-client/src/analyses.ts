/**
 * Typed analyses endpoints (fastp / scanpy pipelines).
 *
 * Every endpoint requires the researcher role or higher — these calls go
 * through the coordinated `http` layer (Bearer auth, refresh-on-401).
 *
 * All types come from the generated OpenAPI schema
 * (`./generated/openapi.d.ts`) — regenerate via
 * `pnpm --filter @soymutdb/api-client generate:api-client` after backend
 * contract changes.
 */

import type { components } from "./generated/openapi";
import { http } from "./auth";

export type AnalysisType = components["schemas"]["AnalysisType"];
export type AnalysisJobStatus = components["schemas"]["AnalysisJobStatus"];
export type AnalysesUploadRequest = components["schemas"]["AnalysesUploadRequest"];
export type AnalysesUploadResponse = components["schemas"]["AnalysesUploadResponse"];
export type AnalysesSubmitRequest = components["schemas"]["AnalysesSubmitRequest"];
export type AnalysesSubmitResponse = components["schemas"]["AnalysesSubmitResponse"];
export type AnalysesJobResponse = components["schemas"]["AnalysesJobResponse"];
export type AnalysesDownloadResponse = components["schemas"]["AnalysesDownloadResponse"];

const SHA256_HEX_PATTERN = /^[0-9a-f]{64}$/;

/**
 * Request a pre-signed multipart POST for an analysis input file.
 *
 * Returns the URL and form fields to upload to plus the `object_key` that
 * must be sent back at submit time. Nothing is persisted server-side yet.
 */
export function requestUpload(
  filename: string,
  size: number,
  checksumSha256: string,
  contentType?: string,
): Promise<AnalysesUploadResponse> {
  if (!SHA256_HEX_PATTERN.test(checksumSha256)) {
    return Promise.reject(
      new TypeError("checksumSha256 must be 64 lowercase hexadecimal characters"),
    );
  }

  const body: AnalysesUploadRequest = {
    filename,
    size,
    checksum_sha256: checksumSha256,
  };
  if (contentType !== undefined) body.content_type = contentType;
  return http.post<AnalysesUploadResponse>("/analyses/uploads", { json: body });
}

/**
 * Submit an analysis job for previously uploaded object keys.
 *
 * @param type Pipeline to run ("fastp" | "scanpy").
 * @param input.inputObjects Object keys returned by `requestUpload`.
 * @param input.params Pipeline parameters (whitelisted server-side).
 */
export function submitAnalysis(
  type: AnalysisType,
  input: { inputObjects: string[]; params?: Record<string, unknown> },
): Promise<AnalysesSubmitResponse> {
  const body: AnalysesSubmitRequest = {
    input_objects: input.inputObjects,
    params: input.params ?? {},
  };
  return http.post<AnalysesSubmitResponse>(`/analyses/${type}/submit`, {
    json: body,
  });
}

/** Return the current status (+ worker-written result when complete) of an analysis job. */
export function getAnalysis(jobId: string): Promise<AnalysesJobResponse> {
  return http.get<AnalysesJobResponse>(`/analyses/${jobId}`);
}

/**
 * Return a pre-signed GET URL for one of the job's own objects.
 *
 * The key must live under `analyses/{job_id}/`; anything outside that prefix
 * (including other jobs' objects) is rejected server-side.
 */
export function getAnalysisDownload(
  jobId: string,
  objectKey: string,
): Promise<AnalysesDownloadResponse> {
  return http.get<AnalysesDownloadResponse>(`/analyses/${jobId}/download`, {
    params: { object_key: objectKey },
  });
}
