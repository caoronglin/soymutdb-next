/**
 * Admin uploads client (D4) — typed wrapper over the admin presign endpoint.
 *
 * Contract (apps/api/app/api/v1/admin_uploads.py + schemas/uploads.py):
 *
 *   POST /api/v1/admin/uploads/presign
 *       { filename, purpose } -> { upload_url, object_key, public_url, expires_in }
 *
 * Upload flow (stateless, used by apps/admin/src/components/file-upload.tsx):
 *   1. POST /admin/uploads/presign to obtain a pre-signed PUT URL.
 *   2. PUT the bytes directly to `upload_url` (S3/MinIO, no auth header).
 *   3. Persist `public_url` (e.g. as `news_articles.cover_url`).
 *
 * Requires the researcher role or higher (same RBAC as the news admin API).
 */

import { http } from "./auth";

/** Presign request — mirrors backend `UploadPresignRequest`. */
export interface UploadPresignRequest {
  filename: string;
  /** Namespace segment under `uploads/`, e.g. "news". Defaults to "news". */
  purpose?: string;
}

/** Presign response — mirrors backend `UploadPresignResponse`. */
export interface UploadPresignResponse {
  upload_url: string;
  object_key: string;
  /** Public-facing URL suitable for persisting (e.g. `cover_url`). */
  public_url: string;
  expires_in: number;
}

/**
 * Request a pre-signed PUT URL for an admin upload (researcher+).
 *
 * Returns the URL to PUT the bytes to plus the public URL to persist.
 * Nothing is stored server-side yet.
 */
export function uploadPresign(
  body: UploadPresignRequest,
): Promise<UploadPresignResponse> {
  return http.post<UploadPresignResponse>("/admin/uploads/presign", {
    json: body,
  });
}
