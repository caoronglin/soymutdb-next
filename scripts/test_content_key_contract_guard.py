#!/usr/bin/env python3
"""Regression coverage for the content-key contract guard (L1 + L2).

The guard has one job: a portal ``get("<key>")`` literal that is not a
registered ``content.*`` setting can never be overridden, so it must fail the
build. These tests pin the parser (so the guard cannot go vacuous), prove the
clean tree passes, and prove a synthetic removed registration fails.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


class ContentKeyContractTests(unittest.TestCase):
    def test_current_tree_has_no_unregistered_literal_get_keys(self) -> None:
        registered = gate.registered_content_keys(gate.REGISTRY.read_text(encoding="utf-8"))
        consumed = gate.portal_get_keys(gate.PORTAL_ROOT)
        unregistered, _unread = gate.drift(registered, consumed)
        self.assertEqual(
            unregistered, [], f"portal reads unregistered content keys: {unregistered}"
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

    def test_unread_registered_keys_are_reported_but_not_gated(self) -> None:
        registered = {"nav.home", "variants.colImpact"}
        consumed = {"nav.home": "apps/web/src/a.tsx"}
        _unregistered, unread = gate.drift(registered, consumed)
        self.assertEqual(unread, ["variants.colImpact"])


if __name__ == "__main__":
    unittest.main()
