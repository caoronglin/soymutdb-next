/** Typed client for the immutable Import Studio version/edit chain. */

import { http } from "./auth";

export interface DatasetVersionCreateRequest {
  dataset_id: number;
  filename: string;
  object_key: string;
  checksum_sha256: string;
  source: string;
  license: string | null;
  mime_type: string;
  row_count: number;
  column_count: number;
  source_objects: Array<Record<string, unknown>>;
}

export interface DatasetVersionResponse {
  id: string;
  dataset_id: number;
  version: number;
  filename: string;
  object_key: string;
  checksum_sha256: string;
  source: string;
  license: string | null;
  mime_type: string;
  row_count: number;
  column_count: number;
  source_objects: Array<Record<string, unknown>>;
  manifest: Record<string, unknown> | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface ImportDraftCreateRequest {
  dataset_version_id: string;
  module_key: string | null;
  row_count: number;
  column_count: number;
}

export interface ImportDraftResponse {
  id: string;
  dataset_version_id: string;
  module_key: string | null;
  filename: string;
  object_key: string;
  checksum_sha256: string;
  source: string;
  license: string | null;
  mime_type: string;
  row_count: number;
  column_count: number;
  field_mapping: Array<Record<string, unknown>>;
  validation: Record<string, unknown>;
  status: string;
  committed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface FieldMappingItem {
  source_field: string;
  target_field: string;
  position: number;
  transform: Record<string, unknown>;
}

export interface DataPatchItem {
  row_key: string;
  column_name: string;
  old_value: unknown | null;
  new_value: unknown | null;
  patch_type: "set" | "clear" | "format";
}

export interface PublicationManifestResponse {
  id: string;
  import_draft_id: string;
  checksum_sha256: string;
  manifest: Record<string, unknown>;
  published_at: string | null;
}

export const adminImportStudioApi = {
  createDatasetVersion(body: DatasetVersionCreateRequest) {
    return http.post<DatasetVersionResponse>(
      "/admin/imports/studio/dataset-versions",
      { json: body },
    );
  },
  createDraft(body: ImportDraftCreateRequest) {
    return http.post<ImportDraftResponse>("/admin/imports/studio/drafts", {
      json: body,
    });
  },
  getDraft(id: string) {
    return http.get<ImportDraftResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}`,
    );
  },
  updateMapping(
    id: string,
    mappings: FieldMappingItem[],
  ) {
    return http.put<ImportDraftResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}/mapping`,
      { json: { mappings } },
    );
  },
  addPatches(id: string, patches: DataPatchItem[]) {
    return http.post<ImportDraftResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}/patches`,
      { json: { patches } },
    );
  },
  validate(
    id: string,
    body: {
      row_count: number;
      column_count: number;
      field_mapping: FieldMappingItem[];
    },
  ) {
    return http.post<ImportDraftResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}/validate`,
      { json: body },
    );
  },
  commit(
    id: string,
    body: {
      page_id: string | null;
      source_id: string;
      kind: string;
      config: Record<string, unknown>;
      confirm: true;
    },
  ) {
    return http.post<ImportDraftResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}/commit`,
      { json: body },
    );
  },
  getManifest(id: string) {
    return http.get<PublicationManifestResponse>(
      `/admin/imports/studio/drafts/${encodeURIComponent(id)}/manifest`,
    );
  },
};
