import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileExcelOutlined, LoadingOutlined } from "@ant-design/icons";
import { Button, Input, PageContainer, Result, Select, Steps, Typography } from "@/lib/antd";
import { capabilitiesApi, http } from "@soymutdb/api-client";

import { ImportPreviewTable } from "../../components/import-preview-table";
import { resolveFeatureState } from "../../lib/capability-state";
import {
  buildImportSubmission,
  createImportIdempotencyKey,
  describeImportIntent,
  fileExtensionOf,
  parseDataSetId,
  parseModuleReleaseId,
  resolveIdempotencyKey,
  validateModuleImport,
  type ImportSubmission,
} from "../../lib/import-submission";
import {
  describeUploadSource,
  fetchModulePreview,
  uploadModuleFile,
  type ModulePreviewResult,
  type UploadedObject,
} from "../../lib/module-import-upload";

/** The only durable submission writer currently exposed by the console. */
const IMPORT_TYPE = "module_tsv" as const;
const ACCEPTED_EXTENSIONS = ".tsv,.txt,.csv,.xlsx";

const BASE_PATH = import.meta.env.BASE_URL.replace(/\/$/, "");

type SourceMode = "local" | "s3";

const STEP_IDS = ["source", "file", "inspect", "review"] as const;

export default function NewImportPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [step, setStep] = useState(0);
  const [moduleKey, setModuleKey] = useState("genes");
  const [dataSetId, setDataSetId] = useState("1");
  const [releaseId, setReleaseId] = useState("");
  const [sourceMode, setSourceMode] = useState<SourceMode>("local");
  const [file, setFile] = useState<File | null>(null);
  const [filename, setFilename] = useState("");
  const [filePath, setFilePath] = useState("");
  const [checksum, setChecksum] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [previewState, setPreviewState] = useState<
    ModulePreviewResult | { status: "checking" } | null
  >(null);
  const previewRequestToken = useRef(0);

  // One visible intent keeps one key. The API answers a repeated key with the
  // task it already created, so a retry of unchanged fields must replay it
  // while a changed payload must rotate it.
  const [idempotencyKey, setIdempotencyKey] = useState(createImportIdempotencyKey);
  const idempotencyIntentRef = useRef<string | null>(null);
  // The completed browser-direct upload, so a rejected POST does not transfer
  // the same bytes (and create a second object) on retry.
  const uploadedSourceRef = useRef<{ identity: string; uploaded: UploadedObject } | null>(null);
  // Synchronous guard: `uploading`/`isPending` only disable the button after a
  // re-render, so two clicks in one tick would both pass the check.
  const submittingRef = useRef(false);

  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [submittedTaskId, setSubmittedTaskId] = useState<number | null>(null);

  const capabilitiesQuery = useQuery({
    queryKey: ["public-capabilities"],
    queryFn: capabilitiesApi.get,
    staleTime: 30_000,
  });
  const capabilitySnapshot = {
    pending: capabilitiesQuery.isPending,
    error: capabilitiesQuery.isError,
    features: capabilitiesQuery.data?.features,
  };
  const moduleImportState = resolveFeatureState(capabilitySnapshot, "imports.module_tsv");
  const localUploadState = resolveFeatureState(capabilitySnapshot, "imports.local_upload");
  const moduleImportEnabled = moduleImportState === "enabled";
  const localUploadEnabled = localUploadState === "enabled";
  // A disabled local-upload capability falls back to the S3 reference flow
  // instead of leaving a mode the server cannot accept.
  const effectiveSourceMode: SourceMode = localUploadEnabled ? sourceMode : "s3";

  const submitMutation = useMutation({
    mutationFn: (body: ImportSubmission) =>
      http.post<{ id: number }>("/admin/imports", {
        json: body,
        timeoutMs: 30_000,
      }),
    onSuccess: (task) => {
      setSubmittedTaskId(task.id);
      queryClient.invalidateQueries({ queryKey: ["admin-imports"] });
    },
    onSettled: () => {
      submittingRef.current = false;
    },
  });

  const busy = submitMutation.isPending || uploading;

  function invalidatePreview() {
    previewRequestToken.current += 1;
    setPreviewState(null);
  }

  function resetDraft() {
    previewRequestToken.current += 1;
    setStep(0);
    setModuleKey("genes");
    setDataSetId("1");
    setReleaseId("");
    setSourceMode("local");
    setFile(null);
    setFilename("");
    setFilePath("");
    setChecksum("");
    setError(null);
    setPreviewState(null);
    setUploading(false);
    setUploadProgress(0);
    setSubmittedTaskId(null);
    setIdempotencyKey(createImportIdempotencyKey());
    idempotencyIntentRef.current = null;
    uploadedSourceRef.current = null;
    submittingRef.current = false;
    submitMutation.reset();
  }

  function validateSourceStep(): string | null {
    try {
      parseModuleReleaseId(releaseId);
      parseDataSetId(dataSetId);
    } catch (parseError) {
      return parseError instanceof Error ? parseError.message : String(parseError);
    }
    return null;
  }

  function validateFileStep(): string | null {
    const name = effectiveSourceMode === "local" ? (file?.name ?? "") : filename.trim();
    if (effectiveSourceMode === "local" && !file) {
      return t("admin.importStudio.fileRequired");
    }
    if (effectiveSourceMode === "s3" && (!name || !filePath.trim())) {
      return t("admin.importStudio.s3Required");
    }
    return validateModuleImport({
      filename: name,
      moduleKey,
      sourceMode: effectiveSourceMode,
      checksum,
    });
  }

  function goNext() {
    const problem = step === 0 ? validateSourceStep() : step === 1 ? validateFileStep() : null;
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setStep((current) => Math.min(STEP_IDS.length - 1, current + 1));
  }

  function goBack() {
    if (busy) return;
    setError(null);
    setStep((current) => Math.max(0, current - 1));
  }

  /** Bounded, read-only validation preview of the selected local file. */
  function runPreview() {
    if (!file) return;
    const requestToken = ++previewRequestToken.current;
    setPreviewState({ status: "checking" });
    void fetchModulePreview({
      filename: file.name,
      moduleKey: moduleKey.trim() || "genes",
      file,
    })
      .then((result) => {
        if (previewRequestToken.current === requestToken) setPreviewState(result);
      })
      .catch((previewError: unknown) => {
        if (previewRequestToken.current === requestToken) {
          setPreviewState({
            status: "unavailable",
            reason:
              previewError instanceof Error
                ? previewError.message
                : t("admin.importStudio.previewUnavailable"),
          });
        }
      });
  }

  function submitImport(
    input: Omit<ImportSubmission, "data_set_id" | "idempotency_key" | "release_id">,
    dataSet: number,
  ): boolean {
    const intent = describeImportIntent({
      filename: input.filename,
      type: input.type,
      dataSetId: dataSet,
      releaseId,
      objectKey: input.object_key,
      filePath: input.file_path,
      moduleKey: input.module_key,
      checksum: input.checksum,
    });
    const key = resolveIdempotencyKey({
      currentKey: idempotencyKey,
      currentIntent: idempotencyIntentRef.current,
      nextIntent: intent,
      createKey: createImportIdempotencyKey,
    });
    idempotencyIntentRef.current = intent;
    if (key !== idempotencyKey) setIdempotencyKey(key);
    try {
      submitMutation.mutate(
        buildImportSubmission({
          filename: input.filename,
          type: input.type,
          filePath: input.file_path,
          objectKey: input.object_key,
          moduleKey: input.module_key,
          checksum: input.checksum,
          dataSetIdInput: String(dataSet),
          releaseIdInput: releaseId,
          idempotencyKey: key,
        }),
      );
      return true;
    } catch (buildError) {
      setError(buildError instanceof Error ? buildError.message : String(buildError));
      return false;
    }
  }

  /**
   * Validate, upload the local source if it changed, and hand the payload to
   * the mutation. Returns true only when a request was actually sent; the
   * mutation then owns releasing the in-flight guard.
   */
  async function runImportSubmission(): Promise<boolean> {
    setError(null);
    if (!capabilitiesQuery.isSuccess) {
      setError(t("admin.importPage.capabilitiesUnavailable"));
      return false;
    }
    if (!moduleImportEnabled) {
      setError(t("admin.importStudio.capabilityUnavailable"));
      return false;
    }

    let dataSet: number;
    try {
      parseModuleReleaseId(releaseId);
      dataSet = parseDataSetId(dataSetId);
    } catch (parseError) {
      setError(parseError instanceof Error ? parseError.message : String(parseError));
      return false;
    }

    if (effectiveSourceMode === "local") {
      if (!file) {
        setError(t("admin.importStudio.fileRequired"));
        return false;
      }
      const name = file.name;
      const key = moduleKey.trim();
      const invalid = validateModuleImport({ filename: name, moduleKey: key, sourceMode: "local" });
      if (invalid) {
        setError(invalid);
        return false;
      }

      const identity = describeUploadSource({
        filename: name,
        size: file.size,
        lastModified: file.lastModified,
        type: IMPORT_TYPE,
        moduleKey: key,
        dataSetId: dataSet,
      });
      const alreadyUploaded = uploadedSourceRef.current;
      let uploaded: UploadedObject;
      if (alreadyUploaded && alreadyUploaded.identity === identity) {
        // The same bytes already reached object storage for this data set.
        uploaded = alreadyUploaded.uploaded;
      } else {
        setUploading(true);
        setUploadProgress(0);
        try {
          uploaded = await uploadModuleFile({
            filename: name,
            type: IMPORT_TYPE,
            file,
            dataSetId: dataSet,
            onProgress: (progress) => setUploadProgress(progress.percent),
          });
        } catch (uploadError) {
          setError(
            uploadError instanceof Error ? uploadError.message : String(uploadError),
          );
          return false;
        } finally {
          setUploading(false);
        }
        uploadedSourceRef.current = { identity, uploaded };
      }

      return submitImport(
        {
          filename: name,
          type: IMPORT_TYPE,
          object_key: uploaded.object_key,
          module_key: key,
          checksum: uploaded.sha256,
        },
        dataSet,
      );
    }

    const name = filename.trim();
    if (!name || !filePath.trim()) {
      setError(t("admin.importStudio.s3Required"));
      return false;
    }
    const key = moduleKey.trim();
    const invalid = validateModuleImport({
      filename: name,
      moduleKey: key,
      sourceMode: "s3",
      checksum,
    });
    if (invalid) {
      setError(invalid);
      return false;
    }
    return submitImport(
      {
        filename: name,
        type: IMPORT_TYPE,
        file_path: filePath.trim(),
        module_key: key,
        checksum: checksum.trim(),
      },
      dataSet,
    );
  }

  async function handleSubmit() {
    if (submittingRef.current) return;
    submittingRef.current = true;
    try {
      if (!(await runImportSubmission())) submittingRef.current = false;
    } catch (submitError) {
      submittingRef.current = false;
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    }
  }

  const stepItems = [
    { title: t("admin.importStudio.stepSource") },
    { title: t("admin.importStudio.stepFile") },
    { title: t("admin.importStudio.stepInspect") },
    { title: t("admin.importStudio.stepReview") },
  ];

  if (submittedTaskId !== null) {
    return (
      <PageContainer
        title={t("admin.importStudio.newImport")}
        subTitle={t("admin.importStudio.subtitle")}
      >
        <Result
          data-testid="import-submitted"
          status="success"
          title={t("admin.importStudio.submitted")}
          subTitle={t("admin.importStudio.submittedHint", {
            id: String(submittedTaskId),
            defaultValue: "Import task {{id}} has been queued.",
          })}
          extra={[
            <Button
              key="open"
              type="primary"
              href={`${BASE_PATH}/imports/${submittedTaskId}`}
              data-testid="import-open-task"
            >
              {t("admin.importStudio.openTask")}
            </Button>,
            <Button key="list" href={`${BASE_PATH}/imports`} data-testid="import-back-to-list">
              {t("admin.importStudio.backToList")}
            </Button>,
            <Button key="over" onClick={resetDraft} data-testid="import-start-over">
              {t("admin.importStudio.startOver")}
            </Button>,
          ]}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title={t("admin.importStudio.newImport")}
      subTitle={t("admin.importStudio.subtitle")}
    >
      <div className="space-y-6" data-testid="import-wizard">
        {capabilitiesQuery.isPending ? (
          <p
            role="status"
            data-testid="import-capabilities-loading"
            className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground"
          >
            {t("admin.importStudio.loadingCapabilities")}
          </p>
        ) : null}
        {capabilitiesQuery.isError ? (
          <p
            role="alert"
            data-testid="import-capabilities-error"
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {t("admin.importPage.capabilitiesUnavailable")}
          </p>
        ) : null}
        {capabilitiesQuery.isSuccess && !moduleImportEnabled ? (
          <p
            role="alert"
            data-testid="import-module-disabled"
            className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground"
          >
            {t("admin.importStudio.capabilityUnavailable")}
          </p>
        ) : null}

        <Steps current={step} items={stepItems} data-testid="import-steps" />

        <section
          data-testid={`import-wizard-step-${STEP_IDS[step]}`}
          className="rounded-lg border bg-card p-4"
        >
          {step === 0 ? (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="import-type">{t("admin.importPage.importType")}</label>
                <p id="import-type" className="text-sm font-medium">
                  {t("admin.importStudio.moduleData")}
                </p>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="import-module-key">{t("admin.importPage.moduleKey")}</label>
                <Input
                  id="import-module-key"
                  placeholder={t("admin.importPage.moduleKeyPlaceholder")}
                  value={moduleKey}
                  onChange={(event) => {
                    setModuleKey(event.target.value);
                    setError(null);
                    invalidatePreview();
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  {t("admin.importStudio.moduleHint")}
                </p>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="import-data-set-id">{t("admin.importPage.datasetId")}</label>
                <Input
                  id="import-data-set-id"
                  type="number"
                  min="1"
                  inputMode="numeric"
                  placeholder={t("admin.importPage.datasetIdPlaceholder")}
                  value={dataSetId}
                  onChange={(event) => {
                    setDataSetId(event.target.value);
                    setError(null);
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  {t("admin.importStudio.datasetHint")}
                </p>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="import-release-id">{t("admin.importPage.releaseId")}</label>
                <Input
                  id="import-release-id"
                  type="number"
                  min="1"
                  inputMode="numeric"
                  placeholder={t("admin.importPage.releaseIdPlaceholder")}
                  value={releaseId}
                  onChange={(event) => {
                    setReleaseId(event.target.value);
                    setError(null);
                  }}
                />
                <p className="text-xs text-muted-foreground">
                  {t("admin.importStudio.releaseHint")}
                </p>
              </div>
            </div>
          ) : null}

          {step === 1 ? (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <label htmlFor="import-mode">{t("admin.importPage.source")}</label>
                <Select
                  id="import-mode"
                  value={effectiveSourceMode}
                  onChange={(value) => {
                    setSourceMode(value as SourceMode);
                    setError(null);
                    invalidatePreview();
                  }}
                  options={[
                    {
                      value: "local",
                      label: t("admin.importPage.localFile"),
                      disabled: !localUploadEnabled,
                    },
                    { value: "s3", label: t("admin.importPage.s3Uri") },
                  ]}
                />
                <p className="text-xs text-muted-foreground">
                  {t("admin.importStudio.fileHint")}
                </p>
              </div>

              {effectiveSourceMode === "local" ? (
                <div className="space-y-1.5">
                  <label>{t("admin.importPage.file")}</label>
                  <FileDropInput
                    file={file}
                    onSelect={(selected) => {
                      setFile(selected);
                      setFilename(selected.name);
                      setError(null);
                      invalidatePreview();
                    }}
                    accept={ACCEPTED_EXTENSIONS}
                  />
                  {file ? (
                    <p className="text-xs text-muted-foreground">
                      {file.name} · {formatBytes(file.size)} ·{" "}
                      {fileExtensionOf(file.name).replace(".", "").toUpperCase()}
                    </p>
                  ) : null}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <label htmlFor="import-filename">{t("admin.importPage.filename")}</label>
                    <Input
                      id="import-filename"
                      placeholder="e.g. genes.tsv"
                      value={filename}
                      onChange={(event) => {
                        setFilename(event.target.value);
                        setError(null);
                        invalidatePreview();
                      }}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="import-filepath">{t("admin.importPage.s3FilePath")}</label>
                    <Input
                      id="import-filepath"
                      placeholder={t("admin.importPage.s3FilePathPlaceholder")}
                      value={filePath}
                      onChange={(event) => {
                        setFilePath(event.target.value);
                        setError(null);
                      }}
                    />
                    <p className="text-xs text-muted-foreground">
                      {t("admin.importStudio.s3Hint")}
                    </p>
                  </div>
                  <div className="space-y-1.5">
                    <label htmlFor="import-checksum">{t("admin.importPage.checksum")}</label>
                    <Input
                      id="import-checksum"
                      placeholder={t("admin.importPage.checksumPlaceholder")}
                      value={checksum}
                      onChange={(event) => {
                        setChecksum(event.target.value);
                        setError(null);
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          ) : null}

          {step === 2 ? (
            <div className="space-y-3">
              <Typography.Text type="secondary">
                {t("admin.importStudio.inspectHint")}
              </Typography.Text>
              {effectiveSourceMode === "local" && file ? (
                <div>
                  <Button
                    htmlType="button"
                    data-testid="import-preview-run"
                    onClick={runPreview}
                    disabled={previewState?.status === "checking"}
                  >
                    {previewState?.status === "checking" ? (
                      <LoadingOutlined className="size-3.5 animate-spin" />
                    ) : null}
                    {t("admin.importStudio.inspect")}
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("admin.importStudio.inspectLocalOnly")}
                </p>
              )}

              {previewState?.status === "unavailable" ? (
                <p
                  data-testid="import-preview-unavailable"
                  className="text-sm text-muted-foreground"
                >
                  {previewState.reason}
                </p>
              ) : null}

              {previewState?.status === "available" ? (
                <div
                  data-testid="import-preview-result"
                  className="space-y-2 rounded-md border border-border p-3"
                >
                  <p className="text-xs text-muted-foreground">
                    {t("admin.importStudio.previewRows", {
                      rows: String(previewState.rowCount),
                    })}
                    {previewState.truncated ? ` ${t("admin.importStudio.previewTruncated")}` : ""}
                    {" "}
                    {t("admin.importStudio.previewReadOnly")}
                  </p>
                  {!previewState.validation.ok ? (
                    <p className="text-xs text-destructive">
                      {t("admin.importStudio.previewErrors")}: {previewState.validation.errorCount}
                      {previewState.validation.errors[0]
                        ? ` — ${previewState.validation.errors[0].message}`
                        : ""}
                    </p>
                  ) : null}
                  {previewState.rows.length > 0 && previewState.headers.length > 0 ? (
                    <ImportPreviewTable
                      ariaLabel={t("admin.importStudio.previewReadOnly")}
                      columns={previewState.headers}
                      rows={previewState.rows}
                      rowKey={(row, index) =>
                        `${index}:${String(row.gene_id ?? row.id ?? "row")}`
                      }
                      editable={false}
                      height={240}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {t("admin.importStudio.previewNoRows")}
                    </p>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 3 ? (
            <dl className="grid gap-3 text-sm sm:grid-cols-2" data-testid="import-review">
              <div>
                <dt className="text-muted-foreground">{t("admin.importStudio.module")}</dt>
                <dd className="font-medium">{moduleKey.trim()}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.importPage.datasetId")}</dt>
                <dd className="font-medium">{dataSetId.trim()}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.importPage.releaseId")}</dt>
                <dd className="font-medium">{releaseId.trim()}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t("admin.importPage.source")}</dt>
                <dd className="font-medium">
                  {effectiveSourceMode === "local"
                    ? t("admin.importPage.localFile")
                    : t("admin.importPage.s3Uri")}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">{t("admin.importPage.file")}</dt>
                <dd className="font-medium">
                  {effectiveSourceMode === "local"
                    ? `${file?.name ?? ""} · ${formatBytes(file?.size ?? 0)}`
                    : filename.trim()}
                </dd>
              </div>
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">{t("admin.importPage.checksum")}</dt>
                <dd className="font-mono text-xs">
                  {effectiveSourceMode === "local"
                    ? t("admin.importStudio.reviewChecksumPending")
                    : checksum.trim()}
                </dd>
              </div>
            </dl>
          ) : null}
        </section>

        {error ? (
          <p
            role="alert"
            data-testid="import-wizard-error"
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {error}
          </p>
        ) : null}

        {submitMutation.isError && !error ? (
          <p
            role="alert"
            data-testid="import-submit-error"
            className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"
          >
            {t("admin.importStudio.submitError")}
            {": "}
            {submitMutation.error instanceof Error
              ? submitMutation.error.message
              : String(submitMutation.error)}
          </p>
        ) : null}

        {uploading ? (
          <div
            role="progressbar"
            aria-valuenow={uploadProgress}
            aria-valuemin={0}
            aria-valuemax={100}
            data-testid="import-upload-progress"
            className="space-y-1"
          >
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              {t("admin.importStudio.uploadProgress")} {uploadProgress}%
            </p>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            data-testid="import-wizard-start-over"
            onClick={resetDraft}
            disabled={busy}
          >
            {t("admin.importStudio.startOver")}
          </Button>
          {step > 0 ? (
            <Button data-testid="import-wizard-back" onClick={goBack} disabled={busy}>
              {t("admin.importStudio.back")}
            </Button>
          ) : null}
          {step < STEP_IDS.length - 1 ? (
            <Button
              type="primary"
              data-testid="import-wizard-next"
              onClick={goNext}
              disabled={busy || !capabilitiesQuery.isSuccess || !moduleImportEnabled}
            >
              {t("admin.importStudio.continue")}
            </Button>
          ) : (
            <Button
              type="primary"
              data-testid="import-wizard-submit"
              onClick={handleSubmit}
              disabled={busy || !capabilitiesQuery.isSuccess || !moduleImportEnabled}
            >
              {busy ? (
                <>
                  <LoadingOutlined className="size-4 animate-spin" />
                  {t("admin.importStudio.submitting")}
                </>
              ) : (
                t("admin.importStudio.submit")
              )}
            </Button>
          )}
        </div>
      </div>
    </PageContainer>
  );
}

interface FileDropInputProps {
  file: File | null;
  accept: string;
  onSelect: (file: File) => void;
}

function FileDropInput({ file, accept, onSelect }: FileDropInputProps) {
  const { t } = useTranslation();
  return (
    <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-dashed border-border p-4 text-sm hover:border-primary">
      <FileExcelOutlined className="size-5 text-primary" aria-hidden />
      <span className="min-w-0 flex-1 truncate">
        {file?.name ?? t("admin.importStudio.chooseFile")}
      </span>
      <input
        type="file"
        className="sr-only"
        accept={accept}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) onSelect(selected);
          event.currentTarget.value = "";
        }}
      />
      <span className="text-xs font-medium text-primary">{t("admin.importStudio.browse")}</span>
    </label>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}