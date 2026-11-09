import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      setError(reason instanceof Error ? reason.message : t("admin.importDraft.operationFailed", { defaultValue: "The draft operation failed." }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="mt-4 space-y-4 border-t border-primary/20 pt-4">
      <Typography.Text type="secondary">
        {t("admin.importDraft.intro", {
          defaultValue:
            "Mapping, patches, validation, and publication operate on this persisted draft. Immutable source metadata and row counts are not editable here.",
        })}
      </Typography.Text>
      {editable ? null : (
        <Typography.Text type="secondary">
          {immutable
            ? t("admin.importDraft.committedLocked", {
                defaultValue: "This draft is committed; all editing controls are locked.",
              })
            : committable
              ? t("admin.importDraft.publishableLocked", {
                  defaultValue:
                    "This draft is {{status}}; mapping, patches, and validation are locked. Publication is available below.",
                  status: draft.status,
                })
              : t("admin.importDraft.readOnlyLocked", {
                  defaultValue:
                    "This draft is {{status}}; mapping, patches, validation, and publication are unavailable.",
                  status: draft.status,
                })}
        </Typography.Text>
      )}

      <label className="block text-sm font-medium">
        {t("admin.importDraft.fieldMapping", { defaultValue: "Field mapping (JSON array)" })}
        <Input.TextArea
          aria-label={t("admin.importDraft.fieldMapping", { defaultValue: "Field mapping (JSON array)" })}
          autoSize={{ minRows: 5, maxRows: 12 }}
          disabled={!editable || busy !== null}
          value={mapping}
          onChange={(event) => setMapping(event.target.value)}
        />
      </label>
      <Button
        disabled={!editable}
        loading={busy === "mapping"}
        onClick={() =>
          run(
            "mapping",
            () =>
              adminImportStudioApi.updateMapping(
                draft.id,
                parseArray<FieldMappingItem>(mapping, t("admin.importDraft.fieldMappingLabel", { defaultValue: "Field mapping" })),
              ),
            t("admin.importDraft.mappingSaved", { defaultValue: "Mapping saved to the draft." }),
          )
        }
      >
        {t("admin.importDraft.saveMapping", { defaultValue: "Save mapping" })}
      </Button>

      <label className="block text-sm font-medium">
        {t("admin.importDraft.dataPatches", { defaultValue: "Data patches (JSON array)" })}
        <Input.TextArea
          aria-label={t("admin.importDraft.dataPatches", { defaultValue: "Data patches (JSON array)" })}
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
        onClick={() =>
          run(
            "patches",
            () =>
              adminImportStudioApi.addPatches(
                draft.id,
                parseArray<DataPatchItem>(patches, t("admin.importDraft.dataPatchesLabel", { defaultValue: "Data patches" })),
              ),
            t("admin.importDraft.patchesSaved", { defaultValue: "Patches saved to the draft." }),
          )
        }
      >
        {t("admin.importDraft.savePatches", { defaultValue: "Save patches" })}
      </Button>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          disabled={!editable}
          loading={busy === "validate"}
          onClick={() =>
            run(
              "validate",
              () =>
                adminImportStudioApi.validate(draft.id, {
                  row_count: draft.row_count,
                  column_count: draft.column_count,
                  module_key: draft.module_key,
                  field_mapping: parseArray<FieldMappingItem>(
                    mapping,
                    t("admin.importDraft.fieldMappingLabel", { defaultValue: "Field mapping" }),
                  ),
                }),
              t("admin.importDraft.validationCompleted", { defaultValue: "Draft validation completed." }),
            )
          }
        >
          {t("admin.importDraft.validate", { defaultValue: "Validate persisted draft" })}
        </Button>
        {Object.keys(draft.validation).length ? (
          <Typography.Text type="secondary">
            {t("admin.importDraft.validationState", {
              defaultValue: "Validation state: {{state}}",
              state: JSON.stringify(draft.validation),
            })}
          </Typography.Text>
        ) : null}
      </div>

      <div className="space-y-2 rounded border border-amber-500/40 p-3">
        <Typography.Text strong>{t("admin.importDraft.publicationTitle", { defaultValue: "Explicit publication confirmation" })}</Typography.Text>
        <Input
          aria-label={t("admin.importDraft.publicationSourceId", { defaultValue: "Publication source id" })}
          disabled={immutable || busy !== null}
          placeholder={t("admin.importDraft.publicationSourceIdPlaceholder", { defaultValue: "Source ID" })}
          value={sourceId}
          onChange={(event) => setSourceId(event.target.value)}
        />
        <Input
          aria-label={t("admin.importDraft.publicationKind", { defaultValue: "Publication kind" })}
          disabled={immutable || busy !== null}
          placeholder={t("admin.importDraft.publicationKindPlaceholder", { defaultValue: "Publication kind" })}
          value={kind}
          onChange={(event) => setKind(event.target.value)}
        />
        <Input.TextArea
          aria-label={t("admin.importDraft.publicationConfig", { defaultValue: "Publication config JSON" })}
          disabled={immutable || busy !== null}
          placeholder={t("admin.importDraft.publicationConfig", { defaultValue: "Publication config JSON" })}
          value={config}
          onChange={(event) => setConfig(event.target.value)}
        />
        <Button
          danger
          disabled={!committable || !sourceId.trim() || !kind.trim()}
          loading={busy === "commit"}
          onClick={() => {
            if (
              !window.confirm(
                t("admin.importDraft.publishConfirm", {
                  defaultValue:
                    "Publish this validated draft? This action is explicit and cannot be undone from the draft editor.",
                }),
              )
            )
              return;
            void run(
              "commit",
              () =>
                adminImportStudioApi.commit(draft.id, {
                  page_id: null,
                  source_id: sourceId.trim(),
                  kind: kind.trim(),
                  config: parseObject(config, t("admin.importDraft.publicationConfigLabel", { defaultValue: "Publication config" })),
                  confirm: true,
                }),
              t("admin.importDraft.committed", { defaultValue: "Draft committed successfully." }),
            );
          }}
        >
          {t("admin.importDraft.confirmCommit", { defaultValue: "Confirm and commit draft" })}
        </Button>
      </div>

      {error ? <Typography.Text type="danger" role="alert">{error}</Typography.Text> : null}
      {notice ? <Typography.Text type="success" role="status">{notice}</Typography.Text> : null}
    </div>
  );
}
