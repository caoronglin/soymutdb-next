import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n } from "@soymutdb/i18n";
import { clearLegacyTokens } from "@soymutdb/api-client";
import { AuthProvider } from "./lib/auth-context";
import { DesignSystemProvider } from "./lib/design-system-provider";
import App from "./App";

// Fonts must be imported as JS modules, not via `@import` in index.css:
// Tailwind v4 inlines the fontsource CSS but leaves its `url(./files/…)`
// relative paths untouched, so the emitted CSS points at assets/files/… which
// is never written to disk (the mono font 404s). Imported here, Vite resolves
// each URL against the CSS module's own path and emits hashed font files.
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";

import "./index.css";

// Initialise i18next before rendering. Admin defaults to Chinese.
initI18n("zh");

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
