/**
 * Comparative-genomics client.
 *
 * The http client is mocked (as in `homolog.test.ts`) so these tests assert the
 * request each function *builds*: the path, the forwarded assembly, and — most
 * importantly — the filters it does not send.
 */

import { http } from "./auth";
import {
  compareFamilies,
  getArtifact,
  getFamily,
  getGeneOrthologs,
  listFamilies,
  requestArtifact,
} from "./comparative";

vi.mock("./auth", () => ({
  http: { get: vi.fn(), post: vi.fn() },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);

describe("comparative client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
  });

  it("forwards the resolved assembly on every family read", async () => {
    mockGet.mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 20 });

    await listFamilies({ assembly_id: 4, level: "gene_family", page: 2 });

    expect(mockGet).toHaveBeenCalledWith("/comparative/families", {
      params: { assembly_id: 4, level: "gene_family", page: 2, page_size: undefined },
    });
  });

  it("omits an unset assembly instead of sending null", async () => {
    mockGet.mockResolvedValueOnce({ family_id: 7, members: [], coverage: [] });

    await getFamily(7, { assembly_id: null });

    expect(mockGet).toHaveBeenCalledWith("/comparative/families/7", {
      params: { assembly_id: undefined },
    });
  });

  it("keeps no_data coverage distinguishable from a zero count", async () => {
    mockGet.mockResolvedValueOnce({
      family_id: 1,
      level: "gene_family",
      external_id: "PF1",
      name: "Family",
      method: "hmmsearch",
      method_version: null,
      source_name: "fixture",
      source_version: "1",
      source_url: "https://example.org",
      release_id: 7,
      assembly_id: 4,
      member_count: 2,
      evidence: { kind: "predicted", source: "gene_families" },
      members: [],
      coverage: [
        { species: "soybean", state: "available", member_count: 2 },
        { species: "arabidopsis", state: "no_data", member_count: null },
      ],
      relationship_types: ["one_to_many"],
    });

    const family = await getFamily(1);
    const coverage = Object.fromEntries(family.coverage.map((entry) => [entry.species, entry]));
    expect(coverage.soybean.member_count).toBe(2);
    // ``null`` -- not 0 -- is what tells a caller the species was not measured.
    expect(coverage.arabidopsis.member_count).toBeNull();
    expect(coverage.arabidopsis.state).toBe("no_data");
  });

  it("passes both family ids to the comparison endpoint", async () => {
    mockGet.mockResolvedValueOnce({
      left: {},
      right: {},
      shared: [],
      only_left: [],
      only_right: [],
      coverage: [],
    });

    await compareFamilies(3, 9);

    expect(mockGet).toHaveBeenCalledWith("/comparative/families/compare", {
      params: { left: 3, right: 9, assembly_id: undefined },
    });
  });

  it("never sends a similarity filter with an orthology query", async () => {
    mockGet.mockResolvedValueOnce({ records: [], state: "no_data" });

    await getGeneOrthologs("Glyma.01G000100", { assembly_id: 4 });

    expect(mockGet).toHaveBeenCalledWith(
      "/comparative/genes/Glyma.01G000100/orthologs",
      { params: { assembly_id: 4, homolog_type: undefined } },
    );
    const params = mockGet.mock.calls[0][1]?.params ?? {};
    expect(params).not.toHaveProperty("evalue");
    expect(params).not.toHaveProperty("identity");
  });

  it("posts an artifact request and reads its state back", async () => {
    const pending = {
      artifact_type: "msa" as const,
      job_id: "6f4a1e1c-0000-4000-8000-000000000000",
      state: "pending" as const,
      method: "mafft",
      input_sha256: "a".repeat(64),
      input_member_ids: ["G1", "G2", "G3"],
      download_url: null,
      error_message: null,
      created_at: null,
      completed_at: null,
    };
    mockPost.mockResolvedValueOnce(pending);
    mockGet.mockResolvedValueOnce({ ...pending, state: "succeeded", download_url: "https://x" });

    const artifact = await requestArtifact({
      family_id: 1,
      artifact_type: "msa",
      method: "mafft",
    });
    expect(artifact.state).toBe("pending");
    expect(mockPost).toHaveBeenCalledWith("/comparative/artifacts", {
      json: { family_id: 1, artifact_type: "msa", method: "mafft" },
    });

    const fetched = await getArtifact(artifact.job_id);
    expect(fetched.download_url).toBe("https://x");
  });
});
