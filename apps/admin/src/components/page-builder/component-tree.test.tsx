import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ComponentDescriptor, PageComponentNode } from "@soymutdb/shared";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (_key: string, options?: { defaultValue?: string }) => options?.defaultValue ?? _key }),
}));

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
  it("uses the real DndContext keyboard drag lifecycle to forward reorder paths", async () => {
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

    expect(screen.getByText("rich_text")).toBeInTheDocument();
    const handles = screen.getAllByRole("button", { name: "Drag to reorder" });
    expect(handles).toHaveLength(3);

    // KeyboardSensor is deterministic in jsdom: pick up the first root child,
    // move to its next sibling, then drop. This exercises DndContext's actual
    // drag start/move/end pipeline rather than calling the adapter directly.
    handles[0].focus();
    await user.keyboard("{Space}{ArrowDown}{Space}");

    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove).toHaveBeenCalledWith([0], [1]);
  });
});
