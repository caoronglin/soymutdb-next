"""Index command/filesystem boundaries; fake executables never perform searches."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from soymutdb_worker import blast_index as index


@pytest.fixture
def metadata():
    return index.BuildMetadata(
        assembly_id="GCF_000001735.4", assembly_version="TAIR10.1", release_id="test-release",
        annotation_version="synthetic-v1", source_url="https://www.ncbi.nlm.nih.gov/nuccore/NC_003070.9",
        source_version="NC_003070.9", license="CC0-1.0",
    )


@pytest.fixture
def binaries(tmp_path):
    # Fixed script protocols mirror the NCBI interface and deliberately fail
    # if a shell/raw option is introduced. Content is synthetic, not biological.
    make = tmp_path / "makeblastdb"
    cmd = tmp_path / "blastdbcmd"
    make.write_text(f"#!{sys.executable}\n" + '''import json, pathlib, sys
if sys.argv[1:] == ['-version']:
    print('makeblastdb: 2.17.0+')
    raise SystemExit
args=sys.argv[1:]
assert '-parse_seqids' in args and args[-2:] == ['-blastdb_version','4']
text=pathlib.Path('input.fasta').read_text()
lengths=[len(record.split('\\n',1)[1].replace('\\n','')) for record in text.split('>')[1:]]
kind=args[args.index('-dbtype')+1]
output=pathlib.Path('db.'+('nin' if kind=='nucl' else 'pin'))
output.write_text(json.dumps({'type':kind,'lengths':lengths}))
''')
    cmd.write_text(f"#!{sys.executable}\n" + '''import json,pathlib,sys
if sys.argv[1:] == ['-version']:
    print('blastdbcmd: 2.17.0+')
    raise SystemExit
args=sys.argv[1:]
assert args[:3] == ['-db','db','-dbtype']
kind=args[3]
data=json.loads(pathlib.Path('db.'+('nin' if kind=='nucl' else 'pin')).read_text())
assert data['type']==kind
if args[4:]==['-info']:
    print(f"{len(data['lengths'])} sequences; {sum(data['lengths'])} total letters")
else:
    assert args[4:]==['-entry','all','-outfmt','%l']
    print('\\n'.join(map(str,data['lengths'])))
''')
    make.chmod(0o700)
    cmd.chmod(0o700)
    return {"makeblastdb_bin": make, "blastdbcmd_bin": cmd}


@pytest.fixture
def files(tmp_path):
    source = tmp_path / "source.fa"
    source.write_text(">forward synthetic\nACGTRYswkmbdhvn\n>reverse synthetic\nNBDHVKMWSRYACGT\n")
    root = tmp_path / "indexes"
    root.mkdir()
    return source, root


def build(files, metadata, binaries, **kwargs):
    return index.build_index(*files, kwargs.pop("db_type", "nucl"), metadata,
                             **binaries, **kwargs)


def test_build_verify_reuse_and_relative_provenance(files, metadata, binaries):
    first = build(files, metadata, binaries)
    assert first["reused"] is False
    assert build(files, metadata, binaries)["reused"] is True
    verified = index.verify_index(files[1], first["index_identity"],
                                  blastdbcmd_bin=binaries["blastdbcmd_bin"])
    assert verified == {**first, "reused": True}
    manifest = first["manifest"]
    assert manifest["request"]["sequence_count"] == 2
    assert manifest["request"]["letter_count"] == 30
    text = json.dumps(first)
    assert str(files[0]) not in text
    assert str(files[1]) not in text
    assert "ACGTRY" not in text
    assert all("/" not in item["name"] for item in manifest["files"])
    assert not list(files[1].glob(".build-*"))


@pytest.mark.parametrize("text", ["", ">x\n", ">x\nACGT\n>x\nTGCA", "ACGT", ">x\nACGT!",
                                 ">\nACGT", ">x\nACGT\n>y\n", ">x\nAC\vGT",
                                 ">x\nAC\fGT"])
def test_invalid_nucleotide_input(files, metadata, binaries, text):
    files[0].write_text(text)
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries)
    assert list(files[1].iterdir()) == []


@pytest.mark.parametrize("text", [">p\nMKWVTFISLL\n", ">p\nACGT\n>q\nMKWVTF\n"])
def test_protein_shared_owner(files, metadata, binaries, text):
    files[0].write_text(text)
    result = build(files, metadata, binaries, db_type="prot")
    assert result["manifest"]["request"]["db_type"] == "prot"


@pytest.mark.parametrize("text", [">p\n", ">p\nMKK\n>p\nMKK", ">p\nMKK!", "MKK", ">p\n*"])
def test_invalid_protein_shared_owner(files, metadata, binaries, text):
    files[0].write_text(text)
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries, db_type="prot")


def test_changed_metadata_and_source_change_identity(files, metadata, binaries):
    first = build(files, metadata, binaries)
    second = build(files, replace(metadata, release_id="release-next"), binaries)
    files[0].write_text(">new\nAGCT\n")
    third = build(files, metadata, binaries)
    assert len({first["index_identity"], second["index_identity"], third["index_identity"]}) == 3
    assert len(list(files[1].iterdir())) == 3


@pytest.mark.parametrize("field,value", [("license", ""), ("source_url", "file:///secret"),
                                          ("assembly_id", "../escape"),
                                          ("source_url", "https://user:pass@example.org/x"),
                                          ("source_url", "https://example.org/?token=secret"),
                                          ("source_url", "http://localhost/source"),
                                          ("source_url", "https://10.0.0.1/source"),
                                          ("source_url", "https://example.org/path#private")])
def test_mandatory_safe_metadata(files, metadata, binaries, field, value):
    with pytest.raises(index.IndexBuildError):
        build(files, replace(metadata, **{field: value}), binaries)
    assert not list(files[1].iterdir())


@pytest.mark.parametrize("kind", ["artifact", "manifest", "directory"])
def test_symlink_published_index_refused(files, metadata, binaries, tmp_path, kind):
    result = build(files, metadata, binaries)
    directory = files[1] / result["index_identity"]
    if kind == "directory":
        moved = tmp_path / "moved"
        directory.rename(moved)
        directory.symlink_to(moved, target_is_directory=True)
    else:
        target = directory / ("manifest.json" if kind == "manifest" else "db.nin")
        moved = tmp_path / "private"
        target.rename(moved)
        target.symlink_to(moved)
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries)


def test_symlink_source_root_and_parent_refused(files, metadata, binaries, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(files[0])
    with pytest.raises(index.IndexBuildError):
        build((link, files[1]), metadata, binaries)
    link.unlink()
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(index.IndexBuildError):
        build((link / "source.fa", files[1]), metadata, binaries)
    with pytest.raises(index.IndexBuildError):
        build((files[0], link / "indexes"), metadata, binaries)


@pytest.mark.parametrize("poison", ["file", "extra", "escape", "request", "noncanonical"])
def test_corruption_and_poisoned_manifest_never_reused(files, metadata, binaries, poison):
    result = build(files, metadata, binaries)
    directory = files[1] / result["index_identity"]
    manifest_path = directory / "manifest.json"
    manifest = result["manifest"]
    if poison == "file":
        (directory / "db.nin").write_text("corrupted")
    elif poison == "extra":
        (directory / "private-file").write_text("secret")
    elif poison == "escape":
        manifest["files"][0]["name"] = "../../secret"
        manifest_path.write_bytes(index._canonical(manifest))
    elif poison == "request":
        manifest["request"]["metadata"]["release_id"] = "wrong"
        manifest_path.write_bytes(index._canonical(manifest))
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2))
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries)
    assert directory.exists()
    assert not list(files[1].glob(".build-*"))


def test_concurrent_publication(files, metadata, binaries):
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: build(files, metadata, binaries), range(3)))
    assert len({item["index_identity"] for item in results}) == 1
    assert sum(not item["reused"] for item in results) == 1
    assert len(list(files[1].iterdir())) == 1


def test_source_mutation_after_read_does_not_change_snapshot(
    files, metadata, binaries, monkeypatch,
):
    original = files[0].read_bytes()
    run = index._run

    def mutate(binary, arguments, cwd, limits):
        if arguments == ["-version"]:
            files[0].write_text(">different\nACGT\n")
        return run(binary, arguments, cwd, limits)

    monkeypatch.setattr(index, "_run", mutate)
    result = build(files, metadata, binaries)
    assert result["manifest"]["request"]["source_sha256"] == index._sha(original)
    assert result["manifest"]["request"]["sequence_count"] == 2


@pytest.mark.parametrize("body,reason", [("import time; time.sleep(5)", "wall time"),
                                       ("raise SystemExit(3)", "failed"),
                                       ("print('x'*10000)", "output limit")])
def test_subprocess_limits_and_failure_cleanup(files, metadata, binaries, body, reason):
    path = binaries["makeblastdb_bin"]
    path.write_text(f"#!{sys.executable}\nimport sys\n"
                    "if sys.argv[1:]==['-version']:\n"
                    " print('makeblastdb: 2.17.0+'); raise SystemExit\n" + body + "\n")
    with pytest.raises(index.IndexBuildError, match=reason):
        build(files, metadata, binaries, limits=index.BuildLimits(wall_seconds=1,
                                                                 max_output_bytes=1024))
    assert not list(files[1].iterdir())


def test_source_size_and_unknown_types(files, metadata, binaries):
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries, limits=index.BuildLimits(max_source_bytes=3))
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries, db_type="protein")
    with pytest.raises(index.IndexBuildError):
        index.verify_index(files[1], "../private")


def test_child_environment_does_not_inherit_secrets(files, metadata, binaries, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private-secret")
    monkeypatch.setenv("LD_PRELOAD", "/private/library")
    path = binaries["makeblastdb_bin"]
    path.write_text(path.read_text().replace(
                    "import json, pathlib, sys", "import json, pathlib, sys, os\n"
                    "assert 'AWS_SECRET_ACCESS_KEY' not in os.environ\n"
                    "assert 'LD_PRELOAD' not in os.environ"))
    build(files, metadata, binaries)


def test_cli_unknown_options_rejected_and_json_error(capsys):
    with pytest.raises(SystemExit) as exc:
        index.main(["build", "--raw-args", "-evil"])
    assert exc.value.code == 2
    assert "private-secret" not in capsys.readouterr().err


def test_no_overwrite_empty_destination_during_publication(files, metadata, binaries, monkeypatch):
    validate = index._validate_database

    def race(binary, directory, db_type, sequences, letters, limits):
        validate(binary, directory, db_type, sequences, letters, limits)
        # Derive identity from the fixed -title supplied to makeblastdb by
        # inspecting the request after a baseline build, in the test below.
        if not (files[1] / identity).exists():
            (files[1] / identity).mkdir()

    first = build(files, metadata, binaries)
    identity = first["index_identity"]
    import shutil
    shutil.rmtree(files[1] / identity)
    monkeypatch.setattr(index, "_validate_database", race)
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries)
    assert list((files[1] / identity).iterdir()) == []


def test_child_creating_symlink_is_refused(files, metadata, binaries):
    path = binaries["makeblastdb_bin"]
    path.write_text(path.read_text().replace(
        "text=pathlib.Path('input.fasta').read_text()",
        "pathlib.Path('db.evil').symlink_to('/etc/passwd')\n"
        "text=pathlib.Path('input.fasta').read_text()"))
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, binaries)
    assert not list(files[1].iterdir())


def test_info_count_mismatch_refused(files, metadata, binaries):
    path = binaries["blastdbcmd_bin"]
    path.write_text(path.read_text().replace("sequences;", "sequences; 900"))
    with pytest.raises(index.IndexBuildError, match="count mismatch"):
        build(files, metadata, binaries)
    assert not list(files[1].iterdir())


def test_binary_content_changes_identity(files, metadata, binaries):
    first = build(files, metadata, binaries)
    path = binaries["makeblastdb_bin"]
    path.write_text(path.read_text() + "\n# patched operator binary\n")
    second = build(files, metadata, binaries)
    assert first["index_identity"] != second["index_identity"]


def test_child_memory_failure_is_bounded_and_cleans_staging(files, metadata, binaries):
    path = binaries["makeblastdb_bin"]
    path.write_text(f"#!{sys.executable}\nimport sys\n"
                    "if sys.argv[1:]==['-version']:\n"
                    " print('makeblastdb: 2.17.0+'); raise SystemExit\n"
                    "data=bytearray(256*1024*1024)\n")
    with pytest.raises(index.IndexBuildError, match="failed"):
        build(files, metadata, binaries, limits=index.BuildLimits(memory_bytes=64*1024**2))
    assert list(files[1].iterdir()) == []


def test_cli_build_and_verify_outputs_only_relative_index(files, metadata, binaries, capsys):
    args = ["build", "--source", str(files[0]), "--output-root", str(files[1]),
            "--db-type", "nucl", "--makeblastdb-bin", str(binaries["makeblastdb_bin"]),
            "--blastdbcmd-bin", str(binaries["blastdbcmd_bin"])]
    for key, value in index.asdict(metadata).items():
        args.extend(["--" + key.replace("_", "-"), value])
    assert index.main(args) == 0
    output = capsys.readouterr().out
    first = json.loads(output)
    assert str(files[1]) not in output and str(files[0]) not in output
    assert index.main(["verify", "--output-root", str(files[1]), "--index-identity",
                       first["index_identity"], "--blastdbcmd-bin",
                       str(binaries["blastdbcmd_bin"])]) == 0
    assert json.loads(capsys.readouterr().out)["reused"]
    with pytest.raises(SystemExit) as exc:
        index.main([*args, "--raw-args", "evil"])
    assert exc.value.code == 2


def test_file_hashing_streams_without_whole_artifact_read(tmp_path, monkeypatch):
    artifact = tmp_path / "db.nin"
    artifact.write_bytes(b"x" * (3 * 1024**2 + 17))
    monkeypatch.setattr(index, "_read_regular", lambda *_: pytest.fail("whole artifact read"))
    inventory = index._artifact_inventory(tmp_path, index.BuildLimits())
    assert inventory == [{"name": "db.nin", "bytes": 3 * 1024**2 + 17,
                          "sha256": index._sha(b"x" * (3 * 1024**2 + 17))}]


def test_symlink_binary_and_parent_traversal_refused(files, metadata, binaries, tmp_path):
    link = tmp_path / "makeblastdb-link"
    link.symlink_to(binaries["makeblastdb_bin"])
    with pytest.raises(index.IndexBuildError):
        build(files, metadata, {**binaries, "makeblastdb_bin": link})
    with pytest.raises(index.IndexBuildError):
        build((files[0].parent / ".." / files[0].parent.name / files[0].name, files[1]),
              metadata, binaries)


def test_runner_tolerates_ncbi_atomic_temp_file_renames(files, binaries, monkeypatch):
    original = Path.iterdir

    def with_disappeared_temp(path):
        yield from original(path)
        if path == files[1]:
            yield path / "db.already-renamed-tmp"

    monkeypatch.setattr(Path, "iterdir", with_disappeared_temp)
    assert "2.17.0+" in index._run(binaries["makeblastdb_bin"], ["-version"], files[1],
                                  index.BuildLimits())
