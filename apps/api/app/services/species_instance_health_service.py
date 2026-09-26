"""Allowlisted, anonymous liveness checks for registered instance peers.

This service is intentionally not a proxy. It can only issue a small GET to a
fixed path, only for an HTTPS origin listed in deployment configuration, and
never forwards the caller's identity or credentials.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.audit import log_action
from ..core.exceptions import NotFoundError
from ..models.table_views import SpeciesInstance
from ..schemas.table_views import SpeciesInstanceHealthResponse

HEALTH_ALLOWLIST_ENV = "SOYMUTDB_INSTANCE_HEALTH_ALLOWLIST"
HEALTH_PATH = "/api/v1/health/live"
HEALTH_STALE_AFTER = timedelta(minutes=10)
MAX_HEALTH_BODY_BYTES = 4096
HEALTH_TIMEOUT_SECONDS = 2.5


def _https_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    hostname = parsed.hostname.lower()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = f"{hostname}:{port}" if port is not None and port != 443 else hostname
    return f"https://{netloc}"


def configured_health_origins(raw: str | None = None) -> frozenset[str]:
    """Parse exact HTTPS origins from a comma- or newline-separated env value."""
    configured = os.environ.get(HEALTH_ALLOWLIST_ENV, "") if raw is None else raw
    origins = {
        origin
        for item in configured.replace("\n", ",").split(",")
        if item.strip()
        if (origin := _https_origin(item)) is not None
    }
    return frozenset(origins)


def is_instance_health_stale(instance: SpeciesInstance, *, now: datetime | None = None) -> bool:
    if instance.connection_state not in {"healthy", "unhealthy"}:
        return instance.last_checked_at is None
    if instance.last_checked_at is None:
        return True
    checked_at = instance.last_checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) - checked_at > HEALTH_STALE_AFTER


async def _probe_registered_peer(instance: SpeciesInstance) -> tuple[str, str | None, bool]:
    """Return (state, error code, did_network_probe) for the fixed liveness URL."""
    origin = _https_origin(instance.api_base_url)
    if origin is None:
        return "unconfigured", "https_origin_required", False
    allowed_origins = configured_health_origins()
    if not allowed_origins:
        return "unconfigured", "trust_not_configured", False
    if origin not in allowed_origins:
        return "unconfigured", "peer_not_allowlisted", False

    target_url = f"{origin}{HEALTH_PATH}"
    timeout = httpx.Timeout(HEALTH_TIMEOUT_SECONDS, connect=1.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            async with client.stream("GET", target_url, headers={"Accept": "application/json"}) as response:
                if response.is_redirect:
                    return "unhealthy", "redirect_rejected", True
                if response.status_code != 200:
                    return "unhealthy", "http_status", True
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_HEALTH_BODY_BYTES:
                        return "unhealthy", "response_too_large", True
        payload = json.loads(body)
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return "unhealthy", "invalid_health_response", True
    except httpx.TimeoutException:
        return "unhealthy", "timeout", True
    except httpx.RequestError:
        return "unhealthy", "connect_error", True
    except (json.JSONDecodeError, UnicodeDecodeError):
        return "unhealthy", "invalid_health_response", True
    except Exception:
        # Keep peer exception text, URL and response details out of API/audit logs.
        return "unhealthy", "probe_error", True
    return "healthy", None, True


async def check_species_instance_health(
    db: AsyncSession,
    *,
    instance_id: int,
    actor_id,
    ip_address: str | None,
) -> SpeciesInstanceHealthResponse:
    """Check one registry row and persist only bounded operational status."""
    instance = await db.get(SpeciesInstance, instance_id)
    if instance is None:
        raise NotFoundError("Species instance not found")

    now = datetime.now(UTC)
    previous_state = instance.connection_state
    previous_error_code = instance.last_error_code
    if not instance.is_enabled:
        state, error_code, did_probe = "disabled", None, False
    elif instance.is_local:
        # The current request has already reached this API and its database.
        state, error_code, did_probe = "healthy", None, False
        instance.last_checked_at = now
    else:
        state, error_code, did_probe = await _probe_registered_peer(instance)
        if did_probe:
            instance.last_checked_at = now

    instance.connection_state = state
    instance.last_error_code = error_code
    if state == "unhealthy":
        instance.last_error_at = now

    # An unhealthy probe is auditable each time; other state changes are logged
    # once. The audit payload contains no URL, token, response body or biology.
    if state == "unhealthy" or state != previous_state or error_code != previous_error_code:
        await log_action(
            db,
            user_id=actor_id,
            action="species_instance_health_checked",
            resource_type="species_instance",
            resource_id=str(instance.id),
            old_value={
                "connection_state": previous_state,
                "error_code": previous_error_code,
            },
            new_value={"connection_state": state, "error_code": error_code},
            ip_address=ip_address,
        )

    await db.commit()
    await db.refresh(instance)
    return SpeciesInstanceHealthResponse(
        id=instance.id,
        code=instance.code,
        connection_state=instance.connection_state,  # type: ignore[arg-type]
        checked_at=now,
        last_checked_at=instance.last_checked_at,
        last_error_at=instance.last_error_at,
        is_stale=is_instance_health_stale(instance, now=now),
        error_code=instance.last_error_code,
        remote_management="local" if instance.is_local else "registration_only",
    )


__all__ = [
    "HEALTH_ALLOWLIST_ENV",
    "HEALTH_PATH",
    "HEALTH_STALE_AFTER",
    "check_species_instance_health",
    "configured_health_origins",
    "is_instance_health_stale",
]
