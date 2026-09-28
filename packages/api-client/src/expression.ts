import { http } from "./auth";

/**
 * One expression observation for a gene.
 *
 * The library is identified by its public sample id (`library_public_id`); the
 * numeric persistence key is internal and never appears in a public payload.
 */
export interface ExpressionRecord {
  library_public_id: string;
  library_name: string;
  fpkm: number | null;
  tpm: number | null;
  tissue: string;
  treatment: string;
  raw_count?: number | null;
}

export interface GeneExpressionResponse {
  gene_id: string;
  expressions: ExpressionRecord[];
  /**
   * Opaque, release- and filter-bound keyset cursor. It is a string (not a row
   * id) so it cannot be replayed against another release or filter set.
   */
  next_cursor: string | null;
  has_more: boolean;
}

export interface ExpressionLibrary {
  /** Public, non-persistence identity (the annotation's sample id). */
  public_id: string;
  sample_id: string;
  library_name: string;
  tissue: string;
  treatment: string;
  developmental_stage: string | null;
  study_ref: string | null;
  source: string | null;
  assembly_name: string | null;
  expression_data_count: number;
  extra_metadata: Record<string, unknown> | null;
}

export async function getGeneExpression(
  geneId: string,
  params?: {
    assembly_id?: string;
    tissue?: string;
    treatment?: string;
    /** Public sample id of a single library to narrow to. */
    library?: string;
    min_fpkm?: number;
    max_fpkm?: number;
    cursor?: string;
    limit?: number;
  },
): Promise<GeneExpressionResponse> {
  return http.get<GeneExpressionResponse>(`/expression/genes/${geneId}/expression`, {
    params,
  });
}

/** Server-side paging contract of GET /expression/libraries. */
export interface ExpressionLibraryPage {
  items: ExpressionLibrary[];
  total: number;
  page: number;
  page_size: number;
}

export async function getExpressionLibraries(params?: {
  page?: number;
  page_size?: number;
  tissue?: string;
  treatment?: string;
  assembly_id?: number;
}): Promise<ExpressionLibraryPage> {
  return http.get<ExpressionLibraryPage>("/expression/libraries", { params });
}

/** Server-side paging contract of GET /expression/search. */
export interface ExpressionSearchPage {
  items: ExpressionSearchRecord[];
  total: number;
  page: number;
  page_size: number;
}

export interface ExpressionSearchRecord {
  gene_id: string;
  library_public_id: string;
  library_name: string;
  tissue: string;
  treatment: string;
  fpkm: number | null;
  tpm: number | null;
  raw_count?: number | null;
}

export async function searchExpression(params: {
  gene_id?: string;
  assembly_id?: number;
  /** Public sample id of a single library to narrow to. */
  library?: string;
  tissue?: string;
  treatment?: string;
  min_fpkm?: number;
  max_fpkm?: number;
  page?: number;
  page_size?: number;
}): Promise<ExpressionSearchPage> {
  return http.get<ExpressionSearchPage>("/expression/search", { params });
}
