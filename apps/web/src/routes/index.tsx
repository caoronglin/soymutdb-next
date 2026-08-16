/**
 * Public home page — approved reference layout (Phase 4), assembled from the
 * seeded PageDefinition (apps/web/src/page-builder/seed.ts). The hero search
 * and statistics strip are removed (outside the approved structure); their
 * underlying APIs remain unchanged.
 *
 * Layout (top to bottom):
 *   1. 2:3 content grid — up to five latest-news links (left) + a three-to-six
 *      image featured carousel (right). Stacks to one column on mobile.
 *   2. Five direct task entries — Gene ID, Physical Location, JBrowse 2, BLAST,
 *      Primer Design (horizontal on desktop, wrap on tablet, stack on mobile).
 *   3. Sanitized, CMS-managed home content block (text/images/video/links),
 *      DOMPurify-sanitised on read.
 *
 * The concrete section order comes from the renderer driven by
 * HOME_DEFINITION; motion (FadeUp) and reduced-motion behavior are preserved.
 */
import { createFileRoute } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { FadeUp, MotionProvider, type MotionConfig } from "@soymutdb/motion";
import { useAnimation } from "../lib/animation-context";
import { HOME_DEFINITION, HOME_TOOL_ENTRIES } from "../page-builder/seed";
import { RenderNode, PageDefinitionRenderer } from "../page-builder/renderer";

export const Route = createFileRoute("/")({
  component: HomeComponent,
});

function HomeComponent() {
  const anim = useAnimation();

  const motionConfig = React.useMemo<MotionConfig>(
    () => ({
      duration: anim.duration,
      durationFast: anim.durationFast,
      durationSlow: anim.durationSlow,
      easing: anim.easing,
      easingSpring: anim.easingSpring,
      stagger: anim.stagger,
      reduced: anim.reduced,
    }),
    [anim],
  );

  return (
    <MotionProvider config={motionConfig}>
      <HomeTopSection />
      <HomeToolEntries />
      <HomeContentSection />
    </MotionProvider>
  );
}

/* ---------------------------------------------------------------------------
 * 1. 2:3 news / carousel grid
 * ------------------------------------------------------------------------- */

function HomeTopSection() {
  const { t } = useTranslation();
  return (
    <section className="bg-background" aria-label={t("news.title")}>
      <div className="container-prose py-10">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="eyebrow">{t("news.title")}</p>
            <h1 className="mt-2 font-display text-2xl font-semibold tracking-tight md:text-3xl">
              {t("news.latestNews")}
            </h1>
          </div>
        </div>

        <FadeUp>
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_3fr]">
            {/* Left: latest news — up to five linked headlines. */}
            <div className="min-w-0">
              <RenderNode
                node={{
                  type: "latest-news",
                  id: "home-latest-news",
                  props: { max: 5 },
                }}
              />
            </div>
            {/* Right: featured cover carousel (three to six slides). */}
            <div className="min-w-0">
              <RenderNode node={{ type: "featured-carousel", id: "home-featured-carousel" }} />
            </div>
          </div>
        </FadeUp>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * 2. Five direct task entries
 * ------------------------------------------------------------------------- */

function HomeToolEntries() {
  const { t } = useTranslation();
  return (
    <section className="border-b bg-muted/10" aria-label={t("nav.tools")}>
      <div className="container-prose py-10">
        <h2 className="mt-0 font-display text-lg font-semibold tracking-tight">
          {t("home.taskEntries")}
        </h2>
        <FadeUp>
          <div className="mt-5 grid w-full gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {HOME_TOOL_ENTRIES.map((entry) =>
              entry.type === "tool-entry" ? (
                <RenderNode key={entry.id} node={entry} />
              ) : null,
            )}
          </div>
        </FadeUp>
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------
 * 3. Sanitized CMS content block
 * ------------------------------------------------------------------------- */

function HomeContentSection() {
  return (
    <section className="border-b bg-background">
      <div className="container-prose py-10">
        <FadeUp>
          <PageDefinitionRenderer
            definition={{
              ...HOME_DEFINITION,
              sections: HOME_DEFINITION.sections.filter((s) => s.id === "home-content"),
            }}
          />
        </FadeUp>
      </div>
    </section>
  );
}
