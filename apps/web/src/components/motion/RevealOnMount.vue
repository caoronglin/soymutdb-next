<template>
  <component :is="as" ref="root">
    <slot />
  </component>
</template>

<script setup lang="ts">
import { onMounted, useTemplateRef } from "vue";

import { useMotion } from "../../lib/motion";

/**
 * Entrance reveal for one page block: fade in + a small upward shift, once,
 * right after mount. The building block for page/section entrances.
 *
 * SSG / no-JS tradeoff (deliberate):
 * the element ships **no inline `opacity: 0`**. Prerendered HTML and the first
 * client paint are therefore fully visible — a JS-less crawler or reader never
 * gets a blank page, and a hydration mismatch cannot hide content. The animation
 * is armed in `onMounted` by adding a class, which for a client-rendered route
 * still runs before the first paint, so blocks do not flash at full opacity
 * first. The cost is that the entrance can only start after mount: a purely
 * CSS `@starting-style` variant would avoid that but needs the hidden initial
 * state to exist before JS, which is the tradeoff rejected here.
 *
 * `opacity` + `transform` only (compositor-friendly; no layout, no LCP-late
 * property), and the scoped rule reads the `--anim-*` tokens so duration and
 * easing stay owned by `style.css`.
 */
const props = withDefaults(
  defineProps<{
    /** Tag to render — `div` by default. */
    as?: string;
    /** Extra delay in ms before this block plays. */
    delay?: number;
    /** Position inside a staggered group; multiplied by the `--anim-stagger` token. */
    index?: number;
    /** Skip the entrance (e.g. a root view transition already covers the swap). */
    disabled?: boolean;
  }>(),
  { as: "div", delay: 0, index: 0, disabled: false },
);

const { reduced, staggerMs } = useMotion();
const root = useTemplateRef<HTMLElement>("root");

/** Marker class consumed by the scoped rule below; also the component contract. */
const ACTIVE_CLASS = "motion-reveal--active";

onMounted(() => {
  if (props.disabled || reduced.value) return;
  const node = root.value;
  if (!node) return;
  const delayMs = props.delay + props.index * staggerMs.value;
  if (delayMs > 0) node.style.animationDelay = `${delayMs}ms`;
  node.classList.add(ACTIVE_CLASS);
});
</script>

<style scoped>
.motion-reveal--active {
  animation: motion-reveal-in var(--anim-duration) var(--anim-easing) both;
  will-change: opacity, transform;
}

@keyframes motion-reveal-in {
  from {
    opacity: 0;
    transform: translate3d(0, 12px, 0);
  }
  to {
    opacity: 1;
    transform: translate3d(0, 0, 0);
  }
}
</style>
