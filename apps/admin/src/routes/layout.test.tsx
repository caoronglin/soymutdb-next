import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import LayoutEditorPage from "./layout";

const { getLayoutMock, listMock, saveLayoutMock } = vi.hoisted(() => ({
  getLayoutMock: vi.fn(),
  listMock: vi.fn(),
  saveLayoutMock: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: any) => <a>{children}</a>,
}));

vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: any) => <div>{children}</div>,
  closestCenter: vi.fn(),
  KeyboardSensor: class KeyboardSensor {},
  PointerSensor: class PointerSensor {},
  useSensor: vi.fn(() => ({})),
  useSensors: vi.fn(() => []),
}));

vi.mock("@dnd-kit/sortable", () => ({
  arrayMove: (items: unknown[]) => items,
  SortableContext: ({ children }: any) => <div>{children}</div>,
  sortableKeyboardCoordinates: vi.fn(),
  useSortable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: vi.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  })),
  verticalListSortingStrategy: {},
}));

vi.mock("@dnd-kit/utilities", () => ({
  CSS: { Transform: { toString: () => undefined } },
}));

vi.mock("../lib/widget-api", () => ({
  widgetApi: {
    getLayout: getLayoutMock,
    list: listMock,
    saveLayout: saveLayoutMock,
  },
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <LayoutEditorPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getLayoutMock.mockReset();
  listMock.mockReset();
  saveLayoutMock.mockReset();
  listMock.mockResolvedValue({ items: [], total: 0 });
});

describe("LayoutEditorPage baseline protection", () => {
  it("does not allow saving while the current layout baseline is loading", () => {
    getLayoutMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByRole("button", { name: "Save Layout" })).toBeDisabled();
    expect(screen.queryByText("No widgets on this page. Add one below.")).not.toBeInTheDocument();
  });

  it("keeps saving locked and avoids an empty state when the layout baseline fails to load", async () => {
    getLayoutMock.mockRejectedValue(new Error("layout unavailable"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to load the current layout.",
    );
    expect(screen.getByRole("button", { name: "Save Layout" })).toBeDisabled();
    expect(screen.queryByText("No widgets on this page. Add one below.")).not.toBeInTheDocument();
  });

  it("allows saving an intentionally empty layout only after its baseline loads", async () => {
    getLayoutMock.mockResolvedValue({ page: "index", widgets: [] });
    renderPage();

    expect(await screen.findByText("No widgets on this page. Add one below.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save Layout" })).toBeEnabled();
    });
  });
});
