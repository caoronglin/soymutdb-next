import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { useTranslation } from "react-i18next";
import { Button, Empty, Input, Skeleton, Table, Typography, type TableColumnsType } from "@/lib/antd";
import { listMutantLines, type MutantLineResponse } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { getReleaseId } from "@soymutdb/api-client";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";

export const Route = createFileRoute("/mutants/")({
  component: MutantsIndex,
  validateSearch: (search: Record<string, unknown>) => ({
    mutagen: typeof search.mutagen === "string" ? search.mutagen : "",
  }),
});

const LIMIT = 100;

function MutantsIndex() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();
  const [mutagenDraft, setMutagenDraft] = React.useState(search.mutagen);

  React.useEffect(() => {
    setMutagenDraft(search.mutagen);
  }, [search.mutagen]);

  const applyMutagenFilter = () => {
    navigate({ to: "/mutants", search: { mutagen: mutagenDraft } });
  };

  const clearMutagenFilter = () => {
    setMutagenDraft("");
    navigate({ to: "/mutants", search: { mutagen: "" } });
  };

  const query = useQuery({
    queryKey: queryKeys.mutants.list({
      mutagen: search.mutagen || null,
      limit: LIMIT,
      releaseId: getReleaseId(),
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () => listMutantLines({ mutagen: search.mutagen || undefined, limit: LIMIT }),
  });
  const lines = query.data ?? [];

  const columns: TableColumnsType<MutantLineResponse> = [
    {
      title: t("mutantLines.lineId", { defaultValue: "Public ID" }),
      dataIndex: "public_id",
      key: "public_id",
      render: (_, line) => (
        <Link
          to="/mutants/$id"
          params={{ id: line.public_id }}
          data-public-id={line.public_id}
          data-testid="mutant-row"
          className="font-mono text-xs text-primary hover:underline"
        >
          {line.public_id}
        </Link>
      ),
    },
    {
      title: t("mutants.columns.name"),
      dataIndex: "name",
      key: "name",
      render: (name, line) => <Link to="/mutants/$id" params={{ id: line.public_id }}>{name}</Link>,
    },
    {
      title: t("mutants.columns.cultivar"),
      dataIndex: "cultivar",
      key: "cultivar",
      render: (value) => value ?? "—",
    },
    {
      title: t("mutants.columns.mutagen"),
      dataIndex: "mutagen",
      key: "mutagen",
      render: (value) => value ?? "—",
    },
    {
      title: t("mutants.columns.linkedVariants"),
      dataIndex: "variant_count",
      key: "variant_count",
      align: "right",
    },
  ];

  return (
    <FadeUp>
      <main className="container-prose py-10 md:py-14">
        <div>
          <p className="eyebrow">{t("mutants.eyebrow")}</p>
          <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("mutants.title")}</h1>
          <Typography.Paragraph type="secondary" className="mt-3 max-w-2xl">
            {t("mutants.subtitle")}
          </Typography.Paragraph>
        </div>

        <div className="mt-8 max-w-md">
          <label className="block" htmlFor="mutagen-filter">
            <span className="mb-2 block font-medium">{t("mutants.filter.label")}</span>
            <Input
              id="mutagen-filter"
              value={mutagenDraft}
              onChange={(event) => setMutagenDraft(event.target.value)}
              onPressEnter={applyMutagenFilter}
              placeholder={t("mutants.filter.placeholder")}
            />
          </label>
          <div className="mt-3 flex gap-2">
            <Button type="primary" onClick={applyMutagenFilter}>{t("mutants.filter.apply")}</Button>
            {search.mutagen ? <Button onClick={clearMutagenFilter}>{t("mutants.filter.clear")}</Button> : null}
          </div>
        </div>

        <section className="mt-6" aria-label={t("mutants.resultsAria")}>
          {query.isLoading ? (
            <Skeleton active paragraph={{ rows: 5 }} aria-label={t("mutants.loading")} />
          ) : query.isError ? (
            <Empty
              description={
                <span>
                  {t("mutants.error")}
                </span>
              }
            />
          ) : (
            <Table<MutantLineResponse>
              rowKey="public_id"
              columns={columns}
              dataSource={lines}
              pagination={false}
              locale={{
                emptyText: (
                  <Empty description={search.mutagen ? t("mutants.emptyFiltered") : t("mutants.empty")} />
                ),
              }}
            />
          )}
        </section>
      </main>
    </FadeUp>
  );
}
