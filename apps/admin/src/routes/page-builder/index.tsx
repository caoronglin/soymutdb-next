/**
 * Page Builder index: list page definitions with a create form.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Layers, Plus, Loader2 } from "lucide-react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Input,
  Label,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../../lib/admin-ui";
import {
  normalizePageDefinition,
  type PageDefinitionV2,
} from "@soymutdb/shared";
import { pageBuilderApi } from "../../lib/page-builder-api";

function defaultDefinition(): PageDefinitionV2 {
  return normalizePageDefinition({
    root: {
      type: "columns",
      props: { columns: 1 },
      children: [{ type: "rich_text", props: { content: "<p>New page</p>" } }],
    },
  })!;
}

export default function PageBuilderIndexPage() {
  const queryClient = useQueryClient();
  const [route, setRoute] = useState("");
  const [titleKey, setTitleKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["page-builder", "pages"],
    queryFn: () => pageBuilderApi.list({ page: 1, page_size: 100 }),
    placeholderData: { items: [], total: 0, page: 1, page_size: 100 },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      pageBuilderApi.create({
        route,
        title_key: titleKey,
        definition: defaultDefinition(),
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
      setRoute("");
      setTitleKey("");
      setError(null);
      // Navigate to the new editor.
      window.location.hash = `#/page-builder/${created.id}`;
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setError(e?.message ?? "Failed to create page.");
    },
  });

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Page Builder</h2>
          <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
            <Layers className="size-3.5" />
            Versioned, schema-validated page definitions
          </p>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Create a page</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="pb-route">Route</Label>
            <Input
              id="pb-route"
              value={route}
              onChange={(e) => setRoute(e.target.value)}
              placeholder="/about-us"
              className="w-64"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="pb-title">Title key</Label>
            <Input
              id="pb-title"
              value={titleKey}
              onChange={(e) => setTitleKey(e.target.value)}
              placeholder="nav.about"
              className="w-64"
            />
          </div>
          <Button
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending || !route || !titleKey}
          >
            {createMutation.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Plus className="size-4" />
            )}
            Create
          </Button>
        </CardContent>
        {error ? (
          <CardContent>
            <p className="text-sm text-destructive">{error}</p>
          </CardContent>
        ) : null}
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pages</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">
              <Loader2 className="inline size-4 animate-spin" /> Loading…
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Route</TableHead>
                  <TableHead>Title key</TableHead>
                  <TableHead>Latest version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data?.items ?? []).length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      No pages yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  (data?.items ?? []).map((p) => (
                    <TableRow key={p.id}>
                      <TableCell className="font-mono text-sm">{p.route}</TableCell>
                      <TableCell className="text-sm">{p.title_key}</TableCell>
                      <TableCell className="text-sm">{p.latest_version}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{p.latest_status}</Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Link to="/page-builder/$pageId" params={{ pageId: p.id }}>
                          <Button variant="outline" size="sm">
                            Edit
                          </Button>
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
