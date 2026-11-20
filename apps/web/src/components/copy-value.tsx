/**
 * One copy affordance for the whole portal.
 *
 * Three call sites had grown their own version (a `Button` with no failure
 * branch, a bare `<button>`, and a third inside the primer panel), so the
 * behaviour a reader got depended on which page they were on. This component is
 * the single implementation:
 *
 * - the clipboard may be missing (insecure origin) or refuse (permission); that
 *   is reported once and the value stays selectable as text rather than the
 *   button looking like it worked;
 * - the confirmation clears itself, and the timer is cancelled on unmount so a
 *   fast navigation does not set state on a gone component;
 * - the announcement is an `aria-live` region: a screen reader hears "copied"
 *   without the focus moving.
 *
 * It is a *button*, never a click-to-copy wrapper around other content: a
 * copyable region that swallows clicks would break text selection, which is
 * what a reader reaches for when the clipboard is denied.
 */
import * as React from "react";
import { Button, Tooltip } from "@/lib/antd";
import { CheckOutlined, CopyOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";

export interface CopyValueProps {
  /** The exact text placed on the clipboard. */
  value: string;
  /** Accessible name; defaults to the generic "copy" label. */
  label?: string;
  /** `icon` is the table/row affordance, `text` the wider action button. */
  variant?: "icon" | "text";
  size?: "small" | "middle";
  className?: string;
  testId?: string;
}

/** How long the confirmation stays visible. */
const CONFIRM_MS = 1400;

export function CopyValue({
  value,
  label,
  variant = "icon",
  size = "small",
  className,
  testId,
}: CopyValueProps) {
  const { t } = useTranslation();
  const [state, setState] = React.useState<"idle" | "copied" | "failed">("idle");
  const timer = React.useRef<number | null>(null);

  React.useEffect(
    () => () => {
      // Clearing on unmount keeps the timeout from touching a dead component.
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const settle = (next: "copied" | "failed") => {
    setState(next);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState("idle"), CONFIRM_MS);
  };

  const copy = async () => {
    if (!value) return;
    if (!navigator.clipboard) {
      settle("failed");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      settle("copied");
    } catch {
      // Denied permission or a non-secure context: say so, and leave the text
      // selectable so the reader can still get it.
      settle("failed");
    }
  };

  // The accessible name carries the value: a table can hold several copy
  // buttons, and "Copy" alone leaves a screen-reader user unable to tell which
  // identifier each one writes.
  const action = label ?? `${t("common.copy")} ${value}`;
  const accessibleLabel =
    state === "copied"
      ? `${t("common.copied")} ${value}`
      : state === "failed"
        ? `${t("common.copyFailed")} ${value}`
        : action;

  return (
    <>
      <Tooltip title={state === "idle" ? accessibleLabel : undefined}>
        <Button
          type="text"
          size={size}
          className={className}
          onClick={() => void copy()}
          aria-label={accessibleLabel}
          data-testid={testId}
          data-copy-state={state}
          icon={
            state === "copied" ? (
              <CheckOutlined aria-hidden />
            ) : (
              <CopyOutlined aria-hidden />
            )
          }
        >
          {variant === "text" ? accessibleLabel : null}
        </Button>
      </Tooltip>
      {/* Announced, not merely drawn: a colour change alone is silent. */}
      <span role="status" aria-live="polite" className="sr-only">
        {state === "idle" ? "" : accessibleLabel}
      </span>
    </>
  );
}
