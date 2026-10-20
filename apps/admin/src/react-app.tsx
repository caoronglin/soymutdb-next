import * as React from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { initI18n } from "@soymutdb/i18n";
import { clearLegacyTokens } from "@soymutdb/api-client";
import { AuthProvider } from "./lib/auth-context";
import { DesignSystemProvider } from "./lib/design-system-provider";
import { createQueryClient } from "./lib/query-client";
import App from "./App";

import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "./index.css";

initI18n("zh");
clearLegacyTokens();

const queryClient = createQueryClient();

/**
 * Announce the React handoff on `<html data-app-ready>`.
 *
 * Umi prerenders inert markup; browser suites must wait for this boundary
 * before interacting (the public portal's `react-app.tsx` does the same).
 * Without it an admin artifact test can only poll for markup that was never
 * interactive.
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
      <DesignSystemProvider>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <AppReadySignal />
            <App />
          </AuthProvider>
        </QueryClientProvider>
      </DesignSystemProvider>
    </React.StrictMode>
  );
}
