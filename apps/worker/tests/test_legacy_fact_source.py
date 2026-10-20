"""The historical backfill reads the legacy store over HTTPS, not a driver.

Every case runs against a mock HTTP transport, so the suite needs neither a
ClickHouse server nor the legacy driver on the interpreter.
"""

from __future__ import annotations

import ast
import inspect
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from soymutdb_worker import legacy_fact_source as legacy
from soymutdb_worker import native_backfill
from soymutdb_worker.legacy_fact_source import (
    LegacySourceConfig,
    LegacySourceError,
    http_fact_source,
    parse_fact_row,
)
from soymutdb_worker.tasks.variant_finalize import BASE_COLUMNS

SOURCE = Path(__file__).resolve().parents[1] / "src/soymutdb_worker/legacy_fact_source.py"

CONFIG = LegacySourceConfig(
    url="https://legacy.example.org:8443/",
    database="soymutdb",
    user="backfill_reader",
    password="s3cr3t-key",
)
ENV = {
    "BACKFILL_CLICKHOUSE_URL": CONFIG.url,
    "BACKFILL_CLICKHOUSE_DATABASE": CONFIG.database,
    "BACKFILL_CLICKHOUSE_USER": CONFIG.user,
    "BACKFILL_CLICKHOUSE_PASSWORD": CONFIG.password,
}


def _fact(**overrides):
    row = {
        "variant_id": 1,
        "release_key": "v5.0",
        "assembly_key": "v5",
        "chromosome": "1",
        "position": 1000,
        "ref_allele": "A",
        "alt_allele": "T",
        "variant_type": "SNV",
        "variant_subtype": "",
        "length": 1,
        "gene_id": "G1",
        "gene_symbol": "G1",
        "gene_surrogate_id": 7,
        "mutant_line_surrogate_id": 3,
        "mutant_line_name": "",
        "consequence": "missense",
        "consequence_id": 2,
        "impact": "MODERATE",
        "rs_id": "",
        "quality_score": 12.5,
        "filter_status": "PASS",
        "read_depth": 30,
        "allele_frequency": 0.25,
        "hgvs_c": "",
        "hgvs_p": "",
        "zygosity": "het",
    }
    row.update(overrides)
    return row


def _payload(*rows, terminate=True):
    body = "".join(json.dumps(row) + "\n" for row in rows)
    if not terminate:
        body = body[:-1]
    return body.encode("utf-8")


class FakeResponse:
    """Minimal stand-in for the object urllib hands back."""

    def __init__(self, payload: bytes = b"") -> None:
        self._payload = payload
        self.closed = False

    def read1(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload)
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk

    def read(self, size: int = -1) -> bytes:
        return self.read1(size)

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    """Mock opener: records requests, hands back canned responses."""

    def __init__(self, *responses, error: Exception | None = None) -> None:
        self.responses = list(responses)
        self.error = error
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[object] = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]

    @property
    def request(self) -> urllib.request.Request:
        return self.requests[0]


def _params(request) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))


def test_query_is_one_bound_readonly_select():
    transport = FakeTransport(FakeResponse(_payload(_fact())))

    rows = list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    assert [row[0] for row in rows] == [1]
    request = transport.request
    body = request.data.decode("utf-8")
    assert request.get_method() == "POST"
    assert body == legacy.build_query()
    assert "SELECT " + ", ".join(BASE_COLUMNS) in body
    assert "WHERE release_key = {release:String}" in body
    assert "ORDER BY variant_id FORMAT JSONEachRow" in body
    assert _params(request) == {
        "database": "soymutdb",
        "readonly": "1",
        "max_block_size": "1000",
        "output_format_json_quote_64bit_integers": "0",
        "param_release": "v5.0",
    }
    assert transport.timeouts == [CONFIG.timeout]


def test_source_never_sends_a_mutating_statement():
    query = legacy.build_query()
    lowered = query.lower()

    for keyword in ("insert", "alter", "drop", "optimize", "truncate", "delete", "create"):
        assert keyword not in lowered
    assert ";" not in query


def test_hostile_release_version_stays_a_bound_parameter():
    hostile = "v5' OR 1=1 --"
    transport = FakeTransport(FakeResponse(_payload(_fact())))

    list(http_fact_source(CONFIG, hostile, opener=transport.open)())

    request = transport.request
    assert hostile not in request.data.decode("utf-8")
    assert "OR 1=1" not in request.full_url
    assert _params(request)["param_release"] == hostile
    assert request.data.decode("utf-8") == legacy.build_query()


def test_credentials_travel_in_headers_and_never_in_the_url():
    transport = FakeTransport(FakeResponse())

    list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    request = transport.request
    assert CONFIG.password not in request.full_url
    assert CONFIG.user not in request.full_url
    assert request.get_header("X-clickhouse-key") == CONFIG.password
    assert request.get_header("X-clickhouse-user") == CONFIG.user


def test_rows_are_returned_in_base_column_order():
    transport = FakeTransport(
        FakeResponse(_payload(_fact(gene_symbol="Gly"), _fact(variant_id=2, position=43)))
    )

    rows = list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    first = dict(zip(BASE_COLUMNS, rows[0], strict=True))
    assert first["gene_symbol"] == "Gly"
    assert first["variant_id"] == 1
    assert dict(zip(BASE_COLUMNS, rows[1], strict=True))["position"] == 43


def test_uint64_maximum_identity_is_accepted():
    transport = FakeTransport(
        FakeResponse(_payload(_fact(variant_id=18446744073709551615)))
    )

    row = next(iter(http_fact_source(CONFIG, "v5.0", opener=transport.open)()))

    assert row[BASE_COLUMNS.index("variant_id")] == 18446744073709551615


@pytest.mark.parametrize(
    ("override", "column"),
    [
        ({"variant_id": 18446744073709551616}, "variant_id"),
        ({"variant_id": -1}, "variant_id"),
        ({"variant_id": "18446744073709551615"}, "variant_id"),
        ({"variant_id": 1.0}, "variant_id"),
        ({"position": 18446744073709551616}, "position"),
        ({"read_depth": 4294967296}, "read_depth"),
        ({"length": 1.5}, "length"),
        ({"quality_score": "12.5"}, "quality_score"),
        ({"allele_frequency": None}, "allele_frequency"),
        ({"chromosome": 1}, "chromosome"),
        ({"zygosity": True}, "zygosity"),
    ],
)
def test_out_of_contract_values_are_rejected(override, column):
    transport = FakeTransport(FakeResponse(_payload(_fact(**override))))

    with pytest.raises(LegacySourceError, match=column):
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("column", ["quality_score", "allele_frequency"])
def test_non_finite_floats_are_rejected_before_reaching_postgres(value, column):
    transport = FakeTransport(FakeResponse(_payload(_fact(**{column: value}))))

    with pytest.raises(LegacySourceError, match=column):
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())


def test_whole_float_from_clickhouse_is_accepted_as_a_number():
    row = parse_fact_row(_fact(quality_score=12, allele_frequency=0))

    assert row[BASE_COLUMNS.index("quality_score")] == 12.0
    assert isinstance(row[BASE_COLUMNS.index("allele_frequency")], float)


def test_missing_and_unexpected_columns_are_rejected():
    missing = _fact()
    del missing["hgvs_p"]
    with pytest.raises(LegacySourceError, match="missing"):
        parse_fact_row(missing)

    with pytest.raises(LegacySourceError, match="unexpected"):
        parse_fact_row({**_fact(), "release_id": 1})


def test_non_object_row_is_rejected():
    with pytest.raises(LegacySourceError, match="JSON object"):
        parse_fact_row([1, 2, 3])


def test_truncated_stream_is_rejected():
    transport = FakeTransport(FakeResponse(_payload(_fact(), terminate=False)))

    with pytest.raises(LegacySourceError, match="incomplete row"):
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())


def test_malformed_json_is_rejected():
    transport = FakeTransport(FakeResponse(b'{"variant_id":1,\n'))

    with pytest.raises(LegacySourceError, match="JSONEachRow"):
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())


def test_invalid_utf8_is_rejected():
    transport = FakeTransport(FakeResponse(b'{"variant_id":"\xff"}\n'))

    with pytest.raises(LegacySourceError, match="UTF-8"):
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())


def test_row_without_a_newline_is_capped_by_the_byte_guard():
    response = FakeResponse(b'{"chromosome":"' + b"x" * 4096)
    transport = FakeTransport(response)

    with pytest.raises(LegacySourceError, match="512 byte limit"):
        list(http_fact_source(CONFIG, "v5.0", max_row_bytes=512, opener=transport.open)())
    assert response.closed is True


def test_stream_is_closed_when_the_consumer_stops_early():
    response = FakeResponse(_payload(_fact(), _fact(variant_id=2), _fact(variant_id=3)))
    rows = http_fact_source(CONFIG, "v5.0", opener=FakeTransport(response).open)()

    iterator = iter(rows)
    assert next(iterator)[0] == 1
    iterator.close()

    assert response.closed is True


def test_stream_is_closed_when_a_row_fails_validation():
    response = FakeResponse(_payload(_fact(variant_id="1")))

    with pytest.raises(LegacySourceError):
        list(http_fact_source(CONFIG, "v5.0", opener=FakeTransport(response).open)())

    assert response.closed is True


def test_each_call_reads_a_fresh_snapshot():
    transport = FakeTransport(
        FakeResponse(_payload(_fact())),
        FakeResponse(_payload(_fact(), _fact(variant_id=2))),
    )
    rows = http_fact_source(CONFIG, "v5.0", opener=transport.open)

    assert len(list(rows())) == 1
    assert len(list(rows())) == 2
    assert len(transport.requests) == 2
    assert transport.requests[0].data == transport.requests[1].data


def test_http_error_message_leaks_neither_url_nor_credentials():
    transport = FakeTransport(error=urllib.error.HTTPError(CONFIG.url, 403, "Forbidden", {}, None))

    with pytest.raises(LegacySourceError) as excinfo:
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    message = str(excinfo.value)
    assert "403" in message
    assert CONFIG.password not in message
    assert CONFIG.user not in message
    assert "example.org" not in message


def test_redirects_are_refused_so_credentials_are_never_forwarded():
    elsewhere = "https://attacker.example.net/collect"
    transport = FakeTransport(
        error=urllib.error.HTTPError(elsewhere, 302, "Found", {"Location": elsewhere}, None)
    )

    with pytest.raises(LegacySourceError) as excinfo:
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    assert "redirect" in str(excinfo.value)
    assert elsewhere not in str(excinfo.value)
    assert len(transport.requests) == 1


def test_default_transport_verifies_tls_and_refuses_redirects():
    opener = legacy._default_opener()

    assert any(isinstance(handler, legacy._NoRedirectHandler) for handler in opener.handlers)
    https_handlers = [
        handler for handler in opener.handlers
        if isinstance(handler, urllib.request.HTTPSHandler)
    ]
    assert https_handlers
    context = https_handlers[0]._context
    assert context.verify_mode
    assert context.check_hostname


def test_transport_failure_message_is_sanitised():
    reason = urllib.error.URLError("refusing https://legacy.example.org with s3cr3t-key")
    transport = FakeTransport(error=reason)

    with pytest.raises(LegacySourceError) as excinfo:
        list(http_fact_source(CONFIG, "v5.0", opener=transport.open)())

    assert str(excinfo.value) == "Legacy fact source transport failed"


@pytest.mark.parametrize("missing", sorted(ENV))
def test_configuration_has_no_defaults(missing):
    env = dict(ENV)
    env.pop(missing)

    with pytest.raises(LegacySourceError, match=missing):
        LegacySourceConfig.from_env(env)


def test_configuration_from_environment_is_explicit():
    env = {**ENV, "BACKFILL_CLICKHOUSE_TIMEOUT": "12.5"}

    config = LegacySourceConfig.from_env(env)

    assert config == LegacySourceConfig(
        url=ENV["BACKFILL_CLICKHOUSE_URL"],
        database=ENV["BACKFILL_CLICKHOUSE_DATABASE"],
        user=ENV["BACKFILL_CLICKHOUSE_USER"],
        password=ENV["BACKFILL_CLICKHOUSE_PASSWORD"],
        timeout=12.5,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://legacy.example.org:8123/",
        "https://backfill_reader:s3cr3t-key@legacy.example.org/",
        "https://legacy.example.org/?database=other",
        "https://",
    ],
)
def test_configuration_rejects_insecure_or_credential_bearing_urls(url):
    with pytest.raises(LegacySourceError):
        LegacySourceConfig(url=url, database="soymutdb", user="backfill_reader", password="")


def test_configuration_rejects_a_non_numeric_timeout():
    with pytest.raises(LegacySourceError, match="BACKFILL_CLICKHOUSE_TIMEOUT"):
        LegacySourceConfig.from_env({**ENV, "BACKFILL_CLICKHOUSE_TIMEOUT": "soon"})


@pytest.mark.parametrize("url", ["http://127.0.0.1:8123/", "http://[::1]:8123/"])
def test_configuration_accepts_only_literal_loopback_for_plain_http(url):
    config = LegacySourceConfig(url=url, database="soymutdb", user="reader", password="local")
    assert config.url == url


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), True, 0, -1])
def test_configuration_rejects_unbounded_or_invalid_timeout(timeout):
    with pytest.raises(LegacySourceError):
        LegacySourceConfig(url=CONFIG.url, database="soymutdb", user="reader",
                           password="local", timeout=timeout)


def test_source_module_never_imports_the_legacy_driver():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    imported = _imported_module_names(tree)

    assert not {name for name in imported if name.startswith("clickhouse_connect")}


def test_cli_module_has_no_legacy_driver_import_at_all():
    source = Path(inspect.getfile(native_backfill)).read_text(encoding="utf-8")

    assert not {name for name in _imported_module_names(ast.parse(source))
                if name.startswith("clickhouse_connect")}
    assert "import clickhouse_connect" not in source
    assert "clickhouse_connect.get_client" not in source


def test_legacy_driver_source_factory_is_kept_for_compatibility():
    assert list(inspect.signature(native_backfill.clickhouse_source).parameters) == [
        "client",
        "source_version",
    ]


def test_apply_requires_source_frozen(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "native_backfill",
        "--release-id", "1",
        "--source-version", "v5.0",
        "--assembly-map", '{"v5":5}',
        "--apply",
    ])

    with pytest.raises(SystemExit) as excinfo:
        native_backfill.main()

    assert excinfo.value.code == 2
    assert "--apply requires --source-frozen" in capsys.readouterr().err


def test_cli_fails_loudly_when_the_source_is_not_configured(monkeypatch, capsys):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", [
        "native_backfill",
        "--release-id", "1",
        "--source-version", "v5.0",
        "--assembly-map", '{"v5":5}',
        "--source-frozen",
    ])

    with pytest.raises(SystemExit) as excinfo:
        native_backfill.main()

    assert excinfo.value.code == 2
    assert "BACKFILL_CLICKHOUSE_URL" in capsys.readouterr().err


def _imported_module_names(tree: ast.AST) -> set[str]:
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    names |= {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    return names
