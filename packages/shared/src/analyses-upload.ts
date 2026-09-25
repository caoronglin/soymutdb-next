/**
 * Analysis-job upload pipeline (framework-neutral).
 *
 * Flow, identical for every caller (checksum → presigned POST → submit):
 *   1. Hash each file with the incremental SHA-256 in bounded chunks, so a
 *      browser never materializes a whole upload in JavaScript memory.
 *   2. Presign every file before any object-store bytes move.
 *   3. Upload sequentially, reporting progress over *logical* bytes rather than
 *      multipart framing bytes.
 *   4. Submit the job only after every object-store POST succeeds.
 *
 * The pure parts live here; `apps/web/src/lib/use-analysis-upload.ts` and
 * the React hook are only the reactive wrappers.
 */
import { IncrementalSha256, SHA256_CHUNK_BYTES } from "./incremental-sha256";

export const MAX_ANALYSIS_FILE_BYTES = 500 * 1024 * 1024;

const SHA256_HEX_PATTERN = /^[0-9a-f]{64}$/;

function clampRatio(ratio: number): number {
  if (!Number.isFinite(ratio)) return 0;
  return Math.min(1, Math.max(0, ratio));
}

/**
 * Hash a File in bounded chunks. The resulting lowercase hex digest is the value
 * bound into the signed POST policy and checked by object storage and by the
 * API at submission.
 */
export async function calculateFileSha256(file: File): Promise<string> {
  if (file.size > MAX_ANALYSIS_FILE_BYTES) {
    throw new Error(`File "${file.name}" exceeds the 500 MiB upload limit.`);
  }

  try {
    const hasher = new IncrementalSha256();
    for (let offset = 0; offset < file.size; offset += SHA256_CHUNK_BYTES) {
      const chunk = file.slice(offset, Math.min(offset + SHA256_CHUNK_BYTES, file.size));
      hasher.update(new Uint8Array(await chunk.arrayBuffer()));
    }
    const checksum = hasher.digestHex();

    if (!SHA256_HEX_PATTERN.test(checksum)) {
      throw new Error("Incremental SHA-256 returned an invalid digest");
    }
    return checksum;
  } catch (error) {
    const detail = error instanceof Error ? `: ${error.message}` : "";
    throw new Error(`Unable to calculate SHA-256 for "${file.name}"${detail}`, {
      cause: error,
    });
  }
}

/** Multipart POST with upload progress. The browser supplies the boundary. */
export function postWithProgress(
  url: string,
  uploadMethod: unknown,
  uploadFields: Record<string, string> | undefined,
  file: File,
  onProgress: (ratio: number) => void,
): Promise<void> {
  if (uploadMethod !== "POST") {
    return Promise.reject(
      new Error(`Unsupported analysis upload method "${String(uploadMethod)}"; expected POST.`),
    );
  }

  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [name, value] of Object.entries(uploadFields ?? {})) {
      form.append(name, value);
    }
    // S3-compatible presigned POSTs require the binary part after all policy fields.
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      // loaded/total both include multipart framing; the ratio is mapped onto
      // the logical file size by the caller instead of comparing the two.
      if (event.lengthComputable && event.total > 0) {
        onProgress(clampRatio(event.loaded / event.total));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(`Upload failed (HTTP ${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed — network error"));
    xhr.onabort = () => reject(new Error("Upload aborted"));
    xhr.send(form);
  });
}

export function calculateUploadProgress(input: {
  completedBytes: number;
  totalBytes: number;
  currentFileBytes: number;
  currentFileRatio: number;
  completedFiles: number;
  totalFiles: number;
}): number {
  const currentRatio = clampRatio(input.currentFileRatio);
  let ratio: number;

  if (input.totalBytes > 0) {
    ratio =
      (Math.max(0, input.completedBytes) +
        Math.max(0, input.currentFileBytes) * currentRatio) /
      input.totalBytes;
  } else if (input.totalFiles > 0) {
    // All files are empty: use the completion count so progress stays finite.
    ratio = (Math.max(0, input.completedFiles) + currentRatio) / input.totalFiles;
  } else {
    return 0;
  }

  return Math.min(99, Math.max(0, Math.round(clampRatio(ratio) * 100)));
}
