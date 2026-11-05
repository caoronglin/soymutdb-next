"""Collect the OpenAPI document-metadata guard for the contracts smoke layer.

The guard itself is ``scripts/check_openapi_document_metadata.py``, kept
runnable directly (stdlib only) so pre-commit and a bare checkout can use it
without pytest. This module is the thin pytest face: one case on the committed
tree, one case proving the ablations are caught, and one case proving the
catalog-completeness invariant (as opposed to the golden byte lock) is what
closes the three-way bless channel for invented tags.
"""

from __future__ import annotations

import importlib.util
import json
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
    problems, ablations, positives = _guard().self_test()
    assert problems == [], "\n".join(problems)
    assert ablations >= 22 and positives >= 1


def test_invented_tag_blessed_in_all_three_artifacts_is_rejected() -> None:
    """The golden lock is green by design on a three-way co-edit; only the
    router-derived completeness invariant can see a tag no router emits."""
    guard = _guard()
    snapshot, generated, golden, main, config, smoke, routers = guard._load()
    entry = {"name": "made-up", "description": "x"}
    main = main.replace(
        "OPENAPI_TAGS = [\n",
        'OPENAPI_TAGS = [\n    {"name": "made-up", "description": "x"},\n',
        1,
    )
    document = json.loads(snapshot)
    document["tags"].insert(0, entry)
    snapshot = json.dumps(document, ensure_ascii=False)
    lock = json.loads(golden)
    lock["tags"].insert(0, entry)
    golden = json.dumps(lock, ensure_ascii=False)

    found = guard.failures(snapshot, generated, golden, main, config, smoke, routers)
    assert any("phantom entries" in item and "made-up" in item for item in found), found
    assert not any("golden lock" in item for item in found), found
