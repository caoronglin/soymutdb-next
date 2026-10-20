/**
 * Settings console contract.
 *
 * The `PUT /admin/settings/{section}` mutation had no `onError` and
 * `saveMutation.isError` was never rendered, so a rejected save (422 / 409 /
 * 500 / network) was indistinguishable from a successful one: the success
 * dialog only opens from `onSuccess`, and nothing else reported the failure.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    http: {
      ...actual.http,
      get: api.get,
      put: api.put,
    },
  };
});

// The rich-text editor lazily pulls in TipTap; it is not what this test is
// about, and the settings form renders one per content field.
vi.mock("../components/rich-editor/rich-editor", () => ({
  RichEditor: (props: { value?: string; onChange?: (html: string) => void }) => (
    <textarea
      data-testid="rich-editor"
      defaultValue={props.value}
      onChange={(event) => props.onChange?.(event.target.value)}
    />
  ),
}));

const SettingsPage = (await import("./settings")).default;

beforeEach(() => {
  api.get.mockReset().mockResolvedValue({});
  api.put.mockReset().mockResolvedValue({});
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

describe("settings save failures", () => {
  it("does not signal saved while the write is still pending", async () => {
    api.put.mockImplementation(() => new Promise(() => {}));
    renderPage();
    const generalSave = (await screen.findAllByRole("button", { name: "Save Changes" }))[0];
    await waitFor(() => expect(generalSave).toBeEnabled());
    fireEvent.click(generalSave);
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("Settings Saved")).toBeNull();
    expect(generalSave).toBeDisabled();
  });
  it("renders an error when the save request is rejected", async () => {
    api.put.mockRejectedValueOnce(new Error("422 validation failed"));
    renderPage();

    const saveButtons = await screen.findAllByRole("button", { name: "Save Changes" });
    const generalSave = saveButtons[0];
    await waitFor(() => expect(generalSave).toBeEnabled());
    fireEvent.click(generalSave);

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(api.put.mock.calls[0][0]).toBe("/admin/settings/general");

    const alert = await screen.findByTestId("settings-save-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("could not be saved");
    expect(alert).toHaveTextContent("422 validation failed");

    // A rejected save must not open the success dialog.
    expect(screen.queryByText("Settings Saved")).toBeNull();
  });

  it("keeps the success dialog for an accepted save", async () => {
    renderPage();

    const saveButtons = await screen.findAllByRole("button", { name: "Save Changes" });
    const generalSave = saveButtons[0];
    await waitFor(() => expect(generalSave).toBeEnabled());
    fireEvent.click(generalSave);

    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Settings Saved")).toBeInTheDocument();
    expect(screen.queryByTestId("settings-save-error")).toBeNull();
  });
});
