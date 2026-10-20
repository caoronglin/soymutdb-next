import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { detectLanguage, initI18n } from "@soymutdb/i18n";
import { addJbrowseI18nResources } from "./i18n-extra";
import { DesignSystemProvider } from "./design-system-provider";
import App from "./App";
import "./index.css";

initI18n(detectLanguage());
addJbrowseI18nResources();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60_000,
      gcTime: 30 * 60_000,
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * Announce the React handoff on `<html data-app-ready>`.
 *
 * Umi prerenders inert markup; browser gates must wait for this boundary before
 * asserting (the portal/admin shells do the same). Without it an offline
 * artifact test cannot distinguish a live shell from the inert document.
 */
function AppReadySignal() {
  React.useLayoutEffect(() => {
    document.documentElement.dataset.appReady = "true";
  }, []);
  return null;
}

export default function ReactApp() {
  return (
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <DesignSystemProvider>
          <AppReadySignal />
          <App />
        </DesignSystemProvider>
      </QueryClientProvider>
    </React.StrictMode>
  );
}
