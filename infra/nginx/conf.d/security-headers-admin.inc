# =====================================================================
# Shared security-header fragment — ADMIN surface
# =====================================================================
# Same six header NAMES as `security-headers.inc`, with the stricter values the
# admin console requires. It exists as a second file because nginx emits every
# `add_header` with a given name that it sees at the active level: "include the
# portal fragment, then override X-Frame-Options" produces TWO
# X-Frame-Options headers and TWO CSP headers, and browsers do not resolve that
# the way it reads (a duplicate CSP is an intersection, a duplicate XFO is
# undefined behaviour). One fragment per surface, never an override chain.
#
# Differences from the portal fragment, and why:
#   * `X-Frame-Options: DENY` / `frame-ancestors 'none'` — admin is never
#     embedded, not even by itself.
#   * `Referrer-Policy: no-referrer` — admin URLs must not leak to anything.
#   * `script-src 'self'` with no `'unsafe-inline'` — the admin entry HTML
#     contains no inline script (verified: only the hashed module entry), so the
#     weaker portal policy is unnecessary here.
#   * `worker-src 'self'` (no `blob:`): the console spawns no blob workers.
#     Stated explicitly rather than left to the `default-src` fallback so the
#     directive set matches the other fragments and the parity gate stays
#     meaningful.
#
# This text mirrors `apps/admin/public/_headers` (the Cloudflare Pages path) so
# the container and the static-hosting path agree. Keep the two in sync;
# scripts/check_artifact_headers.py compares them.
#
# Must keep the `.inc` extension: `include /etc/nginx/conf.d/*.conf;` would
# parse a `.conf` file as a server block and fail `nginx -t`.
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'; object-src 'none'; worker-src 'self'; frame-ancestors 'none'" always;
add_header Strict-Transport-Security $hsts_header_value always;
add_header X-Frame-Options "DENY" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer" always;
add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;
