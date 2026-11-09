import { Link } from "@tanstack/react-router";
import { Tag } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { useInstanceContext } from "../lib/instance-context-react";

function hostOf(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    return new URL(value).host;
  } catch {
    return value;
  }
}

export function InstanceContextBadge() {
  const { t } = useTranslation();
  const { currentInstance, isRemote, isLoading } = useInstanceContext();
  const configuredReleaseId = import.meta.env.VITE_SOYMUTDB_RELEASE_ID as string | undefined;
  const releaseId =
    configuredReleaseId ||
    t("admin.status.releaseActive", { defaultValue: "Active" });
  const instanceLabel = currentInstance
    ? `${currentInstance.name} (${currentInstance.code})`
    : isLoading
      ? t("common.loading", { defaultValue: "Loading" })
      : "—";

  return (
    <Link
      to="/instances"
      className="hidden min-w-0 max-w-2xl items-center gap-2 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring xl:flex"
      aria-label={t("admin.instances.context", { defaultValue: "Current instance context" })}
      data-testid="instance-context"
    >
      <span className="max-w-40 truncate font-medium" data-testid="instance-context-instance">{instanceLabel}</span>
      <span aria-hidden="true" className="opacity-40">·</span>
      <span className="truncate" data-testid="instance-context-release">
        {t("admin.instances.releaseLabel", { defaultValue: "Release" })} {releaseId}
      </span>
      <span aria-hidden="true" className="opacity-40">·</span>
      <span className="truncate font-mono" data-testid="instance-context-server">
        {t("admin.instances.server", { defaultValue: "Server" })} {hostOf(currentInstance?.api_base_url)}
      </span>
      {isRemote ? (
        <Tag color="gold" data-testid="instance-context-remote">
          {t("admin.instances.registrationOnly", { defaultValue: "Registration only" })}
        </Tag>
      ) : null}
    </Link>
  );
}
