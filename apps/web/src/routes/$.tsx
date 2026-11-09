/**
 * Catch-all route for published PageDefinitions.
 *
 * Static portal routes win over this splat. Reaching it means the path is not
 * a compiled route, so the only pages it may serve are admin-published
 * definitions; anything without one is a real 404. The definition is fetched
 * from the public read contract and rendered through the same safe renderer
 * as the homepage override.
 */
import { createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Button, Result, Skeleton } from "@/lib/antd";
import { PageDefinitionRenderer } from "../components/page-builder/page-definition-renderer";
import { usePublishedPageDefinition } from "../lib/page-definitions";

function PublishedRouteComponent() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const definition = usePublishedPageDefinition(pathname);

  if (definition.isPending) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-10">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  if (definition.data) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-6">
        <PageDefinitionRenderer definition={definition.data} />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-16">
      <Result
        status={definition.isError ? "500" : "404"}
        title={definition.isError
          ? t("errors.pageUnavailable")
          : t("errors.notFound")}
        subTitle={definition.isError
          ? t("errors.pageUnavailableHint")
          : t("errors.notFoundHint")}
        extra={
          <Button type="primary" onClick={() => void Promise.resolve(navigate({ to: "/" }))}>
            {t("nav.home")}
          </Button>
        }
      />
    </div>
  );
}

export const Route = createFileRoute("/$")({
  component: PublishedRouteComponent,
});