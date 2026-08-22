/**
 * First-party, one-hop OLS4 relationship graph.
 *
 * The server is authoritative for the graph cap. This component repeats the
 * cap before Cytoscape is loaded so an unexpected API response cannot create
 * an unbounded client-side canvas.
 */

import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ontologyApi,
  type OntologyRelationshipGraphResponse,
} from "@soymutdb/api-client";

export const MAX_RENDERED_GRAPH_NODES = 50;
export const MAX_RENDERED_GRAPH_EDGES = 100;

type CytoscapeNodeElement = {
  data: {
    id: string;
    label: string;
    root: boolean;
    obsolete: boolean;
  };
};

type CytoscapeEdgeElement = {
  data: {
    id: string;
    source: string;
    target: string;
    label: string;
  };
};

export interface BoundedCytoscapeElements {
  nodes: CytoscapeNodeElement[];
  edges: CytoscapeEdgeElement[];
  truncated: boolean;
}

function clampLimit(value: number | undefined, fallback: number, max: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(1, Math.floor(value ?? fallback)));
}

function nodeLabel(iri: string, label: string | null): string {
  if (label?.trim()) return label.trim();
  const fragment = iri.split(/[/#]/).filter(Boolean).at(-1);
  return fragment || iri;
}

/**
 * Normalize once before graph rendering. Edges are retained only when both
 * endpoints survived the node cap, preventing Cytoscape from materialising
 * implicit nodes for omitted relationships.
 */
export function boundedCytoscapeElements(
  graph: OntologyRelationshipGraphResponse,
): BoundedCytoscapeElements {
  const indexedNodes = new Map<string, OntologyRelationshipGraphResponse["nodes"][number]>();
  for (const node of graph.nodes) {
    if (node.iri && !indexedNodes.has(node.iri)) indexedNodes.set(node.iri, node);
  }

  const selectedIds = new Set<string>();
  const nodes: CytoscapeNodeElement[] = [];
  let locallyTruncated = false;
  const addNode = (node: OntologyRelationshipGraphResponse["nodes"][number]) => {
    if (selectedIds.has(node.iri)) return;
    if (selectedIds.size >= MAX_RENDERED_GRAPH_NODES) {
      locallyTruncated = true;
      return;
    }
    selectedIds.add(node.iri);
    nodes.push({
      data: {
        id: node.iri,
        label: nodeLabel(node.iri, node.label),
        root: node.iri === graph.root_iri,
        obsolete: node.is_obsolete,
      },
    });
  };

  const root = indexedNodes.get(graph.root_iri);
  if (root) addNode(root);
  for (const node of indexedNodes.values()) addNode(node);

  const seenEdges = new Set<string>();
  const edges: CytoscapeEdgeElement[] = [];
  for (const edge of graph.edges) {
    if (edges.length >= MAX_RENDERED_GRAPH_EDGES) {
      locallyTruncated = true;
      break;
    }
    if (!selectedIds.has(edge.source) || !selectedIds.has(edge.target)) {
      locallyTruncated = true;
      continue;
    }
    const key = `${edge.source}\u0000${edge.target}\u0000${edge.label ?? ""}`;
    if (seenEdges.has(key)) continue;
    seenEdges.add(key);
    edges.push({
      data: {
        id: `edge-${edges.length}`,
        source: edge.source,
        target: edge.target,
        label: edge.label ?? "related to",
      },
    });
  }
  return { nodes, edges, truncated: graph.truncated || locallyTruncated };
}

export interface OntologyRelationshipGraphProps {
  ontology: string;
  iri: string;
  maxNodes?: number;
  maxEdges?: number;
}

export function OntologyRelationshipGraph({
  ontology,
  iri,
  maxNodes,
  maxEdges,
}: OntologyRelationshipGraphProps) {
  const hostRef = React.useRef<HTMLDivElement>(null);
  const [rendererError, setRendererError] = React.useState(false);
  const limits = React.useMemo(
    () => ({
      maxNodes: clampLimit(maxNodes, 24, MAX_RENDERED_GRAPH_NODES),
      maxEdges: clampLimit(maxEdges, 32, MAX_RENDERED_GRAPH_EDGES),
    }),
    [maxEdges, maxNodes],
  );
  const selectElements = React.useCallback(
    (graph: OntologyRelationshipGraphResponse) => boundedCytoscapeElements(graph),
    [],
  );
  const query = useQuery({
    queryKey: ["ontology-relationship-graph", ontology, iri, limits.maxNodes, limits.maxEdges],
    queryFn: () =>
      ontologyApi.relationshipGraph({
        ontology,
        iri,
        max_nodes: limits.maxNodes,
        max_edges: limits.maxEdges,
      }),
    staleTime: 60_000,
    select: selectElements,
  });
  const elements = query.data ?? null;

  React.useEffect(() => {
    if (typeof window === "undefined" || !elements || !hostRef.current) return;
    let disposed = false;
    let instance: { destroy: () => void } | undefined;
    setRendererError(false);

    // Cytoscape is a separate chunk and is requested only for an active graph.
    void import("cytoscape")
      .then(({ default: cytoscape }) => {
        if (disposed || !hostRef.current) return;
        instance = cytoscape({
          container: hostRef.current,
          elements: [...elements.nodes, ...elements.edges],
          style: [
            {
              selector: "node",
              style: {
                "background-color": "#356859",
                label: "data(label)",
                color: "#1f2937",
                "font-size": "11px",
                "text-wrap": "wrap",
                "text-max-width": "120px",
              },
            },
            {
              selector: "node[root]",
              style: { "background-color": "#d97706", "border-width": 3, "border-color": "#92400e" },
            },
            {
              selector: "node[obsolete]",
              style: { "background-color": "#9ca3af", "line-style": "dashed" },
            },
            {
              selector: "edge",
              style: {
                width: 1.5,
                "line-color": "#94a3b8",
                "target-arrow-color": "#94a3b8",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
              },
            },
          ],
          layout: { name: "breadthfirst", directed: true, padding: 24, animate: false },
        });
      })
      .catch(() => {
        if (!disposed) setRendererError(true);
      });

    return () => {
      disposed = true;
      instance?.destroy();
    };
  }, [elements]);

  if (query.isPending) {
    return <div role="status" className="h-72 animate-pulse rounded-xl border bg-muted/30" />;
  }
  if (query.isError || rendererError) {
    return (
      <div role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive">
        Ontology relationship graph is unavailable.
      </div>
    );
  }
  if (!elements || elements.nodes.length === 0) {
    return <div className="rounded-xl border p-4 text-sm text-muted-foreground">No ontology relationships found.</div>;
  }

  return (
    <section aria-label="Ontology relationship graph" className="rounded-xl border bg-card p-3">
      {elements.truncated ? (
        <p className="mb-2 text-xs text-muted-foreground">
          Graph is limited to {limits.maxNodes} nodes and {limits.maxEdges} relationships.
        </p>
      ) : null}
      <div ref={hostRef} data-testid="ontology-relationship-graph" className="h-72 w-full" />
    </section>
  );
}
