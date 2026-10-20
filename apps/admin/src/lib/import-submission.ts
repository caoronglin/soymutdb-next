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

/**
 * File extensions accepted for module data imports.
 *
 * These mirror the backend's ``SUPPORTED_MODULE_FORMATS`` (``detect_format``
 * returns ``None`` for anything else, and the API rejects the submission with
 * 422). They live here so the local-upload and S3-URI branches validate the
 * same list instead of drifting apart.
 */
export const MODULE_FORMAT_EXTENSIONS = [".tsv", ".txt", ".csv", ".xlsx"] as const;

/** Lower-cased trailing extension of a filename, or ``""`` when there is none. */
export function fileExtensionOf(filename: string): string {
  return filename.toLowerCase().match(/\.[a-z0-9]+$/)?.[0] ?? "";
}

/** Whether a filename carries a module-import supported extension. */
export function isSupportedModuleFilename(filename: string): boolean {
  const ext = fileExtensionOf(filename);
  return ext !== "" && (MODULE_FORMAT_EXTENSIONS as readonly string[]).includes(ext);
}

export interface ModuleImportValidationInput {
  filename: string;
  moduleKey: string;
  sourceMode: "local" | "s3";
  /** Only read in ``s3`` mode; the local flow gets the digest from the upload. */
  checksum?: string;
}

/**
 * First blocking reason for a module data import, or ``null`` when the draft is
 * submittable. The check order (extension, module key, then S3 checksum) and
 * the exact messages are the ones the form has always shown, so this is a
 * de-duplication of two identical inline chains rather than a new policy.
 */
export function validateModuleImport(
  input: ModuleImportValidationInput,
): string | null {
  if (!isSupportedModuleFilename(input.filename)) {
    return `Module data files must use one of ${MODULE_FORMAT_EXTENSIONS.join(" / ")}.`;
  }
  if (!input.moduleKey.trim()) {
    return "Module key is required for module data imports.";
  }
  if (input.sourceMode === "s3" && !input.checksum?.trim()) {
    return "Checksum is required for module data imports.";
  }
  return null;
}

/** The fields that make one submission a distinct import intent. */
export interface ImportIntentInput {
  filename: string;
  type: string;
  dataSetId: number;
  releaseId?: string;
  objectKey?: string;
  filePath?: string;
  moduleKey?: string;
  checksum?: string;
}

/**
 * Stable signature of a submission intent.
 *
 * ``POST /admin/imports`` stores the idempotency key under a unique constraint
 * and returns the *existing* task when the key repeats, so the client must mint
 * a new key exactly when the payload changes. Two submissions sharing a
 * signature are the same intent and must keep one key.
 */
export function describeImportIntent(input: ImportIntentInput): string {
  return JSON.stringify([
    input.type,
    input.dataSetId,
    input.filename.trim(),
    input.releaseId?.trim() ?? "",
    input.objectKey ?? "",
    input.filePath?.trim() ?? "",
    input.moduleKey?.trim() ?? "",
    input.checksum?.trim() ?? "",
  ]);
}

export interface ResolveIdempotencyKeyArgs {
  /** Key currently held by the form; may be empty before the first submit. */
  currentKey: string;
  /** Signature the current key was issued for; ``null`` when never issued. */
  currentIntent: string | null;
  /** Signature of the payload about to be submitted. */
  nextIntent: string;
  createKey: () => string;
}

/**
 * Pick the idempotency key for a submission: reuse the current key only while
 * the intent is unchanged, otherwise mint a fresh one.
 *
 * Reusing across a changed payload would make the API answer with the previous
 * task instead of importing the new content. Rotating on every submit would
 * defeat the de-duplication the key exists for, so retrying a failed submit of
 * unchanged fields keeps the original key.
 */
export function resolveIdempotencyKey(args: ResolveIdempotencyKeyArgs): string {
  const currentKey = args.currentKey.trim();
  if (!currentKey || args.currentIntent === null) return args.createKey();
  return args.currentIntent === args.nextIntent ? currentKey : args.createKey();
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
