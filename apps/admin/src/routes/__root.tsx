import * as React from "react";
import type { ReactNode } from "react";
import { AdminHeader } from "../components/admin-header";
import { AdminShell } from "../components/admin-shell";

interface AdminLayoutProps {
  children: ReactNode;
}

/**
 * Admin root layout: sidebar + header + scrollable content.
 *
 * The shell does NOT name the current page. The former `PAGE_TITLES` map
 * resolved a title here and handed it to `AdminHeader`, which put a second
 * `<h1>` above every page that already declares its own `PageContainer`
 * `title`/`subTitle` (2026-10-01 admin Pro migration §3.1). Two authorities for
 * one page name is exactly the divergence the slice existed to remove, and the
 * map could only ever cover the paths somebody remembered to add. `PageContainer`
 * is now the single owner: the title lives with the page that owns the content.
 */
export default function AdminLayout({ children }: AdminLayoutProps) {
  return (
    <AdminShell>
      <div className="w-full min-w-0 space-y-6">
        <AdminHeader />
        <div className="w-full min-w-0 space-y-6">{children}</div>
      </div>
    </AdminShell>
  );
}
