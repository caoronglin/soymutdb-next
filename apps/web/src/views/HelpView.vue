<script setup lang="ts">

import PortalLayout from "../components/PortalLayout.vue";
import { t } from "../lib/i18n";
import { useSiteContent } from "../lib/site-content";

/**
 * Help center — the portal's usage contract in one page.
 *
 * This is deliberately prose, not a widget: a database portal has to state how
 * identifiers, assemblies and releases behave, because those are the three
 * things a first-time user gets wrong.
 */
const { get } = useSiteContent();

/**
 * FAQ list, in catalog-name form.
 *
 * The i18n catalog keys the questions `help.q1`..`help.q6`, while the
 * admin-editable backend keys are `help.faq1.q`..`help.faq6.q` — a deliberate
 * one-based index shift (React: `get("help.faq" + (i + 1) + ".q", faq.q)`).
 * Keep the catalog name here and derive the backend key from the loop index so
 * neither side silently drifts.
 */
const FAQ = [
  "help.q1",
  "help.q2",
  "help.q3",
  "help.q4",
  "help.q5",
  "help.q6",
] as const;
</script>

<template>
  <PortalLayout>
    <div class="mx-auto max-w-3xl px-4 py-8">
      <h1 class="text-2xl font-semibold">{{ t("help.title") }}</h1>
      <p class="mt-1 text-sm opacity-70">{{ t("help.subtitle") }}</p>

      <section class="mt-8" aria-labelledby="help-getting-started">
        <h2 id="help-getting-started" class="text-lg font-medium">
          {{ get("help.gettingStarted", t("help.gettingStarted")) }}
        </h2>
        <ol class="mt-3 grid list-decimal gap-2 ps-5 text-sm opacity-80">
          <li>{{ t("help.step1") }}</li>
          <li>{{ t("help.step2") }}</li>
          <li>{{ t("help.step3") }}</li>
        </ol>
      </section>

      <section class="mt-8" aria-labelledby="help-documentation">
        <h2 id="help-documentation" class="text-lg font-medium">
          {{ get("help.documentation", t("help.documentation")) }}
        </h2>
        <p class="mt-2 text-sm opacity-80">{{ t("docs.subtitle") }}</p>
      </section>

      <section class="mt-8" aria-labelledby="help-faq">
        <h2 id="help-faq" class="text-lg font-medium">{{ get("help.faq", t("help.faq")) }}</h2>
        <dl class="mt-3 grid gap-4" data-testid="help-faq-list">
          <div v-for="(key, index) in FAQ" :key="key">
            <dt class="text-sm font-medium" :data-testid="'help-question-' + index">
              {{ get(`help.faq${index + 1}.q`, t(`${key}.q`)) }}
            </dt>
            <dd class="mt-1 text-sm opacity-80">
              {{ get(`help.faq${index + 1}.a`, t(`${key}.a`)) }}
            </dd>
          </div>
        </dl>
      </section>

      <section class="mt-8" aria-labelledby="help-contact">
        <h2 id="help-contact" class="text-lg font-medium">
          {{ get("help.contact", t("help.contact")) }}
        </h2>
        <p class="mt-2 text-sm opacity-80">{{ t("help.contactDesc") }}</p>
      </section>
    </div>
  </PortalLayout>
</template>
