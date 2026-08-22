import type { LucideIcon } from "lucide-react";
import {
  CircleDashed,
  Download,
  ShieldCheck,
  CheckCircle2,
  Archive,
  Clock,
  Loader2,
  XCircle,
  AlertCircle,
} from "lucide-react";
import { Badge, cn } from "../lib/admin-ui";

/** Badge variant names supported by the design system. */
type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "outline"
  | "success"
  | "warning";

/** Release lifecycle states (state machine). */
export type ReleaseStatus =
  | "draft"
  | "importing"
  | "validating"
  | "active"
  | "archived";

/** Generic task/job status. */
export type TaskStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

interface StatusConfig {
  label: string;
  variant: BadgeVariant;
  icon: LucideIcon;
  className?: string;
}

const RELEASE_STATUS_CONFIG: Record<ReleaseStatus, StatusConfig> = {
  draft: {
    label: "Draft",
    variant: "secondary",
    icon: CircleDashed,
  },
  importing: {
    label: "Importing",
    variant: "warning",
    icon: Download,
  },
  validating: {
    label: "Validating",
    variant: "warning",
    icon: ShieldCheck,
  },
  active: {
    label: "Active",
    variant: "success",
    icon: CheckCircle2,
  },
  archived: {
    label: "Archived",
    variant: "secondary",
    icon: Archive,
  },
};

const TASK_STATUS_CONFIG: Record<TaskStatus, StatusConfig> = {
  pending: {
    label: "Pending",
    variant: "secondary",
    icon: Clock,
  },
  running: {
    label: "Running",
    variant: "warning",
    icon: Loader2,
    className: "animate-spin",
  },
  completed: {
    label: "Completed",
    variant: "success",
    icon: CheckCircle2,
  },
  failed: {
    label: "Failed",
    variant: "destructive",
    icon: XCircle,
  },
  cancelled: {
    label: "Cancelled",
    variant: "secondary",
    icon: AlertCircle,
  },
};

interface StatusBadgeProps {
  status: ReleaseStatus | TaskStatus | string;
  type?: "release" | "task";
  className?: string;
}

/**
 * Status badge with state-machine-aware colours.
 * Release states: draft → importing → validating → active → archived.
 * Task states: pending → running → completed/failed/cancelled.
 */
export function StatusBadge({ status, type = "task", className }: StatusBadgeProps) {
  const config =
    type === "release"
      ? RELEASE_STATUS_CONFIG[status as ReleaseStatus]
      : TASK_STATUS_CONFIG[status as TaskStatus];

  if (!config) {
    return (
      <Badge variant="outline" className={className}>
        {status}
      </Badge>
    );
  }

  const Icon = config.icon;
  return (
    <Badge variant={config.variant} className={cn("gap-1", className)}>
      <Icon className={cn("size-3", config.className)} aria-hidden />
      {config.label}
    </Badge>
  );
}

/** Allowed state transitions for the release state machine. */
export const RELEASE_TRANSITIONS: Record<ReleaseStatus, ReleaseStatus[]> = {
  draft: ["importing"],
  importing: ["validating", "draft"],
  validating: ["active", "importing"],
  active: ["archived"],
  archived: [],
};

/** Check if a transition between release states is allowed. */
export function canTransition(from: ReleaseStatus, to: ReleaseStatus): boolean {
  return RELEASE_TRANSITIONS[from]?.includes(to) ?? false;
}

export default StatusBadge;
