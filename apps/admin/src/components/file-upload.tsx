/**
 * Generic admin file upload (D4) — AntD Upload + presigned streaming upload.
 *
 * Flow (stateless, mirrors apps/api/app/api/v1/admin_uploads.py):
 *   1. Hash the file and request a size/MIME/SHA-256-bound presigned POST.
 *   2. POST signed fields followed by the file (S3/MinIO, XHR for progress).
 *   3. onChange(public_url) — the caller persists it (e.g. cover_url).
 *
 * The component is CONTROLLED via the AntD ProForm field contract
 * (`value` / `onChange`), so it plugs into `ProForm.Item` / form items
 * directly (see news-form.tsx). Supports drag & drop, progress bar, size
 * limit, file-type filter and multi-file mode (maxCount > 1).
 */
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Upload, type UploadFile, type UploadProps } from "antd";
import { App } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { uploadPresign } from "@soymutdb/api-client";

export interface FileUploadProps {
  /** Current value: public URL (single) or array of public URLs (multi). */
  value?: string | string[];
  /** Emit the new value (undefined when cleared). */
  onChange?: (value: string | string[] | undefined) => void;
  /** Object-key namespace segment under `uploads/`, e.g. "news". */
  purpose?: string;
  /** Per-file size limit in MB (default 10). */
  maxSizeMB?: number;
  /** MIME/extension filter, e.g. "image/*". */
  accept?: string;
  /** 1 = single file, >1 = multi-file (default 1). */
  maxCount?: number;
  /** Custom label for the upload trigger button. */
  buttonText?: string;
}

interface PresignPayload {
  upload_url: string;
  upload_method: string;
  upload_fields: Record<string, string>;
  public_url: string;
}

/** Calculate the lowercase hexadecimal SHA-256 of the exact file bytes. */
async function sha256Hex(file: Blob): Promise<string> {
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/** POST signed fields and then the file with XHR upload progress. */
function postWithProgress(
  url: string,
  fields: Record<string, string>,
  file: File | Blob,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const formData = new FormData();
    for (const [name, value] of Object.entries(fields)) {
      formData.append(name, value);
    }
    formData.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload failed with status ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    // Let the browser set multipart/form-data with its generated boundary.
    xhr.send(formData);
  });
}

function toFileList(value: string | string[] | undefined): UploadFile[] {
  const urls = Array.isArray(value) ? value : value ? [value] : [];
  return urls.map((url, index) => ({
    uid: `existing-${index}-${url}`,
    name: url.split("/").pop() || `file-${index}`,
    status: "done",
    url,
  }));
}

export default function FileUpload({
  value,
  onChange,
  purpose = "news",
  maxSizeMB = 10,
  accept,
  maxCount = 1,
  buttonText,
}: FileUploadProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const fileList = toFileList(value);
  const valueRef = useRef(value);

  // In-flight uploads need the latest controlled value when they finish.
  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  const emit = (next: string | string[] | undefined) => {
    onChange?.(next);
  };

  const customRequest: UploadProps["customRequest"] = async (options) => {
    const { file, onSuccess, onError, onProgress } = options;
    const raw = file as File;
    try {
      if (raw.size > maxSizeMB * 1024 * 1024) {
        throw new Error(
          t("admin.uploads.sizeExceeded", { size: String(maxSizeMB) }),
        );
      }
      const contentType = raw.type.trim().toLowerCase();
      if (!contentType) {
        throw new Error("File MIME type is required");
      }
      const checksumSha256 = await sha256Hex(raw);
      const presign: PresignPayload = await uploadPresign({
        filename: raw.name,
        purpose,
        size: raw.size,
        content_type: contentType,
        checksum_sha256: checksumSha256,
      });
      if (presign.upload_method !== "POST") {
        throw new Error("Upload presign response must use POST");
      }
      await postWithProgress(
        presign.upload_url,
        presign.upload_fields,
        raw,
        (percent) => onProgress?.({ percent }),
      );
      onSuccess?.({} as never);

      const newUrl = presign.public_url;
      const current = valueRef.current;
      const next =
        maxCount > 1
          ? [
              ...(Array.isArray(current) ? current : current ? [current] : []),
              newUrl,
            ]
          : newUrl;
      emit(next);
    } catch (err) {
      message.error(
        `${t("admin.uploads.uploadFailed")}: ${err instanceof Error ? err.message : String(err)}`,
      );
      onError?.(err as Error);
    }
  };

  const handleRemove: UploadProps["onRemove"] = (file) => {
    const current = valueRef.current;
    const urls = Array.isArray(current)
      ? current
      : current
        ? [current]
        : [];
    const removed = file.url ?? file.name;
    const next = urls.filter((u) => u !== removed);
    emit(next.length === 0 ? undefined : maxCount > 1 ? next : next[0]);
    return true;
  };

  return (
    <Upload
      listType="picture"
      accept={accept}
      maxCount={maxCount}
      fileList={fileList}
      customRequest={customRequest}
      onRemove={handleRemove}
      beforeUpload={(file) => {
        if (rawSizeExceeds(file, maxSizeMB)) {
          message.error(
            t("admin.uploads.sizeExceeded", { size: String(maxSizeMB) }),
          );
          return Upload.LIST_IGNORE;
        }
        return true;
      }}
    >
      <UploadOutlined /> {buttonText ?? t("admin.uploads.selectFile")}
    </Upload>
  );
}

/** Size guard for beforeUpload (returns true when the file is too big). */
function rawSizeExceeds(file: File, maxSizeMB: number): boolean {
  return file.size > maxSizeMB * 1024 * 1024;
}
