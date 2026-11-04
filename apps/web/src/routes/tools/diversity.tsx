/**
 * Nucleotide-diversity tool (`/tools/diversity`).
 *
 * POST /api/v1/tools/diversity reports π per base pair, π per polymorphic site
 * and — only when the caller states a sample size — Watterson's θ. Each of the
 * three is `null` for a different reason, so each renders with its own
 * explanation instead of a shared dash:
 *
 *   - π null          → the region holds no polymorphic site at all
 *   - θ null (asked)  → the region has no segregating site to feed θ
 *   - θ null (unasked)→ no sample size was supplied, so θ is not defined
 */
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Breadcrumb, Button, Card, Empty, Input, Result, Statistic, Tag, Typography } from "@/lib/antd";
import { CaretRightOutlined, LineChartOutlined, LoadingOutlined, RedoOutlined } from "@ant-design/icons";
import { ChartFigure } from "@soymutdb/charts";
import { computeDiversity, type DiversityResponse } from "@soymutdb/api-client";
import { DataTable } from "../../components/data-table";
import { formatNumber, formatPosition } from "../../lib/format";
import {
  buildDiversityWindowsChart,
  toWindowChartRows,
  type WindowChartRow,
} from "./-popgen-charts";
import {
  buildRegionQuery,
  EMPTY_REGION,
  formatRegion,
  RegionForm,
  type RegionErrors,
  type RegionFormState,
} from "./-popgen-form";

export const Route = createFileRoute("/tools/diversity")({
  component: DiversityComponent,
});

/** π values are small; four significant digits keep them readable. */
export function formatPi(value: number | null): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toPrecision(4);
}

function DiversityComponent() {
  const { t } = useTranslation();
  const [region, setRegion] = React.useState<RegionFormState>(EMPTY_REGION);
  const [errors, setErrors] = React.useState<RegionErrors>({});
  const [sampleSize, setSampleSize] = React.useState("");
  const [windowSize, setWindowSize] = React.useState("");

  const mutation = useMutation({
    mutationFn: async () => {
      const { query, errors: nextErrors } = buildRegionQuery(region, t);
      const sample = Number(sampleSize);
      const window = Number(windowSize);
      if (sampleSize.trim()) {
        if (!Number.isInteger(sample) || sample < 2 || sample > 1_000_000) {
          nextErrors.start = undefined;
          setErrors({ ...nextErrors });
          throw new Error(t("tools.popgen.diversity.errorSampleSize"));
        }
      }
      if (windowSize.trim() && (!Number.isInteger(window) || window < 0)) {
        throw new Error(t("tools.popgen.diversity.errorWindow"));
      }
      setErrors(nextErrors);
      if (!query) return null;
      return computeDiversity({
        ...query,
        ...(sampleSize.trim() ? { sample_size: sample } : {}),
        ...(windowSize.trim() ? { window_size: window } : {}),
      });
    },
  });

  const result: DiversityResponse | null = mutation.data ?? null;
  const requestedSampleSize = sampleSize.trim().length > 0;
  const windowRows = React.useMemo<WindowChartRow[]>(
    () => (result?.windows ? toWindowChartRows(result.windows) : []),
    [result],
  );

  return (
    <div className="container-prose section-rhythm">
      <header className="flex flex-col gap-4">
        <Breadcrumb
          items={[
            { title: <Link to="/tools">{t("tools.title")}</Link> },
            { title: t("tools.popgen.diversity.title") },
          ]}
        />
        <div className="flex items-start gap-3.5">
          <span className="flex size-11 items-center justify-center rounded-xl border bg-card shadow-sm">
            <LineChartOutlined className="size-5" aria-hidden />
          </span>
          <div>
            <Typography.Title level={1} style={{ margin: 0 }}>
              {t("tools.popgen.diversity.title")}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {t("tools.popgen.diversity.subtitle")}
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
            <Typography.Text type="secondary">
              {t("tools.popgen.diversity.formDesc")}
            </Typography.Text>
          </div>
          <form
            className="grid gap-5"
            onSubmit={(event) => {
              event.preventDefault();
              mutation.mutate();
            }}
          >
            <RegionForm idPrefix="dv" value={region} onChange={setRegion} errors={errors} />

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-2">
                <label htmlFor="dv-sample" className="text-sm font-medium">
                  {t("tools.popgen.diversity.sampleSizeLabel")}
                </label>
                <Input
                  id="dv-sample"
                  type="number"
                  min={2}
                  step={1}
                  value={sampleSize}
                  onChange={(event) => setSampleSize(event.target.value)}
                  placeholder={t("tools.popgen.diversity.sampleSizePlaceholder")}
                  className="font-mono"
                />
                <p className="text-xs text-muted-foreground">
                  {t("tools.popgen.diversity.sampleSizeHelp")}
                </p>
              </div>
              <div className="grid gap-2">
                <label htmlFor="dv-window" className="text-sm font-medium">
                  {t("tools.popgen.diversity.windowLabel")}
                </label>
                <Input
                  id="dv-window"
                  type="number"
                  min={0}
                  step={1}
                  value={windowSize}
                  onChange={(event) => setWindowSize(event.target.value)}
                  placeholder={t("tools.popgen.diversity.windowPlaceholder")}
                  className="font-mono"
                />
                <p className="text-xs text-muted-foreground">
                  {t("tools.popgen.diversity.windowHelp")}
                </p>
              </div>
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
                  setSampleSize("");
                  setWindowSize("");
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
                      {t("tools.popgen.diversity.emptyDesc")}
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
                <Typography.Text type="secondary">{formatRegion(result)}</Typography.Text>
              </div>
              <div className="flex flex-wrap gap-2">
                <Tag>{t("tools.popgen.diversity.span", { bp: formatNumber(result.n_bp) })}</Tag>
                <Tag>{t("tools.popgen.variantCount", { count: formatNumber(result.n_variants) })}</Tag>
                <Tag>
                  {t("tools.popgen.diversity.segregating", {
                    count: formatNumber(result.segregating_sites),
                  })}
                </Tag>
              </div>
            </Card>
          ) : null}
        </div>
      </div>

      {result ? (
        <section className="mt-10 grid gap-6" aria-label={t("tools.popgen.diversity.resultsTitle")}>
          {result.n_variants === 0 ? (
            <Empty
              description={
                <>
                  <p className="font-medium">{t("tools.popgen.diversity.noVariantsTitle")}</p>
                  <p className="text-sm text-muted-foreground">
                    {t("tools.popgen.diversity.noVariantsDesc")}
                  </p>
                </>
              }
            />
          ) : (
            <div className="grid gap-6 sm:grid-cols-3">
              <Card>
                <Statistic
                  title={t("tools.popgen.diversity.piLabel")}
                  value={formatPi(result.pi) ?? "—"}
                  suffix={<span className="text-xs text-muted-foreground">/bp</span>}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  {result.pi === null
                    ? t("tools.popgen.diversity.piNoPolymorphism")
                    : t("tools.popgen.diversity.piHelp")}
                </p>
              </Card>
              <Card>
                <Statistic
                  title={t("tools.popgen.diversity.piPerSiteLabel")}
                  value={formatPi(result.pi_per_site) ?? "—"}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  {result.pi_per_site === null
                    ? t("tools.popgen.diversity.piNoPolymorphism")
                    : t("tools.popgen.diversity.piPerSiteHelp")}
                </p>
              </Card>
              <Card>
                <Statistic
                  title={t("tools.popgen.diversity.thetaLabel")}
                  value={formatPi(result.theta) ?? "—"}
                />
                <p
                  className="mt-2 text-xs text-muted-foreground"
                  data-testid="theta-explanation"
                >
                  {result.theta !== null
                    ? t("tools.popgen.diversity.thetaHelp")
                    : requestedSampleSize
                      ? t("tools.popgen.diversity.thetaNullNoSites")
                      : t("tools.popgen.diversity.thetaNullNoSampleSize")}
                </p>
              </Card>
            </div>
          )}

          {result.windows && result.windows.length > 0 ? (
            <Card>
              <div className="mb-4">
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {t("tools.popgen.diversity.windowsTitle")}
                </Typography.Title>
                <Typography.Text type="secondary">
                  {t("tools.popgen.diversity.windowsDesc")}
                </Typography.Text>
              </div>
              <ChartFigure<WindowChartRow>
                definition={buildDiversityWindowsChart(t("tools.popgen.diversity.windowsAxis"))}
                data={windowRows}
                label={t("tools.popgen.diversity.windowsTitle")}
                description={t("tools.popgen.diversity.windowsDesc")}
                tableColumns={[
                  t("tools.popgen.diversity.windowStart"),
                  t("tools.popgen.diversity.windowEnd"),
                  t("tools.popgen.diversity.segregatingShort"),
                  t("tools.popgen.diversity.piLabel"),
                ]}
                tableRow={(row) => [row.startLabel, row.endLabel, String(row.segregating), row.piLabel]}
                emptyText={t("tools.popgen.diversity.windowsEmpty")}
                height={300}
              />
              <div className="mt-6">
                <DataTable
                  ariaLabel={t("tools.popgen.diversity.windowsTitle")}
                  rowKey={(row) => `${row.start}-${row.end}`}
                  data={result.windows}
                  columns={[
                    {
                      key: "start",
                      header: t("tools.popgen.diversity.windowStart"),
                      numeric: true,
                      cell: (row) => <span className="font-mono text-xs">{formatPosition(row.start)}</span>,
                    },
                    {
                      key: "end",
                      header: t("tools.popgen.diversity.windowEnd"),
                      numeric: true,
                      cell: (row) => <span className="font-mono text-xs">{formatPosition(row.end)}</span>,
                    },
                    {
                      key: "segregating",
                      header: t("tools.popgen.diversity.segregatingShort"),
                      numeric: true,
                      cell: (row) => <span className="font-mono text-xs">{row.segregating_sites}</span>,
                    },
                    {
                      key: "pi",
                      header: t("tools.popgen.diversity.piLabel"),
                      numeric: true,
                      cell: (row) => (
                        <span className="font-mono text-xs">{formatPi(row.pi) ?? "—"}</span>
                      ),
                    },
                  ]}
                />
              </div>
            </Card>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
