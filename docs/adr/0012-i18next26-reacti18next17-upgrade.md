# ADR-0012: upgrade i18next 24 → 26 and react-i18next 15 → 17

Status: accepted (2026-10-18)
Context: ADR-0010 held i18next 26 / react-i18next 17; ADR-0011 took the first
upgrade (Vitest/Vite) and named i18next as the next item. All three apps and
`packages/i18n` share one i18next singleton built from
`packages/i18n-core`'s `buildBaseI18nOptions()`, so the upgrade is small in
surface but touches every rendered string.

Decision: upgrade in this release.

Breaking changes that apply (from the upstream i18next v26 and react-i18next 17
changelogs):

* i18next 26 **removed `initImmediate`** (renamed to `initAsync` in v24; the
  old key is no longer accepted). `buildBaseI18nOptions()` now sets
  `initAsync: false` — the apps load all catalogs synchronously from bundled
  resources, so they never wanted deferred init.
* i18next 26 removed the legacy `interpolation: { format: fn }` option. This
  repository never used it (the only `format` occurrences are interpolation
  *variables* such as `t("...", { format: label })`); no code change needed.
* i18next 26 removed the console support notice and its suppression hooks — no
  repository code referenced them.
* i18next 25 changed `changeLanguage()` resolution (`getBestMatchFromCodes`,
  script fallback) and the value of `i18n.language` during the switch. The
  language switcher persists the choice and reads `i18n.language` after the
  change resolves; the locale-guard and language-switch tests cover it.
* react-i18next 17 requires **i18next >= 26.2** (satisfied: 26.4.7) and
  TypeScript ^5 (satisfied: 5.9.3); it is the only upstream consumer that
  constrains the pair.

Changes:

* `apps/web`, `apps/admin`, `apps/jbrowse`, `packages/i18n`:
  `i18next ^24.2.0 → ^26.4.7`, `react-i18next ^15.4.0 → ^17.0.21`.
* `pnpm-workspace.yaml` `minimumReleaseAgeExclude` gains
  `react-i18next@17.0.21`: pnpm 12 refuses packages younger than its
  supply-chain window and the current release is inside it. This is the same
  explicit, reviewed exemption pattern already used for the pinned
  ProComponents/AntD/Umi versions — it names one exact version, not a range.
* Lockfile refreshed; frozen-lockfile install passes.

Evidence (local, all green after the change):

* `turbo run lint typecheck`: 25/25 tasks.
* `turbo run test`: 11/11 tasks, **1071 tests** (web 373, admin 172,
  api-client 184, genome-data 121, charts 84, shared 49, genome-view 43,
  genome-view-model 23, i18n-core 11, query-keys 11).
* i18n guards: locale key parity (check:locale-keys), locale-language purity
  (5 passed), React visible-text scanner (0 tracked strings).
* Production artifacts: web external + internal and admin build; artifact
  gates (headers, production scan, dual-site isolation, chart/bundle budgets,
  static smoke, browser a11y) pass — recorded in `docs/dev/project-status.md`.

Consequences: all three surfaces stay on one i18next major and share the same
catalogs; the next held major is zod 4 / pdfjs 6 per ADR-0010's order. Rollback
is the four manifest pins plus the lockfile; no persisted data is involved.
