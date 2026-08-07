import { http } from "./auth";

export interface Track {
  id: string;
  name: string;
  type: string;
  description: string;
  assembly_name: string;
  category: string[];
  source: string;
  file_path: string;
  file_size: number;
  status: "ready" | "processing" | "failed";
  is_public: boolean;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
}

export interface TrackListResponse {
  items: Track[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateTrackRequest {
  name: string;
  type: string;
  description: string;
  assembly_name: string;
  category: string[];
  file_path?: string;
  upload_url?: string;
  is_public?: boolean;
  metadata?: Record<string, unknown>;
}

export interface UpdateTrackRequest {
  name?: string;
  description?: string;
  category?: string[];
  is_public?: boolean;
  status?: string;
  metadata?: Record<string, unknown>;
}

export interface TrackListParams {
  page?: number;
  page_size?: number;
  assembly?: string;
  category?: string;
  type?: string;
  search?: string;
  public?: boolean;
}

export function fetchTracks(params?: TrackListParams): Promise<TrackListResponse> {
  return http.get<TrackListResponse>("/tracks", { params });
}

export function fetchAllTracks(assembly?: string): Promise<Track[]> {
  return http.get<Track[]>("/tracks/all", {
    params: assembly ? { assembly } : undefined,
  });
}

export function getTrack(trackId: string): Promise<Track> {
  return http.get<Track>(`/tracks/${trackId}`);
}

export function createTrack(track: CreateTrackRequest): Promise<Track> {
  return http.post<Track>("/tracks", { json: track });
}

export function updateTrack(
  trackId: string,
  track: UpdateTrackRequest,
): Promise<Track> {
  return http.patch<Track>(`/tracks/${trackId}`, { json: track });
}

export function deleteTrack(trackId: string): Promise<void> {
  return http.delete<void>(`/tracks/${trackId}`);
}

export function getTrackUploadUrl(
  trackId: string,
  fileName: string,
): Promise<{ upload_url: string; file_path: string }> {
  return http.post<{ upload_url: string; file_path: string }>(
    `/tracks/${trackId}/upload-url`,
    { json: { file_name: fileName } },
  );
}

export function reindexTrack(trackId: string): Promise<{ job_id: string }> {
  return http.post<{ job_id: string }>(`/tracks/${trackId}/reindex`);
}

export function toggleTrackVisibility(
  trackId: string,
  isPublic: boolean,
): Promise<Track> {
  return http.patch<Track>(`/tracks/${trackId}`, { json: { is_public: isPublic } });
}
