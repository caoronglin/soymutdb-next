import { StrictMode, useEffect, useMemo, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigProvider, App as AntdApp } from "antd";
import type { Locale } from "antd/es/locale";
import i18n, { initI18n, detectLanguage } from "@soymutdb/i18n";
import { clearLegacyTokens } from "@soymutdb/api-client";
import { AuthProvider } from "./lib/auth-context";
import { createAntdTheme, loadAntdLocale, isAdminDark } from "./lib/antd-theme";
import App from "./App";
import "./index.css";

// Initialise i18next before rendering.
initI18n(detectLanguage());

// One-time migration: drop legacy persisted access/refresh tokens from
// localStorage/sessionStorage (sessions now live in memory + HttpOnly cookie).
clearLegacyTokens();

// React Query client.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      gcTime: 5 * 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

// ---------------------------------------------------------------------------
// AntD ConfigProvider wrapper — theme + locale (upgrade-plan.md §二).
// theme: createAntdTheme()（OKLCH 覆盖 + reduced-motion，见 lib/antd-theme.ts）；
//        暗色跟随 admin-header 的 `data-theme` 属性（MutationObserver 监听）。
// locale: i18next `languageChanged` 事件驱动（oracle 遗漏 #1），按需 import
//         dayjs/antd locale 包（约 8KB）。
// ---------------------------------------------------------------------------
function AntdProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale | null>(null);
  const [dark, setDark] = useState(isAdminDark);

  useEffect(() => {
    let disposed = false;
    const apply = (lng?: string) => {
      void loadAntdLocale(lng ?? i18n.language).then((l) => {
        if (!disposed) setLocale(l);
      });
    };
    apply();
    const onChange = (lng: string) => apply(lng);
    i18n.on("languageChanged", onChange);
    return () => {
      disposed = true;
      i18n.off("languageChanged", onChange);
    };
  }, []);

  // Dark mode follows the existing admin `data-theme` attribute (admin-header).
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(isAdminDark()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);

  const theme = useMemo(() => createAntdTheme({ dark }), [dark]);

  return (
    <ConfigProvider locale={locale ?? undefined} theme={theme}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <AntdProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </AntdProvider>
  </StrictMode>,
);
