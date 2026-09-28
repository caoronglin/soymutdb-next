<script setup lang="ts">
import { computed } from "vue";

import { isSafePageHref, type ResourceCardsProps } from "../../lib/page-definition";

/**
 * Renders the CMS-published `resource_cards` node on the home page.
 *
 * Ported from the React page-builder renderer's `ResourceCardsNode`. Only this
 * node type is supported: the portal's layout is code-defined, and the home
 * page is the only route whose content the operator edits through the page
 * builder. Unknown values are dropped rather than rendered — a card with an
 * unsafe `href` becomes a plain article, and an image URL that is not
 * `http(s)` is not rendered at all.
 */
const props = defineProps<{ node: ResourceCardsProps }>();

const visible = computed(() => props.node.heading !== "" || props.node.cards.length > 0);

/** Keep only cards that carry something a reader can see. */
const cards = computed(() =>
  props.node.cards
    .map((card, index) => ({
      key: index,
      title: typeof card.title === "string" ? card.title : "",
      description: typeof card.description === "string" ? card.description : "",
      // A card image must be an absolute http(s) URL; anything else is dropped.
      imageUrl: isSafePageHref(card.image_url) && /^https?:/i.test(card.image_url) ? card.image_url : "",
      href: isSafePageHref(card.href) ? card.href : "",
    }))
    .filter((card) => card.title !== "" || card.description !== "" || card.imageUrl !== "" || card.href !== ""),
);

type CardLink =
  | { kind: "internal"; href: string }
  | { kind: "external"; href: string }
  | { kind: "plain" };

/**
 * Internal routes keep client-side navigation; absolute `http(s)`/`mailto`/`tel`
 * targets become real anchors. React sent every non-http href through the router
 * link, which cannot resolve `mailto:` — a plain anchor is the correct target.
 */
function linkFor(href: string): CardLink {
  if (!href) return { kind: "plain" };
  if (/^https?:/i.test(href)) return { kind: "external", href };
  if (/^(mailto:|tel:)/i.test(href)) return { kind: "external", href };
  return { kind: "internal", href };
}
</script>

<template>
  <section v-if="visible" class="space-y-4" data-testid="resource-cards">
    <h2 v-if="node.heading" class="text-xl font-semibold tracking-tight">{{ node.heading }}</h2>
    <div v-if="cards.length > 0" class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <template v-for="card in cards" :key="card.key">
        <RouterLink
          v-if="linkFor(card.href).kind === 'internal'"
          :to="(linkFor(card.href) as { href: string }).href"
          class="block overflow-hidden rounded-xl border border-border bg-card transition-shadow hover:shadow-md"
          data-testid="resource-card"
        >
          <img v-if="card.imageUrl" :src="card.imageUrl" alt="" class="h-40 w-full object-cover" loading="lazy" />
          <div class="space-y-1.5 p-4">
            <h3 v-if="card.title" class="text-base font-semibold">{{ card.title }}</h3>
            <p v-if="card.description" class="text-sm text-muted-foreground">{{ card.description }}</p>
          </div>
        </RouterLink>
        <a
          v-else-if="linkFor(card.href).kind === 'external'"
          :href="(linkFor(card.href) as { href: string }).href"
          target="_blank"
          rel="noopener noreferrer"
          class="block overflow-hidden rounded-xl border border-border bg-card transition-shadow hover:shadow-md"
          data-testid="resource-card"
        >
          <img v-if="card.imageUrl" :src="card.imageUrl" alt="" class="h-40 w-full object-cover" loading="lazy" />
          <div class="space-y-1.5 p-4">
            <h3 v-if="card.title" class="text-base font-semibold">{{ card.title }}</h3>
            <p v-if="card.description" class="text-sm text-muted-foreground">{{ card.description }}</p>
          </div>
        </a>
        <article
          v-else
          class="block overflow-hidden rounded-xl border border-border bg-card transition-shadow hover:shadow-md"
          data-testid="resource-card"
        >
          <img v-if="card.imageUrl" :src="card.imageUrl" alt="" class="h-40 w-full object-cover" loading="lazy" />
          <div class="space-y-1.5 p-4">
            <h3 v-if="card.title" class="text-base font-semibold">{{ card.title }}</h3>
            <p v-if="card.description" class="text-sm text-muted-foreground">{{ card.description }}</p>
          </div>
        </article>
      </template>
    </div>
  </section>
</template>
