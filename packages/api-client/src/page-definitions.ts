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
