import { BellOutlined, MenuOutlined, SearchOutlined, SunOutlined, BulbOutlined, UserOutlined, LogoutOutlined, DownOutlined } from "@ant-design/icons";
import { AdminCommandPalette, type AdminCommandPath } from "./admin-command-palette";
import type * as React from "react";
// Ant Design icon component type is declared locally for the header.
type IconComponent = React.ComponentType<{
  className?: string;
  style?: React.CSSProperties;
  "aria-hidden"?: boolean | "true" | "false";
}>;
import { useCallback, useEffect, useRef, useState } from "react";
import { useAdminShellShortcuts } from "./use-admin-shell-shortcuts";
import { useTranslation } from "react-i18next";
import { useNavigate } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { cn } from "../lib/cn";
import { Button } from "@/lib/antd";
import { useAuth } from "../lib/auth-context";
interface AdminHeaderProps {
  /** Mobile sidebar toggle. */
  onToggleSidebar?: () => void;
  /** Current page title. */
  title?: string;
}

/**
 * Admin top bar with mobile sidebar toggle, page title, theme/language
 * switches, notification dropdown, and user menu.
 */
export function AdminHeader({ onToggleSidebar, title }: AdminHeaderProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    if (typeof document === "undefined") return "light";
    return document.documentElement.getAttribute("data-theme") === "dark"
      ? "dark"
      : "light";
  });

  const toggleTheme = useCallback(() => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
  }, [theme]);

  useAdminShellShortcuts({
    onOpenCommandPalette: () => setCommandPaletteOpen((open) => !open),
    onToggleSidebar,
  });

  const navigateFromCommandPalette = (path: AdminCommandPath) => {
    void navigate({ to: path });
  };

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-card/80">
      {onToggleSidebar ? (
        <Button
          type="text"
          shape="circle"
          className="lg:hidden"
          onClick={onToggleSidebar}
          aria-label={t("admin.shell.toggleSidebarAria", { defaultValue: "Toggle sidebar" })}
        >
          <MenuOutlined className="size-5" />
        </Button>
      ) : null}

      {title ? (
        <h1 className="font-serif text-lg font-semibold">{title}</h1>
      ) : null}

      <div className="ml-auto flex items-center gap-1">
        <Button
          aria-label={t("admin.shell.openCommandPalette", { defaultValue: "Open command palette" })}
          className="hidden sm:inline-flex"
          icon={<SearchOutlined className="size-4" />}
          onClick={() => setCommandPaletteOpen(true)}
          type="text"
        >
          <span className="text-xs text-muted-foreground">{t("admin.shell.commandPalette", { defaultValue: "Commands" })}</span>
          <kbd className="ml-1 rounded border border-border px-1 text-[10px] text-muted-foreground">⌘K</kbd>
        </Button>
        <ThemeToggle theme={theme} onToggle={toggleTheme} />
        <NotificationBell />
        <UserMenu />
      </div>
      <AdminCommandPalette
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={navigateFromCommandPalette}
        onOpenGene={(geneId) => window.location.assign("/genes/" + encodeURIComponent(geneId))}
        open={commandPaletteOpen}
      />
    </header>
  );
}

// ---------------------------------------------------------------------------
// Theme toggle
// ---------------------------------------------------------------------------

function ThemeToggle({
  theme,
  onToggle,
}: {
  theme: "light" | "dark";
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Button
      type="text"
      shape="circle"
      onClick={onToggle}
      aria-label={theme === "light" ? t("admin.shell.toggleThemeToDark", { defaultValue: "Switch to dark theme" }) : t("admin.shell.toggleThemeToLight", { defaultValue: "Switch to light theme" })}
      title={t("admin.shell.toggleTheme", { defaultValue: "Toggle theme" })}
    >
      {theme === "light" ? (
        <BulbOutlined className="size-4" />
      ) : (
        <SunOutlined className="size-4" />
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Notification bell — backed by GET /api/v1/notifications (auth required)
// ---------------------------------------------------------------------------

interface AdminNotification {
  id: string;
  title: string;
  body: string;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

interface AdminNotificationCount {
  unread_count: number;
}

interface AdminNotificationList {
  items: AdminNotification[];
  total: number;
  unread_count: number;
}

function NotificationBell() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const unreadQuery = useQuery({
    queryKey: ["admin-notifications-unread"],
    queryFn: () => http.get<AdminNotificationCount>("/notifications/unread-count"),
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const listQuery = useQuery({
    queryKey: ["admin-notifications-list"],
    queryFn: () => http.get<AdminNotificationList>("/notifications?limit=20"),
    enabled: open,
    staleTime: 10_000,
  });

  const markAllMutation = useMutation({
    mutationFn: () =>
      http.post<{ marked: number }>("/notifications/read", { json: { all: true } }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-notifications-unread"] });
      queryClient.invalidateQueries({ queryKey: ["admin-notifications-list"] });
    },
  });

  const unreadCount = unreadQuery.data?.unread_count ?? 0;
  const items = listQuery.data?.items ?? [];

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div ref={ref} className="relative">
      <Button
        type="text"
        shape="circle"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={t("admin.shell.notificationsAria", { defaultValue: "Notifications ({{count}} unread)", count: unreadCount })}
        aria-expanded={open}
      >
        <BellOutlined className="size-4" />
        {unreadCount > 0 ? (
          <span className="pointer-events-none absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-destructive-foreground">
            {unreadCount}
          </span>
        ) : null}
      </Button>

      {open ? (
        <div
          className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
          role="menu"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
            <p className="text-sm font-semibold">{t("admin.shell.notifications", { defaultValue: "Notifications" })}</p>
            <button
              type="button"
              className="text-xs font-medium text-primary hover:underline disabled:cursor-not-allowed disabled:opacity-50"
              disabled={unreadCount === 0 || markAllMutation.isPending}
              onClick={() => markAllMutation.mutate()}
            >
              {t("admin.shell.markAllRead", { defaultValue: "Mark all as read" })}
            </button>
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {items.length === 0 ? (
              <li className="px-4 py-6 text-center text-xs text-muted-foreground">
                {t("admin.shell.notificationsEmpty", { defaultValue: "No notifications" })}
              </li>
            ) : null}
            {items.map((n) => (
              <li
                key={n.id}
                className={cn(
                  "flex items-start gap-3 border-b border-border/50 px-4 py-3 last:border-0",
                  !n.read_at && "bg-primary/5",
                )}
              >
                <div
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    n.read_at ? "bg-transparent" : "bg-primary",
                  )}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{n.title}</p>
                  {n.body ? (
                    <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground/80">{n.body}</p>
                  ) : null}
                  <p className="mt-0.5 text-[11px] text-muted-foreground/60">
                    {new Date(n.created_at).toLocaleString()}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// UserOutlined menu
// ---------------------------------------------------------------------------

function UserMenu() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const closeMenu = () => setOpen(false);
  const initials = (user?.username ?? "admin").slice(0, 2).toUpperCase();
  const displayName = user?.username ?? t("admin.shell.adminUserLabel", { defaultValue: "Admin User" });

  const menuItems: Array<{ key: string; label: string; icon: IconComponent; danger?: boolean; onClick: () => void }> = [
    {
      key: "profile",
      label: t("admin.shell.profile", { defaultValue: "Profile" }),
      icon: UserOutlined,
      onClick: () => {
        closeMenu();
        navigate({ to: "/settings" });
      },
    },
    {
      key: "signOut",
      label: t("admin.shell.signOut", { defaultValue: "Sign out" }),
      icon: LogoutOutlined,
      danger: true,
      onClick: () => {
        closeMenu();
        logout();
      },
    },
  ];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label={t("admin.shell.userMenuAria", { defaultValue: "User menu" })}
        aria-expanded={open}
      >
        <div className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          {initials}
        </div>
        <span className="hidden text-sm font-medium sm:inline">{displayName}</span>
        <DownOutlined className="size-3.5 text-muted-foreground" />
      </button>

      {open ? (
        <div
          className="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
          role="menu"
        >
          <div className="border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">{displayName}</p>
            <p className="truncate text-xs text-muted-foreground">
              {user ? user.username : t("admin.shell.notSignedIn", { defaultValue: "Not signed in" })}
            </p>
          </div>
          <ul className="py-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.key}>
                  <button
                    type="button"
                    onClick={item.onClick}
                    className={cn(
                      "flex w-full items-center gap-2.5 px-4 py-2 text-sm transition-colors hover:bg-accent",
                      item.danger
                        ? "text-destructive hover:bg-destructive/10"
                        : "text-foreground",
                    )}
                    role="menuitem"
                  >
                    <Icon className="size-4" aria-hidden />
                    {item.label}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default AdminHeader;
