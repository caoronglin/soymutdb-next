/**
 * Component palette: the server-owned registry rendered as clickable entries.
 * Clicking a component adds it as a child of the page root.
 */

import { PlusOutlined } from "@ant-design/icons";
import { Card, Typography } from "@/lib/antd";
import type { ComponentDescriptor, PageComponentType } from "@soymutdb/shared";

interface ComponentPaletteProps {
  components: ComponentDescriptor[];
  onAdd: (type: PageComponentType) => void;
}

export function ComponentPalette({ components, onAdd }: ComponentPaletteProps) {
  return (
    <Card title="Component Palette">
      <Typography.Text type="secondary" className="mb-3 block">
        {components.length} server-approved component types
      </Typography.Text>
      <div className="space-y-1.5">
        {components.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Registry unavailable — check your connection.
          </p>
        ) : (
          components.map((c) => (
            <button
              key={c.renderer_key}
              type="button"
              onClick={() => onAdd(c.renderer_key as PageComponentType)}
              className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
              aria-label={`Add ${c.label}`}
            >
              <span className="font-mono text-xs">{c.renderer_key}</span>
              <span className="ml-2 flex items-center gap-2 text-muted-foreground">
                {c.label}
                <PlusOutlined className="size-3.5" />
              </span>
            </button>
          ))
        )}
      </div>
    </Card>
  );
}

export default ComponentPalette;
