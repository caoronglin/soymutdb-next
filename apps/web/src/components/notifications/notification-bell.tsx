/**
 * NotificationBell — in-app notification centre (D2).
 *
 * AntD Badge + Popover bell shown in the site header for authenticated
 * users: unread count badge (polled every 30s), the 20 most recent
 * notifications (unread first), per-item type icon + time, click-through
 * links, and a "mark all read" action.
 */
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { BellOutlined, CheckOutlined, CheckCircleOutlined, InfoCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { Badge, Button, Empty, List, Popover, Skeleton, Tag, Tooltip, Typography } from "@/lib/antd";
import { secureHttp } from "../../lib/api";
import { useCurrentUser } from "../../lib/use-current-user";
import { formatDate } from "../../lib/format";

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  body: string;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

interface NotificationListResponse {
  items: NotificationItem[];
  total: number;
  unread_count: number;
}

function fetchNotifications(): Promise<NotificationListResponse> {
  return secureHttp.get<NotificationListResponse>("/notifications?limit=20");
}

function fetchUnreadCount(): Promise<{ unread_count: number }> {
  return secureHttp.get<{ unread_count: number }>("/notifications/unread-count");
}

/** Icon + tone per notification type (worker-side type vocabulary). */
function typeVisual(type: string): { icon: React.ReactNode; color: string } {
  if (type.endsWith("_failed")) {
    return { icon: <CloseCircleOutlined className="size-4" aria-hidden />, color: "error" };
  }
  if (type.endsWith("_completed")) {
    return { icon: <CheckCircleOutlined className="size-4" aria-hidden />, color: "success" };
  }
  return { icon: <InfoCircleOutlined className="size-4" aria-hidden />, color: "processing" };
}

export function NotificationBell() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { user } = useCurrentUser();
  const [open, setOpen] = React.useState(false);

  const unreadQuery = useQuery({
    queryKey: ["notifications-unread"],
    queryFn: fetchUnreadCount,
    enabled: !!user,
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const listQuery = useQuery({
    queryKey: ["notifications-list"],
    queryFn: fetchNotifications,
    enabled: !!user && open,
    staleTime: 10_000,
  });

  const markAllMutation = useMutation({
    mutationFn: () =>
      secureHttp.post<{ marked: number }>("/notifications/read", {
        json: { all: true },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-list"] });
    },
  });

  const markReadMutation = useMutation({
    mutationFn: (id: string) =>
      secureHttp.post<{ marked: number }>("/notifications/read", {
        json: { ids: [id] },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications-unread"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-list"] });
    },
  });

  // Not signed in — no bell.
  if (!user) return null;

  const unread = unreadQuery.data?.unread_count ?? 0;
  const items = listQuery.data?.items ?? [];
  const loading = listQuery.isLoading || listQuery.isFetching;

  const content = (
    <div className="w-[340px] max-w-[85vw]">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <Typography.Text strong>{t("notifications.title")}</Typography.Text>
        <Button
          type="link"
          size="small"
          disabled={unread === 0 || markAllMutation.isPending}
          loading={markAllMutation.isPending}
          icon={<CheckOutlined className="size-3.5" aria-hidden />}
          onClick={() => markAllMutation.mutate()}
        >
          {t("notifications.markAllRead")}
        </Button>
      </div>
      {loading && items.length === 0 ? (
        <div className="p-3">
          <Skeleton active paragraph={{ rows: 3 }} title={false} />
        </div>
      ) : items.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("notifications.empty")}
          className="py-6"
        />
      ) : (
        <List<NotificationItem>
          dataSource={items}
          className="max-h-[420px] overflow-y-auto"
          renderItem={(item) => {
            const visual = typeVisual(item.type);
            return (
              <List.Item
                key={item.id}
                className="cursor-pointer !px-3 hover:bg-accent/60"
                onClick={() => {
                  if (!item.read_at) markReadMutation.mutate(item.id);
                  if (item.link) window.location.href = item.link;
                }}
              >
                <List.Item.Meta
                  avatar={
                    <Tag
                      color={visual.color}
                      className="mt-0.5 flex size-7 items-center justify-center !m-0"
                      icon={visual.icon}
                      style={{ borderRadius: 9999 }}
                    />
                  }
                  title={
                    <span className={item.read_at ? "text-muted-foreground" : "font-medium"}>
                      {item.title}
                    </span>
                  }
                  description={
                    <>
                      <span className="block text-xs text-muted-foreground/80 line-clamp-2">
                        {item.body}
                      </span>
                      <span className="block text-[11px] text-muted-foreground/60">
                        {formatDate(item.created_at)}
                      </span>
                    </>
                  }
                />
              </List.Item>
            );
          }}
        />
      )}
    </div>
  );

  return (
    <Popover
      content={content}
      trigger="click"
      placement="bottomRight"
      open={open}
      onOpenChange={setOpen}
      arrow={false}
      overlayClassName="notification-bell-popover"
    >
      <Tooltip title={t("notifications.title")}>
        <Badge count={unread} size="small" overflowCount={99}>
          <Button
            type="text"
            className="flex size-9 items-center justify-center"
            aria-label={t("notifications.title")}
          >
            <BellOutlined className="size-4" aria-hidden />
          </Button>
        </Badge>
      </Tooltip>
    </Popover>
  );
}
