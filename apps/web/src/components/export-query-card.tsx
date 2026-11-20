/**
 * No-SQL query builder for the unified download centre.
 *
 * It does not invent a second retrieval engine: the filter set is submitted
 * to the existing ``POST /exports/query`` pipeline, which refuses any filter
 * with no backing query capability. The card surfaces that boundary honestly
 * (unsupported filters are listed as unavailable, never offered as inputs)
 * and shows an explicit empty state when the release has no assemblies — a
 * form that can never produce an artifact is worse than no form.
 */

import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, Select, Typography } from "@/lib/antd";
import { submitExportQuery, type ExportQueryFilters } from "@soymutdb/api-client";
import { useIsResearcher } from "../lib/use-current-user";
import {
  EXPORT_QUERY_UNSUPPORTED_LABELS,
  SUPPORTED_EXPORT_QUERY_FILTERS,
} from "../lib/export-query-filters";

export interface ExportQueryCardProps {
  assemblies: { id: number | string; name: string; is_default?: boolean }[];
  defaultAssemblyId?: string;
}

const FORMATS = ["vcf", "tsv", "csv", "json", "bed"] as const;

export function ExportQueryCard({ assemblies, defaultAssemblyId }: ExportQueryCardProps) {
  const { t } = useTranslation();
  const { isResearcher, isLoading } = useIsResearcher();
  const [assemblyId, setAssemblyId] = React.useState<string | undefined>(defaultAssemblyId);
  const [format, setFormat] = React.useState<string>("tsv");
  const [chromosome, setChromosome] = React.useState("");
  const [impact, setImpact] = React.useState("");
  const [variantType, setVariantType] = React.useState("");
  const [state, setState] = React.useState<
    { status: "idle" } | { status: "loading" } | { status: "success"; id: string } | { status: "error"; message: string }
  >({ status: "idle" });

  const selected = assemblies.find((a) => String(a.id) === assemblyId)
    ?? assemblies.find((a) => a.is_default);
  const empty = assemblies.length === 0;

  const submit = async () => {
    if (!selected || !isResearcher) return;
    const filters: ExportQueryFilters = { assembly: selected.name };
    if (chromosome) filters.chromosome = chromosome;
    if (variantType) filters.variant_type = variantType;
    if (impact) filters.impact = impact;
    setState({ status: "loading" });
    try {
      const result = await submitExportQuery({ format, filters });
      setState({ status: "success", id: result.export_id });
    } catch (error) {
      setState({
        status: "error",
        message: error instanceof Error ? error.message : t("downloads.queryBuilderFailed"),
      });
    }
  };

  return (
    <Card className="mt-6 border-dashed" data-testid="export-query-card">
      <div className="p-6">
        <p className="font-medium">{t("downloads.queryBuilderTitle")}</p>
        <p className="text-sm text-muted-foreground">
          {t("downloads.queryBuilderDescription")}
        </p>

        {empty ? (
          <Typography.Text type="secondary" data-testid="export-query-empty">
            {t("downloads.queryBuilderEmpty")}
          </Typography.Text>
        ) : (
          <div className="mt-4 flex flex-wrap items-end gap-3" data-testid="export-query-form">
            <label className="flex flex-col gap-1 text-xs">
              {t("downloads.queryBuilderAssembly")}
              <Select
                data-testid="export-query-assembly"
                value={selected ? String(selected.id) : undefined}
                onChange={(value) => setAssemblyId(String(value))}
                options={assemblies.map((a) => ({ value: String(a.id), label: a.name }))}
                style={{ minWidth: 180 }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("downloads.queryBuilderFormat")}
              <Select
                data-testid="export-query-format"
                value={format}
                onChange={(value) => setFormat(String(value))}
                options={FORMATS.map((f) => ({ value: f, label: f.toUpperCase() }))}
                style={{ minWidth: 100 }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("downloads.queryBuilderChromosome")}
              <input
                className="rounded border px-2 py-1 text-sm"
                data-testid="export-query-chromosome"
                value={chromosome}
                onChange={(event) => setChromosome(event.target.value)}
                placeholder="chr01"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("downloads.queryBuilderVariantType")}
              <Select
                data-testid="export-query-variant-type"
                value={variantType || undefined}
                onChange={(value) => setVariantType(value ? String(value) : "")}
                allowClear
                options={["SNP", "INS", "DEL", "MNV", "SV"].map((v) => ({ value: v, label: v }))}
                style={{ minWidth: 110 }}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs">
              {t("downloads.queryBuilderImpact")}
              <Select
                data-testid="export-query-impact"
                value={impact || undefined}
                onChange={(value) => setImpact(value ? String(value) : "")}
                allowClear
                options={["HIGH", "MODERATE", "LOW", "MODIFIER"].map((v) => ({ value: v, label: v }))}
                style={{ minWidth: 130 }}
              />
            </label>
            <Button
              type="primary"
              data-testid="export-query-submit"
              loading={state.status === "loading"}
              disabled={!isResearcher || isLoading || !selected}
              onClick={() => void submit()}
            >
              {t("downloads.queryBuilderSubmit")}
            </Button>
          </div>
        )}

        {state.status === "success" ? (
          <Typography.Text data-testid="export-query-success">
            {t("downloads.queryBuilderSubmitted")}: {state.id}
          </Typography.Text>
        ) : null}
        {state.status === "error" ? (
          <Typography.Text type="danger" data-testid="export-query-error">
            {state.message}
          </Typography.Text>
        ) : null}

        <Typography.Text type="secondary" className="mt-3 block text-xs">
          {t("downloads.queryBuilderUnsupported")}{" "}
          {EXPORT_QUERY_UNSUPPORTED_LABELS.join(", ")}.{" "}
          {SUPPORTED_EXPORT_QUERY_FILTERS.length} {t("downloads.queryBuilderFiltersCount")}
        </Typography.Text>
      </div>
    </Card>
  );
}
