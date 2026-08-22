import { http } from "./auth";
import {
  adminImportsApi,
  type ImportInspectionRequest,
  type ImportInspectionResponse,
} from "./admin-imports";

vi.mock("./auth", () => ({
  http: {
    post: vi.fn(),
  },
}));

const mockPost = vi.mocked(http.post);

const request: ImportInspectionRequest = {
  filename: "genes.tsv",
  content_base64: "Z2VuZV9pZAo=",
};

const response: ImportInspectionResponse = {
  schema_version: 1,
  module_key: "genes",
  filename: "genes.tsv",
  format: "tsv",
  encoding: "utf-8",
  delimiter: "\t",
  sheet_name: null,
  headers: ["gene_id"],
  row_count: 1,
  rows: [{ gene_id: "G1" }],
  truncated: false,
  checksum_sha256:
    "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a",
  validation: { ok: true, error_count: 0, errors: [] },
};

describe("admin import inspection client", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it.each(["inspect", "validate"] as const)(
    "POSTs a bounded file preview to the %s endpoint",
    async (action) => {
      mockPost.mockResolvedValueOnce(response);

      await expect(
        adminImportsApi[action]("genes", request),
      ).resolves.toEqual(response);
      expect(mockPost).toHaveBeenCalledWith(`/admin/modules/genes/${action}`, {
        json: request,
      });
    },
  );
});
