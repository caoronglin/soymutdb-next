"""Track service – CRUD and signed-URL generation with RBAC enforcement."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.exceptions import NotFoundError
from ..core.security import RoleName, has_role
from ..models.auth import ProjectMember
from ..models.tracks import Track, TrackCategory, TrackStatus, TrackVisibility
from ..schemas.content import SignedUrlResponse
from .presign import DOWNLOAD_EXPIRES_IN, generate_download_url

settings = get_settings()


class TrackService:
    """Track management service.

    The ``get_signed_url`` method enforces RBAC: only the track owner, a
    ``track_manager``, or an ``administrator`` may receive a signed URL for
    private/project tracks.
    """

    async def list_tracks(
        self,
        db: AsyncSession,
        assembly_id: int | None = None,
        category_id: int | None = None,
        *,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        roles = user_roles or []
        project_ids = await self._project_ids_for_user(db, user_id, roles)
        stmt = select(Track).where(
            Track.is_deleted.is_(False),
            Track.status == TrackStatus.READY,
        )
        visibility_filter = self._visibility_filter(user_id, roles, project_ids)
        if visibility_filter is not None:
            stmt = stmt.where(visibility_filter)
        if assembly_id is not None:
            stmt = stmt.where(Track.assembly_id == assembly_id)
        if category_id is not None:
            stmt = stmt.where(Track.category_id == category_id)
        result = await db.execute(stmt)
        return [
            self._track_to_dict(track)
            for track in result.scalars().all()
            if self._can_view_track(track, user_id, roles, project_ids)
        ]

    async def get_track(
        self,
        db: AsyncSession,
        track_id: int,
        *,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
    ) -> dict[str, Any]:
        roles = user_roles or []
        project_ids = await self._project_ids_for_user(db, user_id, roles)
        visibility_filter = self._visibility_filter(user_id, roles, project_ids)
        filters = [
            Track.id == track_id,
            Track.is_deleted.is_(False),
            Track.status == TrackStatus.READY,
        ]
        if visibility_filter is not None:
            filters.append(visibility_filter)
        result = await db.execute(
            select(Track).where(*filters)
        )
        track = result.scalar_one_or_none()
        if track is None or not self._can_view_track(
            track, user_id, roles, project_ids
        ):
            raise NotFoundError(f"Track {track_id} not found")
        return self._track_to_dict(track)

    async def get_signed_url(
        self,
        db: AsyncSession,
        track_id: int,
        user_id: uuid.UUID,
        user_roles: list[str],
    ) -> SignedUrlResponse:
        """Return a signed URL for a track file, enforcing RBAC.

        - Public tracks: accessible to any authenticated user.
        - Project tracks: accessible to project members or managers.
        - Private tracks: accessible only to the owner, ``track_manager``,
          or ``administrator``.
        """
        track = await self._get_track_or_404(
            db,
            track_id,
            user_id=user_id,
            user_roles=user_roles,
        )

        return self._build_signed_url(track)

    async def list_categories(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(
            select(TrackCategory).order_by(TrackCategory.display_order)
        )
        return [
            {"id": c.id, "name": c.name, "display_order": c.display_order}
            for c in result.scalars().all()
        ]

    async def get_jbrowse_config(
        self,
        db: AsyncSession,
        assembly_name: str = "Wm82v4.0",
        *,
        user_id: uuid.UUID | None = None,
        user_roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build a JBrowse 2 configuration response for the standalone browser.

        Queries the database for ready, non-deleted tracks belonging to the
        requested assembly and converts them to JBrowse track format. The
        assembly metadata is returned as a simple name-only object — the
        frontend JBrowse app has full assembly adapter configuration built in
        as defaults.
        """
        # Query tracks joined to assemblies filtered by assembly name.
        from ..models.genomic import Assembly
        from ..models.tracks import TrackStatus

        roles = user_roles or []
        project_ids = await self._project_ids_for_user(db, user_id, roles)
        stmt = (
            select(Track)
            .join(Assembly, Track.assembly_id == Assembly.id)
            .where(
                Track.is_deleted.is_(False),
                Track.status == TrackStatus.READY,
                Assembly.name == assembly_name,
            )
        )
        visibility_filter = self._visibility_filter(user_id, roles, project_ids)
        if visibility_filter is not None:
            stmt = stmt.where(visibility_filter)
        result = await db.execute(stmt)
        tracks = [
            track
            for track in result.scalars().all()
            if self._can_view_track(track, user_id, roles, project_ids)
        ]

        jbrowse_tracks = [self._track_to_jbrowse(t, assembly_name) for t in tracks]

        return {
            "assembly": {"name": assembly_name},
            "tracks": jbrowse_tracks,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_track_manager(user_roles: list[str]) -> bool:
        return has_role(user_roles, RoleName.TRACK_MANAGER) or has_role(
            user_roles, RoleName.ADMINISTRATOR
        )

    async def _project_ids_for_user(
        self,
        db: AsyncSession,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> set[int]:
        if user_id is None or self._is_track_manager(user_roles):
            return set()
        result = await db.execute(
            select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)
        )
        return set(result.scalars().all())

    def _visibility_filter(
        self,
        user_id: uuid.UUID | None,
        user_roles: list[str],
        project_ids: set[int],
    ) -> Any | None:
        if self._is_track_manager(user_roles):
            return None

        allowed = [Track.visibility == TrackVisibility.PUBLIC]
        if user_id is not None:
            allowed.append(Track.owner_id == user_id)
            if project_ids:
                allowed.append(
                    and_(
                        Track.visibility == TrackVisibility.PROJECT,
                        Track.project_id.in_(project_ids),
                    )
                )
        return or_(*allowed)

    def _can_view_track(
        self,
        track: Track,
        user_id: uuid.UUID | None,
        user_roles: list[str],
        project_ids: set[int],
    ) -> bool:
        if track.status != TrackStatus.READY:
            return False
        if self._is_track_manager(user_roles):
            return True
        if track.visibility == TrackVisibility.PUBLIC:
            return True
        if user_id is None:
            return False
        if track.owner_id == user_id:
            return True
        return (
            track.visibility == TrackVisibility.PROJECT
            and track.project_id is not None
            and track.project_id in project_ids
        )

    async def _get_track_or_404(
        self,
        db: AsyncSession,
        track_id: int,
        *,
        user_id: uuid.UUID | None,
        user_roles: list[str],
    ) -> Track:
        project_ids = await self._project_ids_for_user(db, user_id, user_roles)
        filters = [
            Track.id == track_id,
            Track.is_deleted.is_(False),
            Track.status == TrackStatus.READY,
        ]
        visibility_filter = self._visibility_filter(
            user_id,
            user_roles,
            project_ids,
        )
        if visibility_filter is not None:
            filters.append(visibility_filter)
        result = await db.execute(select(Track).where(*filters))
        track = result.scalar_one_or_none()
        if track is None or not self._can_view_track(
            track,
            user_id,
            user_roles,
            project_ids,
        ):
            raise NotFoundError(f"Track {track_id} not found")
        return track

    @staticmethod
    def _track_to_dict(track: Track) -> dict[str, Any]:
        return {
            "id": str(track.id),
            "name": track.name,
            "description": track.description,
            "track_type": track.track_type,
            "file_format": track.file_format,
            "assembly_id": str(track.assembly_id),
            "category_id": str(track.category_id) if track.category_id else None,
            "owner_id": str(track.owner_id) if track.owner_id else None,
            "visibility": track.visibility,
            "status": track.status,
            "created_at": track.created_at.isoformat() if track.created_at else None,
        }

    @classmethod
    def _track_to_jbrowse(
        cls,
        track: Track,
        assembly_name: str,
    ) -> dict[str, Any]:
        """Convert a database Track to a JBrowse 2 track configuration dict."""
        from ..models.tracks import FileFormat, TrackType

        signed = cls._build_signed_url(track)
        file_url = signed.url
        index_url = signed.index_url

        # Map database track types to JBrowse track types.
        track_type_map = {
            TrackType.VARIANT: "VariantTrack",
            TrackType.ANNOTATION: "FeatureTrack",
            TrackType.QUANTITATIVE: "QuantitativeTrack",
            TrackType.DENSITY: "QuantitativeTrack",
            TrackType.SV: "VariantTrack",
            TrackType.ALIGNMENT: "AlignmentsTrack",
            TrackType.PHENOTYPE: "FeatureTrack",
        }
        jb_type = track_type_map.get(track.track_type, "FeatureTrack")

        # Map file formats to JBrowse adapter types.
        adapter_map = {
            FileFormat.VCF: "VcfTabixAdapter",
            FileFormat.BAM: "BamAdapter",
            FileFormat.CRAM: "CramAdapter",
            FileFormat.BIGWIG: "BigWigAdapter",
            FileFormat.BW: "BigWigAdapter",
            FileFormat.BIGBED: "BigBedAdapter",
            FileFormat.GFF3: "Gff3TabixAdapter",
            FileFormat.BED: "BedTabixAdapter",
        }
        adapter_type = adapter_map.get(track.file_format, "GenericFileAdapter")

        adapter: dict[str, Any] = {"type": adapter_type}

        # Build adapter location based on file format.
        if adapter_type == "VcfTabixAdapter":
            adapter["vcfGzLocation"] = {"uri": file_url, "locationType": "UriLocation"}
            if index_url:
                adapter["index"] = {
                    "location": {
                        "uri": index_url,
                        "locationType": "UriLocation",
                    }
                }
        elif adapter_type == "Gff3TabixAdapter":
            adapter["gffGzLocation"] = {"uri": file_url, "locationType": "UriLocation"}
            if index_url:
                adapter["index"] = {
                    "location": {
                        "uri": index_url,
                        "locationType": "UriLocation",
                    }
                }
        elif adapter_type in ("BigWigAdapter", "BigBedAdapter"):
            key = "bigWigLocation" if adapter_type == "BigWigAdapter" else "bigBedLocation"
            adapter[key] = {"uri": file_url, "locationType": "UriLocation"}
        elif adapter_type == "BamAdapter":
            adapter["bamLocation"] = {"uri": file_url, "locationType": "UriLocation"}
            if index_url:
                adapter["index"] = {
                    "location": {
                        "uri": index_url,
                        "locationType": "UriLocation",
                    }
                }
        else:
            adapter["uri"] = file_url

        return {
            "trackId": f"track_{track.id}",
            "name": track.name,
            "type": jb_type,
            "assemblyNames": [assembly_name],
            "category": [track.category.name] if track.category else ["Uncategorized"],
            "description": track.description or "",
            "adapter": adapter,
        }

    @staticmethod
    def _validate_object_key(object_key: str) -> str:
        if not object_key or object_key.startswith(("/", "http://", "https://", "s3://")):
            raise ValueError("track storage path must be a relative object key")
        if "//" in object_key or any(
            segment in {"", ".", ".."} for segment in object_key.split("/")
        ):
            raise ValueError("track storage path contains invalid segments")
        return object_key

    @classmethod
    def _build_signed_url(cls, track: Track) -> SignedUrlResponse:
        """Sign the stored main object and optional index sidecar."""
        file_key = cls._validate_object_key(track.file_url)
        index_key = (
            cls._validate_object_key(track.index_url) if track.index_url else None
        )
        return SignedUrlResponse(
            url=generate_download_url(
                file_key,
                bucket=settings.s3_private_bucket,
                expires_in=DOWNLOAD_EXPIRES_IN,
            ),
            index_url=(
                generate_download_url(
                    index_key,
                    bucket=settings.s3_private_bucket,
                    expires_in=DOWNLOAD_EXPIRES_IN,
                )
                if index_key
                else None
            ),
            expires_in=DOWNLOAD_EXPIRES_IN,
        )
