import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { initI18n, detectLanguage } from "@soymutdb/i18n";
import App from "./App";
import "./index.css";

// Initialise i18next before rendering.
initI18n(detectLanguage());

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
            <App />
        </QueryClientProvider>
    </StrictMode>,
);
