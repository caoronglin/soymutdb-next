/**
 * BLAST — compatibility redirect to the full form at /blast.
 *
 * The default/tool entry now points directly at /blast (Phase 4). This
 * /search/blast route is kept as a redirect so existing links keep working
 * instead of breaking.
 */
import * as React from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Spin } from "antd";
import { FadeUp } from "../../components/route-motion";
import { useTranslation } from "react-i18next";

export const Route = createFileRoute("/search/blast")({
  component: SearchBlastRedirect,
});

function SearchBlastRedirect() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  React.useEffect(() => {
    void navigate({ to: "/blast" });
  }, [navigate]);

  return (
    <FadeUp>
      <div className="flex min-h-[40vh] items-center justify-center py-10">
        <Spin tip={t("common.loading")}>
          <div className="h-16" />
        </Spin>
      </div>
    </FadeUp>
  );
}
