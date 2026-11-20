"""Public source attribution must not disclose credential URLs or local paths."""

import pytest

from soymutdb_jobs.blast_catalog import public_source_url


@pytest.mark.parametrize("value", [
    None, 123, "", "/private/source.fa", "file:///private/source.fa", "s3://private/input.fa",
    "https://user:secret@soybase.org/data", "https://soybase.org/data?token=secret",
    "https://soybase.org/data#private/path", "http://localhost/source",
    "http://index.internal/source", "https://127.0.0.1/source", "https://10.0.0.1/source",
    "https://[::1]/source", "https://soybase.org:invalid/source", "https://soybase.org\n/source",
    "https://soybase.org\\private/source",
])
def test_unsafe_source_metadata_is_omitted(value):
    assert public_source_url(value) is None


@pytest.mark.parametrize("value", [
    "https://soybase.org/data", "https://www.ncbi.nlm.nih.gov/genbank/fastaformat/",
])
def test_public_attribution_is_preserved(value):
    assert public_source_url(value) == value
