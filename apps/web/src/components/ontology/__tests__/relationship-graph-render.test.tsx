// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OntologyRelationshipGraph } from "../relationship-graph";

const { cytoscape, relationshipGraph } = vi.hoisted(() => ({
  cytoscape: vi.fn(() => ({ destroy: vi.fn() })),
  relationshipGraph: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  ontologyApi: { relationshipGraph },
}));

vi.mock("cytoscape", () => ({ default: cytoscape }));

function renderGraph() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <OntologyRelationshipGraph
        ontology="go"
        iri="http://purl.obolibrary.org/obo/GO_0008150"
      />
    </QueryClientProvider>,
  );
}

describe("OntologyRelationshipGraph", () => {
  afterEach(() => {
    cytoscape.mockClear();
    relationshipGraph.mockReset();
  });

  it("renders an accessible error state when the bounded graph request fails", async () => {
    relationshipGraph.mockRejectedValueOnce(new Error("upstream unavailable"));

    renderGraph();

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Ontology relationship graph is unavailable.",
    );
  });

  it("loads Cytoscape only after the bounded graph data resolves", async () => {
    relationshipGraph.mockResolvedValueOnce({
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
    });

    renderGraph();

    expect(cytoscape).not.toHaveBeenCalled();
    await screen.findByTestId("ontology-relationship-graph");
    await waitFor(() => expect(cytoscape).toHaveBeenCalledTimes(1));
  });
});
