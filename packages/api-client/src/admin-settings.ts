/** Typed, versioned administrator settings client. */

import { http } from "./auth";

export type SettingValue = string | number | boolean;
export type PublicSettingKind =
  | "string"
  | "integer"
  | "boolean"
  | "enum"
  | "email"
  | "url";

export interface SettingFieldSchema {
  kind: PublicSettingKind;
  default: SettingValue | null;
  permission: "administrator";
  scope: "global";
  hot_reload: boolean;
  redaction: "none" | "omit";
  requires_approval: boolean;
  allowed_values: string[];
  allowed_url_hosts: string[];
  minimum: number | null;
  maximum: number | null;
  max_length: number;
}

export interface SettingsSectionSchema {
  fields: Record<string, SettingFieldSchema>;
}

export interface SettingsSchemaResponse {
  version: 1;
  sections: Record<string, SettingsSectionSchema>;
}

export interface SettingsDocumentResponse {
  section: string;
  version: number;
  values: Record<string, SettingValue>;
}

export interface SettingsValidateResponse {
  section: string;
  valid: true;
  values: Record<string, SettingValue>;
}

export type SettingsHistoryAction = "patch" | "put_compat" | "rollback";

export interface SettingsHistoryItem {
  version: number;
  action: SettingsHistoryAction;
  values: Record<string, SettingValue>;
  changes: Record<string, SettingValue | null>;
  actor_id: string | null;
  created_at: string;
  rollback_from_version: number | null;
  reason: string | null;
}

export interface SettingsHistoryResponse {
  section: string;
  current_version: number;
  items: SettingsHistoryItem[];
}

export interface SettingsRollbackRequest {
  expected_version: number;
  target_version: number;
  reason: string;
}

export const adminSettingsApi = {
  schema() {
    return http.get<SettingsSchemaResponse>("/admin/settings/schema");
  },
  get(section: string) {
    return http.get<SettingsDocumentResponse>(
      `/admin/settings/${encodeURIComponent(section)}/document`,
    );
  },
  validate(section: string, values: Record<string, SettingValue>) {
    return http.post<SettingsValidateResponse>("/admin/settings/validate", {
      json: { section, values },
    });
  },
  patch(
    section: string,
    expectedVersion: number,
    values: Record<string, SettingValue>,
  ) {
    return http.patch<SettingsDocumentResponse>(
      `/admin/settings/${encodeURIComponent(section)}`,
      { json: { expected_version: expectedVersion, values } },
    );
  },
  history(section: string, limit = 50) {
    return http.get<SettingsHistoryResponse>(
      `/admin/settings/${encodeURIComponent(section)}/history`,
      { params: { limit } },
    );
  },
  rollback(section: string, body: SettingsRollbackRequest) {
    return http.post<SettingsDocumentResponse>(
      `/admin/settings/${encodeURIComponent(section)}/rollback`,
      { json: body },
    );
  },
};
