/**Client for server-owned public/admin feature capabilities.*/

import { http } from "./client";

export interface PublicCapabilitiesResponse {
  version: number;
  features: Record<string, boolean>;
}

export interface FeatureDefinitionResponse {
  key: string;
  enabled: boolean;
  default: boolean;
  public: boolean;
  description: string;
  disable_behavior: string;
}

export interface AdminFeaturesResponse {
  version: number;
  features: FeatureDefinitionResponse[];
}

export const capabilitiesApi = {
  get() {
    return http.get<PublicCapabilitiesResponse>("/capabilities");
  },
  adminGet() {
    return http.get<AdminFeaturesResponse>("/admin/features");
  },
  adminUpdate(features: Record<string, boolean>) {
    return http.put<AdminFeaturesResponse>("/admin/features", { json: { features } });
  },
};
