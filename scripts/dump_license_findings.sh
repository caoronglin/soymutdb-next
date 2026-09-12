#!/usr/bin/env bash
# Temporary diagnostic: print the normalized license findings so a failing CI
# run names the packages it rejected.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"
for report in api worker mcp-server; do
  echo "=== ${report} findings ==="
  cat "artifacts/dependency-audit/python-licenses-${report}.findings.log" 2>/dev/null || echo "(none)"
done
python3 - <<'PY'
import json
for app in ("api", "worker", "mcp-server"):
    path = f"artifacts/dependency-audit/python-licenses-{app}.json"
    try:
        entries = json.load(open(path))
    except Exception as exc:
        print(app, "unreadable", exc); continue
    print(f"=== {app}: {len(entries)} packages ===")
    for entry in entries:
        lic = str(entry.get("License"))
        if lic not in ("MIT", "MIT License", "BSD-3-Clause", "Apache-2.0",
                       "Apache Software License", "BSD License", "ISC License (ISCL)",
                       "Mozilla Public License 2.0 (MPL 2.0)", "Python Software Foundation License",
                       "The Unlicense (Unlicense)", "Apache License 2.0"):
            print("  ?", entry.get("Name"), entry.get("Version"), repr(lic))
PY
