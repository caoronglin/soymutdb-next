"""SoyMutDB ORM models – import every model so Base.metadata is complete."""

from app.widgets.models import PageLayout, Widget, WidgetCategory, WidgetPermission

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
from .blast import BlastDatabase, BlastJob
from .content import DownloadFile, NewsArticle, Publication, Release, StaticPage
from .expression import ExpressionData, ExpressionLibrary
from .gene_data_cache import GeneDataCache
from .genomic import Assembly, Chromosome, Exon, Gene, GeneAlias, Transcript
from .homolog import GeneHomolog
from .import_task import ImportTask
from .seed import SeedInventory, SeedRequest
from .system_settings import SystemSetting
from .tracks import Track, TrackCategory
from .variant import MutantLine, Phenotype, VariantSummary

__all__ = [
    "Assembly",
    "AuditLog",
    "AuditMixin",
    "Base",
    "BlastDatabase",
    "BlastJob",
    "Chromosome",
    "DownloadFile",
    "Exon",
    "ExpressionData",
    "ExpressionLibrary",
    "Gene",
    "GeneAlias",
    "GeneDataCache",
    "GeneHomolog",
    "ImportTask",
    "MutantLine",
    "NewsArticle",
    "Organization",
    "PageLayout",
    "Phenotype",
    "Project",
    "ProjectMember",
    "Publication",
    "RefreshToken",
    "Release",
    "Role",
    "SeedInventory",
    "SeedRequest",
    "SoftDeleteMixin",
    "StaticPage",
    "SystemSetting",
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
