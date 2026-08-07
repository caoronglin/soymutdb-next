#!/usr/bin/env python3
"""CLI script to create or update the initial administrator account.

Usage:
    python -m apps.api.app.scripts.create_admin \\
        --username admin --email admin@soymutdb.local --password <password>

Alternatively, set the environment variables::

    SOYMUTDB_ADMIN_USERNAME=admin \\
    SOYMUTDB_ADMIN_EMAIL=admin@soymutdb.local \\
    SOYMUTDB_ADMIN_PASSWORD=<password> \\
    python -m apps.api.app.scripts.create_admin

With ``--reset`` the script updates an existing admin's password (otherwise it
skips if the admin already exists).

Requires the application database to be reachable (``SOYMUTDB_DATABASE_URL``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.database import get_session_factory
from ..core.security import (
    RoleName,
    hash_password,
    validate_password_strength,
)
from ..models.auth import AuditLog, Role, User


async def create_admin(
    username: str,
    email: str,
    password: str,
    reset: bool = False,
) -> None:
    """Create or update the administrator account.

    Args:
        username: Admin username.
        email: Admin email address.
        password: Plain-text password (validated before hashing).
        reset: If True, update an existing admin's password.
    """
    # 1. Validate password strength.
    valid, reason = validate_password_strength(password)
    if not valid:
        print(f"ERROR: Password validation failed: {reason}")
        return

    # 2. Hash password.
    password_hash = hash_password(password)
    print(f"Password strength: OK (hashed with Argon2id)")

    # 3. Resolve ADMINISTRATOR role.
    factory = get_session_factory()
    async with factory() as db:
        role_result = await db.execute(
            select(Role).where(Role.name == RoleName.ADMINISTRATOR.value)
        )
        role = role_result.scalar_one_or_none()
        if role is None:
            print("ERROR: ADMINISTRATOR role not found in the database. Run migrations first.")
            return

        # 4. Check if admin user already exists.
        result = await db.execute(
            select(User).where(
                (User.username == username) | (User.email == email)
            )
        )
        existing = result.scalar_one_or_none()

        if existing and not reset:
            print(
                f"Admin user '{username}' already exists (id={existing.id}). "
                "Use --reset to update the password."
            )
            return

        if existing and reset:
            # Update password.
            existing.password_hash = password_hash
            print(f"Updated password for admin '{username}' (id={existing.id}).")
            user = existing
        else:
            # Create new admin user.
            user = User(
                id=uuid.uuid4(),
                username=username,
                email=email,
                password_hash=password_hash,
                full_name="System Administrator",
                role_id=role.id,
                is_active=True,
                is_superuser=True,
                joined_at=datetime.now(timezone.utc),
            )
            db.add(user)
            await db.flush()
            print(f"Created admin user '{username}' (id={user.id}).")

        # 5. Log creation to AuditLog.
        db.add(
            AuditLog(
                user_id=user.id,
                action="admin_created" if not existing else "admin_password_reset",
                resource_type="user",
                resource_id=str(user.id),
                new_value={"username": username, "email": email},
                ip_address="localhost",
                timestamp=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    print("Done.")


def main() -> None:
    """Entry point for CLI invocation."""
    parser = argparse.ArgumentParser(
        description="Create or update the SoyMutDB administrator account."
    )
    parser.add_argument("--username", default=None, help="Admin username")
    parser.add_argument("--email", default=None, help="Admin email")
    parser.add_argument("--password", default=None, help="Admin password")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset password for existing admin user",
    )
    args = parser.parse_args()

    username = args.username or os.environ.get("SOYMUTDB_ADMIN_USERNAME", "admin")
    email = args.email or os.environ.get("SOYMUTDB_ADMIN_EMAIL", "admin@soymutdb.local")
    password = args.password or os.environ.get("SOYMUTDB_ADMIN_PASSWORD")

    if not password:
        print("ERROR: Password is required. Provide via --password or SOYMUTDB_ADMIN_PASSWORD.")
        return

    asyncio.run(create_admin(username, email, password, reset=args.reset))


if __name__ == "__main__":
    main()
