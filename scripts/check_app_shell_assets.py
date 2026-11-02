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
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

# Apps whose generated HTML shell must carry an icon. Each app config declares
# the icon source, and built trees prove that Umi copied it into the artifact.
APPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("apps/web", "config/config.ts", ("dist/external", "dist/internal")),
    ("apps/admin", "config/config.ts", ("dist",)),
    ("apps/jbrowse", "config/config.ts", ("dist",)),
)

_SCRIPT_TAG = re.compile(r"<script\b([^>]*)>", re.IGNORECASE)
_DEFERRED = re.compile(r"\b(?:defer|async)\b|type\s*=\s*[\"']module[\"']", re.IGNORECASE)


def blocking_entry_scripts(html: str) -> list[str]:
    """External scripts that would run before the document body exists.

    A classic `<script src=...>` in `<head>` without `defer`/`async` executes
    immediately and cannot see `<div id="root">`; React then aborts with error
    #299 and the SPA renders a blank page. The genome-browser build shipped
    exactly that (its entry scripts lost `defer`), which no gate caught until
    the artifact browser gate was added. Inline scripts are exempt: they are
    CSP-hashed and depend on their position.
    """
    blocking: list[str] = []
    for tag in _SCRIPT_TAG.findall(html):
        if not re.search(r"\bsrc\s*=", tag):
            continue
        if _DEFERRED.search(tag):
            continue
        blocking.append(tag.strip())
    return blocking


class _IconParser(HTMLParser):
    """Recognize the HTML rel token set, including Umi's ``shortcut icon``."""

    href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        rel = (attributes.get("rel") or "").lower().split()
        if tag == "link" and "icon" in rel and self.href is None:
            self.href = attributes.get("href") or None


def icon_href(html: str) -> str | None:
    """Return a real icon link's href, independent of quote/attribute order."""
    parser = _IconParser()
    parser.feed(html)
    return parser.href


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
        html = index.read_text(encoding="utf-8")
        href = icon_href(html)
        if href is None:
            failures.append(f'{app_dir.name}: built {dist.name}/index.html declares no <link rel="icon">')
            continue
        name = href.rsplit("/", 1)[-1]
        if not name or not (dist / name).is_file():
            failures.append(f"{app_dir.name}: built {dist.name}/{name or 'favicon'} is missing")
        blocking = blocking_entry_scripts(html)
        if blocking:
            failures.append(
                f"{app_dir.name}: built {dist.name}/index.html has a blocking entry script "
                f"({blocking[0]}); add defer so React can find the mount node"
            )


def run() -> list[str]:
    failures: list[str] = []
    for app, config_relative, variants in APPS:
        app_dir = ROOT / app
        config_path = app_dir / config_relative
        dist_dirs = tuple(app_dir / variant for variant in variants)
        check_shell(app_dir, config_path, dist_dirs, failures)
    return failures


def self_test() -> int:
    """Exercise rel tokens, pass, and missing declarations/assets."""
    for declaration in (
        '<link rel="icon" href="/favicon.svg">',
        '<link href="/favicon.svg" rel="shortcut icon">',
        "<LINK href='/favicon.svg' REL='SHORTCUT ICON' />",
    ):
        assert icon_href(declaration) == "/favicon.svg", declaration
    for invalid in (
        "<head></head>",
        '<link rel="apple-touch-icon" href="/favicon.svg">',
        '<!-- <link rel="icon" href="/favicon.svg"> -->',
        '<link rel="icon">',
    ):
        assert icon_href(invalid) is None, invalid
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

        # Blocking entry scripts fail; deferred (or module) scripts pass.
        for html, should_fail in (
            ('<head><link rel="icon" href="/favicon.svg"><script src="/assets/app.js"></script></head>', True),
            ('<head><link rel="icon" href="/favicon.svg"><script src="/assets/app.js" defer></script></head>', False),
            ('<head><link rel="icon" href="/favicon.svg"><script type="module" src="/assets/app.js"></script></head>', False),
        ):
            failures.clear()
            (dist / "index.html").write_text(html, encoding="utf-8")
            (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
            check_shell(app, config, (dist,), failures)
            has_blocking_failure = any("blocking entry script" in item for item in failures)
            assert has_blocking_failure is should_fail, (html, failures)

        failures.clear()
        (app / "public" / "favicon.svg").unlink()
        check_shell(app, config, (), failures)
        assert any("no matching public/favicon.svg" in item for item in failures), failures

    # Cover the CLI success path too: APPS entries contain three values.
    with patch(f"{__name__}.run", return_value=[]), patch("sys.argv", [__file__]):
        assert main() == 0
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
    checked = ", ".join(app for app, _, _ in APPS)
    print(f"app shell assets OK ({checked})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
