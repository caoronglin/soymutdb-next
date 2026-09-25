# ADR-0008: no Vue equivalent for the `/antd-pilot` route

Status: accepted
Context: the React portal had an `/antd-pilot` route
(`apps/web/src/routes/_antd-pilot.tsx`), an internal page used while the AntD
design system was being evaluated. It rendered component samples with no data
and no user workflow, and nothing in the portal, the admin console or the
navigation linked to it.

Decision: the Vue portal does not carry that route. Its two purposes are already
served by permanent artefacts:

* the design-system contract lives in `@soymutdb/ui-vue` (the only module allowed
  to import Antdv Next) and is guarded by that package's facade test;
* the visual language lives in the Tailwind token set and the shared design
  tokens in `packages/ui-vue/src/design-tokens.ts`.

An unlinked sample page is not a contract — it is a page that drifts. If a
component gallery is wanted later, it belongs in Storybook-style tooling or a
documented design page, not as a public route in the portal.

Consequences: one fewer public route; the AntD evaluation history remains in git
history and in `docs/ops/antd6-design-system.md`.
