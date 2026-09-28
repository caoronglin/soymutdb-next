"""No-fabrication guards for the public SRA surfaces.

The review found two ways a client could be shown invented data as if it were
the requested record:

* ``GET /sra/run/{accession}`` answered the demo accession ``SRR30334525`` from
  a bundled fixture on upstream failure, and synthesised an ``"unknown"`` stub
  for *any* other accession — indistinguishable from real metadata;
* the ``sra_run`` widget data source kept the bundled demo record and merely
  rewrote its ``Run`` field to whatever accession was requested, so an
  arbitrary SRR rendered demo metadata as real.

The contract now is: a live failure returns 503 (route) / ``run=None`` plus a
``fetch_error`` (widget). Bundled fixtures are served only when the deployment
sets ``SOYMUTDB_DEMO_FIXTURES_ENABLED=true`` **and** the request is for the
fixture's own accession.

These are pure unit tests — httpx is monkeypatched, no network is touched.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.v1 import sra as sra_routes
from app.widgets.data_sources import sra as sra_widget

_DEMO_ACCESSION = "SRR30334525"


class _FailingClient:
    """httpx.AsyncClient stand-in whose GET always raises."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FailingClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, *args: Any, **kwargs: Any):
        raise RuntimeError("network down")


@pytest.fixture()
def offline(monkeypatch):
    """Make every outbound fetch fail and disable the demo fixtures."""
    monkeypatch.setattr(sra_routes.httpx, "AsyncClient", _FailingClient)
    monkeypatch.setattr(sra_widget.httpx, "AsyncClient", _FailingClient)
    monkeypatch.setattr(sra_routes, "_fetch_run_from_ncbi", _raise_fetch)
    # No Redis either: the endpoint must still fail closed.
    monkeypatch.setattr(sra_routes, "get_redis", _NoRedis)


async def _raise_fetch(accession: str):
    return None


class _NoRedis:
    async def get(self, key: str):
        return None

    async def setex(self, *args: Any, **kwargs: Any) -> None:
        return None


def _settings(monkeypatch, *, demo: bool) -> None:
    class _S:
        demo_fixtures_enabled = demo

    monkeypatch.setattr(sra_routes, "get_settings", lambda: _S())
    monkeypatch.setattr(sra_widget, "get_settings", lambda: _S())


# ---------------------------------------------------------------------------
# Route: no fabricated record, no invented stub.
# ---------------------------------------------------------------------------


def test_unknown_accession_fails_closed_with_503(monkeypatch, offline):
    _settings(monkeypatch, demo=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(sra_routes.get_sra_run("SRR999999"))

    assert excinfo.value.status_code == 503
    assert "SRR999999" in str(excinfo.value.detail)


def test_demo_accession_is_not_answered_from_a_fixture_by_default(monkeypatch, offline):
    """Ablation: the fallback branch used to serve this unconditionally."""
    _settings(monkeypatch, demo=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(sra_routes.get_sra_run(_DEMO_ACCESSION))

    assert excinfo.value.status_code == 503


def test_demo_accession_is_served_only_in_explicit_demo_mode(monkeypatch, offline):
    _settings(monkeypatch, demo=True)

    payload = asyncio.run(sra_routes.get_sra_run(_DEMO_ACCESSION))

    assert payload["source"] == "demo"
    assert payload["run"]["Run"] == _DEMO_ACCESSION


def test_demo_mode_does_not_answer_a_different_accession(monkeypatch, offline):
    """Demo mode must not widen to arbitrary accessions."""
    _settings(monkeypatch, demo=True)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(sra_routes.get_sra_run("SRR111111"))

    assert excinfo.value.status_code == 503


def test_samples_endpoint_is_disabled_outside_demo_mode(monkeypatch):
    _settings(monkeypatch, demo=False)

    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(sra_routes.list_soybean_samples())

    assert excinfo.value.status_code == 404


def test_samples_endpoint_is_labelled_demo_in_demo_mode(monkeypatch):
    _settings(monkeypatch, demo=True)

    payload = asyncio.run(sra_routes.list_soybean_samples())

    assert payload["source"] == "demo"
    assert payload["total"] >= 1


# ---------------------------------------------------------------------------
# Widget: never rewrite the fixture's accession.
# ---------------------------------------------------------------------------


def test_widget_returns_an_unavailable_context_on_fetch_failure(monkeypatch):
    """Ablation: the widget used to keep the demo record and rewrite ``Run``."""
    _settings(monkeypatch, demo=False)

    ctx = asyncio.run(sra_widget.sra_run_context({"run": "SRR999999"}))

    assert ctx["run"] is None
    assert ctx["run_accession"] == "SRR999999"
    assert ctx["fetch_error"]
    assert ctx["is_fallback"] is False


def test_widget_never_attaches_demo_metadata_to_another_accession(monkeypatch):
    """Even in demo mode an unrelated accession must not get fixture data."""
    _settings(monkeypatch, demo=True)

    ctx = asyncio.run(sra_widget.sra_run_context({"run": "SRR999999"}))

    assert ctx["run"] is None
    assert ctx["is_fallback"] is False
    assert "SRR999999" in ctx["fetch_error"]


def test_widget_serves_the_fixture_only_for_its_own_accession_in_demo_mode(monkeypatch):
    _settings(monkeypatch, demo=True)

    ctx = asyncio.run(sra_widget.sra_run_context({"run": _DEMO_ACCESSION}))

    assert ctx["run"] is not None
    assert ctx["run"]["Run"] == _DEMO_ACCESSION
    assert ctx["is_fallback"] is True


# ---------------------------------------------------------------------------
# Template: the context renders in every state without inventing a record.
# ---------------------------------------------------------------------------


def _render(**context: Any) -> str:
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates = Path(sra_widget.__file__).parent.parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template("sra_run.html").render(**context)


def test_template_renders_an_explicit_unavailable_state_without_a_record():
    html = _render(
        run=None,
        run_accession="SRR999999",
        fetch_error="SRA metadata is temporarily unavailable.",
        is_fallback=False,
    )

    assert 'data-source="unavailable"' in html
    assert "SRR999999" in html
    # No field of the bundled fixture leaked into the page.
    assert "Zea mays" not in html


def test_template_labels_demo_data_as_demo():
    html = _render(
        run={
            "Run": _DEMO_ACCESSION,
            "sra_url": "https://trace.ncbi.nlm.nih.gov/Traces/sra?run=" + _DEMO_ACCESSION,
            "ScientificName": "Zea mays",
            "ReleaseDate": "2024-01-02",
            "Consent": "public",
        },
        run_accession=_DEMO_ACCESSION,
        fetch_error="demo",
        is_fallback=True,
    )

    assert 'data-source="demo"' in html
    assert "Zea mays" in html
