import { describe, expect, it } from "vitest";
import type { PageComponentNode } from "@soymutdb/shared";
import { moveTreeNode, rebasePathAfterRemoval, removeTreeNode } from "./page-builder-tree";

const root: PageComponentNode = {
  type: "columns", props: {}, children: [
    { type: "notice", props: {} },
    { type: "columns", props: {}, children: [{ type: "rich_text", props: {} }] },
    { type: "divider", props: {} },
  ],
};

describe("Page Builder tree moves", () => {
  const isLayout = (type: string) => type === "columns" || type === "tabs";
  it("rebases a later target after a sibling is removed", () => {
    expect(rebasePathAfterRemoval([2, 0], [0])).toEqual([1, 0]);
  });
  it("moves a root child into a layout container", () => {
    const moved = moveTreeNode(root, [0], [1], isLayout);
    expect(moved.children?.map((node) => node.type)).toEqual(["columns", "divider"]);
    expect(moved.children?.[0].children?.map((node) => node.type)).toEqual(["rich_text", "notice"]);
  });
  it("removes a nested node and rejects a move into its own descendant", () => {
    const removed = removeTreeNode(root, [1, 0]);
    expect(removed.children?.[1].children).toEqual([]);
    expect(moveTreeNode(root, [1], [1, 0], isLayout)).toBe(root);
  });
});
