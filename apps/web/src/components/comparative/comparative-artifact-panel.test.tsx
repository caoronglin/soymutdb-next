// @vitest-environment jsdom
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ComparativeArtifact } from "@soymutdb/api-client";

vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock("../../lib/release-scope", () => ({ useReleaseId: () => "2026.09" }));

const api = vi.hoisted(() => ({
  requestArtifact: vi.fn(),
  getArtifact: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  requestArtifact: api.requestArtifact,
  getArtifact: api.getArtifact,
}));

import { ComparativeArtifactPanel, isTerminalArtifactState } from "./comparative-artifact-panel";

function artifact(overrides: Partial<ComparativeArtifact> = {}): ComparativeArtifact {
  return {
    artifact_type: "msa",
    job_id: "11111111-1111-4111-8111-111111111111",
    state: "pending",
    method: "mafft",
    input_sha256: "abc123frozen",
    input_member_ids: ["Gm01g00010", "Gm02g00020"],
    download_url: null,
    error_message: null,
    created_at: "2026-11-04T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof ComparativeArtifactPanel>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <ComparativeArtifactPanel familyId={7} assemblyId={2} pollIntervalMs={5} {...props} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  api.requestArtifact.mockReset();
  api.getArtifact.mockReset();
});

describe("isTerminalArtifactState", () => {
  it("treats only succeeded and failed as terminal", () => {
    expect(isTerminalArtifactState("succeeded")).toBe(true);
    expect(isTerminalArtifactState("failed")).toBe(true);
    expect(isTerminalArtifactState("pending")).toBe(false);
    expect(isTerminalArtifactState("running")).toBe(false);
    expect(isTerminalArtifactState(undefined)).toBe(false);
  });
});

describe("ComparativeArtifactPanel — pending", () => {
  it("submits a job, polls it, and shows the frozen input hash while running", async () => {
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(artifact({ state: "running" }));

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));

    await waitFor(() => expect(screen.getByTestId("artifact-body")).toBeTruthy());
    expect(api.requestArtifact).toHaveBeenCalledWith(
      expect.objectContaining({ family_id: 7, artifact_type: "msa", method: "mafft", assembly_id: 2 }),
    );

    // A pending/running artifact must still state which input set it describes.
    expect(screen.getByTestId("artifact-input-sha").textContent).toBe("abc123frozen");
    expect(screen.getByTestId("artifact-input-members").textContent).toBe("2");
    expect(screen.queryByTestId("artifact-download")).toBeNull();
    expect(screen.queryByTestId("artifact-error")).toBeNull();
    expect(screen.getByTestId("artifact-body").querySelector('[data-artifact-state="running"]')).toBeTruthy();
  });
});

describe("ComparativeArtifactPanel — succeeded", () => {
  it("offers a download only when the worker published a URL", async () => {
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(
      artifact({ state: "succeeded", download_url: "https://files.example/msa.txt" }),
    );

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));

    await waitFor(() => {
      expect(screen.getByTestId("artifact-download").getAttribute("href")).toBe(
        "https://files.example/msa.txt",
      );
    });
    expect(screen.getByTestId("artifact-input-sha").textContent).toBe("abc123frozen");
    expect(screen.queryByTestId("artifact-error")).toBeNull();
  });

  it("renders no download affordance at all when download_url is null", async () => {
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(
      artifact({ state: "succeeded", download_url: null }),
    );

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));

    await waitFor(() => expect(screen.getByTestId("artifact-download-missing")).toBeTruthy());
    // A null href must never be dressed as a button: that is a dead link.
    expect(screen.queryByTestId("artifact-download")).toBeNull();
    expect(screen.getByTestId("artifact-body").querySelector("a[href]")).toBeNull();
  });
});

describe("ComparativeArtifactPanel — failed", () => {
  it("shows the worker's error message verbatim", async () => {
    const message = "mafft is not installed on this worker";
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(artifact({ state: "failed", error_message: message }));

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));

    await waitFor(() => expect(screen.getByTestId("artifact-error")).toBeTruthy());
    // Verbatim, not paraphrased: the operator needs the sentence the worker wrote.
    expect(screen.getByTestId("artifact-error").textContent).toBe(message);
    expect(screen.queryByTestId("artifact-download")).toBeNull();
  });

  it("stops polling once the job reaches a terminal state", async () => {
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(artifact({ state: "failed", error_message: "boom" }));

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));
    await waitFor(() => expect(screen.getByTestId("artifact-error")).toBeTruthy());

    const callsAtTerminal = api.getArtifact.mock.calls.length;
    await new Promise((resolve) => setTimeout(resolve, 60));
    // The interval keeps firing while a job is in flight; it must not after.
    expect(api.getArtifact.mock.calls.length).toBe(callsAtTerminal);
  });
});

describe("ComparativeArtifactPanel — lifecycle", () => {
  it("stops polling when the page is left", async () => {
    api.requestArtifact.mockResolvedValue(artifact());
    api.getArtifact.mockResolvedValue(artifact({ state: "running" }));

    const { unmount } = renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));
    await waitFor(() => expect(api.getArtifact).toHaveBeenCalled());

    const before = api.getArtifact.mock.calls.length;
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(api.getArtifact.mock.calls.length).toBe(before);
  });

  it("surfaces a rejected request instead of pretending a job started", async () => {
    api.requestArtifact.mockRejectedValue(new Error("Unknown artifact method 'blast'"));

    renderPanel();
    await userEvent.click(screen.getByTestId("request-msa"));

    await waitFor(() => expect(screen.getByTestId("artifact-request-error")).toBeTruthy());
    expect(screen.getByTestId("artifact-request-error").textContent).toContain(
      "Unknown artifact method 'blast'",
    );
    expect(api.getArtifact).not.toHaveBeenCalled();
  });
});
