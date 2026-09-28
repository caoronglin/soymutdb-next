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

export default function ReactApp() {
  return (
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <DesignSystemProvider>
          <App />
        </DesignSystemProvider>
      </QueryClientProvider>
    </React.StrictMode>
  );
}
