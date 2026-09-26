<template>
  <form class="locus-search" role="search" @submit.prevent="onSubmit">
    <label class="locus-search__label" :for="inputId">{{ props.label }}</label>
    <input
      :id="inputId"
      v-model="value"
      class="locus-search__input"
      type="text"
      :placeholder="props.placeholder"
      autocomplete="off"
      spellcheck="false"
    />
    <button class="locus-search__button" type="submit" :disabled="!canSubmit">
      {{ props.submitLabel }}
    </button>
    <p
      v-if="props.status"
      class="locus-search__status"
      :class="`locus-search__status--${props.statusTone}`"
      role="status"
      aria-live="polite"
      data-testid="locus-search-status"
    >
      {{ props.status }}
    </p>
  </form>
</template>

<script setup lang="ts">
import { computed, useId } from "vue";

const props = withDefaults(
  defineProps<{
    label?: string;
    placeholder?: string;
    submitLabel?: string;
    /** Feedback shown under the box (e.g. a "not found" message). */
    status?: string;
    /** Visual tone for `status`; defaults to neutral info. */
    statusTone?: "info" | "error";
  }>(),
  {
    label: "Location or gene",
    placeholder: "chr01:1-1000000 or gene ID",
    submitLabel: "Go",
    statusTone: "info",
  },
);

const emit = defineEmits<{
  (event: "submit", value: string): void;
}>();

const value = defineModel<string>({ default: "" });

const inputId = useId();
const canSubmit = computed(() => value.value.trim().length > 0);

function onSubmit(): void {
  const trimmed = value.value.trim();
  if (trimmed) emit("submit", trimmed);
}
</script>

<style scoped>
.locus-search {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}
.locus-search__status {
  flex-basis: 100%;
  margin: 0;
  font-size: var(--text-caption, 0.75rem);
  line-height: 1.4;
  color: var(--muted-foreground, oklch(0.48 0.028 152));
}
.locus-search__status--error {
  color: var(--destructive, oklch(0.58 0.22 27));
}
.locus-search__label {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}
.locus-search__input {
  min-width: 0;
  flex: 1;
  min-height: 2.25rem;
  padding-inline: 0.625rem;
  border: 1px solid var(--input, oklch(0.905 0.02 148));
  border-radius: var(--radius-md, 0.625rem);
  background: var(--background, #fff);
  color: var(--foreground, oklch(0.195 0.028 152));
  font-family: var(--font-mono, ui-monospace, monospace);
  font-size: var(--text-small, 0.875rem);
}
.locus-search__input:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
.locus-search__button {
  min-height: 2.25rem;
  padding-inline: 0.875rem;
  border: 1px solid var(--primary, oklch(0.46 0.13 152));
  border-radius: var(--radius-md, 0.625rem);
  background: var(--primary, oklch(0.46 0.13 152));
  color: var(--primary-foreground, oklch(0.988 0.004 148));
  font-size: var(--text-small, 0.875rem);
  font-weight: 600;
  cursor: pointer;
}
.locus-search__button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.locus-search__button:focus-visible {
  outline: 2px solid var(--ring, oklch(0.55 0.14 152));
  outline-offset: 2px;
}
</style>
