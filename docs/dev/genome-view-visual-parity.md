# Genome-view visual parity with the React design system

Status: implemented (styles only).
Scope: `packages/genome-view/src/components/**` scoped styles.
Baselines read:

- `apps/jbrowse/src/App.tsx` — React layout/classes for the standalone browser shell.
- `apps/jbrowse/src/index.css` — `@theme` bridge + light/dark palette used by the standalone browser.
- `apps/web/src/style.css` — SoyMutDB design tokens, `@theme` type/radius scale, `@layer design` track tokens.
- `git show 25c32e499^:apps/web/src/components/genome-browser-widget.tsx` — the deleted React
  `GenomeBrowserWidget`; its Tailwind classes are the closest React reference for the track
  container, ruler strip, states and error surfaces.

No behaviour, props, emits or data flow changed: every edit is inside a `<style scoped>` block.

## 1. Extracted tokens

### 1.1 Type scale

| Token (style.css `@theme`) | Value | Line height | React reference |
| --- | --- | --- | --- |
| `--text-caption` | `0.75rem` (12px) | `1.5` | `text-xs` (summary bar, footer, state text), `.eyebrow` |
| `--text-small` | `0.875rem` (14px) | `1.55` | `text-sm` (subtitle, input, messages), `--text-small--line-height` |
| `--text-body` | `1rem` (16px) | `1.65` | base `body` |
| `--text-lg` | `1.125rem` (18px) | Tailwind `1.75rem` | brand `font-serif text-lg font-semibold text-primary`; error heading `font-serif text-lg font-semibold` |
| weight `600` | semibold | — | `font-semibold` (brand, headings, buttons, legends) |
| `--font-mono` | JetBrains Mono | — | `font-mono` (locus input, position/coordinate labels) |

### 1.2 Spacing scale (4px / Tailwind grid)

| Step | Value | React reference |
| --- | --- | --- |
| 1 | `0.25rem` | `gap-1`, `mt-1` |
| 1.5 | `0.375rem` | `py-1.5`, `gap-1.5` |
| 2 | `0.5rem` | `gap-2`, `py-2`, `px-2` |
| 2.5 | `0.625rem` | `left-2.5` |
| 3 | `0.75rem` | `gap-3`, `px-3`, `p-3` |
| 4 | `1rem` | `px-4`, `p-4` |
| 6 | `1.5rem` | `p-6` |
| 8 | `2rem` | `p-8` (loading/error placeholders) |

### 1.3 Radii and heights

| Token | Value | React reference |
| --- | --- | --- |
| `--radius-sm` | `0.375rem` (6px) | Tailwind `rounded` small surfaces; JBrowse MUI `borderRadius: 6` |
| `--radius-md` | `0.625rem` (10px) | antd `borderRadius: 10` (`createThemeConfig`), `rounded-md` |
| `--radius-lg` | `0.875rem` (14px) | `rounded-lg` for the widget/browser container |
| `--radius-xl` | `1.125rem` (18px) | `rounded-xl` (not used by track primitives) |
| micro `0.25rem` | `0.25rem` | widget `rounded` on buttons/tooltip/swatches |
| `h-9` | `2.25rem` (36px) | `App.tsx` locus `Input className="h-9 ..."` |
| compact control | `2rem` (32px) | design-system interaction floor (style.css `.ant-input { min-height: 32px }`) |
| `--ruler-height` | `1.75rem` (28px) | `@layer design` token |
| `--track-height` | `1.5rem` (24px) | `@layer design` token |

### 1.4 Borders, shadows, surfaces

| Token | Value | React reference |
| --- | --- | --- |
| `--border` | light `oklch(0.905 0.02 148)` / dark `oklch(0.30 0.02 152)` | `border-border`, hairline `1px` |
| `--input` | same as `--border` | `border-input` |
| `--shadow-sm/md/lg` | oklch-based | defined in `style.css`; the React baseline cards use `border bg-card` with no shadow — Vue tracks do the same |
| card surface | `--card` light `oklch(1 0 0)` / dark `oklch(0.195 0.018 152)` | widget outer `bg-card` |
| header strip | `--muted` at 30% | widget header `bg-muted/30`; ruler `bg-muted/20` |
| error surface | `--destructive` at 10% | `App.tsx` error placeholder `bg-destructive/10` |

### 1.5 Colour tokens

| Token | Light | Dark | Used by |
| --- | --- | --- | --- |
| `--primary` | `oklch(0.46 0.13 152)` | `oklch(0.70 0.12 151)` | plus-strand features, SNV/MNV marks, buttons, focus accent |
| `--primary-foreground` | `oklch(0.988 0.004 148)` | `oklch(0.155 0.014 152)` | primary button text |
| `--muted-foreground` | `oklch(0.48 0.028 152)` | `oklch(0.68 0.025 152)` | state text, ruler labels, legends |
| `--foreground` | `oklch(0.195 0.028 152)` | `oklch(0.955 0.01 148)` | track names, base letters, error title |
| `--background` | `oklch(0.991 0.004 148)` | `oklch(0.155 0.014 152)` | input fill |
| `--card` | `oklch(1 0 0)` | `oklch(0.195 0.018 152)` | browser container, selector, retry buttons |
| `--border` | `oklch(0.905 0.02 148)` | `oklch(0.30 0.02 152)` | separators, track frames |
| `--destructive` | `oklch(0.58 0.22 27)` | `oklch(0.62 0.22 27)` | deletion marks, error box |
| `--ring` | `oklch(0.55 0.14 152)` | `oklch(0.70 0.12 151)` | `:focus-visible` outline |
| `--chart-1` | `oklch(0.55 0.14 152)` | `oklch(0.70 0.12 151)` | quantitative bars |
| `--chart-2` | `oklch(0.66 0.12 150)` | `oklch(0.74 0.11 150)` | minus-strand features, insertions |
| `--impact-moderate` | `oklch(0.72 0.16 65)` | `oklch(0.78 0.16 65)` | structural-variant marks |

## 2. Per-component mapping

Legend: **React ref** is the class/rule in the baseline that the Vue value is aligned to.
All colours keep the `var(--token, fallback)` form and therefore follow the
`[data-theme="dark"], .dark` overrides automatically.

### 2.1 TrackRuler.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.track-ruler` | `@layer design` `--ruler-height: 28px`; widget ruler `h-6` | `height: var(--ruler-height, 1.75rem)` |
| `.track-ruler__tick` | `border` hairline | `border-left: 1px solid var(--border, oklch(0.905 0.02 148))` |
| `.track-ruler__label` | `text-xs` + `font-mono` position label; `--text-caption` | `font-size: var(--text-caption, 0.75rem)`; `line-height: var(--ruler-height, 1.75rem)`; `color: var(--muted-foreground, ...)` |

### 2.2 TrackSelector.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.track-selector` | widget header `px-3 py-2`; card panel `rounded-md border bg-card` | `padding: 0.5rem 0.75rem`; `gap: 0.25rem`; `border: 1px solid var(--border, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: var(--card, #fff)` |
| `.track-selector__legend` | `.eyebrow` (caption + uppercase) and `text-xs` | `font-size: var(--text-caption, 0.75rem)`; `font-weight: 600`; `text-transform: uppercase`; `letter-spacing: 0.08em`; `color: var(--muted-foreground, ...)` |
| `.track-selector__item` | `@layer design` `--track-height: 24px`; `gap-2` row | `min-height: var(--track-height, 1.5rem)`; `gap: 0.5rem` |
| `.track-selector__checkbox` | `size-4` (16px) control | `inline-size/block-size: 1rem`; `accent-color: var(--primary, ...)` |
| `.track-selector__name` | `text-sm` | `font-size: var(--text-small, 0.875rem)`; `color: var(--foreground, ...)` |
| `.track-selector__empty` | `text-sm text-muted-foreground` | `font-size: var(--text-small, 0.875rem)`; `color: var(--muted-foreground, ...)` |

### 2.3 LocusSearch.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.locus-search` | App.tsx form `flex items-center gap-2` | `gap: 0.5rem` |
| `.locus-search__label` | visually hidden accessible label | `position: absolute; clip-path: inset(50%)` (unchanged) |
| `.locus-search__input` | App.tsx `Input className="h-9 w-full pl-8 font-mono text-sm"`, `border-input rounded-md` | `min-height: 2.25rem`; `padding-inline: 0.625rem`; `border: 1px solid var(--input, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: var(--background, #fff)`; `font-family: var(--font-mono)`; `font-size: var(--text-small, 0.875rem)` |
| `.locus-search__button` | App.tsx `type="primary"` button in the same row | `min-height: 2.25rem`; `padding-inline: 0.875rem`; `border/background: var(--primary, ...)`; `color: var(--primary-foreground, ...)`; `font-size: var(--text-small, 0.875rem)`; `font-weight: 600` |
| `:focus-visible` (both) | global `outline: 2px solid var(--ring); outline-offset: 2px` | same |

### 2.4 FeatureTrack.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.feature-track__feature` | feature fill `--primary` / `--chart-2` / `--muted-foreground` (template) | fill untouched; `opacity 0.9 → 1` on hover |
| `.feature-track__state` | App.tsx placeholder `text-sm text-muted-foreground`; `p-4` | `padding: 1rem`; `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)`; `color: var(--muted-foreground, ...)` |

### 2.5 VariantTrack.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.variant-track__state` | `text-sm text-muted-foreground`; `p-4` | `padding: 1rem`; `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)`; `color: var(--muted-foreground, ...)` |
| `.variant-track__legend` | `.eyebrow` uppercase caption | `font-size: var(--text-caption, 0.75rem)`; `text-transform: uppercase`; `letter-spacing: 0.08em`; `color: var(--muted-foreground, ...)` |
| `.variant-track__legend-item` | `gap-1` micro row | `gap: 0.25rem` |
| `.variant-track__swatch` | widget `rounded` micro element | `0.625rem × 0.625rem`; `border-radius: 0.25rem` |
| mark fills | `--primary` (snv/mnv), `--chart-2` (ins), `--destructive` (del), `--impact-moderate` (sv) | unchanged |

### 2.6 QuantitativeTrack.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.quantitative-track__bar` | `--chart-1` | unchanged (`fill: var(--chart-1, oklch(0.55 0.14 152))`) |
| `.quantitative-track__baseline` | `--border` hairline | unchanged |
| `.quantitative-track__max` | widget tooltip `font-mono text-[10px]`; snapped to `--text-caption` | `font-family: var(--font-mono)`; `font-size: var(--text-caption, 0.75rem)`; `fill: var(--muted-foreground, ...)` |
| `.quantitative-track__state` | `text-sm text-muted-foreground` | `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)` |

### 2.7 SequenceTrack.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.sequence-track__bases` | `font-mono` + `text-sm`; `gap-px`; `p-2` | `font-size: var(--text-small, 0.875rem)`; `padding: 0.5rem`; `gap: 1px`; `letter-spacing: 0.05em` |
| `.sequence-track__base` | `--muted` surface, `--foreground` text; micro `rounded` | `background: var(--muted, ...)`; `color: var(--foreground, ...)`; `border-radius: 0.25rem`; `min-inline-size: 1.25rem`; `block-size: 1.5rem` |
| base letter colours | semantic A/T/G/C hues (not in the token set) | deliberate difference, see §3 |
| `.sequence-track__state` | `text-sm text-muted-foreground` | `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)` |

### 2.8 GenomeBrowser.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.genome-browser` | widget outer `rounded-lg border bg-card` | `border: 1px solid var(--border, ...)`; `border-radius: var(--radius-lg, 0.875rem)`; `background: var(--card, #fff)` (was `--background`) |
| `.genome-browser__ruler` | widget header `border-b bg-muted/30 px-3`; `--ruler-height` | `min-height: var(--ruler-height, 1.75rem)`; `padding-inline: 0.75rem`; `border-block-end: 1px solid var(--border, ...)`; `background: color-mix(in oklch, var(--muted, ...) 30%, transparent)` (was opaque `--muted`); `font-size: var(--text-caption, 0.75rem)` |
| `.genome-browser__ruler-label` | `font-semibold`; `text-xs text-muted-foreground` | `font-weight: 600`; `color: var(--muted-foreground, ...)` |
| `.genome-browser__tracks` | widget content `p-3`, `gap-2` | `padding: 0.75rem`; `gap: 0.5rem`; `min-block-size: 6rem` |
| `.genome-browser__empty` | `text-sm text-muted-foreground`; `p-6` | `padding: 1.5rem`; `font-size: var(--text-small, 0.875rem)`; `color: var(--muted-foreground, ...)` |
| `.genome-browser__track` | inner card `rounded-md border` | `border: 1px solid var(--border, ...)`; `border-radius: var(--radius-md, 0.625rem)` |

### 2.9 TrackErrorBoundary.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.track-error-boundary__error` | error card `p-3/p-4`; `bg-destructive/10` (App.tsx) | `padding: 0.75rem`; `gap: 0.375rem`; `border: 1px solid var(--destructive, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: color-mix(in oklch, var(--destructive, ...) 10%, transparent)` (was 8%) |
| `.track-error-boundary__title` | `font-semibold` + `text-sm` | `font-size: var(--text-small, 0.875rem)`; `font-weight: 600`; `color: var(--foreground, ...)` |
| `.track-error-boundary__message` | `text-sm text-muted-foreground` | `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)`; `color: var(--muted-foreground, ...)` |
| `.track-error-boundary__retry` | widget retry `rounded border px-2 py-1 text-xs`; 32px floor | `min-height: 2rem`; `padding-inline: 0.75rem`; `border: 1px solid var(--border, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: var(--card, #fff)`; `color: var(--foreground, ...)`; `font-size: var(--text-small, 0.875rem)`; `font-weight: 600` |
| `:focus-visible` | global ring | `outline: 2px solid var(--ring, ...); outline-offset: 2px` |

### 2.10 TrackRenderer.vue

| Element | React ref | Vue value |
| --- | --- | --- |
| `.track-renderer__error` | error card `bg-destructive/10` | `padding: 0.75rem`; `gap: 0.375rem`; `border: 1px solid var(--destructive, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: color-mix(in oklch, var(--destructive, ...) 10%, transparent)` (was 8%) |
| `.track-renderer__message` | `text-sm text-muted-foreground` | `font-size: var(--text-small, 0.875rem)`; `line-height: var(--text-small--line-height, 1.55)`; `color: var(--muted-foreground, ...)` |
| `.track-renderer__retry` | widget retry button; 32px floor | `min-height: 2rem`; `padding-inline: 0.75rem`; `border: 1px solid var(--border, ...)`; `border-radius: var(--radius-md, 0.625rem)`; `background: var(--card, #fff)`; `color: var(--foreground, ...)`; `font-size: var(--text-small, 0.875rem)`; `font-weight: 600` |

## 3. Deliberate differences

| # | Difference | Why |
| --- | --- | --- |
| 1 | Micro-labels are snapped **up** to `--text-caption` (12px) instead of the deleted widget's `text-[10px]` / `text-[9px]` / SVG `fontSize=8`. | Keeps every label on the `@theme` type scale and above the practical legibility floor; the React widget's micro sizes exist only for a dense standalone histogram. |
| 2 | Track surfaces use hairline **borders** and no shadow, although `--shadow-sm/md/lg` exist. | The React baseline container is `rounded-lg border bg-card` with no shadow; dense stacked tracks read better with separating hairlines than with shadows. |
| 3 | The locus input is `2.25rem` (`h-9`) but standalone retry buttons are `2rem` (32px), not antd `size="small"` (24px). | `App.tsx` gives the locus input `h-9`; the design system's compact-control floor is 32px (style.css `.ant-input { min-height: 32px }`). Native Vue controls are not bound by antd's sm size. |
| 4 | Container uses `--radius-lg` (14px), inner track/error panels use `--radius-md` (10px). | Matches the widget outer `rounded-lg` plus the design-system `borderRadius: 10` used by AntD controls; a 14px radius on small error boxes would look inflated. |
| 5 | Track marks keep chart/impact tokens (`--chart-1/2`, `--impact-moderate`, `--destructive`) and SequenceTrack keeps semantic A/T/G/C hues. | These encode data, not chrome: the palette must stay distinguishable and consistent across light/dark. A/T/G/C hues are not part of the chrome token set. |
| 6 | `--track-height` and `--ruler-height` are taken from `apps/web` `@layer design` and always used with a `rem` fallback. | The package is a library; consumers that do not load `apps/web/src/style.css` still get the same 28px/24px geometry. |
| 7 | No on-screen heading uses `font-serif`. | The track primitives expose no page headings; the host application (App.tsx `font-serif text-lg`) owns the brand typeface. |
| 8 | The JBrowse-internal MUI theme (`apps/jbrowse/src/config.ts`: `fontSize: 13`, `borderRadius: 6`) is **not** the target. | The task specifies the React **design system**; the design scale is 12/14px text and 10/14px radii. `borderRadius: 6` remains available as the `--radius-sm` fallback (0.375rem). |

## 4. Verification

```bash
cd packages/genome-view
./node_modules/.bin/vue-tsc --noEmit        # exit 0
./node_modules/.bin/vitest run              # 15 files / 56 tests passed
../../node_modules/.bin/eslint src          # exit 1 - see note
```

- `vue-tsc --noEmit`: **pass** (exit 0).
- `vitest run`: **56 tests in 15 files pass**. 53 of those tests across 14 files belong to the
  tracked package; `src/ablation/scratch.test.ts` (3 tests) is an untracked scratch probe created
  concurrently in the shared workspace by another worker. Re-running with
  `--exclude 'src/ablation/**'` gives **14 files / 53 tests passed**.
- `eslint src`: **passes for every tracked source file** (0 errors; `.vue` files are ignored by the
  repository ESLint config). The package-wide invocation exits 1 only because the untracked
  `src/ablation/scratch.test.ts` scratch probe trips `no-useless-assignment` / `no-console`; that
  file is outside this task's owned scope (`packages/genome-view/src/components/**`). Linting the
  tracked sources (`eslint $(git ls-files 'src' | grep -E '\.(ts|vue)$')`) exits 0.

No behaviour, props, emits or data flow changed; every edit is confined to a `<style scoped>`
block.
