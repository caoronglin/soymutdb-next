/** Shared request construction for the admin import form. */

export interface ImportSubmission {
  filename: string;
  type: string;
  file_path?: string;
  object_key?: string;
  module_key?: string;
  checksum?: string;
  data_set_id: number;
  release_id?: number;
  idempotency_key: string;
}

export interface ImportSubmissionInput {
  filename: string;
  type: string;
  filePath?: string;
  objectKey?: string;
  moduleKey?: string;
  checksum?: string;
  dataSetIdInput?: string;
  releaseIdInput?: string;
  idempotencyKey: string;
}

/** Generate a request key that remains stable for one visible import intent. */
export function createImportIdempotencyKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return `import-${uuid}`;
  return `import-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Parse the intentionally explicit release field accepted by the API. */
export function parseModuleReleaseId(value: string | undefined): number {
  const normalized = value?.trim() ?? "";
  if (!/^[1-9]\d*$/.test(normalized)) {
    throw new Error("A positive release ID is required for module data imports.");
  }
  const releaseId = Number(normalized);
  if (!Number.isSafeInteger(releaseId)) {
    throw new Error("A positive release ID is required for module data imports.");
  }
  return releaseId;
}

/** Parse the explicit data set boundary used for object-key ownership. */
export function parseDataSetId(value: string | undefined): number {
  const normalized = value?.trim() ?? "";
  if (!/^[1-9]\d*$/.test(normalized)) {
    throw new Error("A positive data set ID is required to submit an import.");
  }
  const dataSetId = Number(normalized);
  if (!Number.isSafeInteger(dataSetId)) {
    throw new Error("A positive data set ID is required to submit an import.");
  }
  return dataSetId;
}

/** Build the exact JSON payload accepted by ``POST /admin/imports``. */
export function buildImportSubmission(input: ImportSubmissionInput): ImportSubmission {
  const idempotencyKey = input.idempotencyKey.trim();
  if (!idempotencyKey) {
    throw new Error("An idempotency key is required to submit an import.");
  }

  const submission: ImportSubmission = {
    filename: input.filename,
    type: input.type,
    data_set_id: parseDataSetId(input.dataSetIdInput),
    idempotency_key: idempotencyKey,
  };
  if (input.filePath) submission.file_path = input.filePath;
  if (input.objectKey) submission.object_key = input.objectKey;
  if (input.moduleKey) submission.module_key = input.moduleKey;
  if (input.checksum) submission.checksum = input.checksum;
  if (input.type === "module_tsv") {
    submission.release_id = parseModuleReleaseId(input.releaseIdInput);
  }
  return submission;
}
