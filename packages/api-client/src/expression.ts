import { http } from "./auth";

export interface ExpressionRecord {
  library_id: number;
  library_name: string;
  fpkm: number;
  tpm: number;
  tissue: string;
  treatment: string;
}

export interface GeneExpressionResponse {
  gene_id: string;
  expressions: ExpressionRecord[];
}

export interface ExpressionLibrary {
  id: number;
  sample_id: string;
  library_name: string;
  tissue: string;
  treatment: string;
  developmental_stage: string | null;
  study_ref: string | null;
  source: string | null;
}

export async function getGeneExpression(
  geneId: string,
  params?: {
    tissue?: string;
    treatment?: string;
    min_fpkm?: number;
    max_fpkm?: number;
  },
): Promise<GeneExpressionResponse> {
  return http.get<GeneExpressionResponse>(`/genes/${geneId}/expression`, {
    params,
  });
}

export async function getExpressionLibraries(params?: {
  page?: number;
  page_size?: number;
  tissue?: string;
  treatment?: string;
}): Promise<{ items: ExpressionLibrary[]; total: number }> {
  return http.get<{ items: ExpressionLibrary[]; total: number }>(
    "/expression/libraries",
    { params },
  );
}

export async function searchExpression(params: {
  gene_id?: string;
  library_id?: number;
  tissue?: string;
  treatment?: string;
  min_fpkm?: number;
  max_fpkm?: number;
  page?: number;
  page_size?: number;
}): Promise<{ items: unknown[]; total: number }> {
  return http.get<{ items: unknown[]; total: number }>(
    "/expression/search",
    { params },
  );
}
