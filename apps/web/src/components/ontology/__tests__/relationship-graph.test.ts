import { describe, expect, it } from "vitest";
import {
  MAX_RENDERED_GRAPH_EDGES,
  MAX_RENDERED_GRAPH_NODES,
  boundedCytoscapeElements,
} from "../relationship-graph";

describe("bounded Cytoscape relationship graph", () => {
  it("caps nodes and edges while dropping edges whose endpoints were omitted", () => {
    const root = "root";
    const nodes = Array.from({ length: MAX_RENDERED_GRAPH_NODES + 2 }, (_, index) => ({
      iri: index === 0 ? root : `term-${index}`,
      label: `Term ${index}`,
      is_obsolete: false,
    }));
    const edges = [
      ...Array.from({ length: MAX_RENDERED_GRAPH_EDGES + 2 }, (_, index) => ({
        source: `term-${(index % (MAX_RENDERED_GRAPH_NODES - 1)) + 1}`,
        target: `term-${Math.floor(index / (MAX_RENDERED_GRAPH_NODES - 1)) + 1}`,
        label: "is_a",
      })),
      { source: root, target: `term-${MAX_RENDERED_GRAPH_NODES + 1}`, label: "omitted" },
    ];

    const elements = boundedCytoscapeElements({
      ontology: "go",
      root_iri: root,
      nodes,
      edges,
      truncated: true,
    });

    expect(elements.nodes).toHaveLength(MAX_RENDERED_GRAPH_NODES);
    expect(elements.edges).toHaveLength(MAX_RENDERED_GRAPH_EDGES);
    expect(elements.edges.every((edge) => edge.data.target !== `term-${MAX_RENDERED_GRAPH_NODES + 1}`)).toBe(true);
    expect(elements.nodes[0]?.data.root).toBe(true);
  });
});
