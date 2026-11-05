# The published route manifest

Two files under `apps/web/dist/external/` are read by a deployment, not by a
browser:

| file | written by | what a deploy does with it |
| --- | --- | --- |
| `routes.json` | `apps/web/scripts/generate-static-routes.ts` | enumerates the routes that got their own `index.html` and whether a crawler may index them |
| `robots.txt` | same script | the site-level crawl policy (`Allow:` / `Disallow:` / `Sitemap:`) |

`apps/web/scripts/content-snapshot-build.ts` rewrites `sitemap.xml` afterwards to
append the published news pages; `routes.json` is not rewritten, so its sequence
is the sequence the build emitted.

Both files are **committed** for the external variant. They are the two files the
build emits that are also inputs to a review: the ignore rules in `.gitignore`
pin exactly this pair (`apps/web/dist/external/routes.json`,
`apps/web/dist/external/robots.txt`), and `_EXPECTED_ROUTES` /
`_EXPECTED_INDEXABLE` in the guard are the reviewed counts that the committed
file has to match. A regenerated artifact has to be re-committed in the same
change as the metadata edit that caused it — otherwise the export gate is red.

## Why a guard

The only other coverage is `apps/web/src/lib/static-routes.test.ts`, and it
asserts relations:

* the internal variant lists nothing;
* dynamic (`:param`) paths never prerender;
* three specific paths are absent;
* one exact path array.

No gate asserted *which* routes this deployment publishes, *which* of them a
crawler may index, or whether `robots.txt` allows anything at all. Two shapes
therefore shipped green:

* a metadata flip in `apps/web/src/router/routes.ts` — `sitemap: true` on a
  private route, `prerender: false` on a content page — is a data edit and keeps
  every relation above true;
* nothing read the emitted `robots.txt`. Reverting the external build's
  `Allow: /` to `Disallow: /` de-indexes the whole site, and the one suite that
  touches the policy calls `renderRobots()` directly instead of reading the
  file.

## What is pinned

`scripts/check_published_route_manifest.py` holds two hand-written sha256
literals, read from nowhere:

* `_MANIFEST_DIGEST` over `routes.json` as `index|path|indexable|title|description`
  rows **in emitted order**, plus the site origin;
* `_ROBOTS_DIGEST` over `robots.txt` line for line.

Ordered, not sorted: a same-count rotation keeps the route multiset identical
and only moves the sequence, which is exactly what a sorted set cannot see.

Second, independent doors:

* `_EXPECTED_ROUTES` / `_EXPECTED_INDEXABLE` — exact counts;
* `siteVariant == "external"` and an `https://` origin;
* no duplicate path;
* `sitemap.xml` lists as many URLs as `routes.json` marks indexable;
* `robots.txt` does not disallow the site it describes, and advertises a
  `Sitemap:` line.

Wiring: the plain run and `--self-test` are called from `smoke_contracts()`,
the call is pinned in `REQUIRED_GUARD_CALLS`, the guard is in
`_WIRED_SELF_TESTS` with a drift plant and a gut plant in
`check_contracts_self_test_teeth.py`, and
`scripts/test_published_route_manifest.py` is registered in `tests=()` and
`PINNED_SUITES` so the evidence is two-file.

## Changing it on purpose

1. Edit the metadata (`apps/web/src/router/routes.ts`) or the policy
   (`renderRobots`).
2. Rebuild the external artifact so `dist/external/` is regenerated.
3. `python3 scripts/check_published_route_manifest.py --derive` and paste both
   lines.
4. Commit the artifact, the literal and the reason together.

`--self-test` proves the doors work: the decisive case is a two-entry swap whose
multiset is identical, which the count doors cannot see and the digest catches.
