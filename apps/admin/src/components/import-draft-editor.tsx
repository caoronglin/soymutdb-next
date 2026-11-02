import { useEffect, useState } from "react";
import { Button, Input, Typography } from "@/lib/antd";
import {
  adminImportStudioApi,
  type DataPatchItem,
  type FieldMappingItem,
  type ImportDraftResponse,
} from "@soymutdb/api-client";

interface ImportDraftEditorProps {
  draft: ImportDraftResponse;
  onUpdated: () => void;
}

function parseArray<T>(value: string, label: string): T[] {
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON array.`);
  }
  return parsed as T[];
}

function parseObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

/**
 * Edits a server-created ImportDraft without recreating source metadata locally.
 * Counts and immutable source information always remain on the persisted draft.
 */
export function ImportDraftEditor({ draft, onUpdated }: ImportDraftEditorProps) {
  const [mapping, setMapping] = useState("[]");
  const [patches, setPatches] = useState("[]");
  const [sourceId, setSourceId] = useState("");
  const [kind, setKind] = useState("");
  const [config, setConfig] = useState("{}");
  const [busy, setBusy] = useState<"mapping" | "patches" | "validate" | "commit" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setMapping(JSON.stringify(draft.field_mapping, null, 2));
  }, [draft.id, draft.updated_at, draft.field_mapping]);

  // Only a different draft invalidates the previous operation's feedback. A
  // refetch of the same draft (the refresh a successful save triggers) must not
  // erase the success notice that save just produced.
  useEffect(() => {
    setError(null);
    setNotice(null);
  }, [draft.id]);

  // The server permits mapping/patch/validation writes only while the draft is
  // still ``draft`` and commits only ``validated``/``ready`` drafts. Mirror that
  // state machine here instead of offering controls the API will reject with a
  // 409/400.
  const editable = draft.status === "draft";
  const committable = draft.status === "validated" || draft.status === "ready";
  const immutable = draft.status === "committed";

  async function run(action: NonNullable<typeof busy>, work: () => Promise<unknown>, success: string) {
    setBusy(action);
    setError(null);
    setNotice(null);
    try {
      await work();
      setNotice(success);
      onUpdated();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The draft operation failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-4 space-y-4 border-t border-primary/20 pt-4">
      <Typography.Text type="secondary">
        Mapping, patches, validation, and publication operate on this persisted draft.
        Immutable source metadata and row counts are not editable here.
      </Typography.Text>
      {editable ? null : (
        <Typography.Text type="secondary">
          {immutable
            ? "This draft is committed; all editing controls are locked."
            : committable
              ? `This draft is ${draft.status}; mapping, patches, and validation are locked. Publication is available below.`
              : `This draft is ${draft.status}; mapping, patches, validation, and publication are unavailable.`}
        </Typography.Text>
      )}

      <label className="block text-sm font-medium">
        Field mapping (JSON array)
        <Input.TextArea
          aria-label="Field mapping JSON"
          autoSize={{ minRows: 5, maxRows: 12 }}
          disabled={!editable || busy !== null}
          value={mapping}
          onChange={(event) => setMapping(event.target.value)}
        />
      </label>
      <Button
        disabled={!editable}
        loading={busy === "mapping"}
        onClick={() => run("mapping", () => adminImportStudioApi.updateMapping(draft.id, parseArray<FieldMappingItem>(mapping, "Field mapping")), "Mapping saved to the draft.")}
      >
        Save mapping
      </Button>

      <label className="block text-sm font-medium">
        Data patches (JSON array)
        <Input.TextArea
          aria-label="Data patches JSON"
          autoSize={{ minRows: 4, maxRows: 10 }}
          disabled={!editable || busy !== null}
          value={patches}
          onChange={(event) => setPatches(event.target.value)}
          placeholder='[{"row_key": "row-1", "column_name": "name", "old_value": null, "new_value": "value", "patch_type": "set"}]'
        />
      </label>
      <Button
        disabled={!editable}
        loading={busy === "patches"}
        onClick={() => run("patches", () => adminImportStudioApi.addPatches(draft.id, parseArray<DataPatchItem>(patches, "Data patches")), "Patches saved to the draft.")}
      >
        Save patches
      </Button>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={!editable}
          loading={busy === "validate"}
          onClick={() => run("validate", () => adminImportStudioApi.validate(draft.id, {
            row_count: draft.row_count,
            column_count: draft.column_count,
            module_key: draft.module_key,
            field_mapping: parseArray<FieldMappingItem>(mapping, "Field mapping"),
          }), "Draft validation completed.")}
        >
          Validate persisted draft
        </Button>
        {Object.keys(draft.validation).length ? (
          <Typography.Text type="secondary">Validation state: {JSON.stringify(draft.validation)}</Typography.Text>
        ) : null}
      </div>

      <div className="space-y-2 rounded border border-amber-500/40 p-3">
        <Typography.Text strong>Explicit publication confirmation</Typography.Text>
        <Input aria-label="Publication source id" disabled={immutable || busy !== null} placeholder="Source ID" value={sourceId} onChange={(event) => setSourceId(event.target.value)} />
        <Input aria-label="Publication kind" disabled={immutable || busy !== null} placeholder="Publication kind" value={kind} onChange={(event) => setKind(event.target.value)} />
        <Input.TextArea aria-label="Publication config JSON" disabled={immutable || busy !== null} placeholder="Publication config JSON" value={config} onChange={(event) => setConfig(event.target.value)} />
        <Button
          danger
          disabled={!committable || !sourceId.trim() || !kind.trim()}
          loading={busy === "commit"}
          onClick={() => {
            if (!window.confirm("Publish this validated draft? This action is explicit and cannot be undone from the draft editor.")) return;
            void run("commit", () => adminImportStudioApi.commit(draft.id, {
              page_id: null,
              source_id: sourceId.trim(),
              kind: kind.trim(),
              config: parseObject(config, "Publication config"),
              confirm: true,
            }), "Draft committed successfully.");
          }}
        >
          Confirm and commit draft
        </Button>
      </div>

      {error ? <Typography.Text type="danger" role="alert">{error}</Typography.Text> : null}
      {notice ? <Typography.Text type="success" role="status">{notice}</Typography.Text> : null}
    </div>
  );
}
