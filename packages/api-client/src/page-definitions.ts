import { request } from "./client";
import type {
  PageDefinition,
  PageDefinitionStatus,
} from "@soymutdb/shared";

/**
 * Typed public page-definition client.
 *
 *   GET /api/v1/page-definitions/{route}?version=<uuid>
 *
 * Returns the latest *published* definition for a route, or a specific
 * published version when `version` is supplied. This is the read contract
 * shared by the public Web renderer and the SSG publication pipeline.
 */

export interface PageDefinitionVersionPayload {
  /** Public route/version/status contract; persistence/editor metadata is omitted. */
  route: string;
  version: number;
  status: PageDefinitionStatus;
  definition: PageDefinition;
}

/**
 * Fetch a published page definition for a route (optionally pinned version).
 * The route is passed without a leading slash (the API normalises it).
 */
export function getPageDefinition(
  route: string,
  version?: string,
): Promise<PageDefinitionVersionPayload> {
  const path = `/page-definitions/${route.replace(/^\/+/, "")}`;
  const params = version ? { version } : undefined;
  return request<PageDefinitionVersionPayload>(path, { params, auth: false });
}

/**
 * Enumerate every route that currently has a published definition.
 *
 * The endpoint is feature-gated (`page_builder`); a disabled site returns 404
 * and callers fall back to the static portal routes. Each entry is the same
 * minimal payload as {@link getPageDefinition} (newest published version per
 * route, no persistence or editor metadata).
 */
export function listPublishedPageDefinitions(): Promise<PageDefinitionVersionPayload[]> {
  return request<PageDefinitionVersionPayload[]>("/page-definitions/published-routes", {
    auth: false,
  });
}
