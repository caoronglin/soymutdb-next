import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Alert, Descriptions, Empty, Skeleton, Table, type TableColumnsType } from "@/lib/antd";
import { getMutantLine, getMutantLinePhenotypes, searchVariants, type PhenotypeResponse } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";

// Canonical public_id fast-fail gate (engineering default, pending
// product-owner confirmation): ``SM`` prefix + Crockford-Base32 characters.
// Non-canonical URL ids (lab designations, internal keys, arbitrary slugs)
// must never reach the public detail API — fail fast with the neutral
// not-found state. Body length is tolerated (6–12) until the format is
// frozen; the server remains the authoritative not-found oracle.
const CANONICAL_PUBLIC_ID = /^SM[0-9A-HJ-NP-TV-Z]{6,12}$/i;

export const Route = createFileRoute("/mutants/$id")({ component: MutantDetail });

function displayValue(value: string | null | undefined) {
  return value || "—";
}

function MutantDetail() {
  const { t } = useTranslation();
  const { id } = Route.useParams();
  const mutantLineId = CANONICAL_PUBLIC_ID.test(id) ? id : null;
  const lineQuery = useQuery({
    queryKey: ["mutant-line", mutantLineId],
    queryFn: () => {
      if (!mutantLineId) throw new Error("Invalid mutant line ID");
      return getMutantLine(mutantLineId);
    },
    enabled: mutantLineId !== null,
  });
  const phenotypeQuery = useQuery({
    queryKey: ["mutant-line-phenotypes", mutantLineId],
    queryFn: () => {
      if (!mutantLineId) throw new Error("Invalid mutant line ID");
      return getMutantLinePhenotypes(mutantLineId);
    },
    enabled: mutantLineId !== null && lineQuery.isSuccess,
  });
  const variantDiscoveryQuery = useQuery({
    queryKey: ["mutant-line-variant-discovery", mutantLineId],
    queryFn: () => {
      if (!mutantLineId) throw new Error("Invalid mutant line ID");
      return searchVariants({ mutant_line_id: mutantLineId, limit: 1 });
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
        <div className="mt-5"><p className="eyebrow">{t("mutants.eyebrow")}</p><h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{line.name}</h1></div>
        {(variantDiscoveryQuery.data?.items.length ?? 0) > 0 ? (
          <Link
            to="/variants"
            search={{ chromosome: "", variant_type: "", impact: "", mutant_line_id: mutantLineId, cursor: undefined }}
            className="mt-4 inline-flex text-sm font-medium text-primary hover:underline"
          >
            {t("mutants.detail.viewVariants")}
          </Link>
        ) : null}
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
          <Alert className="mt-4" type="info" showIcon message={t("mutants.phenotypes.boundary")} />
          <div className="mt-5">
            {phenotypeQuery.isLoading ? <Skeleton active paragraph={{ rows: 4 }} aria-label={t("mutants.phenotypes.loading")} /> : phenotypeQuery.isError ? <Empty description={t("mutants.phenotypes.error")} /> : <Table<PhenotypeResponse> rowKey="id" columns={phenotypeColumns} dataSource={phenotypeQuery.data ?? []} pagination={false} scroll={{ x: true }} locale={{ emptyText: <Empty description={t("mutants.phenotypes.empty")} /> }} />}
          </div>
        </section>
      </main>
    </FadeUp>
  );
}
