/**
 * Tools hub — entry cards for SeqFetch, Enrichment and ExpPattern.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { Dna, Network, Activity, ArrowRight } from "lucide-react";
import { PageHeader, CardHeader, CardContent, Badge } from "../../lib/web-ui";
import type { LucideIcon } from "lucide-react";

export const Route = createFileRoute("/tools/")({
  component: ToolsIndexComponent,
});

interface ToolCard {
  to: string;
  icon: LucideIcon;
  titleKey: string;
  descKey: string;
  statusKey: string;
}

const TOOLS: ToolCard[] = [
  {
    to: "/tools/seqfetch",
    icon: Dna,
    titleKey: "tools.seqfetch.title",
    descKey: "tools.seqfetch.cardDesc",
    statusKey: "tools.seqfetch.status",
  },
  {
    to: "/tools/enrichment",
    icon: Network,
    titleKey: "tools.enrichment.title",
    descKey: "tools.enrichment.cardDesc",
    statusKey: "tools.enrichment.status",
  },
  {
    to: "/tools/exppattern",
    icon: Activity,
    titleKey: "tools.exppattern.title",
    descKey: "tools.exppattern.cardDesc",
    statusKey: "tools.exppattern.status",
  },
];

function ToolsIndexComponent() {
  const { t } = useTranslation();

  return (
    <div className="container-prose section-rhythm">
      <PageHeader
        icon={Dna}
        title={t("tools.title")}
        description={t("tools.subtitle")}
        breadcrumb={[{ label: t("nav.home"), href: "/" }, { label: t("tools.title") }]}
      />

      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <Link
              key={tool.to}
              to={tool.to}
              className="group flex flex-col rounded-2xl border border-border bg-card p-6 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <CardHeader className="p-0">
                <div className="flex items-center justify-between">
                  <div className="flex size-11 items-center justify-center rounded-xl border border-border bg-muted/40 text-primary">
                    <Icon className="size-5" aria-hidden />
                  </div>
                  <Badge variant="secondary" className="text-[10px] uppercase">
                    {t(tool.statusKey)}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col p-0 pt-5">
                <h2 className="font-display text-lg font-semibold tracking-tight">
                  {t(tool.titleKey)}
                </h2>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">
                  {t(tool.descKey)}
                </p>
                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                  {t("tools.open")}
                  <ArrowRight
                    className="size-4 transition-transform group-hover:translate-x-0.5"
                    aria-hidden
                  />
                </span>
              </CardContent>
            </Link>
          );
        })}
      </div>

      <div className="mt-10 rounded-2xl border border-dashed border-border/80 bg-muted/20 p-6">
        <p className="text-sm leading-relaxed text-muted-foreground">
          {t("tools.note")}{" "}
          <Link to="/blast" className="font-medium text-primary underline-offset-4 hover:underline">
            BLAST
          </Link>
        </p>
      </div>
    </div>
  );
}
