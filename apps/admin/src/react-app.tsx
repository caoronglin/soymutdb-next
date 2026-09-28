import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n } from "@soymutdb/i18n";
import { clearLegacyTokens } from "@soymutdb/api-client";
import { AuthProvider } from "./lib/auth-context";
import { DesignSystemProvider } from "./lib/design-system-provider";
import App from "./App";

import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "./index.css";

initI18n("zh");
clearLegacyTokens();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function ReactApp() {
  return (
    <React.StrictMode>
      <DesignSystemProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <App />
          </AuthProvider>
        </QueryClientProvider>
      </DesignSystemProvider>
    </React.StrictMode>
  );
}
