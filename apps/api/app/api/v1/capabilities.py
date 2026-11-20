"""Public server capabilities for feature-gated clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.database import get_db
from ...core.features import FeatureFlagService
from ...core.plugins import get_plugin_registry
from ...schemas.features import (
    DatabaseCapabilitiesResponse,
    PluginCapabilityResponse,
    PublicCapabilitiesResponse,
)
from ...services import sequence_tools_service
from ...services.plugin_service import PluginService

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=PublicCapabilitiesResponse)
async def get_capabilities(db: AsyncSession = Depends(get_db)) -> PublicCapabilitiesResponse:
    plugin_states = await PluginService.snapshot(db, get_plugin_registry())
    return PublicCapabilitiesResponse(
        features=await FeatureFlagService.snapshot(db, public_only=True),
        plugins={
            key: PluginCapabilityResponse(
                version=state.version,
                installed=state.installed,
                enabled=state.enabled,
                configured=state.configured,
                healthy=state.healthy,
                public_url=state.public_url,
                assemblies=list(state.assemblies),
                reason=state.reason,
            )
            for key, state in plugin_states.items()
        },
        databases=DatabaseCapabilitiesResponse(),
        sequence=sequence_tools_service.capabilities(),
    )
