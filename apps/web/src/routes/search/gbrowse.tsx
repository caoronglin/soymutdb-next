/**
 * Gbrowse — second-level catalog of the /search portal (PPTX V2 slide 5).
 * A transfer page: pick a genome version, then open the genome browser
 * (/browser?assembly=...) in a new tab.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Button, Card, Form, Select, Tag, Typography } from "antd";
import { GlobalOutlined } from "@ant-design/icons";
import { getAssemblies } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";

export const Route = createFileRoute("/search/gbrowse")({
  component: GbrowseComponent,
});

const DEFAULT_LOCUS = "chr01";

function GbrowseComponent() {
  const { t } = useTranslation();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);

  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];
  const selectedAssembly = assemblies.find((a) => String(a.id) === String(assemblyId));

  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId]);

  const openBrowser = () => {
    if (!selectedAssembly) return;
    const params = new URLSearchParams({
      assembly: selectedAssembly.name,
      locus: DEFAULT_LOCUS,
    });
    window.open(`/browser?${params.toString()}`, "_blank", "noopener");
  };

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.gbrowse.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.gbrowse.subtitle")}
        </h2>

        <Card className="mt-6 max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <GlobalOutlined aria-hidden />
            </div>
            <Typography.Paragraph className="mb-0 leading-relaxed text-muted-foreground">
              {t("search.gbrowse.desc")}
            </Typography.Paragraph>
          </div>

          <Form layout="vertical" className="mt-6 max-w-sm" onFinish={openBrowser}>
            <Form.Item label={t("search.gbrowse.assembly")} className="mb-0">
              <Select
                value={assemblyId}
                onChange={(v) => setAssemblyId(v)}
                placeholder={t("search.genes.assemblyPlaceholder")}
                loading={assembliesQuery.isLoading}
                options={assemblies.map((a) => ({
                  value: String(a.id),
                  label: (
                    <span className="flex items-center gap-2">
                      <span>{a.name}</span>
                      {a.is_default ? (
                        <Tag className="m-0 text-[9px] uppercase">Default</Tag>
                      ) : null}
                    </span>
                  ),
                }))}
              />
            </Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              className="mt-4"
              disabled={!selectedAssembly}
            >
              {t("search.gbrowse.open")}
            </Button>
          </Form>
        </Card>
      </div>
    </FadeUp>
  );
}
