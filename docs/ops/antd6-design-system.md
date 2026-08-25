# SoyMutDB Ant Design 6 design system

**Status:** implementation baseline and acceptance contract (2026-08-24)

This document records the Ant Design 6 rules used by the public portal and Admin console. It is deliberately an implementation contract, not a claim that a dependency version alone modernizes the UI.

## 1. Official references

- [Design values](https://ant.design/docs/spec/values)
- [Colors](https://ant.design/docs/spec/colors)
- [Visual](https://ant.design/docs/spec/visual)
- [Motion](https://ant.design/docs/spec/motion)
- [Design principles](https://ant.design/docs/spec/introduce)
- [React introduction / CLI workflow](https://ant.design/docs/react/introduce)
- [ConfigProvider](https://ant.design/components/config-provider)
- [Customize theme](https://ant.design/docs/react/customize-theme)
- [Button](https://ant.design/components/button)
- [Form](https://ant.design/components/form)
- [Table](https://ant.design/components/table)
- [Card](https://ant.design/components/card)
- [Modal](https://ant.design/components/modal)

The repository pins Ant Design `6.6.1` through the workspace catalog. Imports must go through the explicit facades `apps/web/src/lib/antd.ts` and `apps/admin/src/lib/antd.ts` unless a documented native semantic element is more appropriate (for example, a data table's `thead`/`tbody`).

## 2. Token and value contract

| Principle | Repository contract | Evidence / owner |
|---|---|---|
| Color is semantic, not page-local | Use `primary`, `success`, `warning`, `error`, `border`, `background`, and foreground tokens. Do not introduce a new arbitrary brand color for a component. | `apps/web/src/index.css`; `apps/web/src/lib/design-system-provider.tsx`; `apps/admin/src/lib/antd-theme.ts` |
| Consistent spacing | Prefer the AntD spacing scale and the existing utility scale (`gap-2/3/4`, `p-4/5/6`) rather than one-off pixel values. | Public/Admin component reviews |
| Consistent control values | AntD `small`, `middle`, `large` map to intent; no legacy `variant`/`size="sm"` wrapper props remain in Admin application code. | `rg` audit, Admin tsc/build |
| Typography hierarchy | Use `Typography.Title`, `Typography.Text`, `Form` labels and semantic headings; body copy must not be simulated with a heading level. | Web/Admin direct-import batches |
| Surface hierarchy | Use AntD `Card`, `Modal`, `Empty`, `Table`, `Tag` and `Button` with tokens; avoid rebuilding their primitives in an application compatibility layer. | Admin `admin-ui` consumer audit |
| Focus and touch | Interactive targets are at least 24px on desktop and approximately 44px on mobile; visible focus rings remain mandatory. | `apps/web/src/index.css`; `e2e/visual-artifacts/20260824T150817Z/report.json` |

## 3. ConfigProvider boundaries

- Public web: `apps/web/src/lib/design-system-provider.tsx` is the single global AntD boundary. It supplies locale, light/dark algorithm, token theme and motion decision.
- Admin: `apps/admin/src/lib/design-system-provider.tsx` is the single global boundary. It supplies locale, `componentSize="middle"`, `variant="outlined"`, theme tokens from `apps/admin/src/lib/antd-theme.ts`, and the AntD `App` context.
- Do not add route-local providers to compensate for a missing global token. A local provider is allowed only for an intentional isolated preview and must be labelled as such.

## 4. Motion contract

Motion has three effective states: `standard`, `minimal`, and `off`.

- `prefers-reduced-motion: reduce` always resolves to `off`.
- Save-data, low-resource devices and the Admin motion policy can resolve to `minimal`.
- `off` disables AntD motion through the theme token and disables custom transitions/animation in CSS.
- `minimal` keeps state-change feedback but uses short durations.
- New animation must have a reduced-motion branch; do not use an unbounded looping animation for information only.

Implementation and tests:

- `apps/web/src/lib/animation-context.tsx`
- `apps/web/src/lib/motion-prefs.ts`
- `apps/web/src/lib/design-system-provider.tsx`
- `apps/admin/src/lib/motion-policy.ts`
- `apps/admin/src/lib/motion-policy.test.ts`
- `apps/admin/src/lib/antd-theme.ts`
- `apps/admin/src/lib/antd-theme.test.ts`
- `apps/web/src/index.css` and `apps/admin/src/index.css` reduced-motion media rules

## 5. Component and import rules

1. Use the official AntD component API (`type`, `danger`, `size`, `htmlType`, `color`, `options`, `onChange`) rather than the removed compatibility API (`variant`, `SelectTrigger`, `CardContent`, `PageHeader`, etc.).
2. Use `@ant-design/icons` icons and mark decorative icons `aria-hidden` when a button has an explicit accessible name.
3. Use native semantic table elements where the table is custom and data behavior is owned by the component; use AntD `Pagination` for pagination behavior.
4. Do not import `admin-ui` from application source. The final audit must show zero matches for:

   ```bash
   rg -n 'from ["\x27](?:@/|\.\.?/)+lib/admin-ui["\x27]' apps/admin/src
   rg -n 'lucide-react' apps/admin/src
   ```

5. The former `apps/admin/src/lib/admin-ui.tsx` compatibility implementation is not an acceptable end state. Once test-only mocks/contracts are migrated, it must be removed.

## 6. Acceptance commands

```bash
cd /mnt/data02/T25ronglin/code/web
./node_modules/.bin/tsc --noEmit -p apps/web/tsconfig.json
./node_modules/.bin/tsc --noEmit -p apps/admin/tsconfig.json
cd apps/admin && ./node_modules/.bin/vitest run
cd apps/admin && ./node_modules/.bin/vite build
cd /mnt/data02/T25ronglin/code/web
cd e2e && npm run test:visual
```

The public visual gate covers `/`, `/search/genes`, `/search/location`, `/search/gbrowse`, and `/blast` at 1440x900, 1024x768, and 390x844. The second-round evidence at `e2e/visual-artifacts/20260824T150817Z/report.json` has 15/15 passing metrics and `undersized=0`; the related acceptance record is `docs/ops/evidence/visual-layout-t49-20260824T150817Z.md`.

## 7. Known boundary

Visual/static acceptance does not prove real Wm82 data, submitted search result correctness, or an external JBrowse staging iframe. Those remain environment/data gates in `docs/ops/acceptance-current-state.md`; this document must not be used to turn a Demo or virtual-data run into a production claim.
