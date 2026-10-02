import { useTranslation } from "react-i18next";
import { Alert, Card, Space, Tag, Typography } from "@/lib/antd";
import { SettingsDomainPage } from "./section-page";

export default function IntegrationsSettingsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-6">
      <SettingsDomainPage domain="integrations" />
      <Card title={t("admin.integrations.wecom.title", { defaultValue: "WeCom group bot" })}>
        <Space orientation="vertical" size="middle" className="w-full">
          <Typography.Paragraph type="secondary" className="mb-0">
            {t("admin.integrations.wecom.description", {
              defaultValue: "Send compact operational summaries to a WeCom group. Full records remain in the authenticated admin tables.",
            })}
          </Typography.Paragraph>
          <Alert
            type="info"
            showIcon
            title={t("admin.integrations.wecom.secretTitle", { defaultValue: "Secret configuration" })}
            description={t("admin.integrations.wecom.secretDescription", {
              defaultValue: "Configure SOYMUTDB_WECOM_BOT_WEBHOOK in the worker secret environment. The webhook is never stored in the database or returned by the API.",
            })}
          />
          <div className="flex flex-wrap gap-2" aria-label={t("admin.integrations.wecom.eventsLabel", { defaultValue: "Events" })}>
            {[
              "admin.integrations.wecom.eventJobs",
              "admin.integrations.wecom.eventSeeds",
              "admin.integrations.wecom.eventReleases",
            ].map((key) => (
              <Tag key={key} color="green">
                {t(key, { defaultValue: key.split(".").pop() ?? key })}
              </Tag>
            ))}
          </div>
          <Typography.Text type="secondary">
            {t("admin.integrations.wecom.privacy", {
              defaultValue: "Messages contain table-like summaries only; applicant contact details and raw errors are never sent.",
            })}
          </Typography.Text>
        </Space>
      </Card>
    </div>
  );
}
