import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n, detectLanguage } from "@soymutdb/i18n";
import { clearLegacyTokens } from "@soymutdb/api-client";
import { AuthProvider } from "./lib/auth-context";
import { DesignSystemProvider } from "./lib/design-system-provider";
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

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <DesignSystemProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </QueryClientProvider>
    </DesignSystemProvider>
  </StrictMode>,
);
