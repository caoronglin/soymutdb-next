// Re-export shared UI-agnostic formatters. Kept as an app-local alias so
// existing "@/lib/format" imports keep working during the shared-package migration.
export { formatNumber, formatFileSize } from "@soymutdb/shared/format";
