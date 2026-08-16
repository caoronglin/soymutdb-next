"""Admin module schema endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import PlainTextResponse
from fastapi.responses import Response as _Response

from ...core.exceptions import NotFoundError, ValidationError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...services.module_schema_registry import get_schema, render_module_template
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/modules", tags=["admin-modules"])


def _require_admin(user: User) -> None:
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        from ...core.exceptions import AuthorizationError

        raise AuthorizationError("Administrator access required")


@router.get("/{module_key}/template")
async def download_module_template(
    module_key: str,
    format: str = Query(default="tsv"),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download a starter template for a module schema.

    ``format`` is one of ``tsv`` / ``txt`` / ``csv`` / ``xlsx`` (default
    ``tsv``).  ``xlsx`` returns a binary workbook; the text formats return
    plain text with the matching media type and ``Content-Disposition``.
    """
    _require_admin(current_user)
    schema = get_schema(module_key)
    if schema is None:
        raise NotFoundError(f"Unknown module schema '{module_key}'")

    try:
        content, media_type, filename = render_module_template(module_key, format)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    if isinstance(content, bytes):
        return _Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return PlainTextResponse(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
