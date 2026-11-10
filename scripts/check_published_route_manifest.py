#!/usr/bin/env python3
"""Pin the published route manifest to two reviewed, hand-written literals.

The portal is a data-driven SPA, but a deployment still has to know two things
as *files*: which routes get their own document and may be indexed, and what the
site-level crawl policy says. ``apps/web/scripts/generate-static-routes.ts``
writes exactly that -- ``routes.json``, ``robots.txt`` and ``sitemap.xml`` --
and ``apps/web/scripts/content-snapshot-build.ts`` rewrites ``sitemap.xml``
afterwards to append the published news pages.

Nothing in this repository read that output. The only coverage is the vitest
suite in ``apps/web/src/lib/static-routes.test.ts``, and it asserts
*relations*: the internal variant lists nothing, dynamic paths never prerender,
three paths are absent, one path array is exact. No gate asserted which routes
this deployment publishes, which of them a crawler may index, or whether
``robots.txt`` allows anything at all. Two drift shapes therefore ship green:

* a metadata flip in ``PORTAL_ROUTES`` -- ``sitemap: true`` on a private route,
  ``prerender: false`` on a content page -- is a data edit that keeps every
  relation above true;
* ``robots.txt`` has no reader at all. Reverting the external build's
  ``Allow: /`` to ``Disallow: /`` de-indexes the whole site, and the one suite
  that touches the policy calls ``renderRobots()`` directly instead of reading
  the emitted file.

So this guard pins two independent surfaces, from committed bytes, with
``json`` + ``re`` + stdlib only:

* ``apps/web/dist/external/routes.json`` -- the shipped enumeration;
* ``apps/web/dist/external/robots.txt`` -- the shipped crawl policy.

Both literals are hand-written fixed points. Re-deriving either from the bytes
under audit would make the pin self-referential, which is the whole failure this
file replaces. A legitimate change -- a new page, a reworded title, a
deliberately published route -- moves the digest in the same commit as the
artifact and says why, exactly like ``_OPERATION_ID_DIGEST`` in
``check_openapi_operation_id_floor.py``.

The digests are ordered, not sorted: ``routes.json`` is consumed as a sequence
(the enumeration order is the order a deploy walks), so a same-count rotation
moves them.

``--derive`` prints the two literal lines for the tree being reviewed:

    python3 scripts/check_published_route_manifest.py --derive

Usage:
    python3 scripts/check_published_route_manifest.py
    python3 scripts/check_published_route_manifest.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "apps" / "web" / "dist" / "external"
MANIFEST_NAME = "routes.json"
ROBOTS_NAME = "robots.txt"

# Versioned canonical tags: a change to the row format must move the literals on
# purpose, never because a helper was refactored.
MANIFEST_TAG = "soymutdb-published-route-manifest/v1"
ROBOTS_TAG = "soymutdb-published-robots/v1"

# Reviewed fixed points of the external artifact. Arm them with --derive.
#
# Re-pinned 2026-11-09 with the dual-site artifact rebuild: the external
# artifact now declares its own origin (https://external.soymutdb.invalid)
# instead of the legacy single-site https://soymutdb.invalid. The route list,
# order and crawl policy are unchanged; only the origin line moved, so both
# digests moved together.
#
# Re-pinned again 2026-11-09 when the `/analyses` route was removed: this
# repository is a database, not an analysis platform, so the public analysis
# pages (list, fastp, scanpy, job detail) and their navigation entry are gone.
# `/analyses` was the only prerendered route among them, so the enumeration
# drops 33 -> 32 while the indexable set (25) and the crawl policy stay
# unchanged -- which is why only _MANIFEST_DIGEST moved below.
_MANIFEST_DIGEST: str | None = (
    "8aaa581e022784ace37f0a31497dd94c22f3731de26fd23b5e5badc5f66bd751"
)
_ROBOTS_DIGEST: str | None = (
    "270e18bf22e414c7aec477741c0dc91c754859b81a25ca6f263dc843eaf7f4a2"
)

# Second, independent doors: a permutation is only caught by the digests above,
# but a route that gains or loses its document moves these.
_EXPECTED_ROUTES = 32
_EXPECTED_INDEXABLE = 25

MANIFEST_KEYS = frozenset({"siteVariant", "origin", "entries"})
ENTRY_KEYS = frozenset({"path", "title", "description", "includeInSitemap"})
SITEMAP_LOC = re.compile(r"<loc>([^<]+)</loc>")


def canonical_manifest(document: dict[str, Any]) -> str:
    """One row per entry, in emitted order -- not a sorted multiset."""
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("routes.json carries no 'entries' array")
    rows = [MANIFEST_TAG, "origin=" + json.dumps(document.get("origin"), sort_keys=True)]
    for index, entry in enumerate(entries):
        description = entry.get("description")
        rows.append(
            "|".join(
                [
                    str(index),
                    str(entry.get("path")),
                    "1" if entry.get("includeInSitemap") else "0",
                    str(entry.get("title")),
                    "" if description is None else str(description),
                ]
            )
        )
    return "\n".join(rows)


def canonical_robots(text: str) -> str:
    """The shipped policy line for line -- a set would hide rule order."""
    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join([ROBOTS_TAG, *lines])


def manifest_digest(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_manifest(document).encode("utf-8")).hexdigest()


def robots_digest(text: str) -> str:
    return hashlib.sha256(canonical_robots(text).encode("utf-8")).hexdigest()


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return path.name


def _read(external: Path) -> tuple[dict[str, Any], str]:
    manifest = external / MANIFEST_NAME
    robots = external / ROBOTS_NAME
    if not manifest.is_file():
        raise ValueError(
            f"{_display(manifest)} is missing: the external artifact was never "
            "built, or generate-static-routes.ts stopped writing the enumeration"
        )
    if not robots.is_file():
        raise ValueError(
            f"{_display(robots)} is missing: the external artifact carries no "
            "crawl policy"
        )
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{MANIFEST_NAME} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{MANIFEST_NAME} is not a JSON object")
    return document, robots.read_text(encoding="utf-8")


def shape_errors(document: dict[str, Any]) -> list[str]:
    """The keys and row shape the shipped manifest must carry."""
    found: list[str] = []
    missing = MANIFEST_KEYS - set(document)
    if missing:
        found.append(f"routes.json is missing key(s) {sorted(missing)}")
    extra = set(document) - MANIFEST_KEYS
    if extra:
        found.append(
            f"routes.json publishes unreviewed key(s) {sorted(extra)}: a new "
            "top-level field is part of the artifact a deploy reads"
        )
    entries = document.get("entries")
    if not isinstance(entries, list):
        return found + ["routes.json 'entries' is not an array"]
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            found.append(f"routes.json entry {index} is not an object")
            continue
        if set(entry) != ENTRY_KEYS:
            found.append(
                f"routes.json entry {index} ({entry.get('path')!r}) carries keys "
                f"{sorted(entry)}; the reviewed row shape is {sorted(ENTRY_KEYS)}"
            )
    return found


def check(
    external: Path | None = None,
    # `True` means "use the module-level literal"; a string overrides it and
    # `None` models an unarmed door. All three states are exercised by the
    # self-test, so the annotation has to name all three.
    manifest_literal: str | bool | None = True,
    robots_literal: str | bool | None = True,
    expected_routes: int | None = None,
    expected_indexable: int | None = None,
) -> list[str]:
    """Return human-readable failures; empty means both surfaces are pinned.

    ``manifest_literal`` / ``robots_literal`` default to the module literals.
    Passing ``None`` models an unarmed literal, which is reported rather than
    treated as a pass.
    """
    root = EXTERNAL if external is None else external
    armed_manifest = _MANIFEST_DIGEST if manifest_literal is True else manifest_literal
    armed_robots = _ROBOTS_DIGEST if robots_literal is True else robots_literal
    pinned_total = _EXPECTED_ROUTES if expected_routes is None else expected_routes
    pinned_indexable = (
        _EXPECTED_INDEXABLE if expected_indexable is None else expected_indexable
    )

    try:
        document, robots = _read(root)
    except ValueError as exc:
        return [str(exc)]

    found = shape_errors(document)

    derived = manifest_digest(document)
    if armed_manifest is None:
        found.append(
            "the routes.json fixed point is not armed (_MANIFEST_DIGEST is None), "
            "so nothing pins which routes this deployment publishes; review the "
            f"derived value {derived} and record it with --derive"
        )
    elif derived != armed_manifest:
        found.append(
            f"published route manifest drifted: _MANIFEST_DIGEST pins "
            f"{armed_manifest} but {_display(root / MANIFEST_NAME)} derives "
            f"{derived}. The shipped enumeration is what a deploy reads -- re-pin "
            "in the same commit as the artifact, with a reason."
        )

    derived_robots = robots_digest(robots)
    if armed_robots is None:
        found.append(
            "the crawl policy fixed point is not armed (_ROBOTS_DIGEST is None), "
            "so a policy that de-indexes the whole site ships silently; review "
            f"the derived value {derived_robots} and record it"
        )
    elif derived_robots != armed_robots:
        found.append(
            f"published crawl policy drifted: _ROBOTS_DIGEST pins {armed_robots} "
            f"but {_display(root / ROBOTS_NAME)} derives {derived_robots}"
        )

    entries = document.get("entries")
    if isinstance(entries, list):
        rows = [entry for entry in entries if isinstance(entry, dict)]
        if len(rows) != pinned_total:
            found.append(
                f"routes.json ships {len(rows)} route(s), the reviewed floor is "
                f"{pinned_total}: a route gained or lost its own document"
            )
        indexable = [row for row in rows if row.get("includeInSitemap")]
        if len(indexable) != pinned_indexable:
            found.append(
                f"routes.json marks {len(indexable)} route(s) indexable, the "
                f"reviewed floor is {pinned_indexable}"
            )
        paths = [row.get("path") for row in rows]
        # Only real, non-empty path strings can be duplicated; a missing one is
        # reported by the entry-shape door instead of crashing this comparison.
        names = [path for path in paths if isinstance(path, str) and path]
        duplicates = sorted({path for path in names if names.count(path) > 1})
        if duplicates:
            found.append(f"routes.json repeats route path(s) {duplicates}")
        if document.get("siteVariant") != "external":
            found.append(
                "routes.json siteVariant is "
                f"{document.get('siteVariant')!r}: this is the external artifact, "
                "and the site variant is selected explicitly, never inferred"
            )
        origin = document.get("origin")
        if not isinstance(origin, str) or not origin.startswith("https://"):
            found.append(
                f"routes.json origin is {origin!r}: every canonical and sitemap "
                "URL is built from it and it must be an https origin"
            )
        sitemap = root / "sitemap.xml"
        if sitemap.is_file():
            locs = SITEMAP_LOC.findall(sitemap.read_text(encoding="utf-8"))
            expected_locs = sum(1 for _ in indexable)
            if len(locs) != expected_locs:
                found.append(
                    f"sitemap.xml lists {len(locs)} URL(s) but routes.json marks "
                    f"{expected_locs} route(s) indexable"
                )

    if "Disallow: /" in robots and "Allow: /" not in robots:
        found.append(
            "robots.txt disallows the whole external site: that is the internal "
            "variant's policy, and de-indexing every published page is a "
            "release-visible change, not a build detail"
        )
    if "Sitemap:" not in robots:
        found.append(
            "robots.txt advertises no <Sitemap:> line although the external "
            "artifact publishes one"
        )
    return found


def derive(external: Path | None = None) -> str:
    """The two literal lines to paste after a reviewed change."""
    document, robots = _read(EXTERNAL if external is None else external)
    return (
        f'_MANIFEST_DIGEST = "{manifest_digest(document)}"\n'
        f'_ROBOTS_DIGEST = "{robots_digest(robots)}"'
    )


def _row(path: str, *, indexable: bool = True, title: str | None = None) -> dict[str, Any]:
    return {
        "path": path,
        "title": f"{path} — SoyMutDB" if title is None else title,
        "description": None,
        "includeInSitemap": indexable,
    }


CLEAN_ROWS = (_row("/"), _row("/genes"), _row("/login", indexable=False))
CLEAN_ROBOTS = "User-agent: *\nAllow: /\nSitemap: https://soymutdb.invalid/sitemap.xml\n"
SITEMAP = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    "  <url><loc>https://soymutdb.invalid/</loc></url>\n"
    "  <url><loc>https://soymutdb.invalid/genes</loc></url>\n"
    "</urlset>\n"
)
# The fixture's own fixed points, not the production literals: the self-test
# must prove the doors work without depending on the shipped bytes.
FIXTURE = {"entries": list(CLEAN_ROWS), "origin": "https://soymutdb.invalid"}
FIXTURE_MANIFEST = manifest_digest(FIXTURE)
FIXTURE_ROBOTS = robots_digest(CLEAN_ROBOTS)


def _fixture(tmp: Path, rows: list[dict[str, Any]], robots: str, **overrides: Any) -> Path:
    external = tmp / "external"
    external.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "siteVariant": "external",
        "origin": "https://soymutdb.invalid",
    }
    document.update(overrides)
    document["entries"] = rows
    (external / MANIFEST_NAME).write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    (external / ROBOTS_NAME).write_text(robots, encoding="utf-8")
    (external / "sitemap.xml").write_text(SITEMAP, encoding="utf-8")
    return external


def _open(
    rows: list[dict[str, Any]] | None = None,
    robots: str = CLEAN_ROBOTS,
    **overrides: Any,
) -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp())
    return tmp, _fixture(tmp, list(CLEAN_ROWS) if rows is None else rows, robots, **overrides)


def self_test() -> int:
    """Every one-sided drift must be caught; the clean fixture must pass."""
    results = 0
    failures = 0

    def report(passed: bool, ok: str, fail: str) -> None:
        nonlocal results, failures
        results += 1
        print(ok if passed else fail)
        if not passed:
            failures += 1

    def probe(
        name: str,
        *,
        rows: list[dict[str, Any]] | None = None,
        robots: str = CLEAN_ROBOTS,
        rearm: bool = False,
        expect_clean: bool = False,
        manifest_literal: str | None | bool = FIXTURE_MANIFEST,
        robots_literal: str | None | bool = FIXTURE_ROBOTS,
        expected_routes: int = 3,
        **overrides: Any,
    ) -> None:
        tmp, external = _open(rows, robots, **overrides)
        try:
            if rearm:
                document, policy = _read(external)
                manifest_literal = manifest_digest(document)
                robots_literal = robots_digest(policy)
            problems = check(
                external,
                manifest_literal=manifest_literal,
                robots_literal=robots_literal,
                expected_routes=expected_routes,
                expected_indexable=2,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if expect_clean:
            report(
                not problems,
                f"PASS self-test: {name}",
                f"FAIL self-test: {name} -> {problems}",
            )
        else:
            report(
                bool(problems),
                f"PASS self-test: {name} -> {problems[0][:70]}",
                f"FAIL self-test: {name} stayed green",
            )

    probe("the clean fixture", expect_clean=True)

    # Door 1, the enumeration digest. A same-count rotation is the decisive
    # shape: identical route multiset, only the published order moves.
    probe(
        "two routes swapped (same multiset, new document order)",
        rows=[CLEAN_ROWS[1], CLEAN_ROWS[0], CLEAN_ROWS[2]],
    )
    probe(
        "a private route turned indexable",
        rows=[CLEAN_ROWS[0], CLEAN_ROWS[1], _row("/login")],
    )
    probe(
        "a content route turned non-indexable",
        rows=[CLEAN_ROWS[0], _row("/genes", indexable=False), CLEAN_ROWS[2]],
    )
    probe("a route dropped", rows=[CLEAN_ROWS[0], CLEAN_ROWS[1]])
    probe(
        "a description silently added",
        rows=[dict(CLEAN_ROWS[0], description="x"), CLEAN_ROWS[1], CLEAN_ROWS[2]],
    )
    probe(
        "a title edited",
        rows=[dict(CLEAN_ROWS[0], title="Home"), CLEAN_ROWS[1], CLEAN_ROWS[2]],
    )
    probe("the site origin changed", origin="https://evil.invalid")
    probe("the external variant relabelled internal", siteVariant="internal")
    probe("a hand-bumped route count", expected_routes=99)

    # Door 2, the crawl policy. Nothing else reads the emitted file.
    probe("allow reverted to disallow", robots="User-agent: *\nDisallow: /\n")
    probe("the sitemap line removed", robots="User-agent: *\nAllow: /\n")

    # The reviewed action, not a whitelist: re-pinning BOTH literals in the
    # same change stays green, and re-pinning one side cannot silence the other.
    probe(
        "a reviewed reorder re-armed on both halves",
        rows=[CLEAN_ROWS[1], CLEAN_ROWS[0], CLEAN_ROWS[2]],
        rearm=True,
        expect_clean=True,
    )
    probe(
        "a reorder with only the policy literal re-armed",
        rows=[CLEAN_ROWS[1], CLEAN_ROWS[0], CLEAN_ROWS[2]],
        robots="User-agent: *\nDisallow: /\n",
        robots_literal=robots_digest("User-agent: *\nDisallow: /\n"),
    )

    # An unarmed literal is reported, never counted as a pass.
    probe(
        "an unarmed manifest literal",
        manifest_literal=None,
    )
    probe(
        "an unarmed policy literal",
        robots_literal=None,
    )

    tmp, external = _open()
    try:
        (external / ROBOTS_NAME).unlink()
        report(
            any(
                ROBOTS_NAME in problem
                for problem in check(
                    external,
                    manifest_literal=FIXTURE_MANIFEST,
                    robots_literal=FIXTURE_ROBOTS,
                )
            ),
            "PASS self-test: a missing crawl policy is named",
            "FAIL self-test: a missing robots.txt passed",
        )
        (external / MANIFEST_NAME).unlink()
        report(
            any(MANIFEST_NAME in problem for problem in check(external)),
            "PASS self-test: a missing enumeration is named",
            "FAIL self-test: a missing routes.json passed",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp, external = _open()
    try:
        (external / "sitemap.xml").write_text(
            '<?xml version="1.0"?>\n<urlset>\n'
            "  <url><loc>https://soymutdb.invalid/</loc></url>\n</urlset>\n",
            encoding="utf-8",
        )
        report(
            any(
                "sitemap.xml" in problem
                for problem in check(
                    external,
                    manifest_literal=FIXTURE_MANIFEST,
                    robots_literal=FIXTURE_ROBOTS,
                )
            ),
            "PASS self-test: a sitemap that disagrees with the enumeration is named",
            "FAIL self-test: a short sitemap passed",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"self-test: {results} cases, {failures} failure(s)")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--derive",
        action="store_true",
        help="print the two literal lines for the artifact in this tree",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.derive:
        try:
            print(derive())
        except ValueError as exc:
            print(f"published route manifest: FAIL: {exc}", file=sys.stderr)
            return 1
        return 0
    problems = check()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        print(f"published route manifest: {len(problems)} failure(s)", file=sys.stderr)
        return 1
    print(
        "published route manifest: OK "
        f"({_EXPECTED_ROUTES} routes / {_EXPECTED_INDEXABLE} indexable / "
        "crawl policy pinned)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
