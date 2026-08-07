import { http } from "./auth";

export interface HomologRecord {
  species: string;
  gene_id: string;
  type: string;
  source: string;
}

export interface GeneHomologResponse {
  gene_id: string;
  homologs: HomologRecord[];
}

export async function getGeneHomologs(
  geneId: string,
): Promise<GeneHomologResponse> {
  return http.get<GeneHomologResponse>(`/genes/${geneId}/homologs`);
}

export async function searchHomologs(params: {
  gene_id?: string;
  species?: string;
  page?: number;
  page_size?: number;
}): Promise<{ items: unknown[]; total: number }> {
  return http.get<{ items: unknown[]; total: number }>("/homologs/search", {
    params,
  });
}
