/**
 * NewsCard — summary card for a single news article.
 *
 * Cover thumbnail + title + published date + category, linking to the
 * detail page. Backend list items carry no summary field (B1 schemas:
 * NewsSummaryResponse), so the card shows title/date/category + read-more.
 *
 * AntD Card for the surface, Tailwind for text/spacing (B2 pattern, no
 * the former shared component library).
 */
import { Link } from "@tanstack/react-router";
import { Card, Tag } from "@/lib/antd";
import { ArrowRightOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { NewsSummary } from "@soymutdb/api-client";
import { formatDate } from "../lib/format";

export interface NewsCardProps {
  item: NewsSummary;
  /** Optional cover height in px (default 160). */
  coverHeight?: number;
}

/** Pick the locale-appropriate title (zh UI prefers title_zh). */
export function pickNewsTitle(item: NewsSummary, lang: string): string {
  const isZh = lang.toLowerCase().startsWith("zh");
  return isZh && item.title_zh ? item.title_zh : item.title_en;
}

const FALLBACK_COVER =
  "linear-gradient(135deg, oklch(0.92 0.03 152), oklch(0.85 0.06 152))";

export function NewsCard({ item, coverHeight = 160 }: NewsCardProps) {
  const { t, i18n } = useTranslation();
  const title = pickNewsTitle(item, i18n.language);

  return (
    <Link
      to="/news/$slug"
      params={{ slug: item.slug }}
      className="group block h-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      aria-label={title}
    >
      <Card
        className="news-card h-full overflow-hidden transition-shadow hover:shadow-md"
        styles={{ body: { padding: 0 } }}
      >
        {item.cover_url ? (
          <img
            src={item.cover_url}
            alt={title}
            loading="lazy"
            className="w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
            style={{ height: coverHeight }}
          />
        ) : (
          <div
            role="img"
            aria-label={title}
            className="w-full"
            style={{ height: coverHeight, background: FALLBACK_COVER }}
          />
        )}
        <div className="p-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            {item.category ? (
              <Tag color="green" className="m-0">
                {item.category}
              </Tag>
            ) : null}
            {item.published_at ? (
              <span className="font-mono">{formatDate(item.published_at)}</span>
            ) : null}
          </div>
          <h3 className="mt-2 line-clamp-2 font-display text-base font-semibold tracking-tight text-foreground transition-colors group-hover:text-primary">
            {title}
          </h3>
          <span className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary">
            {t("news.readMore")}
            <ArrowRightOutlined className="text-[10px] transition-transform group-hover:translate-x-0.5" aria-hidden />
          </span>
        </div>
      </Card>
    </Link>
  );
}
