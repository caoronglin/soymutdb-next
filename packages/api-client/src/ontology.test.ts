import { http } from "./client";
import {
  ontologyApi,
  type OntologySearchResponse,
} from "./ontology";

vi.mock("./client", () => ({
  http: {
    get: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);

describe("ontology client", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("queries the bounded public OLS4 search endpoint", async () => {
    const response: OntologySearchResponse = {
      query: "mitochondrion",
      ontology: "go",
      count: 1,
      items: [
        {
          term_id: "GO:0000001",
          label: "mitochondrion inheritance",
          iri: "http://purl.obolibrary.org/obo/GO_0000001",
          ontology_name: "go",
          description: [],
          synonyms: [],
          is_obsolete: false,
        },
      ],
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(
      ontologyApi.search({ query: "mitochondrion", ontology: "go", limit: 10 }),
    ).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/ontology/search", {
      params: { query: "mitochondrion", ontology: "go", limit: 10 },
    });
  });

  it("queries the bounded OLS4 relationship graph endpoint", async () => {
    const response = {
      ontology: "go",
      root_iri: "http://purl.obolibrary.org/obo/GO_0008150",
      nodes: [
        {
          iri: "http://purl.obolibrary.org/obo/GO_0008150",
          label: "biological_process",
          is_obsolete: false,
        },
      ],
      edges: [],
      truncated: false,
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(
      ontologyApi.relationshipGraph({
        ontology: "go",
        iri: "http://purl.obolibrary.org/obo/GO_0008150",
        max_nodes: 24,
        max_edges: 32,
      }),
    ).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/ontology/graph", {
      params: {
        ontology: "go",
        iri: "http://purl.obolibrary.org/obo/GO_0008150",
        max_nodes: 24,
        max_edges: 32,
      },
    });
  });
});
