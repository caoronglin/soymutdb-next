import { http } from "./auth";

/** Verified, reusable CMS media asset. */
export interface MediaAsset {
  id: string;
  object_key: string;
  public_url: string;
  original_filename: string;
  purpose: string;
  content_type: string;
  size_bytes: number;
  checksum_sha256: string;
  width: number | null;
  height: number | null;
  alt_text: string | null;
  caption: string | null;
  credit: string | null;
  is_decorative: boolean;
  status: "pending" | "ready" | "archived";
  uploaded_by: string;
  verified_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  usage_count: number;
}

export interface MediaAssetListResponse {
  items: MediaAsset[];
  total: number;
  page: number;
  page_size: number;
}

export interface MediaAssetListParams {
  search?: string;
  purpose?: string;
  status?: "ready" | "archived";
  page?: number;
  page_size?: number;
}

export interface MediaAssetUpdateRequest {
  alt_text?: string | null;
  caption?: string | null;
  credit?: string | null;
  is_decorative?: boolean;
}

export function listMediaAssets(
  params: MediaAssetListParams = {},
): Promise<MediaAssetListResponse> {
  const query: Record<string, string> = {};
  if (params.search?.trim()) query.search = params.search.trim();
  if (params.purpose) query.purpose = params.purpose;
  if (params.status) query.status = params.status;
  if (params.page) query.page = String(params.page);
  if (params.page_size) query.page_size = String(params.page_size);
  return http.get<MediaAssetListResponse>("/admin/media", { params: query });
}

export function getMediaAsset(assetId: string): Promise<MediaAsset> {
  return http.get<MediaAsset>(`/admin/media/${assetId}`);
}

export function updateMediaAsset(
  assetId: string,
  payload: MediaAssetUpdateRequest,
): Promise<MediaAsset> {
  return http.patch<MediaAsset>(`/admin/media/${assetId}`, { json: payload });
}

export function archiveMediaAsset(assetId: string): Promise<void> {
  return http.delete<void>(`/admin/media/${assetId}`);
}
