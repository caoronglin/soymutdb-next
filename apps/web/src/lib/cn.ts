type ClassValue = string | false | null | undefined;

/** Dependency-free class-name joiner (AntD migration: decoupled from web-ui). */
export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
