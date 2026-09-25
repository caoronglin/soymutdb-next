#!/usr/bin/env python3
"""Create (or reset) a local administrator account in a development database.

The admin console and the portal's `/login` both need an account, and a fresh
development database has none — so "sign in" fails with a generic message and
looks like a bug rather than an empty database. This creates one.

It is deliberately *not* a seed fixture: it takes the password from the caller,
refuses to run against a database whose `app_env` is not `dev`, and prints what
it did. Nothing here is imported by the application.

Usage
    SOYMUTDB_DATABASE_URL=postgresql+asyncpg://... \
      apps/api/.venv/bin/python scripts/dev/seed-local-account.py \
      --username admin --email admin@local --password 'choose-a-password'
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="admin")
    parser.add_argument("--email", default="admin@local")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    if os.environ.get("SOYMUTDB_APP_ENV", "dev") != "dev":
        print(
            "refusing to run: this creates a known credential and is only for a "
            f"development database (SOYMUTDB_APP_ENV={os.environ.get('SOYMUTDB_APP_ENV')!r})",
            file=sys.stderr,
        )
        return 2
    if len(args.password) < 12:
        print("refusing to run: choose a password of at least 12 characters", file=sys.stderr)
        return 2

    from sqlalchemy import select

    from app.core.database import get_session_factory
    from app.core.security import RoleName, hash_password
    from app.models.auth import Role, User

    async with get_session_factory()() as session:
        role = (
            await session.execute(select(Role).where(Role.name == RoleName.ADMINISTRATOR.value))
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                name=RoleName.ADMINISTRATOR.value,
                description="Local development administrator",
                permissions={},
            )
            session.add(role)
            await session.flush()

        user = (
            await session.execute(select(User).where(User.username == args.username))
        ).scalar_one_or_none()
        if user is None:
            user = User(
                username=args.username,
                email=args.email,
                password_hash=hash_password(args.password),
                full_name="Local administrator",
                role_id=role.id,
                is_active=True,
            )
            session.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(args.password)
            user.role_id = role.id
            user.is_active = True
            action = "password reset"
        await session.commit()

    print(f"{action}: {args.username} ({args.email}) with role {RoleName.ADMINISTRATOR.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
