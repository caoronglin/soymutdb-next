/**
 * Typed administrator Page Builder client.
 *
 * Mirrors `apps/api/app/page_builder/schemas.py`. Definitions are validated
 * server-side by the component registry; the editor never invents renderer
 * keys of its own (it renders `GET /registry` descriptors).
 */

import type {
  CompatiblePageDefinition,
  ComponentDescriptor,
  PageDefinitionStatus,
  PageDefinitionSummary,
  PageDefinitionVersion,
} from "@soymutdb/shared";
import { http } from "./auth";

export interface PageDefinitionListResponse {
  items: PageDefinitionSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface PageDefinitionResponse {
  id: string;
  route: string;
  title_key: string;
  versions: PageDefinitionVersion[];
  created_at: string;
  updated_at: string;
}

export interface PageDefinitionCreate {
  route: string;
  title_key: string;
  definition: CompatiblePageDefinition;
}

export interface PageDefinitionUpdate {
  base_version: number;
  definition: CompatiblePageDefinition;
  edit_comment?: string | null;
}

export interface PreviewResponse {
  definition: CompatiblePageDefinition;
  version_preview: number;
}

export interface PublishResponse {
  page_id: string;
  version_id: string;
  version: number;
  status: PageDefinitionStatus;
  event_id: string | null;
}

export interface PageTemplate {
  id: string;
  key: string;
  label: string;
  description: string | null;
  category: string;
  definition: CompatiblePageDefinition;
  preview_image_id: string | null;
  builtin: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface PageTemplateListResponse {
  items: PageTemplate[];
  total: number;
}

export interface RegistryResponse {
  components: ComponentDescriptor[];
}

export const adminPageBuilderApi = {
  registry() {
    return http.get<RegistryResponse>("/admin/page-builder/registry");
  },
  templates() {
    return http.get<PageTemplateListResponse>("/admin/page-builder/templates");
  },
  pages(page = 1, pageSize = 50, route?: string) {
    return http.get<PageDefinitionListResponse>("/admin/page-builder/pages", {
      params: { page, page_size: pageSize, ...(route ? { route } : {}) },
    });
  },
  page(pageId: string) {
    return http.get<PageDefinitionResponse>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}`,
    );
  },
  create(body: PageDefinitionCreate) {
    return http.post<PageDefinitionResponse>("/admin/page-builder/pages", {
      json: body,
    });
  },
  saveDraft(pageId: string, body: PageDefinitionUpdate) {
    return http.put<PageDefinitionVersion>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/draft`,
      { json: body },
    );
  },
  preview(pageId: string, definition: CompatiblePageDefinition) {
    return http.post<PreviewResponse>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/preview`,
      { json: { definition } },
    );
  },
  publish(pageId: string, versionId?: string, reason?: string) {
    return http.post<PublishResponse>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/publish`,
      { json: { version_id: versionId ?? null, reason: reason ?? null } },
    );
  },
  requestPublish(pageId: string, versionId?: string, reason?: string) {
    return http.post<PublishResponse>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/publish-request`,
      { json: { version_id: versionId ?? null, reason: reason ?? null } },
    );
  },
};