import * as React from "react";
import { useTranslation } from "react-i18next";
import { ReloadOutlined, WarningOutlined } from "@ant-design/icons";
import { Button, Result } from "@/lib/antd";

export interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: (error: Error, reset: () => void) => React.ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Last-resort rendering guard for the Admin console. It keeps an unexpected
 * render failure recoverable instead of leaving administrators on a blank page.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): React.ReactNode {
    const { error } = this.state;
    if (error) {
      return this.props.fallback?.(error, this.reset) ?? <DefaultFallback onReset={this.reset} />;
    }
    return this.props.children;
  }
}

function DefaultFallback({ onReset }: { onReset: () => void }) {
  const { t } = useTranslation();
  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center p-6" role="alert">
      <Result
        status="error"
        icon={<WarningOutlined />}
        title={t("errorBoundary.title", { defaultValue: "Something went wrong" })}
        subTitle={t("errorBoundary.description", { defaultValue: "An unexpected error occurred while rendering this section." })}
        extra={
          <Button type="primary" icon={<ReloadOutlined />} onClick={onReset}>
            {t("errorBoundary.retry", { defaultValue: "Retry" })}
          </Button>
        }
      />
    </main>
  );
}
