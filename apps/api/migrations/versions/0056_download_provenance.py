"""Provenance manifest columns for catalogued files and variant exports.

Published downloads and exported variant artifacts already state their
release/assembly namespace but carry no way for a downloader to verify the
bytes or cite the artifact. This adds nullable provenance columns only:

* ``sha256`` — hex digest of the exact bytes that were stored. NULL means the
  artifact predates checksum recording; it must never be shown as a real
  digest. A PostgreSQL check constraint enforces the 64-lowercase-hex shape.
* ``license`` — SPDX-ish label for the data license.
* ``generated_at`` — when the artifact was produced (distinct from the row's
  ``created_at``, which is when the record was opened).
* ``source_ref`` — free-text provenance pointer (dataset DOI/accession).

For ``variant_exports`` the worker fills ``sha256`` and ``generated_at`` when
it finalises a successful artifact. For ``download_files`` the columns are
available for the ingestion/import path to populate; this migration does not
backfill them. Both stay nullable so historical rows round-trip.

The migration is additive: downgrade drops only these columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

_TABLES = ("download_files", "variant_exports")
_SHA256_CHECK = "ck_{table}_sha256_shape"
_COLUMNS = (
    ("sha256", sa.String(64), None),
    ("license", sa.String(256), None),
    ("generated_at", sa.DateTime(timezone=True), None),
    ("source_ref", sa.String(1024), None),
)


def upgrade() -> None:
    for table in _TABLES:
        for name, type_, _ in _COLUMNS:
            op.add_column(table, sa.Column(name, type_, nullable=True))
        op.create_check_constraint(
            _SHA256_CHECK.format(table=table),
            table,
            "sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$'",
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_constraint(_SHA256_CHECK.format(table=table), table, type_="check")
        for name, _, _ in reversed(_COLUMNS):
            op.drop_column(table, name)
