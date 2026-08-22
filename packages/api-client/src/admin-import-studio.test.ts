import { http } from "./auth";
import {
  adminImportStudioApi,
  type DatasetVersionResponse,
  type ImportDraftResponse,
} from "./admin-import-studio";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);
const mockPut = vi.mocked(http.put);

function version(): DatasetVersionResponse {
  return {
    id: "version-1",
    dataset_id: 1,
    version: 1,
    filename: "genes.tsv",
    object_key: "s3://bucket/genes.tsv",
    checksum_sha256: "a".repeat(64),
    source: "NCBI RefSeq",
    license: "CC0",
    mime_type: "text/tab-separated-values",
    row_count: 10,
    column_count: 5,
    source_objects: [],
    manifest: null,
    status: "draft",
    created_at: null,
    updated_at: null,
  };
}

function draft(): ImportDraftResponse {
  return {
    id: "draft-1",
    dataset_version_id: "version-1",
    module_key: null,
    filename: "genes.tsv",
    object_key: "s3://bucket/genes.tsv",
    checksum_sha256: "a".repeat(64),
    source: "NCBI RefSeq",
    license: "CC0",
    mime_type: "text/tab-separated-values",
    row_count: 10,
    column_count: 5,
    field_mapping: [],
    validation: {},
    status: "draft",
    committed_at: null,
    created_at: null,
    updated_at: null,
  };
}

describe("admin import studio client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPut.mockReset();
  });

  it("creates an immutable dataset version and draft", async () => {
    mockPost.mockResolvedValueOnce(version()).mockResolvedValueOnce(draft());

    await expect(
      adminImportStudioApi.createDatasetVersion({
        dataset_id: 1,
        filename: "genes.tsv",
        object_key: "s3://bucket/genes.tsv",
        checksum_sha256: "a".repeat(64),
        source: "NCBI RefSeq",
        license: "CC0",
        mime_type: "text/tab-separated-values",
        row_count: 10,
        column_count: 5,
        source_objects: [],
      }),
    ).resolves.toEqual(version());
    await expect(
      adminImportStudioApi.createDraft({
        dataset_version_id: "version-1",
        module_key: null,
        row_count: 10,
        column_count: 5,
      }),
    ).resolves.toEqual(draft());
  });

  it("updates mapping, validates, and commits with explicit confirm", async () => {
    mockPut.mockResolvedValueOnce(draft());
    mockPost.mockResolvedValueOnce(draft()).mockResolvedValueOnce(draft());

    const mapping = [
      { source_field: "gene_id", target_field: "id", position: 0, transform: {} },
    ];
    await adminImportStudioApi.updateMapping("draft-1", mapping);
    expect(mockPut).toHaveBeenCalledWith(
      "/admin/imports/studio/drafts/draft-1/mapping",
      { json: { mappings: mapping } },
    );

    await adminImportStudioApi.validate("draft-1", {
      row_count: 10,
      column_count: 5,
      field_mapping: mapping,
    });
    expect(mockPost).toHaveBeenCalledWith(
      "/admin/imports/studio/drafts/draft-1/validate",
      {
        json: { row_count: 10, column_count: 5, field_mapping: mapping },
      },
    );

    await adminImportStudioApi.commit("draft-1", {
      page_id: null,
      source_id: "dataset",
      kind: "dataset",
      config: {},
      confirm: true,
    });
    expect(mockPost).toHaveBeenCalledWith(
      "/admin/imports/studio/drafts/draft-1/commit",
      {
        json: {
          page_id: null,
          source_id: "dataset",
          kind: "dataset",
          config: {},
          confirm: true,
        },
      },
    );
  });
});
