"""Unified HTML report builder backed by the ``dominate`` DOM API.

Replaces hand-written f-string / Jinja2 HTML fragments across the worker:

- ``tasks/static_pages.py`` — pre-generated gene detail pages (SSG),
- ``tasks/gwas.py`` — the self-contained ``Manhattan_QQ.html`` report.

:class:`HTMLReport` provides the shared document skeleton (head, inline CSS,
chart containers, footer) plus small building blocks (headings, paragraphs,
tables).  All dynamic text is escaped by ``dominate`` by default — values
passed to tags are HTML-escaped, and JSON embedded into ``<script>`` blocks
must go through :func:`embed_json` (which neutralises ``</script>``).

Example::

    report = HTMLReport("My report")
    report.add_heading("Results")
    report.add_table(["Col"], [["<value>"]])  # "<value>" is escaped
    print(report.render())
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Any

from dominate import document
from dominate.dom_tag import dom_tag
from dominate.tags import (
    a,
    div,
    footer,
    h1,
    h2,
    h3,
    h4,
    h5,
    h6,
    header,
    meta,
    p,
    script,
    style,
    table,
    tbody,
    td,
    th,
    thead,
    tr,
)
from dominate.tags import (
    title as title_tag,
)
from dominate.util import raw

#: Default inline CSS: scientific green palette, HarmonyOS font fallback and
#: table styles.  Merged from the former ``templates/base.html.j2`` (SSG gene
#: pages) and the GWAS report styles; ``.plot`` / ``.meta`` keep the original
#: Manhattan/QQ report look.
DEFAULT_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "HarmonyOS Sans SC",
    "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  font-size: 15px; line-height: 1.5; color: #1a1a1a; background: #f8f9fa;
}
.container { max-width: 960px; margin: 0 auto; padding: 16px; }
header {
  background: #1b5e20; color: #fff; padding: 16px 0;
  border-bottom: 3px solid #2e7d32;
}
header .container {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 8px;
}
header h1 { font-size: 1.25rem; font-weight: 600; }
header h1 a { color: #fff; text-decoration: none; }
header h1 a:hover { text-decoration: underline; }
.back-link {
  display: inline-block; font-size: 0.85rem; color: #c8e6c9;
  text-decoration: none;
}
.back-link:hover { text-decoration: underline; }
main { padding: 24px 0; }
h1 { font-size: 1.25rem; }
h2 {
  font-size: 1.1rem; color: #1b5e20; margin: 24px 0 12px; padding-bottom: 6px;
  border-bottom: 2px solid #c8e6c9;
}
h2:first-of-type { margin-top: 0; }
.card {
  background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  padding: 16px; margin-bottom: 16px; overflow: hidden;
}
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
thead { background: #e8f5e9; }
th, td {
  padding: 8px 10px; text-align: left; border-bottom: 1px solid #e0e0e0;
  white-space: nowrap;
}
th { font-weight: 600; color: #1b5e20; }
tr:hover { background: #f1f8e9; }
.table-wrap { overflow-x: auto; margin: 0 -16px; padding: 0 16px; }
.empty-state { color: #888; font-style: italic; padding: 16px; text-align: center; }
.position {
  font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
  font-size: 0.85rem;
}
.note {
  font-size: 0.8rem; color: #666; border-top: 1px solid #e0e0e0;
  padding-top: 12px; margin-top: 24px;
}
.note a { color: #1b5e20; }
footer {
  text-align: center; padding: 16px; font-size: 0.8rem; color: #888;
  border-top: 1px solid #e0e0e0; margin-top: 32px;
}
.plot { width: 100%; height: 480px; }
.meta { color: #666; font-size: 13px; margin-bottom: 16px; }
@media (max-width: 600px) {
  .container { padding: 8px; }
  header .container { flex-direction: column; align-items: flex-start; }
  th, td { padding: 6px 8px; font-size: 0.8rem; }
}
"""

_HEADING_TAGS = {1: h1, 2: h2, 3: h3, 4: h4, 5: h5, 6: h6}

#: Placeholder rendered for ``None`` cells in tables.
_EMPTY_CELL = "—"


def embed_json(obj: Any) -> str:
    """Serialize *obj* for safe embedding inside an inline ``<script>``.

    ``dominate`` escapes HTML text but not ``<script>`` contents, so a value
    containing ``</script>`` could break out of the block.  Escaping ``<`` as
    the JSON ``\\u003c`` escape sequence keeps the decoded JavaScript value
    identical while neutralising the closing tag.
    """
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


class HTMLReport:
    """A self-contained HTML document built with the ``dominate`` DOM API.

    All text passed to the building blocks is HTML-escaped by ``dominate``;
    only content added explicitly via :meth:`add_script` (or ``raw``) is
    injected verbatim.
    """

    def __init__(self, title: str, css: str | None = None, *, lang: str = "en") -> None:
        # ``document`` would add a placeholder <title>Dominate</title> when
        # given a title; pass None and add our (escaped) title explicitly.
        self.doc = document(title=None, lang=lang)
        with self.doc.head:
            meta(charset="utf-8")
            meta(name="viewport", content="width=device-width, initial-scale=1")
            self.title_node = title_tag(title)
            # <style> is a raw-text element: wrap in raw() so quotes in the
            # CSS are not HTML-escaped into entities.
            style(raw(css if css is not None else DEFAULT_CSS))
        self.head = self.doc.head
        self.body = self.doc.body
        self._stack: list[Any] = [self.body]

    # ------------------------------------------------------------------
    # Container management
    # ------------------------------------------------------------------

    @contextmanager
    def container(self, tag: Any) -> Iterator[Any]:
        """Add *tag* to the current container and use it as the insertion
        target while the ``with`` block is active (dominate-style nesting)."""
        self._stack.append(self._current.add(tag))
        try:
            yield self._stack[-1]
        finally:
            self._stack.pop()

    @property
    def _current(self) -> Any:
        return self._stack[-1]

    # ------------------------------------------------------------------
    # Building blocks
    # ------------------------------------------------------------------

    def add_heading(self, text: str, level: int = 2, **attrs: Any) -> Any:
        """Add a heading (``<h1>`` .. ``<h6>``)."""
        return self._current.add(_HEADING_TAGS[level](text, **attrs))

    def add_paragraph(self, text: str, **attrs: Any) -> Any:
        """Add a paragraph; pass ``cls="empty-state"`` etc. via attrs."""
        return self._current.add(p(text, **attrs))

    def add_table(
        self,
        headers: Iterable[str],
        rows: Iterable[Iterable[Any]],
        *,
        empty_text: str | None = None,
        **attrs: Any,
    ) -> Any:
        """Add a ``<table>`` with a header row; ``None`` cells render as "—".

        When *rows* is empty, a paragraph with *empty_text* (class
        ``empty-state``) is added instead and ``None`` is returned.
        """
        row_list = list(rows)
        if not row_list:
            if empty_text is not None:
                self.add_paragraph(empty_text, cls="empty-state")
            return None
        tbl = table(**attrs)
        with tbl:
            with thead():
                with tr():
                    for h in headers:
                        th(h)
            with tbody():
                for row in row_list:
                    with tr():
                        for cell in row:
                            cell_tag = td()
                            if isinstance(cell, dom_tag):
                                cell_tag.add(cell)
                            else:
                                cell_tag.add(cell if cell is not None else _EMPTY_CELL)
        return self._current.add(tbl)

    def add_chart_div(self, div_id: str, **attrs: Any) -> Any:
        """Add a chart container ``<div id="{div_id}">`` (default class ``plot``)."""
        attrs.setdefault("cls", "plot")
        return self._current.add(div(id=div_id, **attrs))

    def add_script(self, js: str) -> Any:
        """Append an inline ``<script>`` block; *js* is injected verbatim.

        Dynamic values inside *js* must be serialized with :func:`embed_json`
        (never raw ``json.dumps``) so ``</script>`` cannot break out.
        """
        return self._current.add(script(raw(js)))

    def add_header(
        self,
        *,
        brand_href: str = "https://soymutdb.com/",
        back_href: str | None = "https://soymutdb.com/genes",
        back_label: str = "← Browse Genes",
    ) -> Any:
        """Add the SoyMutDB brand header (used by the SSG gene pages)."""
        head_tag = header()
        with self._current.add(head_tag):
            with div(cls="container"):
                h1(a("SoyMutDB", href=brand_href))
                if back_href is not None:
                    a(back_label, href=back_href, cls="back-link")
        return head_tag

    def add_footer(self, text: str | None = None) -> Any:
        """Add the standard footer.

        *text* defaults to the SoyMutDB attribution line; an empty string
        renders an empty footer bar.
        """
        footer_tag = footer()
        with self._current.add(footer_tag):
            div(
                "SoyMutDB — Soybean Mutation Database · soymutdb.com"
                if text is None
                else text,
                cls="container",
            )
        return footer_tag

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def render(self) -> str:
        """Return the full HTML document as a string."""
        return self.doc.render()

    def __str__(self) -> str:
        return self.render()
