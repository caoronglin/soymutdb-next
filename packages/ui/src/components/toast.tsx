import * as React from "react";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "../lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type ToastVariant = "success" | "error" | "info";

export type ToastPosition = "bottom-right" | "bottom-left" | "top-right" | "top-left";

export interface ToastOptions {
  /** Toast title. */
  title: string;
  /** Optional supporting detail. */
  description?: string;
  /** Visual variant (default "info"). */
  variant?: ToastVariant;
  /** Auto-dismiss delay in ms. `null` keeps the toast until dismissed (default from provider, 4000). */
  duration?: number | null;
}

export interface ToastItem extends Omit<ToastOptions, "variant" | "duration"> {
  /** Stable id returned by `toast()`. */
  id: string;
  variant: ToastVariant;
  duration: number | null;
}

export interface ToastContextValue {
  /** Show a toast and return its id. */
  toast: (options: ToastOptions) => string;
  /** Show a success toast. */
  success: (title: string, description?: string, duration?: number | null) => string;
  /** Show an error toast. */
  error: (title: string, description?: string, duration?: number | null) => string;
  /** Show an info toast. */
  info: (title: string, description?: string, duration?: number | null) => string;
  /** Dismiss a toast by id. */
  dismiss: (id: string) => void;
  /** Dismiss all visible toasts. */
  dismissAll: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ToastContext = React.createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = React.useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a <ToastProvider>.");
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// Presentation
// ---------------------------------------------------------------------------

const ICONS: Record<ToastVariant, LucideIcon> = {
  success: CircleCheck,
  error: CircleAlert,
  info: Info,
};

const ICON_CLASSES: Record<ToastVariant, string> = {
  success: "text-primary",
  error: "text-destructive",
  info: "text-muted-foreground",
};

const POSITION_CLASSES: Record<ToastPosition, string> = {
  "bottom-right": "bottom-4 right-4 sm:bottom-5 sm:right-5",
  "bottom-left": "bottom-4 left-4 sm:bottom-5 sm:left-5",
  "top-right": "top-4 right-4 sm:top-5 sm:right-5",
  "top-left": "top-4 left-4 sm:top-5 sm:left-5",
};

export interface ToastProviderProps {
  children: React.ReactNode;
  /** Default auto-dismiss delay in ms (default 4000). */
  duration?: number;
  /** Where the toast stack is anchored (default "bottom-right"). */
  position?: ToastPosition;
  /** Maximum simultaneously visible toasts — oldest are dropped first (default 5). */
  limit?: number;
  /** Accessible label for the notifications region. */
  label?: string;
  className?: string;
}

/**
 * Toast notification system: provider + `useToast()` hook. No external
 * dependencies. Auto-dismisses (per-toast `duration`), closable, and
 * announced politely to screen readers.
 */
export function ToastProvider({
  children,
  duration = 4000,
  position = "bottom-right",
  limit = 5,
  label = "Notifications",
  className,
}: ToastProviderProps) {
  const [toasts, setToasts] = React.useState<ToastItem[]>([]);
  const idRef = React.useRef(0);
  const timersRef = React.useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = React.useCallback((id: string) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const dismissAll = React.useCallback(() => {
    timersRef.current.forEach((timer) => clearTimeout(timer));
    timersRef.current.clear();
    setToasts([]);
  }, []);

  const push = React.useCallback(
    (options: ToastOptions): string => {
      const id = `toast-${++idRef.current}`;
      const item: ToastItem = {
        id,
        title: options.title,
        description: options.description,
        variant: options.variant ?? "info",
        duration: options.duration !== undefined ? options.duration : duration,
      };
      setToasts((prev) => [...prev.slice(-(limit - 1)), item]);
      if (item.duration !== null && item.duration > 0) {
        const timer = setTimeout(() => dismiss(id), item.duration);
        timersRef.current.set(id, timer);
      }
      return id;
    },
    [duration, limit, dismiss],
  );

  React.useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer));
      timersRef.current.clear();
    };
  }, []);

  const value = React.useMemo<ToastContextValue>(
    () => ({
      toast: push,
      success: (title, description, dur) =>
        push({ title, description, variant: "success", duration: dur }),
      error: (title, description, dur) =>
        push({ title, description, variant: "error", duration: dur }),
      info: (title, description, dur) =>
        push({ title, description, variant: "info", duration: dur }),
      dismiss,
      dismissAll,
    }),
    [push, dismiss, dismissAll],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-label={label}
        className={cn(
          "pointer-events-none fixed z-[100] flex w-full max-w-sm flex-col gap-2 p-4 sm:w-auto sm:min-w-80",
          POSITION_CLASSES[position],
          className,
        )}
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.variant];
          return (
            <div
              key={t.id}
              role={t.variant === "error" ? "alert" : "status"}
              aria-atomic="true"
              className="rl-toast-enter pointer-events-auto flex w-full items-start gap-3 rounded-xl border border-border bg-card p-3.5 shadow-lg"
            >
              <Icon className={cn("mt-0.5 size-5 shrink-0", ICON_CLASSES[t.variant])} aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{t.title}</p>
                {t.description ? (
                  <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                    {t.description}
                  </p>
                ) : null}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss notification"
                className="shrink-0 rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              >
                <X className="size-4" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
