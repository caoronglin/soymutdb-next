import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Descriptions, Empty, Skeleton, Table, type TableColumnsType } from "@/lib/antd";
import { getMutantLine, getMutantLinePhenotypes, getReleaseId, isMutantLineId, type PhenotypeResponse } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";

// Keep URL validation aligned with the public API contract. The server remains
// authoritative for normalization and existence; this gate only rejects blank,
// oversized, or unsafe path values before they reach the public endpoint.

export const Route = createFileRoute("/mutants/$id")({ component: MutantDetail });

function displayValue(value: string | null | undefined) {
  return value || "—";
}

function MutantDetail() {
  const { t } = useTranslation();
  const { id } = Route.useParams();
  const releaseId = getReleaseId();
  const mutantLineId = isMutantLineId(id) ? id : null;
  const lineQuery = useQuery({
    queryKey: mutantLineId ? queryKeys.mutants.detail(mutantLineId, releaseId, SITE_VARIANT) : ["mutant-line", null],
    queryFn: () => {
      if (!mutantLineId) throw new Error("Invalid mutant line ID");
      return getMutantLine(mutantLineId);
    },
    enabled: mutantLineId !== null,
  });
  const phenotypeQuery = useQuery({
    queryKey: mutantLineId
      ? queryKeys.mutants.phenotypes(mutantLineId, releaseId, SITE_VARIANT)
      : ["mutant-line-phenotypes", null],
    queryFn: () => {
      if (!mutantLineId) throw new Error("Invalid mutant line ID");
      return getMutantLinePhenotypes(mutantLineId);
    },
    enabled: mutantLineId !== null && lineQuery.isSuccess,
  });
  const phenotypeColumns: TableColumnsType<PhenotypeResponse> = [
    { title: t("mutants.phenotypes.category"), dataIndex: "trait_category", key: "trait_category" },
    { title: t("mutants.phenotypes.name"), dataIndex: "trait_name", key: "trait_name" },
    { title: t("mutants.phenotypes.value"), key: "value", render: (_, phenotype) => displayValue(phenotype.trait_value) },
    { title: t("mutants.phenotypes.unit"), dataIndex: "unit", key: "unit", render: displayValue },
    { title: t("mutants.phenotypes.description"), dataIndex: "description", key: "description", render: displayValue },
  ];

  if (mutantLineId && lineQuery.isLoading) {
    return <main className="container-prose py-10 md:py-14" aria-busy="true"><Skeleton active paragraph={{ rows: 7 }} aria-label={t("mutants.detail.loading")} /></main>;
  }

  if (!mutantLineId || lineQuery.isError || !lineQuery.data) {
    return <main className="container-prose py-10 md:py-14"><Empty description={t("mutants.detail.notFound")} /></main>;
  }

  const line = lineQuery.data;
  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14">
        <Link to="/mutants" search={{ mutagen: "" }} className="text-sm font-medium text-primary hover:underline">{t("mutants.detail.back")}</Link>
        <div className="mt-5">
          <p className="eyebrow">{t("mutants.eyebrow")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{line.name}</h1>
          <p className="mt-2 font-mono text-sm text-muted-foreground" data-public-id={line.public_id}>
            {t("mutantLines.lineId", { defaultValue: "Public ID" })}: {line.public_id}
          </p>
        </div>
        <section className="mt-8" aria-labelledby="mutant-line-details">
          <h2 id="mutant-line-details" className="font-display text-2xl font-semibold">{t("mutants.detail.details")}</h2>
          <Descriptions className="mt-4" bordered column={{ xs: 1, sm: 2 }} items={[
            { key: "species", label: t("mutants.fields.species"), children: line.species },
            { key: "cultivar", label: t("mutants.fields.cultivar"), children: displayValue(line.cultivar) },
            { key: "mutagen", label: t("mutants.fields.mutagen"), children: displayValue(line.mutagen) },
            { key: "generation", label: t("mutants.fields.generation"), children: displayValue(line.generation) },
            { key: "description", label: t("mutants.fields.description"), children: displayValue(line.description), span: 2 },
            { key: "phenotype-summary", label: t("mutants.fields.phenotypeSummary"), children: displayValue(line.phenotype_summary), span: 2 },
          ]} />
        </section>
        <section className="mt-10" aria-labelledby="mutant-phenotypes">
          <h2 id="mutant-phenotypes" className="font-display text-2xl font-semibold">{t("mutants.phenotypes.title")}</h2>
          <Alert className="mt-4" type="info" showIcon title={t("mutants.phenotypes.boundary")} />
          <div className="mt-5">
            {phenotypeQuery.isLoading ? <Skeleton active paragraph={{ rows: 4 }} aria-label={t("mutants.phenotypes.loading")} /> : phenotypeQuery.isError ? <Empty description={t("mutants.phenotypes.error")} /> : <Table<PhenotypeResponse> rowKey="id" columns={phenotypeColumns} dataSource={phenotypeQuery.data ?? []} pagination={false} scroll={{ x: true }} locale={{ emptyText: <Empty description={t("mutants.phenotypes.empty")} /> }} />}
          </div>
        </section>
      </main>
    </FadeUp>
  );
}
