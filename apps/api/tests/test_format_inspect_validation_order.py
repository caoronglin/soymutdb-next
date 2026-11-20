"""Request validation must precede kernel availability on /tools/sequence/inspect.

No wheel and no PostgreSQL required: bridge.require() is stubbed to always
raise 503, mirroring a deployment where the compiled extension is missing.
Malformed base64 and oversized bodies must still answer 422, not 503.
"""

from __future__ import annotations

import base64

import pytest

from app.core.exceptions import ServiceUnavailableError, SoyMutDBError
from app.schemas import sequence_tools as s
from app.services import format_inspect_service
from app.services import bio_core_bridge as bridge


@pytest.mark.asyncio
async def test_malformed_base64_422_wins_over_missing_engine(monkeypatch) -> None:
    """422 is a client-input fact; a missing wheel must not mask it as 503."""

    def _unavailable():
        raise ServiceUnavailableError("engine down")

    monkeypatch.setattr(bridge, "require", _unavailable)
    payload = s.FormatInspectRequest(fmt="fasta", data="!!!not-base64!!!")
    with pytest.raises(SoyMutDBError) as exc:
        await format_inspect_service.inspect(payload)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_oversized_payload_422_wins_over_missing_engine(monkeypatch) -> None:
    """The 1 MiB budget is enforced in Python before the kernel is required."""

    def _unavailable():
        raise ServiceUnavailableError("engine down")

    monkeypatch.setattr(bridge, "require", _unavailable)
    oversized = base64.b64encode(b"A" * (format_inspect_service.MAX_INSPECT_BYTES + 1)).decode()
    payload = s.FormatInspectRequest(fmt="fasta", data=oversized)
    with pytest.raises(SoyMutDBError) as exc:
        await format_inspect_service.inspect(payload)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_valid_payload_still_requires_the_engine(monkeypatch) -> None:
    """Reordering must not accidentally make /inspect succeed without a wheel."""

    def _unavailable():
        raise ServiceUnavailableError("engine down")

    monkeypatch.setattr(bridge, "require", _unavailable)
    payload = s.FormatInspectRequest(
        fmt="fasta", data=base64.b64encode(b">g1\nACGT\n").decode()
    )
    with pytest.raises(SoyMutDBError) as exc:
        await format_inspect_service.inspect(payload)
    assert exc.value.status_code == 503
