/**
 * Genome browser route — JBrowse 2 embed.
 *
 * JBrowse 2 is loaded via an iframe. The URL is configurable via the
 * VITE_JBROWSE_URL env var (defaults to the hosted instance). A loading
 * state with a fallback overlay is shown while the iframe loads, and a
 * timeout-based fallback message appears if the service is unreachable.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Microscope, ExternalLink, Search, AlertCircle, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Input, Button } from "@soymutdb/ui";
import { FadeUp } from "../components/route-motion";
import { SOYBEAN_CHROMOSOMES } from "../lib/format";

export const Route = createFileRoute("/browser")({
  component: BrowserComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: String(search.assembly ?? "Wm82.a4.v1"),
    loc: String(search.loc ?? "chr01"),
  }),
});

// Configurable JBrowse URL — defaults to the local JBrowse app (port 5175).
// In production, set VITE_JBROWSE_URL to the deployed JBrowse instance URL.
const JBROWSE_BASE = import.meta.env.VITE_JBROWSE_URL ?? "http://localhost:5175";

function BrowserComponent() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const navigate = useNavigate();
  const [locInput, setLocInput] = React.useState(search.loc);
  const [iframeLoaded, setIframeLoaded] = React.useState(false);
  const [showFallback, setShowFallback] = React.useState(false);

  React.useEffect(() => setLocInput(search.loc), [search.loc]);

  const jbrowseSrc = `${JBROWSE_BASE}/?assembly=${encodeURIComponent(search.assembly)}&loc=${encodeURIComponent(search.loc)}`;

  // Reset state when the URL changes (new location/assembly)
  React.useEffect(() => {
    setIframeLoaded(false);
    setShowFallback(false);
    const timer = setTimeout(() => {
      if (!iframeLoaded) setShowFallback(true);
    }, 8000);
    return () => clearTimeout(timer);
  }, [jbrowseSrc]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="eyebrow">{t("browser.title")}</p>
            <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("browser.subtitle")}</h1>
          </div>
          <Button variant="outline" size="sm" asChild>
            <a href={jbrowseSrc} target="_blank" rel="noopener noreferrer">
              <ExternalLink className="size-4" aria-hidden />
              Open in new tab
            </a>
          </Button>
        </div>
      </FadeUp>

      <Card className="mt-10">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Microscope className="size-5 text-primary" aria-hidden />
            {t("browser.title")}
          </CardTitle>
          <CardDescription>{t("browser.loading")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const next = locInput.trim();
              if (next) navigate({ to: "/browser", search: { ...search, loc: next } });
            }}
            className="mb-4 flex gap-2"
            role="search"
          >
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
              <Input
                value={locInput}
                onChange={(e) => setLocInput(e.target.value)}
                placeholder={t("browser.searchPlaceholder")}
                aria-label={t("browser.location")}
                className="h-12 pl-9"
              />
            </div>
            <Button type="submit">{t("browser.go")}</Button>
          </form>

          <div className="flex flex-wrap gap-1">
            {SOYBEAN_CHROMOSOMES.slice(0, 10).map((c) => (
              <Button
                key={c}
                variant={search.loc === c ? "default" : "outline"}
                size="sm"
                className="px-2.5 font-mono text-xs"
                onClick={() => navigate({ to: "/browser", search: { ...search, loc: c } })}
              >
                {c.replace("chr", "")}
              </Button>
            ))}
          </div>

          <div className="relative mt-4 overflow-hidden rounded-lg border">
            {/* Loading overlay — shown until iframe fires onLoad */}
            {!iframeLoaded && !showFallback && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-muted/50">
                <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
                <p className="mt-3 text-sm text-muted-foreground">{t("browser.loading")}</p>
              </div>
            )}

            {/* Fallback overlay — shown when iframe fails to load within 8s */}
            {showFallback && !iframeLoaded && (
              <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-card p-8 text-center">
                <AlertCircle className="size-10 text-muted-foreground" aria-hidden />
                <h3 className="mt-4 font-display text-lg font-semibold">Genome browser unavailable</h3>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  The JBrowse 2 genome browser service at <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{JBROWSE_BASE}</code> could not be reached.
                  This may be a temporary connectivity issue or the service may not be deployed yet.
                </p>
                <div className="mt-5 flex gap-3">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setShowFallback(false);
                      setIframeLoaded(false);
                      // Force iframe reload by toggling key
                      const iframe = document.querySelector<HTMLIFrameElement>("#jbrowse-iframe");
                      if (iframe) iframe.src = jbrowseSrc;
                    }}
                  >
                    <Loader2 className="size-4" aria-hidden />
                    Retry
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <a href={jbrowseSrc} target="_blank" rel="noopener noreferrer">
                      <ExternalLink className="size-4" aria-hidden />
                      Open directly
                    </a>
                  </Button>
                </div>
              </div>
            )}

            <iframe
              id="jbrowse-iframe"
              src={jbrowseSrc}
              title="JBrowse 2 genome browser"
              className="h-[600px] w-full"
              loading="lazy"
              allow="clipboard-read; clipboard-write"
              onLoad={() => setIframeLoaded(true)}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
