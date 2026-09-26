/**
 * Contract tests for locus-box resolution (coordinates + gene-ID search), the
 * reference-file location helper backing refNames loading, and the built-in
 * JBrowse track definitions (including the BAM alignment track).
 *
 * Run with: node --test locus-search.test.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALIGNMENT_TRACK_ID,
  ALL_TRACKS,
  DEFAULT_ASSEMBLY,
  DEFAULT_TRACKS,
  buildJBrowseConfig,
  sequenceFileLocations,
  validateTrackTypes,
} from "./src/config.ts";
import { parseTextSearchLabel, resolveLocusInput } from "./src/gene-search.ts";

// ---------------------------------------------------------------------------
// resolveLocusInput
// ---------------------------------------------------------------------------

test("resolves a coordinate string without consulting the gene searcher", async () => {
  let called = 0;
  const result = await resolveLocusInput("chr01:1,000-1,000,000", {
    lookupGene: async () => {
      called += 1;
      return null;
    },
  });
  assert.deepEqual(result, {
    kind: "coordinate",
    locus: { refName: "chr01", start: 1000, end: 1000000 },
  });
  assert.equal(called, 0);
});

test("resolves a gene ID through the injected searcher", async () => {
  const seen = [];
  const result = await resolveLocusInput("AT1G01010", {
    lookupGene: async (query) => {
      seen.push(query);
      return { gene_id: "AT1G01010", chromosome: "chr01", start_pos: 1, end_pos: 60 };
    },
  });
  assert.deepEqual(seen, ["AT1G01010"]);
  assert.deepEqual(result, {
    kind: "gene",
    gene: { refName: "chr01", start: 1, end: 60, geneId: "AT1G01010" },
  });
});

test("reports not-found when the gene searcher returns null", async () => {
  const result = await resolveLocusInput("  AT1G99999  ", { lookupGene: async () => null });
  assert.deepEqual(result, { kind: "not-found", query: "AT1G99999" });
});

test("reports not-found for blank input without searching", async () => {
  let called = 0;
  const result = await resolveLocusInput("   ", {
    lookupGene: async () => {
      called += 1;
      return null;
    },
  });
  assert.equal(result.kind, "not-found");
  assert.equal(called, 0);
});

test("surfaces a lookup failure as an explicit error result", async () => {
  const result = await resolveLocusInput("AT1G01010", {
    lookupGene: async () => {
      throw new Error("api unavailable");
    },
  });
  assert.deepEqual(result, {
    kind: "error",
    query: "AT1G01010",
    message: "api unavailable",
  });
});

// ---------------------------------------------------------------------------
// parseTextSearchLabel
// ---------------------------------------------------------------------------

test("decodes a Trix payload into 1-based coordinates", () => {
  assert.deepEqual(parseTextSearchLabel("chr01:1..60|gene:AT1G01010|AT1G01010"), {
    refName: "chr01",
    start: 1,
    end: 60,
  });
  assert.deepEqual(parseTextSearchLabel("chr02:41-60"), { refName: "chr02", start: 41, end: 60 });
});

test("returns null for a payload without a location", () => {
  assert.equal(parseTextSearchLabel("gene:AT1G01010"), null);
  assert.equal(parseTextSearchLabel(""), null);
});

// ---------------------------------------------------------------------------
// sequenceFileLocations
// ---------------------------------------------------------------------------

test("extracts the FASTA/FAI/GZI URIs from a BgzipFastaAdapter assembly", () => {
  const locations = sequenceFileLocations(DEFAULT_ASSEMBLY);
  assert.ok(locations);
  assert.match(locations.fasta, /Wm82_v4\.0\.fa\.gz$/);
  assert.match(locations.fai, /\.fai$/);
  assert.match(locations.gzi, /\.gzi$/);
});

test("returns null for an assembly whose reference adapter is unsupported", () => {
  const assembly = {
    ...DEFAULT_ASSEMBLY,
    sequence: {
      ...DEFAULT_ASSEMBLY.sequence,
      adapter: { type: "TwoBitAdapter", twoBitLocation: { uri: "/x.2bit" } },
    },
  };
  assert.equal(sequenceFileLocations(assembly), null);
});

// ---------------------------------------------------------------------------
// Track configuration
// ---------------------------------------------------------------------------

test("registers a BamAdapter alignment track bound to the default assembly", () => {
  const track = ALL_TRACKS.find((candidate) => candidate.trackId === ALIGNMENT_TRACK_ID);
  assert.ok(track, "alignment track should be in ALL_TRACKS");
  assert.equal(track.type, "AlignmentsTrack");
  assert.equal(track.adapter.type, "BamAdapter");
  assert.deepEqual(track.assemblyNames, [DEFAULT_ASSEMBLY.name]);
  assert.match(track.adapter.bamLocation.uri, /\/alignment\.bam$/);
  assert.equal(track.adapter.index.indexType, "BAI");
  assert.match(track.adapter.index.location.uri, /\/alignment\.bam\.bai$/);
});

test("validateTrackTypes keeps the BamAdapter alignment track", () => {
  const validated = validateTrackTypes(ALL_TRACKS);
  const track = validated.find((candidate) => candidate.trackId === ALIGNMENT_TRACK_ID);
  assert.ok(track, "alignment track should survive validateTrackTypes");
  assert.equal(track.type, "AlignmentsTrack");
  assert.equal(track.adapter.type, "BamAdapter");
});

test("buildJBrowseConfig keeps the alignment track discoverable but off by default", () => {
  const config = buildJBrowseConfig();
  const track = config.tracks.find((candidate) => candidate.trackId === ALIGNMENT_TRACK_ID);
  assert.ok(track, "alignment track should survive buildJBrowseConfig");
  assert.equal(track.type, "AlignmentsTrack");
  assert.deepEqual(track.assemblyNames, [DEFAULT_ASSEMBLY.name]);
  // Explicit visibility choice: available for selection, not fetched on load.
  assert.equal(DEFAULT_TRACKS.includes(ALIGNMENT_TRACK_ID), false);
});
