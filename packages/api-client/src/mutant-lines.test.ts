import { afterEach, describe, expect, it, vi } from "vitest";
import { http } from "./auth";
import {
  getMutantLine,
  getMutantLinePhenotypes,
  isMutantLineId,
  listMutantLines,
} from "./mutant-lines";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

describe("mutant line client contract", () => {
  afterEach(() => vi.clearAllMocks());

  it("accepts canonical public_id formats", () => {
    expect(isMutantLineId("SM7K3ZQ9P2A")).toBe(true);
    expect(isMutantLineId("sm7k3zq9p2a")).toBe(true);
    expect(isMutantLineId("SM10AB25")).toBe(true);
    expect(isMutantLineId("line-42")).toBe(true);
    expect(isMutantLineId("42")).toBe(false);
    expect(isMutantLineId("0")).toBe(false);
    expect(isMutantLineId(" SM7K3ZQ9P2A ")).toBe(false);
    expect(isMutantLineId("")).toBe(false);
    expect(isMutantLineId("a".repeat(33))).toBe(false);
  });

  it("uses the canonical mutant endpoints and list parameters", async () => {
    vi.mocked(http.get).mockResolvedValue([]);

    await listMutantLines({ mutagen: "EMS", limit: 20 });
    await getMutantLine("SM7K3ZQ9P2A");
    await getMutantLinePhenotypes("SM7K3ZQ9P2A");

    expect(http.get).toHaveBeenNthCalledWith(1, "/mutants", {
      params: { mutagen: "EMS", limit: 20 },
    });
    expect(http.get).toHaveBeenNthCalledWith(2, "/mutants/SM7K3ZQ9P2A");
    expect(http.get).toHaveBeenNthCalledWith(3, "/mutants/SM7K3ZQ9P2A/phenotypes");
  });
});
