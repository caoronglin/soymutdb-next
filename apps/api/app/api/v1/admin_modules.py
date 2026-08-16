"""Admin module schema endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from fastapi.responses import PlainTextResponse

from ...core.exceptions import NotFoundError
from ...core.security import RoleName, has_role
from ...models.auth import User
from ...services.module_schema_registry import get_schema
from .deps import get_current_user, get_user_roles

router = APIRouter(prefix="/admin/modules", tags=["admin-modules"])


def _require_admin(user: User) -> None:
    roles = get_user_roles(user)
    if not has_role(roles, RoleName.ADMINISTRATOR):
        from ...core.exceptions import AuthorizationError

        raise AuthorizationError("Administrator access required")


@router.get("/{module_key}/template", response_class=PlainTextResponse)
async def download_module_template(
    module_key: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download a TSV template for a module schema."""
    _require_admin(current_user)
    schema = get_schema(module_key)
    if schema is None:
        raise NotFoundError(f"Unknown module schema '{module_key}'")

    headers = [col.name for col in schema.columns]
    example: list[str] = []
    for col in schema.columns:
        if col.name == "gene_id":
            example.append("Glyma.01G000100")
        elif col.name == "chromosome":
            example.append("Chr01")
        elif col.name == "start":
            example.append("1")
        elif col.name == "end":
            example.append("1000")
        elif col.name == "mutation_feature":
            example.append("")
        else:
            example.append("")

    content = "\t".join(headers) + "\n" + "\t".join(example) + "\n"
    return PlainTextResponse(
        content,
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{module_key}.tsv"'},
    )
