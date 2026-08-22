import { http } from "./auth";
import {
  uploadPresign,
  type UploadPresignRequest,
  type UploadPresignResponse,
} from "./admin-uploads";

vi.mock("./auth", () => ({
  http: {
    post: vi.fn(),
  },
}));

const mockPost = vi.mocked(http.post);

describe("admin uploads client", () => {
  beforeEach(() => {
    mockPost.mockReset();
  });

  it("keeps the handwritten request and multipart POST response types in sync", () => {
    expectTypeOf<UploadPresignRequest>().toEqualTypeOf<{
      filename: string;
      purpose?: string;
      size: number;
      content_type: string;
      checksum_sha256: string;
    }>();
    expectTypeOf<UploadPresignResponse["upload_method"]>().toEqualTypeOf<"POST">();
    expectTypeOf<UploadPresignResponse["upload_fields"]>().toEqualTypeOf<
      Record<string, string>
    >();
  });

  it("POSTs the complete signed-upload declaration", async () => {
    const body: UploadPresignRequest = {
      filename: "cover.png",
      purpose: "news",
      size: 4,
      content_type: "image/png",
      checksum_sha256:
        "9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a",
    };
    const response = {
      upload_url: "https://storage.example.test/public",
      upload_method: "POST" as const,
      upload_fields: { key: "uploads/news/cover.png", policy: "signed" },
      object_key: "uploads/news/cover.png",
      public_url: "https://cdn.example.test/uploads/news/cover.png",
      expires_in: 3600,
    };
    mockPost.mockResolvedValueOnce(response);

    await expect(uploadPresign(body)).resolves.toEqual(response);

    expect(mockPost).toHaveBeenCalledWith("/admin/uploads/presign", {
      json: body,
    });
  });
});
