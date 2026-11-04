/**
 * Allele-frequency tool (`/tools/allelefreq`).
 *
 * POST /api/v1/tools/allelefreq returns one row per variant in a gene or
 * interval, with the allele frequency the released `variant_facts` store
 * carries. A `null` frequency is not zero: the variant is recorded but its
 * frequency was never populated, and the cell says so in words.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Breadcrumb, Button, Card, Empty, Result, Tag, Tooltip, Typography } from "@/lib/antd";
import { CaretRightOutlined, LoadingOutlined, RedoOutlined, PieChartOutlined } from "@ant-design/icons";
import { computeAlleleFreq, type AlleleFreqVariant } from "@soymutdb/api-client";
import { DataTable } from "../../components/data-table";
import { formatNumber, formatPosition } from "../../lib/format";
import {
  buildRegionQuery,
  EMPTY_REGION,
  formatRegion,
  RegionForm,
  type RegionErrors,
  type RegionFormState,
} from "./-popgen-form";

export const Route = createFileRoute("/tools/allelefreq")({
  component: AlleleFreqComponent,
});

/** A frequency renders to three decimals; `null` renders as a word, not a 0. */
export function formatFrequency(
  value: number | null,
  missingLabel: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return missingLabel;
  return value.toFixed(3);
}

function AlleleFreqComponent() {
  const { t } = useTranslation();
  const [region, setRegion] = React.useState<RegionFormState>(EMPTY_REGION);
  const [errors, setErrors] = React.useState<RegionErrors>({});

  const mutation = useMutation({
    mutationFn: async () => {
      const { query, errors: nextErrors } = buildRegionQuery(region, t);
      setErrors(nextErrors);
      if (!query) return null;
      return computeAlleleFreq({ ...query, max_variants: 2000 });
    },
  });

  const result = mutation.data ?? null;
  const missing = t("tools.popgen.notRecorded");

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.popgen.allelefreq.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">
            <PieChartOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={1} style={{ margin: 0 }}>
              {t("tools.popgen.allelefreq.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.popgen.allelefreq.subtitle")}
            </Typography.Paragraph>
          </div>
        </div>
      </header>

      <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <div className="mb-5">
            <Typography.Title level={5} style={{ margin: 0 }}>
              {t("tools.popgen.formTitle")}
            </Typography.Title>
            <Typography.Text type="secondary">{t("tools.popgen.allelefreq.formDesc")}</Typography.Text>
          </div>
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <RegionForm idPrefix="af" value={region} onChange={setRegion} errors={errors} />
            <div className="flex flex-wrap gap-2">
              <Button type="primary" htmlType="submit" disabled={mutation.isPending}>
                {mutation.isPending ? (
                  <LoadingOutlined className="size-4 animate-spin" aria-hidden />
                ) : (
                  <CaretRightOutlined className="size-4" aria-hidden />
                )}
                {t("tools.popgen.submit")}
              </Button>
              <Button
                htmlType="button"
                onClick={() => {
                  setRegion(EMPTY_REGION);
                  setErrors({});
                  mutation.reset();
                }}
              >
                <RedoOutlined className="size-4" aria-hidden />
                {t("common.clear")}
              </Button>
            </div>
          </form>
        </Card>

        <div className="grid gap-6">
          {mutation.isError ? (
            <Result
              status="error"
              title={t("tools.popgen.errorTitle")}
              subTitle={(mutation.error as Error).message}
              extra={
                <Button type="primary" onClick={() => mutation.mutate()}>
                  {t("common.retry")}
                </Button>
              }
            />
          ) : null}

          {!result && !mutation.isError ? (
            <Card>
              <Empty
                description={
                  <>
                    <p className="font-medium">{t("tools.popgen.emptyTitle")}</p>
                    <p className="text-sm text-muted-foreground">
                      {t("tools.popgen.allelefreq.emptyDesc")}
                    </p>
                  </>
                }
              />
            </Card>
          ) : null}

          {result ? (
            <Card>
              <div className="mb-4">
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {t("tools.popgen.summaryTitle")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {formatRegion(result)}
                </Typography.Text>
              </div>
              <div className="flex flex-wrap gap-2">
                <Tag>{t("tools.popgen.variantCount", { count: formatNumber(result.n_variants) })}</Tag>
                <Tag>{result.source === "gene" ? t("tools.popgen.sourceGene") : t("tools.popgen.sourceInterval")}</Tag>
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10" aria-label={t("tools.popgen.allelefreq.resultsTitle")}>
          {result.variants.length === 0 ? (
            <Empty
              description={
                <>
                  <p className="font-medium">{t("tools.popgen.allelefreq.noRowsTitle")}</p>
                  <p className="text-sm text-muted-foreground">
                    {t("tools.popgen.allelefreq.noRowsDesc")}
                  </p>
                </>
              }
            />
          ) : (
            <Card>
              <div className="mb-4">
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {t("tools.popgen.allelefreq.resultsTitle")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("tools.popgen.allelefreq.resultsDesc")}
                </Typography.Text>
              </div>
              <DataTable<AlleleFreqVariant>
                ariaLabel={t("tools.popgen.allelefreq.resultsTitle")}
                rowKey={(row) => row.variant_id}
                data={result.variants}
                columns={[
                  {
                    key: "variant_id",
                    header: (
                      <Tooltip title={t("tools.popgen.columns.variantScopeHelp")}>
                        <span>
                          {t("tools.popgen.columns.variant")}{" "}
                          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                            ({t("tools.popgen.columns.variantScope")})
                          </Typography.Text>
                        </span>
                      </Tooltip>
                    ),
                    cell: (row) => <span className="font-mono text-xs">{row.variant_id}</span>,
                  },
                  {
                    key: "position",
                    header: t("tools.popgen.columns.position"),
                    numeric: true,
                    cell: (row) => (
                      <span className="font-mono text-xs">
                        {row.chromosome}:{formatPosition(row.position)}
                      </span>
                    ),
                  },
                  {
                    key: "alleles",
                    header: t("tools.popgen.columns.alleles"),
                    cell: (row) => (
                      <span className="font-mono text-xs">
                        {row.ref_allele} → {row.alt_allele}
                      </span>
                    ),
                  },
                  {
                    key: "type",
                    header: t("tools.popgen.columns.type"),
                    cell: (row) => <Tag>{row.variant_type}</Tag>,
                  },
                  {
                    key: "allele_frequency",
                    header: t("tools.popgen.columns.alleleFrequency"),
                    numeric: true,
                    cell: (row) =>
                      row.allele_frequency === null ? (
                        // Not recorded is a different claim from "frequency 0".
                        <span className="text-muted-foreground">{missing}</span>
                      ) : (
                        <span className="font-mono tabular-nums">
                          {formatFrequency(row.allele_frequency, missing)}
                        </span>
                      ),
                  },
                ]}
              />
            </Card>
          )}
        </section>
      ) : null}
    </div>
  );
}
