"""Add the import-studio immutable version/edit chain."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE import_draft_status_enum AS ENUM "
        "('draft', 'validated', 'ready', 'committed', 'failed')"
    )

    op.create_table(
        "dataset_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=1024), nullable=False),
        sa.Column("license", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_objects", postgresql.JSONB(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="import_draft_status_enum", create_type=False
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["data_sets.id"],
            name=op.f("fk_dataset_versions_dataset_id_data_sets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_versions")),
        sa.UniqueConstraint(
            "dataset_id",
            "version",
            name="uq_dataset_versions_dataset_version",
        ),
    )

    op.create_table(
        "import_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("module_key", sa.String(length=80), nullable=True),
        sa.Column("filename", sa.String(length=256), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=1024), nullable=False),
        sa.Column("license", sa.String(length=256), nullable=True),
        sa.Column("mime_type", sa.String(length=128), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("column_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("field_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("validation", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                name="import_draft_status_enum", create_type=False
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_import_drafts_dataset_version_id_dataset_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_drafts")),
    )
    op.create_index(
        "ix_import_drafts_dataset_version_id",
        "import_drafts",
        ["dataset_version_id"],
    )

    op.create_table(
        "import_field_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "import_draft_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("source_field", sa.String(length=256), nullable=False),
        sa.Column("target_field", sa.String(length=256), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transform", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["import_draft_id"],
            ["import_drafts.id"],
            name=op.f("fk_import_field_mappings_import_draft_id_import_drafts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_field_mappings")),
        sa.UniqueConstraint(
            "import_draft_id",
            "source_field",
            name="uq_import_field_mappings_draft_source",
        ),
    )
    op.create_index(
        "ix_import_field_mappings_import_draft_id",
        "import_field_mappings",
        ["import_draft_id"],
    )

    op.create_table(
        "import_data_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "import_draft_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("row_key", sa.String(length=512), nullable=False),
        sa.Column("column_name", sa.String(length=256), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("patch_type", sa.String(length=32), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["import_draft_id"],
            ["import_drafts.id"],
            name=op.f("fk_import_data_patches_import_draft_id_import_drafts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_data_patches")),
    )
    op.create_index(
        "ix_import_data_patches_import_draft_id",
        "import_data_patches",
        ["import_draft_id"],
    )

    op.create_table(
        "page_data_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "dataset_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("source_id", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["page_id"],
            ["page_definitions.id"],
            name=op.f("fk_page_data_sources_page_id_page_definitions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_versions.id"],
            name=op.f("fk_page_data_sources_dataset_version_id_dataset_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_page_data_sources")),
        sa.UniqueConstraint(
            "page_id",
            "source_id",
            name="uq_page_data_sources_page_source",
        ),
    )
    op.create_index(
        "ix_page_data_sources_page_id",
        "page_data_sources",
        ["page_id"],
    )
    op.create_index(
        "ix_page_data_sources_dataset_version_id",
        "page_data_sources",
        ["dataset_version_id"],
    )

    op.create_table(
        "import_publication_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "import_draft_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["import_draft_id"],
            ["import_drafts.id"],
            name=op.f("fk_import_publication_manifests_import_draft_id_import_drafts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_publication_manifests")),
    )
    op.create_index(
        "ix_import_publication_manifests_import_draft_id",
        "import_publication_manifests",
        ["import_draft_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_import_publication_manifests_import_draft_id",
        table_name="import_publication_manifests",
    )
    op.drop_table("import_publication_manifests")
    op.drop_index(
        "ix_page_data_sources_dataset_version_id",
        table_name="page_data_sources",
    )
    op.drop_index("ix_page_data_sources_page_id", table_name="page_data_sources")
    op.drop_table("page_data_sources")
    op.drop_index(
        "ix_import_data_patches_import_draft_id",
        table_name="import_data_patches",
    )
    op.drop_table("import_data_patches")
    op.drop_index(
        "ix_import_field_mappings_import_draft_id",
        table_name="import_field_mappings",
    )
    op.drop_table("import_field_mappings")
    op.drop_index(
        "ix_import_drafts_dataset_version_id",
        table_name="import_drafts",
    )
    op.drop_table("import_drafts")
    op.drop_table("dataset_versions")
    op.execute("DROP TYPE IF EXISTS import_draft_status_enum")
