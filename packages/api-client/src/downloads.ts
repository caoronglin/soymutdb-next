import { http } from "./auth";

export interface DownloadFile {
  id: string;
  name: string;
  description: string | null;
  file_url: string;
  file_size: number | null;
  category: string | null;
  download_count: number;
  created_at: string;
}

export interface DownloadUrlResponse {
  url: string;
  expires_in: number;
  request_id?: string;
}

/**
 * Fetch downloadable files, optionally filtered by *category*.
 */
export function getDownloadFiles(category?: string): Promise<DownloadFile[]> {
  return http.get<DownloadFile[]>("/content/downloads", {
    params: category ? { category } : {},
  });
}

/**
 * Generate a pre-signed download URL for a file.
 */
export function getDownloadUrl(fileId: string): Promise<DownloadUrlResponse> {
  return http.get<DownloadUrlResponse>(`/content/downloads/${fileId}/url`);
}
