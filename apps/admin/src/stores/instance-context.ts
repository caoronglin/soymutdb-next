/**
 * Selected SoyMutDB instance (console state).
 *
 * The selection is UI state, not authority: it only names which registered
 * instance the console is presenting. It lives in module memory, like the
 * session itself — the console deliberately does not touch web storage, so a
 * reload returns to the safe local default and no state can survive on a
 * shared machine (see lib/auth.ts and scripts/check_admin_content_architecture.py).
 */
import { defineStore } from "pinia";

export const useAdminInstanceContext = defineStore("admin-instance-context", {
  state: () => ({
    selectedCode: null as string | null,
  }),
  actions: {
    /** Select a registered instance by its unique code; null means local. */
    select(code: string | null): void {
      this.selectedCode = code;
    },
  },
});
