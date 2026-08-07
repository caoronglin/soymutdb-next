import { useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useParams, useNavigate, Link } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  ArrowLeft,
  Blocks,
  Eye,
  Save,
  X,
  Loader2,
} from "lucide-react";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardFooter,
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
} from "@soymutdb/ui";
import { widgetApi, type WidgetCategory, type WidgetPermission } from "../../lib/widget-api";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const WIDGET_CATEGORIES: WidgetCategory[] = [
  "stats",
  "chart",
  "table",
  "list",
  "search",
  "navigation",
  "content",
  "custom",
];

const WIDGET_PERMISSIONS: WidgetPermission[] = ["public", "user", "editor", "admin"];

function isValidJson(s: string): boolean {
  if (!s.trim()) return true; // empty is OK (null)
  try {
    JSON.parse(s);
    return true;
  } catch {
    return false;
  }
}

const widgetSchema = z.object({
  name: z
    .string()
    .min(2, "Name must be at least 2 characters")
    .regex(/^[a-z][a-z0-9_-]*$/, "Must be lowercase: letters, numbers, hyphen, underscore"),
  display_name: z.string().min(1, "Display name is required"),
  description: z.string().max(500).optional().or(z.literal("")),
  category: z.enum([
    "stats",
    "chart",
    "table",
    "list",
    "search",
    "navigation",
    "content",
    "custom",
  ]),
  template_path: z.string().min(1, "Template path is required"),
  data_source: z.string().optional().or(z.literal("")),
  params_schema: z
    .string()
    .refine(isValidJson, "Must be valid JSON or empty")
    .optional()
    .or(z.literal("")),
  cache_ttl: z.coerce
    .number()
    .int("Must be an integer")
    .min(0, "Must be >= 0 (0 disables caching)")
    .max(86400, "Max 86400 seconds (24h)"),
  admin_config: z
    .string()
    .refine(isValidJson, "Must be valid JSON or empty")
    .optional()
    .or(z.literal("")),
  permissions: z.enum(["public", "user", "editor", "admin"]),
  is_active: z.boolean().default(true),
});

type WidgetFormValues = z.infer<typeof widgetSchema>;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WidgetEditorPage() {
  const { name: routeName } = useParams({ from: "/widgets/$name" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isNew = routeName === "new";

  const { data: existingWidget, isLoading: isLoadingWidget } = useQuery({
    queryKey: ["admin-widget", routeName],
    queryFn: () => widgetApi.get(routeName),
    enabled: !isNew,
  });

  const defaultValues: WidgetFormValues = useMemo(
    () => ({
      name: isNew ? "" : existingWidget?.name ?? "",
      display_name: isNew ? "" : existingWidget?.display_name ?? "",
      description: isNew ? "" : existingWidget?.description ?? "",
      category: (isNew ? "custom" : existingWidget?.category) ?? "custom",
      template_path: isNew ? "" : existingWidget?.template_path ?? "",
      data_source: isNew ? "" : existingWidget?.data_source ?? "",
      params_schema: isNew
        ? ""
        : existingWidget?.params_schema
          ? JSON.stringify(existingWidget.params_schema, null, 2)
          : "",
      cache_ttl: isNew ? 300 : existingWidget?.cache_ttl ?? 300,
      admin_config: isNew
        ? ""
        : existingWidget?.admin_config
          ? JSON.stringify(existingWidget.admin_config, null, 2)
          : "",
      permissions: (isNew ? "public" : existingWidget?.permissions) ?? "public",
      is_active: isNew ? true : existingWidget?.is_active ?? true,
    }),
    [isNew, existingWidget],
  );

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isDirty },
  } = useForm<WidgetFormValues>({
    resolver: zodResolver(widgetSchema),
    defaultValues,
    mode: "onBlur",
  });

  // Reset form when existing widget loads
  useEffect(() => {
    if (existingWidget || isNew) {
      reset(defaultValues);
    }
  }, [existingWidget, isNew, defaultValues, reset]);

  const createMutation = useMutation({
    mutationFn: (values: WidgetFormValues) => {
      const payload = {
        name: values.name,
        display_name: values.display_name,
        description: values.description || null,
        category: values.category,
        template_path: values.template_path,
        data_source: values.data_source || null,
        params_schema: values.params_schema
          ? (JSON.parse(values.params_schema) as Record<string, unknown>)
          : null,
        cache_ttl: values.cache_ttl,
        admin_config: values.admin_config
          ? (JSON.parse(values.admin_config) as Record<string, unknown>)
          : null,
        permissions: values.permissions,
        is_active: values.is_active,
      };
      return widgetApi.create(payload);
    },
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["admin-widgets"] });
      navigate({ to: "/widgets/$name", params: { name: created.name }, replace: true });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: WidgetFormValues) => {
      const payload = {
        display_name: values.display_name,
        description: values.description || null,
        category: values.category,
        template_path: values.template_path,
        data_source: values.data_source || null,
        params_schema: values.params_schema
          ? (JSON.parse(values.params_schema) as Record<string, unknown>)
          : null,
        cache_ttl: values.cache_ttl,
        admin_config: values.admin_config
          ? (JSON.parse(values.admin_config) as Record<string, unknown>)
          : null,
        permissions: values.permissions,
        is_active: values.is_active,
      };
      return widgetApi.update(routeName, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-widgets"] });
      queryClient.invalidateQueries({ queryKey: ["admin-widget", routeName] });
    },
  });

  const isSaving = createMutation.isPending || updateMutation.isPending;
  const saveError = isNew ? createMutation.error : updateMutation.error;

  const onSubmit = (values: WidgetFormValues) => {
    if (isNew) {
      createMutation.mutate(values);
    } else {
      updateMutation.mutate(values);
    }
  };

  if (!isNew && isLoadingWidget) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-muted" />
        <div className="h-96 animate-pulse rounded-xl bg-muted" />
      </div>
    );
  }

  const watchedCategory = watch("category");
  const watchedPermissions = watch("permissions");
  const watchedIsActive = watch("is_active");

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link to="/widgets">
            <Button variant="ghost" size="sm">
              <ArrowLeft className="size-4" />
              Back
            </Button>
          </Link>
          <div>
            <h2 className="font-serif text-2xl font-semibold">
              {isNew ? "New Widget" : existingWidget?.display_name ?? routeName}
            </h2>
            <p className="mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              <Blocks className="size-3.5" />
              {isNew ? "Define a new reusable widget" : routeName}
              {!isNew && (
                <>
                  <span>·</span>
                  <Badge variant={watchedIsActive ? "success" : "secondary"}>
                    {watchedIsActive ? "Active" : "Inactive"}
                  </Badge>
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {!isNew && (
            <Link to="/widget-preview" search={{ name: routeName }}>
              <Button variant="outline" size="sm">
                <Eye className="size-4" />
                Preview
              </Button>
            </Link>
          )}
          <Button variant="outline" size="sm" onClick={() => navigate({ to: "/widgets" })}>
            <X className="size-4" />
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit(onSubmit)} disabled={isSaving || !isDirty}>
            {isSaving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            {isSaving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>

      {saveError ? (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {saveError instanceof Error ? saveError.message : "Failed to save widget"}
        </div>
      ) : null}

      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-6 lg:grid-cols-3">
        {/* Main column */}
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>General</CardTitle>
              <CardDescription>
                Basic identity and rendering configuration.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="name">Widget Name (slug)</Label>
                  <Input
                    id="name"
                    placeholder="e.g. recent-releases"
                    disabled={!isNew}
                    {...register("name")}
                  />
                  {errors.name ? (
                    <p className="text-xs text-destructive">{errors.name.message}</p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Unique identifier; cannot be changed after creation.
                    </p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="display_name">Display Name</Label>
                  <Input
                    id="display_name"
                    placeholder="e.g. Recent Releases"
                    {...register("display_name")}
                  />
                  {errors.display_name && (
                    <p className="text-xs text-destructive">{errors.display_name.message}</p>
                  )}
                </div>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  rows={2}
                  placeholder="Brief description shown in admin"
                  {...register("description")}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="template_path">Template Path</Label>
                  <Input
                    id="template_path"
                    placeholder="widgets/recent-releases.njk"
                    {...register("template_path")}
                  />
                  {errors.template_path && (
                    <p className="text-xs text-destructive">{errors.template_path.message}</p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="data_source">Data Source</Label>
                  <Input
                    id="data_source"
                    placeholder="e.g. /api/stats/recent-releases"
                    {...register("data_source")}
                  />
                  <p className="text-xs text-muted-foreground">
                    API endpoint or query identifier.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Schemas & Configuration</CardTitle>
              <CardDescription>
                Parameter schema (JSON Schema) and admin configuration as JSON.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="params_schema">Params Schema (JSON)</Label>
                <Textarea
                  id="params_schema"
                  rows={8}
                  className="font-mono text-xs"
                  placeholder='{\n  "type": "object",\n  "properties": {\n    "limit": { "type": "integer", "default": 5 }\n  }\n}'
                  {...register("params_schema")}
                />
                {errors.params_schema && (
                  <p className="text-xs text-destructive">{errors.params_schema.message as string}</p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="admin_config">Admin Config (JSON)</Label>
                <Textarea
                  id="admin_config"
                  rows={6}
                  className="font-mono text-xs"
                  placeholder="{}"
                  {...register("admin_config")}
                />
                {errors.admin_config && (
                  <p className="text-xs text-destructive">{errors.admin_config.message as string}</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Side column */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label>Category</Label>
                <Select
                  value={watchedCategory}
                  onValueChange={(v) => setValue("category", v as WidgetCategory, { shouldDirty: true })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WIDGET_CATEGORIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c.charAt(0).toUpperCase() + c.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label>Permissions</Label>
                <Select
                  value={watchedPermissions}
                  onValueChange={(v) => setValue("permissions", v as WidgetPermission, { shouldDirty: true })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WIDGET_PERMISSIONS.map((p) => (
                      <SelectItem key={p} value={p}>
                        {p.charAt(0).toUpperCase() + p.slice(1)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="cache_ttl">Cache TTL (seconds)</Label>
                <Input
                  id="cache_ttl"
                  type="number"
                  min={0}
                  max={86400}
                  {...register("cache_ttl")}
                />
                {errors.cache_ttl && (
                  <p className="text-xs text-destructive">{errors.cache_ttl.message as string}</p>
                )}
              </div>

              <div className="flex items-center justify-between rounded-lg border border-border p-3">
                <div>
                  <p className="text-sm font-medium">Active</p>
                  <p className="text-xs text-muted-foreground">
                    When inactive, the widget will not render on pages.
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={watchedIsActive}
                  onClick={() => setValue("is_active", !watchedIsActive, { shouldDirty: true })}
                  className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                    watchedIsActive ? "bg-primary" : "bg-muted"
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-5 transform rounded-full bg-background shadow transition-transform ${
                      watchedIsActive ? "translate-x-5" : "translate-x-0.5"
                    }`}
                  />
                </button>
              </div>
            </CardContent>
            <CardFooter className="flex-col items-stretch gap-2 border-t pt-4">
              <Button type="submit" disabled={isSaving || !isDirty} className="w-full">
                {isSaving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
                {isSaving ? "Saving…" : isNew ? "Create Widget" : "Save Changes"}
              </Button>
            </CardFooter>
          </Card>
        </div>
      </form>
    </div>
  );
}
