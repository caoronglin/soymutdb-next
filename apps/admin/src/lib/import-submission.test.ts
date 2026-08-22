import { describe, expect, it } from "vitest";
import {
  buildImportSubmission,
  createImportIdempotencyKey,
} from "./import-submission";

describe("module import submission contract", () => {
  it("includes an explicit release and idempotency key in every module request", () => {
    const request = buildImportSubmission({
      filename: "genes.tsv",
      type: "module_tsv",
      objectKey: "data/1/genes.tsv",
      moduleKey: "genes",
      checksum: "a".repeat(64),
      releaseIdInput: "42",
      idempotencyKey: "import-42",
    });

    expect(request).toMatchObject({
      filename: "genes.tsv",
      type: "module_tsv",
      object_key: "data/1/genes.tsv",
      module_key: "genes",
      checksum: "a".repeat(64),
      release_id: 42,
      idempotency_key: "import-42",
    });
  });

  it("rejects missing or non-canonical module release ids before upload submission", () => {
    const request = {
      filename: "genes.tsv",
      type: "module_tsv" as const,
      objectKey: "data/1/genes.tsv",
      moduleKey: "genes",
      checksum: "a".repeat(64),
      idempotencyKey: "import-missing-release",
    };

    expect(() => buildImportSubmission({ ...request, releaseIdInput: "" })).toThrow(
      "A positive release ID is required",
    );
    expect(() => buildImportSubmission({ ...request, releaseIdInput: "1.5" })).toThrow(
      "A positive release ID is required",
    );
  });

  it("generates a non-empty idempotency key for a new import intent", () => {
    expect(createImportIdempotencyKey()).toMatch(/^import-/);
  });
});
