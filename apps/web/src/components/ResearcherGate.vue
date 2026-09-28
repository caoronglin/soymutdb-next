<template>
  <StateBlock
    v-if="isLoading"
    variant="loading"
    data-testid="researcher-gate-loading"
    :title="t('analyses.gate.checking', { defaultValue: 'Checking access…' })"
  />
  <StateBlock
    v-else-if="!isResearcher"
    variant="empty"
    icon="beaker"
    data-testid="researcher-gate-denied"
    :title="t('analyses.gate.title', { defaultValue: 'Research access required' })"
    :description="
      t('analyses.gate.description', {
        defaultValue:
          'The Analyze module runs fastp / scanpy pipelines and is available to researcher accounts and above. Sign in with a researcher account to submit analysis jobs.',
      })
    "
  >
    <template #action>
      <Button type="primary" size="small" data-testid="researcher-gate-sign-in" @click="signIn">
        {{ t("analyses.gate.signIn", { defaultValue: "Sign in" }) }}
      </Button>
      <Button size="small" data-testid="researcher-gate-back-home" @click="goHome">
        {{ t("analyses.gate.backHome", { defaultValue: "Back to home" }) }}
      </Button>
    </template>
  </StateBlock>
  <slot v-else />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import { Button } from "@soymutdb/ui-vue";

import StateBlock from "./states/StateBlock.vue";
import { useCurrentUser } from "../lib/current-user";
import { t } from "../lib/i18n";

/**
 * ResearcherGate — route-level permission guard for the analyses module.
 *
 * Analyses endpoints require the researcher role or higher on the server, so a
 * non-researcher session renders a "research access required" empty state
 * instead of hiding the routes (they stay crawlable and visible; only the
 * content is gated).
 *
 * This is UX only: the authorization boundary is `require_role(RESEARCHER)` on
 * the server. The gate merely avoids showing a form that would 401 on submit.
 */
const { isResearcher, isLoading } = useCurrentUser();

const route = useRoute();
const router = useRouter();

/** Send anonymous visitors to the sign-in page, returning here afterwards. */
const loginTarget = computed(() => ({
  path: "/login",
  query: { redirect: route.fullPath },
}));

function signIn() {
  void router.push(loginTarget.value);
}

function goHome() {
  void router.push("/");
}
</script>
