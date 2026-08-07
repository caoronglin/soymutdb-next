"""受控静态 fixture 驱动的 A0 contract reconciliation tests。"""

from __future__ import annotations

import json as rl_json
import sys as rl_sys
from pathlib import Path as rl_Path

rl_project_root = rl_Path(__file__).resolve().parents[4]
if str(rl_project_root) not in rl_sys.path:
    rl_sys.path.insert(0, str(rl_project_root))


def test_rl_contract_mapper_reports_route_and_unresolved_consumer(tmp_path: rl_Path) -> None:
    rl_fixture_root = tmp_path
    rl_api_path = rl_fixture_root / "apps/api/app/api/v1/search.py"
    rl_api_path.parent.mkdir(parents=True)
    rl_api_path.write_text(
        """
from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])

@router.get("")
async def global_search():
    return {}
""",
        encoding="utf-8",
    )
    (rl_fixture_root / "packages/api-client/src").mkdir(parents=True)
    (rl_fixture_root / "packages/api-client/src/search.ts").write_text(
        'export function globalSearch() { return http.get("/search"); }\n',
        encoding="utf-8",
    )

    from tools.a0.rl_reconcile_contracts import rl_reconcile_contracts

    rl_report = rl_reconcile_contracts(rl_fixture_root)
    rl_serialized = rl_json.dumps(rl_report, ensure_ascii=False, sort_keys=True)

    assert rl_report["rl_schema_version"] == "a0.contract-reconciliation.v1"
    assert rl_report["rl_status"] == "BLOCKED"
    assert any(
        rl_row["rl_route"]["rl_status"] == "observed"
        and rl_row["rl_client"]["rl_status"] == "observed"
        for rl_row in rl_report["rl_rows"]
        if rl_row["rl_relation"] == "search"
    )
    assert rl_report["rl_unresolved"]
    assert "rl_authorization_unverified" in rl_serialized
