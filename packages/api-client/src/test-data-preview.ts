import { http } from "./auth";

const PREVIEW_ASSEMBLY = "Gmax_880_v6.0";
const PREVIEW_ASSEMBLY_VERSION = "v6.0";
const PREVIEW_ANNOTATION_VERSION = "Wm82.a6.v1";
const PREVIEW_DATASET_KEY = "03_soymut-a6-test";

/** Metadata for the local, unpublished test dataset. */
export interface TestDataPreviewMeta {
  preview: true;
  publication_status: "unpublished";
  coordinate_system: "1-based-inclusive";
  dataset: {
    key: string;
    source_file: string;
    source_sha256: string;
    row_count: number;
  };
  assembly: {
    name: string;
    version: string;
    species: string;
    status: "unpublished";
  };
  annotation_version: string;
  chromosomes: Array<{ name: string; length: number }>;
}

export interface TestDataPreviewGene {
  gene_id: string;
  gene_symbol: string | null;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  strand: "+" | "-";
  biotype: string;
  mutation_site_count: number;
}

export interface TestDataPreviewGenesResponse {
  preview: true;
  publication_status: "unpublished";
  assembly: TestDataPreviewMeta["assembly"];
  annotation_version: string;
  items: TestDataPreviewGene[];
  total: number;
  limit: number;
}

export interface TestDataPreviewMutationSite {
  /** Stable key from the supplied TSV, not a database primary key. */
  source_site_key: string;
  mutant_line_name: string;
  chromosome: string;
  position: number;
  confidence: "H" | "L";
  gene_id: string;
  feature: string;
  /** Operator-editable from the admin console. */
  available: boolean;
  /** Homolog accessions from the same TSV row; null when the column is empty. */
  gene_v2: string | null;
  gene_v4: string | null;
  gene_dn53: string | null;
}

export interface TestDataPreviewMutationSitesResponse {
  preview: true;
  publication_status: "unpublished";
  coordinate_system: "1-based-inclusive";
  assembly: TestDataPreviewMeta["assembly"];
  annotation_version: string;
  items: TestDataPreviewMutationSite[];
  total: number;
  limit: number;
}

export function getTestDataPreviewMeta(): Promise<TestDataPreviewMeta> {
  return http.get<TestDataPreviewMeta>("/preview/test-data/meta").then(assertPreviewMeta);
}

export function searchTestDataPreviewGenes(params: {
  gene_id: string;
  limit?: number;
}): Promise<TestDataPreviewGenesResponse> {
  return http
    .get<TestDataPreviewGenesResponse>("/preview/test-data/genes", { params })
    .then((value) => {
      assertUnpublishedPreview(value);
      assertPreviewContext(value);
      return value;
    });
}

export function searchTestDataPreviewMutationSites(params: {
  chromosome: string;
  start: number;
  end: number;
  limit?: number;
}): Promise<TestDataPreviewMutationSitesResponse> {
  return http
    .get<TestDataPreviewMutationSitesResponse>("/preview/test-data/mutation-sites", { params })
    .then((value) => {
      assertUnpublishedPreview(value);
      assertPreviewContext(value);
      if (value.coordinate_system !== "1-based-inclusive") {
        throw new Error("Test-data preview response has an unexpected coordinate system");
      }
      return value;
    });
}

/**
 * Every source mutation-site row attached to one exact gene ID.
 *
 * Keyed on the gene relation, not a coordinate interval: 13% of the source rows
 * sit up- or downstream of their gene's start/end, so an interval query would
 * silently drop them.
 */
export function listTestDataPreviewMutationSitesForGene(
  geneId: string,
  limit = 1000,
): Promise<TestDataPreviewMutationSite[]> {
  return http.get<TestDataPreviewMutationSite[]>("/preview/test-data/mutation-sites/by-gene", {
    params: { gene_id: geneId, limit },
  });
}

/**
 * Update the operator-maintained `available` flag of one source row.
 *
 * This is the only writable field of a preview mutation site: everything else
 * is the uploaded table's content and is rewritten on the next import.
 */
export function updateTestDataPreviewMutationSite(
  sourceSiteKey: string,
  payload: { available: boolean },
): Promise<TestDataPreviewMutationSite> {
  // The single-row response is the bare row shape (no `preview` envelope), so
  // there is nothing to assert here beyond the request itself.
  return http.patch<TestDataPreviewMutationSite>(
    `/preview/test-data/mutation-sites/${encodeURIComponent(sourceSiteKey)}`,
    { json: payload },
  );
}

function assertUnpublishedPreview<T extends { preview: boolean; publication_status: string }>(value: T): T {
  if (value.preview !== true || value.publication_status !== "unpublished") {
    throw new Error("Test-data preview response is missing its unpublished-data marker");
  }
  return value;
}

function assertPreviewMeta(value: TestDataPreviewMeta): TestDataPreviewMeta {
  assertUnpublishedPreview(value);
  assertPreviewContext(value);
  if (
    value.coordinate_system !== "1-based-inclusive" ||
    value.dataset.key !== PREVIEW_DATASET_KEY
  ) {
    throw new Error("Test-data preview metadata has an unexpected dataset or coordinate status");
  }
  return value;
}

function assertPreviewContext(value: {
  assembly: TestDataPreviewMeta["assembly"];
  annotation_version: string;
}): void {
  if (
    value.assembly.status !== "unpublished" ||
    value.assembly.name !== PREVIEW_ASSEMBLY ||
    value.assembly.version !== PREVIEW_ASSEMBLY_VERSION ||
    value.annotation_version !== PREVIEW_ANNOTATION_VERSION
  ) {
    throw new Error("Test-data preview response has an unexpected assembly or annotation version");
  }
}
