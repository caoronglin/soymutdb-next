# =====================================================================
# Shared security-header fragment — include at BOTH server and location level
# =====================================================================
# nginx inherits `add_header` from the enclosing level ONLY when the inner level
# declares no `add_header` of its own. Every location below that sets any header
# (a cache-control, a CORS header, a Content-Type) therefore DROPS the server's
# entire security-header set unless it includes this fragment explicitly. That
# is not a hypothetical: `/api/`, `/data/`, `/samples/`, the hashed-asset and
# static-asset regexes, and the `@ratelimit` error location all set headers, and
# the SPA `location /` in the three container configs did too — so the responses
# that most needed `nosniff` and framing protection were the ones without it.
#
# This file must keep the `.inc` extension. `infra/nginx/nginx.conf` loads
# `include /etc/nginx/conf.d/*.conf;`, so a `.conf` name here would be parsed as
# a server block at the http level and fail `nginx -t` with
# `"add_header" directive is not allowed here`.
#
# ---------------------------------------------------------------------
# The CSP below is the DEV / SELF-HOSTED nginx literal, and it is deliberately
# NOT the policy the production HTML ships with:
#   * Production portal/JBrowse HTML is served by Cloudflare Pages or GitHub
#     Pages. Its policy is generated at build time by
#     `apps/web/scripts/finalize-csp.ts` from `buildCsp()` — with exact API /
#     JBrowse origins and per-page inline-script hashes.
#   * This fragment only serves HTML on the local/development Compose path and
#     on self-hosted nginx, where the proxy target is arbitrary, so
#     `connect-src 'self' https:` and `script-src 'unsafe-inline'` are kept.
#   * `/api/`, `/data/`, `/track.gif`, … are not HTML, so carrying this CSP on
#     them is inert; what they need from this fragment is `nosniff`.
#
# Directives that MUST stay byte-identical to the generated policy (asserted by
# scripts/check_nginx_security_headers.py): default-src, style-src, img-src,
# font-src, base-uri, form-action, frame-ancestors, object-src, worker-src.
# Directives allowed to differ, and why, are listed in
# docs/ops/static-hosting-security.md.
#
# `media-src` is intentionally absent: the portal has no <video>/<audio> and
# `buildCsp()` emits no such directive, so adding it here would break the
# directive-set parity the gate checks.
# ---------------------------------------------------------------------
add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https:; frame-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; object-src 'none'; worker-src 'self' blob:" always;
add_header Strict-Transport-Security $hsts_header_value always;
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
