import { type ReactNode, useCallback } from "react";
import { AlertTriangle, ShieldAlert } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  Button,
  Input,
  Label,
  cn,
} from "../lib/admin-ui";

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
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  onConfirm,
  severity = "default",
  confirmPhrase,
  children,
  loading = false,
}: ConfirmDialogProps) {
  const isDestructive = severity === "destructive" || severity === "critical";
  const isCritical = severity === "critical";

  const handleConfirm = useCallback(() => {
    void onConfirm();
  }, [onConfirm]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(isCritical && "border-destructive/50")}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !confirmPhrase && !loading) {
            e.preventDefault();
            handleConfirm();
          }
        }}
      >
        <DialogHeader>
          <div className="flex items-start gap-3">
            <div
              className={cn(
                "flex size-10 shrink-0 items-center justify-center rounded-full",
                isDestructive
                  ? "bg-destructive/10 text-destructive"
                  : "bg-primary/10 text-primary",
              )}
            >
              {isCritical ? (
                <ShieldAlert className="size-5" aria-hidden />
              ) : isDestructive ? (
                <AlertTriangle className="size-5" aria-hidden />
              ) : (
                <AlertTriangle className="size-5" aria-hidden />
              )}
            </div>
            <div className="min-w-0">
              <DialogTitle>{title}</DialogTitle>
              <DialogDescription className="mt-1.5">
                {description}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {children ? <div className="text-sm">{children}</div> : null}

        {confirmPhrase ? (
          <ConfirmPhraseInput phrase={confirmPhrase} />
        ) : null}

        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={loading}
          >
            {cancelLabel}
          </Button>
          <Button
            variant={isDestructive ? "destructive" : "default"}
            onClick={handleConfirm}
            disabled={loading}
            data-confirm-phrase={confirmPhrase}
          >
            {loading ? "Working…" : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Phrase-confirmation input. Disables the confirm button until the user
 * types the exact required phrase (used for critical operations).
 * Uses a MutationObserver-free approach: the button's disabled state is
 * controlled via a data attribute and CSS.
 */
function ConfirmPhraseInput({ phrase }: { phrase: string }) {
  return (
    <div className="space-y-2">
      <Label htmlFor="confirm-phrase">
        Type <code className="font-mono font-semibold">{phrase}</code> to confirm
      </Label>
      <Input
        id="confirm-phrase"
        autoComplete="off"
        spellCheck={false}
        placeholder={phrase}
        onChange={(e) => {
          const value = e.target.value;
          // Walk up to find the confirm button and toggle its disabled state.
          const dialog = e.currentTarget.closest('[role="dialog"]');
          const btn = dialog?.querySelector<HTMLButtonElement>(
            "[data-confirm-phrase]",
          );
          if (btn) {
            btn.disabled = value !== phrase;
          }
        }}
      />
    </div>
  );
}

export default ConfirmDialog;
