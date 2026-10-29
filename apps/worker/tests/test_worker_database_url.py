"""The worker's DSN normalisation.

The worker declares ``psycopg2-binary`` and not ``psycopg``. SQLAlchemy 2
resolves a *bare* ``postgresql://`` to the psycopg v3 dialect, so an
unqualified DSN — the worker's own default, and the shape a deployment most
likely writes — would fail with "No module named 'psycopg'" instead of
connecting.
"""

from __future__ import annotations

import pytest

from soymutdb_worker.utils import db as worker_db


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("postgresql://user:pw@localhost:5432/soymutdb", "postgresql+psycopg2://user:pw@localhost:5432/soymutdb"),
        ("postgres://user:pw@localhost:5432/soymutdb", "postgresql+psycopg2://user:pw@localhost:5432/soymutdb"),
        ("postgresql+asyncpg://user:pw@localhost:5432/soymutdb", "postgresql+psycopg2://user:pw@localhost:5432/soymutdb"),
        ("postgresql+psycopg://user:pw@localhost:5432/soymutdb", "postgresql+psycopg2://user:pw@localhost:5432/soymutdb"),
        ("postgresql+psycopg2://user:pw@localhost:5432/soymutdb", "postgresql+psycopg2://user:pw@localhost:5432/soymutdb"),
    ],
)
def test_the_dsn_always_names_the_driver_the_worker_installs(monkeypatch, configured, expected):
    monkeypatch.setattr(worker_db, "get_setting", lambda name, default=None: configured)

    assert worker_db.get_database_url() == expected
