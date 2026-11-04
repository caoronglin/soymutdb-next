/**
 * Gene family detail (`/comparative/$familyId`).
 *
 * The page has one job beyond listing members: it must not let an absent record
 * become a claim. `method`, `method_version`, `source_name` and
 * `source_version` are part of the family record, so they are rendered as
 * provenance rather than as optional metadata — a family with no stated method
 * is a guess, and the API does not allow one.
 */
import { assembliesQueryOptions } from "../../lib/query-options";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import {
  Card,
  Descriptions,
  Empty,
  Skeleton,
  Table,
  Tag,
  type TableColumnsType,
} from "@/lib/antd";
import { ArrowLeftOutlined as ArrowLeft } from "@ant-design/icons";
import {
  getFamily,
  type FamilyMember,
  type RelationshipType,
} from "@soymutdb/api-client";
import { ComparativeArtifactPanel } from "../../components/comparative/comparative-artifact-panel";
import { CoverageTable } from "../../components/comparative/coverage-states";
import { EvidenceLine } from "../../components/evidence-tag";
import { FadeUp, ScaleIn } from "../../components/route-motion";
import { queryKeys } from "../../lib/query-keys";
import { useReleaseId } from "../../lib/release-scope";
import { SITE_VARIANT } from "../../lib/site-variant";

export interface FamilyDetailSearch {
  assembly: string;
}

export function validateFamilyDetailSearch(search: Record<string, unknown>): FamilyDetailSearch {
  return { assembly: search.assembly ? String(search.assembly) : "" };
}

export const Route = createFileRoute("/comparative/$familyId")({
  component: FamilyDetailComponent,
  validateSearch: validateFamilyDetailSearch,
});

/** Renders the source's own vocabulary. No paraphrasing: the three classes differ. */
export function RelationshipTag({ type }: { type: RelationshipType | string }) {
  const color =
    type === "one_to_one" ? "green" : type === "one_to_many" ? "blue" : "purple";
  return (
    <Tag color={color} className="m-0 font-mono text-xs" data-relationship-type={type}>
      {type}
    </Tag>
  );
}

function FamilyDetailComponent() {
  const { t } = useTranslation();
  const { familyId } = Route.useParams();
  const { assembly } = Route.useSearch();
  const releaseId = useReleaseId();
  const assemblyId = assembly ? Number(assembly) : null;
  const numericId = Number(familyId);

  const assembliesQuery = useQuery(
    assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );
  const assemblyLabel =
    assembliesQuery.data?.find((candidate) => String(candidate.id) === assembly)?.name ??
    (assembly || "—");

  const familyQuery = useQuery({
    queryKey: queryKeys.comparative.family({
      familyId: numericId,
      assemblyId,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () => getFamily(numericId, { assembly_id: assemblyId }),
    enabled: Number.isFinite(numericId),
  });

  const family = familyQuery.data;

  const memberColumns: TableColumnsType<FamilyMember> = [
    {
      title: t("comparative.detail.memberGene"),
      dataIndex: "gene_accession",
      key: "gene_accession",
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_accession }}
          search={{ assembly }}
          className="link-underline font-mono text-xs"
        >
          {row.gene_accession}
        </Link>
      ),
    },
    {
      title: t("comparative.detail.memberSpecies"),
      dataIndex: "species",
      key: "species",
    },
    {
      title: t("comparative.detail.memberRelationship"),
      key: "relationship_type",
      render: (_, row) => <RelationshipTag type={row.relationship_type} />,
    },
    {
      title: t("comparative.detail.memberMethod"),
      key: "method",
      render: (_, row) =>
        // The import format may state no method for an individual row. That is
        // "not stated", not "blast" and not an empty string.
        row.method ? (
          <span className="font-mono text-xs">{row.method}</span>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      title: t("comparative.detail.memberConfidence"),
      dataIndex: "confidence",
      key: "confidence",
      align: "right",
      render: (_, row) =>
        row.confidence == null ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <span className="font-mono text-xs tabular-nums">{row.confidence.toFixed(2)}</span>
        ),
    },
  ];

  return (
    <FadeUp>
      <div className="container-prose section-rhythm py-10" data-testid="family-detail">
        <Link
          to="/comparative"
          search={{ page: 1, assembly, level: "" }}
          className="link-underline inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" aria-hidden />
          {t("comparative.detail.backToList")}
        </Link>

        {familyQuery.isLoading ? (
          <div className="mt-8 grid gap-4">
            <Skeleton active paragraph={{ rows: 1 }} title={{ width: "50%" }} />
            <Skeleton active paragraph={{ rows: 8 }} title={false} />
          </div>
        ) : familyQuery.isError || !family ? (
          <Card className="mt-8">
            <Empty description={t("comparative.detail.notFound")} className="py-8" />
          </Card>
        ) : (
          <>
            <div className="mt-6 flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <Tag className="m-0 font-mono text-[10px] uppercase">
                    {t(`comparative.level.${family.level}`)}
                  </Tag>
                  <Tag color="blue" className="m-0 font-mono text-[10px]">
                    {t("comparative.detail.assembly")}: {assemblyLabel}
                  </Tag>
                </div>
                <h1 className="mt-3 font-mono text-3xl font-semibold tracking-tight">
                  {family.external_id}
                </h1>
                <p className="mt-1 font-display text-xl text-muted-foreground">{family.name}</p>
                <div className="mt-2" data-testid="family-evidence">
                  <EvidenceLine evidence={family.evidence} />
                </div>
              </div>
            </div>

            <ScaleIn delay={80}>
              <Card
                className="mt-6"
                title={t("comparative.detail.provenanceTitle")}
                data-testid="family-provenance"
              >
                <Descriptions
                  size="small"
                  column={2}
                  items={[
                    {
                      key: "method",
                      label: t("comparative.detail.method"),
                      // Required by the contract: an unstated method is a bug,
                      // so an empty value is shown as such rather than as "".
                      children: (
                        <span className="font-mono text-xs" data-testid="family-method">
                          {family.method || "—"}
                        </span>
                      ),
                    },
                    {
                      key: "method_version",
                      label: t("comparative.detail.methodVersion"),
                      children: (
                        <span className="font-mono text-xs" data-testid="family-method-version">
                          {family.method_version ?? "—"}
                        </span>
                      ),
                    },
                    {
                      key: "source_name",
                      label: t("comparative.detail.sourceName"),
                      children: (
                        <span className="font-mono text-xs" data-testid="family-source-name">
                          {family.source_name}
                        </span>
                      ),
                    },
                    {
                      key: "source_version",
                      label: t("comparative.detail.sourceVersion"),
                      children: (
                        <span className="font-mono text-xs" data-testid="family-source-version">
                          {family.source_version}
                        </span>
                      ),
                    },
                    {
                      key: "release",
                      label: t("comparative.detail.release"),
                      children: <span className="font-mono text-xs">{family.release_id}</span>,
                    },
                    {
                      key: "source_url",
                      label: t("comparative.detail.sourceUrl"),
                      children: (
                        <a
                          href={family.source_url}
                          target="_blank"
                          rel="noreferrer"
                          className="link-underline break-all font-mono text-xs"
                        >
                          {family.source_url}
                        </a>
                      ),
                    },
                  ]}
                />
                <p className="mt-3 text-xs text-muted-foreground">
                  {t("comparative.detail.provenanceNote")}
                </p>
              </Card>
            </ScaleIn>

            <ScaleIn delay={120}>
              <Card
                className="mt-4"
                title={t("comparative.detail.relationshipTypes")}
                data-testid="family-relationship-types"
              >
                <div className="flex flex-wrap items-center gap-2">
                  {family.relationship_types.length === 0 ? (
                    <span className="text-sm text-muted-foreground">—</span>
                  ) : (
                    family.relationship_types.map((type) => (
                      <RelationshipTag key={type} type={type} />
                    ))
                  )}
                </div>
              </Card>
            </ScaleIn>

            <ScaleIn delay={160}>
              <Card className="mt-4" title={t("comparative.detail.membersTitle")}>
                <Table<FamilyMember>
                  rowKey={(row) => `${row.species}-${row.gene_accession}`}
                  size="small"
                  columns={memberColumns}
                  dataSource={family.members}
                  pagination={family.members.length > 20 ? { pageSize: 20 } : false}
                  scroll={{ x: 700 }}
                  locale={{ emptyText: t("comparative.detail.membersEmpty") }}
                />
              </Card>
            </ScaleIn>

            <ScaleIn delay={200}>
              <Card className="mt-4" title={t("comparative.coverage.title")}>
                <CoverageTable coverage={family.coverage} />
              </Card>
            </ScaleIn>

            <ComparativeArtifactPanel familyId={family.family_id} assemblyId={assemblyId} />
          </>
        )}
      </div>
    </FadeUp>
  );
}
