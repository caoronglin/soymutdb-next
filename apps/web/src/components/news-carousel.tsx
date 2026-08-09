/**
 * NewsCarousel — autoplay cover-image carousel for the homepage hero area.
 *
 * Fetches `/news/featured` (deduped with the NewsCard grid via the shared
 * `news-featured` query key), flattens the backend carousel groups and
 * renders up to 6 slides (cover image + title overlay → /news/{slug}).
 * Autoplay every 5s (AntD Carousel); API failure / empty data renders
 * nothing (null) — never fake data.
 */
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { Carousel, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { getFeaturedNews, type NewsSummary } from "@soymutdb/api-client";
import { pickNewsTitle } from "./news-card";

/** Shared query key so homepage carousel + news grid fetch once. */
export const NEWS_FEATURED_KEY = ["news-featured"] as const;

export const NEWS_CAROUSEL_MAX_SLIDES = 6;

/** Flatten backend carousel groups → slides that actually have a cover. */
export function flattenCarouselSlides(data: {
  carousel: readonly { group: string; items: readonly NewsSummary[] }[];
}): NewsSummary[] {
  return data.carousel
    .flatMap((group) => group.items)
    .filter((item) => Boolean(item.cover_url))
    .slice(0, NEWS_CAROUSEL_MAX_SLIDES);
}

export function NewsCarousel() {
  const { t, i18n } = useTranslation();
  const featuredQuery = useQuery({
    queryKey: NEWS_FEATURED_KEY,
    queryFn: getFeaturedNews,
    staleTime: 5 * 60 * 1000,
  });

  const slides = featuredQuery.data ? flattenCarouselSlides(featuredQuery.data) : [];

  // Loading: keep layout stable with a subtle placeholder; failure/empty → null.
  if (featuredQuery.isLoading && !featuredQuery.data) {
    return (
      <div
        role="status"
        aria-label={t("news.carouselLoading")}
        className="flex h-72 items-center justify-center rounded-xl border border-border bg-muted/30"
      >
        <Spin size="small" />
      </div>
    );
  }
  if (slides.length === 0) return null;

  return (
    <Carousel
      autoplay
      autoplaySpeed={5000}
      dots
      dotPosition="bottom"
      draggable
      aria-label={t("news.carouselAria")}
    >
      {slides.map((item) => {
        const title = pickNewsTitle(item, i18n.language);
        return (
          <div key={item.slug}>
            <Link
              to="/news/$slug"
              params={{ slug: item.slug }}
              className="group relative block overflow-hidden rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <img
                src={item.cover_url ?? ""}
                alt={title}
                className="h-72 w-full object-cover transition-transform duration-500 group-hover:scale-[1.02]"
              />
              <span className="absolute inset-x-0 bottom-0 block bg-gradient-to-t from-black/70 via-black/30 to-transparent px-6 pb-5 pt-16">
                <span className="block max-w-2xl font-display text-lg font-semibold leading-snug text-white sm:text-xl">
                  {title}
                </span>
                {item.published_at ? (
                  <span className="mt-1 block text-xs text-white/70">
                    {new Intl.DateTimeFormat(i18n.language, {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    }).format(new Date(item.published_at))}
                  </span>
                ) : null}
              </span>
            </Link>
          </div>
        );
      })}
    </Carousel>
  );
}
