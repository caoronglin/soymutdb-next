"""Auth dependencies for widget endpoints – re-exports from v1 deps."""

from __future__ import annotations

from ..api.v1.deps import (
    bearer_scheme,
    get_current_user,
    get_optional_user,
    get_user_roles,
    require_role,
)
from ..core.security import RoleName
from ..models.auth import User

# Pre-built admin dependency – equivalent to Depends(require_role(ADMINISTRATOR))
# but usable as a standalone dependency in widget routers.
require_admin = require_role(RoleName.ADMINISTRATOR)

__all__ = [
    "User",
    "bearer_scheme",
    "get_current_user",
    "get_optional_user",
    "get_user_roles",
    "require_admin",
    "require_role",
]
