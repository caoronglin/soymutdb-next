/**
 * Component palette: the server-owned registry rendered as clickable entries.
 * Clicking a component adds it as a child of the page root.
 */

import { Plus } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@soymutdb/ui";
import type { ComponentDescriptor, PageComponentType } from "@soymutdb/shared";

interface ComponentPaletteProps {
  components: ComponentDescriptor[];
  onAdd: (type: PageComponentType) => void;
}

export function ComponentPalette({ components, onAdd }: ComponentPaletteProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Component Palette</CardTitle>
        <CardDescription>
          {components.length} server-approved component types
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-1.5">
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
                <Plus className="size-3.5" />
              </span>
            </button>
          ))
        )}
      </CardContent>
    </Card>
  );
}

export default ComponentPalette;
