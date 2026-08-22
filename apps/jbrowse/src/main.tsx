import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n, detectLanguage } from "@soymutdb/i18n";
import { addJbrowseI18nResources } from "./i18n-extra";
import { DesignSystemProvider } from "./design-system-provider";
import App from "./App";
import "./index.css";

// Initialise i18next before rendering, then merge in app-only resources.
initI18n(detectLanguage());
addJbrowseI18nResources();

// React Query client with sensible defaults for the genome browser.
const queryClient = new QueryClient({
    defaultOptions: {
        queries: {
            staleTime: 5 * 60 * 1000,
            gcTime: 30 * 60 * 1000,
            retry: 2,
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
        <QueryClientProvider client={queryClient}>
            <DesignSystemProvider>
                <App />
            </DesignSystemProvider>
        </QueryClientProvider>
    </StrictMode>,
);
