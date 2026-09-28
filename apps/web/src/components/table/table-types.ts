/**
 * Shared presentational types for the portal table/list surfaces.
 *
 * These pages used to hand-roll six different `<table>`s; the column contract
 * lives here so `DataTable.vue` is the only place that knows about density,
 * sticky headers, sort affordances and the compact (mobile) card fallback.
 */

/** Sortable/display column of a `DataTable`. */
export interface TableColumn {
  /** Stable column id; also the slot name (`#cell-<id>`) and the row field read by the default cell. */
  id: string;
  /** Visible header text. Omit for an icon/action column. */
  header?: string;
  /** When set, the header renders a sort button and `sort` events carry this key. */
  sortKey?: string;
  /** `data-testid` for that sort button, so page tests keep their stable hook. */
  sortTestId?: string;
  /** Right-align + tabular figures (counts, positions). */
  numeric?: boolean;
  /** Explicit alignment; `numeric` is shorthand for `right`. */
  align?: "left" | "center" | "right";
  /** Marks the column that becomes the heading of the compact mobile card. */
  primary?: boolean;
  /** Optional width hint applied to the header cell. */
  width?: string;
  /** Extra classes for the header cell. */
  headerClass?: string;
  /** `data-testid` for the header cell (conditional columns get a stable hook). */
  headerTestId?: string;
  /** Extra classes for every body cell of this column. */
  cellClass?: string;
}

/** Icon names available to `AppIcon.vue`; kept as a union so a typo fails typecheck. */
export type IconName =
  | "search"
  | "globe"
  | "arrow-right"
  | "arrow-left"
  | "download"
  | "reload"
  | "dna"
  | "beaker"
  | "file-text"
  | "inbox"
  | "alert"
  | "info"
  | "copy"
  | "check"
  | "microscope"
  | "chevron-left"
  | "chevron-right"
  | "arrow-up"
  | "arrow-down"
  | "sort"
  | "external";

/** Sort descriptor shared by the list pages and `DataTable`. */
export interface TableSort {
  key: string;
  dir: "asc" | "desc";
}
