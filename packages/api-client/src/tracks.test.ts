import { http } from "./auth";
import * as tracks from "./tracks";
import { fetchTracks, getTrack, type Track } from "./tracks";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);
const mockPatch = vi.mocked(http.patch);
const mockDelete = vi.mocked(http.delete);

const READY_TRACK: Track = {
  id: "7",
  name: "Glycine max v5 variants",
  description: null,
  track_type: "variant",
  file_format: "vcf",
  assembly_id: "2",
  category_id: null,
  owner_id: null,
  visibility: "public",
  status: "ready",
  created_at: "2026-10-02T08:30:00Z",
};

describe("tracks client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
    mockDelete.mockReset();
  });

  it("reads the collection as a bare list, not a paginated envelope", async () => {
    mockGet.mockResolvedValueOnce([READY_TRACK]);

    await expect(fetchTracks()).resolves.toEqual([READY_TRACK]);
    expect(mockGet).toHaveBeenCalledWith("/tracks", { params: undefined });
  });

  it("scopes the list by assembly and category ids the backend implements", async () => {
    mockGet.mockResolvedValueOnce([READY_TRACK]);

    await fetchTracks({ assembly_id: 2, category_id: 5 });
    expect(mockGet).toHaveBeenCalledWith("/tracks", {
      params: { assembly_id: 2, category_id: 5 },
    });
  });

  it("reads one track by id", async () => {
    mockGet.mockResolvedValueOnce(READY_TRACK);

    await expect(getTrack("7")).resolves.toEqual(READY_TRACK);
    expect(mockGet).toHaveBeenCalledWith("/tracks/7");
  });

  // The API registers no track write routes (see the module comment). These
  // exports are gone; the assertions stop them being reintroduced and quietly
  // re-added to the route-visibility allowlist instead of being built in the
  // backend.
  it("does not expose mutations the API does not serve", () => {
    for (const name of [
      "createTrack",
      "updateTrack",
      "deleteTrack",
      "reindexTrack",
      "toggleTrackVisibility",
      "getTrackUploadUrl",
      "fetchAllTracks",
    ]) {
      expect(tracks).not.toHaveProperty(name);
    }
  });

  it("never issues a mutating request", async () => {
    mockGet.mockResolvedValue([]);

    await fetchTracks();
    await getTrack(7);

    expect(mockPost).not.toHaveBeenCalled();
    expect(mockPatch).not.toHaveBeenCalled();
    expect(mockDelete).not.toHaveBeenCalled();
  });
});
