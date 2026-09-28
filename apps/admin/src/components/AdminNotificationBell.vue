<template>
  <div ref="root" class="relative">
    <button
      type="button"
      class="flex size-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      :aria-label="
        t('admin.shell.notificationsAria', {
          defaultValue: 'Notifications ({{count}} unread)',
          count: unreadCount,
        })
      "
      :aria-expanded="open"
      data-testid="admin-notifications-toggle"
      @click="open = !open"
    >
      <svg aria-hidden="true" viewBox="0 0 24 24" class="size-4" fill="none">
        <path
          d="M6.5 9.5a5.5 5.5 0 1 1 11 0c0 3.2.7 4.8 1.5 5.8H5c.8-1 1.5-2.6 1.5-5.8Z"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linejoin="round"
        />
        <path d="M10.2 18.4a2 2 0 0 0 3.6 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
      </svg>
      <span v-if="unreadCount > 0" class="admin-dot" data-testid="admin-notifications-count">
        {{ unreadCount }}
      </span>
    </button>

    <div
      v-if="open"
      class="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
      role="menu"
      data-testid="admin-notifications-panel"
    >
      <div class="flex items-center justify-between border-b border-border px-4 py-2.5">
        <p class="text-sm font-semibold">
          {{ t("admin.shell.notifications", { defaultValue: "Notifications" }) }}
        </p>
        <button
          type="button"
          class="text-xs font-medium text-primary hover:underline disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="unreadCount === 0 || markAll.isPending.value"
          data-testid="admin-notifications-mark-all"
          @click="markAll.mutate()"
        >
          {{ t("admin.shell.markAllRead", { defaultValue: "Mark all as read" }) }}
        </button>
      </div>

      <!-- Both failure modes stay visible: an unreachable endpoint must not read
           as "no notifications". -->
      <p v-if="list.isPending.value" class="px-4 py-6 text-center text-xs text-muted-foreground">
        {{ t("common.loading") }}
      </p>
      <p
        v-else-if="list.isError.value"
        class="px-4 py-6 text-center text-xs text-destructive"
        data-testid="admin-notifications-error"
      >
        {{ t("common.errorDescription") }}
      </p>
      <ul v-else class="max-h-80 overflow-y-auto">
        <li v-if="items.length === 0" class="px-4 py-6 text-center text-xs text-muted-foreground">
          {{ t("admin.shell.notificationsEmpty", { defaultValue: "No notifications" }) }}
        </li>
        <li
          v-for="item in items"
          :key="item.id"
          class="flex items-start gap-3 border-b border-border/50 px-4 py-3 last:border-0"
          :class="item.read_at ? '' : 'bg-primary/5'"
          data-testid="admin-notification"
        >
          <span
            aria-hidden="true"
            class="mt-1.5 size-2 shrink-0 rounded-full"
            :class="item.read_at ? 'bg-transparent' : 'bg-primary'"
          />
          <div class="min-w-0 flex-1">
            <p class="text-sm">{{ item.title }}</p>
            <p v-if="item.body" class="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
              {{ item.body }}
            </p>
            <p class="mt-0.5 text-[11px] text-muted-foreground">
              {{ formatDate(item.created_at) }}
            </p>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from "@tanstack/vue-query";
import { computed, onMounted, onUnmounted, ref, toValue, useTemplateRef } from "vue";

import { formatDate } from "@soymutdb/shared/format";

import { adminApi } from "../lib/api";
import { t } from "../lib/i18n";

/**
 * Notification bell backed by the real notification endpoints
 * (`GET /notifications/unread-count`, `GET /notifications`, `POST /notifications/read`).
 *
 * The React console had this in the top bar; the Vue port dropped it entirely,
 * so an operator had no way to see that anything had happened.
 */
interface AdminNotification {
  id: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
}

interface AdminNotificationList {
  items: AdminNotification[];
}

const queryClient = useQueryClient();
const open = ref(false);
const root = useTemplateRef<HTMLElement>("root");

const unreadQuery = useQuery({
  queryKey: ["admin", "notifications", "unread"],
  queryFn: () => adminApi.get<{ unread_count: number }>("/notifications/unread-count"),
  refetchInterval: 30_000,
  staleTime: 10_000,
});

const list = useQuery({
  queryKey: ["admin", "notifications", "list"],
  queryFn: () => adminApi.get<AdminNotificationList>("/notifications?limit=20"),
  enabled: open,
  staleTime: 10_000,
});

const markAll = useMutation({
  mutationFn: () => adminApi.post<{ marked: number }>("/notifications/read", { json: { all: true } }),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin", "notifications"] }),
});

const unreadCount = computed(() => toValue(unreadQuery.data)?.unread_count ?? 0);
const items = computed<AdminNotification[]>(() => toValue(list.data)?.items ?? []);

function onDocumentMouseDown(event: MouseEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) open.value = false;
}

onMounted(() => document.addEventListener("mousedown", onDocumentMouseDown));
onUnmounted(() => document.removeEventListener("mousedown", onDocumentMouseDown));
</script>
