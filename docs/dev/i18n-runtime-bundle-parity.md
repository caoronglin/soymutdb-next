# Runtime bundle parity in the i18n key guard

## The defect

`apps/web/src/lib/i18n.ts` composes the effective catalog at runtime from four
sources: the shared `common.json` (en/zh) plus three portal-only overlays from
`apps/web/src/lib/i18n-resources.ts` (`EXTRA_RESOURCES`, `TOOLS_RESOURCES`,
`HOME_RESOURCES`), merged with `addResourceBundle(..., deep=true)`.

`scripts/check-admin-i18n-keys.mjs` is wired into `verify-frontend-artifacts.sh`
and only ever read `common.json`. When #117 shipped
`apps/web/src/routes/tools/sequence.tsx` with its 87 `tools.sequence.*` keys
registered in `TOOLS_RESOURCES`, the guard reported 178 problems
(87 keys x 2 locales, plus 4 dynamic prefixes) — a **false positive**: the UI
rendered the right copy, but the gate went red. The same blind spot exists in
the unwired `scripts/test_locale_language_purity.py`.

Two guards, one missing source of truth. Adding the keys to `common.json` would
silence both while duplicating 106 runtime keys into a second catalog that must
be kept in sync by hand — the exact drift shape this repository keeps hitting.

## The fix

The guard now derives its overlay composition from `i18n.ts` itself: it reads
the `Object.entries(...RESOURCES)` calls in the bootstrap and merges those
exports on top of each locale's `common.json`. Node 26 strips the TypeScript
type annotations on import, so no build, workspace install, or second hardcoded
resource list is needed. The ablation harness covers the positive case
(overlay-only key passes), the negative case (dropping an overlay from
`i18n.ts` makes it fail again), and the dynamic-prefix form.

Consequences:

- A new runtime bundle is visible to the guard as soon as `i18n.ts` merges it.
- A bundle the app stops merging stops satisfying the guard — the guard cannot
  drift into accepting keys that never render.
- A renamed/missing export fails with a named message, not an import stack trace.

## Scope

This fixes the **wired** frontend gate only. The unwired Python purity test is
out of scope: reaching it requires a separate decision about which contracts
suite should collect it (it is not in `smoke.sh`'s `tests[]`). Neither guard was
changed to author catalog entries; `common.json` stays the shared baseline.
