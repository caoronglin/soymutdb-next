import { Button, Result } from "@/lib/antd";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

const RETIRED_PATHS = new Set([
  "/widgets",
  "/layout",
  "/widget-preview",
  "/widget-health",
  "/page-builder",
]);

export default function LegacyUnavailablePage() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const navigate = useNavigate();
  const { t } = useTranslation();
  const resourceCatalog = pathname === "/resource-catalog";
  const retired = [...RETIRED_PATHS].some((path) => pathname === path || pathname.startsWith(`${path}/`));

  return (
    <div className="container-prose py-8">
      <Result
        status={resourceCatalog ? "warning" : "info"}
        title={resourceCatalog
          ? t("admin.legacyUnavailable.resourceCatalogTitle", { defaultValue: "Resource catalog unavailable" })
          : t("admin.legacyUnavailable.retiredTitle", { defaultValue: "This legacy page is unavailable" })}
        subTitle={resourceCatalog
          ? t("admin.legacyUnavailable.resourceCatalogReason", { defaultValue: "There is no backing API for the former static link catalog, so no catalog data is fabricated." })
          : retired
            ? t("admin.legacyUnavailable.retiredReason", { defaultValue: "The page-builder and widget workflow was retired. This route is kept only to explain the change; it does not perform writes." })
            : t("admin.legacyUnavailable.notImplemented", { defaultValue: "This route has not been restored." })}
        extra={[
          <Button key="home" onClick={() => void navigate({ to: "/" })}>
            {t("admin.legacyUnavailable.dashboard", { defaultValue: "Return to dashboard" })}
          </Button>,
          ...(resourceCatalog
            ? [
                <Button key="imports" type="primary" onClick={() => void navigate({ to: "/imports" })}>
                  {t("admin.legacyUnavailable.importsReference", { defaultValue: "Open imports" })}
                </Button>,
              ]
            : []),
        ]}
      />
    </div>
  );
}
