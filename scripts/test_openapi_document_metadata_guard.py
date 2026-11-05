"""Collect the OpenAPI document-metadata guard for the contracts smoke layer.

The guard itself is ``scripts/check_openapi_document_metadata.py``, kept
runnable directly (stdlib only) so pre-commit and a bare checkout can use it
without pytest. This module is the thin pytest face: one case on the committed
tree, and one case per ablation, so a regression names the invariant it broke.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

GUARD = Path(__file__).with_name("check_openapi_document_metadata.py")


def _guard():
    spec = importlib.util.spec_from_file_location("_openapi_document_metadata", GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_document_metadata_matches_the_golden() -> None:
    assert _guard().run() == []


def test_every_ablation_is_caught() -> None:
    problems = _guard().self_test()
    assert problems == [], "\n".join(problems)
