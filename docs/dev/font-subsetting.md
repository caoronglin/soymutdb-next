# Self-hosted font subsetting (admin + genome browser)

The **admin console** and the **standalone genome browser** self-host HarmonyOS
Sans SC. The **public portal does not** — its CSS uses the system CJK stack on
purpose (see the font note in `apps/web/src/index.css`) and ships no
`@font-face`, no font files and no font preload. Keeping a ~908 KB preload for a
font the portal CSS never uses was pure waste, so the portal fonts and preload
were removed (2026-10-18).

The genome browser was converted from three full ~4.2 MB files (plus a second
webpack-emitted hashed copy, ~26 MB in `dist/`) to the same split subset: its
emitted artifact went **31 MB → 8 MB** on 2026-10-18, with the six subset files
served once from `fonts/harmonyos/` and referenced root-absolutely from the
chunk CSS (the browser is served from its own origin root by every deployment).

## Subsets

The originals are ~4.3 MB per weight. Each weight is split by `unicode-range`
into two woff2 files under `apps/<admin|jbrowse>/public/fonts/harmonyos/`:

| file | covers | size | loading |
| --- | --- | --- | --- |
| `HarmonyOS-Sans-SC-<Weight>-latin.woff2` | printable ASCII + Western punctuation/symbols | ~15–16 KB | preloaded (Regular only) |
| `HarmonyOS-Sans-SC-<Weight>-cjk.woff2` | hanzi (GB2312 level-1+2, 6763) + CJK/fullwidth punctuation | ~915–930 KB | fetched only when CJK glyphs render |

Total payload is ~2.82 MB per app (unchanged from the previous single-file
subset), but an English admin session now fetches only the ~15 KB latin Regular
(plus the ~16 KB latin Bold when bold text renders) instead of ~908 KB up front.
A Chinese session downloads the CJK face on demand. The genome browser declares
the faces without a preload (`font-display: swap`), so it pays only for the faces
its rendered text needs.

Kept in the subset: every char in the `zh` + `en` locale bundles, every char in
`apps/*/src/**/*.{ts,tsx}`, GB2312 level-1+2 hanzi, printable ASCII. Hanzi
outside that set fall back to the system UI face, not tofu. A handful of symbols
the source font genuinely lacks (e.g. U+2318 ⌘, U+21B5 ↵) are recorded as
`missing_codepoints` in the manifest and fall back the same way.

The split follows `scripts/subset-portal-fonts.py`'s `CJK_RANGES`: hanzi,
CJK Symbols and Punctuation, CJK Compatibility Forms and Halfwidth/Fullwidth
Forms live in the `cjk` file; everything else lives in `latin`.

## Regenerate

```bash
# needs fontTools + brotli (API/worker venvs have fontTools but NOT brotli)
python scripts/subset-portal-fonts.py            # rewrite 6 admin fonts + manifest
python scripts/subset-portal-fonts.py --check    # verify only, no writes
python scripts/subset-portal-fonts.py --dry-run  # print the plan
```

The first run caches pristine full fonts in `.cache/font-subset-sources/<app>/`
(git-ignored); if gone, restore the originals from git history (they remain
there) or pass `--source-dir DIR`. Each app's manifest lives at
`apps/<app>/public/fonts/harmonyos/subset-manifest.json` (schema: full charset +
`parts` counts, per-file weight/role/bytes/sha256/missing codepoints, budgets).

## Guards

`scripts/test_portal_font_subset.py` reads the character set from the generator
itself (no duplication) and fails when:

* the manifest charset/parts are stale (new Chinese UI text → regenerate),
* a file is missing, hash-mismatched, over the role budget (256 KiB latin /
  1.2 MiB cjk) or the app exceeds 3.0 MiB (full-font recommit),
* either app's CSS loses a split face or its `unicode-range`, or the admin
  preload stops pointing at the small latin file,
* **the portal re-introduces font files, a HarmonyOS `@font-face` or a font
  preload** — its policy is the system stack.

When fontTools is available it also verifies each file's cmap covers exactly the
codepoints its role promises. Run:

```bash
PYTHONPATH="$PWD" python -m pytest scripts/test_portal_font_subset.py -q
```
