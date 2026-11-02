"""Every JSX custom element must have a real ``customElements.define``.

Regression guard for a silent public-portal breakage.

``apps/web/src/routes/sra.tsx`` rendered ``<soymutdb-widget>`` under a card
titled "Additional run metadata". Its React renderer had been deleted in
``25c32e499`` (the Vue cutover) and never restored, so the element was never
registered and the card rendered empty. The failure stayed invisible because the
route carried a ``declare module "react"`` JSX.IntrinsicElements block: the type
system was told the tag existed, so typecheck passed, lint passed and the unit
tests never looked at it.

The dangerous part is the combination, not either half alone:

* a JSX tag with a dash is always a custom element, never an intrinsic HTML tag
  or a React component -- so if it appears in JSX, *something* must call
  ``customElements.define`` for it;
* a ``declare module "react"`` / ``IntrinsicElements`` augmentation for a
  ``*-tagged`` element asserts that a custom element is expected to exist, and
  it suppresses the very TypeScript error that would otherwise surface a stale
  reference.

So this suite asserts, across every app source tree, that each such tag resolves
to at least one ``customElements.define`` call. A dangling declaration or JSX tag
fails here instead of shipping an empty card to the public portal.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Source trees that can render JSX. ``node_modules`` and build output are excluded
# by the glob construction below rather than by a hand-maintained skip list.
APP_SOURCE_ROOTS = (
    "apps/web/src",
    "apps/admin/src",
    "apps/jbrowse/src",
)

SOURCE_SUFFIXES = {".ts", ".tsx"}

# ``<soymutdb-widget``, ``<my-element`` -- a dash means custom element per the
# HTML spec, which is exactly the rule that makes this check decidable. The inner
# group is non-capturing so ``findall`` returns plain tag names.
JSX_TAG_RE = re.compile(r"<\s*([a-z][a-z0-9]*(?:-[a-z0-9]+)+)(?=[\s/>])")

# ``"soymutdb-widget":`` inside a JSX.IntrinsicElements augmentation.
INTRINSIC_DECL_RE = re.compile(
    r"""["']([a-z][a-z0-9]*(?:-[a-z0-9]+)+)["']\s*:""",
)

# ``customElements.define("soymutdb-widget"`` / ``.define('name',``
DEFINE_RE = re.compile(
    r"""customElements\s*\.\s*define\s*\(\s*["']([a-z][a-z0-9]*(?:-[a-z0-9]+)+)["']""",
)

# Doc comments describe markup in prose (``payload: <type-specific payload>``),
# which is not a JSX element. Comments are stripped before scanning so the guard
# only sees real code. ``//`` preceded by ``:`` is a URL, not a comment.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")


def _strip_comments(text: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", text))


def _iter_source_files():
    for relative_root in APP_SOURCE_ROOTS:
        base = ROOT / relative_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix in SOURCE_SUFFIXES and path.is_file():
                yield path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _registered_custom_elements() -> set[str]:
    """Every tag name passed to ``customElements.define`` in the source trees."""
    registered: set[str] = set()
    for path in _iter_source_files():
        registered.update(DEFINE_RE.findall(_strip_comments(_read(path))))
    return registered


def _unqualified(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:  # pragma: no cover - defensive
        return path.as_posix()


class CustomElementRegistrationContractTests(unittest.TestCase):
    """A dashed JSX tag or IntrinsicElements key needs a real registration."""

    def test_source_roots_exist(self) -> None:
        """Guard against a typo silently emptying the scan."""
        missing = [root for root in APP_SOURCE_ROOTS if not (ROOT / root).is_dir()]
        self.assertEqual(missing, [], f"missing app source roots: {missing}")

    def test_jsx_custom_element_tags_are_registered(self) -> None:
        """Every ``<dashed-tag>`` in JSX must have a matching ``define`` call."""
        registered = _registered_custom_elements()
        offenders: list[str] = []
        for path in _iter_source_files():
            for tag in JSX_TAG_RE.findall(_strip_comments(_read(path))):
                if tag not in registered:
                    offenders.append(f"{_unqualified(path)}: <{tag}>")
        self.assertEqual(
            offenders,
            [],
            "JSX renders custom elements that are never registered via "
            "customElements.define, so they mount as inert unknown elements:\n  "
            + "\n  ".join(offenders),
        )

    def test_intrinsic_element_declarations_are_registered(self) -> None:
        """A ``JSX.IntrinsicElements`` entry must not outlive its definition.

        This is the assertion that hid the SRA breakage: the declaration kept
        typecheck green long after the component that defined the element was
        deleted.
        """
        registered = _registered_custom_elements()
        offenders: list[str] = []
        for path in _iter_source_files():
            text = _strip_comments(_read(path))
            if "IntrinsicElements" not in text:
                continue
            for tag in INTRINSIC_DECL_RE.findall(text):
                if tag not in registered:
                    offenders.append(f"{_unqualified(path)}: \"{tag}\":")
        self.assertEqual(
            offenders,
            [],
            "JSX.IntrinsicElements declares custom elements that nothing "
            "registers; the declaration suppresses the TypeScript error that "
            "would reveal the missing renderer:\n  " + "\n  ".join(offenders),
        )

    def test_sra_route_does_not_reintroduce_the_dead_widget(self) -> None:
        """The specific regression: no silent empty card on the public /sra page."""
        sra = (ROOT / "apps/web/src/routes/sra.tsx").read_text(encoding="utf-8")
        self.assertNotIn(
            "<soymutdb-widget",
            sra,
            "apps/web/src/routes/sra.tsx must not render the soymutdb-widget custom "
            "element again: its renderer was deleted in 25c32e499 and the backend "
            "widget is not reachable from the React portal. Restoring it requires a "
            "real React component plus HTML-sanitization review.",
        )

    def test_scan_finds_the_source_corpus(self) -> None:
        """The scan must actually cover app sources, not run over an empty set."""
        files = list(_iter_source_files())
        self.assertGreater(
            len(files),
            50,
            f"expected the app source corpus to be non-trivial, scanned {len(files)} files",
        )


if __name__ == "__main__":
    unittest.main()
