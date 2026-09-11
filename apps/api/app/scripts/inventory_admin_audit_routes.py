#!/usr/bin/env python3
"""Print, but never enforce, declared-audit coverage for admin write routes.

This is an A-12 migration diagnostic. It deliberately exits zero when routes
lack declarations; A-19 may consume the same inventory after a reviewed
baseline migration and explicit CI-gate decision.
"""

from __future__ import annotations

import json

from app.api.v1.admin import router
from app.core.audit_inventory import inventory_write_routes


def main() -> None:
    items = [item.as_dict() for item in inventory_write_routes(router.routes)]
    declared = sum(item["declared"] for item in items)
    print(
        json.dumps(
            {
                "scope": "admin router write routes",
                "declared": declared,
                "undeclared": len(items) - declared,
                "routes": items,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
