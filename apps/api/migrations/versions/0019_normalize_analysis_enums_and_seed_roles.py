"""Normalize analysis enums and initialize the application role catalog.

Revision 0009 was published with uppercase PostgreSQL enum labels while the
ORM and worker contract use lowercase values. This forward migration repairs
already-stamped databases without rewriting that historical revision. It also
ensures a fresh or upgraded database contains every role required by RBAC.
"""

from __future__ import annotations

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | None = None
depends_on: str | None = None

_ROLE_NAMES = (
    "viewer",
    "researcher",
    "curator",
    "data_manager",
    "track_manager",
    "blast_manager",
    "seed_manager",
    "content_editor",
    "auditor",
    "administrator",
)


def _replace_enum(
    column: str,
    type_name: str,
    labels: tuple[str, ...],
    transform: str,
) -> None:
    """Replace an enum while converting existing labels deterministically."""
    previous_type = f"{type_name}_previous"
    rendered_labels = ", ".join(f"'{label}'" for label in labels)
    op.execute(f"ALTER TABLE analysis_jobs ALTER COLUMN {column} DROP DEFAULT")
    op.execute(f"ALTER TYPE {type_name} RENAME TO {previous_type}")
    op.execute(f"CREATE TYPE {type_name} AS ENUM ({rendered_labels})")
    op.execute(
        f"ALTER TABLE analysis_jobs ALTER COLUMN {column} TYPE {type_name} "
        f"USING {transform}({column}::text)::{type_name}"
    )
    op.execute(f"DROP TYPE {previous_type}")


def _seed_roles_and_backfill_users() -> None:
    values = ", ".join(f"('{role_name}')" for role_name in _ROLE_NAMES)
    op.execute(
        f"INSERT INTO roles (name) VALUES {values} "
        "ON CONFLICT (name) DO NOTHING"
    )
    op.execute(
        "UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'viewer') "
        "WHERE role_id IS NULL"
    )


def upgrade() -> None:
    """Converge legacy and drifted databases on lowercase enum values."""
    _replace_enum(
        "analysis_type",
        "analysis_type_enum",
        ("fastp", "scanpy"),
        "lower",
    )
    _replace_enum(
        "status",
        "analysis_job_status_enum",
        (
            "pending",
            "queued",
            "running",
            "succeeded",
            "failed",
            "cancel_requested",
            "cancelled",
        ),
        "lower",
    )
    op.execute(
        "ALTER TABLE analysis_jobs ALTER COLUMN status "
        "SET DEFAULT 'queued'::analysis_job_status_enum"
    )
    _seed_roles_and_backfill_users()


def downgrade() -> None:
    """Restore valid legacy uppercase enums without deleting role data."""
    _replace_enum(
        "analysis_type",
        "analysis_type_enum",
        ("FASTP", "SCANPY"),
        "upper",
    )
    _replace_enum(
        "status",
        "analysis_job_status_enum",
        (
            "PENDING",
            "QUEUED",
            "RUNNING",
            "SUCCEEDED",
            "FAILED",
            "CANCEL_REQUESTED",
            "CANCELLED",
        ),
        "upper",
    )
    op.execute(
        "ALTER TABLE analysis_jobs ALTER COLUMN status "
        "SET DEFAULT 'QUEUED'::analysis_job_status_enum"
    )
