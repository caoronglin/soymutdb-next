import type { PageComponentNode } from "@soymutdb/shared";

export function getTreeNode(root: PageComponentNode, path: number[]): PageComponentNode | null {
  let node: PageComponentNode | undefined = root;
  for (const index of path) {
    node = node?.children?.[index];
    if (!node) return null;
  }
  return node ?? null;
}

export function updateTreeChildren(root: PageComponentNode, path: number[], update: (children: PageComponentNode[]) => PageComponentNode[]): PageComponentNode {
  if (path.length === 0) return { ...root, children: update(root.children ?? []) };
  const [index, ...rest] = path;
  const children = [...(root.children ?? [])];
  if (!children[index]) return root;
  children[index] = updateTreeChildren(children[index], rest, update);
  return { ...root, children };
}

export function rebasePathAfterRemoval(target: number[], removed: number[]): number[] {
  const parent = removed.slice(0, -1);
  const removedIndex = removed[removed.length - 1];
  if (target.length <= parent.length || parent.some((part, index) => target[index] !== part)) return target;
  if (target[parent.length] <= removedIndex) return target;
  const next = target.slice();
  next[parent.length] -= 1;
  return next;
}

export function removeTreeNode(root: PageComponentNode, path: number[]): PageComponentNode {
  if (path.length === 0) return root;
  const parent = path.slice(0, -1);
  const index = path[path.length - 1];
  return updateTreeChildren(root, parent, (children) => children.filter((_child, childIndex) => childIndex !== index));
}

function isDescendant(path: number[], possibleAncestor: number[]): boolean {
  return path.length > possibleAncestor.length && possibleAncestor.every((part, index) => path[index] === part);
}

export function moveTreeNode(root: PageComponentNode, from: number[], over: number[], isLayoutContainer: (type: string) => boolean): PageComponentNode {
  if (!from.length || !over.length || from.join(".") === over.join(".") || isDescendant(over, from)) return root;
  const moving = getTreeNode(root, from);
  const overNode = getTreeNode(root, over);
  if (!moving || !overNode) return root;
  const sourceParent = from.slice(0, -1);
  const sourceIndex = from[from.length - 1];
  const targetParentBeforeRemoval = isLayoutContainer(overNode.type) ? over : over.slice(0, -1);
  let targetIndex = isLayoutContainer(overNode.type) ? (overNode.children?.length ?? 0) : over[over.length - 1];
  if (sourceParent.join(".") === targetParentBeforeRemoval.join(".") && sourceIndex < targetIndex) targetIndex -= 1;
  const withoutSource = removeTreeNode(root, from);
  const targetParent = rebasePathAfterRemoval(targetParentBeforeRemoval, from);
  return updateTreeChildren(withoutSource, targetParent, (children) => {
    const next = children.slice();
    next.splice(Math.max(0, Math.min(targetIndex, next.length)), 0, moving);
    return next;
  });
}
