# Caoslab-inspired transparent visuals

**Status:** original conceptual visuals — not official Caoslab branding; no real experimental data included.

This directory holds **10 transparent SVG assets** in three compatible styles:

- `botanical/`: quiet crop-genomics illustrations for home/research sections
- `soft/`: subtle gradient epigenetics/omics concept illustrations
- `line/`: six restrained, scale-independent scientific navigation icons

The assets are original vector illustrations for SoyMutDB. The high-resolution raster concepts generated during exploration are **separate**, not embedded or claimed to be committed here.

## Use

Reference a file directly as a static asset, e.g.:

```tsx
<img src="/visuals/caoslab/line/gene-search.svg" alt={t("geneSearch")} width={40} height={40} loading="lazy" />
```

Adapt the public base prefix to the deployment `BASE_URL` if served under a sub-path; do not hard-code root-relative paths into React application components. These files are currently **unwired** intentionally: asset delivery does not alter the site, routes or business behavior.

## Design and implementation contracts

- `viewBox` and transparent SVG background; no embedded HTML/JS, `foreignObject`, foreign assets or external fonts
- SVG strokes and gradients represent concepts only, never statistics or experiments
- Large illustrations are decoration: `alt="" aria-hidden="true"` in a page with equivalent nearby context
- Meaningful icons need locale-aware text or a visible label
- Do not overlay a decorative hero on top of the search control
- Contrast and 390/768/1440 viewport review are required **when integrated**
- Follow existing `packages/ui-react` / Ant Design tokens when integrating; do not create a new UI framework
- For real charts, use released API records with Release/Assembly and reproducible counts; no mock empirical figure

Source research reference: https://www.x-mol.com/groups/Caoslab/research

Metadata: [manifest.json](manifest.json).

## Acceptance scope

The asset PR verifies the 10 SVGs are well-formed, have unique titles and explicit sizes, and contain no remote resources. UI layout tests, production rendering, and asset integration are **not** claimed as part of this asset-only PR. Existing functional fixes in PR #20 remain independent.
