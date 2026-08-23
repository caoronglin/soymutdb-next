import * as React from "react";
import { App } from "./antd";

type ToastVariant = "success" | "error" | "info";

export interface ToastOptions {
  title: React.ReactNode;
  description?: React.ReactNode;
  variant?: ToastVariant;
  duration?: number | null;
}

export interface ToastContextValue {
  toast: (options: ToastOptions) => string;
  success: (title: React.ReactNode, description?: React.ReactNode, duration?: number | null) => string;
  error: (title: React.ReactNode, description?: React.ReactNode, duration?: number | null) => string;
  info: (title: React.ReactNode, description?: React.ReactNode, duration?: number | null) => string;
  dismiss: (id: string) => void;
  dismissAll: () => void;
}

/**
 * Ant Design-backed toast hook. Relies on the root `<App>` provider (wired in
 * DesignSystemProvider), so it needs no separate ToastProvider. The returned
 * shape matches the previous `web-ui` `useToast` so call sites are unchanged.
 */
export function useToast(): ToastContextValue {
  const { message } = App.useApp();
  const nextId = React.useRef(0);

  const push = React.useCallback(
    (options: ToastOptions) => {
      const id = `web-toast-${++nextId.current}`;
      const duration = options.duration === undefined ? 4 : options.duration;
      void message.open({
        key: id,
        type: options.variant ?? "info",
        duration: duration === null ? 0 : duration,
        content: (
          <div className="text-left">
            <div className="font-medium">{options.title}</div>
            {options.description ? <div className="text-xs opacity-75">{options.description}</div> : null}
          </div>
        ),
      });
      return id;
    },
    [message],
  );

  return React.useMemo<ToastContextValue>(
    () => ({
      toast: push,
      success: (title, description, duration) => push({ title, description, variant: "success", duration }),
      error: (title, description, duration) => push({ title, description, variant: "error", duration }),
      info: (title, description, duration) => push({ title, description, variant: "info", duration }),
      dismiss: (id) => message.destroy(id),
      dismissAll: () => message.destroy(),
    }),
    [message, push],
  );
}
