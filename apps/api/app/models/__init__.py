"""SoyMutDB ORM models – import every model so Base.metadata is complete."""

from app.widgets.models import PageLayout, Widget, WidgetCategory, WidgetPermission

from .analysis_job import AnalysisJob, AnalysisJobStatus, AnalysisType
from .auth import (
    AuditLog,
    Organization,
    Project,
    ProjectMember,
    RefreshToken,
    Role,
    User,
)
from .base import AuditMixin, Base, SoftDeleteMixin, TimestampMixin
from .blast import BlastDatabase, BlastHit, BlastIndexBuild, BlastJob
from .comparative import (
    ArtifactType,
    ComparativeArtifact,
    ComparativeArtifactState,
    FamilyLevel,
    GeneFamily,
    GeneFamilyMember,
    RelationshipType,
)
from .content import (
    DownloadFile,
    NewsArticle,
    NewsArticleRevision,
    NewsPublicationSchedule,
    NewsScheduleState,
    NewsStatus,
    Publication,
    Release,
    ReleaseStatus,
    StaticPage,
)
from .data_publishing import ActiveRelease, DataSet, ImportStatus, Provenance, ReleaseDataSet
from .data_views import AdminDataView
from .expression import ExpressionData, ExpressionLibrary
from .gene_annotation import GeneAnnotation, GeneAnnotationSet
from .gene_data_cache import GeneDataCache
from .genomic import (
    Assembly,
    Chromosome,
    Exon,
    Gene,
    GeneAlias,
    GeneCrosswalk,
    Transcript,
    TranscriptPart,
    TranscriptSequence,
)
from .gwas import GwasFileType, GwasJob, GwasJobStatus, GwasMethod
from .homolog import GeneHomolog
from .import_manifest import ImportManifest, ImportManifestStatus
from .import_studio import (
    DataPatch,
    DatasetVersion,
    FieldMapping,
    ImportDraft,
    ImportDraftStatus,
    PageDataSource,
    PublicationManifest,
)
from .import_task import ImportTask, ImportTaskStatus, ImportTaskType
from .media import MediaAsset, MediaAssetStatus
from .module_data import ModuleDataRow, ModuleSchema
from .notification import Notification
from .outbox import OutboxEvent
from .page_builder import PageDefinition, PageDefinitionStatus, PageDefinitionVersion
from .publication import (
    PublicationCounter,
    PublicationStatus,
    PublicationTarget,
    PublicationTargetLease,
    StaticPublication,
)
from .seed import SeedInventory, SeedRequest
from .seed_request import SeedRequestContact, SeedRequestStatus
from .system_settings import SystemSetting, SystemSettingRevision
from .table_views import SpeciesInstance, TableViewTemplate
from .tracks import Track, TrackCategory
from .variant import MutantLine, Phenotype, VariantSummary
from .variant_export import VariantExport, VariantExportStatus
from .variant_facts import analytics_events, variant_facts, variant_facts_staging, web_vitals

__all__ = [
    "ArtifactType",
    "ComparativeArtifact",
    "ComparativeArtifactState",
    "FamilyLevel",
    "GeneFamily",
    "GeneFamilyMember",
    "RelationshipType",
    "analytics_events",
    "variant_facts",
    "variant_facts_staging",
    "web_vitals",
    "ActiveRelease",
    "AdminDataView",
    "AnalysisJob",
    "AnalysisJobStatus",
    "AnalysisType",
    "Assembly",
    "AuditLog",
    "AuditMixin",
    "Base",
    "BlastDatabase",
    "BlastHit",
    "BlastIndexBuild",
    "BlastJob",
    "Chromosome",
    "DataPatch",
    "DataSet",
    "DatasetVersion",
    "DownloadFile",
    "Exon",
    "ExpressionData",
    "ExpressionLibrary",
    "FieldMapping",
    "Gene",
    "GeneAlias",
    "GeneAnnotation",
    "GeneAnnotationSet",
    "GeneCrosswalk",
    "TranscriptPart",
    "GeneDataCache",
    "GeneHomolog",
    "GwasFileType",
    "GwasJob",
    "GwasJobStatus",
    "GwasMethod",
    "ImportDraft",
    "ImportDraftStatus",
    "ImportManifest",
    "ImportManifestStatus",
    "ImportStatus",
    "ImportTask",
    "ImportTaskStatus",
    "ImportTaskType",
    "MediaAsset",
    "MediaAssetStatus",
    "ModuleDataRow",
    "ModuleSchema",
    "MutantLine",
    "NewsArticle",
    "NewsArticleRevision",
    "NewsPublicationSchedule",
    "NewsScheduleState",
    "NewsStatus",
    "Notification",
    "Organization",
    "OutboxEvent",
    "PageDataSource",
    "PageDefinition",
    "PageDefinitionStatus",
    "PageDefinitionVersion",
    "PageLayout",
    "Phenotype",
    "Project",
    "ProjectMember",
    "Provenance",
    "Publication",
    "PublicationCounter",
    "PublicationManifest",
    "PublicationStatus",
    "PublicationTarget",
    "PublicationTargetLease",
    "RefreshToken",
    "Release",
    "ReleaseDataSet",
    "ReleaseStatus",
    "Role",
    "SeedInventory",
    "SeedRequest",
    "SeedRequestContact",
    "SeedRequestStatus",
    "SoftDeleteMixin",
    "SpeciesInstance",
    "StaticPage",
    "StaticPublication",
    "SystemSetting",
    "SystemSettingRevision",
    "TableViewTemplate",
    "TimestampMixin",
    "Track",
    "TrackCategory",
    "Transcript",
    "TranscriptSequence",
    "User",
    "VariantExport",
    "VariantExportStatus",
    "VariantSummary",
    "Widget",
    "WidgetCategory",
    "WidgetPermission",
]
