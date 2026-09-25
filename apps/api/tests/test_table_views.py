"""Table-view resolution and admin CRUD contracts.

Two properties are load-bearing and get their own tests:

1. **Resolution order** — a release-pinned template beats the deployment-wide
   one, which beats the built-in default, and an unknown *kind* never silently
   renders every column.
2. **Visibility** — the external site variant never receives an internal-only
   layout, and the cross-assembly homolog columns are opt-in rather than part of
   the default (so an unimplemented column never reads as a missing value).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Release, ReleaseStatus, TableViewTemplate
from app.schemas.table_views import (
    SpeciesInstanceCreate,
    TableColumn,
    TableViewTemplateCreate,
    TableViewTemplateUpdate,
)
from app.services import table_views_service as service

pytestmark = pytest.mark.integration


def _column(key: str, visible: bool = True) -> TableColumn:
    return TableColumn(key=key, label_zh=key, label_en=key, visible=visible)


def _create(**overrides) -> TableViewTemplateCreate:
    payload = {
        "kind": "mutation_sites",
        "name": "mutation sites",
        "species": "Glycine max",
        "site_variant": "external",
        "release_id": None,
        "is_default": False,
        "columns": [_column("mutant_line_name")],
        "notes": None,
    }
    payload.update(overrides)
    return TableViewTemplateCreate(**payload)


async def _release(db: AsyncSession, name: str) -> Release:
    release = Release(name=name, version=name, status=ReleaseStatus.PUBLISHED)
    db.add(release)
    await db.commit()
    await db.refresh(release)
    return release


def test_builtin_default_hides_cross_assembly_homolog_columns() -> None:
    resolved = service.resolve_builtin("mutation_sites", "Glycine max", "external", None)

    keys = [column.key for column in resolved.columns]
    assert keys == [
        "mutant_line_name",
        "mutation_system",
        "chromosome",
        "position",
        "confidence",
        "gene_id",
        "feature",
        "available",
    ]
    # The optional trailing actions are enabled, but the homolog columns that a
    # deployment may not have imported are not — they must be opted in.
    assert resolved.actions.jbrowse is True
    assert resolved.actions.genome_preview is True
    assert not any(key for key in keys if key.startswith("W82") or key.startswith("DN53"))


@pytest.mark.asyncio
async def test_release_scoped_template_wins_over_deployment_wide(
    db_session: AsyncSession,
) -> None:
    await service.create_template(db_session, _create(name="site wide", is_default=True))
    release = await _release(db_session, "2026.09")
    await service.create_template(
        db_session,
        _create(name="release pinned", release_id=int(release.id)),
    )

    resolved = await service.resolve_template(
        db_session,
        kind="mutation_sites",
        species="Glycine max",
        site_variant="external",
        release_id=int(release.id),
    )

    assert resolved.template_name == "release pinned"
    assert resolved.release_id == int(release.id)

    # A different release falls back to the deployment-wide template.
    other = await service.resolve_template(
        db_session,
        kind="mutation_sites",
        species="Glycine max",
        site_variant="external",
        release_id=None,
    )
    assert other.template_name == "site wide"


@pytest.mark.asyncio
async def test_internal_layout_is_not_served_to_the_external_variant(
    db_session: AsyncSession,
) -> None:
    await service.create_template(
        db_session,
        _create(name="internal layout", site_variant="internal", is_default=True),
    )

    external = await service.resolve_template(
        db_session,
        kind="mutation_sites",
        species="Glycine max",
        site_variant="external",
        release_id=None,
    )
    # No external template exists → the built-in default, never the internal one.
    assert external.is_builtin_default is True

    internal = await service.resolve_template(
        db_session,
        kind="mutation_sites",
        species="Glycine max",
        site_variant="internal",
        release_id=None,
    )
    assert internal.template_name == "internal layout"


@pytest.mark.asyncio
async def test_unknown_kind_falls_back_to_the_builtin_default(
    db_session: AsyncSession,
) -> None:
    # An operator cannot conjure a layout for a table the contract does not
    # define; the portal keeps rendering the built-in columns instead.
    resolved = await service.resolve_template(
        db_session,
        kind="variants",
        species="Glycine max",
        site_variant="external",
        release_id=None,
    )
    assert resolved.is_builtin_default is True
    assert [column.key for column in resolved.columns][0] == "variant_id"


@pytest.mark.asyncio
async def test_promoting_a_template_demotes_the_previous_default(
    db_session: AsyncSession,
) -> None:
    first = await service.create_template(
        db_session, _create(name="first", is_default=True)
    )
    second = await service.create_template(
        db_session, _create(name="second", is_default=True)
    )

    defaults = (
        (
            await db_session.execute(
                select(TableViewTemplate).where(TableViewTemplate.is_default.is_(True))
            )
        )
        .scalars()
        .all()
    )
    assert [template.id for template in defaults] == [second.id]


@pytest.mark.asyncio
async def test_template_update_replaces_the_ordered_column_set(
    db_session: AsyncSession,
) -> None:
    created = await service.create_template(db_session, _create(name="v1"))

    updated = await service.update_template(
        db_session,
        created.id,
        TableViewTemplateUpdate(columns=[_column("gene_id"), _column("chromosome")]),
    )

    # ``columns`` is a JSONB column, so the service stores plain dicts; the
    # ordered key list is what the renderer consumes.
    assert [column["key"] for column in updated.columns] == ["gene_id", "chromosome"]


@pytest.mark.asyncio
async def test_species_instance_registry_keeps_exactly_one_local(
    db_session: AsyncSession,
) -> None:
    await service.create_species_instance(
        db_session,
        SpeciesInstanceCreate(
            code="soy",
            name="Soybean",
            species="Glycine max",
            api_base_url="https://api.soy.example.org",
            is_local=True,
        ),
    )
    await service.create_species_instance(
        db_session,
        SpeciesInstanceCreate(
            code="maize",
            name="Maize",
            species="Zea mays",
            api_base_url="https://api.maize.example.org",
            is_local=True,
        ),
    )

    instances = await service.list_species_instances(db_session)
    local = [instance for instance in instances if instance.is_local]
    assert [instance.code for instance in local] == ["maize"]
    assert {instance.code for instance in instances} == {"soy", "maize"}


def test_template_kind_is_validated() -> None:
    with pytest.raises(ValueError):
        TableViewTemplateCreate(
            kind="not_a_table",  # type: ignore[arg-type]
            name="bogus",
            columns=[_column("mutant_line_name")],
        )
