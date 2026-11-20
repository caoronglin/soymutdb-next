"""Guard the offline artifact-E2E sweep.

The sweep exists because eleven Playwright configs were not CI-wired and rotted
silently. The contracts are deliberately structural: every offline config that
serves a built artifact must appear in the sweep, and the sweep must fail closed
(nonzero on a failing gate, missing artifact, or unknown gate).

Offline gates are the configs that point the webServer at a dist tree. The
deployed-stack configs (production, jbrowse, admin-console, portal-embed,
local-preview, default online smoke) are intentionally excluded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-artifact-e2e.sh"
PACKAGE = ROOT / "package.json"

OFFLINE_GATES = (
    "public",
    "internal",
    "admin-production",
    "admin-shell",
    "entity-detail",
    "visual",
    "web-performance",
    "primer",
    "jbrowse-artifact",
    # Serves the gh-pages-shaped tree from build-pages-artifact.sh, mounted under
    # /soymutdb-next. It is skipped with a reason when pages-dist/ is absent, but
    # it is a sweep member and this list is what keeps the two in step.
    "subpath-artifact",
)


def test_sweep_lists_every_offline_gate_once() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^GATES=\(([^)]*)\)", text, re.MULTILINE)
    assert match, "verify-artifact-e2e.sh must declare a GATES=(...) array"
    gates = match.group(1).split()
    assert gates == list(OFFLINE_GATES), (
        f"artifact sweep gates drifted: {gates} != {list(OFFLINE_GATES)}"
    )
    for gate in gates:
        assert (ROOT / "e2e" / f"playwright-{gate}.config.ts").is_file(), (
            f"gate {gate} has no e2e/playwright-{gate}.config.ts"
        )


def test_sweep_serves_only_built_artifacts() -> None:
    for gate in OFFLINE_GATES:
        config = (ROOT / "e2e" / f"playwright-{gate}.config.ts").read_text(encoding="utf-8")
        assert "webServer" in config, f"{gate} must start its own artifact server"
        assert "static-server.mjs" in config or "admin-static-server.mjs" in config, (
            f"{gate} must serve a built artifact through the repo static server"
        )
        # A deployed base may be an *optional* override, but the gate must work
        # with nothing exported: every sweep config defaults to localhost.
        assert "localhost" in config or "127.0.0.1" in config, (
            f"{gate} must default to a local artifact origin"
        )
        assert "dist" in config, f"{gate} must serve a built dist tree"


def test_sweep_fails_closed_and_is_wired_in_package_json() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    assert 'exit 1' in text, "a failing gate must exit nonzero"
    assert "exit 2" in text, "missing artifacts/unknown gates must exit nonzero"
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    assert scripts.get("verify:artifact-e2e") == "bash scripts/verify-artifact-e2e.sh"
