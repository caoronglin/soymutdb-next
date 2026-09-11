# S1 · Tauri Cross-site Authentication Spike

## Scope

This is the M0 go/no-go spike from `desktop-client-plan.md §4`. It tests the recommended MVP option B: a Tauri WebView calls the remote API with `credentials: "include"`, while the API emits an HttpOnly `SameSite=None; Secure` refresh cookie and explicitly trusts the WebView origin.

No desktop/Tauri scaffold currently exists in this repository. The harness therefore proves the **backend contract** first; it cannot claim that a packaged WKWebView accepts or emits `tauri://localhost`.

## Preconditions

- A disposable account on a non-production, HTTPS API deployment.
- Deployment configuration includes the origin being tested in `SOYMUTDB_CORS_ORIGINS`:
  - Windows/Linux: `http://tauri.localhost`
  - macOS: `tauri://localhost`
- `SOYMUTDB_REFRESH_COOKIE_SAMESITE=none` and `SOYMUTDB_REFRESH_COOKIE_SECURE=true`.
- Credentials supplied only as temporary process environment variables; do not put them in shell history or files.

## Execute

```bash
export SOYMUTDB_SPIKE_USERNAME="spike-user@example.org"
export SOYMUTDB_SPIKE_PASSWORD="…"
python3 scripts/desktop_auth_spike.py \
  --api-url https://api-staging.example.org \
  --origin tauri://localhost
```

Run once for `http://tauri.localhost` and once for `tauri://localhost` against the same staging deployment. The command never prints credentials or refresh-token values.

## Automated pass/fail criteria

| Check | Pass condition | Failure consequence |
| --- | --- | --- |
| CORS preflight | HTTP 200/204, exact `Access-Control-Allow-Origin`, and `Access-Control-Allow-Credentials: true` | Option B is **NO-GO** for that origin. |
| Login cookie | Login returns 200 and refresh cookie has `HttpOnly`, `Secure`, `SameSite=None` | Option B is **NO-GO**; correct deployment config before retest. |
| Cookie refresh | Refresh with the issued cookie and tested Origin returns 200 and rotates a cookie with the same flags | Option B is **NO-GO**; investigate CSRF/CORS/cookie path. |

## Required manual macOS evidence

Automated HTTP requests cannot emulate a WKWebView custom scheme or browser cookie policy. Before declaring S1 passed, create the minimal Tauri 2 shell outside this repo or add it in a dedicated desktop change, then on **macOS** record:

1. login from `tauri://localhost` succeeds;
2. after app relaunch, boot-time `/auth/refresh` succeeds without re-entering credentials;
3. DevTools/network shows the request Origin is `tauri://localhost` and the response has the exact credentialed CORS headers;
4. a foreign Origin fails CSRF/CORS checks;
5. repeat on Windows/Linux with `http://tauri.localhost`.

## Evidence recorded in this workspace

A local ASGI configuration check was run with both desktop origins, `SameSite=none`, and `Secure=true`. It verified exact credentialed CORS preflight responses for both origins and a refresh `Set-Cookie` containing `HttpOnly`, `Secure`, `SameSite=None`, and `Path=/api/v1/auth`.

This is configuration evidence only: it did not authenticate a real user, involve a deployed HTTPS endpoint, or run a Tauri/WKWebView.

## Go/no-go decision

- **GO (Option B MVP):** automated contract passes for both origins **and** packaged macOS/Windows-or-Linux evidence passes.
- **NO-GO / switch to Option A:** macOS does not emit a trustworthy Origin, refuses the cookie, or fails session restore. Do not introduce the local proxy option C as a workaround.
- Current state: **backend configuration is compatible; no live or WebView evidence, therefore no decision.**