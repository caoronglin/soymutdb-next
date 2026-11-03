"""Operator-only, immutable NCBI BLAST index builder (no search or queue integration).

The output root is an operator-controlled directory, not writable by untrusted
users. Concurrent builders are supported; hostile mutation of that directory by
another OS principal is outside this module's trust boundary. Child processes
receive fixed arguments, no inherited secrets, and POSIX resource limits.
Parent FASTA parsing uses bounded in-memory input; parent RAM scales with source
size. The memory limit applies to child tools, not this Python operator process.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from soymutdb_jobs.blast_catalog import public_source_url
from soymutdb_jobs.protein_fasta import ProteinFastaError, parse_protein_fasta

BUILD_VERSION = "soymutdb-ncbi-index-v1"
IDENTITY = re.compile(r"[a-f0-9]{64}\Z")
FILE_NAME = re.compile(r"db\.[a-z0-9.]+\Z")
NUCLEOTIDES = frozenset("ACGTURYSWKMBDHVN")


class IndexBuildError(ValueError):
    """Sanitized operator failure; never includes FASTA, child stderr or paths."""


@dataclass(frozen=True)
class BuildMetadata:
    assembly_id: str
    assembly_version: str
    release_id: str
    annotation_version: str
    source_url: str
    source_version: str
    license: str

    def validate(self) -> None:
        for key, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip() or len(value) > 1024:
                raise IndexBuildError(f"invalid metadata: {key}")
            if any(ord(ch) < 32 for ch in value) or "\\" in value:
                raise IndexBuildError(f"invalid metadata: {key}")
            if key != "source_url" and ("/" in value or value in {".", ".."}):
                raise IndexBuildError(f"metadata must not contain paths: {key}")
        if public_source_url(self.source_url) is None:
            raise IndexBuildError("source_url must be public attribution without credentials")


@dataclass(frozen=True)
class BuildLimits:
    max_source_bytes: int = 256 * 1024 * 1024
    wall_seconds: int = 300
    memory_bytes: int = 2 * 1024**3
    max_output_bytes: int = 1024 * 1024
    max_index_bytes: int = 4 * 1024**3
    threads: int = 1

    def validate(self) -> None:
        bounds = {"max_source_bytes": (1, 1024**3), "wall_seconds": (1, 3600),
                  "memory_bytes": (64 * 1024**2, 16 * 1024**3),
                  "max_output_bytes": (1024, 64 * 1024**2),
                  "max_index_bytes": (1024, 64 * 1024**3), "threads": (1, 1)}
        for key, (low, high) in bounds.items():
            value = getattr(self, key)
            if type(value) is not int or not low <= value <= high:
                raise IndexBuildError(f"invalid resource limit: {key}")


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            + "\n").encode()


def _safe_path(path: Path, *, directory: bool = False) -> Path:
    if ".." in path.parts:
        raise IndexBuildError("parent traversal is forbidden")
    path = Path(os.path.abspath(path))
    for item in (*reversed(path.parents), path):
        if item.is_symlink():
            raise IndexBuildError("symlink paths are forbidden")
    if directory and not path.is_dir():
        raise IndexBuildError("output root must be an existing directory")
    return path


def _read_regular(path: Path, max_bytes: int) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise IndexBuildError("file is not regular or exceeds size limit")
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise IndexBuildError("file exceeds size limit")
            return data
    except OSError:
        raise IndexBuildError("cannot read regular file") from None


def _digest_regular(path: Path, max_bytes: int) -> tuple[int, str]:
    """Hash genome-size artifacts with bounded parent memory and no symlink follows."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise IndexBuildError("file is not regular or exceeds size limit")
            digest = hashlib.sha256()
            size = 0
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise IndexBuildError("file exceeds size limit")
                digest.update(chunk)
            return size, digest.hexdigest()
    except OSError:
        raise IndexBuildError("cannot hash regular file") from None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# Use an exec wrapper instead of preexec_fn: safe when operator calls the module
# from a multithreaded process. No shell, LD_* or PYTHON* environment inheritance.
_RUNNER = """import os,resource,sys
memory,size,seconds=map(int,sys.argv[1:4])
resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
resource.setrlimit(resource.RLIMIT_FSIZE,(size,size))
resource.setrlimit(resource.RLIMIT_CPU,(seconds,seconds))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
os.execv(sys.argv[4],sys.argv[4:])
"""


def _run(binary: Path, arguments: list[str], cwd: Path, limits: BuildLimits) -> str:
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                   "HOME": str(cwd), "TMPDIR": str(cwd), "OMP_NUM_THREADS": "1",
                   "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "BLAST_USAGE_REPORT": "false", "NCBI_DONT_USE_NCBIRC": "1",
                   "NCBI_DONT_USE_LOCAL_CONFIG": "1"}
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(
                [sys.executable, "-I", "-c", _RUNNER, str(limits.memory_bytes),
                 str(limits.max_index_bytes), str(limits.wall_seconds), str(binary), *arguments],
                cwd=cwd, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                start_new_session=True,
            )
            try:
                # Poll output sizes as well as elapsed wall time; never buffer an
                # unbounded child response in parent memory.
                deadline = time.monotonic() + limits.wall_seconds
                while process.poll() is None:
                    size = 0
                    for artifact in cwd.iterdir():
                        try:
                            info = artifact.lstat()
                        except FileNotFoundError:
                            # NCBI atomically renames temporary index pieces.
                            continue
                        if not stat.S_ISREG(info.st_mode):
                            raise IndexBuildError("unexpected child artifact")
                        size += info.st_size
                    if size > limits.max_index_bytes + limits.max_source_bytes:
                        raise IndexBuildError("index total size exceeded")
                    if (os.fstat(stdout.fileno()).st_size > limits.max_output_bytes
                            or os.fstat(stderr.fileno()).st_size > limits.max_output_bytes):
                        raise IndexBuildError("binary output limit exceeded")
                    if time.monotonic() >= deadline:
                        raise IndexBuildError("binary wall time exceeded")
                    time.sleep(0.01)
                if process.returncode:
                    raise IndexBuildError("BLAST binary failed")
                if (os.fstat(stdout.fileno()).st_size > limits.max_output_bytes
                        or os.fstat(stderr.fileno()).st_size > limits.max_output_bytes):
                    raise IndexBuildError("binary output limit exceeded")
                stdout.seek(0)
                return stdout.read(limits.max_output_bytes).decode("utf-8", errors="strict")
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    except (OSError, UnicodeError):
        raise IndexBuildError("cannot execute BLAST binary") from None


def _binary(value: str | Path, name: str, cwd: Path, limits: BuildLimits) -> tuple[Path, dict]:
    found = shutil.which(str(value)) if not Path(value).is_absolute() else str(value)
    if not found:
        raise IndexBuildError(f"{name} unavailable")
    path = _safe_path(Path(found))
    _, checksum = _digest_regular(path, 512 * 1024**2)
    version_output = _run(path, ["-version"], cwd, limits)
    match = re.search(rf"\b{re.escape(name)}:\s*([0-9]+(?:\.[0-9]+)+(?:\+)?)", version_output)
    if not match:
        raise IndexBuildError(f"unrecognized {name} version")
    if _digest_regular(path, 512 * 1024**2)[1] != checksum:
        raise IndexBuildError("binary changed during version check")
    return path, {"name": name, "version": match[1], "sha256": checksum}


def _fasta(data: bytes, db_type: str) -> tuple[bytes, int, int, int]:
    try:
        text = data.decode("ascii")
        if db_type == "prot":
            parsed = parse_protein_fasta(text)
            if parsed.synthesized_header:
                raise IndexBuildError("index FASTA requires explicit record identifiers")
            return (parsed.to_fasta.encode(), len(parsed.records),
                    sum(len(record.sequence) for record in parsed.records), parsed.query_length)
        if db_type != "nucl":
            raise IndexBuildError("db_type must be nucl or prot")
        records: list[tuple[str, str]] = []
        seen: set[str] = set()
        current: str | None = None
        chunks: list[str] = []

        def close() -> None:
            if current is None:
                return
            sequence = "".join(chunks)
            if not sequence or current in seen:
                raise IndexBuildError("empty nucleotide record or duplicate identifier")
            seen.add(current)
            records.append((current, sequence))

        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = line.strip(" \t")
            if line.startswith(">"):
                close()
                current = line[1:].split()[0] if line[1:].split() else None
                if not current:
                    raise IndexBuildError("FASTA identifier missing")
                chunks = []
            elif line:
                sequence = line.replace(" ", "").replace("\t", "").upper()
                if current is None or set(sequence) - NUCLEOTIDES:
                    raise IndexBuildError("invalid nucleotide FASTA")
                chunks.append(sequence)
        close()
        if not records:
            raise IndexBuildError("empty nucleotide FASTA")
        normalized = "".join(f">{key}\n{sequence}\n" for key, sequence in records).encode()
        count = sum(len(sequence) for _, sequence in records)
        return normalized, len(records), count, count
    except (UnicodeError, ProteinFastaError):
        raise IndexBuildError("invalid protein or nucleotide FASTA") from None


def _validate_database(binary: Path, directory: Path, db_type: str,
                       sequences: int, letters: int, limits: BuildLimits) -> None:
    args = ["-db", "db", "-dbtype", db_type]
    info = _run(binary, [*args, "-info"], directory, limits)
    match = re.search(
        r"([\d,]+)\s+sequences?;\s*([\d,]+)\s+total\s+(?:letters|bases|residues)", info,
    )
    if not match or [int(part.replace(",", "")) for part in match.groups()] != [
        sequences, letters
    ]:
        raise IndexBuildError("database info count mismatch")
    lengths = _run(binary, [*args, "-entry", "all", "-outfmt", "%l"], directory, limits)
    try:
        values = [int(line) for line in lengths.splitlines()]
    except ValueError:
        raise IndexBuildError("invalid database sequence lengths") from None
    if len(values) != sequences or sum(values) != letters or any(value < 1 for value in values):
        raise IndexBuildError("database contents count mismatch")


def _artifact_inventory(directory: Path, limits: BuildLimits) -> list[dict]:
    result = []
    total = 0
    for path in sorted(directory.iterdir()):
        if path.name == "manifest.json":
            continue
        if not FILE_NAME.fullmatch(path.name):
            raise IndexBuildError("unexpected index artifact")
        size, checksum = _digest_regular(path, limits.max_index_bytes)
        total += size
        if total > limits.max_index_bytes:
            raise IndexBuildError("index total size exceeded")
        result.append({"name": path.name, "bytes": size, "sha256": checksum})
    if not result:
        raise IndexBuildError("index contains no artifacts")
    return result


def _verify_files(root: Path, identity: str, limits: BuildLimits,
                  expected: dict | None = None) -> tuple[Path, dict]:
    if not IDENTITY.fullmatch(identity):
        raise IndexBuildError("invalid index identity")
    directory = _safe_path(root / identity, directory=True)
    try:
        raw = _read_regular(directory / "manifest.json", 1024 * 1024)
        manifest = json.loads(raw)
        request = manifest["request"]
        if (raw != _canonical(manifest) or _sha(_canonical(request)) != identity
                or manifest["index_identity"] != identity or manifest["index_prefix"] != "db"
                or request["build_version"] != BUILD_VERSION
                or request["db_type"] not in {"nucl", "prot"}
                or (expected is not None and request != expected)):
            raise IndexBuildError("manifest identity mismatch")
        BuildMetadata(**request["metadata"]).validate()
        if _artifact_inventory(directory, limits) != manifest["files"]:
            raise IndexBuildError("index checksum mismatch")
        for field in ("sequence_count", "letter_count", "residue_count"):
            if type(request[field]) is not int or request[field] < 1:
                raise IndexBuildError("invalid manifest counts")
        return directory, manifest
    except (KeyError, TypeError, json.JSONDecodeError):
        raise IndexBuildError("invalid index manifest") from None


def verify_index(output_root: Path, index_identity: str, *,
                 blastdbcmd_bin: str | Path = "blastdbcmd",
                 limits: BuildLimits = BuildLimits()) -> dict:
    """Verify canonical identity, every relative artifact checksum and BLAST content."""
    limits.validate()
    root = _safe_path(output_root, directory=True)
    directory, manifest = _verify_files(root, index_identity, limits)
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=root) as temp:
        binary, provenance = _binary(blastdbcmd_bin, "blastdbcmd", Path(temp), limits)
    if provenance != manifest["request"]["binaries"]["blastdbcmd"]:
        raise IndexBuildError("verification binary provenance mismatch")
    request = manifest["request"]
    _validate_database(binary, directory, request["db_type"], request["sequence_count"],
                       request["letter_count"], limits)
    return {"index_identity": index_identity, "index_prefix": f"{index_identity}/db",
            "manifest": manifest, "reused": True}


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def build_index(source: Path, output_root: Path, db_type: str, metadata: BuildMetadata, *,
                makeblastdb_bin: str | Path = "makeblastdb",
                blastdbcmd_bin: str | Path = "blastdbcmd",
                limits: BuildLimits = BuildLimits()) -> dict:
    """Build a content-addressed sibling staging directory and atomically publish it."""
    limits.validate()
    metadata.validate()
    if db_type not in {"nucl", "prot"}:
        raise IndexBuildError("db_type must be nucl or prot")
    root = _safe_path(output_root, directory=True)
    source = _safe_path(source)
    # Read exactly one no-follow descriptor. Hash and build use these same bytes;
    # mutations of the original after this read cannot affect the index content.
    data = _read_regular(source, limits.max_source_bytes)
    normalized, sequences, letters, residues = _fasta(data, db_type)
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        make, make_provenance = _binary(makeblastdb_bin, "makeblastdb", staging, limits)
        cmd, cmd_provenance = _binary(blastdbcmd_bin, "blastdbcmd", staging, limits)
        request = {"build_version": BUILD_VERSION, "db_type": db_type,
                   "metadata": asdict(metadata), "source_sha256": _sha(data),
                   "normalized_sha256": _sha(normalized), "sequence_count": sequences,
                   "letter_count": letters, "residue_count": residues,
                   "binaries": {"makeblastdb": make_provenance, "blastdbcmd": cmd_provenance},
                   "options": {"blastdb_version": 4, "parse_seqids": True}}
        identity = _sha(_canonical(request))
        destination = root / identity
        if destination.exists() or destination.is_symlink():
            _verify_files(root, identity, limits, request)
            return verify_index(root, identity, blastdbcmd_bin=cmd, limits=limits)
        snapshot = staging / "input.fasta"
        snapshot.write_bytes(normalized)
        _run(make, ["-in", "input.fasta", "-out", "db", "-dbtype", db_type,
                    "-title", identity, "-parse_seqids", "-blastdb_version", "4"], staging, limits)
        snapshot.unlink()
        _validate_database(cmd, staging, db_type, sequences, letters, limits)
        manifest = {"index_identity": identity, "index_prefix": "db", "request": request,
                    "files": _artifact_inventory(staging, limits)}
        (staging / "manifest.json").write_bytes(_canonical(manifest))
        for path in staging.iterdir():
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        _sync_directory(staging)
        # Serialize only publication, not expensive construction. A directory
        # descriptor lock adds no mutable lock artifact and prevents even an
        # empty pre-existing destination from being overwritten.
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(root_fd, fcntl.LOCK_EX)
            if destination.exists() or destination.is_symlink():
                _verify_files(root, identity, limits, request)
                return verify_index(root, identity, blastdbcmd_bin=cmd, limits=limits)
            os.rename(staging, destination)
            os.fsync(root_fd)
        finally:
            fcntl.flock(root_fd, fcntl.LOCK_UN)
            os.close(root_fd)
        return {"index_identity": identity, "index_prefix": f"{identity}/db",
                "manifest": manifest, "reused": False}
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", allow_abbrev=False)
    verify = sub.add_parser("verify", allow_abbrev=False)
    for item in (build, verify):
        item.add_argument("--output-root", type=Path, required=True)
        item.add_argument("--blastdbcmd-bin", default=os.getenv("SOYMUTDB_BLASTDBCMD_BIN",
                                                              "blastdbcmd"))
        item.add_argument("--wall-seconds", type=int, default=300)
        item.add_argument("--memory-bytes", type=int, default=2 * 1024**3)
        item.add_argument("--max-output-bytes", type=int, default=1024**2)
        item.add_argument("--max-index-bytes", type=int, default=4 * 1024**3)
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--db-type", choices=("nucl", "prot"), required=True)
    build.add_argument("--makeblastdb-bin", default=os.getenv("SOYMUTDB_MAKEBLASTDB_BIN",
                                                            "makeblastdb"))
    build.add_argument("--max-source-bytes", type=int, default=256 * 1024**2)
    for key in BuildMetadata.__dataclass_fields__:
        build.add_argument("--" + key.replace("_", "-"), required=True)
    verify.add_argument("--index-identity", required=True)
    args = parser.parse_args(argv)
    limits = BuildLimits(max_source_bytes=getattr(args, "max_source_bytes", 256 * 1024**2),
                         wall_seconds=args.wall_seconds, memory_bytes=args.memory_bytes,
                         max_output_bytes=args.max_output_bytes,
                         max_index_bytes=args.max_index_bytes)
    try:
        if args.command == "build":
            metadata = BuildMetadata(**{key: getattr(args, key)
                                        for key in BuildMetadata.__dataclass_fields__})
            result = build_index(args.source, args.output_root, args.db_type, metadata,
                                 makeblastdb_bin=args.makeblastdb_bin,
                                 blastdbcmd_bin=args.blastdbcmd_bin, limits=limits)
        else:
            result = verify_index(args.output_root, args.index_identity,
                                  blastdbcmd_bin=args.blastdbcmd_bin, limits=limits)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (IndexBuildError, OSError):
        print(json.dumps({"error": "blast_index_failed"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
