"""Track service – CRUD and signed-URL generation with RBAC enforcement."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.exceptions import AuthorizationError, NotFoundError
from ..core.security import RoleName, has_role
from ..models.tracks import Track, TrackCategory, TrackVisibility
from ..schemas.content import SignedUrlResponse


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
    ) -> list[dict[str, Any]]:
        stmt = select(Track).where(Track.is_deleted.is_(False))
        if assembly_id is not None:
            stmt = stmt.where(Track.assembly_id == assembly_id)
        if category_id is not None:
            stmt = stmt.where(Track.category_id == category_id)
        result = await db.execute(stmt)
        return [self._track_to_dict(t) for t in result.scalars().all()]

    async def get_track(self, db: AsyncSession, track_id: int) -> dict[str, Any]:
        result = await db.execute(
            select(Track).where(Track.id == track_id, Track.is_deleted.is_(False))
        )
        track = result.scalar_one_or_none()
        if track is None:
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
        track = await self._get_track_or_404(db, track_id)

        # Public tracks are open to all authenticated users.
        if track.visibility == TrackVisibility.PUBLIC:
            return self._build_signed_url(track)

        # Private / project tracks require elevated privileges or ownership.
        is_owner = track.owner_id == user_id
        is_manager = has_role(user_roles, RoleName.TRACK_MANAGER)
        is_admin = has_role(user_roles, RoleName.ADMINISTRATOR)

        if not (is_owner or is_manager or is_admin):
            raise AuthorizationError(
                "You do not have permission to access this track"
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

        stmt = (
            select(Track)
            .join(Assembly, Track.assembly_id == Assembly.id)
            .where(
                Track.is_deleted.is_(False),
                Track.status == TrackStatus.READY,
                Assembly.name == assembly_name,
            )
        )
        result = await db.execute(stmt)
        tracks = result.scalars().all()

        jbrowse_tracks = [self._track_to_jbrowse(t, assembly_name) for t in tracks]

        return {
            "assembly": {"name": assembly_name},
            "tracks": jbrowse_tracks,
        }

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    async def _get_track_or_404(self, db: AsyncSession, track_id: int) -> Track:
        result = await db.execute(
            select(Track).where(Track.id == track_id, Track.is_deleted.is_(False))
        )
        track = result.scalar_one_or_none()
        if track is None:
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
            "file_url": track.file_url,
            "index_url": track.index_url,
            "owner_id": str(track.owner_id) if track.owner_id else None,
            "visibility": track.visibility,
            "status": track.status,
            "created_at": track.created_at.isoformat() if track.created_at else None,
        }

    @staticmethod
    def _track_to_jbrowse(track: Track, assembly_name: str) -> dict[str, Any]:
        """Convert a database Track to a JBrowse 2 track configuration dict."""
        from ..models.tracks import FileFormat, TrackType

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
            adapter["vcfGzLocation"] = {"uri": track.file_url, "locationType": "UriLocation"}
            if track.index_url:
                adapter["index"] = {"location": {"uri": track.index_url, "locationType": "UriLocation"}}
        elif adapter_type == "Gff3TabixAdapter":
            adapter["gffGzLocation"] = {"uri": track.file_url, "locationType": "UriLocation"}
            if track.index_url:
                adapter["index"] = {"location": {"uri": track.index_url, "locationType": "UriLocation"}}
        elif adapter_type in ("BigWigAdapter", "BigBedAdapter"):
            key = "bigWigLocation" if adapter_type == "BigWigAdapter" else "bigBedLocation"
            adapter[key] = {"uri": track.file_url, "locationType": "UriLocation"}
        elif adapter_type == "BamAdapter":
            adapter["bamLocation"] = {"uri": track.file_url, "locationType": "UriLocation"}
            if track.index_url:
                adapter["index"] = {"location": {"uri": track.index_url, "locationType": "UriLocation"}}
        else:
            adapter["uri"] = track.file_url

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
    def _build_signed_url(track: Track) -> SignedUrlResponse:
        """Build a (mock) signed URL.

        In production this would call S3/MinIO ``presigned_get_object``.
        """
        return SignedUrlResponse(
            url=track.file_url,
            expires_in=3600,
        )
