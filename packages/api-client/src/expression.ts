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
  return http.get<GeneExpressionResponse>(`/expression/genes/${geneId}/expression`, {
    params,
  });
}

export async function getExpressionLibraries(params?: {
  cursor?: string;
  limit?: number;
  tissue?: string;
  treatment?: string;
}): Promise<{ items: ExpressionLibrary[]; cursor: string | null; next_cursor: string | null; has_more: boolean; total_count: number | null }> {
  return http.get<Awaited<ReturnType<typeof getExpressionLibraries>>>(
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
  cursor?: string;
  limit?: number;
}): Promise<{ items: unknown[]; cursor: string | null; next_cursor: string | null; has_more: boolean; total_count: number | null }> {
  return http.get<Awaited<ReturnType<typeof searchExpression>>>(
    "/expression/search",
    { params },
  );
}
