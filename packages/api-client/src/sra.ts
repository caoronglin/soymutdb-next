import { http } from "./auth";

/** Metadata for a single SRA run (from NCBI runinfo CSV). */
export interface SraRunInfo {
  Run: string;
  ReleaseDate?: string;
  LoadDate?: string;
  spots?: string;
  bases?: string;
  spots_with_mates?: string;
  avgLength?: string;
  size_MB?: string;
  download_path?: string;
  Experiment?: string;
  LibraryName?: string;
  LibraryStrategy?: string;
  LibrarySelection?: string;
  LibrarySource?: string;
  LibraryLayout?: string;
  InsertSize?: string;
  InsertDev?: string;
  Platform?: string;
  Model?: string;
  SRAStudy?: string;
  BioProject?: string;
  Study_Pubmed_id?: string;
  ProjectID?: string;
  Sample?: string;
  BioSample?: string;
  SampleType?: string;
  TaxID?: string;
  ScientificName?: string;
  SampleName?: string;
  CenterName?: string;
  Submission?: string;
  Consent?: string;
  sra_url: string;
  release_date_short?: string;
  [key: string]: string | undefined;
}

export interface SraRunResponse {
  run: SraRunInfo;
  accession: string;
  source: "ncbi" | "fallback" | "stub";
  cached: boolean;
  error?: string;
}

export interface SraSample {
  Run: string;
  BioProject?: string;
  ScientificName?: string;
  LibraryStrategy?: string;
  Platform?: string;
  Model?: string;
  spots?: string;
  bases?: string;
  avgLength?: string;
  size_MB?: string;
  ReleaseDate?: string;
  CenterName?: string;
  sra_url: string;
  release_date_short?: string;
}

export interface SraSamplesResponse {
  samples: SraSample[];
  demo: SraRunInfo;
  total: number;
}

/** Fetch JSON metadata for a single SRA run accession. */
export function fetchSraRun(accession: string): Promise<SraRunResponse> {
  return http.get<SraRunResponse>(`/sra/run/${encodeURIComponent(accession)}`);
}

/** Fetch the curated list of SRA samples (default species: soybean) + demo run. */
export function fetchSraSamples(): Promise<SraSamplesResponse> {
  return http.get<SraSamplesResponse>("/sra/samples");
}
