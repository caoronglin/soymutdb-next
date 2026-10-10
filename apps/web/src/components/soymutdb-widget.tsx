/**
 * SoyMutDbWidget — renders a server-rendered widget fragment as a React component.
 *
 * The portal embeds widgets served by `GET /api/v1/widget/{name}`
 * (`apps/api/app/widgets/router.py:231`). The response is an HTML fragment
 * produced by a Jinja2 template from a registered data source — for `/sra` that
 * is `sra_run` (`apps/api/app/widgets/data_sources/sra.py`), whose template
 * interpolates values taken from NCBI's runinfo CSV. Parameters travel as a
 * JSON-encoded `params` query parameter.
 *
 * ## Sanitization
 *
 * The API already runs every fragment through bleach
 * (`apps/api/app/widgets/engine.py:sanitize_html`) before returning it. That is
 * not a substitute for sanitizing here: it is a different trust domain, and this
 * client cannot verify which template produced the bytes it received, nor that
 * the response came from the API at all. So the fragment is sanitized with
 * DOMPurify immediately before insertion, and nothing from the response other
 * than the sanitized string is ever handed to the DOM. No user- or
 * server-controlled string is interpolated into markup anywhere in this file:
 * error detail is rendered as a React text child, which React escapes.
 *
 * ## Why a component and not the old custom element
 *
 * `<soymutdb-widget>` (deleted in 25c32e499) was a 420-line lazy-loading custom
 * element with Shadow DOM. As a plain component:
 *
 * - nothing depends on module side-effect ordering for `customElements.define`,
 *   which is exactly the class of breakage
 *   `scripts/test_custom_element_registration_contracts.py` now fails the build
 *   for — a JSX tag that exists but is never registered renders as an inert box
 *   under a heading that promises content;
 * - the fragment is styleable by the portal's own utilities, with no shadow
 *   boundary to keep inherited CSS out;
 * - the fetch is abortable through a real effect, and a failed request renders an
 *   explicit error with a retry control. An empty response is treated as a
 *   failure too: the repo rule is "show an error, never fake success", so a blank
 *   box must never appear under this card's heading.
 */
import * as React from "react";
import { useTranslation } from "react-i18next";
import DOMPurify from "dompurify";
import { Alert, Button, Skeleton } from "@/lib/antd";
import { ReloadOutlined } from "@ant-design/icons";
import { apiBaseUrl } from "@soymutdb/api-client";

/** JSON-encoded into the `params` query parameter; the API parses it per widget. */
export type SoyMutDbWidgetParams = Record<string, unknown>;

export interface SoyMutDbWidgetProps {
  /** Widget name, e.g. `sra_run`. Percent-encoded into `/widget/{name}`. */
  name: string;
  /** Widget parameters, JSON-encoded into `?params=`. */
  params?: SoyMutDbWidgetParams;
  /** Extra classes for the wrapper element. */
  className?: string;
}

type WidgetState =
  | { status: "loading" }
  | { status: "loaded"; html: string }
  /** `detail` is a transport-level string (status line / fetch failure); null means
   *  the request succeeded but produced nothing renderable. */
  | { status: "error"; detail: string | null };

/**
 * DOMPurify configuration.
 *
 * `USE_PROFILES: { html: true }` keeps DOMPurify's curated HTML allow-list, which
 * already excludes `script`, inline event handlers and `javascript:` URLs — the
 * fragment is never trusted enough to widen that surface. The FORBID lists restate
 * that intent for the interactive tags the allow-list would otherwise admit: the
 * widget templates are for rendering, not for accepting input or embedding
 * foreign documents. `target` is allowed because the templates link out to NCBI
 * with `target="_blank"`; `rel="noopener noreferrer"` is added below.
 */
const SANITIZE_CONFIG = {
  USE_PROFILES: { html: true },
  ADD_ATTR: ["target"],
  FORBID_TAGS: ["script", "style", "iframe", "object", "embed", "form", "input", "button", "textarea", "select"],
  FORBID_ATTR: ["onerror", "onload", "onclick", "onfocus", "onblur", "onmouseover", "onanimationstart"],
};

/**
 * Sanitize a widget fragment for insertion.
 *
 * Exported so the sanitization boundary is directly testable rather than only
 * observable through a rendered tree.
 */
export function sanitizeWidgetHtml(html: string): string {
  const sanitized = DOMPurify.sanitize(html, SANITIZE_CONFIG);
  // Hardening pass, mirroring the markdown viewer: every outbound link that opens
  // a new context gets `rel="noopener noreferrer"`. Applied through the DOM API on
  // an inert `<template>` (never by string concatenation), and it can only add
  // attributes — nothing the sanitizer removed comes back.
  const template = document.createElement("template");
  template.innerHTML = sanitized;
  template.content.querySelectorAll('a[target="_blank"]').forEach((link) => {
    link.setAttribute("rel", "noopener noreferrer");
  });
  return template.innerHTML;
}

/**
 * Resolve `GET {apiBaseUrl}/widget/{name}?params=<json>` as an absolute URL.
 *
 * `apiBaseUrl` is `/api/v1` unless `VITE_API_BASE_URL` points at another origin,
 * and it may be given with a trailing slash, so it is normalised here. An absolute
 * base is preserved; a relative one is resolved against the current origin, which
 * is what `fetch` requires.
 */
function buildWidgetUrl(name: string, paramsJson: string): string {
  const base = (apiBaseUrl ?? "").trim().replace(/\/+$/, "") || "/api/v1";
  const path = `${base}/widget/${encodeURIComponent(name)}`;
  const url = /^https?:\/\//i.test(base) ? new URL(path) : new URL(path, window.location.origin);
  url.searchParams.set("params", paramsJson);
  return url.toString();
}

function isAbortError(error: unknown): boolean {
  return (error as { name?: string } | null | undefined)?.name === "AbortError";
}

/**
 * Fetches one server-rendered widget and renders its sanitized HTML.
 *
 * States are exhaustive on purpose: loading, sanitized content, or a visible
 * error with a retry control. There is no path that renders nothing.
 */
export function SoyMutDbWidget({ name, params, className }: SoyMutDbWidgetProps) {
  const { t } = useTranslation();
  const [reloadToken, setReloadToken] = React.useState(0);
  const [state, setState] = React.useState<WidgetState>({ status: "loading" });

  // Call sites pass `params` as an inline object literal, so it must not be an
  // effect dependency by identity. Its JSON form is a stable primitive that changes
  // exactly when the parameters change.
  const paramsJson = JSON.stringify(params ?? {});

  React.useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    void (async () => {
      try {
        const response = await fetch(buildWidgetUrl(name, paramsJson), {
          headers: { Accept: "text/html" },
          signal: controller.signal,
        });
        if (!response.ok) {
          // The API answers 403/404 with an HTML error fragment body. The transport
          // status is the honest thing to report, and the body is discarded instead
          // of being rendered as if it were widget content.
          throw new Error(`HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`);
        }
        const html = sanitizeWidgetHtml(await response.text());
        if (controller.signal.aborted) return;
        // A 200 with no renderable fragment would be a silent blank under the
        // card heading, so it is reported as a failure instead.
        if (!html.trim()) {
          setState({ status: "error", detail: null });
          return;
        }
        setState({ status: "loaded", html });
      } catch (error) {
        if (isAbortError(error) || controller.signal.aborted) return;
        setState({ status: "error", detail: error instanceof Error ? error.message : String(error) });
      }
    })();

    return () => controller.abort();
  }, [name, paramsJson, reloadToken]);

  return (
    <div data-testid={`soymutdb-widget-${name}`} className={className ? `soymutdb-widget ${className}` : "soymutdb-widget"}>
      {state.status === "loading" && (
        <div role="status" aria-live="polite" aria-label={t("common.loading")} data-testid="soymutdb-widget-loading">
          <Skeleton active title={false} paragraph={{ rows: 4 }} />
        </div>
      )}

      {state.status === "error" && (
        <div data-testid="soymutdb-widget-error">
          <Alert
            type="error"
            showIcon
            title={t("common.error")}
            description={state.detail ?? t("common.noData")}
            action={
              <Button
                size="small"
                icon={<ReloadOutlined aria-hidden />}
                onClick={() => setReloadToken((token) => token + 1)}
              >
                {t("common.retry")}
              </Button>
            }
          />
        </div>
      )}

      {state.status === "loaded" && (
        <div
          data-testid="soymutdb-widget-content"
          className="text-sm [&_a]:text-primary [&_a]:underline-offset-2 [&_a:hover]:underline [&_h3]:text-base [&_h3]:font-semibold"
          // Sole insertion point for server HTML, and only ever sanitized output.
          dangerouslySetInnerHTML={{ __html: state.html }}
        />
      )}
    </div>
  );
}