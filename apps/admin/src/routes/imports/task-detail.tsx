import { Button, Typography } from "@/lib/antd";
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
      <section className="space-y-4 p-6">
        <Typography.Title level={2}>Import task unavailable</Typography.Title>
        <p className="text-muted-foreground">The task may have been removed or you may not have access.</p>
        <Button><Link to="/imports">Back to imports</Link></Button>
      </section>
    );
  }

  const task = taskQuery.data;
  return (
    <section className="space-y-6 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <Typography.Title level={2}>Import task #{task.id}</Typography.Title>
          <p className="text-muted-foreground">{task.filename}</p>
        </div>
        <Button><Link to="/imports">Back to imports</Link></Button>
      </div>
      <dl className="grid max-w-2xl grid-cols-[auto_1fr] gap-x-6 gap-y-3 rounded-lg border border-border p-5 text-sm">
        <dt className="text-muted-foreground">Type</dt><dd>{task.type}</dd>
        <dt className="text-muted-foreground">Status</dt><dd>{task.status}</dd>
        <dt className="text-muted-foreground">Progress</dt><dd>{task.progress}% ({task.processed_records.toLocaleString()} / {task.total_records.toLocaleString()})</dd>
        <dt className="text-muted-foreground">Submitted</dt><dd>{task.submitted_at}</dd>
        <dt className="text-muted-foreground">Completed</dt><dd>{task.completed_at ?? "Not completed"}</dd>
        <dt className="text-muted-foreground">Error</dt><dd>{task.error_message ?? "No error reported."}</dd>
      </dl>
    </section>
  );
}
