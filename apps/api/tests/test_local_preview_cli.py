"""Preview data-directory configuration is resolved at parser construction."""

from pathlib import Path

import pytest

from app.scripts.import_local_test_preview import DEFAULT_DATA_DIR_ENV, _parser

_ARGS = ["--database-url", "postgresql+asyncpg://localhost/preview", "--allow-local-test-db"]


@pytest.mark.parametrize("value", [None, ""])
def test_data_directory_is_required_without_environment_default(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(DEFAULT_DATA_DIR_ENV, raising=False)
    else:
        monkeypatch.setenv(DEFAULT_DATA_DIR_ENV, value)
    with pytest.raises(SystemExit) as exc:
        _parser().parse_args(_ARGS)
    assert exc.value.code == 2


def test_environment_default_and_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv(DEFAULT_DATA_DIR_ENV, str(tmp_path))
    assert _parser().parse_args(_ARGS).data_dir == tmp_path
    explicit = tmp_path / "explicit"
    assert _parser().parse_args([*_ARGS, "--data-dir", str(explicit)]).data_dir == explicit


def test_parser_observes_updated_environment(monkeypatch):
    monkeypatch.setenv(DEFAULT_DATA_DIR_ENV, "/data/first")
    assert _parser().parse_args(_ARGS).data_dir == Path("/data/first")
    monkeypatch.setenv(DEFAULT_DATA_DIR_ENV, "/data/second")
    assert _parser().parse_args(_ARGS).data_dir == Path("/data/second")
