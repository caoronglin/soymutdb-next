"""Resolution of configurable table views.

The public path resolves, in order:

1. a template pinned to the caller's ``species`` + ``site_variant`` + ``release``;
2. a template pinned to ``species`` + ``site_variant`` with ``release_id IS NULL``
   (the deployment-wide layout for that site variant);
3. the built-in default below.

The built-in default is the column order required by the product contract: the
identifying columns first, then the assembly-scoped biological coordinates, then
the confidence and availability flags. The cross-assembly homolog columns
(W82_V2 / W82_V4 / DN53_V1 …) are **not** in the default: an operator adds them
per template, because they are only meaningful for an instance that actually
imported those crosswalk rows, and a silently empty homolog column reads as a
missing observation rather than an unimplemented feature.
"""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.table_views import SpeciesInstance, TableViewTemplate
from ..schemas.table_views import (
    ResolvedTableView,
    SpeciesInstanceCreate,
    SpeciesInstanceUpdate,
    TableActions,
    TableColumn,
    TableViewTemplateCreate,
    TableViewTemplateUpdate,
)

TableKind = Literal["mutation_sites", "variants", "genes", "mutant_lines"]

TABLE_KINDS: tuple[TableKind, ...] = (
    "mutation_sites",
    "variants",
    "genes",
    "mutant_lines",
)

# Ordered built-in layout for the mutation-site table. Keys are the exact
# field names the API row payload exposes, so a client renders `row[key]`.
BUILTIN_DEFAULT_COLUMNS: dict[TableKind, list[TableColumn]] = {
    "mutation_sites": [
        TableColumn(key="mutant_line_name", label_zh="株系", label_en="Mutant line"),
        TableColumn(
            key="mutation_system",
            label_zh="突变体系（株系母+位置）",
            label_en="Mutation system (line + position)",
        ),
        TableColumn(key="chromosome", label_zh="染色体号", label_en="Chromosome"),
        TableColumn(key="position", label_zh="位点", label_en="Position"),
        TableColumn(key="confidence", label_zh="可信度", label_en="Confidence"),
        TableColumn(key="gene_id", label_zh="基因号", label_en="Gene ID"),
        TableColumn(key="feature", label_zh="特征", label_en="Feature"),
        TableColumn(key="available", label_zh="可获得", label_en="Available"),
    ],
    "variants": [
        TableColumn(key="variant_id", label_zh="变异 ID", label_en="Variant ID"),
        TableColumn(key="chromosome", label_zh="染色体号", label_en="Chromosome"),
        TableColumn(key="position", label_zh="位点", label_en="Position"),
        TableColumn(key="ref", label_zh="参考等位", label_en="Ref"),
        TableColumn(key="alt", label_zh="替代等位", label_en="Alt"),
        TableColumn(key="variant_type", label_zh="类型", label_en="Type"),
        TableColumn(key="impact", label_zh="影响", label_en="Impact"),
        TableColumn(key="gene_id", label_zh="基因号", label_en="Gene ID"),
    ],
    # The search-result order is the one the product contract fixed: assembly,
    # chromosome, position, mutation feature, gene id, then the action column.
    # The gene *index* page reorders these through its own template when it
    # wants a different emphasis.
    "genes": [
        TableColumn(key="assembly_name", label_zh="基因组版本", label_en="Genome version"),
        TableColumn(key="chromosome", label_zh="染色体号", label_en="Chromosome"),
        TableColumn(key="position", label_zh="位点", label_en="Position"),
        TableColumn(key="variant_count", label_zh="突变特征", label_en="Mutation feature"),
        TableColumn(key="gene_id", label_zh="基因 ID", label_en="Gene ID"),
    ],
    "mutant_lines": [
        TableColumn(key="public_id", label_zh="株系", label_en="Mutant line"),
        TableColumn(key="name", label_zh="名称", label_en="Name"),
        TableColumn(key="mutagen", label_zh="诱变剂", label_en="Mutagen"),
        TableColumn(key="cultivar", label_zh="品种", label_en="Cultivar"),
        TableColumn(key="generation", label_zh="世代", label_en="Generation"),
    ],
}

BUILTIN_DEFAULT_ACTIONS: dict[TableKind, TableActions] = {
    "mutation_sites": TableActions(jbrowse=True, genome_preview=True),
    "variants": TableActions(jbrowse=True, genome_preview=False),
    "genes": TableActions(jbrowse=True, genome_preview=False),
    "mutant_lines": TableActions(jbrowse=False, genome_preview=False),
}

BUILTIN_DEFAULT_NAME = "builtin-default"


def builtin_columns(kind: TableKind) -> list[TableColumn]:
    return [column.model_copy(deep=True) for column in BUILTIN_DEFAULT_COLUMNS[kind]]


def builtin_actions(kind: TableKind) -> TableActions:
    return BUILTIN_DEFAULT_ACTIONS[kind].model_copy(deep=True)


def resolve_builtin(
    kind: TableKind, species: str, site_variant: str, release_id: int | None
) -> ResolvedTableView:
    return ResolvedTableView(
        kind=kind,
        species=species,
        site_variant=site_variant,  # type: ignore[arg-type]
        release_id=release_id,
        template_id=None,
        template_name=BUILTIN_DEFAULT_NAME,
        is_builtin_default=True,
        columns=builtin_columns(kind),
        actions=builtin_actions(kind),
    )


def _to_resolved(
    template: TableViewTemplate, kind: TableKind, site_variant: str
) -> ResolvedTableView:
    columns = [
        TableColumn.model_validate(column) for column in (template.columns or [])
    ]
    return ResolvedTableView(
        kind=kind,
        species=template.species,
        site_variant=site_variant,  # type: ignore[arg-type]
        release_id=template.release_id,
        template_id=template.id,
        template_name=template.name,
        is_builtin_default=False,
        columns=columns,
        actions=TableActions.model_validate(template.actions or {}),
    )


async def resolve_template(
    db: AsyncSession,
    *,
    kind: TableKind,
    species: str,
    site_variant: str,
    release_id: int | None,
) -> ResolvedTableView:
    """Resolve the layout for one table on the public read path."""
    if kind not in TABLE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown table kind: {kind}",
        )

    # Most specific first: a release-pinned template wins over the
    # deployment-wide one for the same site variant.
    statement = (
        select(TableViewTemplate)
        .where(
            TableViewTemplate.kind == kind,
            TableViewTemplate.species == species,
            TableViewTemplate.site_variant == site_variant,
        )
        # Most specific first: a release-pinned row sorts before the
        # deployment-wide (NULL) row for the same kind/species/site variant.
        # `is_(None).asc()` would sort NULLs *first* in PostgreSQL, so the
        # specificity is expressed as an explicit rank instead.
        .order_by(
            case((TableViewTemplate.release_id.is_(None), 0), else_=1).desc(),
            TableViewTemplate.is_default.desc(),
            TableViewTemplate.updated_at.desc(),
            TableViewTemplate.id.desc(),
        )
        .limit(1)
    )
    if release_id is not None:
        statement = statement.where(
            or_(
                TableViewTemplate.release_id == release_id,
                TableViewTemplate.release_id.is_(None),
            )
        )
    else:
        # No release context (e.g. an unauthenticated catalogue read): only the
        # deployment-wide layout is eligible, never a release-pinned one.
        statement = statement.where(TableViewTemplate.release_id.is_(None))

    result = await db.execute(statement)
    template = result.scalars().first()
    if template is None:
        return resolve_builtin(kind, species, site_variant, release_id)
    return _to_resolved(template, kind, site_variant)


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


async def list_templates(
    db: AsyncSession,
    *,
    kind: TableKind | None = None,
    species: str | None = None,
) -> list[TableViewTemplate]:
    statement = select(TableViewTemplate)
    if kind is not None:
        statement = statement.where(TableViewTemplate.kind == kind)
    if species is not None:
        statement = statement.where(TableViewTemplate.species == species)
    result = await db.execute(statement.order_by(TableViewTemplate.id))
    return list(result.scalars().all())


async def create_template(
    db: AsyncSession, payload: TableViewTemplateCreate
) -> TableViewTemplate:
    template = TableViewTemplate(
        kind=payload.kind,
        name=payload.name,
        species=payload.species,
        site_variant=payload.site_variant,
        release_id=payload.release_id,
        is_default=payload.is_default,
        columns=[column.model_dump() for column in payload.columns],
        actions=payload.actions.model_dump(),
        notes=payload.notes,
    )
    db.add(template)
    # Flush so the new row has its id: the demotion filter excludes the new
    # default *by id*, and an unflushed row would leave the id NULL, which
    # SQLAlchemy renders as `IS NOT NULL` — demoting every other template.
    await db.flush()
    if payload.is_default:
        await _demote_other_defaults(
            db, template, payload.kind, payload.species, payload.site_variant
        )
    await db.commit()
    await db.refresh(template)
    return template


async def update_template(
    db: AsyncSession, template_id: int, payload: TableViewTemplateUpdate
) -> TableViewTemplate:
    template = await db.get(TableViewTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    if payload.name is not None:
        template.name = payload.name
    if payload.columns is not None:
        template.columns = [column.model_dump() for column in payload.columns]
    if payload.actions is not None:
        template.actions = payload.actions.model_dump()
    if payload.is_default is not None:
        template.is_default = payload.is_default
        if payload.is_default:
            await _demote_other_defaults(
                db, template, template.kind, template.species, template.site_variant
            )
    if payload.release_id is not None:
        template.release_id = payload.release_id
    if payload.notes is not None:
        template.notes = payload.notes

    await db.commit()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template_id: int) -> None:
    template = await db.get(TableViewTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
    await db.delete(template)
    await db.commit()


async def _demote_other_defaults(
    db: AsyncSession,
    winner: TableViewTemplate,
    kind: str,
    species: str,
    site_variant: str,
) -> None:
    """Exactly one default per (kind, species, site_variant, release scope)."""
    from sqlalchemy import update

    statement = (
        update(TableViewTemplate)
        .where(
            TableViewTemplate.id != winner.id,
            TableViewTemplate.kind == kind,
            TableViewTemplate.species == species,
            TableViewTemplate.site_variant == site_variant,
            TableViewTemplate.is_default.is_(True),
        )
        .values(is_default=False)
    )
    await db.execute(statement)


async def list_species_instances(db: AsyncSession) -> list[SpeciesInstance]:
    result = await db.execute(select(SpeciesInstance).order_by(SpeciesInstance.code))
    return list(result.scalars().all())


async def create_species_instance(
    db: AsyncSession, payload: SpeciesInstanceCreate
) -> SpeciesInstance:
    if payload.is_local:
        await _clear_local_flag(db)
    instance = SpeciesInstance(**payload.model_dump())
    db.add(instance)
    await db.commit()
    await db.refresh(instance)
    return instance


async def update_species_instance(
    db: AsyncSession, instance_id: int, payload: SpeciesInstanceUpdate
) -> SpeciesInstance:
    instance = await db.get(SpeciesInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    updates = payload.model_dump(exclude_unset=True)
    if (
        ("api_base_url" in updates and updates["api_base_url"] != instance.api_base_url)
        or ("is_local" in updates and updates["is_local"] != instance.is_local)
    ):
        # Health status belongs to a specific origin and role. Never carry a
        # previous peer's successful check onto a newly registered endpoint.
        instance.connection_state = "unknown"
        instance.last_checked_at = None
        instance.last_error_at = None
        instance.last_error_code = None
    for field, value in updates.items():
        setattr(instance, field, value)
    if payload.is_local:
        await _clear_local_flag(db, keep_id=instance.id)
    await db.commit()
    await db.refresh(instance)
    return instance


async def delete_species_instance(db: AsyncSession, instance_id: int) -> None:
    instance = await db.get(SpeciesInstance, instance_id)
    if instance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    await db.delete(instance)
    await db.commit()


async def _clear_local_flag(db: AsyncSession, keep_id: int | None = None) -> None:
    from sqlalchemy import update

    statement = update(SpeciesInstance).where(SpeciesInstance.is_local.is_(True))
    if keep_id is not None:
        statement = statement.where(SpeciesInstance.id != keep_id)
    await db.execute(statement.values(is_local=False))


__all__ = [
    "BUILTIN_DEFAULT_COLUMNS",
    "TABLE_KINDS",
    "TableKind",
    "builtin_actions",
    "builtin_columns",
    "create_species_instance",
    "create_template",
    "delete_species_instance",
    "delete_template",
    "list_species_instances",
    "list_templates",
    "resolve_builtin",
    "resolve_template",
    "update_species_instance",
    "update_template",
]
