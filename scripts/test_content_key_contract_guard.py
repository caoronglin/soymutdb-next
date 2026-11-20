#!/usr/bin/env python3
"""Regression coverage for the content-key contract guard.

The guard has one job: portal content readers and the registered ``content.*``
settings must describe the same set of keys. These tests pin the literal and
dynamic parsers (so the guard cannot go vacuous), prove the clean tree passes,
and prove both drift directions fail the gate.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_content_key_contract as gate  # noqa: E402


def _definition(key: str) -> str:
    return (
        "    _definition(\n"
        '        "content",\n'
        f'        "{key}",\n'
        '        default="x",\n'
        "        permission=SettingPermission.ADMINISTRATOR,\n"
        "    ),\n"
    )


class _PortalTree:
    """A tiny temp portal root with only the files a test needs."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def cleanup(self) -> None:
        self._tmp.cleanup()


class ContentKeyContractTests(unittest.TestCase):
    def test_current_tree_has_no_drift_in_either_direction(self) -> None:
        registered = gate.registered_content_keys(gate.REGISTRY.read_text(encoding="utf-8"))
        consumed = gate.portal_get_keys(gate.PORTAL_ROOT)
        unregistered, unread = gate.drift(registered, consumed)
        self.assertEqual(
            unregistered, [], f"portal reads unregistered content keys: {unregistered}"
        )
        self.assertEqual(
            unread, [], f"registered content keys have no consumer: {unread}"
        )

    def test_parser_reads_literal_get_calls_and_ignores_property_access(self) -> None:
        sample = (
            'const a = get("variants.variantId", t("variants.variantId"));\n'
            'const b = di.get("api");\n'
            'const c = map.get("page");\n'
            'const d = get(`tool.${key}.label`, "x");\n'
            "const e = get('nav.home', 'Home');\n"
        )
        keys = gate.GET_CALL.findall(sample)
        self.assertEqual(keys, ["variants.variantId", "nav.home"])

    def test_definition_parser_only_reads_content_domain(self) -> None:
        sample = _definition("variants.variantId") + (
            '    _definition(\n        "email",\n        "smtpHost",\n        default="",\n    ),\n'
        )
        self.assertEqual(gate.registered_content_keys(sample), {"variants.variantId"})

    def test_a_missing_registration_is_reported_with_its_source(self) -> None:
        registered = {"nav.home"}
        consumed = {"nav.home": "apps/web/src/a.tsx", "variants.variantId": "apps/web/src/b.tsx"}
        unregistered, _unread = gate.drift(registered, consumed)
        self.assertEqual(unregistered, ["variants.variantId"])

    def test_orphan_registered_keys_are_reported(self) -> None:
        registered = {"nav.home", "variants.colImpact"}
        consumed = {"nav.home": "apps/web/src/a.tsx"}
        _unregistered, unread = gate.drift(registered, consumed)
        self.assertEqual(unread, ["variants.colImpact"])

    def test_dynamic_tool_faq_and_label_key_families_are_expanded(self) -> None:
        tree = _PortalTree()
        self.addCleanup(tree.cleanup)
        tree.write(
            "components/home/antd-home.tsx",
            "const TOOL_ENTRIES: ToolEntry[] = [\n"
            '  { key: "gene", labelKey: "home.toolGeneLabel" },\n'
            '  { key: "blast", labelKey: "home.toolBlastLabel" },\n'
            "];\n"
            "const a = get(`tool.${tool.key}.label`, \"\");\n"
            "const b = get(`tool.${tool.key}.desc`, \"\");\n"
            "const c = get(`tool.${tool.key}.image`, \"\");\n",
        )
        tree.write(
            "routes/help.tsx",
            "const FAQS = [\n"
            '  { q: "one", a: "first" },\n'
            '  { q: "two", a: "second" },\n'
            "];\n"
            "get(`help.faq${i + 1}.q`, \"\");\n"
            "get(`help.faq${i + 1}.a`, \"\");\n",
        )
        tree.write(
            "components/site-header.tsx",
            'const groups = [{ labelKey: "nav.search" }, { labelKey: "search.tabGenes" }];\n'
            "get(group.labelKey, t(group.labelKey));\n",
        )

        consumed = gate.portal_get_keys(tree.root)

        self.assertEqual(
            set(consumed),
            {
                "tool.gene.label",
                "tool.gene.desc",
                "tool.gene.image",
                "tool.blast.label",
                "tool.blast.desc",
                "tool.blast.image",
                "help.faq1.q",
                "help.faq1.a",
                "help.faq2.q",
                "help.faq2.a",
                "nav.search",
                "search.tabGenes",
            },
        )
        # labelKey constants outside a get(labelKey) consumer stay i18n-only.
        self.assertNotIn("home.toolGeneLabel", consumed)

    def test_an_unknown_dynamic_template_fails_closed(self) -> None:
        tree = _PortalTree()
        self.addCleanup(tree.cleanup)
        tree.write("routes/widget.tsx", "get(`tool.${slug}.label`, \"\");\n")

        with self.assertRaises(gate.UnmodelledDynamicRead):
            gate.portal_get_keys(tree.root)

    def _run_gate(self, tree: _PortalTree, registry_text: str) -> tuple[int, str]:
        registry = tree.root / "settings_registry.py"
        registry.write_text(registry_text, encoding="utf-8")
        stderr = io.StringIO()
        with (
            patch.object(gate, "REGISTRY", registry),
            patch.object(gate, "PORTAL_ROOT", tree.root),
            redirect_stderr(stderr),
        ):
            status = gate.main([])
        return status, stderr.getvalue()

    def test_gate_fails_on_an_unregistered_dynamic_tool_key(self) -> None:
        tree = _PortalTree()
        self.addCleanup(tree.cleanup)
        tree.write(
            "components/home/antd-home.tsx",
            "const TOOL_ENTRIES = [\n"
            '  { key: "primer", labelKey: "home.toolPrimerLabel" },\n'
            "];\n"
            "get(`tool.${tool.key}.label`, \"\");\n",
        )
        status, stderr = self._run_gate(tree, _definition("tool.gene.label"))

        self.assertEqual(status, 1)
        self.assertIn("tool.primer.label", stderr)

    def test_gate_fails_on_an_orphan_registered_key(self) -> None:
        tree = _PortalTree()
        self.addCleanup(tree.cleanup)
        status, stderr = self._run_gate(tree, _definition("nav.home"))

        self.assertEqual(status, 1)
        self.assertIn("no portal consumer", stderr)
        self.assertIn("nav.home", stderr)

    def test_gate_passes_when_dynamic_readers_match_the_registry(self) -> None:
        tree = _PortalTree()
        self.addCleanup(tree.cleanup)
        tree.write(
            "components/home/antd-home.tsx",
            "const TOOL_ENTRIES = [\n"
            '  { key: "gene", labelKey: "home.toolGeneLabel" },\n'
            "];\n"
            "get(`tool.${tool.key}.label`, \"\");\n",
        )
        status, stderr = self._run_gate(tree, _definition("tool.gene.label"))

        self.assertEqual(status, 0, stderr)


if __name__ == "__main__":
    unittest.main()