"""Local publication adapter (Phase 3 Task 5).

Stages the immutable artifact by copying it to a fresh version directory
under the configured root, fsyncs the files, verifies the manifest digest,
then atomically replaces a ``current`` symlink with ``os.replace`` so a
failed stage/verify never changes the live pointer.

Rollback restores the previous version directory by re-pointing ``current``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import DeploymentRef, ValidationEvidence, verify_manifest


class LocalAdapter:
    target = "local"

    def __init__(self, root: str | None) -> None:
        self.root = Path(root).resolve() if root else None

    def _check_configured(self) -> Path:
        if self.root is None:
            raise RuntimeError("local publication root is not configured (PUBLICATION_LOCAL_ROOT)")
        return self.root

    def stage(self, publication_id: int, artifact: Path) -> DeploymentRef:
        root = self._check_configured()
        version_dir = root / "releases" / f"{publication_id}"
        if version_dir.exists():
            shutil.rmtree(version_dir)
        version_dir.mkdir(parents=True, exist_ok=False)
        # Copy files first, then fsync directory + files.
        _copy_tree(artifact, version_dir)
        _fsync_tree(version_dir)
        return DeploymentRef(
            target=self.target,
            ref=str(version_dir),
            manifest_digest=_read_manifest_digest(version_dir),
            artifact_path=str(version_dir),
        )

    def verify(self, deployment: DeploymentRef) -> ValidationEvidence:
        artifact = Path(deployment.artifact_path)
        return verify_manifest(artifact, deployment.manifest_digest)

    def promote(self, deployment: DeploymentRef) -> str:
        root = self._check_configured()
        version_dir = Path(deployment.ref)
        current = root / "current"
        current_tmp = root / ".current.tmp"
        # Point a temporary symlink at the staged directory, then atomically
        # replace ``current`` with os.replace (never leaves a dangling link).
        if current_tmp.exists() or current_tmp.is_symlink():
            current_tmp.unlink()
        current_tmp.symlink_to(version_dir, target_is_directory=True)
        os.replace(current_tmp, current)
        return str(version_dir)

    def rollback(self, remote_id: str) -> str:
        root = self._check_configured()
        target = Path(remote_id)
        if not target.is_dir():
            raise RuntimeError(f"rollback target not found: {remote_id}")
        current = root / "current"
        current_tmp = root / ".current.tmp"
        if current_tmp.exists() or current_tmp.is_symlink():
            current_tmp.unlink()
        current_tmp.symlink_to(target, target_is_directory=True)
        os.replace(current_tmp, current)
        return str(target)


def _read_manifest_digest(artifact: Path) -> str:
    from .base import manifest_digest_of_file

    return manifest_digest_of_file(artifact / "manifest.json")


def _copy_tree(src: Path, dst: Path) -> None:
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)


def _fsync_tree(root: Path) -> None:
    for item in root.rglob("*"):
        if item.is_file():
            with open(item, "rb") as fh:
                os.fsync(fh.fileno())
    # fsync the directories themselves so the entries are durable.
    for dirpath in sorted([p for p in root.rglob("*") if p.is_dir()], reverse=True):
        fd = os.open(dirpath, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


__all__ = ["LocalAdapter"]
