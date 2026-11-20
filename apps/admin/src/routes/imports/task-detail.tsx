import { Button, PageContainer, ProCard, ProDescriptions } from "@/lib/antd";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { http } from "@soymutdb/api-client";
import { useTranslation } from "react-i18next";

type ImportTaskDetail = {
  id: number;
  filename: string;
  type: string;
  status: string;
  progress: number;
  processed_records: number;
  total_records: number;
  error_message: string | null;
  submitted_at: string;
  completed_at: string | null;
};

export default function ImportTaskDetailRoute() {
  const { taskId } = useParams({ strict: false }) as { taskId: string };
  // `Number("abc")` is NaN, and "NaN" was then sent to the API as if it were
  // an id, which answers 422 for a URL the operator cannot have meant. A
  // non-numeric id is a bad request, not a missing task.
  const parsed = Number(taskId);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return <ImportTaskDetailPage taskId={null} />;
  }
  return <ImportTaskDetailPage taskId={parsed} />;
}

export function ImportTaskDetailPage({ taskId }: { taskId: number | null }) {
  const { t } = useTranslation();
  const taskQuery = useQuery({
    queryKey: ["admin-import", taskId],
    // An invalid id never reaches the API: there is nothing to fetch, and a
    // request for it would only report the mistake as a server error.
    queryFn: () => http.get<ImportTaskDetail>("/admin/imports/" + taskId),
    enabled: taskId !== null,
  });

  if (taskId === null) {
    return (
      <PageContainer
        title={t("admin.importDetail.invalidTitle", { defaultValue: "Invalid import task id" })}
        extra={[<Button key="back"><Link to="/imports">{t("admin.importDetail.back", { defaultValue: "Back to imports" })}</Link></Button>]}
      >
        <p className="text-muted-foreground">
          {t("admin.importDetail.invalidBody", {
            defaultValue: "This address does not name an import task.",
          })}
        </p>
      </PageContainer>
    );
  }

  if (taskQuery.isPending) return <p className="p-6" role="status">{t("admin.importDetail.loading", { defaultValue: "Loading import task…" })}</p>;
  if (taskQuery.isError || !taskQuery.data) {
    return (
      <PageContainer
        title={t("admin.importDetail.unavailableTitle", { defaultValue: "Import task unavailable" })}
        extra={[<Button key="back"><Link to="/imports">{t("admin.importDetail.back", { defaultValue: "Back to imports" })}</Link></Button>]}
      >
        <p className="text-muted-foreground">
          {t("admin.importDetail.unavailableBody", {
            defaultValue: "The task may have been removed or you may not have access.",
          })}
        </p>
      </PageContainer>
    );
  }

  const task = taskQuery.data;
  return (
    <PageContainer
      title={t("admin.importDetail.titleWithId", { id: task.id, defaultValue: "Import task #{{id}}" })}
      subTitle={task.filename}
      extra={[<Button key="back"><Link to="/imports">{t("admin.importDetail.back", { defaultValue: "Back to imports" })}</Link></Button>]}
    >
      {/*
        These six label/value pairs used to be a hand-written `<dl>` grid. The
        fields, the order, the "—" for an absent timestamp and the error fallback
        text are unchanged — only the container moved to ProDescriptions (design
        §3.3), so the detail view is described by a schema instead of six repeats
        of the same markup.
      */}
      <ProCard>
        <ProDescriptions<ImportTaskDetail>
          column={1}
          bordered
          dataSource={task}
          columns={[
            {
              title: t("admin.importDetail.type", { defaultValue: "Type" }),
              dataIndex: "type",
            },
            {
              title: t("admin.importDetail.status", { defaultValue: "Status" }),
              dataIndex: "status",
            },
            {
              title: t("admin.importDetail.progress", { defaultValue: "Progress" }),
              key: "progress",
              render: (_value, row) => (
                <span>
                  {row.progress}% ({row.processed_records.toLocaleString()} /{" "}
                  {row.total_records.toLocaleString()})
                </span>
              ),
            },
            {
              title: t("admin.importDetail.submittedAt", { defaultValue: "Submitted" }),
              dataIndex: "submitted_at",
            },
            {
              title: t("admin.importDetail.completedAt", { defaultValue: "Completed" }),
              key: "completed_at",
              render: (_value, row) =>
                row.completed_at ??
                t("admin.importDetail.notCompleted", { defaultValue: "Not completed" }),
            },
            {
              title: t("admin.importDetail.errorMessage", { defaultValue: "Error" }),
              key: "error_message",
              render: (_value, row) =>
                row.error_message ??
                t("admin.importDetail.noError", { defaultValue: "No error reported." }),
            },
          ]}
        />
      </ProCard>
    </PageContainer>
  );
}
