/**
 * Search tools — second-level catalog of the /search portal (PPTX V2).
 * Entry cards linking to the standalone tools: seqfetch / enrichment /
 * exppattern (under /tools).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Typography } from "@/lib/antd";
import {
  ExperimentOutlined,
  BarChartOutlined,
  HeatMapOutlined,
  ToolOutlined,
  ArrowRightOutlined,
} from "@ant-design/icons";
import { FadeUp } from "../../components/route-motion";

export const Route = createFileRoute("/search/tools")({
  component: SearchToolsComponent,
});

const TOOLS = [
  {
    to: "/tools/seqfetch",
    icon: ExperimentOutlined,
    titleKey: "search.tools.seqfetch",
    descKey: "search.tools.seqfetchDesc",
  },
  {
    to: "/tools/enrichment",
    icon: BarChartOutlined,
    titleKey: "search.tools.enrichment",
    descKey: "search.tools.enrichmentDesc",
  },
  {
    to: "/tools/exppattern",
    icon: HeatMapOutlined,
    titleKey: "search.tools.exppattern",
    descKey: "search.tools.exppatternDesc",
  },
] as const;

function SearchToolsComponent() {
  const { t } = useTranslation();

  return (
    <FadeUp>
      <div className="py-6">
        <h1 className="eyebrow">{t("search.tools.title")}</h1>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.tools.subtitle")}
        </h2>

        <div className="mt-6 max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <ToolOutlined aria-hidden />
            </div>
            <Typography.Paragraph className="mb-0 leading-relaxed text-muted-foreground">
              {t("search.tools.desc")}
            </Typography.Paragraph>
          </div>

          <div className="mt-6 grid gap-4 md:grid-cols-3">
            {TOOLS.map((tool) => {
              const Icon = tool.icon;
              return (
                <Link
                  key={tool.to}
                  to={tool.to}
                  className="group flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                >
                  <div className="flex size-9 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                    <Icon aria-hidden />
                  </div>
                  <h3 className="mt-3 font-display text-sm font-semibold tracking-tight">
                    {t(tool.titleKey)}
                  </h3>
                  <p className="mt-1.5 flex-1 text-xs leading-relaxed text-muted-foreground">
                    {t(tool.descKey)}
                  </p>
                  <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary">
                    {t("search.tools.open")}
                    <ArrowRightOutlined
                      className="transition-transform group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </FadeUp>
  );
}
