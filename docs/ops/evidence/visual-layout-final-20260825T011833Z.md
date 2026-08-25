# Final public-site visual smoke acceptance

- Build: demo mode with `VITE_BASE_URL=/soymutdb-next/`, API/JBrowse test origins.
- Command: `cd e2e && npm run test:visual`
- Evidence: `e2e/visual-artifacts/20260825T011833Z/report.json` plus 15 PNG screenshots.
- Routes: `/`, `/search/genes`, `/search/location`, `/search/gbrowse`, `/blast`.
- Viewports: 1440x900, 1024x768, 390x844.
- Result: **15/15 passed**.
- Metrics: all pages had no horizontal overflow; main content/headings were visible; body text was non-empty; `undersized=0` for all 15 metrics.
- Homepage structure checked by the evidence run: independent Hero/search block first, latest-news + carousel below it, then tool/resource bands.

This is a static/demo visual smoke gate. It does not claim real Wm82 result data, external JBrowse staging availability, or production deployment readiness.
