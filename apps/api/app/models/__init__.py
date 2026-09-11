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
from .blast import BlastDatabase, BlastHit, BlastJob
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
from .expression import ExpressionData, ExpressionLibrary
from .gene_data_cache import GeneDataCache
from .genomic import (
    Assembly,
    Chromosome,
    Exon,
    Gene,
    GeneAlias,
    GeneCrosswalk,
    Transcript,
)
from .gwas import GwasFileType, GwasJob, GwasJobStatus, GwasMethod
from .homolog import GeneHomolog
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
from .tracks import Track, TrackCategory
from .variant import MutantLine, Phenotype, VariantSummary

__all__ = [
    "AnalysisJob",
    "AnalysisJobStatus",
    "AnalysisType",
    "Assembly",
    "AuditLog",
    "AuditMixin",
    "Base",
    "BlastDatabase",
    "BlastHit",
    "BlastJob",
    "Chromosome",
    "DownloadFile",
    "Exon",
    "ExpressionData",
    "ExpressionLibrary",
    "Gene",
    "GeneAlias",
    "GeneCrosswalk",
    "GeneDataCache",
    "GeneHomolog",
    "GwasFileType",
    "GwasJob",
    "GwasJobStatus",
    "GwasMethod",
    "ImportTask",
    "ImportTaskStatus",
    "ImportTaskType",
    "ImportDraft",
    "ImportDraftStatus",
    "DatasetVersion",
    "FieldMapping",
    "DataPatch",
    "PageDataSource",
    "PublicationManifest",
    "ImportStatus",
    "DataSet",
    "ReleaseDataSet",
    "ActiveRelease",
    "Provenance",
    "ModuleDataRow",
    "ModuleSchema",
    "MediaAsset",
    "MediaAssetStatus",
    "MutantLine",
    "NewsArticle",
    "NewsArticleRevision",
    "NewsPublicationSchedule",
    "NewsScheduleState",
    "NewsStatus",
    "Notification",
    "Organization",
    "OutboxEvent",
    "PageDefinition",
    "PageDefinitionStatus",
    "PageDefinitionVersion",
    "PageLayout",
    "Phenotype",
    "Project",
    "ProjectMember",
    "Publication",
    "PublicationCounter",
    "PublicationStatus",
    "PublicationTarget",
    "PublicationTargetLease",
    "RefreshToken",
    "Release",
    "ReleaseStatus",
    "Role",
    "SeedInventory",
    "SeedRequest",
    "SeedRequestContact",
    "SeedRequestStatus",
    "SoftDeleteMixin",
    "StaticPage",
    "StaticPublication",
    "SystemSetting",
    "SystemSettingRevision",
    "TimestampMixin",
    "Track",
    "TrackCategory",
    "Transcript",
    "User",
    "VariantSummary",
    "Widget",
    "WidgetCategory",
    "WidgetPermission",
]
