import { ApiOutlined, BookOutlined, DatabaseOutlined, InfoCircleOutlined } from "@ant-design/icons";
import { Collapse, ProCard, Tag, Typography } from "../lib/antd";
import { useTranslation } from "react-i18next";

export interface AdminUsageGuideItem {
  key: string;
  title: string;
  steps: string[];
  api?: string[];
  tables?: string[];
  note?: string;
}

interface AdminUsageGuideProps {
  items: AdminUsageGuideItem[];
  title?: string;
  description?: string;
  defaultActiveKey?: string[];
}

function CodeList({ values }: { values: string[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {values.map((value) => (
        <code
          key={value}
          className="max-w-full break-all rounded bg-muted px-2 py-1 font-mono text-xs text-foreground"
        >
          {value}
        </code>
      ))}
    </div>
  );
}

/**
 * Compact, route-level operating guide. Every item can describe both the API
 * contract and the database projection so operators know what a control does.
 */
export function AdminUsageGuide({
  items,
  title,
  description,
  defaultActiveKey = [],
}: AdminUsageGuideProps) {
  const { t } = useTranslation();
  if (items.length === 0) return null;

  const collapseItems = items.map((item) => ({
    key: item.key,
    label: item.title,
    children: (
      <div className="space-y-4 text-sm">
        <div>
          <Typography.Text strong>
            {t("admin.usage.stepsLabel", { defaultValue: "操作步骤" })}
          </Typography.Text>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-muted-foreground">
            {item.steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
        {item.api && item.api.length > 0 ? (
          <div className="space-y-2">
            <Typography.Text strong className="flex items-center gap-2">
              <ApiOutlined aria-hidden />
              {t("admin.usage.apiLabel", { defaultValue: "API 绑定" })}
            </Typography.Text>
            <CodeList values={item.api} />
          </div>
        ) : null}
        {item.tables && item.tables.length > 0 ? (
          <div className="space-y-2">
            <Typography.Text strong className="flex items-center gap-2">
              <DatabaseOutlined aria-hidden />
              {t("admin.usage.databaseLabel", { defaultValue: "数据库关系" })}
            </Typography.Text>
            <div className="flex flex-wrap gap-2">
              {item.tables.map((table) => (
                <Tag key={table} color="blue">
                  {table}
                </Tag>
              ))}
            </div>
          </div>
        ) : null}
        {item.note ? (
          <Typography.Text type="secondary" className="flex items-start gap-2">
            <InfoCircleOutlined className="mt-0.5 shrink-0" aria-hidden />
            <span>{item.note}</span>
          </Typography.Text>
        ) : null}
      </div>
    ),
  }));

  return (
    <ProCard className="border-primary/20 bg-primary/[0.03]" size="small">
      <div className="mb-3 flex items-start gap-3">
        <BookOutlined className="mt-1 text-primary" aria-hidden />
        <div className="min-w-0">
          <Typography.Title level={5} className="!mb-1">
            {title ?? t("admin.usage.title", { defaultValue: "使用说明" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            {description ??
              t("admin.usage.description", {
                defaultValue: "查看操作步骤、API 绑定和数据库关系。",
              })}
          </Typography.Text>
        </div>
      </div>
      <Collapse
        bordered={false}
        className="bg-transparent"
        defaultActiveKey={defaultActiveKey}
        items={collapseItems}
      />
    </ProCard>
  );
}
