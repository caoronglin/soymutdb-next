import { Button, PageContainer, ProCard, ProDescriptions } from "@/lib/antd";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { http } from "@soymutdb/api-client";

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
  return <ImportTaskDetailPage taskId={Number(taskId)} />;
}

export function ImportTaskDetailPage({ taskId }: { taskId: number }) {
  const taskQuery = useQuery({
    queryKey: ["admin-import", taskId],
    queryFn: () => http.get<ImportTaskDetail>("/admin/imports/" + taskId),
  });

  if (taskQuery.isPending) return <p className="p-6" role="status">Loading import task…</p>;
  if (taskQuery.isError || !taskQuery.data) {
    return (
      <PageContainer
        title="Import task unavailable"
        extra={[<Button key="back"><Link to="/imports">Back to imports</Link></Button>]}
      >
        <p className="text-muted-foreground">The task may have been removed or you may not have access.</p>
      </PageContainer>
    );
  }

  const task = taskQuery.data;
  return (
    <PageContainer
      title={`Import task #${task.id}`}
      subTitle={task.filename}
      extra={[<Button key="back"><Link to="/imports">Back to imports</Link></Button>]}
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
            { title: "Type", dataIndex: "type" },
            { title: "Status", dataIndex: "status" },
            {
              title: "Progress",
              key: "progress",
              render: (_value, row) => (
                <span>
                  {row.progress}% ({row.processed_records.toLocaleString()} /{" "}
                  {row.total_records.toLocaleString()})
                </span>
              ),
            },
            { title: "Submitted", dataIndex: "submitted_at" },
            {
              title: "Completed",
              key: "completed_at",
              render: (_value, row) => row.completed_at ?? "Not completed",
            },
            {
              title: "Error",
              key: "error_message",
              render: (_value, row) => row.error_message ?? "No error reported.",
            },
          ]}
        />
      </ProCard>
    </PageContainer>
  );
}
