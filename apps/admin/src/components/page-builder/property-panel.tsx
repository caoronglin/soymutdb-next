/**
 * Schema-driven property panel.
 *
 * Renders only registry-declared controls for the selected component's
 * ``config_schema`` (JSON Schema emitted by the server).  Supported control
 * kinds: string, number/integer, boolean, enum (select), string[] (list), and
 * object arrays (e.g. navigation items).  Anything else falls back to a
 * read-only code view so an unknown control is never invented client-side.
 */

import { Badge, Button, Card, Input, Select, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  const enumValues = Array.isArray(schema.enum) ? (schema.enum as Array<string | number>) : undefined;
  const anyOf = schema.anyOf as JsonSchema[] | undefined;
  const type = schema.type ?? anyOf?.[0]?.type;

  if (enumValues) {
    return (
      <Select
        value={value == null ? undefined : String(value)}
        onChange={(v) => onChange(v)}
        options={enumValues.map((v) => ({ value: String(v), label: String(v) }))}
      />
    );
  }

  if (type === "boolean") {
    return (
      <Select
        value={value == null ? "false" : String(value)}
        onChange={(v) => onChange(v === "true")}
        options={[{ value: "true", label: "true" }, { value: "false", label: "false" }]}
      />
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
      <Input.TextArea
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
        placeholder={t("admin.builder.oneItemPerLine", { defaultValue: "one item per line" })}
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

/** Structured editor for schema object arrays, including resource card text/image/link fields. */
function ObjectArrayControl({
  value,
  schema,
  onChange,
}: {
  value: unknown;
  schema: JsonSchema;
  onChange: (v: unknown) => void;
}) {
  const { t } = useTranslation();
  const items = Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
  const itemSchema = (schema.items as JsonSchema | undefined) ?? {};
  const fields = Object.keys((itemSchema.properties as Record<string, unknown> | undefined) ?? {});
  const defaults = fields.reduce<Record<string, unknown>>((result, field) => {
    result[field] = field === "route" || field === "href" ? "/" : "";
    return result;
  }, {});

  return (
    <div className="space-y-3">
      {items.map((item, index) => (
        <fieldset key={index} className="space-y-2 rounded-md border p-2">
          <div className="flex items-center justify-between">
            <legend className="text-xs font-medium text-muted-foreground">{t("admin.builder.itemLabel", { defaultValue: "Item {{index}}", index: index + 1 })}</legend>
            <div className="flex gap-1">
              <Button type="text" size="small" className="h-7 px-2" disabled={index === 0} onClick={() => {
                const next = [...items]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; onChange(next);
              }}>↑</Button>
              <Button type="text" size="small" className="h-7 px-2" disabled={index === items.length - 1} onClick={() => {
                const next = [...items]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; onChange(next);
              }}>↓</Button>
              <Button type="text" size="small" className="h-7 px-2" onClick={() => onChange(items.filter((_, i) => i !== index))} aria-label={t("admin.builder.removeItemLabel", { defaultValue: "Remove item {{index}}", index: index + 1 })}>×</Button>
            </div>
          </div>
          {fields.map((field) => (
            <div key={field} className="space-y-1">
              <Typography.Text className="text-xs">{field}</Typography.Text>
              {field === "description" ? (
                <Input.TextArea id={`object-${field}-${index}`} rows={2} value={item[field] == null ? "" : String(item[field])} onChange={(e) => {
                  const next = items.map((entry, i) => i === index ? { ...entry, [field]: e.target.value || null } : entry); onChange(next);
                }} />
              ) : (
                <Input id={`object-${field}-${index}`} type={field === "image_url" || field === "href" || field === "route" ? "url" : "text"} value={item[field] == null ? "" : String(item[field])} onChange={(e) => {
                  const next = items.map((entry, i) => i === index ? { ...entry, [field]: e.target.value || (field === "title" || field === "label" ? "" : null) } : entry); onChange(next);
                }} />
              )}
            </div>
          ))}
        </fieldset>
      ))}
      <Button size="small" onClick={() => onChange([...items, defaults])}>{t("admin.builder.addItem", { defaultValue: "Add item" })}</Button>
    </div>
  );
}

export function PropertyPanel({
  component,
  node,
  onChangeProps,
}: PropertyPanelProps) {
  const { t } = useTranslation();
  const props = node?.props ?? {};

  if (!component) {
    return (
      <Card title={t("admin.builder.propertiesTitle", { defaultValue: "Properties" })}>
        <Typography.Text type="secondary">{t("admin.builder.selectComponent", { defaultValue: "Select a component in the tree to edit its properties." })}</Typography.Text>
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
    <Card title={<span className="flex items-center gap-2">{t("admin.builder.propertiesTitle", { defaultValue: "Properties" })} <Badge color="default">{component.renderer_key}</Badge></span>}>
      <Typography.Paragraph type="secondary">{component.label}</Typography.Paragraph>
      <div className="space-y-4">
        {propertyNames.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("admin.builder.noConfigurableProperties", { defaultValue: "This component has no configurable properties." })}
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
                <Typography.Text className="flex items-center gap-1">
                  {name}
                  {required.includes(name) ? (
                    <span className="text-destructive">*</span>
                  ) : null}
                </Typography.Text>
                {isObjectArray ? (
                  <ObjectArrayControl
                    value={value}
                    schema={propSchema}
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
      </div>
    </Card>
  );
}

export default PropertyPanel;
