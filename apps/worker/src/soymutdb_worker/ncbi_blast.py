"""Safe NCBI BLAST+ runner; lifecycle integration belongs to the BLAST task.

Binary/database parents and the job work directory are operator-controlled.
Query input is bounded to 1 MiB before shared validation (100k residues).
Each child, including version discovery, receives explicit resource limits.
Published results contain executable name/version/hash, never its private path.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

PROGRAM_DATABASE_TYPES = {
    "blastn": "nucl",
    "blastp": "prot",
    "blastx": "prot",
    "tblastn": "nucl",
    "tblastx": "nucl",
}
OUTFMT6 = (
    "qseqid",
    "sseqid",
    "pident",
    "length",
    "mismatch",
    "gapopen",
    "qstart",
    "qend",
    "sstart",
    "send",
    "evalue",
    "bitscore",
)


class NcbiBlastError(ValueError):
    pass


@dataclass(frozen=True)
class SearchLimits:
    wall_seconds: int = 300
    memory_bytes: int = 2 * 1024**3
    output_bytes: int = 64 * 1024**2
    threads: int = 1


def validate_program_database(program: str, db_type: str) -> tuple[str, str]:
    if program not in PROGRAM_DATABASE_TYPES:
        raise NcbiBlastError("unsupported BLAST program")
    if db_type != PROGRAM_DATABASE_TYPES[program]:
        raise NcbiBlastError("incompatible database type")
    query_type = "prot" if program in {"blastp", "tblastn"} else "nucl"
    return db_type, query_type


def _shared_query(text: str, program: str) -> tuple[str, int, int]:
    try:
        from soymutdb_jobs.blast_search import normalize_query

        result = normalize_query(text, program)
        return result.normalized_fasta, result.query_length, result.record_count
    except ImportError:
        raise NcbiBlastError("shared BLAST query validator unavailable") from None
    except ValueError:
        raise NcbiBlastError("invalid BLAST query") from None


def _binary(bin_dir: Path, program: str) -> Path:
    if not bin_dir.is_absolute() or bin_dir.is_symlink():
        raise NcbiBlastError("invalid BLAST binary directory")
    path = bin_dir / program
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise NcbiBlastError("invalid BLAST executable")
    return path


def build_command(program, db_type, db_path, query_path, output_path, parameters, bin_dir):
    from soymutdb_jobs.blast_search import validate_search_parameters

    validate_program_database(program, db_type)
    try:
        params = validate_search_parameters(program, "ncbi_blast", parameters)
    except ValueError:
        raise NcbiBlastError("invalid BLAST search parameters") from None
    argv = [
        str(_binary(Path(bin_dir), program)),
        "-query",
        str(query_path),
        "-db",
        str(db_path),
        "-out",
        str(output_path),
        "-outfmt",
        "6 " + " ".join(OUTFMT6),
    ]
    for key, value in params.items():
        if key == "perc_identity":
            if program != "blastn":
                raise NcbiBlastError("perc_identity is supported only for blastn")
            argv.extend(["-perc_identity", str(value)])
            continue
        if key in {"dust", "soft_masking"}:
            value = ("yes" if value else "no") if key == "dust" else str(value).lower()
        argv.extend(["-" + key, str(value)])
    if "num_threads" not in params:
        argv.extend(["-num_threads", "1"])
    return argv


def _env(cwd: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(cwd),
        "TMPDIR": str(cwd),
        "OMP_NUM_THREADS": "1",
        "BLAST_USAGE_REPORT": "false",
        "NCBI_DONT_USE_NCBIRC": "1",
        "NCBI_DONT_USE_LOCAL_CONFIG": "1",
    }


_LIMIT_EXEC = """import os,resource,sys
memory,size,seconds=map(int,sys.argv[1:4])
resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
resource.setrlimit(resource.RLIMIT_FSIZE,(size,size))
resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
os.execv(sys.argv[4],sys.argv[4:])
"""


def _execute(command, cwd, limits):
    import sys
    import tempfile
    import time

    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-c",
                _LIMIT_EXEC,
                str(limits.memory_bytes),
                str(limits.output_bytes),
                str(limits.wall_seconds),
                *command,
            ],
            cwd=cwd,
            env=_env(cwd),
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + limits.wall_seconds
            while process.poll() is None:
                if (
                    os.fstat(stdout.fileno()).st_size > limits.output_bytes
                    or os.fstat(stderr.fileno()).st_size > limits.output_bytes
                ):
                    raise NcbiBlastError("BLAST diagnostic output exceeded limit")
                if time.monotonic() >= deadline:
                    raise NcbiBlastError("BLAST wall time exceeded")
                time.sleep(0.01)
            if process.returncode:
                raise NcbiBlastError("BLAST execution failed")
            if (
                os.fstat(stdout.fileno()).st_size > limits.output_bytes
                or os.fstat(stderr.fileno()).st_size > limits.output_bytes
            ):
                raise NcbiBlastError("BLAST diagnostic output exceeded limit")
            stdout.seek(0)
            return stdout.read(limits.output_bytes).decode("ascii")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _provenance(binary, cwd, limits):
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    version = _execute([str(binary), "-version"], cwd, limits).splitlines()
    if not version or not re.fullmatch(
        re.escape(binary.name) + r": [0-9]+(?:\.[0-9]+)+(?:\+)?", version[0]
    ):
        raise NcbiBlastError("unrecognized BLAST executable version")
    return {"program": binary.name, "version": version[0], "sha256": digest.hexdigest()}


def run_search(
    program: str,
    db_type: str,
    db_path: Path,
    query_path: Path,
    output_path: Path,
    parameters: dict,
    bin_dir: Path,
    limits: SearchLimits = SearchLimits(),
) -> dict:
    validate_program_database(program, db_type)
    if (
        type(limits.threads) is not int
        or not 1 <= limits.threads <= 4
        or type(limits.wall_seconds) is not int
        or not 1 <= limits.wall_seconds <= 3600
        or type(limits.memory_bytes) is not int
        or not 64 * 1024**2 <= limits.memory_bytes <= 16 * 1024**3
        or type(limits.output_bytes) is not int
        or not 1 <= limits.output_bytes <= 256 * 1024**2
    ):
        raise NcbiBlastError("invalid resource limits")
    query_path = Path(query_path)
    output_path = Path(output_path)
    if (
        query_path.is_symlink()
        or not query_path.is_file()
        or output_path.exists()
        or output_path.is_symlink()
    ):
        raise NcbiBlastError("invalid query/output path")
    if query_path.stat().st_size > 1024 * 1024:
        raise NcbiBlastError("query file exceeds size limit")
    with os.fdopen(os.open(query_path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        data = source.read(1024 * 1024 + 1)
    if len(data) > 1024 * 1024:
        raise NcbiBlastError("query file exceeds size limit")
    text = data.decode("ascii")
    normalized, query_len, record_count = _shared_query(text, program)
    normalized_query = output_path.parent / (f".{output_path.name}.query")
    if normalized_query.exists() or normalized_query.is_symlink():
        raise NcbiBlastError("query staging path already exists")
    command = build_command(
        program, db_type, Path(db_path), normalized_query, output_path, parameters, Path(bin_dir)
    )
    requested_threads = parameters.get("num_threads", 1)
    if requested_threads > limits.threads:
        raise NcbiBlastError("requested threads exceed resource limit")
    with normalized_query.open("x", encoding="ascii") as target:
        target.write(normalized)
    binary = Path(command[0])

    try:
        provenance = _provenance(binary, output_path.parent, limits)
        _execute(command, output_path.parent, limits)
        if (
            output_path.is_symlink()
            or not output_path.is_file()
            or output_path.stat().st_size > limits.output_bytes
        ):
            raise NcbiBlastError("BLAST output invalid or oversized")
    except OSError, UnicodeError:
        raise NcbiBlastError("cannot execute BLAST") from None
    finally:
        try:
            normalized_query.unlink()
        except FileNotFoundError:
            pass
    with os.fdopen(os.open(output_path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as artifact:
        output = artifact.read(limits.output_bytes + 1)
    if len(output) > limits.output_bytes:
        raise NcbiBlastError("BLAST output limit exceeded")
    raw = output.decode("ascii")
    hits = parse_tabular(raw)
    return {
        "binary": provenance,
        "output_sha256": hashlib.sha256(output).hexdigest(),
        "output_bytes": output_path.stat().st_size,
        "query_len": query_len,
        "record_count": record_count,
        "hit_count": len(hits),
        "total_hits": len(hits),
        "hits": hits,
    }


def parse_tabular(text: str) -> list[dict[str, object]]:
    hits = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if (
            len(line) > 65536
            or len(fields) != 12
            or any(
                not field or any(ord(c) < 32 or c.isspace() for c in field) for field in fields[:2]
            )
        ):
            raise NcbiBlastError("invalid BLAST tabular row")
        try:
            nums = [
                float(fields[2]),
                int(fields[3]),
                int(fields[4]),
                int(fields[5]),
                int(fields[6]),
                int(fields[7]),
                int(fields[8]),
                int(fields[9]),
                float(fields[10]),
                float(fields[11]),
            ]
        except ValueError:
            raise NcbiBlastError("invalid BLAST numeric field") from None
        if (
            not all(-(2**63) < x < 2**63 for x in nums)
            or not all(math.isfinite(x) for x in nums)
            or not 0 <= nums[0] <= 100
            or nums[1] <= 0
            or nums[2] > nums[1]
            or nums[3] > nums[1]
            or any(x < 0 for x in nums[2:])
            or any(x < 1 for x in nums[4:8])
            or nums[8] < 0
            or nums[9] < 0
        ):
            raise NcbiBlastError("invalid BLAST hit bounds")
        q_start, q_end, s_start, s_end = nums[4:8]
        hits.append(
            {
                "query_id": fields[0],
                "subject_id": fields[1],
                "subject_title": "",
                "percent_identity": nums[0],
                "alignment_length": nums[1],
                "mismatches": nums[2],
                "gap_opens": nums[3],
                "query_start": q_start,
                "query_end": q_end,
                "subject_start": s_start,
                "subject_end": s_end,
                "evalue": nums[8],
                "bit_score": nums[9],
                "query_strand": "plus" if q_start <= q_end else "minus",
                "subject_strand": "plus" if s_start <= s_end else "minus",
            }
        )
    return hits
