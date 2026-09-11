import ImportsPage, { type ImportsPageProps } from "../imports";

/**
 * Transitional route-compatible submission entry. It contains no duplicate
 * request or validation logic: all submits continue through the proven legacy
 * dialog until the fields are moved into a standalone wizard component.
 */
export function ImportSubmitEntry({ initialUploadOpen = true }: ImportsPageProps) {
  return <ImportsPage initialUploadOpen={initialUploadOpen} />;
}
