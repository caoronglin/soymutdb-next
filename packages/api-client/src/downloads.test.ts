/**
 * Tests for downloads API functions.
 *
 * Mocks the http client and verifies correct path/params for each function.
 */

import { http } from "./client";
import { getDownloadFiles, getDownloadUrl } from "./downloads";

vi.mock("./client", () => ({
  http: {
    get: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);

// ---------------------------------------------------------------------------
// getDownloadFiles
// ---------------------------------------------------------------------------
describe("getDownloadFiles", () => {
  it("calls http.get with /content/downloads and empty params when no category", async () => {
    mockGet.mockResolvedValueOnce([]);

    await getDownloadFiles();

    expect(mockGet).toHaveBeenCalledWith("/content/downloads", {
      params: {},
    });
  });

  it("passes category param when provided", async () => {
    mockGet.mockResolvedValueOnce([]);

    await getDownloadFiles("genome");

    expect(mockGet).toHaveBeenCalledWith("/content/downloads", {
      params: { category: "genome" },
    });
  });

  it("returns the download file list", async () => {
    const files = [
      { id: "f1", name: "genome.fa", description: null, file_url: "/files/genome.fa", file_size: 1000, category: "genome", download_count: 5, created_at: "2025-01-01T00:00:00Z" },
    ];
    mockGet.mockResolvedValueOnce(files);

    const result = await getDownloadFiles();

    expect(result).toEqual(files);
  });
});

// ---------------------------------------------------------------------------
// getDownloadUrl
// ---------------------------------------------------------------------------
describe("getDownloadUrl", () => {
  it("calls http.get with file-specific URL path", async () => {
    const mockResponse = { url: "https://cdn.example.com/file", expires_in: 3600 };
    mockGet.mockResolvedValueOnce(mockResponse);

    const result = await getDownloadUrl("file-123");

    expect(mockGet).toHaveBeenCalledWith("/content/downloads/file-123/url");
    expect(result).toEqual(mockResponse);
  });
});
