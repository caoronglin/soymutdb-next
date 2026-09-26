/** Read-only, bounded import inspection and validation client. */

import { http } from "./auth";

export interface ImportInspectionRequest {
  filename: string;
  content_base64: string;
}

export interface ImportInspectionError {
  code: string;
  row: number | null;
  message: string;
}

export interface ImportInspectionValidation {
  ok: boolean;
  error_count: number;
  errors: ImportInspectionError[];
}

export interface ImportInspectionResponse {
  schema_version: 1;
  module_key: string;
  filename: string;
  format: string;
  encoding: string | null;
  delimiter: string | null;
  sheet_name: string | null;
  headers: string[];
  row_count: number;
  rows: Array<Record<string, unknown>>;
  truncated: boolean;
  checksum_sha256: string;
  validation: ImportInspectionValidation;
}

export interface ImportTask {
  id: number;
  filename: string;
  type: string;
  status: string;
  progress?: number | null;
  total_records?: number | null;
  processed_records?: number | null;
  celery_task_id?: string | null;
  submitted_by?: string | null;
  file_path?: string | null;
  error_message?: string | null;
  submitted_at?: string | null;
  completed_at?: string | null;
}

export interface ImportLiveStatus {
  id: number;
  status: string;
  celery_status: string;
  progress: number | null;
  processed_records: number | null;
  total_records: number | null;
  error_message: string | null;
}

export interface ImportCreateRequest {
  filename: string;
  type: string;
  file_path?: string;
  object_key?: string;
  release_id?: number;
  assembly?: string;
  module_key?: string;
  checksum?: string;
  idempotency_key: string;
}

export interface ImportListParams {
  page?: number;
  page_size?: number;
  status?: string;
  type?: string;
  search?: string;
}

export interface ImportListResponse {
  items: ImportTask[];
  total: number;
  page: number;
  page_size: number;
}

export const adminImportsApi = {
  inspect(moduleKey: string, body: ImportInspectionRequest) {
    return http.post<ImportInspectionResponse>(
      `/admin/modules/${encodeURIComponent(moduleKey)}/inspect`,
      { json: body },
    );
  },
  validate(moduleKey: string, body: ImportInspectionRequest) {
    return http.post<ImportInspectionResponse>(
      `/admin/modules/${encodeURIComponent(moduleKey)}/validate`,
      { json: body },
    );
  },
  list(params: ImportListParams = {}) {
    return http.get<ImportListResponse>("/admin/imports", { params });
  },
  get(importId: number) {
    return http.get<ImportTask>(`/admin/imports/${importId}`);
  },
  status(importId: number) {
    return http.get<ImportLiveStatus>(`/admin/imports/${importId}/status`);
  },
  create(body: ImportCreateRequest) {
    return http.post<ImportTask>("/admin/imports", { json: body });
  },
  cancel(importId: number) {
    return http.delete<void>(`/admin/imports/${importId}`);
  },
  retry(importId: number) {
    return http.post<ImportTask>(`/admin/imports/${importId}/retry`);
  },
};
