import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  Menu,
  Sun,
  Moon,
  User,
  LogOut,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import { Button, cn } from "../lib/admin-ui";

interface AdminHeaderProps {
  /** Mobile sidebar toggle. */
  onToggleSidebar?: () => void;
  /** Current page title. */
  title?: string;
}

interface Notification {
  id: string;
  message: string;
  timestamp: string;
  read: boolean;
}

/**
 * Admin top bar with mobile sidebar toggle, page title, theme/language
 * switches, notification dropdown, and user menu.
 */
export function AdminHeader({ onToggleSidebar, title }: AdminHeaderProps) {
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

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-border bg-card/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-card/80">
      {onToggleSidebar ? (
        <Button
          variant="ghost"
          size="icon"
          className="lg:hidden"
          onClick={onToggleSidebar}
          aria-label="Toggle sidebar"
        >
          <Menu className="size-5" />
        </Button>
      ) : null}

      {title ? (
        <h1 className="font-serif text-lg font-semibold">{title}</h1>
      ) : null}

      <div className="ml-auto flex items-center gap-1">
        <ThemeToggle theme={theme} onToggle={toggleTheme} />
        <NotificationBell />
        <UserMenu />
      </div>
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
  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={onToggle}
      aria-label={`Switch to ${theme === "light" ? "dark" : "light"} theme`}
      title="Toggle theme"
    >
      {theme === "light" ? (
        <Moon className="size-4" />
      ) : (
        <Sun className="size-4" />
      )}
    </Button>
  );
}

// ---------------------------------------------------------------------------
// Notification bell
// ---------------------------------------------------------------------------

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const notifications: Notification[] = [
    { id: "1", message: "Release v4.0 validation completed", timestamp: "2m ago", read: false },
    { id: "2", message: "New seed request from Dr. Chen", timestamp: "1h ago", read: false },
    { id: "3", message: "BLAST database updated", timestamp: "3h ago", read: true },
  ];
  const unreadCount = notifications.filter((n) => !n.read).length;

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
        variant="ghost"
        size="icon"
        onClick={() => setOpen((prev) => !prev)}
        aria-label={`Notifications (${unreadCount} unread)`}
        aria-expanded={open}
      >
        <Bell className="size-4" />
        {unreadCount > 0 ? (
          <span className="absolute right-1 top-1 flex size-4 items-center justify-center rounded-full bg-destructive text-[10px] font-bold text-destructive-foreground">
            {unreadCount}
          </span>
        ) : null}
      </Button>

      {open ? (
        <div
          className="absolute right-0 top-full mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
          role="menu"
        >
          <div className="border-b border-border px-4 py-2.5">
            <p className="text-sm font-semibold">Notifications</p>
          </div>
          <ul className="max-h-80 overflow-y-auto">
            {notifications.map((n) => (
              <li
                key={n.id}
                className={cn(
                  "flex items-start gap-3 border-b border-border/50 px-4 py-3 last:border-0",
                  !n.read && "bg-primary/5",
                )}
              >
                <div
                  className={cn(
                    "mt-1.5 size-2 shrink-0 rounded-full",
                    n.read ? "bg-transparent" : "bg-primary",
                  )}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm">{n.message}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {n.timestamp}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <div className="border-t border-border px-4 py-2">
            <button className="text-xs font-medium text-primary hover:underline">
              Mark all as read
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// User menu
// ---------------------------------------------------------------------------

function UserMenu() {
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

  const menuItems: Array<{ label: string; icon: LucideIcon; danger?: boolean }> = [
    { label: "Profile", icon: User },
    { label: "Sign out", icon: LogOut, danger: true },
  ];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="User menu"
        aria-expanded={open}
      >
        <div className="flex size-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-primary-foreground">
          AD
        </div>
        <span className="hidden text-sm font-medium sm:inline">Admin</span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </button>

      {open ? (
        <div
          className="absolute right-0 top-full mt-2 w-56 overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
          role="menu"
        >
          <div className="border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">Admin User</p>
            <p className="truncate text-xs text-muted-foreground">
              admin@soymutdb.org
            </p>
          </div>
          <ul className="py-1">
            {menuItems.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.label}>
                  <button
                    type="button"
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
