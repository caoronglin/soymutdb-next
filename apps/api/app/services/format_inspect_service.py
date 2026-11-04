"""Bounded format validation using the Rust noodles adapters.

Bytes arrive as base64 in the request body; no path, URL or object key is ever
accepted.  The Python layer enforces the size budget before handing bytes to
the kernel.
"""

from __future__ import annotations

import base64
import binascii

import anyio.to_thread

from ..core.exceptions import ValidationError
from ..schemas import sequence_tools as s
from . import bio_core_bridge as bridge

MAX_INSPECT_BYTES = 1_048_576


def _decode(data: str) -> bytes:
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("data must be valid base64") from exc
    if len(raw) > MAX_INSPECT_BYTES:
        raise ValidationError("inspect payload exceeds the 1 MiB limit")
    return raw


async def inspect(payload: s.FormatInspectRequest) -> s.FormatInspectResponse:
    core = bridge.require()
    raw = _decode(payload.data)
    fn = {
        "fasta": "validate_fasta",
        "fastq": "validate_fastq",
        "bed": "validate_bed",
    }[payload.fmt]
    try:
        result = await anyio.to_thread.run_sync(lambda: getattr(core, fn)(raw))
    except core.BioCoreException as exc:
        raise bridge.translate_error(exc) from exc

    st = bridge.status()
    meta = s.EngineMetadata(
        engine=st.engine or "unavailable",
        engine_version=st.engine_version or "unavailable",
    )
    if payload.fmt == "bed":
        return s.FormatInspectResponse(
            fmt=payload.fmt,
            valid=True,
            record_count=int(result),
            truncated=False,
            records=[],
            engine=meta,
        )
    records = [
        {"name": name, "length": length} for name, length in result["records"]
    ]
    return s.FormatInspectResponse(
        fmt=payload.fmt,
        valid=True,
        record_count=int(result["total_records"]),
        truncated=bool(result["truncated"]),
        records=records,
        engine=meta,
    )
