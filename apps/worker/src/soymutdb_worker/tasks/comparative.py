"""Comparative-genomics artifacts: multiple-sequence alignments and trees.

The task runs a small, allowlisted command line and writes exactly one object
per artifact. Three properties matter more than speed:

* **The input is frozen.** The job payload carries the ordered member ids and
  the hash the API computed over them. If the family changed between request
  and execution, the recomputed hash differs and the run fails instead of
  labelling an artifact with an input it was not computed from.
* **One job, one artifact.** Re-delivered messages are skipped once the row is
  terminal; a second run cannot overwrite a published object.
* **Similarity is not orthology.** Nothing here classifies relationships. The
  aligner produces an alignment; the tree builder produces a tree. Neither
  writes a homology claim into ``gene_family_members``.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from celery import Task
from soymutdb_jobs.contract import QUEUE_ANALYSES
from sqlalchemy import select, update

from soymutdb_worker.config import get_setting
from soymutdb_worker.main import celery_app
from soymutdb_worker.tables import comparative_artifacts, gene_family_members, utcnow
from soymutdb_worker.utils.db import get_db
from soymutdb_worker.utils.s3 import get_s3_client

logger = logging.getLogger(__name__)

COMPARATIVE_ARTIFACT_TASK = "soymutdb_worker.tasks.comparative.build_artifact"

#: Methods the worker will execute. The API refuses anything else before it
#: reaches the queue; this list is the second gate, not a duplicate of a
#: policy that lives elsewhere.
ALLOWED_METHODS = ("mafft", "muscle", "iqtree", "fasttree")

#: Hard ceiling: an alignment over thousands of genes is a batch job, not an
#: interactive artifact, and would hold a worker slot for hours.
MAX_MEMBERS = 2000

#: Object prefix for every artifact this task writes.
OBJECT_PREFIX = "comparative"


#: Bucket for derived artifacts. Each artifact family owns a bucket, matching
#: the worker's other writes (``analyses``, ``blast-dbs``, ``exports``).
COMPARATIVE_BUCKET = get_setting("S3_COMPARATIVE_BUCKET", "comparative")


class ArtifactInputError(ValueError):
    """The frozen input no longer matches, or is unusable."""


def input_fingerprint(member_ids: list[str]) -> str:
    """Same order-sensitive hash the API computes; kept byte-identical."""
    digest = hashlib.sha256()
    for member in member_ids:
        digest.update(member.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Reject a payload that cannot produce an honest artifact."""
    required = (
        "artifact_id",
        "artifact_type",
        "method",
        "input_sha256",
        "member_ids",
        "release_id",
        "assembly_id",
    )
    missing = [key for key in required if payload.get(key) in (None, "")]
    if missing:
        raise ArtifactInputError(f"artifact payload missing {', '.join(missing)}")
    artifact_type = payload["artifact_type"]
    if artifact_type not in {"msa", "tree"}:
        raise ArtifactInputError(f"unknown artifact type {artifact_type!r}")
    method = payload["method"]
    if method not in ALLOWED_METHODS:
        raise ArtifactInputError(f"unknown artifact method {method!r}")
    members = payload["member_ids"]
    if not isinstance(members, list) or not members:
        raise ArtifactInputError("artifact requires at least one member")
    if len(members) > MAX_MEMBERS:
        raise ArtifactInputError(f"artifact input exceeds {MAX_MEMBERS} members")
    if input_fingerprint(list(members)) != payload["input_sha256"]:
        # The frozen hash is the only thing tying the artifact to its input.
        raise ArtifactInputError("input hash does not match the member list")
    if artifact_type == "tree" and len(members) < 3:
        # A tree over two sequences is not a tree; it is a pairwise distance.
        raise ArtifactInputError("a phylogenetic tree requires at least three members")
    return payload


def build_command(method: str, artifact_type: str, fasta: Path, workdir: Path) -> list[str]:
    """Argument arrays only -- never a shell string assembled from input."""
    if method == "mafft":
        if artifact_type != "msa":
            raise ArtifactInputError("mafft produces alignments, not trees")
        return ["mafft", "--auto", "--quiet", str(fasta)]
    if method == "muscle":
        if artifact_type != "msa":
            raise ArtifactInputError("muscle produces alignments, not trees")
        return ["muscle", "-align", str(fasta), "-output", str(workdir / "aln.fasta")]
    if method == "iqtree":
        if artifact_type != "tree":
            raise ArtifactInputError("iqtree produces trees, not alignments")
        return ["iqtree2", "-s", str(fasta), "-fast", "-quiet"]
    if method == "fasttree":
        if artifact_type != "tree":
            raise ArtifactInputError("fasttree produces trees, not alignments")
        return ["fasttree", "-quiet", str(fasta)]
    raise ArtifactInputError(f"unknown artifact method {method!r}")


def _member_sequences(db, members: list[str]) -> dict[str, str]:
    """Member accessions -> sequences.

    The platform stores coordinates, not residues, so a family member has no
    sequence to align. Returning an empty mapping is the honest answer and the
    caller fails the artifact with ``no_sequence_store`` instead of aligning
    placeholders.
    """
    rows = db.execute(
        select(gene_family_members.c.gene_accession).where(
            gene_family_members.c.gene_accession.in_(members)
        )
    ).all()
    # Presence check only: this proves the members exist, it does not invent
    # sequences for them.
    if not rows:
        raise ArtifactInputError("none of the members exist in this release")
    return {}


def _claim(db, artifact_id: str) -> dict[str, Any] | None:
    """Move a pending artifact to running; ``None`` when it is not claimable."""
    row = db.execute(
        select(
            comparative_artifacts.c.id,
            comparative_artifacts.c.state,
            comparative_artifacts.c.artifact_type,
            comparative_artifacts.c.method,
            comparative_artifacts.c.input_sha256,
            comparative_artifacts.c.input_member_ids,
        ).where(comparative_artifacts.c.id == uuid.UUID(str(artifact_id)))
    ).first()
    if row is None:
        return None
    state = row[1]
    if state in {"running", "succeeded", "failed"}:
        return None
    claimed = db.execute(
        update(comparative_artifacts)
        .where(
            comparative_artifacts.c.id == uuid.UUID(str(artifact_id)),
            comparative_artifacts.c.state == "pending",
        )
        .values(state="running")
    )
    if not getattr(claimed, "rowcount", 0):
        return None
    return {
        "id": str(row[0]),
        "artifact_type": row[2],
        "method": row[3],
        "input_sha256": row[4],
        "member_ids": list(row[5] or []),
    }


def _finish(db, artifact_id: str, *, object_key: str, object_sha256: str) -> None:
    db.execute(
        update(comparative_artifacts)
        .where(comparative_artifacts.c.id == uuid.UUID(str(artifact_id)))
        .values(
            state="succeeded",
            object_key=object_key,
            object_sha256=object_sha256,
            error_message=None,
            completed_at=utcnow(),
        )
    )


def _fail(db, artifact_id: str, reason: str) -> None:
    # ``where`` has to match the row type of ``comparative_artifacts.id``
    # (UUID); passing the Python string silently matches nothing and leaves the
    # artifact stuck in ``running`` for the download endpoint to misreport.
    db.execute(
        update(comparative_artifacts)
        .where(comparative_artifacts.c.id == uuid.UUID(str(artifact_id)))
        .values(state="failed", error_message=reason[:2000], completed_at=utcnow())
    )


def _run(command: list[str], *, workdir: Path) -> str:
    """Execute one allowlisted tool and return its output text."""
    if shutil.which(command[0]) is None:
        raise ArtifactInputError(f"{command[0]} is not installed on this worker")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    if completed.returncode != 0:
        # stderr is operator diagnostic only; it never reaches the API payload.
        raise ArtifactInputError(f"{command[0]} exited {completed.returncode}")
    output_file = workdir / "aln.fasta"
    if output_file.is_file():
        return output_file.read_text()
    return completed.stdout


@celery_app.task(bind=True, name=COMPARATIVE_ARTIFACT_TASK, queue=QUEUE_ANALYSES)
def build_artifact(
    self: Task,  # noqa: ARG001 - Celery binds the task instance
    payload: dict | None = None,
    *,
    artifact_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compute one alignment or tree and store it as an object.

    Accepts the outbox ``JobPayload`` (canonical) or a legacy ``artifact_id``
    keyword. The frozen member list and its hash come from the payload; the row
    is the authority for state.
    """
    job_payload = payload or {}
    body = job_payload.get("payload", job_payload)
    identifier = artifact_id or body.get("artifact_id")
    if not identifier:
        raise ArtifactInputError("artifact_id is required")

    with get_db() as db:
        claimed = _claim(db, str(identifier))
    if claimed is None:
        # Re-delivery of a finished or in-flight artifact: nothing to do.
        return {"artifact_id": identifier, "skipped": True}

    try:
        frozen = validate_payload(
            {
                "artifact_id": claimed["id"],
                "artifact_type": body.get("artifact_type", claimed["artifact_type"]),
                "method": body.get("method", claimed["method"]),
                "input_sha256": body.get("input_sha256", claimed["input_sha256"]),
                "member_ids": body.get("member_ids", claimed["member_ids"]),
                "release_id": body.get("release_id"),
                "assembly_id": body.get("assembly_id"),
            }
        )
        if frozen["input_sha256"] != claimed["input_sha256"]:
            raise ArtifactInputError("member set changed after the request was frozen")

        with get_db() as db:
            sequences = _member_sequences(db, list(frozen["member_ids"]))
        if not sequences:
            raise ArtifactInputError(
                "no_sequence_store: the platform holds coordinates, not residues, "
                "so there is nothing to align"
            )

        with tempfile.TemporaryDirectory(prefix="comparative-") as tmp:
            workdir = Path(tmp)
            fasta = workdir / "members.fasta"
            fasta.write_text("".join(f">{name}\n{seq}\n" for name, seq in sequences.items()))
            command = build_command(frozen["method"], frozen["artifact_type"], fasta, workdir)
            output = _run(command, workdir=workdir)

        digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
        object_key = (
            f"{OBJECT_PREFIX}/{frozen['release_id']}/{frozen['artifact_type']}/{identifier}.txt"
        )
        get_s3_client().put_object(
            Bucket=COMPARATIVE_BUCKET, Key=object_key, Body=output.encode("utf-8")
        )
        with get_db() as db:
            _finish(db, str(identifier), object_key=object_key, object_sha256=digest)
        return {
            "artifact_id": identifier,
            "state": "succeeded",
            "object_key": object_key,
            "object_sha256": digest,
        }
    except Exception as exc:
        logger.warning("comparative artifact %s failed: %s", identifier, type(exc).__name__)
        with get_db() as db:
            _fail(db, str(identifier), str(exc))
        raise


__all__ = [
    "ALLOWED_METHODS",
    "ArtifactInputError",
    "COMPARATIVE_ARTIFACT_TASK",
    "MAX_MEMBERS",
    "build_artifact",
    "build_command",
    "input_fingerprint",
    "validate_payload",
]
