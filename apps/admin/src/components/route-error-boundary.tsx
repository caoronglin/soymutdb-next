import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
  return (
    <ErrorBoundary
      fallback={(_error, reset) => (
        <section className="py-12" role="alert">
          <Result
            status="error"
            title={t("errorBoundary.title", { defaultValue: "Something went wrong" })}
            subTitle={t("errorBoundary.description", { defaultValue: "An unexpected error occurred while rendering this section." })}
            extra={[
              <Button key="retry" type="primary" icon={<ReloadOutlined />} onClick={reset}>
                {t("errorBoundary.retry", { defaultValue: "Retry" })}
              </Button>,
              <Button key="home" href="/">
                {t("errorBoundary.backToDashboard", { defaultValue: "Back to dashboard" })}
              </Button>,
            ]}
          />
        </section>
      )}
    >
      {children}
    </ErrorBoundary>
  );
}
