import type { ReactNode } from "react";
import { ReloadOutlined } from "@ant-design/icons";
import { Button, Result } from "@/lib/antd";
import { ErrorBoundary } from "./error-boundary";

interface RouteErrorBoundaryProps {
  children: ReactNode;
}

/**
 * Contains a failed admin route while preserving the surrounding console
 * chrome. Route components are intentionally wrapped at registration time.
 */
export function RouteErrorBoundary({ children }: RouteErrorBoundaryProps) {
  return (
    <ErrorBoundary
      fallback={(_error, reset) => (
        <section className="py-12" role="alert">
          <Result
            status="error"
            title="此页面出错了"
            subTitle="请重试，或返回仪表盘继续其他工作。"
            extra={[
              <Button key="retry" type="primary" icon={<ReloadOutlined />} onClick={reset}>重试</Button>,
              <Button key="home" href="/">返回仪表盘</Button>,
            ]}
          />
        </section>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
