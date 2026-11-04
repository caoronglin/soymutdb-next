/**
 * Shared region form for the three population-genetics tools.
 *
 * All three endpoints take the *same* region selector: either a gene accession
 * or an explicit `assembly + chromosome + start + end` interval, never both and
 * never a partial interval. Building that selector once means the three pages
 * cannot disagree about what a valid query is, and the "exactly one mode"
 * refusal is stated in the form instead of arriving as a 422.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Input, Segmented, Select } from "@/lib/antd";
import type { PopgenRegionQuery } from "@soymutdb/api-client";
import { assembliesQueryOptions } from "../../lib/query-options";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

/** Server-side ceiling for one interval scan (see apps/api schemas/popgen.py). */
export const MAX_REGION_SPAN = 50_000_000;

export type RegionMode = "gene" | "interval";

export interface RegionFormState {
  mode: RegionMode;
  geneId: string;
  assembly: string;
  chromosome: string;
  start: string;
  end: string;
}

export const EMPTY_REGION: RegionFormState = {
  mode: "gene",
  geneId: "",
  assembly: "",
  chromosome: "",
  start: "",
  end: "",
};

export type RegionErrors = Partial<Record<keyof RegionFormState, string>>;

/**
 * Validate the form into either a usable request body or a field-error map.
 *
 * Returning the errors rather than throwing keeps the caller able to render
 * every problem at once, and keeps the "no query at all" case visibly distinct
 * from "a query the server will reject".
 */
export function buildRegionQuery(
  state: RegionFormState,
  t: (key: string, options?: Record<string, unknown>) => string,
): { query: PopgenRegionQuery | null; errors: RegionErrors } {
  const errors: RegionErrors = {};
  if (state.mode === "gene") {
    const gene = state.geneId.trim();
    if (!gene) errors.geneId = t("tools.popgen.errors.geneRequired");
    else if (gene.length > 64) errors.geneId = t("tools.popgen.errors.geneTooLong");
    if (!gene || errors.geneId) return { query: null, errors };
    return { query: { gene_id: gene }, errors };
  }

  const assembly = state.assembly.trim();
  const chromosome = state.chromosome.trim();
  const start = Number(state.start);
  const end = Number(state.end);
  if (!assembly) errors.assembly = t("tools.popgen.errors.assemblyRequired");
  if (!chromosome) errors.chromosome = t("tools.popgen.errors.chromosomeRequired");
  if (!Number.isInteger(start) || start < 1) errors.start = t("tools.popgen.errors.startInvalid");
  if (!Number.isInteger(end) || end < 1) errors.end = t("tools.popgen.errors.endInvalid");
  if (!errors.start && !errors.end && start > end) errors.end = t("tools.popgen.errors.order");
  if (!errors.start && !errors.end && end - start + 1 > MAX_REGION_SPAN) {
    errors.end = t("tools.popgen.errors.span", { max: MAX_REGION_SPAN });
  }
  if (Object.keys(errors).length > 0) return { query: null, errors };

  return {
    query: { assembly, chromosome, start, end },
    errors,
  };
}

export interface RegionFormProps {
  idPrefix: string;
  value: RegionFormState;
  onChange: (next: RegionFormState) => void;
  errors: RegionErrors;
}

export function RegionForm({ idPrefix, value, onChange, errors }: RegionFormProps) {
  const { t } = useTranslation();
  const releaseId = useReleaseId();
  const assembliesQuery = useQuery(
    assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );
  const assemblies = assembliesQuery.data ?? [];

  const patch = (next: Partial<RegionFormState>) => onChange({ ...value, ...next });

  return (
    <div className="grid gap-5">
      <div className="grid gap-2">
        <span className="text-sm font-medium">{t("tools.popgen.regionLabel")}</span>
        <Segmented<RegionMode>
          value={value.mode}
          onChange={(mode) => patch({ mode })}
          options={[
            { value: "gene", label: t("tools.popgen.modeGene") },
            { value: "interval", label: t("tools.popgen.modeInterval") },
          ]}
        />
        <p className="text-xs text-muted-foreground">{t("tools.popgen.regionHelp")}</p>
      </div>

      {value.mode === "gene" ? (
        <div className="grid gap-2">
          <label htmlFor={`${idPrefix}-gene`} className="text-sm font-medium">
            {t("tools.popgen.geneLabel")}
          </label>
          <Input
            id={`${idPrefix}-gene`}
            value={value.geneId}
            onChange={(event) => patch({ geneId: event.target.value })}
            placeholder={t("tools.popgen.genePlaceholder")}
            className="font-mono"
            aria-invalid={Boolean(errors.geneId)}
          />
          {errors.geneId ? <p className="text-xs text-destructive">{errors.geneId}</p> : null}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="grid gap-2">
            <label htmlFor={`${idPrefix}-assembly`} className="text-sm font-medium">
              {t("tools.popgen.assemblyLabel")}
            </label>
            <Select
              id={`${idPrefix}-assembly`}
              value={value.assembly || undefined}
              onChange={(next) => patch({ assembly: next ?? "" })}
              placeholder={t("tools.popgen.assemblyPlaceholder")}
              loading={assembliesQuery.isLoading}
              disabled={assembliesQuery.isError}
              options={assemblies.map((assembly) => ({
                value: String(assembly.id),
                label: `${assembly.name} (${assembly.version})`,
              }))}
              aria-invalid={Boolean(errors.assembly)}
            />
            {errors.assembly ? (
              <p className="text-xs text-destructive">{errors.assembly}</p>
            ) : assembliesQuery.isError ? (
              <p className="text-xs text-muted-foreground">
                {t("tools.popgen.assembliesError")}
              </p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <label htmlFor={`${idPrefix}-chromosome`} className="text-sm font-medium">
              {t("tools.popgen.chromosomeLabel")}
            </label>
            <Input
              id={`${idPrefix}-chromosome`}
              value={value.chromosome}
              onChange={(event) => patch({ chromosome: event.target.value })}
              placeholder={t("tools.popgen.chromosomePlaceholder")}
              className="font-mono"
              aria-invalid={Boolean(errors.chromosome)}
            />
            {errors.chromosome ? (
              <p className="text-xs text-destructive">{errors.chromosome}</p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <label htmlFor={`${idPrefix}-start`} className="text-sm font-medium">
              {t("tools.popgen.startLabel")}
            </label>
            <Input
              id={`${idPrefix}-start`}
              type="number"
              min={1}
              step={1}
              value={value.start}
              onChange={(event) => patch({ start: event.target.value })}
              className="font-mono"
              aria-invalid={Boolean(errors.start)}
            />
            {errors.start ? (
              <p className="text-xs text-destructive">{errors.start}</p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <label htmlFor={`${idPrefix}-end`} className="text-sm font-medium">
              {t("tools.popgen.endLabel")}
            </label>
            <Input
              id={`${idPrefix}-end`}
              type="number"
              min={1}
              step={1}
              value={value.end}
              onChange={(event) => patch({ end: event.target.value })}
              className="font-mono"
              aria-invalid={Boolean(errors.end)}
            />
            {errors.end ? <p className="text-xs text-destructive">{errors.end}</p> : null}
          </div>
        </div>
      )}
    </div>
  );
}

/** Render a resolved region as `assembly chromosome:start-end`. */
export function formatRegion(result: {
  assembly: string;
  chromosome: string;
  start: number;
  end: number;
}): string {
  return `${result.assembly} ${result.chromosome}:${result.start}-${result.end}`;
}
