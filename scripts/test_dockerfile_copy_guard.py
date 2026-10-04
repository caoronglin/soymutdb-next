"""Exercise the release COPY guard against isolated build contexts."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_copy_guard_missing_source_and_restore(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/check-dockerfile-copy.sh", scripts)
    (scripts / "list-images.sh").write_text(
        "soymutdb_image_entry() { printf '%s\n' 'fixture|.|Dockerfile'; }\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    dockerfile = tmp_path / "Dockerfile"
    original = "FROM scratch\nCOPY package.json /package.json\n"
    dockerfile.write_text(original, encoding="utf-8")

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(scripts / "check-dockerfile-copy.sh")],
            capture_output=True, text=True, check=False,
        )

    assert run().returncode == 0
    dockerfile.write_text(original.replace("COPY package.json", "COPY missing.json"), encoding="utf-8")
    mutant = run()
    assert mutant.returncode == 1
    assert "Dockerfile:2" in mutant.stdout
    assert "missing.json" in mutant.stdout
    dockerfile.write_text(original, encoding="utf-8")
    assert run().returncode == 0
