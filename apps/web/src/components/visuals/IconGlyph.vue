<template>
  <svg
    class="icon-glyph"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="markup"
  />
</template>

<script setup lang="ts">
/**
 * IconGlyph — inline SVG icon set (no icon npm dependency).
 *
 * Semantics mirror the @ant-design/icons used by the React baseline
 * (`antd-home.tsx` / `site-header.tsx` at d3904c2105...): Idcard / Environment /
 * Global / Experiment / Thunderbolt for the five search tools, plus the header
 * and section glyphs. Inner markup is a static string per name so the component
 * stays dependency-free and tree-shakeable.
 */
import { computed } from "vue";

const ICONS: Record<string, string> = {
  // Search tools (Idcard / Environment / Global / Experiment / Thunderbolt).
  idcard:
    '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10.8" r="1.9"/><path d="M5.4 16.2c.7-1.7 2-2.6 3.1-2.6s2.4.9 3.1 2.6"/><path d="M14.6 9.6H18M14.6 13.2H18"/>',
  environment:
    '<path d="M12 21s6.5-5.6 6.5-10.5A6.5 6.5 0 0 0 5.5 10.5C5.5 15.4 12 21 12 21Z"/><circle cx="12" cy="10.4" r="2.4"/>',
  global:
    '<circle cx="12" cy="12" r="8.6"/><path d="M3.4 12h17.2M12 3.4c2.5 2.5 2.5 14.7 0 17.2M12 3.4c-2.5 2.5-2.5 14.7 0 17.2"/>',
  experiment:
    '<path d="M9 3h6M10 3v5.6L5.2 17A2 2 0 0 0 7 20h10a2 2 0 0 0 1.8-3L14 8.6V3"/><path d="M7.4 14h9.2"/>',
  thunderbolt: '<path d="M13.6 2.5 4.5 13.6H11l-.6 7.9 9.1-11.1H13z"/>',
  // Database directories.
  gene: '<path d="M7 3c0 4 10 4 10 9s-10 5-10 9"/><path d="M17 3c0 4-10 4-10 9s10 5 10 9"/><path d="M8.4 6.2h7.2M8.4 17.8h7.2M7 12h10"/>',
  variant:
    '<path d="M4 7h16M4 12h16M4 17h16"/><circle cx="9" cy="7" r="1.7"/><circle cx="15" cy="12" r="1.7"/><circle cx="7" cy="17" r="1.7"/>',
  mutant:
    '<path d="M12 21v-7"/><path d="M12 14c0-3.1-2.6-5.2-6.2-5.2C5.8 12 8.4 14 12 14Z"/><path d="M12 14c0-3.1 2.6-5.2 6.2-5.2C18.2 12 15.6 14 12 14Z"/>',
  assembly:
    '<path d="m12 3 8 4.5-8 4.5-8-4.5z"/><path d="m4 12 8 4.5 8-4.5"/><path d="m4 16.6 8 4.4 8-4.4"/>',
  download: '<path d="M12 4v10"/><path d="m8 11 4 4 4-4"/><path d="M5 19.5h14"/>',
  guide:
    '<path d="M4 5.6A2.6 2.6 0 0 1 6.6 3H19v15.4H6.6A2.6 2.6 0 0 0 4 21Z"/><path d="M4 18.4A2.6 2.6 0 0 1 6.6 16H19"/>',
  publications:
    '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12.5h6M9 16h6"/>',
  // Chrome.
  search: '<circle cx="11" cy="11" r="6.6"/><path d="m15.8 15.8 4.2 4.2"/>',
  news:
    '<path d="M6 9.5a6 6 0 1 1 12 0c0 4 1.4 5.6 1.4 5.6H4.6S6 13.5 6 9.5Z"/><path d="M10 18.6a2 2 0 0 0 4 0"/>',
  "arrow-right": '<path d="M4.5 12h14"/><path d="m12.5 6 6 6-6 6"/>',
  "chevron-down": '<path d="m5 9 7 7 7-7"/>',
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.2M12 19.8V22M4.9 4.9l1.6 1.6M17.5 17.5l1.6 1.6M2 12h2.2M19.8 12H22M4.9 19.1l1.6-1.6M17.5 6.5l1.6-1.6"/>',
  moon: '<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8 8.6 8.6 0 1 0 20.2 14.6Z"/>',
  github:
    '<path d="M9.2 20.4c-3.7 1.2-3.7-1.9-5.2-2.3M14.8 22v-3.1c0-.9.1-1.3-.4-1.8 2.2-.3 4.4-1.1 4.4-4.8a3.7 3.7 0 0 0-1-2.6 3.5 3.5 0 0 0-.1-2.6s-.8-.3-2.8 1a9.7 9.7 0 0 0-5.2 0c-2-1.3-2.8-1-2.8-1a3.5 3.5 0 0 0-.1 2.6 3.7 3.7 0 0 0-1 2.6c0 3.7 2.2 4.5 4.4 4.8-.4.4-.5.9-.5 1.6V22"/>',
  grid: '<rect x="3.6" y="3.6" width="7" height="7" rx="1.6"/><rect x="13.4" y="3.6" width="7" height="7" rx="1.6"/><rect x="3.6" y="13.4" width="7" height="7" rx="1.6"/><rect x="13.4" y="13.4" width="7" height="7" rx="1.6"/>',
  command:
    '<path d="M9.2 6A3.2 3.2 0 1 0 6 9.2h12A3.2 3.2 0 1 0 14.8 6v12A3.2 3.2 0 1 0 18 14.8H6A3.2 3.2 0 1 0 9.2 18Z"/>',
  leaf: '<path d="M12 21c0-6 2.5-10.5 7.5-13-1 6-3.5 9.5-7.5 13Z"/><path d="M12 21C12 15 9.5 10.5 4.5 8c1 6 3.5 9.5 7.5 13Z"/><path d="M12 21v-6.5"/>',
};

const props = defineProps<{ name: string }>();
const markup = computed(() => ICONS[props.name] ?? ICONS.gene);
</script>

<style scoped>
.icon-glyph {
  width: 1em;
  height: 1em;
  flex: none;
}
</style>
