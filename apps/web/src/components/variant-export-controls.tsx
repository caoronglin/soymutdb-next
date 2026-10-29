/**
 * Variant export control — the portal's single owner for the export chain.
 *
 * The export endpoint requires the researcher capability, so the control is
 * only offered to a session the server would accept: a visitor without that
 * capability gets an explicit sign-in path instead of a button that would be
 * refused with a 403. The submit → poll → download lifecycle itself lives in
 * `lib/use-variant-export.ts`.
 *
 * Both surfaces that offer an export (the variants workspace and the
 * downloads catalogue) render this component, so the ownership rules and the
 * state vocabulary are defined once.
 */

import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { DownloadOutlined as Download, LoginOutlined } from "@ant-design/icons";
import { Button, Typography } from "@/lib/antd";
import { useIsResearcher } from "../lib/use-current-user";
import {
  useVariantExport,
  type VariantExportFilters,
  type VariantExportFormat,
} from "../lib/use-variant-export";

export interface VariantExportControlsProps {
  /**
   * The single assembly namespace the artifact is built from.
   *
   * Empty means the namespace is not resolved yet; the submission stays
   * disabled instead of sending a request that could mix namespaces.
   */
  assemblyKey: string;
  /** The filters the artifact is built from. */
  filters?: VariantExportFilters;
  /** Artifact format; defaults to the tab-separated variant table. */
  format?: VariantExportFormat;
  /** Whether the artifact is compressed; defaults to true. */
  compress?: boolean;
  /** The submit button's label. */
  submitLabel: React.ReactNode;
  /** Extra classes for the wrapper. */
  className?: string;
}

export function VariantExportControls({
  assemblyKey,
  filters,
  format,
  compress,
  submitLabel,
  className,
}: VariantExportControlsProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { isResearcher, isLoading } = useIsResearcher();
  const {
    submitState,
    exportId,
    exportStatus,
    exportErrorMessage,
    downloadError,
    pollExpired,
    requestExport,
    downloadExport,
    checkAgain,
  } = useVariantExport({
    assemblyKey,
    filters,
    format,
    compress,
    downloadErrorFallback: t("variants.exportDownloadFailed"),
  });

  // A capability the server has not confirmed yet must not be read as a
  // refusal: the control waits instead of disappearing.
  const capabilityKnown = !isLoading;
  const canExport = isResearcher && Boolean(assemblyKey);

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          icon={<Download className="size-4" aria-hidden />}
          onClick={() => void requestExport()}
          loading={submitState.status === "loading"}
          disabled={!canExport}
          data-testid="variant-export-submit"
        >
          {submitLabel}
        </Button>
        {capabilityKnown && !isResearcher ? (
          <Typography.Text type="secondary" data-testid="variant-export-gate">
            {t("variants.exportRequiresAccount")}
          </Typography.Text>
        ) : null}
        {capabilityKnown && !isResearcher ? (
          <Button
            size="small"
            icon={<LoginOutlined className="size-4" aria-hidden />}
            onClick={() => navigate({ to: "/login" })}
          >
            {t("variants.exportSignIn")}
          </Button>
        ) : null}
      </div>
      {submitState.status === "success" || submitState.status === "error" ? (
        <Typography.Paragraph
          className="mt-3"
          type={submitState.status === "error" ? "danger" : "secondary"}
          data-testid="variant-export-status"
        >
          {submitState.message}
        </Typography.Paragraph>
      ) : null}
      {exportId ? (
        <div className="mt-3 flex flex-wrap items-center gap-3" data-testid="variant-export-progress">
          <Typography.Text type="secondary" data-testid="variant-export-state">
            {exportStatus === "succeeded"
              ? t("variants.exportReady")
              : exportStatus === "failed"
                ? t("variants.exportFailed")
                : exportStatus === "running"
                  ? t("variants.exportRunning")
                  : t("variants.exportPending")}
          </Typography.Text>
          {exportStatus === "succeeded" ? (
            <Button
              icon={<Download className="size-4" aria-hidden />}
              onClick={() => void downloadExport()}
              data-testid="variant-export-download"
            >
              {t("variants.exportDownload")}
            </Button>
          ) : null}
          {exportStatus === "failed" && exportErrorMessage ? (
            <Typography.Text type="danger" data-testid="variant-export-error">
              {exportErrorMessage}
            </Typography.Text>
          ) : null}
          {downloadError ? (
            <Typography.Text type="danger" data-testid="variant-export-download-error">
              {downloadError}
            </Typography.Text>
          ) : null}
          {pollExpired ? (
            <>
              <Typography.Text type="secondary" data-testid="variant-export-poll-expired">
                {t("variants.exportTakingLong")}
              </Typography.Text>
              <Button size="small" onClick={checkAgain} data-testid="variant-export-check-again">
                {t("variants.exportCheckAgain")}
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
