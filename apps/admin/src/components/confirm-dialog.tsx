import { WarningOutlined, SafetyOutlined } from "@ant-design/icons";
import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "../lib/cn";
import { Button, Input, Modal, Typography } from "@/lib/antd";
interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Dialog title. */
  title: string;
  /** Descriptive message explaining the consequence. */
  description: string;
  /** Confirm button label. */
  confirmLabel?: string;
  /** Cancel button label. */
  cancelLabel?: string;
  /** Called when the user confirms. */
  onConfirm: () => void | Promise<void>;
  /** Visual severity of the action. */
  severity?: "default" | "destructive" | "critical";
  /** When provided, the user must type this exact phrase to enable confirm. */
  confirmPhrase?: string;
  /** Additional content rendered above the footer (e.g. details). */
  children?: ReactNode;
  /**
   * Failure reason of the confirmed action.
   *
   * A rejected write has to explain itself somewhere the operator is already
   * looking — the dialog stays open after a failure, so the reason belongs
   * inside it rather than in a transient toast that may be missed.
   */
  error?: ReactNode;
  /** Whether the confirm action is currently loading. */
  loading?: boolean;
}

/**
 * Confirmation dialog for high-risk operations.
 *
 * - `destructive`: red confirm button (e.g. delete, rollback).
 * - `critical`: red + requires typing a confirm phrase (e.g. activate release,
 *   role escalation requiring four-eyes approval).
 *
 * Keyboard accessible: focus is trapped, Escape closes, Enter confirms
 * (when the confirm button is enabled).
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  severity = "default",
  confirmPhrase,
  children,
  error,
  loading = false,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const isDestructive = severity === "destructive" || severity === "critical";
  const isCritical = severity === "critical";
  const confirmLabelText = confirmLabel ?? t("admin.confirm.confirm", { defaultValue: "Confirm" });
  const cancelLabelText = cancelLabel ?? t("admin.confirm.cancel", { defaultValue: "Cancel" });

  const [confirmation, setConfirmation] = useState({ open, phrase: confirmPhrase, value: "" });
  // Reset on reopen or when the required phrase changes, including dialogs
  // that remain mounted after a successful mutation.
  if (confirmation.open !== open || confirmation.phrase !== confirmPhrase) {
    setConfirmation({ open, phrase: confirmPhrase, value: "" });
  }
  const phraseMatches = !confirmPhrase || (
    confirmation.open === open && confirmation.phrase === confirmPhrase && confirmation.value === confirmPhrase
  );
  const handleConfirm = () => {
    if (!loading && phraseMatches) void onConfirm();
  };
  const handleCancel = () => {
    if (!loading) onOpenChange(false);
  };

  return (
    <Modal
      open={open}
      onCancel={handleCancel}
      closable={!loading}
      keyboard={!loading}
      maskClosable={!loading}
      footer={[
        <Button key="cancel" onClick={handleCancel} disabled={loading}>{cancelLabelText}</Button>,
        <Button key="confirm" type="primary" danger={isDestructive} onClick={handleConfirm} disabled={loading || !phraseMatches}>{loading ? t("admin.confirm.working", { defaultValue: "Working…" }) : confirmLabelText}</Button>,
      ]}
      title={<div className="flex items-start gap-3"><span className={cn("flex size-10 items-center justify-center rounded-full", isDestructive ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary")}>{isCritical ? <SafetyOutlined /> : <WarningOutlined />}</span><span><Typography.Title level={4}>{title}</Typography.Title><Typography.Text type="secondary">{description}</Typography.Text></span></div>}
    >
      {error ? (
        <div
          role="alert"
          aria-label={t("admin.confirm.errorLabel", { defaultValue: "Action failed" })}
          className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
        >
          {error}
        </div>
      ) : null}
      {children ? <div className="mb-4 text-sm">{children}</div> : null}
      {confirmPhrase ? <ConfirmPhraseInput phrase={confirmPhrase} value={confirmation.value} disabled={loading} onChange={(value) => setConfirmation({ open, phrase: confirmPhrase, value })} /> : null}
    </Modal>
  );
}

/**
 * Phrase-confirmation input. Disables the confirm button until the user
 * types the exact required phrase (used for critical operations).
 * React owns the phrase and disabled state; direct DOM changes cannot bypass
 * the pending-action safeguard.
 */
function ConfirmPhraseInput({ phrase, value, disabled, onChange }: { phrase: string; value: string; disabled: boolean; onChange: (value: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      <Typography.Text>
        {t("admin.confirm.typePhrasePrefix", { defaultValue: "Type" })}{" "}
        <code className="font-mono font-semibold">{phrase}</code>{" "}
        {t("admin.confirm.typePhraseSuffix", { defaultValue: "to confirm" })}
      </Typography.Text>
      <Input
        id="confirm-phrase"
        autoComplete="off"
        spellCheck={false}
        placeholder={phrase}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
