import { http } from "./auth";

export interface HomologRecord {
  species: string;
  gene_id: string;
  type: string;
  source: string | null;
}

export interface GeneHomologResponse {
  gene_id: string;
  homologs: HomologRecord[];
  next_cursor: string | null;
  has_more: boolean;
}

interface ApiGeneHomologRecord {
  homolog_species: string;
  homolog_gene_id: string;
  homolog_type: string;
  source: string | null;
}

interface ApiGeneHomologResponse {
  gene_id: string;
  homologs: ApiGeneHomologRecord[];
  next_cursor: string | null;
  has_more: boolean;
}

export async function getGeneHomologs(
  geneId: string,
  params?: { assembly_id?: string; cursor?: string; limit?: number },
): Promise<GeneHomologResponse> {
  const response = await http.get<ApiGeneHomologResponse>(
    `/homologs/genes/${geneId}/homologs`,
    { params },
  );
  return {
    gene_id: response.gene_id,
    homologs: response.homologs.map((homolog) => ({
      species: homolog.homolog_species,
      gene_id: homolog.homolog_gene_id,
      type: homolog.homolog_type,
      source: homolog.source,
    })),
    next_cursor: response.next_cursor,
    has_more: response.has_more,
  };
}

/** Server-side paging contract of GET /homologs/search. */
export interface HomologSearchPage {
  items: ApiGeneHomologRecord[];
  total: number | null;
  page: number | null;
  page_size: number;
  cursor: string | null;
  next_cursor: string | null;
  has_more: boolean;
}

export async function searchHomologs(params: {
  gene_id?: string;
  /** Canonical assembly id; required when the accession spans assemblies. */
  assembly_id?: string;
  /**
   * Species filter. The server parameter is `homolog_species`; the previous
   * client sent `species`, which the API ignored — a filter that silently did
   * nothing.
   */
  homolog_species?: string;
  homolog_type?: string;
  page?: number;
  page_size?: number;
  cursor?: string;
}): Promise<HomologSearchPage> {
  return http.get<HomologSearchPage>("/homologs/search", { params });
}
