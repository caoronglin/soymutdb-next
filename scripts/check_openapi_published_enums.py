#!/usr/bin/env python3
"""Every value domain the OpenAPI snapshot publishes must be the one the source declares.

``openapi.json`` and ``openapi.d.ts`` are both exports of ``app.main:app``, so a
guard that compares them to each other proves self-consistency, not truth.
Retype a value domain in the snapshot **and** regenerate the client from that
edited snapshot, and ``scripts/check-contract.sh``'s export==snapshot diff stays
green while the published contract advertises a value the model never declares.
The offline guards that do read the snapshot (#154's 422 guard, #168's body
guard, #169's auth surface, #171's error envelope) all stop at *which* schema a
response names; none of them looks inside a field's value domain.

The authoritative side is the Python source, read here with :mod:`ast`; the
published side is the committed snapshot. Both directions fail: a member the
source declares and the snapshot omits (a regenerated client narrows to a value
the API really sends), and a member the snapshot invents (a client branch for a
value that never arrives). Those comparisons are two half-views of one tree, so
a coordinated edit to source and snapshot (add, drop, retype, or a ``True -> 1``
type weakening) stays green. ``_PUBLISHED_ENUM_BASELINE`` is an independent
literal pin of every published domain, compared with type identity, so the pin
means "publishes exactly this"; a legitimate change must move the literal in
the same commit and say why.

The pin walks the *whole* snapshot, not just ``components.schemas``: a path or
query parameter can publish an inline ``enum`` (the ``{kind}`` table-view
selector is one today). Such a domain has no source-side comparison here at all,
so a coordinated regenerate of the model, the snapshot and the generated client
moves all three halves together with nothing left to object.

The snapshot has three spellings for one declared ``Literal``, and a guard that
knows only one of them is a guard that mostly passes:

* ``enum`` -- a field the model makes required, or an ``anyOf``/``oneOf`` branch;
* ``const`` -- a single-member ``Literal``, which pydantic folds into a constant;
* ``$defs`` -- pydantic copies any ``$ref``-ed model into the referencing
  schema, so a constrained field can be published twice and the second copy is
  checked here too.

``StrEnum``/``Enum`` classes are read as class bodies and matched to the schema
they become. The handful of classes pydantic flattens inline instead of giving
a component are named in ``INLINED_ENUM_CLASSES``: an enum class that is NOT on
that list must publish a component, because "the component is absent" is the
exact co-revert a guard like this exists to catch. A ``Literal`` whose members
are not statically recoverable (a comprehension over a runtime enum, an
``Annotated``/validator composition) is reported as unverifiable rather than
silently dropped.

Usage:
    python3 scripts/check_openapi_published_enums.py
    python3 scripts/check_openapi_published_enums.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import copy
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = Path("packages/api-client/openapi.json")
SCHEMA_ROOT = Path("apps/api/app/schemas")

_LITERAL_NAMES = frozenset({"Literal"})
_ENUM_BASES = frozenset({"str", "int", "Enum", "StrEnum", "IntEnum"})
# A member the source declares through a spelling this guard cannot resolve.
UNVERIFIABLE = "<unverifiable>"

# Models whose fields reach the snapshot inline (as a request body) rather than
# as a component of their own. Verified on live `main`: no key of these names
# exists under `components.schemas`, and none of their member values appears
# anywhere else in `openapi.json` either -- so there is nothing published to
# compare against, and saying so is more honest than a green.
INLINED_MODELS = frozenset(
    {
        # Only ever used as a request body; pydantic publishes its fields inline
        # and defines no component. Verified: neither the name nor any of its
        # member values ("performance", "needs-improvement", ...) appears
        # anywhere in the committed openapi.json, so there is nothing published
        # to compare against -- named here rather than counted as a pass.
        "WebVitalEvent",
        # Abstract bases. They are published through their subclasses
        # (`EnrichmentResponse(mode="ora")`, `EnrichmentGseaResponse(mode="gsea")`)
        # and the snapshots of those subclasses ARE compared; pydantic defines no
        # component for the base itself, so its own entry has nothing to check.
        "EnrichmentCalculationResponse",
        "EnrichmentGseaCalculationResponse",
    }
)

# Enum classes pydantic publishes inline (as a bare ``enum``/``const`` on the
# referencing field) instead of as a named ``components.schemas`` entry. This
# list is a reviewed, independent fixed point: absence from the snapshot is
# NEVER allowed to prove an exemption. Without it, ``inline_classes`` was
# derived from the very artifact being guarded, so deleting a real enum
# component (source + both exports in step) reclassified the enum as inline
# and the check stayed green while ``compared`` silently dropped. Verified on
# live ``main``: exactly these 8 of the 26 source enum classes have no
# component; the other 18 must keep theirs.
INLINED_ENUM_CLASSES = frozenset(
    {
        "AssemblyMetricReason",
        "GeneFeatureType",
        "SeedAvailability",
        "SeedRequestStatus",
        "SortOrder",
        "_Availability",
        "_EvidenceKind",
        "_SectionState",
    }
)
# Exact published value domains, an independent fixed point.  Read the
# committed snapshot on both sides of the comparisons below and every
# coordinated edit is invisible: add, drop or retype a member in the source and
# the snapshot together, and the two halves still agree.  ``True == 1`` in
# Python, so a bare ``!=`` is also blind to a boolean leaf silently republished
# as an integer.  This literal is NOT derived from either half -- update it in
# the same commit as an intentional change and say why, exactly like
# ``_ERROR_RESPONSE_BASELINE`` / ``_SNAPSHOT_FLOOR`` / ``_PAGINATION_BASELINE``.
#
# Keys are the schema path to the ``enum`` / ``const`` holder; values are the
# ordered domain lists.  ``_same`` compares types recursively as well as values.
_PUBLISHED_ENUM_BASELINE: dict[str, list[list[Any]]] = {
    'AdminSiteBrandResponse.properties.variant': [['external', 'internal']],
    'AnalysesSubmitResponse.properties.status': [['queued']],
    'AnalysesUploadResponse.properties.upload_method': [['POST']],
    'AnalysisJobStatus': [
        ['pending', 'queued', 'running', 'succeeded', 'failed', 'cancel_requested', 'cancelled'],
    ],
    'AnalysisType': [['fastp', 'scanpy']],
    'AnnotationTerm.properties.kind': [
        ['experimental', 'curated', 'predicted', 'transferred', 'imported', 'unknown'],
    ],
    'AnnotationTerm.properties.ontology': [['go', 'kegg']],
    'ArtifactRequest.properties.artifact_type': [['msa', 'tree']],
    'ArtifactResponse.properties.artifact_type': [['msa', 'tree']],
    'ArtifactResponse.properties.state': [['pending', 'running', 'succeeded', 'failed']],
    'BlastDatabaseResponse.properties.build_status': [
        ['pending', 'building', 'validating', 'publishing', 'published', 'failed', 'ready'],
    ],
    'BlastDatabaseResponse.properties.engine': [['diamond', 'ncbi_blast']],
    'BlastDatabaseResponse.properties.sequence_type.anyOf': [
        [
           'genome', 'cds', 'transcript', 'protein', 'repeat_masked', 'pan_genome',
           'family_consensus', 'custom',
        ],
    ],
    'BlastGenomeTargetResponse.properties.reason.anyOf': [
        [
           'job_not_completed', 'authorization_failed', 'unsupported_program',
           'subject_not_found', 'ambiguous_subject', 'assembly_mismatch',
           'no_genomic_coordinates', 'invalid_subject_id',
        ],
    ],
    'BlastGenomeTargetResponse.properties.resolution.anyOf': [
        ['gene_accession', 'gene_alias', 'transcript_id'],
    ],
    'BlastGenomeTargetResponse.properties.status': [['resolved', 'unresolved']],
    'BlastIndexBuildRequest.properties.db_type': [['nucl', 'prot']],
    'BlastIndexBuildRequest.properties.sequence_type': [
        [
           'genome', 'cds', 'transcript', 'protein', 'repeat_masked', 'pan_genome',
           'family_consensus', 'custom',
        ],
    ],
    'BlastIndexBuildResponse.properties.db_type': [['nucl', 'prot']],
    'BlastIndexBuildResponse.properties.state': [
        ['pending', 'building', 'validating', 'publishing', 'published', 'failed', 'ready'],
    ],
    'BlastJobResponse.properties.engine': [['ncbi_blast', 'diamond']],
    'BlastJobStatus': [['pending', 'running', 'completed', 'failed', 'cancelled', 'expired']],
    'BlastProgram': [['blastn', 'blastp', 'blastx', 'tblastn', 'tblastx']],
    'BlastSubmitProgram': [['blastn', 'blastp', 'blastx', 'tblastn', 'tblastx']],
    'BlastSubmitRequest.properties.engine': [['ncbi_blast', 'diamond']],
    'ConsequenceType': [
        [
           'missense_variant', 'stop_gained', 'synonymous_variant', 'frameshift_variant',
           'inframe_insertion', 'inframe_deletion', 'splice_donor_variant',
           'splice_acceptor_variant', 'intron_variant', '5_prime_UTR_variant',
           '3_prime_UTR_variant', 'upstream_gene_variant', 'downstream_gene_variant',
           'intergenic_variant', 'start_lost', 'stop_lost',
        ],
    ],
    'DataPatchItem.properties.patch_type': [['set', 'clear', 'format']],
    'DatabaseCapabilitiesResponse.properties.analytics.anyOf': [['postgresql']],
    'DatabaseCapabilitiesResponse.properties.authoritative': [['postgresql']],
    'EnrichmentGseaResponse.properties.mode': [['gsea']],
    'EnrichmentGseaResponse.properties.ontology': [['go', 'kegg']],
    'EnrichmentRequest.properties.mode': [['ora', 'gsea']],
    'EnrichmentRequest.properties.ontology': [['go', 'kegg']],
    'EnrichmentResponse.properties.mode': [['ora']],
    'EnrichmentResponse.properties.ontology': [['go', 'kegg']],
    'EvidenceTag.properties.kind': [
        ['experimental', 'curated', 'predicted', 'transferred', 'imported', 'unknown'],
    ],
    'ExpPatternRequest.properties.scale': [['zscore', 'none']],
    'ExpPatternResponse.properties.clustering': [['input', 'hierarchical', 'mean_sort', 'none']],
    'ExpPatternResponse.properties.scale': [['zscore', 'none']],
    'ExternalArticlePlatform': [['wechat', 'xmol']],
    'FamilyDetailResponse.properties.level': [['gene_family', 'gene_subfamily']],
    'FamilyMemberResponse.properties.relationship_type': [
        ['one_to_one', 'one_to_many', 'many_to_many'],
    ],
    'FamilyResponse.properties.level': [['gene_family', 'gene_subfamily']],
    'FooterNavigationLink.properties.target': [['internal', 'external']],
    'FormatInspectRequest.properties.fmt': [['fasta', 'fastq', 'bed']],
    'FormatInspectResponse.properties.fmt': [['fasta', 'fastq', 'bed']],
    'GwasFileType': [['snp', 'other']],
    'GwasJobStatus': [['pending', 'running', 'completed', 'failed', 'cancelled']],
    'GwasMethod': [['emmax', 'gemma']],
    'HomologRecord.properties.homolog_type': [['ortholog', 'paralog']],
    'HomologRecord.properties.kind': [
        ['experimental', 'curated', 'predicted', 'transferred', 'imported', 'unknown'],
    ],
    'ImpactLevel': [['HIGH', 'MODERATE', 'LOW', 'MODIFIER']],
    'ImportCommitRequest.properties.confirm': [[True]],
    'ImportCreateRequest.properties.type': [
        [
           'vcf', 'gff3', 'fasta', 'blast_db', 'seed_data', 'expression_csv', 'homolog_csv',
           'module_tsv',
        ],
    ],
    'ImportInspectionResponse.properties.schema_version': [[1]],
    'InlineTarget.properties.kind': [['inline']],
    'KmerRequest.properties.ambiguity_policy': [['skip', 'reject']],
    'LocalTestPreviewMeta.properties.annotation_version': [['Wm82.a6.v1']],
    'LocalTestPreviewMeta.properties.coordinate_system': [['1-based-inclusive']],
    'LocalTestPreviewMeta.properties.preview': [[True]],
    'LocalTestPreviewMeta.properties.publication_status': [['unpublished']],
    'MatchHit.properties.strand': [['+', '-']],
    'MatchType': [['exact', 'alias', 'cross-version', 'text']],
    'MediaAssetStatus': [['pending', 'ready', 'archived']],
    'MultipartStartRequest.properties.type': [
        [
           'vcf', 'gff3', 'fasta', 'blast_db', 'seed_data', 'expression_csv', 'homolog_csv',
           'module_tsv',
        ],
    ],
    'NewsStatus': [['draft', 'published', 'archived']],
    'OrfCandidate.properties.strand': [['+', '-']],
    'OrthologRecord.properties.homolog_type': [['ortholog', 'paralog']],
    'OrthologRecord.properties.relationship_type': [['one_to_one', 'one_to_many', 'many_to_many']],
    'OrthologResponse.properties.state': [['available', 'no_data', 'not_imported']],
    'OverlapRequest.properties.annotation_type': [['gene']],
    'OverlapRequest.properties.coordinate_system': [['1-based-inclusive']],
    'OverlapRequest.properties.mode': [['hits', 'count']],
    'OverlapResponse.properties.coordinate_system': [['1-based-inclusive']],
    'PageDefinitionStatusEnum': [['draft', 'preview', 'requested', 'published']],
    'PageStatus': [['draft', 'published', 'archived']],
    'PluginRoute.properties.method': [['GET', 'POST', 'PUT', 'PATCH', 'DELETE']],
    'PreviewAssembly.properties.name': [['Gmax_880_v6.0']],
    'PreviewAssembly.properties.species': [['Glycine max']],
    'PreviewAssembly.properties.status': [['unpublished']],
    'PreviewAssembly.properties.version': [['v6.0']],
    'PreviewDatasetSource.properties.key': [['03_soymut-a6-test']],
    'PreviewGeneItem.properties.strand': [['+', '-']],
    'PreviewGeneSearchResponse.properties.annotation_version': [['Wm82.a6.v1']],
    'PreviewGeneSearchResponse.properties.preview': [[True]],
    'PreviewGeneSearchResponse.properties.publication_status': [['unpublished']],
    'PreviewMutationSiteItem.properties.confidence': [['H', 'L']],
    'PreviewMutationSiteSearchResponse.properties.annotation_version': [['Wm82.a6.v1']],
    'PreviewMutationSiteSearchResponse.properties.coordinate_system': [['1-based-inclusive']],
    'PreviewMutationSiteSearchResponse.properties.preview': [[True]],
    'PreviewMutationSiteSearchResponse.properties.publication_status': [['unpublished']],
    'PublicationStatus': [
        [
           'requested', 'building', 'validating', 'deploying', 'published', 'failed',
           'rolled_back', 'superseded',
        ],
    ],
    'PublicationTarget': [['local', 'github_pages', 'cloudflare_pages']],
    'ReleaseActionRequest.properties.confirm': [[True]],
    'ReleaseStatus': [
        [
           'draft', 'validated', 'ready', 'published', 'rolled_back', 'validated', 'published',
           'rolled_back',
        ],
    ],
    'ResolvedTableView.properties.site_variant': [['external', 'internal']],
    'ReverseComplementRequest.properties.alphabet': [['dna', 'rna', 'protein']],
    'ReverseComplementResponse.properties.alphabet': [['dna', 'rna', 'protein']],
    'SearchResultType': [['gene', 'variant', 'mutant_line', 'phenotype', 'publication']],
    'SectionStatus.properties.section': [
        ['annotation', 'homolog', 'expression', 'variants', 'phenotype', 'literature'],
    ],
    'SectionStatus.properties.state': [['available', 'empty', 'not_imported']],
    'SequenceAlignRequest.properties.alphabet': [['dna', 'rna', 'protein']],
    'SequenceAlignRequest.properties.mode': [['local', 'global', 'semiglobal']],
    'SequenceAlignResponse.properties.coordinate_system': [['1-based-inclusive']],
    'SequenceAlignResponse.properties.mode': [['local', 'global', 'semiglobal']],
    'SequenceAvailability.properties.availability': [['available', 'unavailable']],
    'SequenceAvailability.properties.molecule': [['genomic', 'cds', 'transcript', 'protein']],
    'SequenceMatchRequest.properties.alphabet': [['dna', 'rna', 'protein']],
    'SequenceMatchRequest.properties.iupac_mode': [['literal']],
    'SequenceMatchRequest.properties.mode': [['exact', 'approximate']],
    'SequenceMatchResponse.properties.coordinate_system': [['1-based-inclusive']],
    'SequenceMatchResponse.properties.method': [['exact', 'approximate']],
    'SequenceStatsRequest.properties.alphabet': [['dna', 'rna', 'protein']],
    'SequenceStatsRequest.properties.ambiguous_gc_policy': [['exclude', 'include']],
    'SettingFieldSchema.properties.kind': [
        ['string', 'color', 'integer', 'boolean', 'enum', 'email', 'url', 'uuid'],
    ],
    'SettingFieldSchema.properties.permission': [['administrator']],
    'SettingFieldSchema.properties.redaction': [['none', 'omit']],
    'SettingFieldSchema.properties.scope': [['global']],
    'SettingsHistoryItem.properties.action': [['patch', 'put_compat', 'rollback']],
    'SettingsSchemaResponse.properties.version': [[1]],
    'SettingsValidateResponse.properties.valid': [[True]],
    'SiteBrandResponse.properties.variant': [['external', 'internal']],
    'SiteVariant': [['external', 'internal']],
    'SpeciesCoverageResponse.properties.state': [['available', 'no_data', 'not_imported']],
    'SpeciesInstanceHealthResponse.properties.connection_state': [
        ['unknown', 'healthy', 'unhealthy', 'disabled', 'unconfigured'],
    ],
    'SpeciesInstanceHealthResponse.properties.remote_management': [['local', 'registration_only']],
    'SpeciesInstanceResponse.properties.connection_state': [
        ['unknown', 'healthy', 'unhealthy', 'disabled', 'unconfigured'],
    ],
    'SpeciesInstanceResponse.properties.remote_management': [['local', 'registration_only']],
    'Strand': [['+', '-']],
    'TableViewTemplateCreate.properties.kind': [
        ['mutation_sites', 'variants', 'genes', 'mutant_lines'],
    ],
    'TableViewTemplateCreate.properties.site_variant': [['external', 'internal']],
    'TableViewTemplateResponse.properties.site_variant': [['external', 'internal']],
    'TranscriptPartResponse.properties.kind': [['cds', 'utr5', 'utr3']],
    'UploadPresignResponse.properties.upload_method': [['POST']],
    'UserCreate.properties.role_name': [['viewer']],
    'VariantType': [['SNP', 'INS', 'DEL', 'MNV', 'SV']],
    'WidgetCategoryEnum': [
        [
           'hero', 'navigation', 'search', 'data_table', 'detail', 'visualization', 'stats',
           'external', 'layout', 'custom',
        ],
    ],
    'WidgetPermissionEnum': [['public', 'authenticated', 'admin']],
    'app__models__seed_request__SeedRequestStatus': [
        ['pending', 'approved', 'rejected', 'fulfilled'],
    ],
    'app__schemas__seed__SeedRequestStatus': [
        ['pending', 'approved', 'shipped', 'completed', 'rejected'],
    ],
    'paths./api/v1/table-views/{kind}.get.parameters.schema': [
        ['mutation_sites', 'variants', 'genes', 'mutant_lines'],
    ],
}


class _Unresolvable:
    """A declared value domain the guard cannot turn into a member list."""

    def __init__(self, why: str) -> None:
        self.why = why


EnumSpec = list[Any] | _Unresolvable


def _without_none(members: list[Any]) -> list[Any]:
    """Drop the ``None`` that ``Literal[...] | None`` adds.

    The snapshot publishes an optional field as ``anyOf: [enum, {type: null}]``,
    so ``None`` is the null branch's job and never an enum member. Keeping it in
    the expected set makes every nullable Literal look like a dropped member.
    """
    return [member for member in members if member is not None]


# ---------------------------------------------------------------------------
# Source side
# ---------------------------------------------------------------------------


def _const_value(
    node: ast.AST | None, constants: dict[str, ast.AST], enums: dict[str, list[Any]] | None = None
) -> Any:
    """Resolve a bare name to a module-level constant, or ``UNVERIFIABLE``."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        target = constants.get(node.id)
        if target is None:
            return UNVERIFIABLE
        return _const_value(target, constants, enums)
    if enums is not None:
        enum_name = _all_strings(node)
        if enum_name is not None:
            return enums.get(enum_name, UNVERIFIABLE)
    if isinstance(node, (ast.Tuple, ast.List)):
        out: list[Any] = []
        for element in node.elts:
            value = _const_value(element, constants)
            if value is UNVERIFIABLE:
                return UNVERIFIABLE
            out.append(value)
        return out
    return UNVERIFIABLE


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, (tuple, list)):
        out: list[Any] = []
        for item in value:
            out.extend(_flatten(item))
        return out
    return [value]


def _literal_spec(
    node: ast.AST | None,
    constants: dict[str, ast.AST],
    enums: dict[str, list[Any]] | None = None,
) -> EnumSpec | None:
    """Return the members of a ``Literal[...]`` annotation, ``None`` if it is not one."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _literal_spec(node.left, constants, enums)
        right = _literal_spec(node.right, constants, enums)
        if left is None and right is None:
            return None
        for part in (left, right):
            if isinstance(part, _Unresolvable):
                return part
        return _flatten(left) + _flatten(right)  # type: ignore[operator]
    if isinstance(node, ast.Subscript):
        value = node.value
        if isinstance(value, ast.Name) and value.id in _LITERAL_NAMES:
            elements = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            members: list[Any] = []
            for element in elements:
                resolved = _const_value(element, constants, enums)
                if resolved is UNVERIFIABLE:
                    return _Unresolvable(
                        f"`Literal[{ast.unparse(element)}]` is not a constant this guard "
                        "can resolve statically"
                    )
                members.extend(_flatten(resolved))
            return members
    return None


def _all_strings(node: ast.AST) -> list[str] | None:
    """Recover the string members of a comprehension over an enum class.

    ``AVAILABILITY_LITERALS = tuple(state.value for state in _Availability)`` is
    a spelling the codebase uses for "the literal a client receives". It is
    statically readable: a single generator whose iterable is an enum class with
    constant members. Anything else returns ``None`` so the caller reports it
    rather than guessing.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return None
    if node.func.id not in {"tuple", "list", "frozenset"} or not node.args:
        return None
    generator = node.args[0]
    if not isinstance(generator, ast.GeneratorExp) or len(generator.generators) != 1:
        return None
    comprehension = generator.generators[0]
    if not isinstance(comprehension.iter, ast.Name) or comprehension.ifs:
        return None
    enum_name = comprehension.iter.id
    element = generator.elt
    wanted = None
    if isinstance(element, ast.Attribute) and element.attr == "value":
        if isinstance(element.value, ast.Name) and element.value.id == comprehension.target.id:
            wanted = "value"
    if wanted is None:
        return None
    return enum_name


def _enum_class_spec(node: ast.ClassDef) -> EnumSpec | None:
    """Return the members of an ``Enum`` class body, ``None`` if it is not one."""
    bases = {ast.unparse(base) for base in node.bases}
    if not bases & _ENUM_BASES:
        return None
    members: list[Any] = []
    for statement in node.body:
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            if not all(isinstance(target, ast.Name) for target in statement.targets):
                continue
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            value = statement.value
        else:
            continue
        if not isinstance(value, ast.Constant):
            return _Unresolvable(f"`{node.name}` members are not simple constants")
        members.append(value.value)
    if not members:
        return None
    return members


def _field_map(node: ast.ClassDef, constants: dict[str, ast.AST], enums: dict[str, list[Any]]
) -> dict[str, EnumSpec]:
    fields: dict[str, EnumSpec] = {}
    for statement in node.body:
        if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
            continue
        spec = _literal_spec(statement.annotation, constants, enums)
        if spec is not None:
            fields[statement.target.id] = spec
    return fields


def source_constraints(source_root: Path) -> dict[str, dict[str, EnumSpec]]:
    """Map ``Model -> field -> declared value domain`` across the schema modules."""
    models: dict[str, ast.ClassDef] = {}
    constants: dict[str, ast.AST] = {}
    for path in sorted(source_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            if isinstance(statement, ast.ClassDef):
                models[statement.name] = statement
            elif isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = statement.value
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.value is not None:
                    constants[statement.target.id] = statement.value

    enums: dict[str, list[Any]] = {}
    for name, node in models.items():
        if name in constants:
            continue
        spec = _enum_class_spec(node)
        if isinstance(spec, list):
            enums[name] = spec

    constraints: dict[str, dict[str, EnumSpec]] = {}
    for name, node in models.items():
        fields: dict[str, EnumSpec] = {}
        enum_spec = _enum_class_spec(node)
        if enum_spec is not None:
            fields["__enum__"] = enum_spec
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(
                statement.target, ast.Name
            ):
                continue
            spec = _literal_spec(statement.annotation, constants, enums)
            if spec is not None:
                fields[statement.target.id] = spec
        if fields:
            constraints[name] = fields

    # A subclass is published as its own component, so it inherits the literal
    # fields of every base. Without this, `EnrichmentResponse(EnrichmentCalculationResponse)`
    # drops out of the check entirely and nobody notices.
    bases = {name: {ast.unparse(base) for base in node.bases} for name, node in models.items()}
    for _ in range(4):  # depth of the schema hierarchy here is 2; bound the walk
        for name in sorted(models):
            inherited: dict[str, EnumSpec] = {}
            for base in bases[name]:
                inherited.update(constraints.get(base, {}))
            if inheritable := {
                field: spec for field, spec in inherited.items() if field != "__enum__"
            }:
                merged = {**inheritable, **constraints.get(name, {})}
                if merged != constraints.get(name):
                    constraints[name] = merged
    return constraints


# ---------------------------------------------------------------------------
# Published side
# ---------------------------------------------------------------------------


def walk_properties(node: Any, location: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield every object carrying ``properties``, including ``$defs`` copies."""
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield location, node
        for key, value in node.items():
            if key == "properties":
                for field, sub in (value or {}).items():
                    yield from walk_properties(sub, f"{location}.{field}")
            elif key == "$defs":
                for defname, sub in (value or {}).items():
                    yield from walk_properties(sub, f"{location}.$defs.{defname}")
            else:
                yield from walk_properties(value, f"{location}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from walk_properties(item, f"{location}[{index}]")


def walk_field_schema(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict inside one field schema (in place, so it is mutable)."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_field_schema(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_field_schema(value)


def published_domains(node: Any) -> list[list[Any]]:
    """Collect every value domain inside one field schema, ``enum`` and ``const``."""
    found: list[list[Any]] = []

    def walk(current: Any) -> None:
        if isinstance(current, dict):
            if isinstance(current.get("enum"), list):
                found.append(current["enum"])
            if "const" in current:
                found.append([current["const"]])
            for value in current.values():
                walk(value)
        elif isinstance(current, list):
            for value in current:
                walk(value)

    walk(node)
    return found


def field_domains(schema: dict[str, Any], field: str, label: str) -> list[tuple[str, list[Any]]]:
    out: list[tuple[str, list[Any]]] = []
    for location, node in walk_properties(schema, label):
        properties = node.get("properties")
        if not isinstance(properties, dict) or field not in properties:
            continue
        for domain in published_domains(properties[field]):
            out.append((location, domain))
    return out


def field_domain_nodes(
    schema: dict[str, Any], field: str, label: str
) -> list[tuple[str, dict[str, Any]]]:
    """The ``enum``/``const`` holders themselves, so a mutation lands in place."""
    out: list[tuple[str, dict[str, Any]]] = []
    for location, node in walk_properties(schema, label):
        properties = node.get("properties")
        if not isinstance(properties, dict) or field not in properties:
            continue
        for holder in walk_field_schema(properties[field]):
            if isinstance(holder.get("enum"), list) or "const" in holder:
                out.append((location, holder))
    return out


def _same(a: Any, b: Any) -> bool:
    """Structural equality that also requires identical types.

    ``True == 1`` and ``1 == 1.0`` in Python, so a plain ``!=`` between a
    published domain and its pin accepts a boolean quietly rewritten as an
    integer.  Compare types as well as values, recursively.
    """
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _first_parameter_enum(document: dict[str, Any]) -> dict[str, Any] | None:
    """The first inline ``enum`` holder under a path/query parameter."""
    for methods in document.get("paths", {}).values():
        if not isinstance(methods, dict):
            continue
        for operation in methods.values():
            if not isinstance(operation, dict):
                continue
            for parameter in operation.get("parameters") or []:
                if not isinstance(parameter, dict):
                    continue
                node = parameter.get("schema")
                if isinstance(node, dict) and isinstance(node.get("enum"), list):
                    return node
    return None


def _published_domains(document: dict[str, Any]) -> dict[str, list[list[Any]]]:
    """Every published ``enum`` / ``const`` domain, keyed by its schema path.

    Walks the whole snapshot, not just ``components.schemas``: a path or query
    parameter can publish an inline ``enum``, which has no source-side
    comparison here and would otherwise be unpinned. Derived from the snapshot
    alone, so a domain the source-driven comparisons skip (an inlined model, a
    ``$defs`` copy, a field whose ``Literal`` the AST reader cannot resolve) is
    still pinned by the independent baseline.
    """
    found: dict[str, list[list[Any]]] = {}

    def walk(node: Any, label: str) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("enum"), list):
                found.setdefault(label, []).append(list(node["enum"]))
            if "const" in node:
                found.setdefault(label, []).append([node["const"]])
            for key, value in node.items():
                if key in ("enum", "const"):
                    continue
                walk(value, f"{label}.{key}")
        elif isinstance(node, list):
            for value in node:
                walk(value, label)

    components = document.get("components", {})
    for name, schema in sorted(components.get("schemas", {}).items()):
        walk(schema, name)
    for key, value in sorted(components.items()):
        if key != "schemas":
            walk(value, f"components.{key}")
    for section, body in sorted(document.items()):
        if section != "components":
            walk(body, section)
    return {label: sorted(domains, key=repr) for label, domains in sorted(found.items())}


def _compare(label: str, spec: EnumSpec, published: list[Any]) -> list[str]:
    if isinstance(spec, _Unresolvable):
        return [f"{label}: {spec.why}; widen the guard instead of letting this pass unseen"]
    spec = _without_none(spec)
    missing = [member for member in spec if member not in published]
    invented = [member for member in published if member not in spec]
    problems: list[str] = []
    if missing:
        problems.append(
            f"{label}: source declares {missing!r} but the snapshot publishes only "
            f"{published!r} -- a regenerated client narrows to a value the API really sends"
        )
    if invented:
        problems.append(
            f"{label}: snapshot publishes {invented!r} which the source does not declare "
            f"({spec!r}) -- a client branch for a value that never arrives"
        )
    return problems


def failures(
    document: dict[str, Any], constraints: dict[str, dict[str, EnumSpec]]
) -> tuple[list[str], int]:
    """Return ``(problems, compared_enum_pairs)``."""
    found: list[str] = []
    compared = 0
    components = document.get("components", {}).get("schemas", {})
    enum_classes = [name for name, fields in constraints.items() if "__enum__" in fields]
    # Exemptions come from a reviewed literal, never from the artifact under
    # guard. An enum class absent from components.schemas that is NOT on the
    # list is a regression (its published value domain disappeared), not an
    # inline class to skip.
    inline_classes = [name for name in enum_classes if name in INLINED_ENUM_CLASSES]
    for name in enum_classes:
        if name not in inline_classes and name not in components:
            found.append(
                f"openapi.json publishes no `{name}` enum component, so its "
                "declared value domain cannot be verified (add it to "
                "INLINED_ENUM_CLASSES only if pydantic truly inlines it)"
            )

    for model, fields in sorted(constraints.items()):
        if "__enum__" in fields:
            continue
        schema = components.get(model)
        if schema is None:
            # Either pydantic inlines the model (so it publishes no component)
            # or it left the contract. An inline-only model is listed in
            # INLINED_MODELS; everything else is named, never counted as a pass.
            if model not in INLINED_MODELS:
                found.append(
                    f"openapi.json publishes no `{model}`, so its "
                    f"{len(fields)} constrained field(s) cannot be verified"
                )
            continue
        for field, spec in sorted(fields.items()):
            pairs = field_domains(schema, field, model)
            if not pairs:
                found.append(
                    f"{model}.{field}: the source constrains this field but the snapshot "
                    "publishes no `enum` or `const` for it"
                )
                continue
            for location, domain in pairs:
                compared += 1
                found.extend(_compare(f"{location}.{field}", spec, domain))

    for name in enum_classes:
        if name in inline_classes:
            continue
        schema = components.get(name)
        if schema is None:
            # Named above as an unexpected absence; fail cleanly instead of
            # raising KeyError on a mutated artifact.
            continue
        domains = published_domains(schema)
        if not domains:
            found.append(f"`{name}` is an enum class but publishes no `enum` or `const`")
            continue
        for domain in domains:
            compared += 1
            found.extend(_compare(name, constraints[name]["__enum__"], domain))

    if compared == 0:
        found.append(
            "nothing was compared: no published value domain matched a declared one"
        )

    # Every comparison above is two half-views of one tree.  Compare the whole
    # published surface to an independent literal instead, so a coordinated
    # edit cannot satisfy them all by agreeing with itself.
    published_all = _published_domains(document)
    if not _same(published_all, _PUBLISHED_ENUM_BASELINE):
        found.append(
            "openapi.json publishes value domains that no longer match the "
            "independent baseline: a coordinated edit to the source and the "
            "snapshot cannot be seen by comparing them to each other"
        )
    return found, compared


def _load(root: Path) -> tuple[dict[str, Any], dict[str, dict[str, EnumSpec]]]:
    document = json.loads((root / SNAPSHOT).read_text(encoding="utf-8"))
    return document, source_constraints(root / SCHEMA_ROOT)


# ---------------------------------------------------------------------------
# Self-test: each ablation must be caught by the check it names
# ---------------------------------------------------------------------------


def _self_test(document: dict[str, Any], constraints: dict[str, dict[str, EnumSpec]]) -> int:
    target = None
    components = document["components"]["schemas"]
    for model, fields in sorted(constraints.items()):
        if "__enum__" in fields or model not in components:
            continue
        for field, spec in sorted(fields.items()):
            if not isinstance(spec, list):
                continue
            if field_domain_nodes(components[model], field, model):
                target = (model, field)
                break
        if target:
            break
    if target is None:
        print("FAIL: self-test found no published value domain to mutate")
        return 1
    if _first_parameter_enum(document) is None:
        print("FAIL: self-test found no inline parameter enum outside components.schemas")
        return 1
    model, field = target

    def holder(doc: dict[str, Any]) -> dict[str, Any]:
        return field_domain_nodes(doc["components"]["schemas"][model], field, model)[0][1]

    def _enum_of(node: dict[str, Any]) -> list[Any]:
        # A single-member ``Literal`` is published as ``const``; mutating it as
        # if it were ``enum`` would prove nothing about the real spelling.
        if "const" in node:
            return node["const"]
        return node["enum"]

    def drop_member(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            # Dropping the only member of a ``const`` means removing the domain.
            node.pop("const")
        else:
            node["enum"].remove(node["enum"][-1])
        return failures(doc, constraints)[0]

    def invent_member(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            node["enum"] = [node.pop("const"), "__never_declared__"]
        else:
            node["enum"].append("__never_declared__")
        return failures(doc, constraints)[0]

    def retype(doc: dict[str, Any]) -> list[str]:
        node = holder(doc)
        if isinstance(node.get("const"), str):
            node["const"] = "__retyped__"
        else:
            node["enum"][0] = "__retyped__"
        return failures(doc, constraints)[0]

    def retype_const(doc: dict[str, Any]) -> list[str]:
        # A single-member ``Literal`` is published as ``const``, not ``enum``;
        # mutating the wrong spelling proves nothing.
        for name, fields in sorted(constraints.items()):
            schema = doc["components"]["schemas"].get(name)
            if schema is None or "__enum__" in fields:
                continue
            for other, spec in sorted(fields.items()):
                if not isinstance(spec, list) or len(_without_none(spec)) != 1:
                    continue
                nodes = field_domain_nodes(schema, other, name)
                if nodes and "const" in nodes[0][1]:
                    nodes[0][1]["const"] = "__retyped_const__"
                    return failures(doc, constraints)[0]
        return []

    def drop_field(doc: dict[str, Any]) -> list[str]:
        for _, node in walk_properties(doc["components"]["schemas"][model], model):
            if field in node["properties"]:
                node["properties"].pop(field)
                break
        return failures(doc, constraints)[0]

    def drop_model(doc: dict[str, Any]) -> list[str]:
        doc["components"]["schemas"].pop(model, None)
        return failures(doc, constraints)[0]

    def source_adds(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = _without_none(mutated[model][field]) + ["__source_only__"]
        return failures(doc, mutated)[0]

    def source_drops(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = mutated[model][field][:-1]
        return failures(doc, mutated)[0]

    def source_unresolvable(doc: dict[str, Any]) -> list[str]:
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = _Unresolvable("synthetic unresolvable spelling")
        return failures(doc, mutated)[0]

    def _co_domain(doc: dict[str, Any]) -> list[Any]:
        node = holder(doc)
        return node["enum"] if "enum" in node else [node["const"]]

    def _co_set(doc: dict[str, Any], values: list[Any]) -> None:
        node = holder(doc)
        if "const" in node and len(values) == 1:
            node["const"] = values[0]
        else:
            node.pop("const", None)
            node["enum"] = values

    def coord_add(doc: dict[str, Any]) -> list[str]:
        # Source and snapshot gain the same member: the source-driven equality
        # checks stay green, only the independent literal can see the change.
        _co_set(doc, _co_domain(doc) + ["__co_added__"])
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = _without_none(mutated[model][field]) + ["__co_added__"]
        return failures(doc, mutated)[0]

    def coord_drop(doc: dict[str, Any]) -> list[str]:
        _co_set(doc, _co_domain(doc)[:-1])
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = mutated[model][field][:-1]
        return failures(doc, mutated)[0]

    def coord_retype(doc: dict[str, Any]) -> list[str]:
        _co_set(doc, ["__co_retyped__"] + _co_domain(doc)[1:])
        mutated = copy.deepcopy(constraints)
        mutated[model][field] = ["__co_retyped__"] + list(mutated[model][field])[1:]
        return failures(doc, mutated)[0]

    def coord_bool_to_int(doc: dict[str, Any]) -> list[str]:
        # ``True == 1``: a value-only pin accepts a boolean leaf republished as
        # an integer in both halves.  The pin must compare types recursively.
        for name, fields in sorted(constraints.items()):
            schema = doc["components"]["schemas"].get(name)
            if schema is None or "__enum__" in fields:
                continue
            for other, spec in sorted(fields.items()):
                if not isinstance(spec, list) or True not in _without_none(spec):
                    continue
                nodes = field_domain_nodes(schema, other, name)
                if not nodes or "const" not in nodes[0][1]:
                    continue
                nodes[0][1]["const"] = 1
                mutated = copy.deepcopy(constraints)
                mutated[name][other] = [1 if v is True else v for v in mutated[name][other]]
                return failures(doc, mutated)[0]
        return []

    def path_parameter_domain_add(doc: dict[str, Any]) -> list[str]:
        # A parameter enum lives outside ``components.schemas`` and has no
        # source-side comparison at all. A coordinated regenerate of the
        # model, the snapshot and the generated client moves every half
        # together; only the independent literal can see the new member.
        node = _first_parameter_enum(doc)
        node["enum"].append("__path_added__")
        return failures(doc, constraints)[0]

    def coord_wholesale_drop(doc: dict[str, Any]) -> list[str]:
        # Remove every constrained field from the source view and its published
        # domain from the snapshot together.  Enum classes still compare, so
        # ``compared == 0`` does not fire; only the literal inventory can.
        mutated = copy.deepcopy(constraints)
        for name, fields in list(mutated.items()):
            if "__enum__" in fields:
                continue
            schema = doc["components"]["schemas"].get(name)
            if schema is None:
                continue
            for other in list(fields):
                if not isinstance(fields[other], list):
                    continue
                for _, node in field_domain_nodes(schema, other, name):
                    node.pop("enum", None)
                    node.pop("const", None)
                del mutated[name][other]
        return failures(doc, mutated)[0]


    def inline_model_still_checked(doc: dict[str, Any]) -> list[str]:
        # Dropping an INLINED_MODELS exemption must be loud, not silent: an
        # exempted model that vanishes from the snapshot without a note is
        # exactly the "counted as a pass" failure this guard exists to avoid.
        mutated = copy.deepcopy(constraints)
        mutated["SyntheticNotPublished"] = {"field": ["x"]}
        return failures(doc, mutated)[0]

    def enum_component_dropped(doc: dict[str, Any]) -> list[str]:
        # The vacuous exemption this guard used to have: absence from
        # components.schemas proved "pydantic inlined it". Deleting a real
        # enum component must be a named failure, not a silent skip.
        victim = next(n for n, f in sorted(constraints.items())
                      if "__enum__" in f and n in doc["components"]["schemas"])
        doc["components"]["schemas"].pop(victim)
        return failures(doc, constraints)[0]

    cases = [
        ("published domain drops a declared member", drop_member),
        ("published domain invents a member", invent_member),
        ("published domain retyped wholesale", retype),
        ("single-member Literal published as `const` retyped", retype_const),
        ("published field removed from its model", drop_field),
        ("published model removed", drop_model),
        ("source adds a member the snapshot lacks", source_adds),
        ("source drops a member the snapshot still lists", source_drops),
        ("source spelling the guard cannot resolve", source_unresolvable),
        ("model missing from the snapshot is named", inline_model_still_checked),
        ("a real enum component disappearing is named", enum_component_dropped),
        ("coordinated ADD of a member in both halves", coord_add),
        ("coordinated DROP of a member in both halves", coord_drop),
        ("coordinated RETYPE of a member in both halves", coord_retype),
        ("coordinated bool -> int type weakening in both halves", coord_bool_to_int),
        ("wholesale coordinated drop of all constrained domains", coord_wholesale_drop),
        (
            "published path-parameter domain drifts outside components.schemas",
            path_parameter_domain_add,
        ),
    ]

    result = 0
    for label, mutate in cases:
        problems = mutate(copy.deepcopy(document))
        if not problems:
            print(f"FAIL: {label} was not caught")
            result = 1
    clean, _ = failures(document, constraints)
    if clean:
        print("FAIL: clean inputs do not pass")
        for problem in clean:
            print(f"  {problem}")
        result = 1
    # Positive control: a legitimate change that moves both halves AND the
    # literal in the same commit must stay green (an exact pin is not a
    # whitelist).  This is checked directly, not through the ablation loop,
    # because a healthy tree produces no problems.
    saved = globals()["_PUBLISHED_ENUM_BASELINE"]
    legit = copy.deepcopy(document)
    legit_constraints = copy.deepcopy(constraints)
    legit_node = field_domain_nodes(
        legit["components"]["schemas"][model], field, model
    )[0][1]
    if "const" in legit_node:
        legit_node.pop("const")
        legit_node["enum"] = _without_none(legit_constraints[model][field]) + [
            "__legitimate__"
        ]
    else:
        legit_node["enum"] = legit_node["enum"] + ["__legitimate__"]
    legit_constraints[model][field] = (
        _without_none(legit_constraints[model][field]) + ["__legitimate__"]
    )
    globals()["_PUBLISHED_ENUM_BASELINE"] = _published_domains(legit)
    try:
        repin_problems = failures(legit, legit_constraints)[0]
    finally:
        globals()["_PUBLISHED_ENUM_BASELINE"] = saved
    if repin_problems:
        print(f"FAIL: same-commit repin was rejected: {repin_problems}")
        result = 1

    # Invariants that are not document mutations: assert them directly, so a
    # broken comparator or a runtime-derived pin fails the wired self-test.
    for a, b in ((True, 1), (1, 1.0), ({"flag": True}, {"flag": 1}), ([True, 1], [1, 1])):
        if _same(a, b):
            print(f"FAIL: _same({a!r}, {b!r}) must be False")
            result = 1
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    literal_ok = False
    for node in tree.body:
        targets = (
            [node.target]
            if isinstance(node, ast.AnnAssign)
            else node.targets if isinstance(node, ast.Assign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "_PUBLISHED_ENUM_BASELINE":
                if isinstance(node.value, (ast.Dict, ast.List, ast.Tuple)):
                    ast.literal_eval(node.value)
                    literal_ok = True
    if not literal_ok:
        print("FAIL: _PUBLISHED_ENUM_BASELINE is not a module-level literal")
        result = 1

    if result == 0:
        print(f"OK ({len(cases)} ablations)")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="mutate in-memory copies and prove each ablation is caught",
    )
    args = parser.parse_args(argv)

    try:
        document, constraints = _load(REPO_ROOT)
    except (OSError, json.JSONDecodeError, SyntaxError) as error:
        print(f"FAIL: cannot read the contract inputs: {error}")
        return 1

    if args.self_test:
        return _self_test(document, constraints)

    problems, compared = failures(document, constraints)
    if problems:
        print("FAIL: published value domains no longer match the source:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(
        f"OK (published value domains pinned, {compared} pair(s) across "
        f"{len(constraints)} model(s))"
    )
    return 0


def test_committed_tree_matches_the_independent_enum_pin() -> None:
    """The literal must be an exact, type-exact description of the snapshot."""
    document, constraints = _load(REPO_ROOT)
    assert failures(document, constraints)[0] == []


def test_path_parameter_domains_are_pinned_too() -> None:
    """The pin must cover ``paths``, not only ``components.schemas``."""
    document, constraints = _load(REPO_ROOT)
    published = _published_domains(document)
    assert any(key.startswith("paths.") for key in published)
    assert _same(published, _PUBLISHED_ENUM_BASELINE)
    node = _first_parameter_enum(document)
    assert node is not None
    node["enum"] = node["enum"] + ["__co_added__"]
    assert any("independent baseline" in p for p in failures(document, constraints)[0])


def test_a_coordinated_add_is_rejected() -> None:
    """Source + snapshot gaining one member together must not stay green."""
    document, constraints = _load(REPO_ROOT)
    document = copy.deepcopy(document)
    constraints = copy.deepcopy(constraints)
    target = "AnnotationTerm"
    field = "kind"
    node = field_domain_nodes(
        document["components"]["schemas"][target], field, target
    )[0][1]
    node["enum"] = node["enum"] + ["__co_added__"]
    constraints[target][field] = list(constraints[target][field]) + ["__co_added__"]
    assert any("independent baseline" in p for p in failures(document, constraints)[0])


def test_a_coordinated_drop_is_rejected() -> None:
    document, constraints = _load(REPO_ROOT)
    document = copy.deepcopy(document)
    constraints = copy.deepcopy(constraints)
    target, field = "AnnotationTerm", "kind"
    node = field_domain_nodes(
        document["components"]["schemas"][target], field, target
    )[0][1]
    node["enum"] = node["enum"][:-1]
    constraints[target][field] = list(constraints[target][field])[:-1]
    assert any("independent baseline" in p for p in failures(document, constraints)[0])


def test_a_coordinated_bool_to_int_type_drift_is_rejected() -> None:
    """``True == 1``: a value-only pin would republish a boolean as an int."""
    document, constraints = _load(REPO_ROOT)
    document = copy.deepcopy(document)
    constraints = copy.deepcopy(constraints)
    target, field = "ReleaseActionRequest", "confirm"
    node = field_domain_nodes(
        document["components"]["schemas"][target], field, target
    )[0][1]
    assert node["const"] is True
    node["const"] = 1
    constraints[target][field] = [1]
    assert any("independent baseline" in p for p in failures(document, constraints)[0])


def test_the_pin_distinguishes_a_bool_from_an_int() -> None:
    assert not _same(True, 1)
    assert not _same(1, 1.0)
    assert not _same({"a": True}, {"a": 1})
    assert not _same([True], [1])
    assert not _same({"a": 1}, {"a": 1, "b": 2})
    assert _same({"a": [True, 1]}, {"a": [True, 1]})
    assert not _same({"a": [True, 1]}, {"a": [1, 1]})


def test_the_pin_is_a_source_literal_not_a_runtime_derivation() -> None:
    """Re-deriving the pin from the snapshot would reopen the co-revert hole."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "_PUBLISHED_ENUM_BASELINE":
                assert isinstance(node.value, (ast.Dict, ast.List, ast.Tuple))
                ast.literal_eval(node.value)
                return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_PUBLISHED_ENUM_BASELINE":
                    assert isinstance(node.value, (ast.Dict, ast.List, ast.Tuple))
                    ast.literal_eval(node.value)
                    return
    raise AssertionError("_PUBLISHED_ENUM_BASELINE is not a module-level literal")


def test_a_repin_in_the_same_commit_stays_green() -> None:
    """An exact pin is deliberate, not a whitelist: move it with the artifact."""
    document, constraints = _load(REPO_ROOT)
    document = copy.deepcopy(document)
    saved = globals()["_PUBLISHED_ENUM_BASELINE"]
    target, field = "AnnotationTerm", "kind"
    node = field_domain_nodes(
        document["components"]["schemas"][target], field, target
    )[0][1]
    node["enum"] = node["enum"] + ["__legitimate__"]
    constraints = copy.deepcopy(constraints)
    constraints[target][field] = list(constraints[target][field]) + ["__legitimate__"]
    globals()["_PUBLISHED_ENUM_BASELINE"] = _published_domains(document)
    try:
        assert failures(document, constraints)[0] == []
    finally:
        globals()["_PUBLISHED_ENUM_BASELINE"] = saved


if __name__ == "__main__":
    sys.exit(main())
