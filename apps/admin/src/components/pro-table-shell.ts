/**
 * Shared ProTable shell preset for admin list pages (design §3.2).
 *
 * Every migrated list page owns its own data source, columns, rowKey and
 * pagination — this preset only pins the *shell*: the surrounding chrome that
 * ProTable would otherwise add. Keeping it in one object is what stops each page
 * from re-deciding, independently, whether it grows a search form, a toolbar and
 * a "settings" dropdown.
 *
 * Why read-only by default: these pages keep their own filter forms and their own
 * server-side pagination contract. ProTable's own search form would issue a second
 * `request` path with different params, and its settings/toolbar controls are
 * columns-visibility state the pages never had. Neither is a silent no-op, so both
 * stay off and a page that genuinely needs them opts back in explicitly.
 */
export const PRO_LIST_SHELL = {
  /** No generated search form — the page owns its filters. */
  search: false,
  /** No column-visibility / density dropdown. */
  options: false,
  /** No table title bar. */
  toolBarRender: false,
  /** No selection alert bar. */
  tableAlertRender: false,
  /** The page owns its container; a second card is redundant chrome. */
  cardBordered: false,
} as const;
