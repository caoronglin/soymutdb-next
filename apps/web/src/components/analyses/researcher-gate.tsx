/**
 * ResearcherGate — route-level permission guard for the analyses module.
 *
 * Analyses endpoints require the researcher role or higher, so non-researcher
 * sessions render a "research access required" empty state instead of hiding
 * the routes (the routes stay crawlable/visible; only the content is gated).
 */

import * as React from "react";
import { useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { SafetyOutlined, LoginOutlined } from "@ant-design/icons";
import { Button, Empty, Spin } from "@/lib/antd";
import { useIsResearcher } from "../../lib/use-current-user";

export function ResearcherGate({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();
  const { isResearcher, isLoading } = useIsResearcher();
  const navigate = useNavigate();

  if (isLoading) {
    return <Spin tip={t("analyses.gate.checking")} className="flex justify-center py-20" />;
  }

  if (!isResearcher) {
    return (
      <Empty
        image={<SafetyOutlined className="text-4xl text-muted-foreground" aria-hidden />}
        description={
          <div>
            <p className="font-medium">{t("analyses.gate.title")}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("analyses.gate.description")}
            </p>
          </div>
        }
      >
        <div className="flex flex-wrap items-center justify-center gap-3">
          <Button size="small" type="primary" icon={<LoginOutlined className="size-4" aria-hidden />} onClick={() => navigate({ to: "/login" })}>
            {t("analyses.gate.signIn")}
          </Button>
          <Button size="small" type="default" onClick={() => navigate({ to: "/" })}>
            {t("analyses.gate.backHome")}
          </Button>
        </div>
      </Empty>
    );
  }

  return <>{children}</>;
}
