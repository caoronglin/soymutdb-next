import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentDescriptor, PageComponentNode } from "@soymutdb/shared";

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: ... })` returns a new function per render and makes any
// component with `t` in an effect dependency loop forever. See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

import { ComponentTree } from "./component-tree";

const root: PageComponentNode = {
  type: "columns", props: {}, children: [
    { type: "notice", props: {} },
    { type: "columns", props: {}, children: [{ type: "rich_text", props: {} }] },
  ],
};

const descriptors = new Map<string, ComponentDescriptor>([
  ["columns", { renderer_key: "columns", label: "Columns", config_schema: {}, allowed_children: [], is_layout_container: true }],
  ["notice", { renderer_key: "notice", label: "Notice", config_schema: {}, allowed_children: [], is_layout_container: false }],
  ["rich_text", { renderer_key: "rich_text", label: "Rich text", config_schema: {}, allowed_children: [], is_layout_container: false }],
]);

describe("ComponentTree DnD adapter", () => {
  it("renders every node with a keyboard-reachable drag handle", () => {
    render(
      <ComponentTree
        root={root}
        descriptors={descriptors}
        selectedPath={null}
        onSelect={vi.fn()}
        onRemoveNode={vi.fn()}
        onMove={vi.fn()}
      />,
    );

    expect(screen.getByText("rich_text")).toBeInTheDocument();
    const handles = screen.getAllByRole("button", { name: "Drag to reorder" });
    expect(handles).toHaveLength(3);
    for (const handle of handles) {
      // A drag handle that cannot take focus cannot be operated by keyboard.
      expect(handle).toHaveAttribute("tabindex", "0");
      expect(handle).toHaveAttribute("aria-roledescription", "sortable");
    }
  });

  it("starts a keyboard drag from the focused handle", async () => {
    // `{Space}` is not a valid user-event key descriptor and produces
    // `code: "Unknown"`, which dnd-kit's KeyboardSensor does not recognise as the
    // activation code. Press the literal space character instead.
    const user = userEvent.setup();
    render(
      <ComponentTree
        root={root}
        descriptors={descriptors}
        selectedPath={null}
        onSelect={vi.fn()}
        onRemoveNode={vi.fn()}
        onMove={vi.fn()}
      />,
    );

    const handles = screen.getAllByRole("button", { name: "Drag to reorder" });
    handles[0].focus();
    await user.keyboard(" ");

    expect(handles[0]).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps the drag-reorder adapter inert until a drop lands elsewhere", async () => {
    // jsdom reports zero-size rects, so `closestCenter` always resolves `over`
    // to the active node. A same-node drop must stay a no-op rather than emit a
    // bogus move.
    const user = userEvent.setup();
    const onMove = vi.fn();
    render(
      <ComponentTree
        root={root}
        descriptors={descriptors}
        selectedPath={null}
        onSelect={vi.fn()}
        onRemoveNode={vi.fn()}
        onMove={onMove}
      />,
    );

    const handles = screen.getAllByRole("button", { name: "Drag to reorder" });
    handles[0].focus();
    await user.keyboard(" ");
    await user.keyboard("{ArrowDown}");
    await user.keyboard(" ");

    expect(onMove).not.toHaveBeenCalled();
  });
});
