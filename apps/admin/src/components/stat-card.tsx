import type { ReactNode } from "react";
import { ProCard, Statistic, Typography } from "@/lib/antd";

export interface StatCardProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  trend?: { value: string; positive?: boolean };
  className?: string;
}

/** Small dashboard metric card implemented directly with Ant Design primitives. */
export function StatCard({ label, value, icon, trend, className }: StatCardProps) {
  return (
    <ProCard className={className} size="small">
      <div className="flex items-start justify-between gap-3">
        <Statistic title={label} value={value} />
        {icon ? <span className="text-primary">{icon}</span> : null}
      </div>
      {trend ? <Typography.Text type={trend.positive ? "success" : "secondary"}>{trend.value}</Typography.Text> : null}
    </ProCard>
  );
}
