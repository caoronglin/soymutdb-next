import * as React from "react";
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
  return (
    <main className="mx-auto flex min-h-screen max-w-xl items-center p-6" role="alert">
      <Result
        status="error"
        icon={<WarningOutlined />}
        title="管理后台暂时无法显示"
        subTitle="页面渲染时发生了意外错误。请重试；若问题持续存在，请联系系统管理员。"
        extra={<Button type="primary" icon={<ReloadOutlined />} onClick={onReset}>重试</Button>}
      />
    </main>
  );
}
