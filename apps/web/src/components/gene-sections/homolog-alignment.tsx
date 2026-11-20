/**
 * Align a gene's homologs and draw a neighbour-joining sketch tree.
 *
 * Two honest constraints shape this component:
 *
 * 1. A homolog row carries an *accession*, not residues. Aligning therefore
 *    means resolving each accession through the gene API first. A cross-version
 *    homolog (v4, DN53, …) often names a record this deployment does not hold,
 *    and this component says so per row instead of dropping it silently.
 * 2. The distances are p-distances over a progressive alignment. The response
 *    carries that caveat verbatim; nothing here upgrades it to a phylogeny.
 *
 * Nothing runs until the reader asks: a gene page must not fire N gene lookups
 * and a compute call to render a tab.
 */
import * as React from "react";
import { Alert, Button, Card, Empty, Space, Tag, Typography } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import {
  getGene,
  sequenceApi,
  type TreeResponse,
  type GeneHomologRecord,
} from "@soymutdb/api-client";

/** Two sequences cannot form a tree; the API requires at least three. */
const MIN_TREE_SEQUENCES = 3;

type Resolved = { accession: string; sequence: string };
type Unresolved = { accession: string; reason: string };

export interface HomologAlignmentProps {
  records: GeneHomologRecord[];
  /** Molecule to compare. CDS compares like with like across loci. */
  molecule?: "cds" | "protein";
}

export function HomologAlignment({ records, molecule = "cds" }: HomologAlignmentProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = React.useState(false);
  const [tree, setTree] = React.useState<TreeResponse | null>(null);
  const [resolved, setResolved] = React.useState<Resolved[]>([]);
  const [unresolved, setUnresolved] = React.useState<Unresolved[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  const accessions = React.useMemo(
    () => [...new Set(records.map((row) => row.homolog_gene_id).filter(Boolean))],
    [records],
  );

  /**
   * Resolve one accession to its sequence for the chosen molecule.
   *
   * Returns a value rather than throwing: a cross-version accession this
   * deployment does not hold is the expected case, and one missing record must
   * not abort the whole run.
   */
  const resolveOne = React.useCallback(
    async (accession: string): Promise<Resolved | Unresolved> => {
      try {
        const gene = await getGene(accession);
        const entry = (gene.sequences ?? []).find((item) => item.molecule === molecule);
        if (entry?.availability === "available" && entry.sequence) {
          return { accession, sequence: entry.sequence };
        }
        return {
          accession,
          reason: entry?.reason ?? t("genes.homologs.align.noSequence", { molecule }),
        };
      } catch {
        return { accession, reason: t("genes.homologs.align.notInDatabase") };
      }
    },
    [molecule, t],
  );

  const requestTree = React.useCallback(
    async (found: Resolved[]) => {
      try {
        const payload = await sequenceApi.tree({
          sequences: found.map((item) => item.sequence),
          labels: found.map((item) => item.accession),
          alphabet: molecule === "protein" ? "protein" : "dna",
        });
        setTree(payload);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : t("genes.sequences.analysis.failed"));
      }
    },
    [molecule, t],
  );

  const run = async () => {
    setBusy(true);
    setError(null);
    setTree(null);

    const outcomes = await Promise.all(accessions.map(resolveOne));
    const found = outcomes.filter((item): item is Resolved => "sequence" in item);
    const missing = outcomes.filter((item): item is Unresolved => "reason" in item);

    setResolved(found);
    setUnresolved(missing);

    if (found.length < MIN_TREE_SEQUENCES) {
      setError(
        t("genes.homologs.align.tooFew", {
          count: found.length,
          needed: MIN_TREE_SEQUENCES,
        }),
      );
      setBusy(false);
      return;
    }

    await requestTree(found);
    setBusy(false);
  };

  if (accessions.length === 0) {
    return <Empty description={t("genes.homologs.no_data")} />;
  }

  return (
    <Card
      size="small"
      data-testid="homolog-alignment"
      title={<span className="text-base">{t("genes.homologs.align.title")}</span>}
    >
      <Space orientation="vertical" size="small" className="w-full">
        <Space wrap size="small">
          <Button size="small" loading={busy} onClick={() => void run()}>
            {t("genes.homologs.align.run", { count: accessions.length, molecule })}
          </Button>
          <Typography.Text type="secondary" className="text-xs">
            {t("genes.homologs.align.hint")}
          </Typography.Text>
        </Space>

        {error ? <Alert type="error" showIcon title={error} /> : null}

        {unresolved.length > 0 ? (
          <Alert
            type="warning"
            showIcon
            data-testid="homolog-alignment-unresolved"
            title={t("genes.homologs.align.unresolvedTitle", { count: unresolved.length })}
            description={
              <ul className="m-0 list-disc pl-4 text-xs">
                {unresolved.map((item) => (
                  <li key={item.accession}>
                    <span className="font-mono">{item.accession}</span> — {item.reason}
                  </li>
                ))}
              </ul>
            }
          />
        ) : null}

        {tree ? (
          <div data-testid="homolog-alignment-tree">
            <Space wrap size="small" className="mb-1">
              <Tag color="blue">{t("genes.homologs.align.leaves", { count: tree.leaf_count })}</Tag>
              <Tag>{tree.method}</Tag>
              <Tag>{tree.distance_model}</Tag>
            </Space>
            <pre className="max-h-48 overflow-auto break-all whitespace-pre-wrap rounded border border-border bg-muted/30 p-2 font-mono text-xs">
              {tree.newick}
            </pre>
            {/* The API publishes this caveat; repeating it here keeps the tree
                from being read as a phylogenetic result. */}
            <Typography.Text type="secondary" className="mt-1 block text-xs">
              {tree.caveat}
            </Typography.Text>
          </div>
        ) : null}

        {resolved.length > 0 && !tree ? (
          <Typography.Text type="secondary" className="text-xs">
            {t("genes.homologs.align.resolved", { count: resolved.length })}
          </Typography.Text>
        ) : null}
      </Space>
    </Card>
  );
}
