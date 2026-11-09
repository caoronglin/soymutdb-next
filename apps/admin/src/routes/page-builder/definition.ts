/**
 * Tree + JSON-Schema helpers for the Page Builder editor.
 *
 * Nodes are addressed by their index path below the root (`[]` is the root
 * node itself). Every mutation returns a fresh tree so React state updates stay
 * immutable; the server re-validates the whole document on save.
 */

import type {
  ComponentDescriptor,
  PageComponentNode,
  PageDefinitionTheme,
  PageDefinitionV2,
} from "@soymutdb/shared";
import { isLayoutContainer } from "@soymutdb/shared";

export type NodePath = number[];

export function pathKey(path: NodePath): string {
  return path.length === 0 ? "root" : path.join(".");
}

export function pathEquals(a: NodePath | null, b: NodePath | null): boolean {
  if (a === null || b === null) return a === b;
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

export function nodeAt(root: PageComponentNode, path: NodePath): PageComponentNode | null {
  let current: PageComponentNode | undefined = root;
  for (const index of path) {
    current = current?.children?.[index];
    if (!current) return null;
  }
  return current;
}

export function updateAt(
  root: PageComponentNode,
  path: NodePath,
  updater: (node: PageComponentNode) => PageComponentNode,
): PageComponentNode {
  if (path.length === 0) return updater(root);
  const [index, ...rest] = path;
  const children = [...(root.children ?? [])];
  const child = children[index];
  if (!child) return root;
  children[index] = updateAt(child, rest, updater);
  return { ...root, children };
}

export function removeAt(root: PageComponentNode, path: NodePath): PageComponentNode {
  if (path.length === 0) return root;
  return updateAt(root, path.slice(0, -1), (parent) => {
    const children = [...(parent.children ?? [])];
    children.splice(path[path.length - 1], 1);
    return { ...parent, children };
  });
}

export function appendChild(
  root: PageComponentNode,
  parentPath: NodePath,
  node: PageComponentNode,
): PageComponentNode {
  return updateAt(root, parentPath, (parent) => ({
    ...parent,
    children: [...(parent.children ?? []), node],
  }));
}

export function moveChild(
  root: PageComponentNode,
  parentPath: NodePath,
  from: number,
  to: number,
): PageComponentNode {
  if (from === to) return root;
  return updateAt(root, parentPath, (parent) => {
    const children = [...(parent.children ?? [])];
    const [moved] = children.splice(from, 1);
    if (!moved) return parent;
    children.splice(to, 0, moved);
    return { ...parent, children };
  });
}

/** Append to the selected container, or to the root when a leaf is selected. */
export function insertionTarget(
  root: PageComponentNode,
  path: NodePath | null,
): NodePath {
  if (!path) return [];
  const node = nodeAt(root, path);
  if (node && isLayoutContainer(node.type)) return path;
  if (path.length > 0) {
    const parent = nodeAt(root, path.slice(0, -1));
    if (parent && isLayoutContainer(parent.type)) return path.slice(0, -1);
  }
  return [];
}

export function emptyDefinition(titleKey?: string): PageDefinitionV2 {
  return {
    schema_version: 2,
    ...(titleKey ? { title_key: titleKey } : {}),
    root: { type: "columns", props: { columns: 1 }, children: [] },
    data_sources: [],
    theme_id: "scientific-light",
    layouts: { desktop: {}, tablet: {}, mobile: {} },
  };
}

export const PAGE_THEMES: PageDefinitionTheme[] = [
  "scientific-light",
  "scientific-dark",
  "high-contrast",
  "compact-data",
  "print",
];

type JsonSchema = Record<string, unknown>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export interface SchemaField {
  name: string;
  schema: JsonSchema;
  required: boolean;
}

export type FieldKind =
  | "string"
  | "number"
  | "boolean"
  | "enum"
  | "tags"
  | "json";

function resolveRef(schema: JsonSchema, root: JsonSchema): JsonSchema {
  const ref = schema.$ref;
  if (typeof ref !== "string" || !ref.startsWith("#/$defs/")) return schema;
  const defs = root.$defs;
  const key = ref.slice("#/$defs/".length);
  if (isRecord(defs) && isRecord(defs[key])) return defs[key];
  return schema;
}

/** Unwrap `anyOf`/`oneOf` null unions (Python `X | None`) into the real schema. */
function unwrapNullable(schema: JsonSchema): JsonSchema {
  const variants = schema.anyOf ?? schema.oneOf;
  if (!Array.isArray(variants)) return schema;
  const concrete = variants.filter(
    (variant) => isRecord(variant) && variant.type !== "null",
  );
  if (concrete.length !== 1 || !isRecord(concrete[0])) return schema;
  return { ...(concrete[0] as JsonSchema), ...(schema.default !== undefined ? { default: schema.default } : {}) };
}

export function listFields(descriptor: ComponentDescriptor): SchemaField[] {
  const root = descriptor.config_schema as JsonSchema;
  const properties = root.properties;
  if (!isRecord(properties)) return [];
  const required = Array.isArray(root.required)
    ? new Set(root.required.filter((name): name is string => typeof name === "string"))
    : new Set<string>();
  return Object.entries(properties).flatMap(([name, raw]) => {
    if (!isRecord(raw)) return [];
    return [{ name, schema: unwrapNullable(resolveRef(raw, root)), required: required.has(name) }];
  });
}

function fieldKind(schema: JsonSchema): FieldKind {
  if (Array.isArray(schema.enum)) return "enum";
  if (typeof schema.const === "string") return "enum";
  if (schema.type === "boolean") return "boolean";
  if (schema.type === "integer" || schema.type === "number") return "number";
  if (schema.type === "array") {
    const items = isRecord(schema.items) ? schema.items : {};
    return items.type === "string" ? "tags" : "json";
  }
  if (schema.type === "object") return "json";
  return "string";
}

export { fieldKind };

export function enumValues(schema: JsonSchema): string[] {
  if (Array.isArray(schema.enum)) {
    return schema.enum.filter((value): value is string => typeof value === "string");
  }
  return typeof schema.const === "string" ? [schema.const] : [];
}

function defaultValue(schema: JsonSchema, depth = 0): unknown {
  if (schema.default !== undefined) return schema.default;
  if (Array.isArray(schema.enum)) return schema.enum[0];
  if (typeof schema.const !== "undefined") return schema.const;
  switch (schema.type) {
    case "boolean":
      return false;
    case "integer":
    case "number":
      return typeof schema.minimum === "number" ? schema.minimum : 0;
    case "string":
      return "";
    case "array":
      return [];
    case "object": {
      if (depth > 2 || !isRecord(schema.properties)) return {};
      const result: Record<string, unknown> = {};
      for (const [name, raw] of Object.entries(schema.properties)) {
        if (isRecord(raw)) result[name] = defaultValue(unwrapNullable(raw), depth + 1);
      }
      return result;
    }
    default:
      return undefined;
  }
}

/** Build props that satisfy the schema where possible (server still validates). */
export function defaultProps(descriptor: ComponentDescriptor): Record<string, unknown> {
  const props: Record<string, unknown> = {};
  for (const field of listFields(descriptor)) {
    const value = defaultValue(field.schema);
    if (value !== undefined) props[field.name] = value;
  }
  return props;
}

export function nodeFromDescriptor(descriptor: ComponentDescriptor): PageComponentNode {
  return {
    type: descriptor.renderer_key,
    props: defaultProps(descriptor),
    ...(descriptor.is_layout_container ? { children: [] } : {}),
  };
}

export function descriptorFor(
  registry: ComponentDescriptor[],
  type: string,
): ComponentDescriptor | undefined {
  return registry.find((entry) => entry.renderer_key === type);
}

export function componentLabel(registry: ComponentDescriptor[], type: string): string {
  return descriptorFor(registry, type)?.label ?? type;
}

export function summarizeNode(node: PageComponentNode): string {
  const props = node.props;
  for (const key of ["title", "label", "heading", "content"]) {
    const value = props[key];
    if (typeof value === "string" && value.trim()) return value.trim().slice(0, 60);
  }
  const children = node.children?.length ?? 0;
  return children > 0 ? `${children} child${children === 1 ? "" : "ren"}` : "no props set";
}