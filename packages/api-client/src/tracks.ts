import { http } from "./auth";

/**
 * Track reads.
 *
 * The API serves five GET routes under "/tracks": the collection,
 * "/categories", "/jbrowse-config", "/{track_id}" and
 * "/{track_id}/signed-url". This module covers the collection and detail
 * reads; the JBrowse app calls the other three directly.
 *
 * The API serves no track write routes — creation, update, deletion, reindex
 * and upload-url are not registered by any router — so this module is
 * read-only by contract, not by omission.
 *
 * Visibility and caching are server-side and not negotiable from here: these
 * responses are RBAC-filtered per caller, authenticated ones are
 * "private, no-store" with "Vary: Authorization", and only the anonymous
 * public projection may be served from a shared cache. Do not layer caching
 * over them.
 */

/** Mirrors TrackType in "apps/api/app/models/tracks.py". */
export type TrackType =
  | "variant"
  | "alignment"
  | "annotation"
  | "quantitative"
  | "density"
  | "structural_variant"
  | "phenotype";

/** Mirrors FileFormat in "apps/api/app/models/tracks.py". */
export type TrackFileFormat =
  | "vcf"
  | "bam"
  | "cram"
  | "bigwig"
  | "bigbed"
  | "gff3"
  | "bed"
  | "bw";

/** Mirrors TrackVisibility in "apps/api/app/models/tracks.py". */
export type TrackVisibility = "public" | "project" | "private";

/**
 * The read routes filter on a ready status and skip soft-deleted rows, so
 * "ready" is the only status a caller can observe here.
 */
export type TrackStatus = "ready";

/**
 * A track as the backend track service serializes it.
 *
 * Identifiers are strings, and "assembly_id" is a stable numeric identity
 * rendered as text. An assembly *name* is not interchangeable with it across
 * release namespaces.
 */
export interface Track {
  id: string;
  name: string;
  description: string | null;
  track_type: TrackType;
  file_format: TrackFileFormat;
  assembly_id: string;
  category_id: string | null;
  owner_id: string | null;
  visibility: TrackVisibility;
  status: TrackStatus;
  created_at: string | null;
}

/**
 * The only filters the backend accepts. Unknown query parameters are silently
 * ignored, so an unimplemented filter would look like it worked and quietly
 * return unfiltered rows.
 */
export interface TrackListParams {
  assembly_id?: number;
  category_id?: number;
}

/**
 * List visible tracks, optionally scoped to one assembly and/or category.
 *
 * Returns a bare array; the route takes no pagination.
 */
export function fetchTracks(params?: TrackListParams): Promise<Track[]> {
  return http.get<Track[]>("/tracks", { params });
}

/**
 * Read one track by id.
 *
 * A track the caller may not see is reported as 404, so this does not leak the
 * existence of private or project tracks.
 */
export function getTrack(trackId: string | number): Promise<Track> {
  return http.get<Track>(`/tracks/${trackId}`);
}
