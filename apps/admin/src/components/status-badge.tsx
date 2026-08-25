import { DashOutlined, DownloadOutlined, SafetyCertificateOutlined, CheckCircleOutlined, InboxOutlined, ClockCircleOutlined, LoadingOutlined, CloseCircleOutlined, ExclamationCircleOutlined } from "@ant-design/icons";
import type { ComponentType } from "react";
import { cn } from "../lib/cn";
import { Badge } from "@/lib/antd";
/** Badge variant names supported by the design system. */
type BadgeVariant = "default" | "processing" | "success" | "warning" | "error";

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
  icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  className?: string;
}

const RELEASE_STATUS_CONFIG: Record<ReleaseStatus, StatusConfig> = {
  draft: {
    label: "Draft",
    variant: "default",
    icon: DashOutlined,
  },
  importing: {
    label: "Importing",
    variant: "warning",
    icon: DownloadOutlined,
  },
  validating: {
    label: "Validating",
    variant: "warning",
    icon: SafetyCertificateOutlined,
  },
  active: {
    label: "Active",
    variant: "success",
    icon: CheckCircleOutlined,
  },
  archived: {
    label: "Archived",
    variant: "default",
    icon: InboxOutlined,
  },
};

const TASK_STATUS_CONFIG: Record<TaskStatus, StatusConfig> = {
  pending: {
    label: "Pending",
    variant: "default",
    icon: ClockCircleOutlined,
  },
  running: {
    label: "Running",
    variant: "warning",
    icon: LoadingOutlined,
    className: "animate-spin",
  },
  completed: {
    label: "Completed",
    variant: "success",
    icon: CheckCircleOutlined,
  },
  failed: {
    label: "Failed",
    variant: "error",
    icon: CloseCircleOutlined,
  },
  cancelled: {
    label: "Cancelled",
    variant: "default",
    icon: ExclamationCircleOutlined,
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
      <Badge color="default" className={className}>
        {status}
      </Badge>
    );
  }

  const Icon = config.icon;
  return (
    <Badge color={config.variant} className={cn("gap-1", className)}>
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
