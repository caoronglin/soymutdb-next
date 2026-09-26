import { describe, expect, it } from "vitest";
import {
  IntervalFeatureReader,
  QuantitativeReader,
  createTrackDataSource,
  normalizeBigBedFeatures,
  normalizeQuantFeatures,
  parseBigBedRest,
} from "@soymutdb/genome-data";
import {
  ASSEMBLIES,
  bigBedFeatureTrack,
  featureTrack,
  memoryProvider,
  quantitativeTrack,
  referenceTrack,
} from "./support";

type QuantFeature = Parameters<typeof normalizeQuantFeatures>[0][number];
type BedFeature = Parameters<typeof normalizeBigBedFeatures>[0][number];

describe("ablation scenario 4: quantitative/interval", () => {
  it("normalizes BigWig and BigBed feature units", () => {
    const quantFeatures = [
      { start: 0, end: 10, score: 3.5 },
      { start: 10, end: 20 },
    ] as unknown as QuantFeature[];
    expect(normalizeQuantFeatures(quantFeatures, "v4", "chr01")).toEqual([
      { assemblyKey: "v4", refName: "chr01", start: 0, end: 10, score: 3.5 },
      { assemblyKey: "v4", refName: "chr01", start: 10, end: 20, score: 0 },
    ]);

    const bedFeatures = [
      { start: 5, end: 9, rest: "repeatA 42 +", uniqueId: "bb1" },
    ] as unknown as BedFeature[];
    const normalized = normalizeBigBedFeatures(bedFeatures, {
      assemblyKey: "v4",
      refName: "chr01",
      featureType: "repeat",
    });
    expect(normalized[0]).toMatchObject({
      id: "bb1",
      type: "repeat",
      name: "repeatA",
      score: 42,
      strand: "+",
      start: 5,
      end: 9,
    });

    expect(parseBigBedRest("name 7 - extra")).toMatchObject({
      name: "name",
      score: 7,
      strand: "-",
      fields: ["name", "7", "-", "extra"],
    });
  });

  it("factory dispatches quantitative/interval/feature tracks by adapter type", () => {
    const provider = memoryProvider([]);
    const quant = createTrackDataSource(quantitativeTrack(), { provider, assemblies: ASSEMBLIES });
    expect(quant.kind).toBe("quantitative");
    expect(quant.reader).toBeInstanceOf(QuantitativeReader);

    const interval = createTrackDataSource(bigBedFeatureTrack(), { provider, assemblies: ASSEMBLIES });
    expect(interval.kind).toBe("interval");
    expect(interval.reader).toBeInstanceOf(IntervalFeatureReader);

    const feature = createTrackDataSource(featureTrack(), { provider, assemblies: ASSEMBLIES });
    expect(feature.kind).toBe("feature");

    const sequence = createTrackDataSource(referenceTrack(), { provider, assemblies: ASSEMBLIES });
    expect(sequence.kind).toBe("reference-sequence");
  });
});
