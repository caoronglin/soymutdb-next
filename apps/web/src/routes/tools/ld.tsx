/**
 * Linkage-disequilibrium tool (`/tools/ld`).
 *
 * POST /api/v1/tools/ld returns the variant coordinates in a region plus an
 * optional r² matrix. The matrix is only computable when per-sample genotypes
 * are supplied inline: the released `variant_facts` store carries per-variant
 * allele frequencies but no genotype calls, so without them the server answers
 * `r_squared: null` and a `note`.
 *
 * That `null` is the point of this page. It is rendered as "not computable from
 * this store", with the reason — never as a 0, a blank matrix, or an empty
 * chart, all of which would assert independence between variants. When the
 * caller does paste a genotype matrix, the real r² values are drawn.
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Empty,
  Input,
  Result,
  Tag,
  Tooltip,
  Typography,
} from "@/lib/antd";
import { CaretRightOutlined, LoadingOutlined, PartitionOutlined, RedoOutlined } from "@ant-design/icons";
import type { GenotypeMatrix } from "@soymutdb/api-client";
import { ChartFigure } from "@soymutdb/charts";
import { DataTable } from "../../components/data-table";
import { formatNumber, formatPosition } from "../../lib/format";
import { computeLd } from "@soymutdb/api-client";
import { buildLdHeatmapChart, ldChartState, toLdCells, type LdCell } from "./-popgen-charts";
import {
  buildRegionQuery,
  EMPTY_REGION,
  formatRegion,
  RegionForm,
  variantRowKey,
  type RegionErrors,
  type RegionFormState,
} from "./-popgen-form";

export const Route = createFileRoute("/tools/ld")({
  component: LdComponent,
});

interface GenotypeParse {
  matrix: GenotypeMatrix | null;
  error: "empty" | "shape" | "value" | "labels" | null;
}

/**
 * Parse a pasted genotype block.
 *
 * Format: a header row `sample<TAB>v1<TAB>v2…`, then one row per sample with a
 * dosage (0/1/2) per variant. Missing calls are rejected here as well as in the
 * service: a matrix with holes cannot produce a correlation, and the server's
 * refusal would arrive as a generic 422.
 */
export function parseGenotypes(raw: string): GenotypeParse {
  const lines = raw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) return { matrix: null, error: null };

  const header = lines[0].split(/[\s,]+/).filter(Boolean);
  if (header.length < 3) return { matrix: null, error: "shape" };
  const variantIds = header.slice(1);
  const sampleIds: string[] = [];
  const values: number[][] = [];

  for (const line of lines.slice(1)) {
    const cells = line.split(/[\s,]+/).filter(Boolean);
    if (cells.length !== header.length) return { matrix: null, error: "shape" };
    const [sample, ...dosages] = cells;
    const parsed = dosages.map((cell) => Number(cell));
    for (const dosage of parsed) {
      if (!Number.isInteger(dosage) || dosage < 0 || dosage > 2) {
        return { matrix: null, error: "value" };
      }
    }
    sampleIds.push(sample);
    values.push(parsed);
  }

  if (sampleIds.length < 2) return { matrix: null, error: "labels" };

  return { matrix: { sample_ids: sampleIds, variant_ids: variantIds, values }, error: null };
}

function LdComponent() {
  const { t } = useTranslation();
  const [region, setRegion] = React.useState<RegionFormState>(EMPTY_REGION);
  const [errors, setErrors] = React.useState<RegionErrors>({});
  const [genotypeRaw, setGenotypeRaw] = React.useState("");
  const [genotypeError, setGenotypeError] = React.useState<GenotypeParse["error"]>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const { query, errors: nextErrors } = buildRegionQuery(region, t);
      setErrors(nextErrors);
      const parsed = parseGenotypes(genotypeRaw);
      setGenotypeError(parsed.error);
      if (parsed.error) throw new Error(t(`tools.popgen.ld.genotypeError.${parsed.error}`));
      if (!query) return null;
      return computeLd({ ...query, ...(parsed.matrix ? { genotypes: parsed.matrix } : {}) });
    },
  });

  const result = mutation.data ?? null;
  const state = result ? ldChartState(result) : null;
  const cells = React.useMemo<LdCell[]>(() => (result ? toLdCells(result) : []), [result]);

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.popgen.ld.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">
            <PartitionOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={1} style={{ margin: 0 }}>
              {t("tools.popgen.ld.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.popgen.ld.subtitle")}
            </Typography.Paragraph>
          </div>
        </div>
      </header>

      {/* The r² limitation is a property of the data store, so it is stated
          before the form: a reader must not expect a matrix this tool cannot
          compute from the database alone. */}
      <Alert
        className="mt-6"
        type="info"
        showIcon
        data-testid="ld-genotype-notice"
        title={t("tools.popgen.ld.boundaryTitle")}
        description={t("tools.popgen.ld.boundaryBody")}
      />

      <div className="mt-10 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Card>
          <div className="mb-5">
            <Typography.Title level={5} style={{ margin: 0 }}>
              {t("tools.popgen.formTitle")}
            </Typography.Title>
            <Typography.Text type="secondary">{t("tools.popgen.ld.formDesc")}</Typography.Text>
          </div>
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <RegionForm idPrefix="ld" value={region} onChange={setRegion} errors={errors} />

            <div className="grid gap-2">
              <label htmlFor="ld-genotypes" className="text-sm font-medium">
                {t("tools.popgen.ld.genotypesLabel")}
              </label>
              <Input.TextArea
                id="ld-genotypes"
                value={genotypeRaw}
                onChange={(event) => {
                  setGenotypeRaw(event.target.value);
                  setGenotypeError(null);
                }}
                placeholder={t("tools.popgen.ld.genotypesPlaceholder")}
                className="min-h-[120px] font-mono text-sm"
                aria-invalid={Boolean(genotypeError)}
              />
              <p className="text-xs text-muted-foreground">
                {t("tools.popgen.ld.genotypesHelp")}
              </p>
              {genotypeError ? (
                <p className="text-xs text-destructive" data-testid="ld-genotype-error">
                  {t(`tools.popgen.ld.genotypeError.${genotypeError}`)}
                </p>
              ) : null}
            </div>

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
                  setGenotypeRaw("");
                  setGenotypeError(null);
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
                    <p className="text-sm text-muted-foreground">{t("tools.popgen.ld.emptyDesc")}</p>
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
                <Typography.Text type="secondary">{formatRegion(result)}</Typography.Text>
              </div>
              <div className="flex flex-wrap gap-2">
                <Tag>{t("tools.popgen.variantCount", { count: formatNumber(result.n_variants) })}</Tag>
                <Tag
                  color={state === "matrix" ? "green" : "default"}
                  data-testid="ld-r2-state"
                >
                  {state === "matrix"
                    ? t("tools.popgen.ld.stateComputed")
                    : t("tools.popgen.ld.stateNotComputable")}
                </Tag>
              </div>
              {state === "no-genotypes" ? (
                <p
                  className="mt-3 rounded-lg border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
                  data-testid="ld-r2-null-explanation"
                >
                  {t("tools.popgen.ld.r2NullExplanation")}
                  {result.note ? ` ${result.note}` : ""}
                </p>
              ) : null}
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6" aria-label={t("tools.popgen.ld.resultsTitle")}>
          {state === "no-variants" ? (
            <Empty
              description={
                <>
                  <p className="font-medium">{t("tools.popgen.ld.noVariantsTitle")}</p>
                  <p className="text-sm text-muted-foreground">
                    {t("tools.popgen.ld.noVariantsDesc")}
                  </p>
                </>
              }
            />
          ) : null}

          {state === "no-genotypes" ? (
            // Deliberately not a chart: an empty matrix drawn as a figure reads
            // as "LD is zero everywhere", which is the opposite of "unknown".
            <Alert
              type="warning"
              showIcon
              data-testid="ld-no-genotypes-panel"
              title={t("tools.popgen.ld.noGenotypesTitle")}
              description={t("tools.popgen.ld.noGenotypesDesc", { count: formatNumber(result.n_variants) })}
            />
          ) : null}

          {state === "matrix" ? (
            <Card>
              <div className="mb-4">
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {t("tools.popgen.ld.heatmapTitle")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("tools.popgen.ld.heatmapDesc")}
                </Typography.Text>
              </div>
              <ChartFigure<LdCell>
                definition={buildLdHeatmapChart(t("tools.popgen.ld.heatmapLegend"))}
                data={cells}
                label={t("tools.popgen.ld.heatmapTitle")}
                description={t("tools.popgen.ld.heatmapDesc")}
                tableColumns={[
                  t("tools.popgen.columns.variant"),
                  t("tools.popgen.columns.variant"),
                  "r²",
                ]}
                tableRow={(cell) => [cell.x, cell.y, cell.value.toFixed(3)]}
                emptyText={t("tools.popgen.ld.heatmapEmpty")}
                height={320}
              />
            </Card>
          ) : null}

          {result.variants.length > 0 ? (
            <Card>
              <div className="mb-4">
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {t("tools.popgen.ld.variantsTitle")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("tools.popgen.ld.variantsDesc")}
                </Typography.Text>
              </div>
              <DataTable
                ariaLabel={t("tools.popgen.ld.variantsTitle")}
                rowKey={variantRowKey}
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
                ]}
              />
            </Card>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
