/**
 * Seed-request entry for the gene detail page.
 *
 * Placement rules that matter:
 *
 * - The entry renders **only** when the gene actually has obtainable material
 *   (`availableSiteCount > 0`), so the page never advertises a request that
 *   cannot be fulfilled.
 * - The demand readout on the right is a plain antd `Statistic` fed by the
 *   public counts endpoint. No charting library is involved on this surface, and
 *   the endpoint returns counts only — nothing about a requester is ever
 *   fetched, let alone rendered.
 * - It is an in-page card, not a new route: navigating to the form is an
 *   ordinary link carrying the accession in the query string.
 */
import * as React from "react";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { SendOutlined } from "@ant-design/icons";
import { Button, Card, Flex, Space, Statistic, Tag, Tooltip, Typography, theme } from "@/lib/antd";
import { secureHttp } from "../lib/api";

export interface GeneSeedRequestEntryProps {
  geneId: string;
  /** Count of mutation sites flagged obtainable for this gene. */
  availableSiteCount: number;
  className?: string;
}

interface SeedRequestGeneCount {
  gene_id: string;
  requests: number;
}

interface SeedRequestStatsResponse {
  items: SeedRequestGeneCount[];
  total_requests: number;
}

/** Shown when the count is unknown, so a failed lookup never reads as "zero". */
const UNKNOWN = "—";

export function GeneSeedRequestEntry({
  geneId,
  availableSiteCount,
  className,
}: GeneSeedRequestEntryProps) {
  const { t } = useTranslation();
  const { token } = theme.useToken();

  const statsQuery = useQuery({
    queryKey: ["seed-request", "gene-stats", geneId],
    queryFn: () =>
      secureHttp.get<SeedRequestStatsResponse>(
        `/seed-requests/stats?gene_ids=${encodeURIComponent(geneId)}`,
      ),
    // Demand moves slowly and this sits on a read-hot page.
    staleTime: 5 * 60 * 1000,
    // Statistics are decoration here; a failure must not retry-spam the API or
    // surface an error banner over the gene itself.
    retry: false,
  });

  if (availableSiteCount <= 0) return null;

  const own = statsQuery.data?.items.find((item) => item.gene_id === geneId)?.requests;
  const overall = statsQuery.data?.total_requests;

  return (
    <Card className={className} size="small" data-testid="gene-seed-request">
      <Flex align="center" justify="space-between" wrap gap={token.marginMD}>
        <Space size={token.marginXS} wrap>
          <Link to="/seed-request" search={{ genes: geneId }}>
            <Button type="primary" icon={<SendOutlined />}>
              {t("genes.seedRequest.action", { defaultValue: "申请种子" })}
            </Button>
          </Link>
          <Tooltip
            title={t("genes.seedRequest.availableHint", {
              defaultValue: "该基因有 {{count}} 个突变位点标记为可获得",
              count: availableSiteCount,
            })}
          >
            <Tag color="green">
              {t("genes.seedRequest.availableCount", {
                defaultValue: "{{count}} 个可获得位点",
                count: availableSiteCount,
              })}
            </Tag>
          </Tooltip>
        </Space>

        <Space size={token.marginLG} wrap>
          <Statistic
            title={t("genes.seedRequest.ownCount", { defaultValue: "本基因申请次数" })}
            value={own ?? UNKNOWN}
            valueStyle={{ fontSize: token.fontSizeLG, color: token.colorPrimary }}
          />
          <Statistic
            title={t("genes.seedRequest.totalCount", { defaultValue: "全站申请总数" })}
            value={overall ?? UNKNOWN}
            valueStyle={{ fontSize: token.fontSize, color: token.colorTextSecondary }}
          />
        </Space>
      </Flex>

      {statsQuery.isError ? (
        <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
          {t("genes.seedRequest.statsUnavailable", {
            defaultValue: "申请次数暂时无法获取，不影响提交申请。",
          })}
        </Typography.Text>
      ) : null}
    </Card>
  );
}
