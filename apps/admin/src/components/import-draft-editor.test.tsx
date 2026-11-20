import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImportDraftResponse } from "@soymutdb/api-client";

import { ImportDraftEditor } from "./import-draft-editor";

const api = vi.hoisted(() => ({
  updateMapping: vi.fn(),
  addPatches: vi.fn(),
  validate: vi.fn(),
  commit: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({ adminImportStudioApi: api }));

// The editor is a localized surface; initialize the real catalogs so the
// assertions below read the shipped English copy (and interpolate {{status}}).
await import("@soymutdb/i18n").then(({ initI18n }) => initI18n("en"));

// The admin app compiles TSX with the classic React.createElement factory
// (tsconfig sets jsx: "preserve") and its component modules deliberately do
// not import React, so the identifier must exist globally before first render.
(globalThis as unknown as { React: unknown }).React = React;

const MAPPING = [
  { source_field: "gene_id", target_field: "id", position: 0, transform: {} },
];

const PATCHES = [
  {
    row_key: "row-1",
    column_name: "gene_id",
    old_value: "G1",
    new_value: "G2",
    patch_type: "set" as const,
  },
];

function draft(overrides: Partial<ImportDraftResponse> = {}): ImportDraftResponse {
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
    field_mapping: MAPPING,
    validation: {},
    status: "draft",
    committed_at: null,
    created_at: null,
    updated_at: "2026-08-30T00:00:00Z",
    ...overrides,
  };
}

function renderEditor(
  overrides: Partial<ImportDraftResponse> = {},
  onUpdated = vi.fn(),
) {
  const result = render(
    <ImportDraftEditor draft={draft(overrides)} onUpdated={onUpdated} />,
  );
  return { ...result, onUpdated };
}

function mappingInput(): HTMLTextAreaElement {
  return screen.getByLabelText("Field mapping (JSON array)") as HTMLTextAreaElement;
}

function patchesInput(): HTMLTextAreaElement {
  return screen.getByLabelText("Data patches (JSON array)") as HTMLTextAreaElement;
}

function commitButton(): HTMLElement {
  return screen.getByRole("button", { name: "Confirm and commit draft" });
}

function fillPublicationFields() {
  fireEvent.change(screen.getByLabelText("Publication source id"), {
    target: { value: "dataset" },
  });
  fireEvent.change(screen.getByLabelText("Publication kind"), {
    target: { value: "dataset" },
  });
  fireEvent.change(screen.getByLabelText("Publication config JSON"), {
    target: { value: '{"channel":"test"}' },
  });
}

beforeEach(() => {
  api.updateMapping.mockReset().mockResolvedValue(draft());
  api.addPatches.mockReset().mockResolvedValue(draft());
  api.validate.mockReset().mockResolvedValue(draft({ status: "validated" }));
  api.commit.mockReset().mockResolvedValue(draft({ status: "committed" }));
  vi.stubGlobal("confirm", vi.fn(() => true));
});

describe("ImportDraftEditor rendering", () => {
  it("renders the persisted mapping and validation state from the draft", () => {
    renderEditor({
      field_mapping: MAPPING,
      validation: { ok: true, errors: [] },
    });

    expect(mappingInput().value).toContain('"source_field": "gene_id"');
    expect(screen.getByText(/^Validation state:/)).toHaveTextContent(
      '{"ok":true,"errors":[]}',
    );
  });

  it("keeps a committed draft immutable and says so", () => {
    renderEditor({ status: "committed", committed_at: "2026-08-30T00:00:00Z" });

    expect(
      screen.getByText("This draft is committed; all editing controls are locked."),
    ).toBeInTheDocument();
    expect(mappingInput()).toBeDisabled();
    expect(patchesInput()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save mapping" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save patches" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Validate persisted draft" }),
    ).toBeDisabled();
    expect(screen.getByLabelText("Publication source id")).toBeDisabled();
    expect(commitButton()).toBeDisabled();
  });
});

describe("ImportDraftEditor mapping and patch writes", () => {
  it("saves mapping as the parsed array and refreshes the parent", async () => {
    const { onUpdated } = renderEditor();

    fireEvent.change(mappingInput(), {
      target: { value: JSON.stringify(MAPPING) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    await waitFor(() =>
      expect(api.updateMapping).toHaveBeenCalledWith("draft-1", MAPPING),
    );
    expect(
      await screen.findByText("Mapping saved to the draft."),
    ).toBeInTheDocument();
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("rejects a mapping JSON object without calling the client", async () => {
    renderEditor();

    fireEvent.change(mappingInput(), {
      target: { value: '{"source_field":"gene_id"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Field mapping must be a JSON array.",
    );
    expect(api.updateMapping).not.toHaveBeenCalled();
  });

  it("saves parsed patches and validates with the persisted counts", async () => {
    renderEditor({ row_count: 12, column_count: 3 });

    fireEvent.change(patchesInput(), {
      target: { value: JSON.stringify(PATCHES) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save patches" }));

    await waitFor(() =>
      expect(api.addPatches).toHaveBeenCalledWith("draft-1", PATCHES),
    );

    fireEvent.change(mappingInput(), {
      target: { value: JSON.stringify(MAPPING) },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Validate persisted draft" }),
    );

    await waitFor(() =>
      expect(api.validate).toHaveBeenCalledWith("draft-1", {
        row_count: 12,
        column_count: 3,
        module_key: null,
        field_mapping: MAPPING,
      }),
    );
    expect(
      await screen.findByText("Draft validation completed."),
    ).toBeInTheDocument();
  });

  it("validates a science draft with its persisted module-aware shape", async () => {
    renderEditor({ module_key: "genes", row_count: 150_000, column_count: 100 });
    fireEvent.click(screen.getByRole("button", { name: "Validate persisted draft" }));

    await waitFor(() =>
      expect(api.validate).toHaveBeenCalledWith("draft-1", {
        row_count: 150_000,
        column_count: 100,
        module_key: "genes",
        field_mapping: MAPPING,
      }),
    );
  });

  it("keeps the success notice when the parent refetches the same draft", async () => {
    const { rerender, onUpdated } = renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));
    expect(
      await screen.findByText("Mapping saved to the draft."),
    ).toBeInTheDocument();

    // The parent's refresh returns the same draft with a new revision and the
    // server-normalized mapping. The notice that save produced must survive it.
    rerender(
      <ImportDraftEditor
        draft={draft({
          updated_at: "2026-08-31T00:00:00Z",
          field_mapping: [
            { source_field: "gene_id", target_field: "gene", position: 0, transform: {} },
          ],
        })}
        onUpdated={onUpdated}
      />,
    );

    expect(screen.getByText("Mapping saved to the draft.")).toBeInTheDocument();
    expect(mappingInput().value).toContain('"target_field": "gene"');
  });

  it("surfaces a server error instead of reporting success", async () => {
    api.updateMapping.mockRejectedValueOnce(
      new Error("Import draft draft-1 is validated and cannot be edited"),
    );
    const { onUpdated } = renderEditor();

    fireEvent.click(screen.getByRole("button", { name: "Save mapping" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Import draft draft-1 is validated and cannot be edited",
    );
    expect(screen.queryByText("Mapping saved to the draft.")).toBeNull();
    expect(onUpdated).not.toHaveBeenCalled();
  });
});

describe("ImportDraftEditor publication state machine", () => {
  it("locks mapping, patches, and validation once the draft is validated", () => {
    renderEditor({ status: "validated" });

    // The API rejects every edit/validate on a non-draft row, so the controls
    // must not offer those operations after validation.
    expect(mappingInput()).toBeDisabled();
    expect(patchesInput()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save mapping" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save patches" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Validate persisted draft" }),
    ).toBeDisabled();
    expect(
      screen.getByText(
        "This draft is validated; mapping, patches, and validation are locked. Publication is available below.",
      ),
    ).toBeInTheDocument();
  });

  it("does not offer publication until the draft has been validated", () => {
    const { rerender, onUpdated } = renderEditor({ status: "draft" });
    fillPublicationFields();

    expect(commitButton()).toBeDisabled();

    rerender(
      <ImportDraftEditor
        draft={draft({ status: "validated" })}
        onUpdated={onUpdated}
      />,
    );
    expect(commitButton()).toBeEnabled();
  });

  it("commits only after the operator explicitly confirms", async () => {
    const { onUpdated } = renderEditor({ status: "validated" });
    fillPublicationFields();
    const confirm = vi.mocked(window.confirm);
    confirm.mockReturnValue(false);

    fireEvent.click(commitButton());
    expect(api.commit).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(commitButton());

    await waitFor(() =>
      expect(api.commit).toHaveBeenCalledWith("draft-1", {
        page_id: null,
        source_id: "dataset",
        kind: "dataset",
        config: { channel: "test" },
        confirm: true,
      }),
    );
    expect(
      await screen.findByText("Draft committed successfully."),
    ).toBeInTheDocument();
    expect(onUpdated).toHaveBeenCalledTimes(1);
  });

  it("rejects a non-object publication config without committing", async () => {
    renderEditor({ status: "validated" });
    fillPublicationFields();
    fireEvent.change(screen.getByLabelText("Publication config JSON"), {
      target: { value: "[]" },
    });

    fireEvent.click(commitButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Publication config must be a JSON object.",
    );
    expect(api.commit).not.toHaveBeenCalled();
  });
});
