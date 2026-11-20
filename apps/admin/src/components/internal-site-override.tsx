/**
 * The internal site is a separate deployment artifact, not a content toggle.
 *
 * Every appearance editor edits the public site unconditionally; this wrapper is
 * the one place an operator can opt into the internal variant's editors, with
 * the explanation next to the switch so the choice is never mistaken for "show
 * hidden content". Collapsed by default: most deployments never open it.
 */
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Flex, Switch, Typography } from "@/lib/antd";

export interface InternalSiteOverrideProps {
  /** Editors for the internal site artifact. */
  children: ReactNode;
}

export function InternalSiteOverride({ children }: InternalSiteOverrideProps) {
  const { t } = useTranslation();
  const [showInternal, setShowInternal] = useState(false);

  return (
    <Flex vertical gap={12}>
      <Flex
        align="center"
        justify="space-between"
        gap={12}
        className="rounded-md border border-dashed border-border p-3"
      >
        <Flex vertical>
          <Typography.Text strong>
            {t("admin.siteAppearance.internal.title", {
              defaultValue: "Internal site (internal deployments only)",
            })}
          </Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            {t("admin.siteAppearance.internal.help", {
              defaultValue:
                "The internal site is a separate deployment artifact, not part of the public site; these settings only affect the internal build.",
            })}
          </Typography.Text>
        </Flex>
        <Switch
          data-testid="site-variant-internal-switch"
          aria-label={t("admin.siteAppearance.internal.toggleAria", {
            defaultValue: "Edit internal site content",
          })}
          checked={showInternal}
          onChange={setShowInternal}
        />
      </Flex>
      {showInternal ? (
        <div data-testid="site-variant-internal-panel" className="space-y-3">
          {children}
        </div>
      ) : null}
    </Flex>
  );
}