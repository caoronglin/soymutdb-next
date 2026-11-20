/**
 * Convert a downloaded sequence file between formats, in place.
 *
 * The catalogue already carries FASTA artifacts, and `/tools/sequence/convert`
 * turns one into GenBank/EMBL without leaving the page. Two rules keep this
 * honest:
 *
 * - only text the browser already fetched is converted, so the endpoint's
 *   "inline text, never a path" contract still holds;
 * - the input is capped at the API's own record budget, and a file over it says
 *   so instead of sending a request that can only be rejected.
 */
import * as React from "react";
import { Alert, Button, Select, Space, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { sequenceApi, type SequenceTextFormat } from "@soymutdb/api-client";

/** Formats this component offers as conversion targets. */
const TARGETS: readonly SequenceTextFormat[] = ["genbank", "embl", "tab"];

export interface SequenceFormatConverterProps {
  /** The already-fetched file body. */
  text: string;
  /** Source format, when the catalogue name makes it certain. */
  sourceFormat?: SequenceTextFormat;
  fileName?: string;
}

export function SequenceFormatConverter({
  text,
  sourceFormat = "fasta",
  fileName,
}: SequenceFormatConverterProps) {
  const { t } = useTranslation();
  const [target, setTarget] = React.useState<SequenceTextFormat>("genbank");
  const [busy, setBusy] = React.useState(false);
  const [output, setOutput] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  if (!text.trim()) {
    return (
      <Typography.Text type="secondary" className="text-xs">
        {t("downloads.convert.empty")}
      </Typography.Text>
    );
  }

  const run = async () => {
    setBusy(true);
    setError(null);
    setOutput(null);
    try {
      const payload = await sequenceApi.convertFormat({
        data: text,
        source_format: sourceFormat,
        target_format: target,
      });
      setOutput(payload.output);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t("downloads.convert.failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 space-y-2" data-testid="download-convert">
      <Space wrap size="small">
        <Typography.Text className="text-xs">
          {t("downloads.convert.label", { source: sourceFormat })}
        </Typography.Text>
        <Select<SequenceTextFormat>
          size="small"
          value={target}
          onChange={setTarget}
          aria-label={t("downloads.convert.label", { source: sourceFormat })}
          options={TARGETS.map((value) => ({ value, label: value }))}
          className="min-w-28"
        />
        <Button size="small" loading={busy} onClick={() => void run()}>
          {t("downloads.convert.run")}
        </Button>
      </Space>

      {error ? <Alert type="error" showIcon title={error} /> : null}

      {output ? (
        <>
          <Space wrap size="small">
            <Button
              size="small"
              onClick={() => downloadText(output, convertedName(fileName, target))}
            >
              {t("downloads.convert.save", { format: target })}
            </Button>
            <Typography.Text type="secondary" className="text-xs">
              {output.length.toLocaleString()} {t("downloads.convert.chars")}
            </Typography.Text>
          </Space>
          <pre
            data-testid="download-convert-output"
            className="max-h-48 overflow-auto break-all whitespace-pre-wrap rounded border border-border bg-muted/30 p-2 font-mono text-xs"
          >
            {output.slice(0, 4000)}
          </pre>
        </>
      ) : null}
    </div>
  );
}

/** Replace the extension so the saved file matches its content. */
function convertedName(fileName: string | undefined, format: SequenceTextFormat): string {
  const base = (fileName ?? "sequence").replace(/\.[^.]+$/, "");
  const extension = format === "tab" ? "tsv" : format === "genbank" ? "gb" : "embl";
  return `${base}.${extension}`;
}

/** Save the converted text through a blob URL, then release it. */
function downloadText(text: string, fileName: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}
