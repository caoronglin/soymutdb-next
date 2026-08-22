/**
 * Schema-driven property panel.
 *
 * Renders only registry-declared controls for the selected component's
 * ``config_schema`` (JSON Schema emitted by the server).  Supported control
 * kinds: string, number/integer, boolean, enum (select), string[] (list), and
 * object arrays (e.g. navigation items).  Anything else falls back to a
 * read-only code view so an unknown control is never invented client-side.
 */

import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  Badge,
} from "../../lib/admin-ui";
import type { ComponentDescriptor, PageComponentNode } from "@soymutdb/shared";

type JsonSchema = Record<string, unknown>;

interface PropertyPanelProps {
  /** Selected component descriptor (null when nothing selected). */
  component: ComponentDescriptor | null;
  /** The live node being edited (undefined until a component is selected). */
  node?: PageComponentNode;
  /** Callback to update the selected node's props. */
  onChangeProps: (props: Record<string, unknown>) => void;
}


function resolveProps(schema: JsonSchema): Record<string, unknown> {
  return (schema?.properties as Record<string, unknown>) ?? {};
}

function FieldControl({
  schema,
  value,
  onChange,
}: {
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const enumValues = Array.isArray(schema.enum) ? (schema.enum as Array<string | number>) : undefined;
  const anyOf = schema.anyOf as JsonSchema[] | undefined;
  const type = schema.type ?? anyOf?.[0]?.type;

  if (enumValues) {
    return (
      <Select
        value={value == null ? undefined : String(value)}
        onValueChange={(v) => onChange(v)}
      >
        <SelectTrigger>
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {enumValues.map((v) => (
            <SelectItem key={String(v)} value={String(v)}>
              {String(v)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    );
  }

  if (type === "boolean") {
    return (
      <Select
        value={value == null ? "false" : String(value)}
        onValueChange={(v) => onChange(v === "true")}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">true</SelectItem>
          <SelectItem value="false">false</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  if (type === "number" || type === "integer") {
    return (
      <Input
        type="number"
        value={value == null ? "" : String(value)}
        onChange={(e) => {
          const raw = e.target.value;
          onChange(raw === "" ? null : Number(raw));
        }}
      />
    );
  }

  if (type === "array") {
    const items = Array.isArray(value) ? (value as unknown[]) : [];
    return (
      <Textarea
        rows={3}
        value={items.map((v) => (typeof v === "object" ? JSON.stringify(v) : String(v))).join("\n")}
        onChange={(e) => {
          const lines = e.target.value.split("\n").filter((l) => l.trim() !== "");
          // Re-parse object arrays when possible (navigation items).
          const parsed = lines.map((l) => {
            try {
              return JSON.parse(l) as unknown;
            } catch {
              return l;
            }
          });
          onChange(parsed);
        }}
        placeholder="one item per line"
      />
    );
  }

  // Default: string (and fallback for anything else).
  return (
    <Input
      value={value == null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

/** A single ``{label, route}``-style object-array editor (navigation items). */
function ObjectArrayControl({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const items = Array.isArray(value)
    ? (value as Array<Record<string, unknown>>)
    : [];
  return (
    <div className="space-y-1">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-1">
          <Input
            className="flex-1"
            value={item.label == null ? "" : String(item.label)}
            placeholder="label"
            onChange={(e) => {
              const next = items.map((it, j) =>
                j === i ? { ...it, label: e.target.value } : it,
              );
              onChange(next);
            }}
          />
          <Input
            className="flex-1"
            value={item.route == null ? "" : String(item.route)}
            placeholder="route"
            onChange={(e) => {
              const next = items.map((it, j) =>
                j === i ? { ...it, route: e.target.value } : it,
              );
              onChange(next);
            }}
          />
          <Button
            variant="ghost"
            size="sm"
            className="size-7 p-0"
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            aria-label="Remove item"
          >
            ×
          </Button>
        </div>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onChange([...items, { label: "", route: "/" }])}
      >
        Add item
      </Button>
    </div>
  );
}

export function PropertyPanel({
  component,
  node,
  onChangeProps,
}: PropertyPanelProps) {
  const props = node?.props ?? {};

  if (!component) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Properties</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            Select a component in the tree to edit its properties.
          </p>
        </CardContent>
      </Card>
    );
  }

  const schema = component.config_schema;
  const properties = resolveProps(schema);
  const required = Array.isArray(schema.required)
    ? (schema.required as string[])
    : [];
  const propertyNames = Object.keys(properties);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          Properties
          <Badge variant="outline">{component.renderer_key}</Badge>
        </CardTitle>
        <CardDescription>{component.label}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {propertyNames.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            This component has no configurable properties.
          </p>
        ) : (
          propertyNames.map((name) => {
            const propSchema = (properties[name] ?? {}) as JsonSchema;
            const value = props[name];
            // Object-array types (e.g. navigation items) get a structured editor.
            const isObjectArray =
              propSchema.type === "array" &&
              (propSchema.items as JsonSchema)?.type === "object";
            return (
              <div key={name} className="space-y-1.5">
                <Label htmlFor={`prop-${name}`} className="flex items-center gap-1">
                  {name}
                  {required.includes(name) ? (
                    <span className="text-destructive">*</span>
                  ) : null}
                </Label>
                {isObjectArray ? (
                  <ObjectArrayControl
                    value={value}
                    onChange={(v) => onChangeProps({ ...props, [name]: v })}
                  />
                ) : (
                  <FieldControl
                    schema={propSchema}
                    value={value}
                    onChange={(v) => onChangeProps({ ...props, [name]: v })}
                  />
                )}
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}

export default PropertyPanel;
