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
import {
  calculateFileSha256,
  calculateUploadProgress,
  postWithProgress,
} from "@soymutdb/shared/analyses-upload";
import { recordRecentJob } from "@soymutdb/shared/analyses-local";
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
    // The snapshot declares this field as always present (`default: null`), so
    // an omitted content type goes on the wire as an explicit null.
    content_type: contentType ?? null,
  };
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

/**
 * Checksum → presign → upload → submit pipeline for one analysis job.
 *
 * The pure hashing/upload helpers live in `@soymutdb/shared/analyses-upload`;
 * the orchestration lives here because it is the module that owns both the
 * presign and the submit request. Both frontends share it, so a change to the
 * upload contract cannot land in one framework only.
 */
export async function submitAnalysisFiles(
  type: AnalysisType,
  options: {
    files: File[];
    params: Record<string, unknown>;
    onProgress: (percent: number) => void;
  },
): Promise<string> {
  const { files, params, onProgress } = options;
  if (files.length === 0) throw new Error("Select at least one file first.");

  onProgress(0);
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  let uploadedBytes = 0;
  let uploadedFiles = 0;

  // Hash sequentially so peak JavaScript memory stays bounded to one slice
  // while preserving the integrity contract.
  const checksums: string[] = [];
  for (const file of files) {
    checksums.push(await calculateFileSha256(file));
  }

  // Presign every file before any object-store bytes move.
  const presigned = await Promise.all(
    files.map((file, index) =>
      requestUpload(file.name, file.size, checksums[index]!, file.type || undefined).then(
        (response) => ({
          file,
          uploadUrl: response.upload_url,
          uploadMethod: response.upload_method,
          uploadFields: response.upload_fields,
          objectKey: response.object_key,
        }),
      ),
    ),
  );

  const objectKeys: string[] = [];
  for (const item of presigned) {
    await postWithProgress(
      item.uploadUrl,
      item.uploadMethod,
      item.uploadFields,
      item.file,
      (ratio: number) => {
        onProgress(
          calculateUploadProgress({
            completedBytes: uploadedBytes,
            totalBytes,
            currentFileBytes: item.file.size,
            currentFileRatio: ratio,
            completedFiles: uploadedFiles,
            totalFiles: files.length,
          }),
        );
      },
    );
    uploadedBytes += item.file.size;
    uploadedFiles += 1;
    objectKeys.push(item.objectKey);
  }

  onProgress(100);
  const response = await submitAnalysis(type, { inputObjects: objectKeys, params });
  recordRecentJob(response.job_id);
  return response.job_id;
}
