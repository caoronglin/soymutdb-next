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

# Apps whose generated HTML shell must carry an icon. Each app config declares
# the icon source, and built trees prove that Umi copied it into the artifact.
APPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("apps/web", "config/config.ts", ("dist/external", "dist/internal")),
    ("apps/admin", "config/config.ts", ("dist",)),
    ("apps/jbrowse", "config/config.ts", ("dist",)),
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
    config_path: Path,
    dist_dirs: tuple[Path, ...],
    failures: list[str],
) -> None:
    """Check Umi's icon declaration and every built tree that exists."""
    config = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    if "favicon.svg" not in config or "favicons:" not in config:
        failures.append(f"{app_dir.name}: Umi config must declare favicon.svg")
        return

    source_asset = app_dir / "public" / "favicon.svg"
    if not source_asset.is_file():
        failures.append(f"{app_dir.name}: config favicon has no matching public/favicon.svg")
        return

    for dist in dist_dirs:
        if not dist.is_dir():
            continue
        index = dist / "index.html"
        if not index.is_file():
            failures.append(f"{app_dir.name}: built {dist.name}/index.html is missing")
            continue
        href = icon_href(index.read_text(encoding="utf-8"))
        if href is None:
            failures.append(f'{app_dir.name}: built {dist.name}/index.html declares no <link rel="icon">')
            continue
        name = href.rsplit("/", 1)[-1]
        if not name or not (dist / name).is_file():
            failures.append(f"{app_dir.name}: built {dist.name}/{name or 'favicon'} is missing")


def run() -> list[str]:
    failures: list[str] = []
    for app, config_relative, variants in APPS:
        app_dir = ROOT / app
        config_path = app_dir / config_relative
        dist_dirs = tuple(app_dir / variant for variant in variants)
        check_shell(app_dir, config_path, dist_dirs, failures)
    return failures


def self_test() -> int:
    """Exercise pass and both failure modes on a throwaway tree."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        app = root / "apps" / "demo"
        (app / "public").mkdir(parents=True)
        (app / "public" / "favicon.svg").write_text("<svg/>", encoding="utf-8")
        config = app / "config" / "config.ts"
        config.parent.mkdir(parents=True)
        config.write_text('favicons: [`${base}favicon.svg`],', encoding="utf-8")
        dist = app / "dist"
        dist.mkdir()
        (dist / "index.html").write_text(
            '<head><link rel="icon" type="image/svg+xml" href="/favicon.svg" /></head>',
            encoding="utf-8",
        )
        (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")

        failures: list[str] = []
        check_shell(app, config, (dist,), failures)
        assert failures == [], failures

        (dist / "favicon.svg").unlink()
        check_shell(app, config, (dist,), failures)
        assert any("built dist/favicon.svg is missing" in item for item in failures), failures

        failures.clear()
        (dist / "index.html").write_text("<head></head>", encoding="utf-8")
        check_shell(app, config, (dist,), failures)
        assert any("declares no" in item for item in failures), failures

        failures.clear()
        (app / "public" / "favicon.svg").unlink()
        check_shell(app, config, (), failures)
        assert any("no matching public/favicon.svg" in item for item in failures), failures

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
