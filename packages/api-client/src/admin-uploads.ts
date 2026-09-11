/**
 * Admin uploads client (D4) — typed wrapper over the admin presign endpoint.
 *
 * Contract (apps/api/app/api/v1/admin_uploads.py + schemas/uploads.py):
 *
 *   POST /api/v1/admin/uploads/presign
 *       { filename, purpose, size, content_type, checksum_sha256 }
 *       -> { upload_url, upload_method, upload_fields, object_key, public_url, expires_in }
 *
 * Upload flow (stateless, used by apps/admin/src/components/file-upload.tsx):
 *   1. POST /admin/uploads/presign to obtain a constrained multipart POST.
 *   2. POST all signed fields followed by the file (no auth header).
 *   3. Persist `public_url` (e.g. as `news_articles.cover_url`).
 *
 * Requires the content-editor role (administrators inherit the capability).
 */

import { http } from "./auth";
import type { MediaAsset } from "./admin-media";

/** Presign request — mirrors backend `UploadPresignRequest`. */
export interface UploadPresignRequest {
  filename: string;
  /** Namespace segment under `uploads/`, e.g. "news". Defaults to "news". */
  purpose?: string;
  size: number;
  content_type: string;
  /** Lowercase hexadecimal SHA-256 digest of the exact file bytes. */
  checksum_sha256: string;
}

/** Presign response — mirrors backend `UploadPresignResponse`. */
export interface UploadPresignResponse {
  upload_url: string;
  upload_method: "POST";
  upload_fields: Record<string, string>;
  object_key: string;
  /** Public-facing URL suitable for persisting (e.g. `cover_url`). */
  public_url: string;
  expires_in: number;
}

/** Completion request sent only after the signed POST succeeds. */
export interface MediaAssetCompleteRequest {
  object_key: string;
  filename: string;
  purpose: string;
  size: number;
  content_type: string;
  checksum_sha256: string;
}

/** Verify an object server-side and register it in the media library. */
export function completeUpload(
  body: MediaAssetCompleteRequest,
): Promise<MediaAsset> {
  return http.post<MediaAsset>("/admin/uploads/complete", {
    json: body,
  });
}

/**
 * Request a constrained multipart POST for an admin upload.
 *
 * Returns the action and signed form fields plus the public URL to persist.
 * Nothing is stored server-side yet.
 */
export function uploadPresign(
  body: UploadPresignRequest,
): Promise<UploadPresignResponse> {
  return http.post<UploadPresignResponse>("/admin/uploads/presign", {
    json: body,
  });
}
