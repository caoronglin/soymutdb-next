<template>
  <div v-if="signedIn" ref="root" class="relative">
    <button
      ref="toggle"
      type="button"
      class="relative flex size-10 items-center justify-center rounded-md text-muted-foreground outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      aria-haspopup="menu"
      data-testid="portal-notifications-toggle"
      @click="togglePanel"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" class="size-5" fill="none">
        <path
          d="M6.5 9.5a5.5 5.5 0 1 1 11 0c0 3.2.7 4.8 1.5 5.8H5c.8-1 1.5-2.6 1.5-5.8Z"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
        <path d="M10.2 18.4a2 2 0 0 0 3.6 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      </svg>
      <span
        v-if="unreadCount > 0"
        class="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-semibold leading-4 text-primary-foreground"
        data-testid="portal-notifications-count"
      >
        {{ unreadCount > 99 ? "99+" : unreadCount }}
      </span>
    </button>

    <div
      v-if="open"
      class="absolute right-0 top-full z-50 mt-2 w-80 max-w-[85vw] overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
      role="menu"
      :aria-label="t('notifications.title', { defaultValue: 'Notifications' })"
      data-testid="portal-notifications-panel"
    >
      <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
        <p class="text-sm font-semibold">{{ t("notifications.title", { defaultValue: "Notifications" }) }}</p>
        <button
          type="button"
          class="text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="unreadCount === 0 || isMarkingRead"
          data-testid="portal-notifications-mark-all"
          @click="markAllRead"
        >
          {{ t("notifications.markAllRead", { defaultValue: "Mark all read" }) }}
        </button>
      </div>

      <!-- An unreachable endpoint must not read as "no notifications". -->
      <p v-if="isLoading" class="px-4 py-6 text-center text-xs text-muted-foreground">
        {{ t("common.loading", { defaultValue: "Loading..." }) }}
      </p>
      <div v-else-if="isError" class="px-4 py-6 text-center text-xs">
        <p class="text-destructive" data-testid="portal-notifications-error">
          {{ t("common.errorDescription", { defaultValue: "An unexpected error occurred while loading this page." }) }}
        </p>
        <button
          type="button"
          class="mt-2 font-medium text-primary hover:underline"
          data-testid="portal-notifications-retry"
          @click="refetch"
        >
          {{ t("common.retry", { defaultValue: "Retry" }) }}
        </button>
      </div>
      <ul v-else class="max-h-80 overflow-y-auto">
        <li v-if="items.length === 0" class="px-4 py-6 text-center text-xs text-muted-foreground" data-testid="portal-notifications-empty">
          {{ t("notifications.empty", { defaultValue: "No notifications yet" }) }}
        </li>
        <!-- Each row is itself the interactive element (`<a>` when the
             notification carries a link, `<button>` otherwise) so the click
             target is one focusable node, never a nested pair. -->
        <li
          v-for="item in orderedItems"
          :key="item.id"
          class="border-b border-border/50 last:border-0"
          :class="item.read_at ? '' : 'bg-primary/5'"
        >
          <a
            v-if="item.link"
            :href="item.link"
            role="menuitem"
            class="flex w-full items-start gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring"
            :data-read="item.read_at ? 'true' : 'false'"
            data-testid="portal-notification-row"
            @click="openItem(item)"
          >
            <span
              aria-hidden="true"
              class="mt-0.5 shrink-0"
              :class="typeVisual(item.type).tone"
              :title="typeTitle(item.type)"
            >
              <svg viewBox="0 0 24 24" class="size-4" fill="none">
                <path
                  :d="typeVisual(item.type).path"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm" :class="item.read_at ? 'text-muted-foreground' : 'font-medium'">
                {{ item.title.trim() || typeTitle(item.type) }}
              </span>
              <span v-if="item.body" class="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                {{ item.body }}
              </span>
              <span class="mt-0.5 block text-[11px] text-muted-foreground/80">
                {{ formatRelativeTime(item.created_at) }}
              </span>
            </span>
          </a>
          <button
            v-else
            type="button"
            role="menuitem"
            class="flex w-full items-start gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-accent/50 focus-visible:ring-2 focus-visible:ring-ring"
            :data-read="item.read_at ? 'true' : 'false'"
            data-testid="portal-notification-row"
            @click="openItem(item)"
          >
            <span
              aria-hidden="true"
              class="mt-0.5 shrink-0"
              :class="typeVisual(item.type).tone"
              :title="typeTitle(item.type)"
            >
              <svg viewBox="0 0 24 24" class="size-4" fill="none">
                <path
                  :d="typeVisual(item.type).path"
                  stroke="currentColor"
                  stroke-width="1.6"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm" :class="item.read_at ? 'text-muted-foreground' : 'font-medium'">
                {{ item.title.trim() || typeTitle(item.type) }}
              </span>
              <span v-if="item.body" class="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">
                {{ item.body }}
              </span>
              <span class="mt-0.5 block text-[11px] text-muted-foreground/80">
                {{ formatRelativeTime(item.created_at) }}
              </span>
            </span>
          </button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * PortalNotificationBell — in-app notification centre for the public portal.
 *
 * Restores the React baseline `notifications/notification-bell.tsx`
 * (d3904c2105f34e5d74f3ae3a163d6b25f075bf64), which the Vue migration dropped
 * entirely: signed-in-only bell, unread badge (30s poll), the 20 most recent
 * notifications unread-first, per-type icon, relative time, click-through
 * links, and "mark all read".
 *
 * The portal's ui-vue facade exposes no Badge/Popover/List, so the markup and
 * its tokens follow `apps/admin/src/components/AdminNotificationBell.vue`
 * (same design tokens, custom overlay) instead of the AntD primitives.
 *
 * Behavioural adaptations vs the baseline, all deliberate:
 *  - `enabled: !!user` on the list too (see lib/notifications.ts) so an
 *    anonymous visitor issues no guaranteed-401 request.
 *  - relative time instead of the baseline's absolute short date.
 *  - a row click calls `markRead` *and* navigates; the baseline also called
 *    `markRead` for unread rows only.
 *  - full a11y overlay contract (Escape, outside click, focus restore) which
 *    AntD's Popover supplied for free in React.
 */
import { computed, onMounted, onUnmounted, useTemplateRef, ref } from "vue";

import type { NotificationItem } from "@soymutdb/api-client";

import { useCurrentUser } from "../lib/current-user";
import { useNotifications } from "../lib/notifications";
import { t } from "../lib/i18n";

interface TypeVisual {
  /** Single-path inline SVG, stroked with `currentColor`. */
  path: string;
  /** Tone utility applied to the icon wrapper. */
  tone: string;
}

const ICON_COMPLETED = "M20 6.5 9.6 17 4 11.4";
const ICON_FAILED = "m6.5 6.5 11 11M17.5 6.5l-11 11";
const ICON_INFO = "M12 10.5V17M12 7.2v.2";
const ICON_INFO_BUBBLE = "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z";

/** Type vocabulary -> icon/tone. Mirrors the baseline's `typeVisual`. */
function typeVisual(type: string): TypeVisual {
  if (type.endsWith("_failed")) return { path: ICON_FAILED, tone: "text-destructive" };
  if (type.endsWith("_completed")) return { path: ICON_COMPLETED, tone: "text-emerald-600" };
  return { path: `${ICON_INFO_BUBBLE}${ICON_INFO}`, tone: "text-primary" };
}

/**
 * `blast_completed` -> `notifications.blastCompleted`, so a known job type
 * gets its translated title; an unknown type falls back to the raw string.
 */
function typeTitle(type: string): string {
  const key = type.replace(/_([a-z])/g, (_match, letter: string) => letter.toUpperCase());
  return t(`notifications.${key}`, { defaultValue: type });
}

const RELATIVE_UNITS: readonly { unit: Intl.RelativeTimeFormatUnit; ms: number }[] = [
  { unit: "year", ms: 31_536_000_000 },
  { unit: "month", ms: 2_592_000_000 },
  { unit: "day", ms: 86_400_000 },
  { unit: "hour", ms: 3_600_000 },
  { unit: "minute", ms: 60_000 },
];

/** Compact "3m ago" style relative time for a server timestamp. */
function formatRelativeTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const deltaMs = date.getTime() - Date.now();
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto", style: "narrow" });
  for (const { unit, ms } of RELATIVE_UNITS) {
    if (Math.abs(deltaMs) >= ms) return formatter.format(Math.round(deltaMs / ms), unit);
  }
  return formatter.format(Math.round(deltaMs / 1000), "second");
}

const root = useTemplateRef<HTMLElement>("root");
const toggle = useTemplateRef<HTMLButtonElement>("toggle");
const open = ref(false);

// Signed-in gate: an anonymous visitor gets no bell at all, and the query layer
// stays dormant (see lib/notifications.ts).
const { user } = useCurrentUser();
const { items, unreadCount, isLoading, isError, isMarkingRead, markRead, refetch } =
  useNotifications({ listEnabled: () => open.value });

const signedIn = computed(() => user.value !== null);

/**
 * Unread first, then newest first. The server already returns this order
 * (`notification_service.list_notifications`); re-sorting client-side keeps the
 * guarantee visible and survives a future unordered server change without
 * silently regressing the popover.
 */
const orderedItems = computed<NotificationItem[]>(() =>
  [...items.value].sort((a, b) => {
    const aUnread = a.read_at ? 1 : 0;
    const bUnread = b.read_at ? 1 : 0;
    if (aUnread !== bUnread) return aUnread - bUnread;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  }),
);

const ariaLabel = computed(() =>
  unreadCount.value > 0
    ? t("notifications.titleWithCount", {
        count: unreadCount.value,
        defaultValue: "Notifications ({{count}} unread)",
      })
    : t("notifications.title", { defaultValue: "Notifications" }),
);

function closePanel(restoreFocus = false) {
  open.value = false;
  if (restoreFocus) toggle.value?.focus();
}

function togglePanel() {
  if (open.value) closePanel(true);
  else open.value = true;
}

function openItem(item: NotificationItem) {
  if (!item.read_at) markRead({ ids: [item.id] });
  if (item.link) {
    closePanel();
    // Full navigation, like the baseline (`window.location.href`): notification
    // links are absolute app paths and may target an app the router does not own.
    window.location.href = item.link;
  }
}

function markAllRead() {
  markRead({ all: true });
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (!open.value || event.key !== "Escape") return;
  event.preventDefault();
  closePanel(true);
}

function onDocumentPointerDown(event: PointerEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) {
    // A pointer click outside does not move focus, so restoring it here would
    // steal focus from whatever the user just clicked. Only Escape restores.
    closePanel();
  }
}

onMounted(() => {
  document.addEventListener("keydown", onDocumentKeydown);
  document.addEventListener("pointerdown", onDocumentPointerDown);
});

onUnmounted(() => {
  document.removeEventListener("keydown", onDocumentKeydown);
  document.removeEventListener("pointerdown", onDocumentPointerDown);
});
</script>
