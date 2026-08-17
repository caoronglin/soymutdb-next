/**
 * Admin module file upload helper (Phase D).
 *
 * Implements browser-direct multipart upload to MinIO/S3 via the admin
 * imports endpoints (apps/api/app/api/v1/admin_imports.py):
 *
 *   1. POST /admin/imports/uploads/multipart
 *        { filename, type, part_count, content_type, data_set_id? }
 *        -> { upload_id, object_key, parts: [{ part_number, url }] }
 *   2. PUT each part's bytes to its pre-signed `url`, capturing the ETag.
 *   3. POST /admin/imports/uploads/multipart/{upload_id}/complete
 *        { object_key, parts: [{ part_number, etag }], sha256 }
 *        -> { upload_id, object_key, sha256, parts }
 *
 * The file bytes never touch the API; only the pre-signed URLs are fetched.
 * The returned `{ object_key, sha256 }` feed directly into `POST
 * /admin/imports` (with `module_key` for `module_tsv`).
 */

import { http } from "@soymutdb/api-client";

/** Minimum multipart part size on S3 (5 MiB) — all but the last part. */
export const MULTIPART_PART_SIZE = 5 * 1024 * 1024;

/** Number of parts needed to upload `size` bytes (>= 1). */
export function partCountFor(size: number): number {
  if (size <= 0) return 1;
  return Math.max(1, Math.ceil(size / MULTIPART_PART_SIZE));
}

/** Compute the hex SHA-256 of raw bytes (for the multipart complete callout). */
export async function sha256Hex(data: ArrayBuffer | Uint8Array): Promise<string> {
  const buf = data instanceof Uint8Array ? data : new Uint8Array(data);
  const normalized = new Uint8Array(buf);
  const digest = await crypto.subtle.digest("SHA-256", normalized.buffer as ArrayBuffer);
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

export interface MultipartStartRequest {
  filename: string;
  type: string;
  part_count: number;
  content_type: string;
  data_set_id?: number;
}

export interface MultipartStartResponse {
  upload_id: string;
  object_key: string;
  parts: Array<{ part_number: number; url: string }>;
}

export interface MultipartCompletePart {
  part_number: number;
  etag: string;
}

export interface MultipartCompleteResponse {
  upload_id: string;
  object_key: string;
  sha256: string;
  parts: Array<{ part_number: number; etag: string }>;
}

export interface UploadedObject {
  object_key: string;
  sha256: string;
}

/** POST /admin/imports/uploads/multipart — begin a multipart session. */
export function startMultipart(body: MultipartStartRequest): Promise<MultipartStartResponse> {
  return http.post<MultipartStartResponse>("/admin/imports/uploads/multipart", {
    json: body,
    timeoutMs: 30_000,
  });
}

/** POST /admin/imports/uploads/multipart/{upload_id}/complete — finalize. */
export function completeMultipart(
  uploadId: string,
  body: { object_key: string; parts: MultipartCompletePart[]; sha256: string },
): Promise<MultipartCompleteResponse> {
  return http.post<MultipartCompleteResponse>(
    `/admin/imports/uploads/multipart/${encodeURIComponent(uploadId)}/complete`,
    { json: body, timeoutMs: 60_000 },
  );
}

interface PartUploadResult {
  etag: string;
}

/**
 * PUT one part's bytes to its pre-signed URL via XHR (progress + no API auth
 * header on the S3 call). Returns the ETag from the response headers.
 */
function putPart(
  url: string,
  bytes: Blob,
  onProgress?: (percent: number) => void,
): Promise<PartUploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0 && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        // S3 returns the ETag header; strip surrounding quotes if present.
        const etag = (xhr.getResponseHeader("ETag") ?? xhr.getResponseHeader("etag") ?? "")
          .replace(/^"(.*)"$/, "$1");
        resolve({ etag });
      } else {
        reject(new Error(`Part upload failed with status ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during part upload"));
    xhr.send(bytes);
  });
}

export interface UploadProgress {
  /** 0–100 overall (bytes uploaded / total). */
  percent: number;
}

export interface UploadModuleFileOptions {
  filename: string;
  type: string;
  file: File;
  dataSetId?: number;
  onProgress?: (p: UploadProgress) => void;
  signal?: AbortSignal;
}

/**
 * Run the full multipart upload for a local file. Returns the completed
 * object key + checksum for import submission. Throws on any step failure so
 * the caller can surface an error/retry state.
 */
export async function uploadModuleFile(
  opts: UploadModuleFileOptions,
): Promise<UploadedObject> {
  const { filename, type, file, dataSetId, onProgress, signal } = opts;
  const partCount = partCountFor(file.size);
  const contentType = file.type || "application/octet-stream";

  const session = await startMultipart({
    filename,
    type,
    part_count: partCount,
    content_type: contentType,
    ...(dataSetId != null ? { data_set_id: dataSetId } : {}),
  });

  const bytesBuffer = await file.arrayBuffer();
  const sha256 = await sha256Hex(bytesBuffer);

  const parts: MultipartCompletePart[] = [];
  let uploadedBytes = 0;

  for (const part of session.parts) {
    if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
    const start = (part.part_number - 1) * MULTIPART_PART_SIZE;
    const end = Math.min(start + MULTIPART_PART_SIZE, file.size);
    const slice = new Blob([bytesBuffer.slice(start, end)], { type: contentType });

    const result = await putPart(part.url, slice, (percent) => {
      // part percent * part size / total, accumulated with prior parts.
      const partBytes = (end - start) * (percent / 100);
      const pct = Math.round(((uploadedBytes + partBytes) / file.size) * 100);
      onProgress?.({ percent: Math.min(100, pct) });
    });
    parts.push({ part_number: part.part_number, etag: result.etag });
    uploadedBytes += end - start;
  }

  const completed = await completeMultipart(session.upload_id, {
    object_key: session.object_key,
    parts,
    sha256,
  });

  return { object_key: completed.object_key, sha256: completed.sha256 };
}

/* ------------------------------------------------------------------------ */
/* Import preview (gap)                                                     */
/* ------------------------------------------------------------------------ */

/**
 * Import preview is NOT yet provided by the backend. There is no endpoint
 * that returns a validated, row-level preview of a module file before commit,
 * so the Admin UI must not fabricate one. This type documents the intended
 * contract for when the backend adds it (see docs/agent-state/import-preview-gap.md)
 * and lets the UI render an explicit "preview unavailable" state instead of
 * fake results.
 */
export interface ModulePreviewRequest {
  filename: string;
  module_key: string;
}

export type ModulePreviewResult =
  | { status: "available"; rows: Array<Record<string, unknown>>; truncated: boolean; warning?: string }
  | { status: "unavailable" };

/** Stub preview resolution that never invents data. */
export async function fetchModulePreview(
  _req: ModulePreviewRequest,
): Promise<ModulePreviewResult> {
  return { status: "unavailable" };
}
