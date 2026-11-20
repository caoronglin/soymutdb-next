"""The kernel's error vocabulary must survive the trip to the client.

The frontend keys on ``error.details.code`` -- it is the only field that says
*which* input to change.  That makes the code set a public contract, and a
contract nothing exercised, because the tests that existed only asserted two
errors out of the ten the kernel can raise.

Every expectation here is DERIVED from ``packages/bio-core/src/errors.rs`` at
collection time, so the file cannot drift from the kernel: adding a code to the
Rust enum without teaching this file how to trigger it fails the suite, and
deleting a code from the bridge's message table fails it too.
``scripts/check_bio_core_error_codes.py`` guards the same binding from the
source side, without needing a wheel or CPython 3.15.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from app.api.v1.tools_sequence import router
from app.core.exceptions import SoyMutDBError, soy_mut_db_exception_handler
from app.services import bio_core_bridge as bridge
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

WHEEL_AVAILABLE = importlib.util.find_spec("soymutdb_bio_core") is not None
requires_wheel = pytest.mark.skipif(
    not WHEEL_AVAILABLE, reason="compiled bio-core wheel not installed"
)

ERRORS_RS = (
    Path(__file__).resolve().parents[3] / "packages/bio-core/src/errors.rs"
)


def kernel_codes() -> dict[str, str]:
    """{code: sentence} straight out of the Rust error enum."""
    body = re.sub(r"//[^\n]*", "", ERRORS_RS.read_text(encoding="utf-8"))
    sentences = {
        variant: message
        for message, variant in re.findall(
            r'#\[error\("((?:[^"\\]|\\.)*)"\)\]\s*([A-Za-z_]\w*)', body
        )
    }
    return {
        code: sentences[variant]
        for variant, code in re.findall(
            r'Self::([A-Za-z_]\w*)\s*=>\s*"([A-Z0-9_]+)"', body
        )
    }


#: How to make the kernel raise each code through a real HTTP request.  A
#: mapping, not a list, so a new Rust code fails collection until it is covered.
TRIGGERS: dict[str, tuple[str, dict]] = {
    "EMPTY_SEQUENCE": (
        "/api/v1/tools/sequence/reverse-complement",
        {"sequence": "", "alphabet": "dna", "preserve_case": False},
    ),
    "INVALID_CHARACTER": (
        "/api/v1/tools/sequence/reverse-complement",
        {"sequence": "ACGT#", "alphabet": "dna", "preserve_case": False},
    ),
    "UNSUPPORTED_ALPHABET": (
        "/api/v1/tools/sequence/reverse-complement",
        {"sequence": "ACGT", "alphabet": "protein", "preserve_case": False},
    ),
    "SEQUENCE_TOO_LONG": (
        "/api/v1/tools/sequence/kmers",
        {"sequence": "A" * 200_000, "k": 32, "max_items": 5},
    ),
    "BUDGET_EXCEEDED": (
        "/api/v1/tools/sequence/kmers",
        {"sequence": "AC" * 4000, "k": 1, "max_items": 1},
    ),
    "INVALID_INTERVAL": (
        "/api/v1/tools/sequence/align",
        {"query": "ACGT", "target": "ACGT", "mode": "local",
         "scoring": {"match": 1, "mismatch": -1, "gap_open": 0, "gap_extend": 0}},
    ),
    "COORDINATE_OVERFLOW": (
        "/api/v1/tools/sequence/align",
        {"query": "ACGT", "target": "ACGT", "mode": "global",
         "scoring": {"match": 1, "mismatch": -1, "gap_open": 2**40, "gap_extend": 1}},
    ),
    "UNSUPPORTED_PARAMETER": (
        "/api/v1/tools/sequence/translate",
        {"sequence": "ATG", "genetic_code_id": 1, "frame": 0},
    ),
    # Code 7 is absent from every codon table both engines ship. Code 11 used
    # to stand here, but it is a real bacterial table the Biopython engine
    # supports, so asking for it is a valid request now.
    "UNKNOWN_GENETIC_CODE": (
        "/api/v1/tools/sequence/translate",
        {"sequence": "ATG", "genetic_code_id": 7},
    ),
    "INVALID_RECORD": (
        "/api/v1/tools/sequence/inspect",
        {"fmt": "fasta", "data": "bm90IGEgZmFzdGE="},
    ),
}


def _app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    return application


@pytest.fixture
async def client():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_every_kernel_code_has_a_trigger() -> None:
    """Derivation, not enumeration: the Rust enum is the source of truth."""
    codes = kernel_codes()
    assert codes, "errors.rs parsed to an empty code set"
    assert set(TRIGGERS) == set(codes), (
        "every kernel code needs an HTTP trigger; missing "
        f"{sorted(set(codes) - set(TRIGGERS))}, stale "
        f"{sorted(set(TRIGGERS) - set(codes))}"
    )


def test_bridge_mirrors_the_kernel_sentences() -> None:
    """The message table is a mirror of errors.rs, not a second opinion."""
    assert bridge.KERNEL_ERROR_MESSAGES == kernel_codes()


@pytest.mark.parametrize("code", sorted(kernel_codes()))
def test_kernel_code_reaches_the_client_verbatim(code: str) -> None:
    """A kernel rejection is a 422 whose ``details.code`` is the kernel's code."""
    if not WHEEL_AVAILABLE:  # pragma: no cover - covered by the skip marker below
        pytest.skip("compiled bio-core wheel not installed")

    from app.services import bio_core_bridge as real_bridge

    exc = real_bridge._load().BioCoreException(code, "kernel sentence")
    mapped = real_bridge.translate_error(exc)
    envelope = mapped.details
    assert envelope["code"] == code
    assert mapped.message == kernel_codes()[code]
    assert mapped.status_code == 422


def test_foreign_exception_cannot_forge_a_code() -> None:
    """A non-kernel exception has no machine code, so it must not invent one.

    Regression: the bridge accepted ``args[0]`` whenever it was a string, so
    ``Exception("timeout")`` published ``details.code == "timeout"`` and the
    client rendered a code the vocabulary never contained.
    """
    for exc in (
        Exception("timeout"),
        ValueError("connection reset"),
        RuntimeError("EMPTY_SEQUENCE"),  # right shape, wrong object
    ):
        mapped = bridge.translate_error(exc)
        assert mapped.details["code"] == "validation_error", exc
        assert mapped.message == "invalid sequence tool request"
        assert "timeout" not in mapped.message


def test_single_arity_exception_is_not_trusted() -> None:
    """The kernel raises ``(code, message)``; one element is not that shape."""
    mapped = bridge.translate_error(Exception("EMPTY_SEQUENCE"))
    assert mapped.details["code"] == "validation_error"


def test_non_string_pair_is_not_trusted() -> None:
    """A tuple of non-strings is an FFI accident, not a machine code."""
    mapped = bridge.translate_error(Exception(("EMPTY_SEQUENCE", 42)))
    assert mapped.details["code"] == "validation_error"


@requires_wheel
@pytest.mark.asyncio
async def test_unknown_genetic_code_is_reported_over_http(client: AsyncClient) -> None:
    """End-to-end: the message says what to fix instead of the generic text."""
    path, payload = TRIGGERS["UNKNOWN_GENETIC_CODE"]
    r = await client.post(path, json=payload)
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"]["code"] == "UNKNOWN_GENETIC_CODE"
    assert error["message"] == "genetic code is not implemented"
