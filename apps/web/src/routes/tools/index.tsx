/**
 * Tools hub — entry cards for SeqFetch, Enrichment, ExpPattern and the three
 * population-genetics tools (linkage disequilibrium, nucleotide diversity,
 * allele frequency).
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  ArrowRightOutlined,
  DeploymentUnitOutlined,
  LineChartOutlined,
  NodeIndexOutlined,
  PartitionOutlined,
  PieChartOutlined,
  RiseOutlined,
} from "@ant-design/icons";
import { Breadcrumb, Tag, Typography } from "@/lib/antd";
import * as React from "react";

type IconComponent = React.ComponentType<{ className?: string; style?: React.CSSProperties }>;

export const Route = createFileRoute("/tools/")({
  component: ToolsIndexComponent,
});

interface ToolCard {
  to: string;
  icon: IconComponent;
  titleKey: string;
  descKey: string;
  statusKey: string;
}

const TOOLS: ToolCard[] = [
  {
    to: "/tools/seqfetch",
    icon: DeploymentUnitOutlined,
    titleKey: "tools.seqfetch.title",
    descKey: "tools.seqfetch.cardDesc",
    statusKey: "tools.seqfetch.status",
  },
  {
    to: "/tools/enrichment",
    icon: NodeIndexOutlined,
    titleKey: "tools.enrichment.title",
    descKey: "tools.enrichment.cardDesc",
    statusKey: "tools.enrichment.status",
  },
  {
    to: "/tools/exppattern",
    icon: RiseOutlined,
    titleKey: "tools.exppattern.title",
    descKey: "tools.exppattern.cardDesc",
    statusKey: "tools.exppattern.status",
  },
  {
    to: "/tools/ld",
    icon: PartitionOutlined,
    titleKey: "tools.popgen.ld.title",
    descKey: "tools.popgen.ld.subtitle",
    statusKey: "tools.popgen.title",
  },
  {
    to: "/tools/diversity",
    icon: LineChartOutlined,
    titleKey: "tools.popgen.diversity.title",
    descKey: "tools.popgen.diversity.subtitle",
    statusKey: "tools.popgen.title",
  },
  {
    to: "/tools/allelefreq",
    icon: PieChartOutlined,
    titleKey: "tools.popgen.allelefreq.title",
    descKey: "tools.popgen.allelefreq.subtitle",
    statusKey: "tools.popgen.title",
  },
];

function ToolsIndexComponent() {
  const { t } = useTranslation();

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb items={[{ title: <Link to="/">{t("nav.home")}</Link> }, { title: t("tools.title") }]} />
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3.5">
            <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">
              <DeploymentUnitOutlined className="size-5" aria-hidden />
            </span>
            <div>
              <Typography.Title level={2} style={{ margin: 0 }}>{t("tools.title")}</Typography.Title>
              <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
                {t("tools.subtitle")}
              </Typography.Paragraph>
            </div>
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {TOOLS.map((tool) => {
          const Icon = tool.icon;
          return (
            <Link
              key={tool.to}
              to={tool.to}
              className="group flex flex-col rounded-2xl border border-border bg-card p-6 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <div className="flex items-center justify-between">
                <div className="flex size-11 items-center justify-center rounded-xl border border-border bg-muted/40 text-primary">
                  <Icon className="size-5" aria-hidden />
                </div>
                <Tag className="text-[10px] uppercase">{t(tool.statusKey)}</Tag>
              </div>
              <div className="flex flex-1 flex-col pt-5">
                <h2 className="font-display text-lg font-semibold tracking-tight">{t(tool.titleKey)}</h2>
                <p className="mt-2 flex-1 text-sm leading-relaxed text-muted-foreground">{t(tool.descKey)}</p>
                <span className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-primary">
                  {t("tools.open")}
                  <ArrowRightOutlined className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                </span>
              </div>
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
