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
};
