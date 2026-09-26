#!/usr/bin/env python3
"""App-shell asset contract: every shell declares a favicon that resolves.

The admin console shipped without a `<link rel="icon">`, so every page load
requested `/favicon.ico` and logged a 404. The favicon is part of the published
shell contract (and the runtime brand snapshot may replace it), so the check
covers both the source tree and, when present, the built artifacts — source-only
checks pass while a build drops the asset, and dist-only checks cannot explain
which source change broke it.

Usage:
    python3 scripts/check_app_shell_assets.py
    python3 scripts/check_app_shell_assets.py --self-test
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Apps whose HTML shell must carry an icon. `dist_variants` lists the possible
# built roots (a single-tree build and the dual-site build both count).
APPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # The portal is only ever published as a site variant (external/internal);
    # the single-tree apps/web/dist is not a release artifact, so requiring it
    # here forced a redundant third web build in the frontend gate.
    ("apps/web", ("dist/external", "dist/internal")),
    ("apps/admin", ("dist",)),
)

ICON_LINK = re.compile(r"<link[^>]*rel=\"icon\"[^>]*>", re.IGNORECASE)
HREF = re.compile(r"href=\"([^\"]+)\"", re.IGNORECASE)


def icon_href(html: str) -> str | None:
    """Return the declared icon href, or None when the shell has no icon link."""
    match = ICON_LINK.search(html)
    if match is None:
        return None
    href = HREF.search(match.group(0))
    return href.group(1) if href else None


def check_shell(
    app_dir: Path,
    dist_dirs: tuple[Path, ...],
    failures: list[str],
) -> None:
    """Check one app's source shell and every built tree that exists."""
    index = app_dir / "index.html"
    if not index.is_file():
        failures.append(f"{app_dir.name}: index.html is missing")
        return
    href = icon_href(index.read_text(encoding="utf-8"))
    if href is None:
        failures.append(f'{app_dir.name}/index.html declares no <link rel="icon">')
        return

    # A Vite shell uses `/favicon.svg`, rewritten to the deployment base at
    # build time; only the file name has to resolve.
    name = href.rsplit("/", 1)[-1]
    if not name:
        failures.append(f"{app_dir.name}: icon href {href!r} has no file name")
        return

    source_asset = app_dir / "public" / name
    if not source_asset.is_file():
        failures.append(f"{app_dir.name}: {href} has no matching public/{name}")

    for dist in dist_dirs:
        if not dist.is_dir():
            continue
        if not (dist / name).is_file():
            failures.append(f"{app_dir.name}: built {dist.name}/{name} is missing")


def run() -> list[str]:
    failures: list[str] = []
    for app, variants in APPS:
        app_dir = ROOT / app
        dist_dirs = tuple(app_dir / variant for variant in variants)
        check_shell(app_dir, dist_dirs, failures)
    return failures


def self_test() -> int:
    """Exercise pass and both failure modes on a throwaway tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app = root / "apps" / "demo"
        (app / "public").mkdir(parents=True)
        (app / "public" / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        (app / "index.html").write_text(
            '<head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>',
            encoding="utf-8",
        )
        (app / "dist").mkdir()
        (app / "dist" / "favicon.svg").write_text("<svg/>", encoding="utf-8")

        failures: list[str] = []
        check_shell(app, (app / "dist",), failures)
        assert failures == [], failures

        (app / "dist" / "favicon.svg").unlink()
        check_shell(app, (app / "dist",), failures)
        assert any("built dist/favicon.svg is missing" in item for item in failures), failures

        failures.clear()
        (app / "index.html").write_text("<head></head>", encoding="utf-8")
        check_shell(app, (), failures)
        assert any("declares no" in item for item in failures), failures

        failures.clear()
        (app / "public" / "favicon.svg").unlink()
        (app / "index.html").write_text(
            '<head><link rel="icon" href="/favicon.svg" /></head>', encoding="utf-8"
        )
        check_shell(app, (), failures)
        assert any("has no matching public/favicon.svg" in item for item in failures), failures

    print("app shell asset self-test passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    failures = run()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    checked = ", ".join(app for app, _ in APPS)
    print(f"app shell assets OK ({checked})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
