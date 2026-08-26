type ClassValue = string | false | null | undefined;

/** Dependency-free class-name joiner (shared across Web/Admin). */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
