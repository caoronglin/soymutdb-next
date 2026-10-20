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
 *        { object_key, parts: [{ part_number, etag }] }
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
  body: { object_key: string; parts: MultipartCompletePart[]; sha256?: string },
): Promise<MultipartCompleteResponse> {
  return http.post<MultipartCompleteResponse>(
    `/admin/imports/uploads/multipart/${encodeURIComponent(uploadId)}/complete`,
    { json: body, timeoutMs: 300_000 },
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
  signal?: AbortSignal,
): Promise<PartUploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    if (signal?.aborted) {
      reject(new DOMException("Upload cancelled", "AbortError"));
      return;
    }
    const onAbort = () => xhr.abort();
    signal?.addEventListener("abort", onAbort, { once: true });
    const settle = (finish: () => void) => {
      signal?.removeEventListener("abort", onAbort);
      finish();
    };
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0 && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        settle(() => reject(new Error(`Part upload failed with status ${xhr.status}`)));
        return;
      }
      // S3 returns the ETag header; strip surrounding quotes if present.
      const etag = (xhr.getResponseHeader("ETag") ?? xhr.getResponseHeader("etag") ?? "")
        .replace(/^"(.*)"$/, "$1");
      if (!etag) {
        // complete_multipart_upload rejects falsy ETags, so an empty header
        // would otherwise surface as an opaque failure after the whole file
        // has already been transferred.
        settle(() =>
          reject(new Error("Object storage did not return an ETag for the uploaded part.")),
        );
        return;
      }
      settle(() => resolve({ etag }));
    };
    xhr.onerror = () => settle(() => reject(new Error("Network error during part upload")));
    xhr.onabort = () => settle(() => reject(new DOMException("Upload cancelled", "AbortError")));
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

/** The local-file facts that decide whether two uploads are the same intent. */
export interface UploadSourceIdentity {
  filename: string;
  size: number;
  /** File.lastModified; 0 when the browser does not expose one. */
  lastModified: number;
  type: string;
  moduleKey?: string;
  dataSetId?: number;
}

/**
 * Signature of one uploaded source.
 *
 * Object keys are bound to their data set on the server (validate_data_key
 * checks the data/<data_set_id>/... prefix), so the data set is part of the
 * identity: the same bytes uploaded into another data set are a different
 * object and must never be reused.
 */
export function describeUploadSource(identity: UploadSourceIdentity): string {
  return JSON.stringify([
    identity.filename,
    identity.size,
    identity.lastModified,
    identity.type,
    identity.moduleKey?.trim() ?? "",
    identity.dataSetId ?? "",
  ]);
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
  if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
  if (file.size === 0) {
    // A zero-byte file divides by zero in the progress callback and still
    // opens a multipart session the server can never turn into an import.
    throw new Error("The selected file is empty.");
  }
  const partCount = partCountFor(file.size);
  const contentType = file.type || "application/octet-stream";

  const session = await startMultipart({
    filename,
    type,
    part_count: partCount,
    content_type: contentType,
    ...(dataSetId != null ? { data_set_id: dataSetId } : {}),
  });

  const parts: MultipartCompletePart[] = [];
  let uploadedBytes = 0;

  for (const part of session.parts) {
    if (signal?.aborted) throw new DOMException("Upload cancelled", "AbortError");
    const start = (part.part_number - 1) * MULTIPART_PART_SIZE;
    const end = Math.min(start + MULTIPART_PART_SIZE, file.size);
    // Blob/File#slice retains only this multipart range. In contrast to a
    // whole-file ArrayBuffer this keeps peak browser memory bounded by one
    // in-flight S3 part.
    const slice = file.slice(start, end, contentType);

    const result = await putPart(
      part.url,
      slice,
      (percent) => {
        // part percent * part size / total, accumulated with prior parts.
        const partBytes = (end - start) * (percent / 100);
        const pct = Math.round(((uploadedBytes + partBytes) / file.size) * 100);
        onProgress?.({ percent: Math.min(100, pct) });
      },
      signal,
    );
    parts.push({ part_number: part.part_number, etag: result.etag });
    uploadedBytes += end - start;
  }

  const completed = await completeMultipart(session.upload_id, {
    object_key: session.object_key,
    // S3 requires the completion list in ascending part order and the API
    // forwards it verbatim.
    parts: [...parts].sort((a, b) => a.part_number - b.part_number),
  });

  return { object_key: completed.object_key, sha256: completed.sha256 };
}

/* ------------------------------------------------------------------------ */
/* Import preview                                                            */
/* ------------------------------------------------------------------------ */

/**
 * Inspection is deliberately limited to one small local file. It never
 * claims that a bounded preview is a preview of a larger remote object.
 */
export const MAX_MODULE_PREVIEW_BYTES = 256 * 1024;

export interface ModulePreviewRequest {
  filename: string;
  moduleKey: string;
  file: File;
}

export interface ModulePreviewValidationError {
  code: string;
  row: number | null;
  message: string;
}

export type ModulePreviewResult =
  | {
      status: "available";
      headers: string[];
      rows: Array<Record<string, unknown>>;
      rowCount: number;
      truncated: boolean;
      checksumSha256: string;
      validation: {
        ok: boolean;
        errorCount: number;
        errors: ModulePreviewValidationError[];
      };
    }
  | { status: "unavailable"; reason: string };

interface InspectionResponse {
  headers: string[];
  row_count: number;
  rows: Array<Record<string, unknown>>;
  truncated: boolean;
  checksum_sha256: string;
  validation: {
    ok: boolean;
    error_count: number;
    errors: ModulePreviewValidationError[];
  };
}

function base64Encode(bytes: Uint8Array): string {
  const binaryChunks: string[] = [];
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binaryChunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
  }
  return btoa(binaryChunks.join(""));
}

/** Request a validated preview only when the complete local file is bounded. */
export async function fetchModulePreview(
  req: ModulePreviewRequest,
): Promise<ModulePreviewResult> {
  if (req.file.size === 0) {
    return { status: "unavailable", reason: "Preview requires a non-empty local file." };
  }
  if (req.file.size > MAX_MODULE_PREVIEW_BYTES) {
    return {
      status: "unavailable",
      reason: "Preview is available only for local module files up to 256 KiB.",
    };
  }

  const bytes = new Uint8Array(await req.file.slice(0, req.file.size).arrayBuffer());
  const inspected = await http.post<InspectionResponse>(
    `/admin/modules/${encodeURIComponent(req.moduleKey)}/inspect`,
    {
      json: {
        filename: req.filename,
        content_base64: base64Encode(bytes),
      },
      timeoutMs: 30_000,
    },
  );
  return {
    status: "available",
    headers: inspected.headers,
    rows: inspected.rows,
    rowCount: inspected.row_count,
    truncated: inspected.truncated,
    checksumSha256: inspected.checksum_sha256,
    validation: {
      ok: inspected.validation.ok,
      errorCount: inspected.validation.error_count,
      errors: inspected.validation.errors,
    },
  };
}
