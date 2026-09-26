import { describe, expect, it } from "vitest";

import type { AssemblyContext } from "../assembly";
import { GenomeDataError } from "../errors";
import type { FileProvider } from "../file-provider";
import {
  IntervalFeatureReader,
  normalizeBigBedFeatures,
  parseBigBedRest,
} from "./interval";
import {
  FailFirstOpenProvider,
  fixtureLocation,
  fixtureProvider,
} from "./test-fixtures";

const assembly: AssemblyContext = {
  key: "v5.0",
  name: "Wm82v5.0",
  refNames: ["chr01"],
};

function makeReader(provider: FileProvider = fixtureProvider([])): IntervalFeatureReader {
  return new IntervalFeatureReader({
    provider,
    assembly,
    trackId: "repeats",
    bigBed: fixtureLocation("repeats.bb"),
    featureType: "repeat",
  });
}

// A minimal valid bigBed (chr01:0-10, BED3, blockSize=1, itemsPerSlot=1)
// generated once with Biopython's Bio.Align.bigbed.AlignmentWriter. The repo
// ships no offline bigBed writer, so this is the only decodeable bigBed
// payload in the test suite; it lets the retry test reach a successful read.
const BIGBED_BASE64 =
  "6/KJhwQAAQB0AgAAAAAAAKUCAAAAAAAAuwIAAAAAAAADAAMAMAEAAAAAAAAMAgAAAAAAACAAAAA0AgAAAAAAAAoAAAAAAAAADwMAAAAAAAAyAwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHRhYmxlIGJlZAoiQnJvd3NlciBFeHRlbnNpYmxlIERhdGEiCigKICAgc3RyaW5nIGNocm9tOyAgICAgICAgICJSZWZlcmVuY2Ugc2VxdWVuY2UgY2hyb21vc29tZSBvciBzY2FmZm9sZCIKICAgdWludCAgIGNocm9tU3RhcnQ7ICAgICJTdGFydCBwb3NpdGlvbiBpbiBjaHJvbW9zb21lIgogICB1aW50ICAgY2hyb21FbmQ7ICAgICAgIkVuZCBwb3NpdGlvbiBpbiBjaHJvbW9zb21lIgopCgAKAAAAAAAAAAAAAAAAAPA/AAAAAAAA8D8AAAAAAAAkQAAAAAAAACRAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJGMyngBAAAABQAAAAgAAAABAAAAAAAAAAAAAAAAAAAAAQABAGNocjAxAAAAADwAAAABAAAAAAAAAHicY2CAAC4QAQAAPwAL4KxoJAEAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAoAAAC7AgAAAAAAAAEAAAAAAAAAAQABAAAAAAAAAAAAAAAAAAoAAACtAgAAAAAAAA4AAAAAAAAAAQAAAHicY2CAAC4oZmBosIdgBUcQBgAVyAJVeJwDAAAAAAHgrGgkAQAAAAEAAAAAAAAAAAAAAAAAAAAAAAAACgAAADIDAAAAAAAAAQAAAAAAAAABAAEAAAAAAAAAAAAAAAAACgAAABMDAAAAAAAAHwAAAAAAAADr8omH";

describe("parseBigBedRest", () => {
  it("splits the space-separated BED columns", () => {
    expect(parseBigBedRest("repeat01 960 +")).toEqual({
      name: "repeat01",
      score: 960,
      strand: "+",
      fields: ["repeat01", "960", "+"],
    });
  });

  it("tolerates missing or partial rest payloads", () => {
    expect(parseBigBedRest(undefined)).toEqual({ fields: [] });
    expect(parseBigBedRest("solo")).toEqual({ name: "solo", fields: ["solo"] });
    expect(parseBigBedRest("name . ?").fields).toEqual(["name", ".", "?"]);
  });
});

describe("normalizeBigBedFeatures", () => {
  it("maps spans and rest columns to feature records", () => {
    const records = normalizeBigBedFeatures(
      [{ chromId: 0, start: 100, end: 200, rest: "repeat01 960 +" }],
      { assemblyKey: "v5.0", refName: "chr01", featureType: "repeat" },
    );
    expect(records).toEqual([
      {
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 100,
        end: 200,
        id: "repeat01",
        type: "repeat",
        name: "repeat01",
        strand: "+",
        score: 960,
        attributes: { rest: "repeat01 960 +" },
      },
    ]);
  });

  it("falls back to uniqueId then coordinates for the id", () => {
    const [withUniqueId] = normalizeBigBedFeatures(
      [{ chromId: 0, start: 1, end: 2, uniqueId: "bb-1", rest: "x" }],
      { assemblyKey: "v5.0", refName: "chr01", featureType: "feature" },
    );
    expect(withUniqueId.id).toBe("bb-1");
    const [withoutName] = normalizeBigBedFeatures(
      [{ chromId: 0, start: 1, end: 2 }],
      { assemblyKey: "v5.0", refName: "chr01", featureType: "feature" },
    );
    expect(withoutName.id).toBe("chr01:1-2");
    expect(withoutName.attributes).toBeUndefined();
  });
});

describe("IntervalFeatureReader", () => {
  it("rejects a cross-assembly region", async () => {
    await expect(
      makeReader().getFeatures({ assemblyKey: "v4.0", refName: "chr01", start: 0, end: 10 }),
    ).rejects.toMatchObject({ code: "assembly-mismatch" });
  });

  it("returns no features for an empty region without reading the file", async () => {
    const records = await makeReader(fixtureProvider([])).getFeatures({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 0,
    });
    expect(records).toEqual([]);
  });

  it("wraps a missing BigBed file as a fetch error", async () => {
    await expect(
      makeReader(fixtureProvider([])).getFeatures({
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 0,
        end: 10,
      }),
    ).rejects.toMatchObject({ code: "fetch" });
  });

  it("retries the open after a failed open and then succeeds", async () => {
    const inner = fixtureProvider([]);
    inner.add(fixtureLocation("repeats.bb"), Buffer.from(BIGBED_BASE64, "base64"));
    const provider = new FailFirstOpenProvider(inner);
    const reader = makeReader(provider);
    const region = { assemblyKey: "v5.0", refName: "chr01", start: 0, end: 10 };
    const first = await reader.getFeatures(region).catch((error: unknown) => error);
    expect(first).toBeInstanceOf(GenomeDataError);
    expect(first).toMatchObject({ code: "fetch" });
    const openedAfterFailure = provider.openCount;
    const features = await reader.getFeatures(region);
    expect(features).toHaveLength(1);
    expect(features[0]).toMatchObject({
      assemblyKey: "v5.0",
      refName: "chr01",
      start: 0,
      end: 10,
      type: "repeat",
    });
    expect(provider.openCount).toBeGreaterThan(openedAfterFailure);
  });

  // No offline BigBed writer exists in this repo; see the quantitative test
  // for the rationale. This still covers header parsing and error mapping.
  it("maps an undecodable BigBed payload to a parse error", async () => {
    const provider = fixtureProvider([]);
    provider.add(fixtureLocation("repeats.bb"), "not a bigbed file");
    await expect(
      makeReader(provider).getFeatures({
        assemblyKey: "v5.0",
        refName: "chr01",
        start: 0,
        end: 10,
      }),
    ).rejects.toMatchObject({ code: "parse" });
  });
});
