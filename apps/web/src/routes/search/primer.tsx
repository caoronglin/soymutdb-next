/**
 * Primer design — second-level catalog of the /search portal (PPTX V2).
 * The Primer3 backend is not implemented yet: this is a placeholder page
 * aligned to the PPTX layout (genome version + target region + hint), with
 * no backend call on submit.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Alert, Button, Card, Form, Input, Select, Tag, Typography } from "antd";
import { ToolOutlined } from "@ant-design/icons";
import { getAssemblies } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";

export const Route = createFileRoute("/search/primer")({
  component: PrimerComponent,
});

function PrimerComponent() {
  const { t } = useTranslation();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(undefined);

  // Only the shared assemblies lookup (read-only display, PPTX layout) —
  // no primer backend is called.
  const assembliesQuery = useQuery({
    queryKey: ["assemblies"],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];

  React.useEffect(() => {
    if (assemblyId || assemblies.length === 0) return;
    const def = assemblies.find((a) => a.is_default) ?? assemblies[0];
    if (def) setAssemblyId(String(def.id));
  }, [assemblies, assemblyId]);

  return (
    <FadeUp>
      <div className="py-6">
        <p className="eyebrow">{t("search.primer.title")}</p>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {t("search.primer.subtitle")}
        </h2>

        <Alert
          className="mt-6 max-w-3xl"
          type="info"
          showIcon
          message={t("search.primer.comingSoon")}
          description={
            <span>
              {t("search.primer.desc")}{" "}
              <Link
                to="/search/blast"
                search={{
                  q: undefined,
                  tissue: undefined,
                  treatment: undefined,
                  min_fpkm: undefined,
                }}
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                BLAST
              </Link>
            </span>
          }
        />

        <Card className="mt-6 max-w-3xl">
          <div className="flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent text-accent-foreground">
              <ToolOutlined aria-hidden />
            </div>
            <Typography.Paragraph className="mb-0 text-muted-foreground">
              {t("search.primer.subtitle")}
            </Typography.Paragraph>
          </div>

          <Form layout="vertical" className="mt-6">
            <div className="grid gap-4 sm:grid-cols-[240px_1fr]">
              <Form.Item label={t("search.primer.assembly")} className="mb-0">
                <Select
                  value={assemblyId}
                  onChange={(v) => setAssemblyId(v)}
                  placeholder={t("search.genes.assemblyPlaceholder")}
                  loading={assembliesQuery.isLoading}
                  disabled
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
              <Form.Item label={t("search.primer.region")} className="mb-0">
                <Input
                  disabled
                  placeholder={t("search.primer.regionPlaceholder")}
                  className="font-mono text-sm"
                />
              </Form.Item>
            </div>
            <Button type="primary" className="mt-4" disabled>
              {t("search.primer.submit")}
            </Button>
          </Form>
        </Card>
      </div>
    </FadeUp>
  );
}
