export interface AuditLogFilterValues {
  search?: string;
  action?: string;
  ipAddress?: string;
  startDate?: string;
  endDate?: string;
}

/**
 * Build the query parameters shared by audit-log list and export requests.
 *
 * Keeping the server field names here prevents the list and export actions from
 * drifting apart (the API uses ip_address, not the UI's ipFilter name).
 * Empty values are omitted so the API can distinguish an active filter from an
 * empty form field.
 */
export function buildAuditLogFilterParams(
  filters: AuditLogFilterValues,
): Record<string, string | undefined> {
  return {
    search: filters.search?.trim() || undefined,
    action:
      filters.action && filters.action !== "all" ? filters.action : undefined,
    ip_address: filters.ipAddress?.trim() || undefined,
    start_date: filters.startDate || undefined,
    end_date: filters.endDate || undefined,
  };
}
