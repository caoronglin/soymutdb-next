"""Enforce the CNB-primary / GitHub-mirror delivery architecture.

The delivery pipeline used to exist only as four GitHub Actions workflows with
their build/test/scan logic inlined. The logic now lives in checked-in scripts
that both CI providers call, and `.cnb.yml` is authoritative. These contracts
fail when someone re-inlines logic into a workflow, or when the two providers
stop agreeing on the pins and job list.

Run with: python3 -m unittest scripts.test_ci_job_contracts -v
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

NODE_VERSION = "26.13.0"
PNPM_VERSION = "12.11.2"
PYTHON_VERSION = "3.15"

CNB_CONFIG = ROOT / ".cnb.yml"
LEGACY_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/baseline-validation.yml",
    ".github/workflows/pages.yml",
    ".github/workflows/e2e-smoke.yml",
)

SHARED_SCRIPTS = (
    "scripts/ci-job-steps.sh",
    "scripts/setup-workspace.sh",
    "scripts/install_python_workspace.py",
    "scripts/stage-pages-publication.sh",
    "scripts/verify-frontend-artifacts.sh",
    "scripts/verify-backend-tests.sh",
    "scripts/verify-bio-core.sh",
    "scripts/check_bio_core_wheel.py",
    "scripts/install-worker-science-build-deps.sh",
    "scripts/with-postgres-service.sh",
    "scripts/build-static-apps.sh",
    "scripts/build-all-static-apps.sh",
    "scripts/ci-nightly-artifact-gate.sh",
    "scripts/build-release-image.sh",
    "scripts/release-contract.golden.sh",
    "scripts/build-pages-artifact.sh",
    "scripts/verify-pages-artifact.sh",
    "scripts/verify-site-variant-artifacts.sh",
    "scripts/verify-artifact-e2e.sh",
    "scripts/mcp-transport-smoke.sh",
    "scripts/assert-clickhouse-migration.py",
    "scripts/smoke.sh",
    "scripts/start-cloud-dev.sh",
    "scripts/acceptance.sh",
)

# Independent floor for the tuple above. Every assertion keyed on SHARED_SCRIPTS
# derives its expectation FROM that tuple, so deleting an entry deletes the
# assertion with it and the whole suite stays green while a gate goes
# unguarded. This list is written out by hand on purpose: it must not be
# computed from SHARED_SCRIPTS, or it inherits the same blind spot. Entries are
# the scripts whose disappearance would silently remove a gate, not merely a
# convenience wrapper.
REQUIRED_SHARED_SCRIPTS = (
    "scripts/ci-job-steps.sh",
    "scripts/setup-workspace.sh",
    "scripts/install_python_workspace.py",
    "scripts/stage-pages-publication.sh",
    "scripts/verify-frontend-artifacts.sh",
    "scripts/verify-backend-tests.sh",
    "scripts/verify-bio-core.sh",
    "scripts/check_bio_core_wheel.py",
    "scripts/install-worker-science-build-deps.sh",
    "scripts/with-postgres-service.sh",
    "scripts/build-static-apps.sh",
    "scripts/build-all-static-apps.sh",
    "scripts/ci-nightly-artifact-gate.sh",
    "scripts/build-release-image.sh",
    "scripts/release-contract.golden.sh",
    "scripts/build-pages-artifact.sh",
    "scripts/verify-pages-artifact.sh",
    "scripts/verify-site-variant-artifacts.sh",
    "scripts/verify-artifact-e2e.sh",
    "scripts/mcp-transport-smoke.sh",
    "scripts/assert-clickhouse-migration.py",
    "scripts/smoke.sh",
    "scripts/start-cloud-dev.sh",
    "scripts/acceptance.sh",
)

PIPELINE_FILES = (
    ".cnb/pipelines/verify.yml",
    ".cnb/pipelines/api.yml",
    ".cnb/pipelines/dependency-governance.yml",
    ".cnb/pipelines/docker-images.yml",
    ".cnb/pipelines/release.yml",
    ".cnb/pipelines/pages-publish.yml",
    ".cnb/pipelines/acceptance.yml",
)


def _cnb() -> dict:
    return yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))


# CNB data-volume types (docs.cnb.cool/zh/build/grammar.md#pipeline-volumes).
# The declared type defaults to copy-on-write when omitted.
_CNB_VOLUME_TYPES = frozenset(
    {
        "rw",
        "ro",
        "cow",
        "data",
        "read-write",
        "read-only",
        "copy-on-write",
        "copy-on-write-read-only",
    }
)


def _cnb_volume_path(entry: str, location: str) -> str:
    """Return the mount path of a CNB `docker.volumes` entry, or fail the test.

    A CNB volume is `<group>:<path>:<type>`, `<path>:<type>` or `<path>` -- it is
    NOT Docker's `host:container`. Misreading the format is what made the first
    attempt at this fix fail a second time in Prepare:

        volumes:
          - /cache/pnpm-store:/cache/pnpm-store

    CNB splits that into group=/cache/pnpm-store, path=/cache/pnpm-store and no
    type, then rejects the leading segment as an unknown *type*:

        Pipeline prepare error:
          Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store

    The old version of this test accepted any 2-segment entry whose first part
    started with "/" and silently treated it as a path, so it validated a
    document CNB refuses to prepare. Assert the real grammar instead.
    """
    parts = entry.split(":")
    if len(parts) > 3:
        raise AssertionError(
            f"{location}: volume {entry!r} has {len(parts)} colon-separated "
            "segments; the grammar is <group>:<path>:<type>"
        )
    if len(parts) == 3:
        group, path, volume_type = parts
        if not group:
            raise AssertionError(f"{location}: volume {entry!r} has an empty group")
        if volume_type not in _CNB_VOLUME_TYPES:
            raise AssertionError(
                f"{location}: volume {entry!r}: unknown type {volume_type!r}; "
                f"expected one of {sorted(_CNB_VOLUME_TYPES)}"
            )
    elif len(parts) == 2:
        path, volume_type = parts
        if volume_type not in _CNB_VOLUME_TYPES:
            # e.g. `- /cache/pnpm-store:/cache/pnpm-store`: the second segment is
            # a CONTAINER PATH, not a type, so CNB reads the first as the type
            # and fails Prepare with "Unsupported volume type".
            raise AssertionError(
                f"{location}: volume {entry!r}: {volume_type!r} is not a volume "
                "type -- CNB parses `<path>:<type>`, not Docker's `host:container`; "
                "use a bare `- <path>` to mount the same path on the node"
            )
    else:
        path = parts[0]
    if not path.startswith("/"):
        raise AssertionError(
            f"{location}: volume {entry!r}: path {path!r} must be absolute"
        )
    return path


def _cnb_pipelines(branch: str, event: str) -> list[dict]:
    document = _cnb()
    return document.get(branch, {}).get(event, []) or []


def _pipeline_names(branch: str, event: str) -> set[str]:
    return {pipeline["name"] for pipeline in _cnb_pipelines(branch, event)}


def _cnb_text() -> str:
    return CNB_CONFIG.read_text(encoding="utf-8")


def _iter_script_bodies(node: object, path: str = ""):
    """Yield (location, body) for every `script:` value, at any nesting depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "script" and isinstance(value, str):
                yield path, value
            else:
                yield from _iter_script_bodies(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_script_bodies(value, f"{path}[{index}]")


def _iter_pipelines(node: object):
    """Yield every pipeline object, whatever branch/event nests it.

    The CNB config is `branch -> event -> [pipeline]`. Walking it generically
    keeps the assertions from hard-coding a shape that a new event would break.
    """
    if isinstance(node, dict):
        if "stages" in node or "name" in node:
            yield node
            return
        for value in node.values():
            yield from _iter_pipelines(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_pipelines(value)


class _DevAllowlist:
    """The shipped `resolveDevAllowedHosts` plus Vite's own matching rule.

    Vite does not do a plain membership test on `allowedHosts`: an entry that
    starts with a dot (`.cnb.space`) matches that domain *and every subdomain*,
    which is exactly what a generated `cnb-38o-1k28dm5ta-001.cnb.space` needs.
    Re-deriving that rule inside the test would let the assertion agree with
    itself while the dev server still blocked the request, so both halves are
    taken from the code that ships: the allowlist from
    `apps/web/src/lib/deployment.ts`, the matching rule from Vite itself
    (`server.allowedHosts` is normalized into RegExps over the host, without the
    port — github.com/vitejs/vite, `createServer`).
    """

    def __init__(self, entries: list[str] | bool) -> None:
        self.raw = entries
        self.is_wildcard = entries is True
        self.entries: list[str] = [] if entries is True else sorted(entries)
        explicit = [] if entries is True else list(entries)
        self._wildcard = any(entry in ("*", "true") for entry in explicit)
        # Vite: an entry that starts with a dot means "this domain and every
        # subdomain"; every other entry is an exact host.
        self._suffixes = [entry[1:].lower() for entry in explicit if entry.startswith(".")]
        self._exact = {
            entry.lower() for entry in explicit if entry and not entry.startswith(".")
        }

    def accept(self, host: str, value: str | None = None) -> bool:
        """Would Vite accept this `Host` header?

        `value` keeps the signature parallel to `_load_dev_allowlist`; the
        allowlist is already bound to it at construction time.
        """
        del value
        if self.is_wildcard or self._wildcard:
            return True
        # The Host header carries a port and an optional IPv6 bracket; Vite
        # matches on the hostname alone.
        hostname = host.strip().lower()
        if hostname.startswith("["):
            hostname = hostname[: hostname.index("]") + 1]
        else:
            hostname = hostname.rsplit(":", 1)[0]
        if hostname in self._exact:
            return True
        return any(hostname == suffix or hostname.endswith("." + suffix) for suffix in self._suffixes)


def _node_major_version(executable: str) -> int | None:
    """Major version reported by `executable`, or None when it cannot run."""
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = re.match(r"v?(\d+)\.", completed.stdout.strip())
    return int(match.group(1)) if match else None


def _capable_node_executables() -> list[str]:
    """Return Node 24+ interpreters, PATH first, then native system paths.

    The shipped helper uses TypeScript syntax (``as const``) and the parent
    program uses ``stripTypeScriptTypes``, both of which need Node 24+. A
    mounted-filesystem Node can be runnable as a parent while denying child
    exec, so native ``/usr/bin`` and ``/usr/local/bin`` candidates are kept.
    """
    candidates: list[str] = []
    for candidate in (shutil.which("node"), "/usr/bin/node", "/usr/local/bin/node"):
        if candidate is None:
            continue
        resolved = str(Path(candidate).resolve())
        if resolved not in candidates:
            candidates.append(resolved)
    return [candidate for candidate in candidates if (_node_major_version(candidate) or 0) >= 24]


def _load_dev_allowlist(value: str | None = None) -> _DevAllowlist:
    """Evaluate the SHIPPED `resolveDevAllowedHosts` and expose its matcher.

    A static assertion on the source text cannot answer "does this allowlist
    cover the generated CNB hostname?" -- the answer lives in the matching
    rules. The helper is therefore extracted, executed through Node's built-in
    TypeScript support (the repository's Node 24 pin runs a `.ts` file
    directly), and probed with a table of real hosts, so the test and the dev
    server cannot disagree about the pattern.
    """
    source = (ROOT / "packages/shared/src/deployment.ts").read_text(encoding="utf-8")
    # From the first helper constant to the end of the helper: the function
    # closes over `CNB_DEV_HOSTS` / `CNB_DEV_HOST_SUFFIXES`, so extracting only
    # the function body would evaluate against free variables.
    start = source.index("const CNB_DEV_HOST_SUFFIXES")
    body = source[start:].replace("export function", "function")

    candidates = _capable_node_executables()
    if not candidates:
        searched = shutil.which("node") or "none on PATH"
        raise AssertionError(
            "resolveDevAllowedHosts needs Node 24+ (the helper is TypeScript and "
            "the loader uses `stripTypeScriptTypes`), but no capable interpreter "
            f"was found; PATH node: {searched}; also checked /usr/bin/node and "
            "/usr/local/bin/node"
        )
    # The parent runs the extraction program; PATH Node is normally the pinned
    # CI interpreter, so prefer it and only fall back to a native system Node if
    # PATH is too old.
    node = candidates[0]
    # Prefer a native system Node for the child probe: a checkout may run Node
    # from a mounted filesystem where child exec is denied even though the parent
    # is runnable. If that exec is denied anyway, the program's inline vm
    # fallback still evaluates the helper.
    native = [candidate for candidate in candidates if candidate.startswith("/usr/")]
    probe_node = native[0] if native else node

    program = (
        "import fs from 'node:fs';\n"
        "import os from 'node:os';\n"
        "import path from 'node:path';\n"
        "import vm from 'node:vm';\n"
        "import { stripTypeScriptTypes } from 'node:module';\n"
        "import { spawnSync } from 'node:child_process';\n"
        "const helper = fs.readFileSync(0, 'utf8');\n"
        "const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'allowed-hosts-'));\n"
        "const file = path.join(dir, 'helper.ts');\n"
        "fs.writeFileSync(file, helper + \"\\nprocess.stdout.write(JSON.stringify("
        "resolveDevAllowedHosts(process.env.PROBE_VALUE)));\\n\");\n"
        "const result = spawnSync(process.env.PROBE_NODE || process.execPath, [file], { encoding: 'utf8' });\n"
        "if (result.error) {\n"
        "  try {\n"
        "    const source = stripTypeScriptTypes(helper + `\\nJSON.stringify(resolveDevAllowedHosts(process.env.PROBE_VALUE))`, { mode: 'strip' });\n"
        "    const output = vm.runInThisContext(source);\n"
        "    if (typeof output !== 'string' || output.length === 0) throw new Error('inline helper produced no JSON output');\n"
        "    process.stdout.write(output);\n"
        "    process.exit(0);\n"
        "  } catch (error) {\n"
        "    process.stderr.write(`spawnSync failed and inline evaluation failed: ${error.message}\\n`); process.exit(1);\n"
        "  }\n"
        "}\n"
        "if (result.status !== 0) { process.stderr.write(result.stderr ?? `child exited with status ${result.status}\\n`); process.exit(1); }\n"
        "if (typeof result.stdout !== 'string' || result.stdout.length === 0) { process.stderr.write('child produced no JSON output\\n'); process.exit(1); }\n"
        "process.stdout.write(result.stdout);\n"
    )
    completed = subprocess.run(
        [node, "--input-type=module", "-e", program],
        input=body,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PROBE_VALUE": value or "",
            # Some development checkouts run Node from a mounted filesystem
            # where child exec is denied even though the parent is runnable.
            # Prefer a native system Node when present; CI images fall back to
            # the pinned interpreter that launched this helper.
            "PROBE_NODE": probe_node,
        },
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"could not evaluate resolveDevAllowedHosts:\n{completed.stderr}"
        )
    return _DevAllowlist(json.loads(completed.stdout))


def _cnb_config_files() -> tuple[Path, ...]:
    return (CNB_CONFIG, *sorted((ROOT / ".cnb").glob("*.yml"))) + tuple(
        ROOT / name for name in PIPELINE_FILES
    )


def _workflow_text(name: str) -> str:
    return (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


def _is_executable(script: str) -> bool:
    """Is this shared script executable?

    The filesystem mode is authoritative on a normal clone, but some workspace
    mounts (SMB/CIFS) force every file to the same mode and refuse `chmod`. In
    that case git still records the real mode, so a script committed as 100755
    is executable for everyone who checks the repo out — which is what CI does.
    Fall back to the index bit rather than failing a gate that the mount broke.
    """
    path = ROOT / script
    if path.stat().st_mode & 0o111:
        return True
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--stage", "--", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    fields = completed.stdout.split()
    return len(fields) >= 2 and fields[0] == "100755"


_DOC_SECTION_CITATION = re.compile(r'\((docs/[\w./-]+\.md),\s*"([^"]+)"\)', re.DOTALL)
_COMMENT_WRAP = re.compile(r"\n[ \t]*#[ \t]*")


def _fold_comment_wrap(match: re.Match[str]) -> str:
    """Replacement for one wrapped comment continuation (``\n# ``).

    ASCII prose needs a space when a line break stands in for one
    (``"build once,\n# consume"`` -> ``"build once, consume"``). CJK headings
    carry no inter-word spaces, so a wrap there must vanish instead
    (``"构建一次，\n# 消费一次"`` -> ``"构建一次，消费一次"``). Wide/fullwidth
    characters mark the latter case; everything else keeps the space.
    """
    prev = match.string[match.start() - 1]
    return "" if unicodedata.east_asian_width(prev) in ("W", "F") else " "


def _doc_section_citations(text: str) -> list[tuple[str, str]]:
    """Return every ``(docs/*.md, "label")`` citation, wrapped lines included.

    Shared scripts wrap long shell comments mid-citation. Fold the continuation
    prefixes first, then whitespace-normalize the label. Kept as a helper so
    the gate and its regression tests exercise the same parsing, not a copy.
    """
    folded = _COMMENT_WRAP.sub(_fold_comment_wrap, text)
    return [
        (doc, " ".join(label.split()))
        for doc, label in _DOC_SECTION_CITATION.findall(folded)
    ]


class DeliveryArchitectureTests(unittest.TestCase):
    """The CNB pipeline is authoritative and the GitHub workflows mirror it."""

    def test_image_verifier_runs_copy_guard_before_building(self) -> None:
        script = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")
        guard = "bash scripts/check-dockerfile-copy.sh"
        self.assertIn(guard, script)
        self.assertLess(script.index(guard), script.index('step "Build release images'))

    def test_cnb_pipeline_exists_and_declares_the_delivery_jobs(self) -> None:
        self.assertTrue(CNB_CONFIG.is_file(), "missing .cnb.yml")
        push = _pipeline_names("main", "push")
        self.assertLessEqual(
            {
                "verify",
                "clickhouse-migration",
                "mcp-e2e",
            },
            push,
        )
        # Release and publication run on main pushes, tags and manual buttons,
        # never on pull requests. They sit under `main` -> `push` (not `$`)
        # because their `cnb:await` has to pair with the image pipelines'
        # `cnb:resolve`, and await/resolve pair within one event only.
        self.assertLessEqual({"release", "publish"}, _pipeline_names("main", "push"))
        self.assertNotIn(
            "release",
            _pipeline_names("$", "push"),
            "a publisher under `$` starts on every branch push; only `main` "
            "pushes build the packages it consumes",
        )
        self.assertLessEqual(
            {
                "verify",
                "clickhouse-migration",
                "mcp-e2e",
                "docker-images (amd64)",
                "docker-images (arm64)",
            },
            _pipeline_names("main", "push"),
        )
        self.assertIn("verify", _pipeline_names("main", "pull_request"))
        self.assertLessEqual(
            {
                "docker-images (amd64)",
                "docker-images (arm64)",
                "release-tagged",
            },
            _pipeline_names("$", "tag_push"),
        )

    def test_every_cnb_pipeline_calls_the_shared_job_entrypoint(self) -> None:
        text = _cnb_text()
        self.assertIn("scripts/ci-job-steps.sh run frontend", text)
        self.assertIn("scripts/ci-job-steps.sh run api-tests", text)
        self.assertIn("scripts/ci-job-steps.sh run dependency-governance", text)
        self.assertIn("scripts/ci-job-steps.sh run image-build", text)
        self.assertIn("scripts/ci-job-steps.sh run release", text)

    def test_shared_script_catalog_cannot_shrink_without_a_failure(self) -> None:
        """The derived tuple must never silently lose a gate.

        `SHARED_SCRIPTS` drives ~a dozen assertions, each of which builds its
        expectation by walking that same tuple. Deleting an entry therefore
        deletes the assertion: on fb601eb3, dropping
        `scripts/check_bio_core_wheel.py` kept the suite at 92 OK. The floor is
        declared independently so a shrink has to be argued for in the diff.
        """
        self.assertEqual(
            sorted(set(REQUIRED_SHARED_SCRIPTS) & set(SHARED_SCRIPTS)),
            sorted(REQUIRED_SHARED_SCRIPTS),
            "SHARED_SCRIPTS lost entries the delivery contract still requires",
        )
        self.assertEqual(
            sorted(SHARED_SCRIPTS),
            sorted(set(SHARED_SCRIPTS)),
            "SHARED_SCRIPTS must not repeat an entry",
        )
        for script in REQUIRED_SHARED_SCRIPTS:
            self.assertTrue((ROOT / script).is_file(), f"missing shared script: {script}")

    def test_shared_script_catalog_ablation_is_detected(self) -> None:
        """Prove the floor bites: remove one required entry and assert failure.

        The ablation runs in a scratch copy of the module's own constants so it
        needs no filesystem mutation and cannot disturb the real suite.
        """
        survivors = tuple(
            script for script in SHARED_SCRIPTS
            if script != "scripts/check_bio_core_wheel.py"
        )
        self.assertNotIn("scripts/check_bio_core_wheel.py", survivors)
        lost = set(REQUIRED_SHARED_SCRIPTS) - set(survivors)
        self.assertEqual(
            lost,
            {"scripts/check_bio_core_wheel.py"},
            "the floor must name the ablated script, or the guard is toothless",
        )

    def test_cnb_job_catalog_matches_the_scripts_on_disk(self) -> None:
        for script in SHARED_SCRIPTS:
            self.assertTrue((ROOT / script).is_file(), f"missing shared script: {script}")

        catalog = subprocess.run(
            ["bash", "scripts/ci-job-steps.sh", "list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        jobs = set(catalog.stdout.split())
        self.assertLessEqual(
            {
                "frontend",
                "bio-core",
                "api-tests",
                "dependency-governance",
                "compose-acceptance",
                "clickhouse-migration",
                "mcp-e2e",
                "image-build",
                "release",
            },
            jobs,
        )

    def test_shared_script_catalog_does_not_silently_shrink(self) -> None:
        """Deleting a SHARED_SCRIPTS entry must fail, not stay green.

        Every loop over SHARED_SCRIPTS proves a property of the scripts that
        ARE listed (is_file, executable, strict mode, no credential echo).
        None prove the reverse -- that a script the delivery pipeline calls is
        still listed. Deleting one entry makes every loop skip that script and
        the whole suite stays green: on dfa5915b, removing the
        ``with-postgres-service.sh`` line leaves 88 tests OK and
        ``check_bio_core_wheel.py --static`` green, because both gates then
        scan one fewer shared script. PR #124's two smoke.sh assertions pin
        the *call sites*, not this registration half (its commit message says
        "mutation-tested each half"; the registration half was not tested).

        This is the reverse half, following the shape of
        ``test_worker_science_build_deps_are_provisioned_before_the_worker_install``:
        a typed floor the catalog must still cover. Subset, not equality --
        adding a new shared script is allowed, but it must not displace an
        existing one silently. The plant below proves the assertion is
        load-bearing for the real tuple shape, not a vacuous pass.
        """
        expected = frozenset({
            "scripts/ci-job-steps.sh",
            "scripts/setup-workspace.sh",
            "scripts/install_python_workspace.py",
            "scripts/stage-pages-publication.sh",
            "scripts/verify-frontend-artifacts.sh",
            "scripts/verify-backend-tests.sh",
            "scripts/verify-bio-core.sh",
            "scripts/check_bio_core_wheel.py",
            "scripts/install-worker-science-build-deps.sh",
            "scripts/with-postgres-service.sh",
            "scripts/build-static-apps.sh",
            "scripts/build-all-static-apps.sh",
            "scripts/ci-nightly-artifact-gate.sh",
            "scripts/build-release-image.sh",
            "scripts/release-contract.golden.sh",
            "scripts/build-pages-artifact.sh",
            "scripts/verify-pages-artifact.sh",
            "scripts/verify-site-variant-artifacts.sh",
            "scripts/verify-artifact-e2e.sh",
            "scripts/mcp-transport-smoke.sh",
            "scripts/assert-clickhouse-migration.py",
            "scripts/smoke.sh",
            "scripts/start-cloud-dev.sh",
            "scripts/acceptance.sh",
        })
        missing = sorted(expected - set(SHARED_SCRIPTS))
        self.assertEqual(
            missing, [],
            "these shared scripts dropped out of SHARED_SCRIPTS, so the "
            "is_file/executable/strict loops silently stopped checking them",
        )
        self.assertEqual(
            len(SHARED_SCRIPTS), len(set(SHARED_SCRIPTS)),
            "SHARED_SCRIPTS contains duplicate entries",
        )

        # Load-bearing: planting a deletion in the committed tuple must remove
        # the entry from the parsed catalog. Scope to the tuple block -- the
        # same 4-space string also appears in 12-space assertIn lines
        # elsewhere in this file, and a bare sed-style plant there fakes a red.
        source = (ROOT / "scripts" / "test_ci_job_contracts.py").read_text(
            encoding="utf-8"
        )
        match = re.search(r"SHARED_SCRIPTS\s*=\s*\((.*?)\n\)", source, re.DOTALL)
        self.assertIsNotNone(match, "SHARED_SCRIPTS tuple must be parseable")
        assert match is not None
        line_re = re.compile(
            r'^    "scripts/with-postgres-service\.sh",\n?', re.MULTILINE
        )
        self.assertEqual(len(line_re.findall(match.group(1))), 1)
        mutated = (
            source[: match.start(1)]
            + line_re.sub("", match.group(1), count=1)
            + source[match.end(1) :]
        )
        parsed = re.search(r"SHARED_SCRIPTS\s*=\s*\((.*?)\n\)", mutated, re.DOTALL)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertNotIn(
            "scripts/with-postgres-service.sh",
            re.findall(r'"([^"]+)"', parsed.group(1)),
            "the plant must actually drop the entry from the parsed catalog",
        )

    def test_bio_core_gate_is_delegated_by_both_providers(self) -> None:
        """The Rust kernel gate must be one shared job body, not two YAML copies."""
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn("bio_core_run()", steps)
        self.assertIn("scripts/verify-bio-core.sh", steps)
        self.assertIn("run bio-core", _workflow_text("ci.yml"))
        self.assertIn("run bio-core", _flatten(_cnb()))
        # The wheel gate is real: it must build AND import, not just build.
        verify = (ROOT / "scripts/verify-bio-core.sh").read_text(encoding="utf-8")
        self.assertIn("maturin build", verify)
        self.assertIn("import soymutdb_bio_core", verify)
        self.assertIn("-m pytest", verify)
        # Regression for cnb-6e3-1k6jsptrg: the CNB system Python 3.15 has
        # no pytest, so the wheel gate must build its own throwaway venv.
        self.assertIn("-m venv", verify)
        self.assertIn("--locked", verify)
        # Both smoke layers must keep invoking the wheel checker. Without these
        # two assertions, deleting either call from smoke.sh stays green.
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("check_bio_core_wheel.py --static", smoke)
        self.assertIn("check_bio_core_wheel.py --runtime", smoke)
        # PR #135 landed scripts/test_bio_core_capability_parity_wiring.py but
        # no gate collected it, so removing the parity guard's two invocations
        # from verify-bio-core.sh stayed green. Pin the suite into the layer.
        self.assertIn("test_bio_core_capability_parity_wiring.py", smoke)
        # The crate pins its own compiler; no second Rust version in the YAML.
        pin = (ROOT / "packages/bio-core/rust-toolchain.toml").read_text(encoding="utf-8")
        self.assertIn("channel", pin)

    # The Rust bio-core job the spec (docs/dev/rust-core-development-spec-
    # 2026-11-05.md §13.1) requires. The two tests above are SUBSET assertions
    # (`assertLessEqual`), so they stay green no matter what a new job does --
    # including a job that is registered in `.cnb.yml` but never dispatched
    # through the shared entrypoint, or one that only one provider knows about.
    # This one is deliberately ordered the other way: the job must exist and
    # must be reachable from both providers through the same script.
    BIO_CORE_JOB = "bio-core"

    def test_bio_core_job_is_dispatched_through_the_shared_entrypoint(self) -> None:
        invocation = f"scripts/ci-job-steps.sh run {self.BIO_CORE_JOB}"

        # CNB is authoritative, and the GitHub workflows are its mirror: both
        # must dispatch the job by name through ci-job-steps.sh, or the two
        # providers stop executing the same bytes.
        for provider, text in (
            (".cnb.yml", _cnb_text()),
            (".github/workflows/ci.yml", _workflow_text("ci.yml")),
        ):
            self.assertIn(invocation, text, f"{provider} does not dispatch {self.BIO_CORE_JOB}")

        # Dispatch is not registration. `run <job>` forwards to `<job>_run`, so a
        # pipeline calling an unregistered name fails at runtime with a shell
        # error instead of a review-time failure here.
        catalog = subprocess.run(
            ["bash", "scripts/ci-job-steps.sh", "list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn(
            self.BIO_CORE_JOB,
            catalog.stdout.split(),
            f"{self.BIO_CORE_JOB} is not in the `ci-job-steps.sh list` catalog",
        )

    def test_bio_core_job_body_does_not_hide_in_a_provider_config(self) -> None:
        """§13.1: no standalone rust.yml, and no cargo/maturin in a wrapper.

        The shared job body owns the toolchain commands; the provider configs
        only sequence jobs. If `cargo`/`maturin` appears in `.cnb.yml` or in the
        GitHub mirror, the same gate runs from two places and drifts.
        """
        for provider, text in (
            (".cnb.yml", _cnb_text()),
            (".github/workflows/ci.yml", _workflow_text("ci.yml")),
        ):
            for command in ("cargo ", "maturin "):
                self.assertNotIn(
                    command,
                    text,
                    f"{provider} inlines `{command}`; it belongs in the shared job body",
                )

        # The spec explicitly forbids a second, provider-specific Rust pipeline.
        rust_pipelines = sorted(
            path.name
            for path in (ROOT / ".cnb" / "pipelines").glob("*rust*.yml")
        )
        self.assertEqual(
            rust_pipelines,
            [],
            "the Rust gate extends .cnb.yml + ci-job-steps.sh; a separate "
            "pipeline is what §13.1 forbids",
        )
    def test_bio_core_wheel_is_built_once_and_only_consumed_by_the_backend_gate(self) -> None:
        """The backend gate installs the wheel; it never builds one.

        Regression for a real review finding on PR #105: the api-tests CNB
        stage is a bare `python:3.15` (no curl / cargo / C linker), so a
        `maturin build` inside scripts/verify-backend-tests.sh dies on the first
        CI run for a reason unrelated to the change, and an uncached native
        build (bio / noodles / rust-lapper / bio-seq, thin LTO) would add
        minutes to every PR push. The wheel must be built ONCE by the bio-core
        job and only CONSUMED by the backend gate (spec §13.5: install, do not
        merely build). A missing wheel must still fail closed, never skip.
        """
        producer = (ROOT / "scripts/verify-bio-core.sh").read_text(encoding="utf-8")
        backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")

        # The producer owns the only maturin build and writes the wheel to the
        # directory both gates agree on.
        self.assertIn("maturin build", producer)
        self.assertIn("artifacts/wheels", producer)
        self.assertIn("SOYMUTDB_BIO_CORE_WHEEL_DIR", producer)

        # The backend gate must NOT bootstrap a Rust toolchain or build the
        # crate: that is the whole point of crossing the job boundary.
        for forbidden in (
            "sh.rustup.rs",
            "maturin build",
            "pip install --quiet \"maturin",
            "RUSTUP_HOME",
            "CARGO_HOME",
            "command -v cc",
            "command -v cargo",
        ):
            self.assertNotIn(forbidden, backend, forbidden)

        # It still installs the exact artifact, imports it, and runs the wheel
        # contract pytest — §13.5 is preserved, not weakened.
        self.assertIn("--force-reinstall --no-deps", backend)
        self.assertIn("import soymutdb_bio_core as c", backend)
        self.assertIn("packages/bio-core/python_tests", backend)
        self.assertIn("soymutdb_bio_core-*-cp315-*.whl", backend)

        # Fail-closed: absent / ambiguous wheel is a hard exit, not a skip.
        self.assertIn("expected exactly one cp315 bio-core wheel", backend)
        self.assertIn("#BIO_CORE_WHEELS[@]} -ne 1", backend)
        for skip in ("pytest.skip", "SKIPPED", "exit 0 #"):
            self.assertNotIn(skip, backend, skip)

    def test_doc_section_citations_resolve_to_real_headings(self) -> None:
        """A quoted doc section must name a heading that actually exists.

        Regression for two consecutive review findings on PR #116: a comment in
        scripts/ci-job-steps.sh cited docs/build/script-vs-plugin.md#file-sharing
        (a file that never existed), then cited an English translation of a
        Chinese heading ("CI: build once, consume once") that no text search or
        HTML anchor could resolve. Neither was caught because no gate validates
        prose citations. This guard covers the general form: any (path, "label")
        citation in a shared script must match a real file and a real heading.
        Wrapped comment lines are folded first, so reformatting the citation
        across lines cannot silently remove it from the checked set.
        """
        citations = [
            (script, doc, label)
            for script in SHARED_SCRIPTS
            for doc, label in _doc_section_citations(
                (ROOT / script).read_text(encoding="utf-8")
            )
        ]

        self.assertTrue(citations, "no doc-section citations found to validate")
        for script, path, label in citations:
            doc = ROOT / path
            self.assertTrue(doc.is_file(), f"{script}: cited missing doc {path}")
            headings = [
                line.lstrip("#").strip()
                for line in doc.read_text(encoding="utf-8").splitlines()
                if line.startswith("#")
            ]
            self.assertIn(
                label,
                headings,
                f"{script}: cites {path} section {label!r}, which is not a heading "
                f"(headings: {headings})",
            )

    def test_doc_section_citation_wrap_tolerance(self) -> None:
        """Wrapping a real citation across comment lines must not dissolve the gate.

        The heading is Chinese and has now been re-quoted twice; a plain rewrap
        of that comment line is the most likely next edit. Folding must keep a
        correct citation green and keep a dangling label red, so the signal
        never inverts. CJK text has no inter-word spaces, hence the no-space
        join in _fold_comment_wrap.
        """
        script = "scripts/ci-job-steps.sh"
        original = (ROOT / script).read_text(encoding="utf-8")
        doc = "docs/ops/bio-core-wheel.md"
        good = "CI：构建一次，消费一次"
        headings = [
            line.lstrip("#").strip()
            for line in (ROOT / doc).read_text(encoding="utf-8").splitlines()
            if line.startswith("#")
        ]
        self.assertIn(good, headings)

        # The committed tree itself must parse. Without this assertion the
        # regression is only self-contained in the neighbouring guard: a
        # mutation that drops the citation entirely would leave this test's
        # wrapped/dangling derivations silently empty.
        self.assertEqual(_doc_section_citations(original), [(doc, good)])

        wrapped = original.replace(f'"{good}"', '"CI：构建一次，\n# 消费一次"')
        self.assertNotEqual(wrapped, original)
        self.assertEqual(_doc_section_citations(wrapped), [(doc, good)])

        # A wrap right after the ASCII "CI" takes the space-keeping branch and
        # yields a spurious space in BOTH gates. Pin the shape so a future
        # "fix" to one fold cannot silently diverge from the other.
        after_ci = original.replace(f'"{good}"', '"CI\n# ：构建一次，消费一次"')
        self.assertEqual(
            _doc_section_citations(after_ci), [(doc, "CI ：构建一次，消费一次")]
        )

        dangling = original.replace(f'"{good}"', '"CI: build once,\n# consume once"')
        self.assertEqual(
            _doc_section_citations(dangling),
            [(doc, "CI: build once, consume once")],
        )
        self.assertNotIn("CI: build once, consume once", headings)

    def test_github_mirror_hands_the_wheel_from_bio_core_to_api_tests(self) -> None:
        """GitHub jobs do not share a filesystem: the wheel crosses as an artifact.

        CNB shares /workspace between stages of one pipeline; GitHub Actions
        needs an explicit upload/download pair plus a `needs` edge, otherwise
        the api-tests job would fail closed on a wheel nobody produced there.
        """
        workflow = _workflow_text("ci.yml")
        parsed = yaml.safe_load(workflow)
        jobs = parsed["jobs"]

        bio_core = jobs["bio-core"]
        api_tests = jobs["api-tests"]
        upload_steps = [
            step for step in bio_core["steps"]
            if "upload-artifact" in str(step.get("uses", ""))
        ]
        self.assertEqual(len(upload_steps), 1, "bio-core must upload exactly one wheel artifact")
        upload = upload_steps[0]
        self.assertEqual(upload["with"]["name"], "bio-core-wheel")
        self.assertIn("artifacts/wheels/soymutdb_bio_core-*-cp315-*.whl", upload["with"]["path"])
        self.assertEqual(upload["with"]["if-no-files-found"], "error")

        download_steps = [
            step for step in api_tests["steps"]
            if "download-artifact" in str(step.get("uses", ""))
        ]
        self.assertEqual(len(download_steps), 1, "api-tests must download the wheel artifact")
        download = download_steps[0]
        self.assertEqual(download["with"]["name"], "bio-core-wheel")
        self.assertEqual(download["with"]["path"], "artifacts/wheels")

        # Ordering is explicit, so a failed producer stops the consumer instead
        # of letting it fail on a stale or missing wheel.
        self.assertEqual(api_tests["needs"], "bio-core")

    def test_cnb_verify_pipelines_build_the_wheel_before_the_backend_gate(self) -> None:
        """CNB shares /workspace: the producer stage must precede the consumer.

        Every verify pipeline (PR / main push / manual) runs bio-core then
        api-tests as ordered stages. If the order flips or the bio-core stage is
        dropped, the backend gate fails closed on a wheel nobody produced. The
        backend stage stays on the bare python:3.15 image — that is precisely
        why it must not own a Rust toolchain.
        """
        for branch, event in (
            ("main", "pull_request"),
            ("main", "push"),
            ("$", "web_trigger_verify"),
        ):
            pipelines = [
                pipeline
                for pipeline in _cnb_pipelines(branch, event)
                if pipeline.get("name") == "verify"
                or (event == "web_trigger_verify" and pipeline.get("name") == "verify-manual")
            ]
            self.assertTrue(pipelines, f"missing verify pipeline for {branch}/{event}")
            for pipeline in pipelines:
                stages = pipeline.get("stages", [])
                names = [str(stage.get("name", "")) for stage in stages]
                self.assertIn("Rust bio-core", names, f"{branch}/{event}: no wheel producer")
                self.assertIn(
                    "API + Worker verification", names,
                    f"{branch}/{event}: no backend gate",
                )
                self.assertLess(
                    names.index("Rust bio-core"),
                    names.index("API + Worker verification"),
                    f"{branch}/{event}: bio-core must run before api-tests",
                )
                api_stage = stages[names.index("API + Worker verification")]
                self.assertEqual(
                    api_stage.get("image"), "python:3.15",
                    f"{branch}/{event}: api-tests must stay on the toolchain-free image",
                )

    def test_check_bio_core_wheel_static_parses_cargo_manifest(self) -> None:
        """The static gate must parse Cargo.toml, not grep literal strings.

        A string-match gate breaks on a reformat or a workspace-inherited
        `pyo3.workspace = true`; tomllib is the real parser and is stdlib on the
        pinned 3.15.
        """
        checker = (ROOT / "scripts/check_bio_core_wheel.py").read_text(encoding="utf-8")
        self.assertIn("import tomllib", checker)
        self.assertIn("tomllib.loads", checker)
        self.assertIn('cargo.get("dependencies", {})', checker)
        self.assertNotIn('"bio ="', checker)

    def test_bio_core_static_gate_rejects_dangling_doc_citations(self) -> None:
        """--static must check that every cited docs/ path exists.

        The section-heading guard above only matches `(path, "label")` pairs:
        a bare dangling path (the shape the squash regression actually had)
        yields zero citations, and a dangling path next to a valid labeled one
        is not checked at all. This is the narrower, stronger assertion: every
        docs/*.md path in ci-job-steps.sh must resolve, so a squash cannot
        silently drop a path fix again. The loop below now spans every
        shared script, not just the dispatcher.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_under_test",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertEqual(
            checker.doc_ref_errors(steps), [],
            "--static must pass on the committed tree",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/ops").mkdir(parents=True)
            (root / "docs/ops/bio-core-wheel.md").write_text(
                "# Wheel\n\n## CI：构建一次，消费一次\n", encoding="utf-8"
            )
            good = '# see docs/ops/bio-core-wheel.md, "CI：构建一次，消费一次"'
            self.assertEqual(checker.doc_ref_errors(good, root), [], good)
            # A wrap inside the quoted label must fold the same way in both
            # gates: CJK carries no inter-word space, so the join must vanish.
            wrapped = (
                '# see docs/ops/bio-core-wheel.md, "CI：构建一次，\n'
                '# 消费一次"'
            )
            self.assertEqual(checker.doc_ref_errors(wrapped, root), [], wrapped)
            # A bare dangling path, with no label at all.
            dangling = "# see docs/build/script-vs-plugin.md#file-sharing"
            self.assertTrue(
                checker.doc_ref_errors(dangling, root),
                "a docs/ path that is not committed must fail --static",
            )
            # ...and one hiding next to a perfectly valid labeled citation.
            alongside = (
                '# see docs/ops/bio-core-wheel.md, "CI：构建一次，消费一次" and '
                'docs/build/script-vs-plugin.md#file-sharing'
            )
            self.assertTrue(
                checker.doc_ref_errors(alongside, root),
                "a dangling path beside a valid citation must fail --static",
            )
            stale = '# see docs/ops/bio-core-wheel.md, section "renamed heading"'
            self.assertTrue(
                checker.doc_ref_errors(stale, root),
                "a section hint naming no heading must fail --static",
            )

    def test_doc_section_hint_is_checked_before_the_path_too(self) -> None:
        """A section named *before* the path must resolve, not pass silently.

        Regression for #141. SECTION_HINT only searched the 120 chars after a
        docs/ path, so `section "NOPE" in docs/ops/bio-core-wheel.md` parsed as
        zero citations and --static stayed green on a label naming no heading.
        DOC_REF has no leading anchor, so the path was always found; the miss
        was entirely on the hint side. Both orderings now share one checker.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_pre_path",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        good = "CI：构建一次，消费一次"
        doc = "bio-core-wheel.md"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / doc).write_text(
                f"# Wheel\n\n## {good}\n", encoding="utf-8"
            )
            shipped = [
                f'# see docs/ops/{doc}, "{good}"',
                f'# see docs/ops/{doc}, section "{good}"',
                f'# see section "{good}" in docs/ops/{doc}',
            ]
            for text in shipped:
                self.assertEqual(
                    checker.doc_ref_errors(text, root), [],
                    f"a real section must stay green in every form: {text}",
                )

            dangling = [
                f'# see section "NOPE" in docs/ops/{doc}',
                # Wrapped across comment lines, the shape the shipped citation
                # in ci-job-steps.sh already takes.
                f'# see section \n# "NOPE" in docs/ops/{doc}',
            ]
            for text in dangling:
                self.assertTrue(
                    checker.doc_ref_errors(text, root),
                    f"a pre-path label naming no heading must fail: {text}",
                )

            # A dangling path stays red on the pre-path form as well, so the
            # widened hint cannot mask the path check.
            self.assertTrue(
                checker.doc_ref_errors('# see section "X" in docs/ghost/gone.md', root),
                "a pre-path citation of a missing doc must fail",
            )
            # A quoted string with no comma or `section` in front of a path is
            # not a citation: widening must not turn any quote into a heading.
            self.assertEqual(
                checker.doc_ref_errors(f'# "{good}" is unrelated to docs/ops/{doc}', root),
                [],
                "an unrelated quoted string beside a path is not a section hint",
            )

    def test_section_hint_window_is_a_deliberate_boundary(self) -> None:
        """A label far from its path is out of scope — decided, not overlooked.

        #141 gap 3: SECTION_HINT only ever searched 120 chars either side of a
        docs/ path, so a quoted label beyond that returned zero hints. That
        bound is kept on purpose. There is no delimiter telling the gate that a
        distant quoted string belongs to the path, so searching the whole line
        turns `see docs/a.md ... , "anything"` into a heading claim. In-window
        labels stay checked in both word orders; beyond the window the label is
        prose, and the shipped citations are all well inside it.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_hint_window",
            ROOT / "scripts" / "check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        doc = "docs/ops/bio-core-wheel.md"
        window = checker.PRE_PATH_WINDOW
        self.assertEqual(window, 120, "the pinned window changed; re-decide the scope")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / "bio-core-wheel.md").write_text(
                "# Wheel\n\n## CI：构建一次，消费一次\n", encoding="utf-8"
            )
            # Inside the window: a dangling label must fail, in both orders.
            near = f'# see {doc}, "NOPE"'
            before = f'# see section "NOPE" in {doc}'
            for text in (near, before):
                self.assertTrue(
                    checker.doc_ref_errors(text, root),
                    f"a label inside the window must be checked: {text}",
                )
            # Just past the window, in both orders, the same label is prose.
            far = f'# see {doc} ' + "x" * (window + 1) + ', "NOPE"'
            far_before = '# see section "NOPE" ' + "x" * (window + 1) + f" {doc}"
            for text in (far, far_before):
                self.assertEqual(
                    checker.doc_ref_errors(text, root), [],
                    f"a label beyond the window is out of scope by decision: {text}",
                )
            # Widening the search would fabricate a citation from an unrelated
            # quoted string; the bound is what keeps that from happening.
            unrelated = f'# see {doc} ' + "x" * (window + 1) + ', "unrelated"'
            self.assertEqual(
                checker.doc_ref_errors(unrelated, root), [],
                "a distant unrelated quote must not become a section claim",
            )
            # The shipped citation is comfortably inside the bound, so this
            # decision does not relax a citation the committed tree relies on.
            shipped = f'# see {doc}, "CI：构建一次，消费一次"'
            self.assertEqual(checker.doc_ref_errors(shipped, root), [], shipped)

    def test_unquoted_section_heading_is_not_a_citation(self) -> None:
        """Unquoted headings stay out of scope — decided, not overlooked.

        #141 asked for a deliberate call. A citation is checked only when its
        label is quoted and sits beside a docs/ path behind a comma or the word
        `section`. An unquoted heading (`see the section 构建一次 消费一次 in
        docs/…`) has no delimiter telling the gate where the heading ends, so
        accepting it would mean guessing at prose extent and red-flagging any
        sentence that happens to contain a path. Out of scope: writers must
        quote the label, which the shipped citations already do.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_unquoted",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        good = "CI：构建一次，消费一次"
        doc = "bio-core-wheel.md"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / doc).write_text(
                f"# Wheel\n\n## {good}\n", encoding="utf-8"
            )
            for text in (
                f"# see the section {good} in docs/ops/{doc}",
                f"# see the section 完全不存在 的标题 in docs/ops/{doc}",
            ):
                self.assertEqual(
                    checker.doc_ref_errors(text, root), [],
                    f"unquoted heading is out of scope by decision: {text}",
                )
            # The quoted form of the same sentence IS checked, so the scope
            # boundary is the quotation, not the word order.
            self.assertTrue(
                checker.doc_ref_errors(f'# see the section "完全不存在 的标题" in docs/ops/{doc}', root),
                "quoting the label puts it back in scope",
            )

    def test_prose_mentions_of_a_doc_path_are_not_citations(self) -> None:
        """A path named inside a sentence must not be followed as a citation.

        Regression for the first CI run of #142: the gate scans every shared
        script, and it is one, so --static read its own docstrings -- where it
        says "every docs/ citation ... resolves". Those example paths were
        chased as links, and the Contract suites stage failed on a file the
        checker itself had invented. Line-leading paths and real citations stay
        checked; prose stays prose.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_prose",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / "bio-core-wheel.md").write_text(
                "# Wheel\n\n## CI：构建一次，消费一次\n", encoding="utf-8"
            )
            # Prose: the shape the checker's own docstrings take.
            for text in (
                "# --static reads every docs/ghost/gone.md path in a sentence",
                "# a dangling docs/ghost/gone.md citation must fail",
                "# cited in docs/ghost/gone.md only as an example path",
                '"""Fail when a docs/ghost/gone.md citation is dangling."""',
            ):
                self.assertEqual(
                    checker.doc_ref_errors(text, root), [],
                    f"prose is not a citation: {text}",
                )
            # Citations stay checked in every shape the gate documents.
            for text in (
                "# see docs/ghost/gone.md",
                '# see (docs/ghost/gone.md, "CI：构建一次，消费一次")',
                '# see docs/ops/bio-core-wheel.md, "renamed heading"',
                '# see section "renamed heading" in docs/ops/bio-core-wheel.md',
                "        # docs/ghost/gone.md",
            ):
                self.assertTrue(
                    checker.doc_ref_errors(text, root),
                    f"a citation must still be resolved: {text}",
                )

    def test_bio_core_static_gate_passes_on_its_own_source(self) -> None:
        """--static must be green on every shared script, this checker included.

        The checker is one of the files it reads, so its own docstrings are part
        of the input. Pinning the committed tree keeps a future explanatory
        example from failing the gate it explains.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_selfscan",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        for script in SHARED_SCRIPTS:
            self.assertEqual(
                checker.doc_ref_errors(
                    (ROOT / script).read_text(encoding="utf-8"), source=script
                ),
                [],
                f"--static must be green on {script}",
            )
        # The checker is not itself in SHARED_SCRIPTS, but --static reads its own
        # docstrings through check_static(), so prose there must stay prose.
        self.assertEqual(
            checker.doc_ref_errors(
                (ROOT / "scripts" / "check_bio_core_wheel.py").read_text(
                    encoding="utf-8"
                ),
                source="scripts/check_bio_core_wheel.py",
            ),
            [],
            "--static must be green on its own source",
        )

    def test_a_quoted_label_is_never_vetoed_by_prose_in_front_of_the_path(
        self,
    ) -> None:
        """A cited label is a citation whatever prose word precedes the path.

        `fb601eb3` added an `is_doc_citation()` prose-word veto to keep the
        checker's own docstrings green. Applied before the label is read, it
        also discards a genuine reference: `section "NOPE" in docs/…` stayed
        green while `see section "NOPE" in docs/…` was red, decided only by
        the comment's first word. A quoted label beside the path is decisive
        evidence and must bypass the prose veto; prose without a label stays
        out of scope.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_label_veto",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / "bio-core-wheel.md").write_text(
                "# Wheel\n\n## CI：构建一次，消费一次\n", encoding="utf-8"
            )
            doc = "docs/ops/bio-core-wheel.md"
            # Same bad label, two wordings: both must be red. On the unfixed
            # tree the bare pre-path form is the one that goes silently green.
            for text in (
                f'# see section "NOPE" in {doc}',
                f'# section "NOPE" in {doc}',
                f'# the file {doc}, "NOPE"',
                f'# a {doc}, "NOPE"',
            ):
                self.assertTrue(
                    checker.doc_ref_errors(text, root),
                    f"a quoted label must not be vetoed by prose: {text}",
                )
            # A dangling doc with a label must be red in the same shapes.
            for text in (
                '# section "NOPE" in docs/ops/gone.md',
                '# the file docs/ops/gone.md, "NOPE"',
            ):
                self.assertTrue(
                    checker.doc_ref_errors(text, root),
                    f"a labelled dangling path must fail: {text}",
                )
            # Prose without a label stays out of scope; the shipped citation
            # with a correct heading stays green.
            self.assertEqual(
                checker.doc_ref_errors(
                    "# --static reads every docs/ghost/gone.md path", root
                ),
                [],
                "prose without a label is still not a citation",
            )
            self.assertEqual(
                checker.doc_ref_errors(
                    f'# see ({doc}, "CI：构建一次，消费一次")', root
                ),
                [],
                "the shipped citation stays green",
            )
            # A quote ending a trailing prose clause is not attached to the
            # path. When the label veto is bypassed unconditionally, this prose
            # is promoted to a section claim — the regression that broke the
            # composition with the wider post-path window on PR #163.
            self.assertEqual(
                checker.doc_ref_errors(
                    f"# Resolve every {doc} reference before shipping, "
                    '"hello"',
                    root,
                ),
                [],
                "a quote at the end of a prose clause is not a section label",
            )

    def test_bio_core_static_gate_scans_every_shared_script(self) -> None:
        """--static must cover the same file set as the contract citation guard.

        Regression for a review finding on PR #120: doc_ref_errors() was called
        on scripts/ci-job-steps.sh only, while the contract gate scans all
        SHARED_SCRIPTS. A dangling citation planted in any of the other shared
        scripts made the contract gate red but left --static green. Both gates
        now read the same canonical list and must fail on the same plant.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_coverage",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        self.assertEqual(
            checker.shared_scripts(),
            list(SHARED_SCRIPTS),
            "--static and the contract gate must scan the same shared scripts",
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # A minimal but complete synthetic tree, so check_static() itself
            # (not just doc_ref_errors) runs its loop over every shared script.
            (root / "scripts").mkdir(parents=True)
            (root / "docs" / "ops").mkdir(parents=True)
            (root / "docs" / "ops" / "bio-core-wheel.md").write_text(
                "# Wheel\n\n## CI：构建一次，消费一次\n", encoding="utf-8"
            )
            (root / "packages" / "bio-core").mkdir(parents=True)
            for name in ("Cargo.toml", "Cargo.lock", "rust-toolchain.toml",
                         "pyproject.toml"):
                # rust-toolchain.toml pins under a [toolchain] table; a bare
                # `channel` key is the wrong TOML shape and --static (correctly)
                # rejects it, so the "clean" baseline stopped being clean.
                (root / "packages" / "bio-core" / name).write_text(
                    '[toolchain]\nchannel = "1.99.1"\n'
                    if name == "rust-toolchain.toml"
                    else "",
                    encoding="utf-8",
                )
            (root / "packages" / "bio-core" / "src").mkdir()
            (root / "packages" / "bio-core" / "src" / "lib.rs").write_text(
                "", encoding="utf-8"
            )
            (root / "packages" / "bio-core" / "Cargo.toml").write_text(
                "[dependencies]\n"
                'bio = "4"\nnoodles = "0"\nrust-lapper = "1"\n'
                'bio-seq = "0"\npyo3 = "0"\n', encoding="utf-8"
            )
            (root / "scripts" / "test_ci_job_contracts.py").write_text(
                (ROOT / "scripts" / "test_ci_job_contracts.py").read_text(
                    encoding="utf-8"
                ), encoding="utf-8"
            )
            for script in SHARED_SCRIPTS:
                target = root / script
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("", encoding="utf-8")
            # The dispatcher still needs its job markers to stay quiet.
            (root / "scripts" / "ci-job-steps.sh").write_text(
                "bio-core\nbio_core_run()\n", encoding="utf-8"
            )
            (root / "scripts" / "verify-bio-core.sh").write_text(
                "maturin build\nimport soymutdb_bio_core\n-m pytest\n--locked\n",
                encoding="utf-8",
            )
            (root / "scripts" / "verify-backend-tests.sh").write_text(
                "soymutdb_bio_core-*-cp315-*.whl\n"
                "--force-reinstall --no-deps\n"
                "import soymutdb_bio_core as c\n", encoding="utf-8",
            )

            checker.ROOT = root
            checker.CRATE = root / "packages" / "bio-core"

            # Baseline: no dangling citations anywhere -> --static green.
            self.assertEqual(checker.check_static(), 0, "synthetic tree must be clean")

            # Plant a dangling path in a NON-dispatcher shared script. The whole
            # point of the fix: --static must see it, not just the contract gate.
            planted = root / "scripts" / "verify-bio-core.sh"
            planted.write_text(
                planted.read_text(encoding="utf-8")
                + "# see docs/build/never-existed.md\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(
                    checker.check_static(), 1,
                    "a dangling path in a non-dispatcher script must fail --static",
                )

    def test_doc_citation_gates_agree_on_wrapped_citations(self) -> None:
        """The contract guard and --static must never give opposite signals.

        Both parse wrapped comments with their own copy of the fold. A correct
        rewrap must stay green in both, and a dangling label must stay red in
        both; otherwise a future edit to one parser silently reintroduces the
        inverted signal this guard was added to prevent.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bio_core_wheel_checker_consistency",
            ROOT / "scripts/check_bio_core_wheel.py",
        )
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)

        original = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        good = "CI：构建一次，消费一次"
        doc = "docs/ops/bio-core-wheel.md"
        wrapped = original.replace(f'"{good}"', '"CI：构建一次，\n# 消费一次"')
        dangling = original.replace(f'"{good}"', '"CI: build once,\n# consume once"')

        self.assertEqual(_doc_section_citations(wrapped), [(doc, good)])
        self.assertEqual(checker.doc_ref_errors(wrapped), [], "false positive in --static")
        self.assertEqual(
            _doc_section_citations(dangling),
            [(doc, "CI: build once, consume once")],
        )
        self.assertTrue(checker.doc_ref_errors(dangling), "dangling label must stay red")

    def test_github_workflows_delegate_instead_of_inlining_gates(self) -> None:
        ci = _workflow_text("ci.yml")
        for delegation in (
            "scripts/verify-frontend-artifacts.sh",
            "scripts/verify-backend-tests.sh",
            "scripts/ci-job-steps.sh run bio-core",
            "scripts/ci-job-steps.sh run dependency-governance",
            "scripts/ci-job-steps.sh run clickhouse-migration",
            "scripts/ci-job-steps.sh run mcp-e2e",
            "scripts/build-release-image.sh",
            "scripts/release-contract.golden.sh",
            "scripts/build-pages-artifact.sh",
            "scripts/verify-pages-artifact.sh",
            "scripts/verify-site-variant-artifacts.sh",
        ):
            self.assertIn(delegation, ci, delegation)

        # The inlined per-image build/smoke/scan sequence must be gone: it now
        # lives once, in the script both providers call.
        for inlined in (
            "docker build -f infra/docker/Dockerfile.api",
            "Trivy scan API image (hard gate)",
            "Generate API SPDX SBOM",
        ):
            self.assertNotIn(inlined, ci, inlined)

    def test_every_legacy_workflow_announces_the_authoritative_source(self) -> None:
        for workflow in LEGACY_WORKFLOWS:
            text = _workflow_text(Path(workflow).name)
            self.assertIn(".cnb.yml", text, workflow)

    def test_legacy_workflows_keep_a_working_dispatch_path(self) -> None:
        """The GitHub mirror must stay runnable until it is formally retired."""
        for workflow in LEGACY_WORKFLOWS:
            parsed = yaml.safe_load(_workflow_text(Path(workflow).name))
            self.assertTrue(parsed.get("jobs"), workflow)
            for job in parsed["jobs"].values():
                self.assertTrue(job.get("steps"), workflow)

    def test_pipeline_files_are_valid_yaml_and_consistent_with_the_root_config(self) -> None:
        for pipeline_file in PIPELINE_FILES:
            path = ROOT / pipeline_file
            self.assertTrue(path.is_file(), f"missing pipeline: {pipeline_file}")
            yaml.safe_load(path.read_text(encoding="utf-8"))

        self.assertTrue((ROOT / ".cnb/web_trigger.yml").is_file())
        triggers = yaml.safe_load((ROOT / ".cnb/web_trigger.yml").read_text(encoding="utf-8"))
        declared = {
            button["event"]
            for group in triggers["branch"]
            for button in group["buttons"]
        }
        self.assertLessEqual(
            {
                "web_trigger_verify",
                "web_trigger_acceptance",
                "web_trigger_workspace-preview",
                "web_trigger_docker-images",
                "web_trigger_release",
                "web_trigger_publish",
            },
            declared,
        )

    def test_archived_pipeline_files_do_not_drift_from_the_root_config(self) -> None:
        """`.cnb/pipelines/*.yml` must mirror `.cnb.yml`, not lag behind it.

        These files are advertised (and asserted above) as the reviewable record
        of what each job runs. Nothing compared their *content* to `.cnb.yml`,
        so they silently became historical:

          * `.cnb/pipelines/verify.yml` still declared a stage-level
            `services: [postgres:16]` after the root config moved `services` to
            the pipeline level, i.e. the exact shape whose silent no-op started
            the PostgreSQL outage this suite documents at length.
          * the same file carried none of the root pipeline's `push` stages
            (Pages artifact build/upload, verification-evidence upload).

        A mirror that disagrees with its source of truth is worse than no
        mirror: it is the document a reviewer reads to decide whether the
        pipeline is correct. Compare the parts that carry meaning -- declared
        services, the env the gate bodies read, and the delegated job commands --
        so the two cannot disagree on a question a reviewer would ask.
        """
        root_verify = None
        for pipeline in _cnb_pipelines("main", "push"):
            if pipeline.get("name") == "verify":
                root_verify = pipeline
        self.assertIsNotNone(root_verify, "missing main/push verify pipeline")

        archived = yaml.safe_load(
            (ROOT / ".cnb/pipelines/verify.yml").read_text(encoding="utf-8")
        )

        # 1. Services are a PIPELINE-level key; the archived file must place
        #    them exactly where the root config does.
        self.assertEqual(
            root_verify.get("services"),
            archived.get("services"),
            "archived verify pipeline declares different pipeline-level services",
        )
        for stage in archived.get("stages", []) or []:
            self.assertNotIn("services", stage, f"stage-level services: {stage}")

        # 2. The build environment the gate bodies actually read.
        for key in ("VITE_DEPLOYMENT_MODE", "VITE_API_BASE_URL", "VITE_JBROWSE_BASE_URL"):
            self.assertEqual(
                root_verify.get("env", {}).get(key),
                archived.get("env", {}).get(key),
                f"archived verify pipeline disagrees on {key}",
            )

        # 3. Every stage the root pipeline runs must appear in the mirror with
        #    the same delegated command (an artifact-upload stage has settings
        #    rather than a script, so compare `script` when present).
        def _stage_map(pipeline: dict) -> dict[str, str]:
            mapped: dict[str, str] = {}
            for stage in pipeline.get("stages", []) or []:
                if not isinstance(stage, dict) or "name" not in stage:
                    continue
                mapped[str(stage["name"])] = str(
                    stage.get("script") or _flatten(stage.get("settings") or {})
                )
            return mapped

        root_stages = _stage_map(root_verify)
        archived_stages = _stage_map(archived)
        self.assertEqual(
            set(root_stages),
            set(archived_stages),
            "the archived verify pipeline runs a different stage list than .cnb.yml",
        )
        for name, script in root_stages.items():
            self.assertEqual(
                script,
                archived_stages[name],
                f"archived verify pipeline stage {name!r} is stale",
            )

    def test_web_trigger_events_have_matching_pipelines(self) -> None:
        document = _cnb()
        fallback = document.get("$", {})
        for event in (
            "web_trigger_verify",
            "web_trigger_acceptance",
            "web_trigger_workspace-preview",
            "web_trigger_docker-images",
            "web_trigger_release",
            "web_trigger_publish",
        ):
            self.assertIn(event, fallback, event)

    def test_npc_events_resolve_a_role_declared_in_settings(self) -> None:
        """An NPC event needs a role; `.cnb/settings.yml` is where it lives.

        The `$` -> `issue.comment@npc` pipeline is this repository's NPC entry
        point, and the platform resolves the mentioned role *by name* against
        `npc.roles` before the container starts. With no roles declared, the
        `npc go` stage aborts with "No roles defined in .cnb/settings.yml" and
        the pipeline body in `.cnb.yml` never runs -- so the failure looks like
        a broken CI pipeline when in fact no CI job was involved. Two of them
        (no NPC pipeline at all, or a pipeline with no role list) are cheap to
        keep apart here.
        """
        fallback = _cnb().get("$", {})
        npc_events = [
            event
            for event in fallback
            if isinstance(event, str) and event.startswith("issue.comment@npc")
        ]
        if not npc_events:
            return

        settings = yaml.safe_load(
            (ROOT / ".cnb/settings.yml").read_text(encoding="utf-8")
        ) or {}
        roles = (settings.get("npc") or {}).get("roles") or []
        self.assertTrue(
            roles,
            ".cnb.yml declares an NPC pipeline but .cnb/settings.yml defines "
            "no npc.roles, so the platform stops at "
            "'No roles defined in .cnb/settings.yml'",
        )
        names = [role.get("name") for role in roles]
        for name in names:
            self.assertTrue(name, "every npc role needs a name")
        self.assertEqual(
            len(names),
            len(set(names)),
            f"npc role names must be unique, got {names}",
        )
        self.assertIn("CodeBuddy", names)

    def test_delivery_pipelines_are_named_and_off_pr_agents(self) -> None:
        """Every pipeline in the delivery chain carries a `name`, and no agent runs on PRs.

        Twice now a hand edit has dropped an `npc:go` block into `main` ->
        `pull_request`. The block arrives without a `name` key, so it does not
        sit *next to* `verify`; it replaces it: `main/pull_request` lost the
        verification gate and every `pipeline["name"]` consumer raised
        `KeyError: 'name'`. The same block also named a role the settings file
        never declared, which the platform rejects before any container starts
        (`Role "..." not found in .cnb/settings.yml`).

        Two independent invariants, both cheap to check:
          * pull_request is the verification gate -- no `npc:go` stage there;
          * a role named in `npc:go` is declared under `npc.roles`, since the
            platform resolves it by name before the job exists.
        """
        settings = yaml.safe_load(
            (ROOT / ".cnb/settings.yml").read_text(encoding="utf-8")
        ) or {}
        declared = {
            role.get("name") for role in (settings.get("npc") or {}).get("roles") or []
        }

        for branch, event in (
            ("main", "pull_request"),
            ("main", "push"),
            ("$", "pull_request"),
            ("$", "push"),
            ("$", "tag_push"),
            ("$", "web_trigger_verify"),
            ("$", "issue.comment@npc"),
            ("$", "pull_request.comment@npc"),
        ):
            for pipeline in _cnb_pipelines(branch, event):
                self.assertTrue(
                    pipeline.get("name"),
                    f"{branch}/{event}: a pipeline needs an explicit `name`; an "
                    "unnamed block does not sit beside the delivery chain, it "
                    "replaces it",
                )
                for stage in pipeline.get("stages", []):
                    if stage.get("type") != "npc:go":
                        continue
                    self.assertNotEqual(
                        (branch, event),
                        ("main", "pull_request"),
                        "pull_request is the verification gate; an agent session "
                        "there turns every push into an npc run instead of CI",
                    )
                    if str(event).endswith("@npc"):
                        # An `@` mention supplies the role: the platform injects
                        # it from the mentioned role and ignores `options`, so
                        # requiring `options.role` here would demand a value that
                        # can never take effect.
                        continue
                    role = (stage.get("options") or {}).get("role")
                    self.assertTrue(
                        role,
                        f"{branch}/{event}/{pipeline['name']}: npc:go needs a role",
                    )
                    self.assertIn(
                        role,
                        declared,
                        f"{branch}/{event}/{pipeline['name']}: role {role!r} is not "
                        f"declared in .cnb/settings.yml npc.roles (declared: "
                        f"{sorted(declared)}); the platform resolves the role by "
                        "name before the container starts",
                    )

    def test_npc_events_run_the_npc_task_instead_of_a_placeholder(self) -> None:
        """An `@` mention must reach `npc:go`, and both NPC events must be declared.

        The body used to be `script: echo "Handled by the .cnb.yml npc pipeline"`.
        That failure is the expensive kind: the pipeline goes green, the mention
        is acknowledged, and no agent ever reads the thread. Nothing downstream
        noticed, because a placeholder that exits 0 is indistinguishable from a
        task that succeeded.

        Declaring only `issue.comment@npc` is the second half: NPC config merges
        per event, so a missing `pull_request.comment@npc` silently falls back to
        the platform default and the two entry points drift apart.

        Prompt text is deliberately not asserted. For `@` mentions the platform
        injects the role prompt and ignores `options`, so a prompt asserted here
        would pin a value with no effect.
        """
        fallback = _cnb().get("$", {})
        events = ("issue.comment@npc", "pull_request.comment@npc")
        for event in events:
            self.assertTrue(
                fallback.get(event),
                f"{event} must be declared; NPC config merges per event, so a "
                "missing one falls back to the platform default",
            )
            for pipeline in _cnb_pipelines("$", event):
                bodies = [
                    stage.get("script") or stage.get("type") or ""
                    for stage in pipeline.get("stages", [])
                ]
                self.assertTrue(
                    any(
                        stage.get("type") == "npc:go"
                        for stage in pipeline.get("stages", [])
                    ),
                    f"$/{event}: stages {bodies} carry no `type: npc:go`, so the "
                    "mention is acknowledged and then nothing happens",
                )


    def test_bio_core_wheel_abi_ledger_is_enforced_by_the_contracts_layer(self) -> None:
        """The per-arch wheel tag guard must be wired, not merely committed.

        A guard that no gate calls is decoration: an arm64 image shipping an
        x86_64 wheel would still pass every existing check. Both the static
        ledger validator and the synthetic-negative suite have to be reachable
        from `smoke.sh --profile contracts`, and the Rust supply-chain scan has
        to run in the single bio-core job (one finding set, not two).
        """
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/check_bio_core_wheel_abi.py --ledger --self-test", smoke)
        self.assertIn("scripts/test_bio_core_wheel_abi.py", smoke)

        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn("verify-bio-core-supply-chain.sh", steps)
        scanner = (ROOT / "scripts/verify-bio-core-supply-chain.sh").read_text(encoding="utf-8")
        self.assertIn("cargo audit", scanner)
        self.assertIn("cargo deny", scanner)
        self.assertIn("cargo-supply-chain.json", scanner)
        # ci-job-steps.sh runs each script as a separate `bash` child, so the
        # wheel builder's exported toolchain PATH does not reach the scanner.
        # Both must resolve the same bootstrapped rustup storage; see the
        # byte-identical-default guard in check_bio_core_wheel_abi.py.
        self.assertIn('export PATH="${CARGO_HOME}/bin:${PATH}"', scanner)
        # rustup is bootstrapped with `--default-toolchain none`: cargo only
        # resolves a channel from CRATE_DIR's rust-toolchain.toml. A bare
        # `cargo install` at the repo root fails with "no default is configured"
        # (cnb-h85-1k6kahbov). Every cargo command must run inside CRATE_DIR.
        for line in scanner.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#") or "command -v cargo" in line:
                continue
            if any(stripped.startswith(f"cargo {cmd}") or f"&& cargo {cmd}" in line
                   for cmd in ("install", "audit", "deny")):
                self.assertIn('(cd "${CRATE_DIR}" && cargo ', line, line)

        # A scanner that cannot read the advisory database aborts before it
        # reports anything, so its version pin is part of the gate. 0.21.2 is
        # the measured CVSS 4.0 red gate (cnb-k4a-1k6kbhl3c, runner L4405 --
        # that run installed 0.21.2). 0.22.1 also died (cnb-7qb-1k6kbvp1e)
        # with its reason redirected out of the stage log. 0.22.2 is the
        # first runner log showing the audit scan completing clean.
        audit_pin = re.search(r"SOYMUTDB_BIO_CORE_CARGO_AUDIT:-(\d+(?:\.\d+)*)", scanner)
        self.assertIsNotNone(audit_pin, "cargo-audit version pin is gone")
        self.assertEqual(
            audit_pin.group(1),
            "0.22.2",
            "cargo-audit must stay pinned to the exact 0.22.2 resolution; "
            "a floor-only guard lets a later release drift the finding set",
        )

        # cargo-deny hits the same parse wall and needs the same floor:
        # 0.18.4 links rustsec 0.30.x -> cvss 2.1.0, so the run dies on the
        # first CVSS 4.0 advisory (cnb-qf2-1k6kc4hoo). 0.18.9 is the first
        # release whose published Cargo.lock carries rustsec 0.31.0 -> cvss
        # 2.2.0.
        deny_pin = re.search(r"SOYMUTDB_BIO_CORE_CARGO_DENY:-(\d+(?:\.\d+)*)", scanner)
        self.assertIsNotNone(deny_pin, "cargo-deny version pin is gone")
        self.assertEqual(
            deny_pin.group(1),
            "0.18.9",
            "cargo-deny must stay pinned to the exact 0.18.9 resolution; "
            "a floor-only guard lets a later release drift the finding set",
        )

        # The pin compares the committed DECLARATION. A bare
        # `--version "0.22.2"` is a caret requirement (^0.22.2), so cargo
        # could install 0.22.99 at run time. The "=" operator makes it an
        # exact requirement; the source guard in check_bio_core_wheel_abi.py
        # owns the general form, this is the second reader.
        self.assertIn('--version "=${AUDIT_VERSION}"', scanner)
        self.assertIn('--version "=${DENY_VERSION}"', scanner)

        # The loop above catches a command that was left at the repo root; this
        # pins the other escape hatch, an explicit channel pin, so a future
        # rewrite has to keep at least one of the two. The source guard in
        # check_bio_core_wheel_abi.py owns the general form.
        self.assertTrue(
            "export RUSTUP_TOOLCHAIN=" in scanner or 'cd "${CRATE_DIR}" && cargo ' in scanner,
            "the supply-chain scanner must resolve a rustup channel",
        )

        # cargo deny without a config falls back to an empty license allowlist
        # and rejects every crate. The policy is committed next to Cargo.lock
        # and auto-discovered because the scanner runs inside the crate dir.
        deny_cfg = ROOT / "packages" / "bio-core" / "deny.toml"
        self.assertTrue(deny_cfg.is_file(), "packages/bio-core/deny.toml is missing")
        text = deny_cfg.read_text(encoding="utf-8")
        self.assertIn("allow = [", text)
        # Lint levels are parsed VALUES, not byte substrings. A substring
        # survives in a comment while the real key flips to a fail-open level;
        # measured on 11c3971d, all seven such assertions passed GREEN on that
        # mutation. This mirrors check_bio_core_wheel_abi.source_failures().
        import tomllib
        from collections import defaultdict
        policy = tomllib.loads(text)
        sources = policy.get("sources", {})
        self.assertEqual(sources.get("unknown-registry"), "deny")
        self.assertEqual(sources.get("unknown-git"), "deny")
        # The three unfixable advisories are ignored by ID: a scope spelling is
        # a blanket (measured: "transitive" fails them anyway because their
        # direct dependent is `bio`; "workspace" hides every unmaintained crate
        # behind a direct dependency).
        advisories = policy.get("advisories", {})
        self.assertEqual(advisories.get("unmaintained"), "all")
        self.assertIn("RUSTSEC-2024-0436", text)
        self.assertEqual(advisories.get("yanked"), "deny")
        # Existing duplicates are named in `skip`; a new one must still fail.
        bans = policy.get("bans", {})
        self.assertEqual(bans.get("multiple-versions"), "deny")
        self.assertEqual(bans.get("wildcards"), "deny")
        exceptions = policy.get("licenses", {}).get("exceptions")
        bsl = [
            entry for entry in (exceptions if isinstance(exceptions, list) else [])
            if isinstance(entry, dict) and "BSL-1.0" in (entry.get("allow") or [])
        ]
        self.assertEqual(len(bsl), 1, "deny.toml must grant BSL-1.0 to one crate")
        self.assertEqual(bsl[0].get("crate"), "ryu@1.0.23")
        # The same substring class survives in four more keys that the seven
        # parsed levels above do not cover. Each one is a fail-open in the
        # direction that matters: an unused allow-list entry stops being
        # reported, a private workspace crate starts being skipped from the
        # license check, and a 0.0 confidence threshold accepts a license match
        # on any evidence at all. All four stayed GREEN before this block.
        licenses = policy.get("licenses", {})
        self.assertEqual(licenses.get("unused-allowed-license"), "warn")
        private = licenses.get("private", {})
        self.assertEqual(private.get("ignore"), False)
        self.assertEqual(licenses.get("confidence-threshold"), 0.8)
        # The one license outside the allow-list is granted to exactly one
        # crate; a wholesale swap to an allow-listed SPDX id is invisible to
        # the crate/allow pair check above if the pair itself is edited.
        self.assertEqual(
            sorted(
                entry.get("crate") for entry in (exceptions or [])
                if isinstance(entry, dict)
            ),
            ["ryu@1.0.23", "unicode-ident"],
        )
        self.assertEqual(
            sorted(
                tuple(entry.get("allow") or []) for entry in (exceptions or [])
                if isinstance(entry, dict)
            ),
            [("BSL-1.0",), ("Unicode-3.0",)],
        )
        self.assertIn("skip = [", text)
        # The skip list names exactly the duplicate versions in Cargo.lock;
        # a bare "skip = [" substring let one entry be deleted.
        lock = tomllib.loads((ROOT / "packages/bio-core/Cargo.lock").read_text(encoding="utf-8"))
        seen: dict[str, list[str]] = defaultdict(list)
        for pkg in lock["package"]:
            seen[pkg["name"]].append(pkg["version"])
        expected = {
            f"{name}@{version}"
            for name, versions in seen.items()
            if len(versions) > 1
            for version in versions
        }
        named = {entry["crate"] for entry in policy["bans"]["skip"]}
        self.assertEqual(named, expected, "deny.toml skip list drifted from Cargo.lock")

        # The verdict is exit-status based and lives in a real module. A
        # heredoc that read `found` as a count or matched "error" in stdout
        # was fail-open on three shapes and no gate could import it to check.
        verdict = ROOT / "scripts" / "check_bio_core_supply_chain.py"
        self.assertTrue(verdict.is_file(), "check_bio_core_supply_chain.py is missing")
        module = verdict.read_text(encoding="utf-8")
        for token in ("audit_rc", "deny_rc", "count", "audit_findings"):
            self.assertIn(token, module)
        self.assertNotIn('vulnerabilities.get("found"', scanner)
        self.assertNotIn('"error" in deny_text', scanner)
        self.assertIn("check_bio_core_supply_chain.py", scanner)
        for arg in ('"${AUDIT_RC}"', '"${DENY_RC}"'):
            self.assertIn(arg, scanner)
        # The signed report must name the binaries that ran, not a hardcoded
        # "pinned" placeholder. `=` is an install contract; only each tool's
        # own --version proves which release produced the clean verdict.
        for token in ("def read_observations(", "def validate_observations(",
                      "def parse_scanner_version(", "executed as"):
            self.assertIn(token, module, f"the verdict lost {token!r}")
        import ast  # local: this module uses ast in several disjoint checks
        verdict_ast = ast.parse(module)
        constants = {
            node.value for node in ast.walk(verdict_ast)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertNotIn("pinned", constants, "the verdict re-hardcoded a placeholder version")
        for probe in ("cargo audit --version", "cargo deny --version"):
            self.assertIn(probe, scanner, f"the scanner stopped observing {probe!r}")
        for arg in ("--audit-version-file", "--deny-version-file",
                    "--expect-audit", "--expect-deny"):
            self.assertIn(arg, scanner, f"the scanner stopped passing {arg!r} to the verdict")
        self.assertIn(
            "scripts/test_bio_core_supply_chain.py",
            (ROOT / "scripts" / "smoke.sh").read_text(encoding="utf-8"),
        )

        # Exactly one Rust finding set: no second cargo-* analyzer in the
        # governance policy, which would produce a contradictory report.
        policy = (ROOT / "dependency-governance.json").read_text(encoding="utf-8")
        self.assertNotIn("cargo audit", policy)

    def test_contracts_job_provisions_every_import_it_needs(self) -> None:
        """The contracts stage must provision the layer's whole dependency set.

        `smoke-contracts` runs `scripts/smoke.sh --profile contracts` on a
        `python:3.15` stage, which ships neither a test runner nor PyYAML. The
        job has to provision both, and both were found the expensive way:
        CNB build `cnb-66s-1k4i8rfii` (2026-10-10) failed in 11s on missing
        pytest, and the fix then failed again on missing PyYAML -- because
        `compose_loader` is vendored under scripts/ and imports yaml, so a
        compose contract imports PyYAML while appearing to import only repo
        code.

        Two CI round trips to discover two requirements is the failure mode this
        replaces. The set is now derived from the layer's own import graph, so
        adding a contract that imports a new third-party package fails here
        rather than on the pipeline, where the symptom names an unrelated file.
        """
        import ast
        import sys

        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        # The gating suites of the contracts layer, read from smoke.sh rather
        # than restated here so the two cannot drift.
        function = smoke.split("smoke_contracts() {", 1)[1]
        block = function.split("environment_bound=(", 1)[0]
        targets = re.findall(r"^\s+((?:scripts|infra)/[A-Za-z0-9_./-]+\.py)\s*$",
                             block, flags=re.MULTILINE)
        assert targets, "failed to read the contracts layer suite list from smoke.sh"

        third_party = set()
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        for relative in targets:
            path = ROOT / relative
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import: repo code, not a package
                        continue
                    roots = [(node.module or "").split(".")[0]]
                else:
                    continue
                for root in roots:
                    if not root or root in stdlib:
                        continue
                    if (ROOT / "scripts" / f"{root}.py").exists():
                        continue  # vendored under scripts/
                    if (ROOT / root).is_dir() or (ROOT / "tools" / root).exists():
                        continue  # repo package
                    third_party.add(root)

        # Modules pytest itself needs are never our problem.
        third_party -= {"pytest"}

        self.assertTrue(third_party == {"yaml"}, f"unexpected contracts deps: {third_party}")

        shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        # Scope every assertion below to ensure_contracts_python. Searching the
        # whole file passes for the wrong reason: PyYAML is also installed by
        # ensure_governance_python, so dropping it from the contracts bootstrap
        # would leave the string present and the guard silent. That hole was
        # found by ablation, not by reading.
        body = shared.split("ensure_contracts_python() {", 1)[1].split("\n}\n", 1)[0]
        self.assertTrue(body, "ensure_contracts_python disappeared from ci-job-steps.sh")
        provisioners = {"yaml": "PyYAML==${GOVERNANCE_PYYAML_VERSION}"}
        for module in third_party:
            self.assertIn(
                provisioners[module], body,
                f"contracts layer imports {module} but ensure_contracts_python provisions no pin for it",
            )
        # And the test runner itself, pinned and post-verified.
        self.assertRegex(shared, r'CONTRACTS_PYTEST_VERSION="\$\{[^}]*:-[0-9]+\.[0-9]+\.[0-9]+\}"')
        self.assertIn('"pytest==${CONTRACTS_PYTEST_VERSION}"', body)
        self.assertIn("pytest is still not runnable by", body)
        self.assertIn("PyYAML is still not importable by", body)

    def test_contract_suites_stage_carries_both_pinned_interpreters(self) -> None:
        """The contracts stage must be able to run the contracts layer it hosts.

        The layer is not Python-only: `resolveDevAllowedHosts` is TypeScript,
        and one case shells out to node to run the frontend gate self-test. The
        stage was declared `image: python:3.15`, which has no node, so CNB
        build `cnb-t65-1k4ibj79d` (2026-10-10) reported
        "FileNotFoundError: No such file or directory: 'node'" — 264 contracts
        passed and two could not run.

        The pipeline image is the correct host: .cnb/env/Dockerfile.frontend is
        `FROM python:3.15` with Node 26.13.0 unpacked on top, so it is the only
        image in the pipeline carrying both pins.

        Two wrong-looking fixes are ruled out here rather than left to review:
        re-adding `python:3.15` fails the assertion, and so does swapping the
        `FROM` to `node:26.13.0` with a copied interpreter, which cannot start
        across the glibc 2.36 / 2.38 boundary.
        """
        cnb = yaml.safe_load((ROOT / ".cnb.yml").read_text(encoding="utf-8"))
        stage = next(
            st for st in cnb["main"]["pull_request"][0]["stages"]
            if st["name"] == "Contract suites"
        )
        self.assertNotIn(
            "image", stage,
            "the contracts stage must inherit the pipeline image, which carries "
            "both the pinned Python and the pinned Node",
        )

        dockerfile = (ROOT / ".cnb/env/Dockerfile.frontend").read_text(encoding="utf-8")
        base = re.search(r"(?m)^FROM\s+(\S+)", dockerfile)
        self.assertIsNotNone(base, "Dockerfile.frontend has no FROM")
        self.assertEqual(
            base.group(1), "python:3.15",
            "the pipeline image must be built FROM python:3.15 and carry Node on "
            "top; node:26.13.0 is glibc 2.36 and cannot host a copied 3.15 "
            "interpreter that needs 2.38",
        )
        self.assertIn("node --version", dockerfile)

        # The mirror must agree, or the two providers stop executing the same
        # stage on the same image.
        verify = yaml.safe_load((ROOT / ".cnb/pipelines/verify.yml").read_text(encoding="utf-8"))
        mirror = next(
            st for st in verify["stages"] if st["name"] == "Contract suites"
        )
        self.assertNotIn("image", mirror)

    def _load_governance_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dep_governance_under_test", ROOT / "scripts/dependency_governance.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _pnpm_audit_report(self, dg, tmp_path, *, advisories):
        path = tmp_path / "pnpm-audit.json"
        path.write_text(json.dumps({"advisories": advisories, "metadata": {}}))
        return path

    def _acceptance_fixture_payload(self, dg, *, today, **overrides):
        """Build a synthetic, fully signed acceptance record.

        The record is fixture data, never a repository acceptance: it names a
        package that does not exist and an advisory id that is never issued,
        so no assertion built on it can be satisfied by -- or leak into -- a
        real risk acceptance. Its expiry sits exactly on the ceiling, so the
        boundary is exercised as well as the interior.
        """
        from datetime import timedelta

        entry = {
            "advisory": "GHSA-1111-2222-3333",
            "package": "soymutdb-fixture-package",
            "vulnerable_range": "<=1.2.3",
            "title": "synthetic fixture advisory",
            "introduced_by": "soymutdb-fixture-package@1.0.0",
            "severity_reached": "high",
            "reachability": [
                "Fixture only: the package does not exist in this repository.",
            ],
            "rationale": (
                "Fixture only: this record exists so the acceptance policy can be "
                "exercised without depending on a live risk acceptance."
            ),
            "accepted_by": "fixture-approver",
            "accepted_on": today.isoformat(),
            "expires_on": (today + timedelta(days=dg.MAX_ACCEPTANCE_DAYS)).isoformat(),
            "review": "Fixture only.",
        }
        entry.update(overrides)
        return {"schema_version": 1, "acceptances": [entry]}

    def _write_acceptance_file(self, tmp_path, payload, name="advisory-acceptances.json"):
        path = Path(tmp_path) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_advisory_acceptance_is_narrow_expiring_and_signed(self) -> None:
        """A signed risk acceptance must behave like a record, not a suppression.

        The mechanism that acknowledges a finding is asserted here because the
        failure mode is a gate that silently stops failing -- the one outcome
        nobody would notice in review.

        The record under test is a fixture this test owns, written to a temp
        dir. It used to be the live security/advisory-acceptances.json, which
        tied the contract to that file being non-empty: retiring an acceptance
        (the correct response to a withdrawn advisory) turned this test red
        for a reason that had nothing to do with the policy. An empty
        acceptances list is a legal state; the live record's own legality --
        and the fact that an empty record grants nothing -- is asserted
        separately, in
        test_advisory_acceptance_record_is_legal_when_empty_and_grants_nothing.
        """
        from datetime import date, timedelta

        dg = self._load_governance_module()
        today = date(2026, 10, 10)

        def advisories(
            module="soymutdb-fixture-package",
            advisory="GHSA-1111-2222-3333",
            severity="high",
        ):
            return {
                "1": {
                    "module_name": module, "severity": severity,
                    "github_advisory_id": advisory,
                    "vulnerable_versions": "<=1.2.3", "patched_versions": None,
                }
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # The fixture is explicitly signed and expires within the ceiling.
            payload = self._acceptance_fixture_payload(dg, today=today)
            entry = payload["acceptances"][0]
            for field in ("accepted_by", "rationale", "reachability"):
                self.assertTrue(
                    str(entry.get(field, "")).strip(),
                    f"the fixture acceptance must be signed with {field}",
                )
            self.assertLessEqual(
                (date.fromisoformat(entry["expires_on"]) - today).days,
                dg.MAX_ACCEPTANCE_DAYS,
                "a fixture acceptance must expire within the ceiling it tests",
            )

            accept = self._write_acceptance_file(tmp_path, payload)
            entries = dg.load_advisory_acceptances(accept, today=today)
            self.assertEqual(len(entries), 1)
            for field in dg.ACCEPTANCE_REQUIRED_FIELDS:
                self.assertTrue(str(entries[0].get(field, "")).strip(), f"{field} is required")

            # A properly signed, unexpired acceptance accepts exactly its own
            # finding. Without this the checks below would only prove that the
            # mechanism refuses everything.
            passed, findings, accepted = dg.evaluate_advisory_report(
                self._pnpm_audit_report(dg, tmp_path, advisories=advisories()),
                entries,
            )
            self.assertTrue(
                passed,
                f"a signed acceptance must accept its own finding: {findings}",
            )
            self.assertEqual(len(accepted), 1)
            self.assertFalse(accepted[0]["expired"])
            self.assertEqual(accepted[0]["advisory"], "GHSA-1111-2222-3333")
            self.assertEqual(accepted[0]["package"], "soymutdb-fixture-package")

            # Narrow: a different advisory in the same package is still a failure.
            passed, findings, _ = dg.evaluate_advisory_report(
                self._pnpm_audit_report(
                    dg, tmp_path, advisories=advisories(advisory="GHSA-0000-0000-0000")
                ),
                entries,
            )
            self.assertFalse(passed, "an unlisted advisory must not be accepted")
            self.assertTrue(any("GHSA-0000-0000-0000" in f for f in findings))

            # Narrow: a different package under the same advisory likewise.
            passed, _, _ = dg.evaluate_advisory_report(
                self._pnpm_audit_report(
                    dg, tmp_path, advisories=advisories(module="some-other-package")
                ),
                entries,
            )
            self.assertFalse(passed, "an acceptance must not transfer to another package")

            # Severity downgrade: the finding stops being gated, so the
            # acceptance stops being load-bearing and must be reported stale.
            # Failing here is the point -- it forces the record to be deleted
            # instead of outliving the risk, and it is what stops an acceptance
            # from being quietly parked while a package gets worse again.
            passed, findings, _ = dg.evaluate_advisory_report(
                self._pnpm_audit_report(
                    dg, tmp_path, advisories=advisories(severity="moderate")
                ),
                entries,
            )
            self.assertFalse(passed)
            self.assertTrue(any("matches no reported finding" in f for f in findings))

        # Expiring: an expired entry fails rather than degrading to a warning.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = self._acceptance_fixture_payload(
                dg, today=today, expires_on="2026-09-01"
            )
            expired = self._write_acceptance_file(tmp_path, payload)
            entries = dg.load_advisory_acceptances(expired, today=today)
            passed, findings, accepted = dg.evaluate_advisory_report(
                self._pnpm_audit_report(dg, tmp_path, advisories=advisories()),
                entries,
            )
            self.assertFalse(passed, "an expired acceptance must fail the gate")
            self.assertTrue(any("expired" in f for f in findings))
            self.assertTrue(accepted and accepted[0]["expired"])

        # Bounded: no entry may be written further out than the maximum.
        with tempfile.TemporaryDirectory() as tmp:
            payload = self._acceptance_fixture_payload(
                dg,
                today=today,
                expires_on=(today + timedelta(days=dg.MAX_ACCEPTANCE_DAYS + 1)).isoformat(),
            )
            far = self._write_acceptance_file(Path(tmp), payload)
            with self.assertRaises(dg.AcceptancePolicyError):
                dg.load_advisory_acceptances(far, today=today)

        # Unsigned: a missing approver is a policy error, never a silent accept.
        for field in ("accepted_by", "rationale", "expires_on", "advisory", "package"):
            with self.subTest(missing=field):
                with tempfile.TemporaryDirectory() as tmp:
                    payload = self._acceptance_fixture_payload(dg, today=today)
                    payload["acceptances"][0].pop(field)
                    path = self._write_acceptance_file(Path(tmp), payload)
                    with self.assertRaises(dg.AcceptancePolicyError):
                        dg.load_advisory_acceptances(path, today=today)

        # Non-rotting: an entry matching nothing is stale and fails.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = self._acceptance_fixture_payload(
                dg, today=today, advisory="GHSA-3333-3333-3333"
            )
            path = self._write_acceptance_file(tmp_path, payload)
            passed, findings, _ = dg.evaluate_advisory_report(
                self._pnpm_audit_report(dg, tmp_path, advisories=advisories()),
                dg.load_advisory_acceptances(path, today=today),
            )
            self.assertFalse(passed, "a stale acceptance must fail")
            self.assertTrue(any("matches no reported finding" in f for f in findings))

    def test_advisory_acceptance_record_is_legal_when_empty_and_grants_nothing(self) -> None:
        """The live acceptance record is data; the policy is the code.

        security/advisory-acceptances.json is expected to be empty whenever no
        risk is currently accepted, so the contract may not require it to hold
        an entry. What it must hold is:

          * the file exists and is schema-valid -- schema_version 1 and a list
            of acceptances -- under the very loader the gate uses;
          * every entry it does carry is complete: approver, rationale,
            expiry and a reachability argument;
          * an empty list is a legal state, not a malformed one; and
          * an empty list grants nothing: a high finding with no matching
            acceptance still fails the gate, so retiring an acceptance can
            never be read as "everything is accepted now".
        """
        from datetime import date

        dg = self._load_governance_module()
        accept = ROOT / "security/advisory-acceptances.json"

        self.assertTrue(accept.is_file(), "the acceptance record must be committed")

        raw = json.loads(accept.read_text(encoding="utf-8"))
        self.assertEqual(raw.get("schema_version"), 1)
        self.assertIsInstance(raw.get("acceptances"), list)

        # Loaded with today's date, exactly as the gate loads it, so a record
        # the production gate would reject fails this contract too.
        entries = dg.load_advisory_acceptances(accept, today=date.today())
        for entry in entries:
            for field in dg.ACCEPTANCE_REQUIRED_FIELDS:
                self.assertTrue(
                    str(entry.get(field, "")).strip(),
                    f"{field} is required on every accepted advisory",
                )
            self.assertTrue(
                str(entry.get("reachability", "")).strip(),
                "an acceptance must state why the finding is not reachable",
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # An empty acceptances list is legal: it loads, and it is empty.
            empty = self._write_acceptance_file(
                tmp_path, {"schema_version": 1, "acceptances": []}, name="empty.json"
            )
            self.assertEqual(dg.load_advisory_acceptances(empty, today=date.today()), [])

            probe = {
                "1": {
                    "module_name": "soymutdb-acceptance-probe",
                    "severity": "high",
                    "github_advisory_id": "GHSA-probe-probe-probe",
                    "vulnerable_versions": "<=0.0.1",
                    "patched_versions": None,
                }
            }
            report = self._pnpm_audit_report(dg, tmp_path, advisories=probe)

            # An empty record grants nothing: the probe finding still fails.
            passed, findings, accepted = dg.evaluate_advisory_report(
                report, dg.load_advisory_acceptances(empty, today=date.today())
            )
            self.assertFalse(passed, "an empty acceptance record must not pass a high finding")
            self.assertEqual(accepted, [])
            self.assertTrue(
                any("GHSA-probe-probe-probe" in f for f in findings),
                f"an unaccepted finding must be reported, not dropped: {findings}",
            )

            # And neither does the live record, whatever it currently holds:
            # the probe matches no acceptance, so it can never be accepted.
            passed, findings, accepted = dg.evaluate_advisory_report(report, entries)
            self.assertFalse(passed, "the live acceptance record must not pass an unlisted finding")
            self.assertEqual(accepted, [], "no acceptance may match the probe")
            self.assertTrue(any("GHSA-probe-probe-probe" in f for f in findings))

    def test_accepted_advisories_stay_visible_in_gate_output(self) -> None:
        """An accepted finding is printed on pass, not only on failure."""
        dg = self._load_governance_module()
        row = {
            "name": "pnpm-audit",
            "status": "passed",
            "report": "pnpm-audit.json",
            "accepted": [
                {
                    "package": "braces",
                    "advisory": "GHSA-vfj7-8cjw-p6xm",
                    "expires_on": "2026-12-09",
                    "expired": False,
                    "accepted_by": "caoronglin",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            evidence = dg._audit_failure_evidence(row, Path(tmp))
            self.assertTrue(evidence, "a passing run must still report what it accepted")
            joined = " ".join(evidence)
            self.assertIn("GHSA-vfj7-8cjw-p6xm", joined)
            self.assertIn("2026-12-09", joined)
            self.assertIn("caoronglin", joined)

        # And the policy must actually point the check at the record.
        policy = json.loads((ROOT / "dependency-governance.json").read_text(encoding="utf-8"))
        audit = next(c for c in policy["checks"] if c["name"] == "pnpm-audit")
        self.assertEqual(audit.get("normalize"), "accepted-advisories")
        self.assertTrue((ROOT / audit["accept_file"]).is_file())

    def test_no_build_path_depends_on_corepack(self) -> None:
        """No image build, compose service or CI job may shell out to corepack.

        Node 25 removed corepack from the distribution. Raising the pin to
        26.13.0 therefore broke every path that did `corepack enable`: the CNB
        pipeline image failed at stage Prepare with
        `corepack: command not found` (build cnb-on5-1k4i8kkap, 2026-10-10) and
        no gate ran at all.

        Nothing caught it. Every local gate passed, because the dev machine had
        a leftover corepack 0.34.5 from an unrelated Node install, and the only
        signal was a pipeline that could not build its own image.

        pnpm must come from `npm install -g pnpm@<pinned>`, which is what the
        reviewed pin resolves to either way. scripts/setup-workspace.sh is the
        one exception: it keeps a corepack branch for older pinned images, and
        this test tolerates it because the call sits inside a
        `command -v corepack` guard that npm-installed pnpm cannot reach.
        """
        import re as _re

        targets = [
            ".cnb/env/Dockerfile.frontend",
            "apps/jbrowse/Dockerfile",
            "infra/docker/Dockerfile.web",
            "infra/docker/Dockerfile.admin",
            "docker-compose.dev.yml",
            "docker-compose.yml",
            ".github/workflows/ci.yml",
            ".github/workflows/baseline-validation.yml",
            ".github/workflows/e2e-smoke.yml",
        ]
        for relative in targets:
            path = ROOT / relative
            if not path.exists():
                continue
            # Strip comments so prose explaining the corepack removal, or the
            # build log that records it, does not trip the assertion.
            text = path.read_text(encoding="utf-8")
            code = _re.sub(r"^\s*#.*$", "", text, flags=_re.MULTILINE)
            for call in ("corepack enable", "corepack prepare", "corepack pnpm"):
                self.assertNotIn(call, code, f"{relative} still calls `{call}`")

        # The one sanctioned corepack path must actually be guarded, or this
        # exception becomes a silent dependency again.
        setup = (ROOT / "scripts/setup-workspace.sh").read_text(encoding="utf-8")
        self.assertIn("command -v corepack", setup)
        self.assertIn('npm install --global --no-fund --no-audit "pnpm@${PNPM_VERSION}"', setup)

    def test_contract_suites_run_in_both_pipelines(self) -> None:
        """`smoke.sh --profile contracts` must execute in CI on both providers.

        scripts/test_ci_job_contracts.py — which asserts that every shared script
        is executable and strict — runs only under that profile. Until the
        smoke-contracts job existed, no pipeline invoked it, so the suite could
        not fail a build and commits 00429d35e / 62d0dd3e3 shipped shared
        scripts with a cleared exec bit.

        Each provider must delegate through scripts/ci-job-steps.sh rather than
        call the profile directly, so both run identical bytes.
        """
        jobs = subprocess.run(
            ["bash", str(ROOT / "scripts/ci-job-steps.sh"), "list"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        self.assertIn("smoke-contracts", jobs)

        call = "bash scripts/ci-job-steps.sh run smoke-contracts"
        self.assertIn(call, _workflow_text("ci.yml"))
        self.assertIn(call, _flatten(_cnb()))

        # The job body must stay a delegation. Inline pytest invocation would be
        # a second owner for the same gate, which is what
        # test_no_duplicate_verification_logic_between_providers forbids. Only
        # `run:` lines count; a comment may still explain what the profile is.
        run_lines = [
            line
            for line in _workflow_text("ci.yml").splitlines()
            if re.match(r"\s*run:", line)
        ]
        self.assertFalse(
            [line for line in run_lines if "smoke.sh --profile contracts" in line],
            "the contracts profile must be reached through ci-job-steps.sh, "
            "not invoked directly in the workflow",
        )

    def test_toolchain_pins_agree_across_pipelines_and_manifests(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(package["packageManager"], f"pnpm@{PNPM_VERSION}")
        self.assertEqual((ROOT / ".nvmrc").read_text(encoding="utf-8").strip(), NODE_VERSION)
        self.assertEqual(
            (ROOT / ".node-version").read_text(encoding="utf-8").strip(), NODE_VERSION
        )

        cnb = _cnb_text()
        self.assertIn(f"node:{NODE_VERSION}", cnb)
        self.assertIn(f"python:{PYTHON_VERSION}", cnb)
        for stale in ("node:20", "node:22", "node:24", "pnpm@10", "python:3.12"):
            self.assertNotIn(stale, cnb, stale)

        # The pnpm version is no longer inlined into every CNB stage: the
        # workspace bootstrap lives in scripts/setup-workspace.sh, which reads
        # the same pin. Assert it wherever it actually lives, and assert that
        # .cnb.yml cannot silently pick a different one.
        for provider_config in (ROOT / "scripts/setup-workspace.sh",):
            text = provider_config.read_text(encoding="utf-8")
            self.assertIn(f'PNPM_VERSION="${{SOYMUTDB_CI_PNPM_VERSION:-{PNPM_VERSION}}}"', text)
        self.assertNotIn("corepack prepare pnpm@", cnb)

        shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn(f'NODE_VERSION="${{SOYMUTDB_CI_NODE_VERSION:-{NODE_VERSION}}}"', shared)
        self.assertIn(f'PNPM_VERSION="${{SOYMUTDB_CI_PNPM_VERSION:-{PNPM_VERSION}}}"', shared)
        self.assertIn(f'PYTHON_VERSION="${{SOYMUTDB_CI_PYTHON_VERSION:-{PYTHON_VERSION}}}"', shared)

    def test_pull_request_pipelines_never_hold_release_credentials(self) -> None:
        """PR builds get a restricted token, so no publish step may run there."""
        for branch, event in (("main", "pull_request"), ("$", "pull_request")):
            for pipeline in _cnb_pipelines(branch, event):
                text = _flatten(pipeline)
                for forbidden in ("docker login", "cosign", "docker push"):
                    self.assertNotIn(forbidden, text, f"{branch}/{event}: {forbidden}")

        # Credential-bearing pipelines must be main/tag-triggered only.
        for pipeline in _cnb_pipelines("$", "push"):
            if pipeline["name"] not in {"release", "publish"}:
                continue
            self.assertTrue(pipeline.get("stages"), pipeline["name"])

    def test_pull_request_pipelines_are_named_verification_only(self) -> None:
        """PR builds must stay verifiable and never resolve an undefined NPC role.

        A stray `npc:go` reviewer stage once became `main.pull_request[0]`. It
        carried no `name`, so the contract helpers that index `[0]` for the
        `verify` pipeline broke, and its `role: 代码审查员` resolved against a
        `.cnb/settings.yml` with no `npc.roles` — CI failed in Prepare with
        "No roles defined in .cnb/settings.yml" before any verification ran.
        """
        for branch, event in (("main", "pull_request"), ("$", "pull_request")):
            pipelines = _cnb_pipelines(branch, event)
            if branch == "main":
                self.assertTrue(pipelines, "main/pull_request must run verify")
            for index, pipeline in enumerate(pipelines):
                self.assertIn(
                    "name", pipeline,
                    f"{branch}/{event}[{index}]: every pipeline needs a name; "
                    "an unnamed pipeline displaces `verify` from index [0]",
                )
                for stage in pipeline.get("stages", []) or []:
                    self.assertNotEqual(
                        stage.get("type"), "npc:go",
                        f"{branch}/{event}/{pipeline['name']}: an `npc:go` "
                        "stage needs an `npc.roles` definition in "
                        ".cnb/settings.yml and runs AI before the verification "
                        "gate; PR builds are verification-only",
                    )

        # If an NPC stage is ever added deliberately, its `role` must resolve.
        settings = yaml.safe_load(
            (ROOT / ".cnb/settings.yml").read_text(encoding="utf-8")
        ) or {}
        defined_roles = {
            role.get("name")
            for role in (settings.get("npc") or {}).get("roles", []) or []
            if isinstance(role, dict)
        }
        for pipeline in _iter_pipelines(_cnb()):
            for stage in pipeline.get("stages", []) or []:
                if stage.get("type") != "npc:go":
                    continue
                role = (stage.get("options") or {}).get("role")
                if role is not None:
                    self.assertIn(
                        role, defined_roles,
                        f"npc:go role {role!r} is not defined in "
                        ".cnb/settings.yml npc.roles",
                    )

    def test_no_duplicate_verification_logic_between_providers(self) -> None:
        """Shared logic must be scripted once, not copy-pasted per provider.

        Each gate's identifying string must appear in exactly one executing
        place: either a shared script, or the provider config as a bare
        delegation call.
        """
        ci = _workflow_text("ci.yml")
        shared_scripts = "\n".join(
            (ROOT / script).read_text(encoding="utf-8")
            for script in SHARED_SCRIPTS
            if script.endswith((".sh",))
        )

        for marker in (
            "Smoke test Worker task registry (hard gate)",
            "Assert actual native image architecture (hard gate)",
            "Merge manifests, attest evidence, and write release manifest",
        ):
            self.assertIn(marker, shared_scripts, marker)
            self.assertNotIn(marker, ci, marker)

    def test_image_verification_and_publication_are_separate_pipelines(self) -> None:
        verify_names = {"docker-images (amd64)", "docker-images (arm64)"}
        publish_names = {"release"}
        for pipeline in (
            _cnb_pipelines("$", "push")
            + _cnb_pipelines("main", "push")
            + _cnb_pipelines("$", "tag_push")
            + _cnb_pipelines("$", "web_trigger_release")
        ):
            text = _flatten(pipeline)
            if pipeline["name"] in verify_names:
                self.assertNotIn("docker push", text)
                self.assertNotIn("cosign", text)
            if pipeline["name"] in publish_names:
                self.assertNotIn("docker build", text)

    def test_arch_specific_image_pipelines_use_native_runners(self) -> None:
        pipelines = {pipeline["name"]: pipeline for pipeline in _cnb_pipelines("main", "push")}
        amd64 = pipelines["docker-images (amd64)"]
        arm64 = pipelines["docker-images (arm64)"]

        self.assertEqual(amd64["env"]["SOYMUTDB_CI_ARCH"], "amd64")
        self.assertEqual(arm64["env"]["SOYMUTDB_CI_ARCH"], "arm64")
        # amd64 is the default runner; arm64 must select an arm64 node so the
        # exported image architecture is natively proven, never emulated.
        self.assertNotIn("tags", amd64.get("runner", {}))
        self.assertEqual(arm64["runner"]["tags"], "cnb:arch:arm64:v8")

    def test_image_pipelines_resolve_independent_architecture_keys(self) -> None:
        """Each native image pipeline hands off only after its own export."""
        for branch, event in (
            ("main", "push"),
            ("$", "tag_push"),
            ("$", "web_trigger_release"),
        ):
            pipelines = {
                pipeline["name"]: pipeline
                for pipeline in _cnb_pipelines(branch, event)
                if pipeline["name"] in {"docker-images (amd64)", "docker-images (arm64)"}
            }
            self.assertEqual(
                {"docker-images (amd64)", "docker-images (arm64)"},
                set(pipelines),
                f"{branch}/{event} must verify both native architectures",
            )
            for arch, pipeline in (("amd64", pipelines["docker-images (amd64)"]), ("arm64", pipelines["docker-images (arm64)"])):
                resolves = [
                    stage for stage in pipeline.get("stages", [])
                    if stage.get("type") == "cnb:resolve"
                ]
                self.assertEqual(1, len(resolves), f"{branch}/{event}/{arch}")
                self.assertEqual(
                    f"validated-runtime-images-{arch}", resolves[0]["options"]["key"]
                )
                self.assertIs(resolves[0], pipeline["stages"][-1])
                uploads = [
                    (index, stage)
                    for index, stage in enumerate(pipeline.get("stages", []))
                    if stage.get("image") == "cnbcool/artifact"
                ]
                self.assertEqual(1, len(uploads), f"{branch}/{event}/{arch} upload")
                self.assertLess(uploads[0][0], pipeline["stages"].index(resolves[0]))
                self.assertFalse(
                    any(
                        stage.get("type") == "cnb:resolve"
                        for stage in pipeline.get("endStages", []) or []
                    ),
                    f"{branch}/{event}/{arch} resolve cannot be in endStages",
                )
                self.assertEqual("$CNB_COMMIT", pipeline["env"]["SOURCE_REVISION"])
                self.assertEqual("$CNB_EVENT", pipeline["env"]["SOURCE_EVENT"])

    # -------------------------------------------------------------------------
    # Stage shell
    # -------------------------------------------------------------------------
    # Regression guard. A CNB stage body is executed with `sh`; shell options
    # and other bashisms can fail only when the body runs. The very first real
    # CNB build died during workspace setup for exactly that reason. Syntax
    # compilation and YAML parsing do not catch runtime shell incompatibility,
    # so the stage bodies are checked statically instead.

    def test_stage_scripts_never_rely_on_the_platform_shell(self) -> None:
        """Every CNB stage body must pin its interpreter to bash."""
        bashisms = (
            "set -o pipefail",
            "set -euo pipefail",
            "set -uo pipefail",
        )
        offenders = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for location, body in _iter_script_bodies(document):
                # A stage body is a single command line handed to `sh`. Either it
                # is a multiline block (whose first line decides the syntax that
                # `sh` must parse), or a one-liner that must itself start with an
                # explicit interpreter.
                first_line = body.strip().splitlines()[0].strip()
                if any(bashism in body for bashism in bashisms) and not first_line.startswith(
                    ("bash", "./")
                ):
                    offenders.append(f"{config.name}:{location}: {first_line[:80]}")
                # Multiline blocks are parsed by `sh` line by line, so any bashism
                # anywhere in an un-pinned block is fatal regardless of the first
                # line.
                if len(body.strip().splitlines()) > 1 and not first_line.startswith(
                    ("bash", "./")
                ):
                    for line in body.splitlines():
                        stripped = line.strip()
                        for pattern in (
                            "[[ ",
                            "]]",
                            "source ",
                            "set -o ",
                            "pipefail",
                        ):
                            if stripped.startswith(pattern) or pattern in stripped:
                                offenders.append(
                                    f"{config.name}:{location}: {stripped[:80]}"
                                )
                                break
        self.assertEqual(offenders, [], "stage bodies must pin bash:\n" + "\n".join(offenders))

    def test_sh_syntax_only_does_not_prove_runtime_success(self) -> None:
        """Keep the runtime-vs-syntax distinction without shell-specific text."""
        # `sh -n` validates grammar only. A portable command that fails when
        # executed demonstrates why syntax-only validation cannot replace the
        # static interpreter guard above, regardless of which `sh` is installed.
        body = "set -e\nfalse\n"

        syntax_only = subprocess.run(
            ["sh", "-n"], input=body, capture_output=True, text=True
        )
        self.assertEqual(
            syntax_only.returncode,
            0,
            "`sh -n` unexpectedly rejected a portable shell body",
        )

        executed = subprocess.run(["sh"], input=body, capture_output=True, text=True)
        self.assertNotEqual(executed.returncode, 0)

    def test_no_stage_depends_on_another_stages_container_state(self) -> None:
        """CNB gives every stage a fresh container.

        Regression guard for the second failure the first real build produced,
        after the `sh`/pipefail one was fixed:

            Setup workspace with cache   → success (52.5s)
            Frontend verification        → error, exit 127
              scripts/ci-job-steps.sh: line 89: pnpm: command not found

        `corepack enable` had run in the setup stage, but it writes a shim into
        that stage's container, which is destroyed when the stage exits. The
        checkout carries no node_modules either. So:
          * no stage may rely on a "setup" stage having prepared it;
          * every job body that needs the JS toolchain must bootstrap itself;
          * only declared `volumes` cross the container boundary.
        """
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        # The shared bootstrap must exist and be used by the jobs that need it.
        self.assertTrue((ROOT / "scripts/setup-workspace.sh").is_file())
        self.assertIn("ensure_workspace()", steps)
        self.assertIn("setup-workspace.sh", steps)

        # Extract every shell function body, then follow the call chain: a job
        # may delegate its bootstrap to a helper (frontend_run -> frontend_install).
        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)

        def reaches_bootstrap(name: str, seen: frozenset[str] = frozenset()) -> bool:
            if name in seen or name not in bodies:
                return False
            body = bodies[name]
            if "setup-workspace.sh" in body:
                return True
            for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M):
                if reaches_bootstrap(callee, seen | {name}):
                    return True
            return False

        # Every job that shells out to pnpm must reach the bootstrap, however the
        # call chain is structured.
        for job in ("frontend", "dependency-governance"):
            entry = f"{job.replace('-', '_')}_run"
            self.assertTrue(
                reaches_bootstrap(entry),
                f"{entry} calls pnpm but never reaches scripts/setup-workspace.sh; "
                "it would fail with `pnpm: command not found` in its own container",
            )

        # A stage named like a setup step must not masquerade as preparation for
        # later stages. If one comes back, it must at least be honest about it.
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))
        for branch, event in (
            ("main", "pull_request"),
            ("main", "push"),
            ("$", "web_trigger_verify"),
            ("main", "crontab: 0 2 * * *"),
        ):
            for pipeline in _cnb_pipelines(branch, event):
                stage_names = [stage.get("name", "") for stage in pipeline.get("stages", [])]
                for name in stage_names:
                    self.assertNotIn(
                        "Setup workspace",
                        name,
                        f"{branch}/{event}/{pipeline['name']}: {name!r} implies it "
                        "prepares later stages, which is impossible across containers",
                    )
                # Every stage that runs a pnpm-dependent job body must be able
                # to reach the store, or the install silently de-caches into a
                # dead layer. The store lives in the PIPELINE-level volumes
                # (`docker.volumes`); a stage-level `volumes:` key is not part of
                # the CNB schema, and an entry written as `host:container` is
                # read as an unknown volume TYPE. Either aborts the whole build
                # in Prepare, before any stage runs:
                #
                #   Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store
                #
                # So assert against `docker.volumes`, and separately assert that
                # no stage declares `volumes:` at all.
                pipeline_volumes = " ".join(
                    str(v) for v in (pipeline.get("docker", {}).get("volumes") or [])
                )
                for stage in pipeline.get("stages", []):
                    self.assertNotIn(
                        "volumes",
                        stage,
                        f"{branch}/{event}/{pipeline['name']}/{stage.get('name')}: "
                        "stage-level `volumes` is not a supported key and fails "
                        "Prepare with `Unsupported volume type`; declare it as "
                        "pipeline `docker.volumes`",
                    )
                    script = stage.get("script", "")
                    if "run frontend" in script or "run dependency-governance" in script:
                        self.assertIn(
                            "pnpm-store",
                            pipeline_volumes,
                            f"{branch}/{event}/{pipeline['name']}/{stage['name']}: "
                            "pnpm job without a persistent store volume",
                        )

    def test_i18n_handling_needs_no_per_render_double(self) -> None:
        """The translation layer is shared, and test doubles keep `t` stable.

        The failure this guards against is a `useTranslation` double that
        returns a *fresh* `t` every render. Any component that lists `t` in a
        `useCallback`/`useEffect` dependency array then gets a new callback each
        render and re-runs its effect: 224 renders for one click on a real CNB
        build, blamed on a page whose assertions had passed. A double that
        returns `{{name}}` verbatim is the second half of the same problem.

        Each frontend therefore either uses the real translator or a shared
        double that preserves i18next's semantics (stable identity +
        interpolation). An earlier version of this check forbade
        `src/test/mocks.ts` outright; the migration solved the problem by
        centralising a *correct* double there, so the assertion is on the
        double's properties rather than on its absence.
        """
        # The translation layer must reach the shared catalogs, or a locale
        # change would silently apply to only one frontend. `apps/web` consumes
        # the React adapter (`@soymutdb/i18n`), `apps/admin` the
        # framework-neutral core; both must resolve to `@soymutdb/i18n-core`,
        # which is asserted by following the adapter rather than by requiring one
        # particular import spelling.
        # Vue is retired, so the two frontends no longer share one per-app
        # `src/lib/i18n.ts`: web keeps a local adapter module, while admin
        # initialises the shared package from its React entry point. Name each
        # entry explicitly rather than assuming a path that no longer exists.
        i18n_entries = {
            "web": ROOT / "apps/web/src/lib/i18n.ts",
            "admin": ROOT / "apps/admin/src/react-app.tsx",
        }
        for app, entry in i18n_entries.items():
            self.assertTrue(entry.exists(), f"{app}: missing i18n entry point {entry}")
            i18n = entry.read_text(encoding="utf-8")
            self.assertTrue(
                "@soymutdb/i18n" in i18n,
                f"{entry.relative_to(ROOT)} must use the shared i18n package",
            )

            # If a shared double exists it must be the stable kind.
            mocks = ROOT / f"apps/{app}/src/test/mocks.ts"
            if mocks.exists():
                source = mocks.read_text(encoding="utf-8")
                self.assertIn(
                    "stableT",
                    source,
                    f"{app}/src/test/mocks.ts must export the stable `t` stand-in",
                )
                # It must document the identity/interpolation requirements, so a
                # future "simplification" back to `(key) => key` is a visible
                # change rather than a silent regression.
                self.assertIn("interpolat", source.lower(), str(mocks))
                self.assertIn("every render", source, str(mocks))

        adapter = (ROOT / "packages/i18n/src/index.ts").read_text(encoding="utf-8")
        self.assertIn("@soymutdb/i18n-core", adapter)
        core = json.loads(
            (ROOT / "packages/i18n/package.json").read_text(encoding="utf-8")
        )
        self.assertIn("@soymutdb/i18n-core", core["dependencies"])

        # No test may re-introduce the per-render `t` mock.
        offenders = []
        pattern = re.compile(
            r"useTranslation:\s*\(\s*\)\s*=>\s*\(\{[^}]*?t:\s*(?P<value>\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
            re.S,
        )
        for source in sorted(ROOT.glob("apps/*/src/**/*.test.ts*")):
            if pattern.search(source.read_text(encoding="utf-8")):
                offenders.append(str(source.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            "these test files mock useTranslation with a per-render `t`:\n"
            + "\n".join(offenders),
        )

    def test_shared_test_setup_restores_stubbed_globals(self) -> None:
        """A test setup that stubs globals must undo them.

        Real CNB failure: `apps/admin` used `vi.stubGlobal` and then called only
        `vi.restoreAllMocks()` in teardown. Vitest documents `restoreAllMocks` as
        spying only — it deliberately leaves stubbed globals in place — so each
        stub outlived its own test, including a `stubGlobal("crypto", undefined)`
        that removed the property rather than restoring it, and react-dom then
        hit the hole from a later file.

        The Vue apps do not stub globals: their test support mounts a component
        with an isolated query client and clears the document between tests, and
        `vi.clearAllMocks()` is enough because nothing replaces a global. The
        guard therefore checks that no app reintroduces a setup file that stubs
        globals without unstubbing them.
        """
        offenders = []
        for setup in sorted(ROOT.glob("apps/*/src/test/setup.ts")):
            text = setup.read_text(encoding="utf-8")
            if "stubGlobal" in text and "unstubAllGlobals" not in text:
                offenders.append(str(setup.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            "these setup files stub globals without unstubbing them:\n"
            + "\n".join(offenders),
        )

    def test_js_unit_tests_do_not_inherit_the_build_environment(self) -> None:
        """`turbo run test` must not see the demo build's VITE_* variables.

        On a real CNB build the api-client suite failed with

            AssertionError: expected 'https://api.soymutdb.test/genes/Glyma...'
                                 to be '/api/v1/genes/Glyma.01G000100'

        `apiBaseUrl` resolves from `import.meta.env.VITE_API_BASE_URL` and only
        falls back to the relative base when it is unset — and the suite asserts
        the relative base, because it is testing path construction. CI exports
        VITE_API_BASE_URL for the demo build, and turbo.json lists it under
        `globalEnv`, so the build-time value leaked into the unit tests.

        The fix is to isolate the test run, not to weaken the URL assertions: a
        test whose result depends on an ambient variable is not a test of this
        package. `turbo run test` sets NODE_ENV=test, and vitest resolves
        `import.meta.env` from process.env, so the package config must clear the
        build variables before the config is evaluated.
        """
        config = (ROOT / "packages/api-client/vitest.config.ts").read_text(encoding="utf-8")
        for variable in ("VITE_API_BASE_URL", "VITE_JBROWSE_BASE_URL"):
            self.assertIn(
                f"delete process.env.{variable}",
                config,
                f"packages/api-client/vitest.config.ts must clear {variable} before "
                "vitest resolves import.meta.env",
            )

        # The variable must still be a tracked turbo input for build tasks, or
        # cross-environment builds would share cache entries.
        turbo = json.loads((ROOT / "turbo.json").read_text(encoding="utf-8"))
        self.assertIn("VITE_API_BASE_URL", turbo.get("globalEnv", []))

        # And it must still be exported for the gates that legitimately need it.
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("SOYMUTDB_CI_DEMO_API_URL", gate)

    def test_variant_row_key_guard_is_wired_into_both_gates(self) -> None:
        """A source+test co-reversion must fail, not stay green.

        A stale-base branch carried an older ``rowKey`` together with the two
        test cases that match it: vitest reported 2/2 and the OpenAPI gate has
        no opinion about frontend source. The guard reads the committed sources
        independently of the test runner, so deleting tests cannot make it
        greener. Both the frontend gate and the contracts layer must invoke it.
        """
        frontend = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/check_variant_row_key_contract.py", frontend)
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/test_variant_row_key_contract.py", smoke)
        self.assertTrue((ROOT / "scripts/check_variant_row_key_contract.py").is_file())
        self.assertTrue((ROOT / "scripts/test_variant_row_key_contract.py").is_file())

    def test_api_client_base_path_guard_is_wired_into_both_gates(self) -> None:
        """PR #117 doubled /api/v1 in the sequence client; a source guard is
        the only gate that reads .ts path construction. Both the frontend gate
        and the contracts smoke layer must run it, and its regression suite
        must prove the doubled-BASE shape fails."""
        frontend = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/check_api_client_base_path.py --self-test", frontend)
        self.assertIn("scripts/check_api_client_base_path.py", frontend)
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("scripts/test_api_client_base_path_guard.py", smoke)
        self.assertTrue((ROOT / "scripts/check_api_client_base_path.py").is_file())
        self.assertTrue((ROOT / "scripts/test_api_client_base_path_guard.py").is_file())

    def test_package_script_invocations_do_not_double_up_the_separator(self) -> None:
        """`pnpm run <script> -- --flag` forwards a literal "--" to the script.

        On a real CNB build the frontend gate ran

            pnpm --filter @soymutdb/i18n-core check:locale-keys -- --self-test

        which executed `node check-locale-keys.mjs -- --self-test` and failed
        with `ENOENT: no such file or directory, open '--'`. The symptom points
        at a missing locale file; the cause is an extra separator. pnpm consumes
        the FIRST `--` as its own end-of-options marker, so the second one is
        passed straight through to the script's argv.
        """
        offenders = []
        for script in SHARED_SCRIPTS:
            if not script.endswith(".sh"):
                continue
            text = "\n".join(
                line
                for line in (ROOT / script).read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            for line in text.splitlines():
                # Any bare `--` after the script name. Looking only for `-- --`
                # would miss the equally broken one-separator form
                # (`pnpm run check -- --self-test`, where the flag itself is
                # `--self-test` and the separator is the sole `--`).
                if re.search(r"\bpnpm\b.*(^|\s)--(\s|$)", line):
                    offenders.append(f"{script}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "these pnpm invocations forward a literal '--' to the script:\n"
            + "\n".join(offenders),
        )

    def test_frontend_gate_self_test_really_runs_the_self_test(self) -> None:
        """Regression: the locale checker must be invoked as a self-test.

        The bare `--` above meant the parity gate's self-test never executed; the
        checker instead read a file called `--` and failed. Assert the exact
        command shape that pnpm turns into `node check-locale-keys.mjs
        --self-test`, and that the checker treats `--self-test` as a mode flag
        rather than a path.
        """
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn(
            "pnpm --filter @soymutdb/i18n-core check:locale-keys --self-test",
            gate,
            "the locale parity gate must run the checker's self-test",
        )

        checker = (ROOT / "packages/i18n-core/check-locale-keys.mjs").read_text(encoding="utf-8")
        self.assertIn('args[0] === "--self-test"', checker)

        manifest = json.loads(
            (ROOT / "packages/i18n-core/package.json").read_text(encoding="utf-8")
        )
        self.assertIn("check:locale-keys", manifest.get("scripts", {}))

        # Run the real thing: both the self-test and the fixture check must pass.
        for args in (["--self-test"], []):
            completed = subprocess.run(
                ["node", "check-locale-keys.mjs", *args],
                cwd=ROOT / "packages/i18n-core",
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"check-locale-keys.mjs {args} failed:\n{completed.stdout}\n{completed.stderr}",
            )

        # The invocation the gate used to make. The checker now filters a stray
        # `--` as defence in depth, so passing is correct — but the flag after it
        # must still select the self-test. A checker that swallowed the flag too
        # would "pass" by running the plain parity check, which is exactly the
        # false green this regression exists to prevent.
        completed = subprocess.run(
            ["node", "check-locale-keys.mjs", "--", "--self-test"],
            cwd=ROOT / "packages/i18n-core",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"the `--` form must degrade to a normal run:\n{completed.stdout}\n{completed.stderr}",
        )
        self.assertIn(
            "self-test passed",
            completed.stdout,
            "a stray `--` must not swallow the following --self-test flag",
        )

    def test_scripts_that_run_pnpm_bootstrap_their_own_container(self) -> None:
        """Generalised form of the container-lifecycle rule.

        The first real build failed at `Frontend verification` with
        `pnpm: command not found` because it inherited nothing from the stage
        before it. Checking only the two job bodies I happened to fix would leave
        the next script with the same bug, so instead: any shared script that
        shells out to pnpm must reach scripts/setup-workspace.sh.
        """
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        # A script may legitimately call pnpm without bootstrapping IF it is only
        # ever reached through an entry point that already bootstrapped in the
        # same container (frontend_run -> frontend_install -> verify-*.sh). The
        # rule is therefore about entry points: whatever a CNB stage invokes
        # directly must reach the bootstrap itself.
        entry_scripts = set()
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for _location, body in _iter_script_bodies(document):
                for referenced in re.findall(r"scripts/([\w./-]+\.sh)", body):
                    entry_scripts.add(f"scripts/{referenced}")
                # `bash scripts/ci-job-steps.sh run <job>` is the other entry
                # style; the job body is checked separately below.
                for job in re.findall(r"ci-job-steps\.sh run ([\w-]+)", body):
                    function = f"{job.replace('-', '_')}_run"
                    entry_scripts.add(function)

        offenders = []
        for script in sorted(entry_scripts):
            if script in {"scripts/setup-workspace.sh", "scripts/smoke.sh"}:
                continue
            path = ROOT / script
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            lines = [
                line
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if not any(re.search(r"(^|[^\w-])pnpm\s", line) for line in lines):
                continue
            # setup-workspace.sh is the bootstrap itself; a script that names it
            # is delegating correctly.
            if "setup-workspace.sh" in text:
                continue
            offenders.append(script)
        self.assertEqual(
            offenders,
            [],
            "scheduled entry points run pnpm but never bootstrap pnpm:\n"
            + "\n".join(offenders),
        )

        # Same rule for the ci-job-steps entry points, following the call chain.
        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)

        def reaches_bootstrap(name: str, seen: frozenset[str] = frozenset()) -> bool:
            if name in seen or name not in bodies:
                return False
            body = bodies[name]
            if "setup-workspace.sh" in body:
                return True
            return any(
                reaches_bootstrap(callee, seen | {name})
                for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M)
            )

        for name, body in bodies.items():
            if not name.endswith("_run"):
                continue
            if not any(
                re.search(r"(^|[^\w-])pnpm\s", line)
                for line in body.splitlines()
                if not line.lstrip().startswith("#")
            ):
                # The body may delegate to a helper that uses pnpm; check those
                # by resolving the whole chain for pnpm usage.
                chain_uses_pnpm = any(
                    re.search(r"(^|[^\w-])pnpm\s", bodies.get(callee, ""))
                    for callee in re.findall(r"^\s*(\w+)\s*$", body, re.M)
                )
                if not chain_uses_pnpm:
                    continue
            self.assertTrue(
                reaches_bootstrap(name),
                f"{name} needs pnpm but never reaches scripts/setup-workspace.sh; "
                "it would fail with `pnpm: command not found` in its own container",
            )

        # The governance job body must bootstrap the Python modules its own
        # `pnpm deps:*` scripts import. The GitHub mirror installs
        # `PyYAML==6.0.3 uv==0.13.1` by hand; the CNB stage ran in
        # `node:26.13.0`, which has no PyYAML and no pip, and died with
        # `ModuleNotFoundError: No module named 'yaml'`.
        self.assertIn("ensure_governance_python", bodies["dependency_governance_step"])
        governance_python = bodies["ensure_governance_python"]

        # python-licenses-worker runs `uv run --locked --project apps/worker`,
        # which resolves the worker science stack (h5py has no CPython 3.15
        # wheel) and therefore needs HDF5 headers + pkg-config in THIS stage's
        # container. "Compiler prerequisites" is a separate container, so its
        # apt install does not survive here. Without the shared prerequisite
        # script the analyzer never starts, no report is written, and the gate
        # fails with `normalization_unavailable:license-expressions`.
        governance_step = bodies["dependency_governance_step"]
        self.assertIn("install-worker-science-build-deps.sh", governance_step)
        self.assertIn("HDF5_PKGCONFIG_NAME", governance_step)
        self.assertLess(
            governance_step.index("install-worker-science-build-deps.sh"),
            governance_step.index("deps:audit"),
            "HDF5 prerequisites must be installed before uv builds h5py",
        )
        self.assertIn("import yaml", governance_python)
        self.assertIn("PyYAML==", governance_python)
        # `uv`/`uvx` drive the Deptry/license analyzers; without it every one is
        # reported unavailable, which the fail-closed gate treats as a failure.
        self.assertIn("uv==${UV_VERSION}", governance_python)
        # It must be pinned, or the two providers can resolve different linters.
        self.assertIn("GOVERNANCE_PYYAML_VERSION", steps)
        self.assertIn("SOYMUTDB_CI_GOVERNANCE_PYYAML_VERSION", steps)
        # A bare `node:*` python has no pip, so the job body must be able to
        # bootstrap it; otherwise the install above fails with
        # `No module named pip` and the real cause is hidden again.
        # The pip bootstrap is reached from the PyYAML installer, not from the
        # step directly.
        self.assertIn("ensure_governance_pip", governance_python)
        self.assertIn("ensurepip", bodies["ensure_governance_pip"])

        # A stage `image:` overrides the pipeline environment, so a Node-only
        # pin is exactly the regression: the gate also needs an interpreter.
        # Check every config that can run the stage, including the standalone
        # pipeline records -- `.cnb/pipelines/verify.yml` is a third copy that a
        # root-config-only assertion would miss.
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                build = (pipeline.get("docker") or {}).get("build")
                inherited = build if isinstance(build, dict) else {}
                for stage in pipeline.get("stages", []):
                    if "run dependency-governance" not in str(stage.get("script", "")):
                        continue
                    image = str(stage.get("image", ""))
                    self.assertNotIn(
                        "node:",
                        image,
                        f"{config.name}/{stage.get('name')}: image={image!r} has no "
                        "Python, but the governance gate runs a Python script",
                    )
                    if not image:
                        self.assertTrue(
                            inherited.get("dockerfile"),
                            f"{config.name}/{stage.get('name')}: the stage drops its "
                            "`image:` without a pipeline-level docker.build to "
                            "inherit a dual-toolchain environment from",
                        )

        # And the stage that runs them must mount the store, or the install
        # caches into a container layer that is thrown away.
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))
        for branch, event, pipeline_name in (
            ("main", "pull_request", "verify"),
            ("main", "push", "verify"),
            ("$", "web_trigger_verify", "verify-manual"),
        ):
            pipelines = _cnb_pipelines(branch, event)
            pipeline = next(p for p in pipelines if p["name"] == pipeline_name)
            pipeline_volumes = " ".join(
                str(v) for v in (pipeline.get("docker", {}).get("volumes") or [])
            )
            for stage in pipeline["stages"]:
                uses_pnpm = bool(
                    re.search(r"(^|[^\w-])pnpm\s", _flatten(stage).replace("run ", " "))
                ) or "build-pages-artifact" in _flatten(stage)
                if uses_pnpm:
                    self.assertIn(
                        "pnpm-store",
                        pipeline_volumes,
                        f"{branch}/{event}/{pipeline_name}/{stage['name']}: "
                        "pnpm stage without a persistent store volume",
                    )

    def test_frontend_stage_can_reach_the_openapi_contract_gate(self) -> None:
        """The frontend gate ends with a Python-backed contract check.

        Regression for a real CNB build:

            ==> API client contract
            $ bash scripts/check-contract.sh
            >> exporting OpenAPI from backend...
            scripts/check-contract.sh: line 18:
            /workspace/apps/api/.venv/bin/python: No such file or directory
            [ERR_PNPM_RECURSIVE_RUN_FIRST_FAIL] @soymutdb/api-client@2.0.0
            check:contract: `bash scripts/check-contract.sh`

        `verify-frontend-artifacts.sh` closes with
        `pnpm --filter @soymutdb/api-client check:contract`, and that script
        exports the backend OpenAPI document from `apps/api/.venv/bin/python`.
        CNB ran the gate in `node:26.13.0`, which carries no Python, so the venv
        could neither exist nor be created. The GitHub mirror escaped the same
        failure only because `actions/setup-python` installs an interpreter.

        Every one of these is load-bearing; dropping any of them re-opens the
        failure without changing the failure message.
        """
        # 1. The gate really is a hard, non-skippable step of the frontend
        #    script, or nothing below would matter.
        gate = (ROOT / "scripts/verify-frontend-artifacts.sh").read_text(encoding="utf-8")
        self.assertIn("@soymutdb/api-client check:contract", gate)
        self.assertIn(
            "SOYMUTDB_CI_SKIP_CONTRACT",
            gate,
            "the contract gate must be the only thing an explicit skip flag bypasses",
        )

        # 2. The contract script must keep exporting the schema with the venv
        #    interpreter, so the venv is genuinely required.
        contract = (ROOT / "packages/api-client/scripts/check-contract.sh").read_text(
            encoding="utf-8"
        )
        # The contract script resolves the venv from the package root, so the
        # marker is the relative venv path, not a literal absolute one.
        self.assertIn(".venv/bin/python", contract)
        self.assertIn('API_DIR="$REPO_ROOT/apps/api"', contract)

        # 3. The frontend job body must create that venv before running the gate.
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")

        def function_bodies(text: str) -> dict[str, str]:
            bodies: dict[str, str] = {}
            for match in re.finditer(r"^(\w+)\(\) \{\n", text, re.M):
                start = match.end()
                end = text.index("\n}\n", start)
                bodies[match.group(1)] = text[start:end]
            return bodies

        bodies = function_bodies(steps)
        self.assertIn("ensure_api_venv", bodies)

        venv_body = bodies["ensure_api_venv"]
        self.assertIn("apps/api/.venv", venv_body)
        # The venv and the editable workspace installs are owned by the shared
        # bootstrap so GitHub, CNB, and local runs cannot drift on the install
        # order (packages/import-protocol is not publishable to PyPI).
        self.assertIn("scripts/install_python_workspace.py", venv_body)
        self.assertIn("apps/api", venv_body)
        bootstrap = (ROOT / "scripts/install_python_workspace.py").read_text(encoding="utf-8")
        self.assertIn("packages/jobs-py", bootstrap)
        self.assertIn("packages/import-protocol", bootstrap)
        # The venv must actually be created by the bootstrap, not assumed.
        self.assertIn('"-m", "venv"', bootstrap)

        # The interpreter must be the PINNED one. The image supplies it, but
        # `command -v python3` succeeding is a weaker claim than "python3 is
        # 3.15": a rebuilt image could put 3.11 on PATH, the venv would be
        # created, and the contract gate would validate against a backend the
        # repository never declared. Assert the version check is real.
        self.assertIn("interpreter_matches_pin", bodies)
        check_body = bodies["interpreter_matches_pin"]
        self.assertIn("PYTHON_VERSION", check_body)
        self.assertIn(
            "version_info",
            check_body,
            "the interpreter must be compared against the pin, not merely found",
        )
        self.assertRegex(
            venv_body,
            r"(?m)^\s*if ! interpreter_matches_pin",
            "ensure_api_venv must reject an interpreter that misses the pin",
        )

        # frontend_run must actually call it, in the same container as the gate.
        self.assertRegex(
            bodies["frontend_run"],
            r"(?m)^\s*ensure_api_venv\s*$",
        )

        # 4. The frontend stage's environment must carry BOTH toolchains, and it
        #    must be declared where CNB can actually consume a Dockerfile.
        #
        #    This is the regression that made the first CNB build of this PR fail
        #    before a single gate ran:
        #
        #        docker pull .cnb/env/Dockerfile.frontend
        #        invalid reference format: repository name must be lowercase
        #
        #    `image:` is a registry reference. The platform's runner passes it
        #    straight to `docker pull`, so a repository path is not a valid value
        #    there, whatever it points at. A Dockerfile may only appear in
        #    `docker.build`, and `build` exists at the PIPELINE level only
        #    ("任务级仅支持 image 配置，不支持 dockerfile"). Assert both halves, or
        #    the config can pass every other check while still failing on the
        #    runner.
        frontend_dockerfiles = set()
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                frontend_stages = [
                    stage
                    for stage in pipeline.get("stages", [])
                    if "run frontend" in str(stage.get("script", ""))
                ]
                if not frontend_stages:
                    continue

                # 4a. Never put a path in `image:`; the runner would `docker
                #     pull` it. This is the exact failure being guarded.
                for stage in frontend_stages:
                    image = str(stage.get("image", ""))
                    self.assertNotRegex(
                        image,
                        r"^[./]|Dockerfile",
                        f"{config.name}: the frontend stage sets image={image!r}; "
                        "`image:` is handed to `docker pull`, so it must be a "
                        "registry reference, not a Dockerfile path (use docker.build)",
                    )

                # 4b. The environment therefore comes from the pipeline-level
                #     `docker.build`, which must name a committed Dockerfile that
                #     carries both pinned toolchains.
                build = (pipeline.get("docker") or {}).get("build")
                self.assertIsNotNone(
                    build,
                    f"{config.name}: the frontend stage needs a dual-toolchain "
                    "image, which only a pipeline-level `docker.build` can supply",
                )
                dockerfile = build if isinstance(build, str) else build.get("dockerfile")
                self.assertTrue(
                    dockerfile,
                    f"{config.name}: docker.build names no Dockerfile",
                )
                frontend_dockerfiles.add(str(dockerfile))

        self.assertTrue(
            frontend_dockerfiles, "no CNB pipeline declares the frontend environment"
        )
        for dockerfile_path in frontend_dockerfiles:
            path = ROOT / dockerfile_path
            self.assertTrue(
                path.is_file(),
                f"{dockerfile_path} runs the frontend gate but is not committed",
            )
            # Present is not enough. `.gitignore` once had an unanchored `env/`
            # pattern that matched `.cnb/env/` at any depth, so these files
            # existed in the working tree but never in a checkout and the
            # schema-documenting test above still passed. Ask git.
            ignored = subprocess.run(
                ["git", "check-ignore", "--quiet", dockerfile_path],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(
                ignored.returncode,
                0,
                f"{dockerfile_path} is ignored by .gitignore; a CNB checkout "
                "would not have it",
            )
            docker_text = path.read_text(encoding="utf-8")
            self.assertRegex(
                docker_text,
                r"(?m)^FROM python:3\.15",
                f"{dockerfile_path} must carry Python for the OpenAPI contract gate",
            )
            # Node is installed from the official release tarball, not from a
            # `FROM node:` base: python:3.15 and node:26.13.0 sit on different
            # Debian generations, and `COPY --from` cannot carry the C library
            # the copied interpreter needs, so the reverse composition dies with
            # `GLIBC_2.38 not found`. Assert the version arrives pinned AND that
            # the download is verified, or the toolchain can be swapped under a
            # reviewed pin.
            self.assertRegex(
                docker_text,
                rf"(?m)^ARG NODE_VERSION={re.escape(NODE_VERSION)}$",
                f"{dockerfile_path} must pin Node to the repository version",
            )
            self.assertIn(
                "sha256sum --check",
                docker_text,
                f"{dockerfile_path} must verify the Node tarball checksum",
            )
            self.assertNotRegex(
                docker_text,
                r"(?m)^FROM node:",
                f"{dockerfile_path} cannot be built on a node: base and also "
                "provide Python 3.15 from python: via COPY --from",
            )

    def test_openapi_contract_gate_is_never_skipped_in_ci(self) -> None:
        """No CI caller may mention the flag that bypasses the contract gate.

        ``verify-frontend-artifacts.sh`` ends with
        ``pnpm --filter @soymutdb/api-client check:contract``, guarded by
        ``SOYMUTDB_CI_SKIP_CONTRACT``. That gate is the only check that
        re-exports ``app.main:app`` and diffs the fresh document against the
        committed snapshot, so setting the flag in a CI caller would hide a
        stale ``openapi.json`` while every unit guard stays green. Local and
        build-only callers may still use it; the assertion covers CI configs
        and the shared job bodies they delegate to.

        The name is forbidden outright rather than matched as an assignment:
        YAML ``key: "1"``, shell ``key=1`` and ``export key=1`` all have to
        redden, and a commented-out assignment is one edit away from a real
        one. Document why it stays unset in the script's header instead.

        The companion assertion in
        ``test_frontend_stage_can_reach_the_openapi_contract_gate`` pins the
        opposite direction -- that the flag exists and bypasses only this one
        gate -- so it must stay.
        """
        flag = "SOYMUTDB_CI_SKIP_CONTRACT"
        configs = list(_cnb_config_files())
        # LEGACY_WORKFLOWS is the mirror's *dispatch* list, not an inventory of
        # every workflow file: dependency-lock-candidates.yml is a workflow too,
        # so enumerate the directory instead of trusting a hand-kept tuple.
        configs += sorted((ROOT / ".github/workflows").glob("*.yml"))
        configs.append(ROOT / "scripts/ci-job-steps.sh")
        self.assertEqual(
            len(configs),
            len(set(configs)),
            "a CI caller is listed twice; check the config inventory",
        )
        # A guard over an empty or stale inventory is vacuously green. Pin the
        # floor so deleting or renaming a config cannot silently shrink it.
        self.assertGreaterEqual(len(configs), 16, "CI config inventory shrank")
        for config in configs:
            self.assertTrue(config.is_file(), f"missing CI caller: {config}")
            body = config.read_text(encoding="utf-8")
            self.assertNotIn(
                flag,
                body,
                f"{config.relative_to(ROOT)} mentions {flag}; no CI caller may "
                "set it, because the OpenAPI contract gate is the only check "
                "that can see a stale snapshot",
            )

    def test_no_stage_image_is_a_dockerfile_path(self) -> None:
        """A Dockerfile belongs in `docker.build`, never in `image:`.

        Regression for the failure that took down the first CNB build of the PR
        that added the frontend environment, and for the same breakage already
        present on main in the release/image pipelines:

            Runner[docker] $ docker pull .cnb/env/Dockerfile.frontend
            invalid reference format: repository name (env/Dockerfile.frontend)
            must be lowercase

            Runner[docker] $ docker pull .cnb/env/Dockerfile.build-tools
            invalid reference format: repository name (env/Dockerfile.build-tools)
            must be lowercase

        `image:` is a registry reference. The runner hands it to `docker pull`
        verbatim, so any value that names a file in the repository fails before
        a single stage script runs, on every provider and every branch. Only
        `docker.build` accepts a Dockerfile, and `build` exists at the pipeline
        level alone ("任务级仅支持 image 配置，不支持 dockerfile").

        The two earlier tests asserted that the referenced file exists, is
        tracked and carries the right toolchains. All of that held while the
        build still failed, because none of them asked whether the platform can
        consume a path in that position. This one does, for every `image:` in
        every pipeline and every stage, not just the frontend one.
        """
        offenders = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                docker = pipeline.get("docker") or {}
                images = [
                    str(docker.get("image", "")),
                    *[
                        str(stage.get("image", ""))
                        for stage in pipeline.get("stages", [])
                        if isinstance(stage, dict)
                    ],
                ]
                for image in images:
                    if not image:
                        continue
                    # A registry reference is `<name>[:tag]`; it never starts
                    # with a path component and never names a Dockerfile.
                    # Anything else is a file path the runner would try to pull.
                    looks_like_path = (
                        image.startswith((".", "/"))
                        or "Dockerfile" in image
                    )
                    if looks_like_path:
                        offenders.append(
                            f"{config.name}: image={image!r} is a repository path; "
                            "`image:` is passed to `docker pull` — use "
                            "`docker.build.dockerfile` instead"
                        )
        self.assertEqual(
            offenders,
            [],
            "stage/pipeline images must be registry references, not Dockerfiles:\n"
            + "\n".join(offenders),
        )

    def test_every_cnb_stage_script_target_exists_on_disk(self) -> None:
        """No stage may reference a script that is not in the repository."""
        missing = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for location, body in _iter_script_bodies(document):
                for referenced in re.findall(r"scripts/([\w./-]+\.(?:sh|py))", body):
                    if not (ROOT / "scripts" / referenced).is_file():
                        missing.append(f"{config.name}:{location}: scripts/{referenced}")
        self.assertEqual(missing, [], "stage bodies reference missing scripts:\n" + "\n".join(missing))

    def test_cnb_toolchain_pins_are_actually_in_sync(self) -> None:
        """Run the repository guard that keeps NODE_VERSION from desyncing.

        `.nvmrc` and `.node-version` are read by different toolchains, so they
        must both equal NODE_VERSION. They had already drifted apart while this
        test was written, which is why the assertion lives in code and not in a
        reviewer's checklist.
        """
        check = ROOT / "scripts/check-toolchain-pins.py"
        self.assertTrue(check.is_file(), "missing scripts/check-toolchain-pins.py")
        result = subprocess.run(
            ["python3", str(check)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cnb_env_helpers_referenced_by_cnb_yml_exist(self) -> None:
        """.cnb.yml must not point at files that were never committed.

        `image: .cnb/env/Dockerfile.build-tools` and the release `imports:` URL
        are both load-bearing: a missing Dockerfile fails the job, and a missing
        import URL can fail config resolution before any stage starts.
        """
        text = _cnb_text()
        self.assertTrue(
            (ROOT / ".cnb/env/Dockerfile.build-tools").is_file(),
            ".cnb.yml builds .cnb/env/Dockerfile.build-tools but it is not committed",
        )
        self.assertTrue(
            (ROOT / ".cnb/env/release.yml").is_file(),
            ".cnb.yml imports .cnb/env/release.yml but it is not committed",
        )
        # Existing in the working tree is not enough: `.gitignore` had a
        # virtualenv pattern (`env/`, no leading slash) that matched at any
        # depth, so .cnb/env/ was ignored and these files were "added" in review
        # after review without ever being committed. Ask git, not the filesystem.
        untracked = []
        for relative in (".cnb/env/Dockerfile.build-tools", ".cnb/env/release.yml"):
            check = subprocess.run(
                ["git", "check-ignore", "--quiet", relative],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if check.returncode == 0:
                untracked.append(f"{relative}: ignored by .gitignore")
                continue
            staged = subprocess.run(
                ["git", "ls-files", "--cached", "--error-unmatch", relative],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if staged.returncode != 0:
                untracked.append(f"{relative}: present but not tracked by git")
        self.assertEqual(
            untracked,
            [],
            "files .cnb.yml references must be tracked, not just present:\n"
            + "\n".join(untracked),
        )
        for referenced in re.findall(r"\.cnb/env/([\w.-]+)", text):
            self.assertTrue(
                (ROOT / ".cnb/env" / referenced).is_file(),
                f".cnb.yml references missing .cnb/env/{referenced}",
            )

    def test_ci_job_steps_only_advertises_commands_it_implements(self) -> None:
        """No documented entry point may be left undeclared.

        `emit github|cnb` used to be documented in the usage text and dispatched
        to scripts/emit-ci-pipeline.py, which was never committed. The command
        was removed; this test keeps a future usage string honest.
        """
        steps = ROOT / "scripts/ci-job-steps.sh"
        text = steps.read_text(encoding="utf-8")
        self.assertNotIn("emit-ci-pipeline.py", text)
        for documented in ("list", "run"):
            self.assertIn(documented, text, documented)

        # Anything the usage text documents must be a real case label.
        usage = re.search(r"Commands:\n(.*?)\nJobs:", text, re.S)
        self.assertIsNotNone(usage, "usage block not found")
        documented_commands = set(re.findall(r"^\s{2}(\w+)", usage.group(1), re.M))
        implemented = set(re.findall(r"^\s{4}(\w+[\w-]*)\)", text, re.M))
        self.assertLessEqual(
            documented_commands,
            implemented,
            f"documented but not implemented: {documented_commands - implemented}",
        )

    def test_every_advertised_job_actually_dispatches(self) -> None:
        """`run <job>` must resolve for every job `list` prints.

        Regression for a real CNB build. `api-tests` was advertised by `list`
        and invoked by five pipeline stages, but its body was named `api_run`,
        while the dispatcher resolves `<job with - as _>_run`. The stage died in
        1.6s with no test executed:

            $ bash scripts/ci-job-steps.sh run api-tests
            unknown job: api-tests
            Finished, code: 2

        The sibling contract only asserted the *string* `run api-tests` was
        present in the pipeline configs, so it passed the entire time. This test
        exercises the dispatcher itself. It never runs a job body, so it stays
        fast and toolchain-free: the dispatcher is asked to resolve each name
        with its own rule, then verified with `declare -F`.
        """
        steps = ROOT / "scripts/ci-job-steps.sh"
        catalog = subprocess.run(
            ["bash", str(steps), "list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        jobs = catalog.stdout.split()
        self.assertTrue(jobs, "the job catalog is empty")

        # Resolve each advertised job exactly as `main()` does.
        resolver = "; ".join(
            f'if declare -F "{job.replace("-", "_")}_run" >/dev/null; '
            f'then echo "OK {job}"; else echo "MISSING {job}"; fi'
            for job in jobs
        )
        # `main "$@"` would execute the job instead of only defining it, so the
        # library is sourced with that single dispatch line removed.
        source_without_dispatch = 'source <(sed "s|^main \\"\\$@\\"$||" "$1")'
        resolved = subprocess.run(
            ["bash", "-c", f'{source_without_dispatch}; {resolver}', "bash", str(steps)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            resolved.returncode,
            0,
            f"dispatcher probe failed:\n{resolved.stdout}\n{resolved.stderr}",
        )

        reported = [line.split(None, 1) for line in resolved.stdout.splitlines() if line.strip()]
        self.assertEqual(
            len(reported),
            len(jobs),
            f"dispatcher probe reported {len(reported)} of {len(jobs)} jobs: {resolved.stdout}",
        )

        missing = [job for verdict, job in reported if verdict == "MISSING"]
        self.assertEqual(
            missing,
            [],
            "jobs advertised by `list` but not dispatchable by `run`: " + ", ".join(missing),
        )

    def test_smoke_profiles_cover_every_layer_and_never_fake_a_pass(self) -> None:
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        for profile in ("contracts", "static", "runtime", "e2e", "images"):
            self.assertIn(profile, smoke, profile)
        # A missing prerequisite must be reported SKIPPED, not as success.
        self.assertIn("skip_layer", smoke)
        self.assertIn("SMOKE PASS", smoke)
        self.assertIn("SMOKE FAIL", smoke)

    def test_package_scripts_expose_the_shared_entrypoints(self) -> None:
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        self.assertEqual(scripts["smoke"], "bash scripts/smoke.sh")
        for name in ("ci:verify", "ci:api", "ci:images", "ci:release", "ci:jobs"):
            self.assertIn(name, scripts, name)
            self.assertIn("scripts/ci-job-steps.sh", scripts[name])

    def test_shared_scripts_are_executable_and_strict(self) -> None:
        # Two documented exceptions, both multi-layer reporters. They must run
        # every layer even after one fails, or the summary would hide the rest
        # of the evidence — so they use `set -uo pipefail` without `-e` and
        # decide their exit status explicitly.
        #
        #   scripts/smoke.sh       prints SMOKE PASS / SMOKE FAIL
        #   scripts/acceptance.sh  prints ACCEPTANCE PASS / ACCEPTANCE FAIL
        non_exiting = {
            "scripts/smoke.sh": "SMOKE FAIL",
            "scripts/acceptance.sh": "ACCEPTANCE FAIL",
        }
        for script in SHARED_SCRIPTS:
            if script.endswith(".py"):
                continue
            text = (ROOT / script).read_text(encoding="utf-8")
            if script in non_exiting:
                self.assertIn("set -uo pipefail", text, script)
                # `set -e` would abort on the first failed layer; the presence of
                # an explicit verdict is what replaces it, so assert both.
                self.assertNotIn("set -euo pipefail", text, script)
                self.assertIn(non_exiting[script], text, script)
                self.assertIn("exit 1", text, script)
            else:
                self.assertIn("set -euo pipefail", text, script)
            self.assertTrue(
                _is_executable(script),
                f"{script}: must be executable (filesystem or git index)",
            )

    def test_shared_scripts_never_echo_credentials(self) -> None:
        for script in SHARED_SCRIPTS:
            text = (ROOT / script).read_text(encoding="utf-8")
            for leak in ("echo ${CNB_TOKEN", "echo $CNB_TOKEN", "set -x"):
                self.assertNotIn(leak, text, f"{script}: {leak}")

    def test_frontend_test_imports_resolve_to_real_files(self) -> None:
        """Relative imports inside test files must point at files that exist.

        The shared i18n double (apps/<app>/src/test/mocks.ts) is imported with a
        hand-written relative path in every test file that needs it. Five of six
        paths were wrong, and the failure mode is quiet: Vite reports one resolve
        error per file, and the suite summary then reports *fewer* tests rather
        than any failure, so a broken import can read as a healthy run.

          Test Files  12 failed | 35 passed (47)
          Tests       10 failed | 76 passed (86)     ← 40 of 116 never collected

        Resolving each relative import against the importing file's directory
        turns that into a build-time error the reviewer can see.
        """
        unresolved: list[str] = []
        for test_file in sorted(
            list(ROOT.glob("apps/*/src/**/*.test.ts")) + list(ROOT.glob("apps/*/src/**/*.test.tsx"))
        ):
            text = test_file.read_text(encoding="utf-8")
            for match in re.finditer(r"""(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)""", text):
                specifier = match.group(1)
                if not specifier.startswith("."):
                    continue
                base = test_file.parent / specifier
                candidates = [
                    base,
                    *[base.with_suffix(suffix) for suffix in (".ts", ".tsx", ".js", ".jsx", ".json")],
                    base / "index.ts",
                    base / "index.tsx",
                ]
                if not any(candidate.is_file() for candidate in candidates):
                    unresolved.append(
                        f"{test_file.relative_to(ROOT)}: {specifier}"
                    )
        self.assertEqual([], unresolved, "test imports that do not resolve:")

    # -------------------------------------------------------------------------
    # Startup and acceptance
    # -------------------------------------------------------------------------
    # "Can I start it?" and "can I accept it?" used to be answerable only by a
    # developer with a local Docker daemon. They are now platform entry points:
    # $ -> vscode starts a development environment, and the web-trigger
    # acceptance pipeline states a verdict about a revision. Both are contracts
    # in their own right, so they are asserted here rather than left to review.

    def test_cloud_development_entry_point_prepares_the_environment(self) -> None:
        """The cloud dev button must run the shared bootstrap, not inline YAML."""
        document = _cnb()
        pipelines = document["$"]["vscode"]
        self.assertEqual(len(pipelines), 1)
        pipeline = pipelines[0]

        # `services: vscode` is what makes this the platform's development entry
        # point; without it the button falls back to the default environment and
        # the SoyMutDB bootstrap never runs.
        services = pipeline["services"]
        self.assertIn("docker", services)
        vscode_service = next(s for s in services if isinstance(s, dict) and s.get("name") == "vscode")
        options = vscode_service["options"]
        self.assertIs(options["onlyPreview"], True)
        self.assertIn("scripts/start-cloud-dev.sh", options["launch"])

        # The launch command must be reachable after a fresh checkout. `./` and
        # `bash` forms both pin the interpreter; a bare path relies on the exec
        # bit surviving the checkout.
        first_token = options["launch"].split()[0]
        self.assertIn(first_token, ("bash", "./"))

        # 8686 is fixed by only-preview mode. Passing it through the environment
        # keeps the launch command a plain script invocation and keeps the port
        # in one place.
        self.assertEqual(pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"], "8686")
        self.assertIn("8686", options["launch"] + pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"])

        # Every stage body is a single bash invocation (see the stage-shell
        # tests); the preparation stage runs the same script in full mode.
        self.assertEqual(
            [stage["script"] for stage in pipeline["stages"]],
            ["bash scripts/start-cloud-dev.sh full"],
        )

        # The store must be mounted, or every environment creation re-downloads
        # the whole dependency tree into a container layer.
        volumes = " ".join(str(v) for v in pipeline["docker"]["volumes"])
        self.assertIn("pnpm-store", volumes)

    def test_no_stage_declares_volumes_and_paths_do_not_nest(self) -> None:
        """Volumes must use the CNB grammar, at the pipeline level, non-nested.

        Real CNB failure this guards -- it killed the build in Prepare, before a
        single stage ran:

            Pipeline prepare error:
              Unsupported volume type. 不支持的数据卷类型: /cache/pnpm-store

        Two distinct mistakes produced that message, and both must be caught:

          1. Declaring the store as a STAGE key. `volumes` is only understood
             under `docker:` at the pipeline level; a stage-level one is not in
             the schema:

               stages:
                 - name: Frontend verification
                   volumes:                    # <-- not in the CNB schema
                     - /cache/pnpm-store

          2. Writing the entry in Docker's `host:container` form. CNB parses
             `<path>` or `[<group>:]<path>[:<type>]`, so the second segment is a
             TYPE, not a mount target:

               docker:
                 volumes:
                   - /cache/pnpm-store:/cache/pnpm-store   # <- "type" is a path

        Prepare parses the whole document before the first stage runs, so one bad
        entry fails every pipeline that copies it. Three invariants:

          1. No stage may declare `volumes`.
          2. Every entry must be valid CNB volume grammar (see _cnb_volume_path).
          3. No declared volume path may be a prefix of, or nested inside, another
             (`/a` and `/a/b/c` are rejected -- "存在包含关系的卷路径"). In
             particular a volume under /workspace is invalid, because /workspace
             is always shared.
        """
        document = yaml.safe_load(CNB_CONFIG.read_text(encoding="utf-8"))

        # 1. No stage-level volumes anywhere in the file. Walk branch -> event ->
        #    pipeline -> stages, which is the only place a stage can appear.
        for branch, events in document.items():
            if not isinstance(events, dict):
                continue
            for event, pipelines in events.items():
                for pipeline in pipelines or []:
                    for stage in pipeline.get("stages", []) or []:
                        self.assertNotIn(
                            "volumes",
                            stage,
                            f"{branch}/{event}/{pipeline.get('name')}/"
                            f"{stage.get('name')}: stage-level `volumes` is not a "
                            "supported key and fails Prepare with `Unsupported "
                            "volume type`; move it to the pipeline's "
                            "`docker.volumes`",
                        )

        # 2. Within ONE pipeline, every declared volume must be a normalised,
        #    non-nested absolute path. The inclusion rule is per pipeline, so the
        #    same store path may legitimately appear in several pipelines.
        def declared_volumes(body: object) -> list[str]:
            """Collect `docker.volumes` at any depth (pipeline and cloud-dev)."""
            found: list[str] = []
            if isinstance(body, dict):
                docker = body.get("docker")
                if isinstance(docker, dict):
                    found.extend(str(v) for v in (docker.get("volumes") or []))
                for value in body.values():
                    found.extend(declared_volumes(value))
            elif isinstance(body, list):
                for value in body:
                    found.extend(declared_volumes(value))
            return found

        pipelines_checked = 0
        for branch, events in document.items():
            if not isinstance(events, dict):
                continue
            for event, pipelines in events.items():
                for pipeline in pipelines or []:
                    entries = declared_volumes(pipeline)
                    if not entries:
                        continue
                    pipelines_checked += 1
                    location = f"{branch}/{event}/{pipeline.get('name')}"

                    paths: list[str] = []
                    for entry in entries:
                        path = _cnb_volume_path(entry, location)
                        self.assertTrue(
                            path.startswith("/"),
                            f"{location}: volume {entry!r}: only absolute "
                            "container paths are portable",
                        )
                        self.assertFalse(
                            path.startswith("/workspace") and path != "/workspace",
                            f"{location}: volume {entry!r}: /workspace is already "
                            "shared, so a volume nested inside it is rejected "
                            "(存在包含关系的卷路径)",
                        )
                        paths.append(path.rstrip("/"))

                    for index, path in enumerate(paths):
                        for other in paths[index + 1 :]:
                            nested = (
                                path == other
                                or path.startswith(other + "/")
                                or other.startswith(path + "/")
                            )
                            self.assertFalse(
                                nested,
                                f"{location}: volume paths {path!r} and {other!r} "
                                "overlap or nest; CNB rejects volumes with an "
                                "inclusion relationship",
                            )

        self.assertGreater(
            pipelines_checked, 0, "the pnpm store volume is required for caching"
        )

    def test_cloud_development_preview_survives_a_generated_hostname(self) -> None:
        """The CNB preview proxy must not be blocked by Umi's `allowedHosts`.

        Real report (Issue #10):

            Blocked request. This host ("cnb-38o-1k28dm5ta-001.cnb.space") is
            not allowed.
            To allow this host, add "cnb-38o-1k28dm5ta-001.cnb.space" to
            `devServer.allowedHosts` in the Umi config.

        The development server rejects any request whose `Host` is not allowlisted, and CNB
        mints a NEW `*.cnb.space` hostname for every environment. So neither
        half of the obvious fix is enough on its own:

          * hard-coding the reported hostname fixes exactly one environment;
          * `allowedHosts: true` accepts ANY hostname, which turns a forwarded
            preview URL into a DNS-rebinding pivot.

        The contract is therefore: the three dev servers (`web`, `admin`,
        `jbrowse`) resolve an allowlist through the shared helper, the helper
        matches the platform domains by pattern, and both the config and the
        bootstrap script stay additive instead of restrictive.
        """
        # 1. The helper exists in the apps that serve a dev server, matches the
        #    platform domains by pattern, and never defaults to a wildcard.
        deployment = (ROOT / "packages/shared/src/deployment.ts").read_text(encoding="utf-8")
        self.assertIn("export function resolveDevAllowedHosts", deployment)
        self.assertIn(".cnb.space", deployment)
        self.assertIn(".cnb.run", deployment)
        self.assertIn("normalizeDevHost", deployment)
        # The reported hostname must be covered by the PATTERN, not by a
        # literal copy of it: a new environment gets a new id. The comment above
        # the helper quotes the message, so assert on the code that builds the
        # allowlist rather than on the file.
        constants = deployment[
            deployment.index("const CNB_DEV_HOST_SUFFIXES"):
            deployment.index("export function resolveDevAllowedHosts")
        ]
        self.assertNotIn("cnb-38o-1k28dm5ta-001.cnb.space", constants)

        # The reported hostname, and every hostname the platform can mint for
        # the next environment, must be accepted.
        allowlist = _load_dev_allowlist()
        self.assertFalse(allowlist.is_wildcard)
        for host in (
            # The exact hostname from the Issue report, with and without the
            # port the proxy appends.
            "cnb-38o-1k28dm5ta-001.cnb.space",
            "cnb-38o-1k28dm5ta-001.cnb.space:8686",
            # The only-preview form documented in only-preview.md.
            "cnb-38o-1k28dm5ta-001-8686.cnb.space",
            # `*.cnb.run` is the other documented preview domain
            # (business-preview.md: https://<id>-{{port}}.cnb.run).
            "fjisdofi21-5173.cnb.run",
            "cnb.space",
            "cnb.run",
            # Loopback: the readiness wait and any local browser.
            "localhost:5173",
            "localhost",
            "127.0.0.1:8686",
        ):
            self.assertTrue(
                allowlist.accept(host),
                f"the dev server would block {host!r}; the CNB preview would show the "
                "blocked-host page instead of the portal",
            )

        # ...and it must still not be a wildcard: a DNS-rebinding host, a host
        # that merely contains the platform domain, and a look-alike domain are
        # all rejected.
        for host in (
            "evil.example.com",
            "cnb.space.evil.com",
            "evil-cnb.space",
            "notcnb.space",
            "cnb.spacex",
        ):
            self.assertFalse(
                allowlist.accept(host),
                f"the allowlist accepts {host!r}; `allowedHosts` is a security "
                "boundary, not a formality",
            )

        # An operator-provided host is additive, and so is `true` (the
        # documented escape hatch for a tunnel that cannot be enumerated).
        extended = _load_dev_allowlist("staging.example.com, https://tunnel.foo.io:8080/x")
        for host in ("staging.example.com", "tunnel.foo.io", "cnb-38o-1k28dm5ta-001.cnb.space"):
            self.assertTrue(extended.accept(host), host)
        self.assertFalse(extended.accept("other.example.com"))
        self.assertTrue(_load_dev_allowlist("true").accept("anything.example.com"))
        self.assertFalse(_load_dev_allowlist().accept("anything.example.com"))

        # 2. Every Umi dev server uses the shared resolver and never an
        #    unconditional wildcard.
        #
        #    Umi 4 rejects `devServer` as a *top-level* config key ("Invalid
        #    config keys: dynamicImport, devServer"), so the allowlist is applied
        #    through the chainable config: `memo.devServer.set(...)` /
        #    `memo.devServer.allowedHosts.merge(...)`. The assertion is on that
        #    contract rather than on a spelling Umi refuses to load — an earlier
        #    version of this check kept passing against a shape that no longer
        #    built.
        configs = {
            "apps/web/config/config.ts": "resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS)",
            "apps/admin/config/config.ts": "resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS)",
            "apps/jbrowse/config/config.ts": "resolveDevAllowedHosts(env.SOYMUTDB_DEV_ALLOWED_HOSTS)",
        }
        for relative, expected in configs.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(expected, source, relative)
            self.assertIn("chainWebpack", source, relative)
            self.assertIn('memo.devServer.allowedHosts.merge(configuredDevHosts)', source, relative)
            self.assertNotIn("devServer:", source.split("chainWebpack")[0], relative)
            self.assertNotIn("allowedHosts: true", source, relative)
            self.assertNotIn('allowedHosts: "*"', source, relative)
            self.assertNotIn('allowedHosts: ["*"]', source, relative)

            # The `"all"` wildcard is permitted ONLY behind an explicit
            # operator opt-in (`SOYMUTDB_DEV_ALLOWED_HOSTS=true`), which the
            # resolver reports as `is_wildcard`. Assert the guard, not just the
            # absence of a literal: an unconditional wildcard is the
            # DNS-rebinding pivot this whole test exists to prevent.
            wildcard_index = source.find('memo.devServer.set("allowedHosts", "all")')
            if wildcard_index != -1:
                guard_index = source.find("configuredDevHosts === true")
                self.assertNotEqual(
                    guard_index,
                    -1,
                    f"{relative}: an unconditional allowedHosts wildcard",
                )
                self.assertLess(
                    guard_index,
                    wildcard_index,
                    f"{relative}: the wildcard is not inside the opt-in branch",
                )

        # 3. The bootstrap script derives the same variable from the platform.
        script = (ROOT / "scripts/start-cloud-dev.sh").read_text(encoding="utf-8")
        self.assertIn("SOYMUTDB_DEV_ALLOWED_HOSTS", script)
        self.assertIn("CNB_VSCODE_PROXY_URI", script)
        for domain in ("cnb.space", "cnb.run"):
            self.assertIn(domain, script)

        # 4. `dev` and `preview` must BOTH bind all interfaces. Umi dev takes
        #    `--host`; the static preview uses Python's explicit `--bind`.
        for app, port in (("web", 5173), ("admin", 5174), ("jbrowse", 5175)):
            scripts = json.loads(
                (ROOT / f"apps/{app}/package.json").read_text(encoding="utf-8")
            )["scripts"]
            for name in ("dev", "preview"):
                self.assertIn(
                    "0.0.0.0",
                    scripts[name],
                    f"apps/{app}: `{name}` must bind all interfaces so the CNB "
                    "preview proxy can reach it",
                )
                self.assertNotIn("127.0.0.1", scripts[name], f"apps/{app}: {name}")

        # 5. Umi's build config validates deployment origins at load time.
        #    The cloud-development bootstrap must default the required values
        #    before starting the server.
        self.assertIn("VITE_API_BASE_URL", script)
        for origin in ("VITE_API_BASE_URL", "VITE_JBROWSE_BASE_URL", "VITE_DEPLOYMENT_MODE"):
            self.assertIn(
                origin,
                script,
                "the bootstrap must default the origins the config validates",
            )

    def test_cloud_development_frontend_image_prewarms_the_pnpm_store(self) -> None:
        """The build image must ship a warm store through a `VOLUME`.

        CNB shares a path declared with the Docker `VOLUME` instruction between
        the pipeline container and every later container of the same pipeline
        (build-env.md, "Volume 共享"). The image filesystem is NOT what a
        pipeline's `docker.volumes` mount carries, so a store written below
        /cache without a VOLUME declaration is discarded by the very mount that
        is supposed to make it persistent -- and `--frozen-lockfile` then
        re-downloads the whole lockfile on the first run of every environment.

        The warm-up is also why `build.by` has to list the lockfile: a store
        baked from a manifest set that no longer matches `pnpm-lock.yaml` would
        be served as a cache hit forever.
        """
        dockerfile = (ROOT / ".cnb/env/Dockerfile.frontend").read_text(encoding="utf-8")
        self.assertIn("VOLUME /cache/pnpm-store", dockerfile)
        self.assertIn("pnpm config set store-dir /cache/pnpm-store", dockerfile)
        # Fetch the exact package tarballs selected by the lockfile; no
        # installation or node_modules tree is created in the image.
        self.assertIn("pnpm fetch --ignore-scripts", dockerfile)
        # No RUN instruction may perform an install, because the warm store is
        # prepared from the lockfile while setup-workspace owns installation.
        run_lines = "\n".join(
            line for line in dockerfile.splitlines() if line.startswith("RUN ")
        )
        self.assertNotIn("pnpm install", run_lines)
        # The VOLUME must be declared AFTER the warm-up, or the engine copies an
        # empty (not yet created) directory into the share.
        self.assertLess(
            dockerfile.index("pnpm fetch --ignore-scripts"),
            dockerfile.index("VOLUME /cache/pnpm-store"),
            "VOLUME must be declared after the store is populated",
        )
        # A hard-coded pnpm version would let the image warm a store with a
        # pnpm the pipeline never activates.
        self.assertIn(f"ARG PNPM_VERSION={PNPM_VERSION}", dockerfile)
        # The warm-up is only real if the lockfile is IN the image when it runs.
        # Asserting the command while the image had no manifests is what let
        # every remote run die in Prepare with
        #
        #   ERR_PNPM_NO_LOCKFILE
        #
        # so the lockfile and the workspace file must be copied, and copied
        # before the fetch.
        lines = dockerfile.splitlines()
        for required in ("pnpm-lock.yaml", "pnpm-workspace.yaml"):
            self.assertTrue(
                any(line.startswith("COPY ") and required in line for line in lines),
                f"the pnpm warm-up needs {required} inside the image",
            )
        lockfile_copy = next(
            line
            for line in lines
            if line.startswith("COPY ") and "pnpm-lock.yaml" in line
        )
        self.assertLess(
            dockerfile.index(lockfile_copy),
            dockerfile.index("pnpm fetch --ignore-scripts"),
            "pnpm fetch runs before the lockfile is copied into the image",
        )

        document = _cnb()
        frontend_builds = [
            pipeline["docker"]["build"]
            for pipeline in (
                *_cnb_pipelines("main", "pull_request"),
                *_cnb_pipelines("main", "push"),
                *_cnb_pipelines("$", "web_trigger_verify"),
            )
            if pipeline.get("docker", {}).get("build", {}).get("dockerfile")
            == ".cnb/env/Dockerfile.frontend"
        ]
        self.assertEqual(len(frontend_builds), 3, "expected three frontend pipelines")
        for build in frontend_builds:
            self.assertIn(".cnb/env/Dockerfile.frontend", build["by"])
            self.assertIn(
                "pnpm-lock.yaml",
                build["by"],
                "the store warm-up must be rebuilt when the lockfile changes",
            )
            # grammar.md: "未出现在 by 列表中的文件，在构建镜像时不会被 COPY 进
            # 镜像（Dockerfile 本身除外）". A COPY of a path that is missing from
            # `by` therefore dies while resolving the context --
            #
            #   failed to calculate checksum of ref ...: "/.npmrc": not found
            #
            # which is not a missing file in the repository but a missing entry
            # in this list. Keep the two ends from drifting apart.
            declared = set(build["by"])
            copied = [
                token
                for line in lines
                if line.startswith("COPY ")
                for token in line.split()[1:-1]
            ]
            self.assertTrue(copied, "expected the frontend image to COPY its inputs")
            for source in copied:
                self.assertIn(
                    source,
                    declared,
                    f"the frontend image COPYs {source}, but it is absent from "
                    "docker.build.by and so never reaches the build context",
                )

    def test_cloud_development_buttons_share_one_bootstrap(self) -> None:
        """The manual preview pipeline must not fork the environment prep.

        A second entry point that reimplements the launch would be the classic
        way the two drift: the branch button and the manual button would start
        subtly different environments. Both must call the same script with the
        same mode and port.
        """
        document = _cnb()
        vscode_pipeline = document["$"]["vscode"][0]
        manual_pipeline = document["$"]["web_trigger_workspace-preview"][0]

        def launch_and_port(pipeline: dict) -> tuple[str, str]:
            service = next(
                s for s in pipeline["services"] if isinstance(s, dict) and s.get("name") == "vscode"
            )
            return service["options"]["launch"], pipeline["env"]["SOYMUTDB_DEV_WEB_PORT"]

        self.assertEqual(launch_and_port(vscode_pipeline), launch_and_port(manual_pipeline))
        self.assertEqual(
            [stage["script"] for stage in manual_pipeline["stages"]],
            [stage["script"] for stage in vscode_pipeline["stages"]],
        )

    def test_development_data_layer_environment_satisfies_compose(self) -> None:
        """`docker compose` interpolates the whole file, not the services named.

        `docker-compose.yml` is the production topology and fails fast on
        `${POSTGRES_PASSWORD:?…}` /
        `${REDIS_PASSWORD:?…}` / `${MINIO_ROOT_USER:?…}` /
        `${MINIO_ROOT_PASSWORD:?…}`. Compose resolves those before it selects
        services, so on a cloud-development environment -- which has no release
        `.env` -- even `up -d postgres` aborts during interpolation:

          error while interpolating x-app-env.SOYMUTDB_S3_ACCESS_KEY:
            required variable MINIO_ROOT_USER is missing a value

        `start-cloud-dev.sh` reaches that state on its FIRST compose call, which
        makes the whole preview pipeline fail in Prepare ("Preview launch script
        execution failed"). The variables therefore have to exist before any
        compose invocation, and there is exactly one place both CNB entry points
        and a local run pass through: scripts/setup-workspace.sh.
        """
        required = (
            "POSTGRES_PASSWORD",
            "REDIS_PASSWORD",
            "MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD",
        )

        # 1. The base compose file keeps its fail-fast posture. A default here
        #    would silently weaken production; the defaults belong in the
        #    development bootstrap instead.
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        for variable in required:
            self.assertIn(
                f"${{{variable}:?",
                compose,
                f"docker-compose.yml must keep ${variable} required",
            )

        # 2. The overlay is where the fix has to live, because
        #    `start-cloud-dev.sh` runs this script as a CHILD PROCESS: an
        #    `export` below never reaches the data-layer `docker compose` call in
        #    the parent. Measured on the fix that only touched this script
        #    (PR #14), the compose call still saw all five variables unset.
        overlay = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
        # `!reset` is the only form that takes the base file's `${…:?…}`
        # references off the merge's default branch; an anchor merge leaves them
        # there and Compose interpolates them anyway.
        self.assertIn("x-app-env: !reset", overlay)
        # The base healthcheck reads `${REDIS_PASSWORD:?…}`, and a service-level
        # `environment:` entry is not visible to interpolation, so the overlay
        # has to replace the healthcheck itself.
        redis_section = overlay.split("\n  redis:\n", 1)[1].split("\n  redis-celery:\n", 1)[0]
        effective = "\n".join(
            line for line in redis_section.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("${REDIS_PASSWORD:?", effective)
        self.assertIn("redis-cli -a soymutdb_dev_password ping", overlay)

        # The parent-process check: the data layer must NOT be reachable only
        # through a subprocess `export`.
        start_script = (ROOT / "scripts/start-cloud-dev.sh").read_text(encoding="utf-8")
        self.assertIn("--env-file /dev/null", start_script)
        self.assertRegex(
            start_script,
            r"set_default POSTGRES_PASSWORD",
            "start-cloud-dev.sh must default the compose variables in its OWN "
            "process; a subprocess `export` cannot reach the data-layer compose "
            "call",
        )

        # 3. The bootstrap declares every one of them, and only when unset, so a
        #    caller-provided value (the GitHub mirror's ci-compose-* secrets, an
        #    operator's real ones) stays authoritative. This is a convenience
        #    for the other callers of the workspace, NOT the preview's fix --
        #    point 2 above is.
        script = (ROOT / "scripts/setup-workspace.sh").read_text(encoding="utf-8")
        for variable in required:
            self.assertRegex(
                script,
                rf': "\$\{{{variable}:=[^}}]+\}}"',
                f"setup-workspace.sh must default {variable} for the data layer",
            )
        # A plain assignment would override a caller's value and silently pin a
        # development password onto a real deployment.
        for variable in required:
            self.assertNotRegex(
                script,
                rf"^\s*{variable}=",
                f"setup-workspace.sh must not override an exported {variable}",
            )
        self.assertIn('export POSTGRES_PASSWORD', script)

        # 4. It must NOT run for an image build. Those pipelines are the release
        #    path, where the daemon is never started and defaulting a production
        #    secret is the opposite of fail-fast; they declare no data volume.
        guard = script.index('if [[ -z "${POSTGRES_PASSWORD:-}" ]]')
        self.assertLess(
            guard,
            script.index(': "${POSTGRES_PASSWORD:='),
            "the caller-provided check must come first",
        )
        self.assertIn("POSTGRES_PASSWORD", script[guard:])

        # 5. `start-cloud-dev.sh` must reach the bootstrap before its first
        #    compose call, for every mode that touches the data layer.
        start = (ROOT / "scripts/start-cloud-dev.sh").read_text(encoding="utf-8")
        self.assertLess(
            start.index("setup-workspace.sh"),
            start.index("compose_cmd()"),
            "the compose variables must exist before the first compose call",
        )

    def test_image_build_compose_gate_supplies_every_required_variable(self) -> None:
        """The CI compose gate must interpolate the production file with no .env.

        `docker compose config` resolves every `${VAR:?}` in the file before it
        selects a profile's services, so the image-build gate aborted before
        building a single image:

          error while interpolating x-app-env.SOYMUTDB_REDIS_URL:
            required variable REDIS_PASSWORD is missing a value

        The gate must supply a validation-only placeholder for every required
        variable; otherwise a new `${VAR:?}` silently breaks the image build.
        """
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        required = sorted(set(re.findall(r"\$\{([A-Z0-9_]+):\?", compose)))
        self.assertTrue(required, "docker-compose.yml declares no required variables")

        jobs = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn("compose_acceptance_run()", jobs)
        body = jobs.split("compose_acceptance_run()", 1)[1].split("\n}", 1)[0]
        missing = [name for name in required if name not in body]
        self.assertEqual(
            [],
            missing,
            "compose-acceptance does not supply placeholders for: " + ", ".join(missing),
        )

    def test_clickhouse_migration_provisions_its_python_dependency(self) -> None:
        """CNB and GitHub must install clickhouse-connect the same way.

        The GitHub job used to `pip install clickhouse-connect` inline while the
        CNB job did not, so only CNB reached:

          clickhouse-connect is required for ClickHouse migration

        The install now lives in the shared body so both providers provision the
        same dependency, and the workflow no longer inlines it.
        """
        jobs = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        self.assertIn("clickhouse_migration_run()", jobs)
        body = jobs.split("clickhouse_migration_run()", 1)[1].split("\n}", 1)[0]
        self.assertIn("clickhouse_connect", body, "the migration body must check for the client")
        self.assertIn(
            "pip install",
            body,
            "the migration body must install clickhouse-connect when it is missing",
        )

        ci = _workflow_text("ci.yml")
        self.assertNotIn(
            "pip install --quiet clickhouse-connect",
            ci,
            "the dependency belongs in the shared script, not inlined in the workflow",
        )

    def test_clickhouse_migration_keeps_its_own_python_314(self) -> None:
        """The legacy ClickHouse lane stays below the 3.15 floor, on purpose.

        Every native service moved to 3.15, and clickhouse-connect moved with
        them -- out of [project].dependencies and into a 'legacy-clickhouse'
        extra whose marker is python_version < 3.15, because upstream 1.10
        declares requires-python >=3.10,<3.15 and publishes no 3.15 release.
        The migration lane still needs that driver: the migration library
        imports it and scripts/assert-clickhouse-migration.py asserts
        through it.

        So the lane keeps one interpreter of its own, and this test guards two
        silent failures: the stage image following the pipeline to 3.15, where
        pip can only report 'no matching distribution' for the driver; and the
        shared body losing the assertion that turns that into a clear message.
        """
        CH_JOB = "clickhouse-migration"
        CH_VERSION = "3.14"
        dollar = chr(36)  # the pin lives inside a bash parameter expansion

        shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        body = shared.split("clickhouse_migration_run()", 1)[1].split(chr(10) + "}", 1)[0]
        self.assertIn(
            "CLICKHOUSE_MIGRATION_PYTHON_VERSION",
            body,
            "the migration body must pin and verify its own interpreter version",
        )
        self.assertIn(
            "SOYMUTDB_CLICKHOUSE_MIGRATION_PYTHON_VERSION:-" + CH_VERSION,
            body,
            "the legacy ClickHouse lane must default to Python " + CH_VERSION,
        )
        self.assertIn(
            "version_info",
            body,
            "the migration body must compare sys.version_info against that pin, "
            "not merely find an interpreter",
        )
        self.assertIn(
            'PYTHON_VERSION="'
            + dollar
            + "{SOYMUTDB_CI_PYTHON_VERSION:-"
            + PYTHON_VERSION
            + '}"',
            shared,
        )
        self.assertNotEqual(
            CH_VERSION,
            PYTHON_VERSION,
            "if clickhouse-connect ever ships 3.15 wheels, move the lane with it "
            "instead of leaving this test asserting a split that no longer exists",
        )

        cnb = yaml.safe_load((ROOT / ".cnb.yml").read_text(encoding="utf-8"))
        pipeline = next(job for job in cnb["main"]["push"] if job["name"] == CH_JOB)
        images = [stage.get("image") for stage in pipeline["stages"]]
        self.assertEqual(
            images,
            ["python:" + CH_VERSION],
            "the ClickHouse migration stage must stay on python:" + CH_VERSION,
        )

        ci = yaml.safe_load(_workflow_text("ci.yml"))
        job = ci["jobs"][CH_JOB]
        setup = next(
            step for step in job["steps"] if step.get("name", "").startswith("Setup Python")
        )
        self.assertEqual(
            str(setup["with"]["python-version"]),
            CH_VERSION,
            "the ClickHouse migration job must set up Python " + CH_VERSION,
        )
        self.assertEqual(
            job["env"].get("CLICKHOUSE_MIGRATION_PYTHON"),
            "python",
            "the assertion target must be the interpreter the job installs",
        )

        dockerfile = (ROOT / "infra/docker/Dockerfile.migrate-clickhouse").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "FROM python:3.14.6-slim",
            dockerfile,
            "the migrator image is the other half of this lane and stays on 3.14",
        )

    def test_setup_workspace_declares_helpers_before_it_calls_them(self) -> None:
        """Step 0 runs before any helper declared below it.

        The compose-variable step above was added at the top of the script, but
        `log()` was still declared further down. `set -u` does not catch an
        undefined *command*, so bash reported:

          scripts/setup-workspace.sh: line 122: log: command not found  (exit 127)

        and every stage that bootstraps the workspace died in its first
        millisecond -- the whole Frontend/API/Worker fan-out. Assert the
        ordering statically so the next helper moved above its definition is
        caught by `python3 -m unittest` instead of by a red build.
        """
        script = (ROOT / "scripts/setup-workspace.sh").read_text(encoding="utf-8")
        definition = script.index('log() {')
        first_call = script.index('log "compose interpolation variables')
        self.assertLess(
            definition,
            first_call,
            "log() must be declared before step 0 calls it",
        )

        # Same rule for every other locally declared function: its definition
        # must precede its first invocation.
        for name in ("log",):
            call = re.search(rf"(?m)^\s*(?!#).*(?<!\w){name} \"", script)
            if call is not None:
                self.assertLess(
                    definition,
                    call.start(),
                    f"{name}() is called before it is defined",
                )

    def test_start_cloud_dev_binds_services_to_all_interfaces(self) -> None:
        """A service on localhost is unreachable from CNB's preview proxy.

        This is the single most likely "the environment started but the preview
        is blank" bug, and it is invisible locally (a local browser CAN reach
        loopback). Pin the 0.0.0.0 binding and the readiness wait that turns a
        crash-on-start into a reported failure.
        """
        script = (ROOT / "scripts/start-cloud-dev.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", script)
        self.assertIn("VITE_HOST", script)
        self.assertIn("0.0.0.0", script)
        # The preview must not be reported as started before it can be reached.
        self.assertIn("/dev/tcp/127.0.0.1/", script)
        # Missing prerequisites must be actionable, not a stack trace.
        self.assertIn("SOYMUTDB_DATABASE_URL", script)
        # It must not carry credentials or secrets of its own.
        self.assertNotIn("CNB_TOKEN", script)

    def test_acceptance_pipeline_reports_per_layer_and_uploads_evidence(self) -> None:
        document = _cnb()
        pipeline = document["$"]["web_trigger_acceptance"][0]

        scripts = [stage.get("script", "") for stage in pipeline["stages"]]
        self.assertEqual(
            scripts,
            [
                "bash scripts/acceptance.sh --profile contracts",
                "bash scripts/acceptance.sh --profile backend",
                "bash scripts/acceptance.sh --profile static",
            ],
        )

        # PostgreSQL integration is mandatory for the backend layer: the
        # privacy/identity/assembly matrix must fail closed, not skip green.
        self.assertEqual(pipeline["env"]["SOYMUTDB_RUN_POSTGRES_INTEGRATION"], "1")
        # `services` is a PIPELINE-level key, not a stage key: a stage-level
        # `services:` is silently dropped and the dind daemon never starts.
        self.assertIn("docker", pipeline["services"])
        self.assertNotIn("postgres:16", pipeline["services"])
        for stage in pipeline["stages"]:
            self.assertNotIn(
                "services",
                stage,
                "`services` is a pipeline key; on a stage it is ignored",
            )
        self.assertIn(
            "pnpm-store",
            " ".join(str(v) for v in pipeline["docker"]["volumes"]),
        )

        # Evidence is uploaded even when a layer fails, so a failed acceptance
        # still leaves the per-layer verdicts for review.
        self.assertTrue(pipeline["endStages"], "acceptance must upload evidence")
        self.assertIn("artifacts/acceptance", _flatten(pipeline["endStages"]))

        # Acceptance must never publish or hold release credentials: it runs on
        # feature branches and on Issue-driven NPC tasks.
        text = _flatten(pipeline)
        for forbidden in ("docker login", "docker push", "cosign"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_postgres_backed_stages_declare_a_real_service_and_resolve_a_database(self) -> None:
        """The PostgreSQL gate must depend on a service CNB actually starts.

        Regression for the first real CNB build of the api-tests stage
        (cnb-ubo-1k2852ukb). The stage declared:

            services:
              - postgres:16

        CNB accepted the declaration and started NOTHING. Measured in a probe
        build on the same runner (cnb-j0g-1k285hm3b):

            CLOSED postgres 5432 [Errno -2] Name or service not known
            CLOSED 127.0.0.1 5432 [Errno 111] Connection refused
            /var/run/docker.sock missing

        `services` only implements `docker` and `vscode`, so any other name is
        a silent no-op. The suite therefore fell through to Testcontainers and
        every database-backed test errored with a docker stack trace:

            docker.errors.DockerException: Error while fetching server API
            version: ('Connection aborted.', FileNotFoundError(2, ...))

        ...116 ERRORS that read as 116 product failures. The fix is a service
        the platform does start (`docker`) plus a resolver that fails closed.
        """
        forbidden = {"postgres", "postgresql", "mysql", "mariadb", "redis", "mongo"}

        database_stages: list[tuple[str, dict]] = []
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                for stage in pipeline.get("stages", []) or []:
                    if not isinstance(stage, dict):
                        continue
                    body = _flatten(stage)
                    if "api-tests" not in body and "--profile backend" not in body:
                        continue
                    database_stages.append((config.name, pipeline))

                    # `services` is a PIPELINE-level key (docs.cnb.cool
                    # grammar.md#pipeline-services: siblings of `stages`,
                    # `docker`, `env`). Declaring it inside a Stage is silently
                    # ignored: the stage then has no dind daemon and no docker
                    # CLI, which is exactly the observed failure
                    #   [postgres-service] docker CLI is unavailable:
                    #   this stage must declare `services: [docker]`
                    # on the real build cnb-m06-1k28813m9. Assert on the
                    # pipeline, never on the stage.
                    services = pipeline.get("services") or []
                    names = {
                        entry if isinstance(entry, str) else entry.get("name")
                        for entry in services
                    }
                    self.assertNotIn(
                        forbidden,
                        names,
                        f"{config.name}: `services:` only implements docker and "
                        "vscode; a database name here is accepted and starts "
                        "nothing",
                    )
                    self.assertIn(
                        "docker",
                        names,
                        f"{config.name}: the PostgreSQL gate needs the pipeline "
                        "to declare `services: [docker]` so it can start a "
                        "database through the dind daemon",
                    )
                    # And it must NOT be misplaced on the stage: a stage-level
                    # `services` is not in the Stage schema and is dropped.
                    for stage in pipeline.get("stages", []) or []:
                        if not isinstance(stage, dict) or "stages" in stage:
                            continue
                        self.assertNotIn(
                            "services",
                            stage,
                            f"{config.name}/{stage.get('name')}: `services` "
                            "is a pipeline key; on a stage it is silently "
                            "ignored and the dind daemon never starts",
                        )

        self.assertTrue(
            database_stages,
            "no pipeline stage runs the PostgreSQL-backed gate; the privacy, "
            "identity and assembly matrix would never execute",
        )
        # The same misplaced-key hazard applies to every pipeline in the
        # repository, not just the database gate: `services` on a Stage is
        # always a no-op, so forbid it everywhere and keep the fix from
        # regressing one file at a time.
        for config in _cnb_config_files():
            document = yaml.safe_load(config.read_text(encoding="utf-8"))
            for pipeline in _iter_pipelines(document):
                for stage in pipeline.get("stages", []) or []:
                    if not isinstance(stage, dict):
                        continue
                    # A stage MAY be a whole nested pipeline (`stages:` inside
                    # the stage). That inner object is a pipeline, so its own
                    # `services:` is legal pipeline configuration -- `.cnb.yml`
                    # uses this shape for the per-architecture image builds.
                    if "stages" in stage:
                        continue
                    if "services" in stage:
                        self.fail(
                            f"{config.name}/{stage.get('name')}: `services` is "
                            "a pipeline-level key; declaring it on a stage is "
                            "silently ignored"
                        )

        # The resolver itself must stay fail-closed and driver-accurate.
        resolver = (ROOT / "scripts/with-postgres-service.sh").read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", resolver)
        # An explicit caller-provided database is honoured, so local runs and
        # the GitHub runner (where Testcontainers works) are unaffected.
        self.assertIn("SOYMUTDB_TEST_DATABASE_URL", resolver)
        marker = 'if [[ -n "${SOYMUTDB_TEST_DATABASE_URL:-}" ]]'
        self.assertIn(
            marker,
            resolver,
            "an explicitly provided database must short-circuit the bootstrap",
        )
        # Readiness must be proven with the suite's own driver: the vendor
        # image serves `pg_isready` from a temporary socket during initdb, so a
        # TCP-level check alone reports a healthy server as unusable.
        self.assertIn("asyncpg.connect", resolver)
        self.assertIn("pg_isready", resolver)
        # It must never fall back to "skip because there is no database".
        for skip in ("pytest.skip", "SKIPPED", "exit 0 #"):
            self.assertNotIn(skip, resolver, skip)

        # The gate consumes the resolver's output without `source`, because a
        # CNB stage body runs under `sh` where `source` does not exist.
        backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")
        for marker in (
            "with-postgres-service.sh",
            "--print-exports",
            "export SOYMUTDB_RUN_POSTGRES_INTEGRATION=1",
            # The worker suite reuses a fixture by package path, and a broken
            # import aborts collection for the whole run. This must stay a hard
            # step *before* the worker install so it fails fast and cheaply.
            "scripts/check_worker_test_package.py",
        ):
            self.assertIn(marker, backend, marker)
        self.assertNotIn("source \"${PG_ENV_FILE}\"", backend)

        # `--ensure` must write a POSIX `KEY=VALUE` file, not shell `export`
        # lines, for the same reason.
        self.assertNotIn("printf 'export SOYMUTDB_TEST_DATABASE_URL", resolver)

    def test_worker_science_build_deps_are_provisioned_before_the_worker_install(self) -> None:
        """Python 3.15 has no h5py wheel: the backend gate must install HDF5 first.

        Regression for real CNB build cnb-7cn-1k6gvafcf. The `api-tests` stage
        runs on a bare `python:3.15` image. `verify-backend-tests.sh` editable-
        installs `apps/worker[dev]`, which pulls scanpy -> anndata -> h5py;
        h5py 3.16 has no cp315 wheel, so pip builds it from sdist and needs
        system HDF5 headers. The image has none, so the stage died with:

            error: libhdf5.so: cannot open shared object file: No such file
            ERROR: Failed building wheel for h5py

        The production image (infra/docker/Dockerfile.worker) already solves
        this with `libhdf5-dev` + `pkg-config` and HDF5_PKGCONFIG_NAME pointing
        at Debian/Ubuntu's serial flavour. The CI gate must apply the same
        recipe BEFORE the worker install, and both providers reach it through
        this one script so the prerequisite cannot drift.
        """
        backend = (ROOT / "scripts/verify-backend-tests.sh").read_text(encoding="utf-8")
        prereq = (ROOT / "scripts/install-worker-science-build-deps.sh").read_text(
            encoding="utf-8"
        )
        dockerfile = (ROOT / "infra/docker/Dockerfile.worker").read_text(encoding="utf-8")

        # The gate must provision the system deps and set the pkg-config name
        # before running the worker editable install.
        self.assertIn("scripts/install-worker-science-build-deps.sh", backend)
        self.assertIn("export HDF5_PKGCONFIG_NAME=", backend)
        self.assertIn("hdf5-serial", backend)
        self.assertLess(
            backend.index("install-worker-science-build-deps.sh"),
            backend.index('"apps/worker[dev]"'),
            "HDF5 prerequisites must be installed BEFORE pip builds h5py",
        )

        # Same package names and pkg-config flavour as the production image.
        # The full recipe matters: `uv run --locked` in the governance gate
        # builds h5py/cyvcf2/pandas/numcodecs from sdists, so it needs the C
        # toolchain, HDF5 and htslib's compression headers too, not just the
        # two packages the pip-based backend gate needs.
        for package in (
            "build-essential",
            "libhdf5-dev",
            "pkg-config",
            "zlib1g-dev",
            "libbz2-dev",
            "liblzma-dev",
        ):
            self.assertIn(package, prereq, package)
            self.assertIn(package, dockerfile, package)
        # cyvcf2's bundled htslib runs `autoreconf -i` at build time, which
        # `uv run --locked` reaches but the pip-based backend gate does not;
        # these are CI-only prerequisites, so they live in the script alone.
        for package in ("autoconf", "automake", "libtool"):
            self.assertIn(package, prereq, package)
        self.assertIn("HDF5_PKGCONFIG_NAME=hdf5-serial", dockerfile)

        # Every CNB stage is a fresh container, so the governance stage cannot
        # inherit the backend stage's apt installs. It must provision the same
        # prerequisites for its own `uv run` license/pip-audit analyzers.
        steps = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        start = steps.index("dependency_governance_step() {")
        governance = steps[start : steps.index("\n}\n", start)]
        self.assertIn(
            "scripts/install-worker-science-build-deps.sh", governance,
            "the governance stage must provision worker science build deps",
        )
        self.assertIn("export HDF5_PKGCONFIG_NAME=", governance)

        # The prerequisite script is a real, strict, executable shared script.
        self.assertIn("set -euo pipefail", prereq)
        self.assertIn(
            "scripts/install-worker-science-build-deps.sh",
            SHARED_SCRIPTS,
            "register the prerequisite script so the shared-script gates cover it",
        )

    def test_dependency_governance_provisions_hdf5_before_the_worker_license_probe(self) -> None:
        """The governance license analyzer resolves the worker runtime too.

        Real CNB build cnb-9gi-1k6h3mikv failed Dependency governance with
        `python-licenses-worker: failed (normalization_unavailable:license-expressions)`.
        `uv run --locked --project apps/worker --with pip-licenses` builds h5py
        3.16 from its sdist on Python 3.15 (scanpy -> anndata -> h5py), so it
        needs the same system HDF5 headers + pkg-config the backend gate already
        installs. Without them pip-licenses crashes before writing a report and
        the fail-closed gate has nothing to normalize. The governance stage must
        provision them through the shared script BEFORE `pnpm deps:audit` runs,
        and both providers reach it through this one job body.
        """
        shared = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        step = shared[shared.index("dependency_governance_step() {") :]
        step = step[: step.index("\ndependency_governance_run()")]

        self.assertIn("export HDF5_PKGCONFIG_NAME=", step)
        self.assertIn("hdf5-serial", step)
        self.assertIn("scripts/install-worker-science-build-deps.sh", step)
        self.assertIn("pnpm deps:audit", step)
        self.assertLess(
            step.index("install-worker-science-build-deps.sh"),
            step.index("pnpm deps:audit"),
            "HDF5 prerequisites must be installed BEFORE the worker license probe",
        )

    def test_acceptance_entry_point_never_reports_a_missing_prerequisite_as_a_pass(self) -> None:
        """The acceptance/smoke difference is deliberate and must stay visible.

        scripts/smoke.sh reports `SKIPPED` for a missing prerequisite because it
        is a developer tool: it runs what is possible locally. Acceptance must
        do the opposite for a required layer — on the platform the prerequisite
        is a property of the pipeline definition, so its absence is a failure to
        fix there, not a layer to be waved through. This test pins both halves so
        neither entry point silently adopts the other's posture.
        """
        acceptance = (ROOT / "scripts/acceptance.sh").read_text(encoding="utf-8")
        self.assertIn("block_layer", acceptance)
        self.assertIn("BLOCKED", acceptance)
        self.assertIn("ACCEPTANCE PASS", acceptance)
        self.assertIn("ACCEPTANCE FAIL", acceptance)
        # A blocked layer must fail the profile.
        exit_guard = acceptance.index("ACCEPTANCE FAIL")
        self.assertIn("#BLOCKED[@]}", acceptance[:exit_guard][-400:])

        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        self.assertIn("skip_layer", smoke)
        self.assertIn("SKIPPED", smoke)

        # The acceptance profiles must cover the layers the pipeline uses, and
        # the list must match the dispatched cases.
        catalog = subprocess.run(
            ["bash", "scripts/acceptance.sh", "--list"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        profiles = set(catalog.stdout.split())
        self.assertLessEqual({"contracts", "static", "runtime", "e2e", "images", "backend", "full"}, profiles)

        # `profile` names in the usage/`--list` must be dispatchable, exactly as
        # for scripts/ci-job-steps.sh: a documented profile that no `case` arm
        # handles would silently accept nothing.
        dispatch = set(re.findall(r"^\s+(\w+)\)$", acceptance, re.M))
        self.assertLessEqual({"contracts", "static", "runtime", "e2e", "images", "backend"}, dispatch)

    def test_startup_and_acceptance_are_documented_and_reachable_from_the_package(self) -> None:
        """A platform entry point nobody can find is not an entry point."""
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        scripts = package["scripts"]
        self.assertEqual(scripts["accept"], "bash scripts/acceptance.sh")
        self.assertEqual(scripts["dev:cloud"], "bash scripts/start-cloud-dev.sh")

        doc = ROOT / "docs/ops/cnb-startup-acceptance.md"
        self.assertTrue(doc.is_file(), "missing docs/ops/cnb-startup-acceptance.md")
        text = doc.read_text(encoding="utf-8")
        for marker in (
            "start-cloud-dev.sh",
            "acceptance.sh",
            ".cnb/settings.yml",
            "web_trigger_acceptance",
            "8686",
        ):
            self.assertIn(marker, text, marker)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("cnb-startup-acceptance.md", readme)

        # The settings file that customises the launch button must be committed,
        # not merely present: `.gitignore` once swallowed .cnb/env/ the same way.
        settings = ".cnb/settings.yml"
        self.assertTrue((ROOT / settings).is_file(), settings)
        ignored = subprocess.run(
            ["git", "check-ignore", "--quiet", settings], cwd=ROOT, capture_output=True
        )
        self.assertNotEqual(ignored.returncode, 0, f"{settings} is ignored by .gitignore")
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--error-unmatch", settings],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(tracked.returncode, 0, f"{settings} is present but not tracked by git")

    def test_release_contract_is_provider_agnostic(self) -> None:
        golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
        # Registry namespace, source identity and pipeline id come from the
        # environment so the same script runs under either provider.
        self.assertIn("RELEASE_REGISTRY_OWNER", golden)
        self.assertIn("SOURCE_REPOSITORY", golden)
        self.assertIn("SOURCE_REVISION", golden)
        self.assertIn("SOURCE_PIPELINE", golden)
        self.assertIn("CNB_DOCKER_REGISTRY", golden)
        self.assertNotIn("github.repository_owner", golden)
        self.assertRegex(golden, re.compile(r"CNB_TOKEN"))


class ArchivedPipelineMirrorTests(unittest.TestCase):
    """`.cnb/pipelines/release.yml` must mirror the release pipeline.

    The archived files are the reviewable record of what each pipeline runs, so
    a reviewer reading `release.yml` must see the same stages `.cnb.yml`
    executes. Only `verify.yml` was ever compared, and `release.yml` is the one
    a release reviewer opens, so it gets the same treatment here.
    """

    def _release_documents(self) -> tuple[dict, dict]:
        # The publisher is declared under the `main` GLOB key, not under `$`:
        # `cnb:await` only pairs with a `cnb:resolve` of the SAME event, and the
        # image pipelines that resolve the key are started by `main` -> `push`.
        root = next(
            pipeline
            for pipeline in _cnb_pipelines("main", "push")
            if pipeline["name"] == "release"
        )
        archived = yaml.safe_load(
            (ROOT / ".cnb/pipelines/release.yml").read_text(encoding="utf-8")
        )
        return root, archived

    def test_release_pipeline_file_mirrors_the_root_config(self) -> None:
        root, archived = self._release_documents()

        def _stage_map(pipeline: dict, key: str = "stages") -> dict[str, str]:
            mapped: dict[str, str] = {}
            for stage in pipeline.get(key, []) or []:
                if not isinstance(stage, dict) or "name" not in stage:
                    continue
                if stage.get("type"):
                    body = f"{stage['type']}:{stage['options'].get('key')}"
                else:
                    body = str(
                        stage.get("script")
                        or _flatten(stage.get("settings") or {})
                    )
                mapped[str(stage["name"])] = body
            return mapped

        # `.cnb.yml` splits the terminal upload into `endStages`; the archived
        # pipeline (and the provider-neutral pipeline file convention) lists it
        # as a final stage. Compare the concatenation, and compare the two
        # ordered lists separately.
        root_stages = _stage_map(root)
        archived_stages = _stage_map(archived)
        root_end = _stage_map(root, "endStages")
        self.assertEqual(
            list(root_stages) + list(root_end),
            list(archived_stages),
            "the archived release pipeline runs a different stage list than .cnb.yml",
        )
        # Acceptance criterion: the archived file must name the same delegated
        # job, whichever indirection the copy uses. `.cnb.yml` goes through the
        # shared job entrypoint, the archived file calls the golden script the
        # entrypoint forwards to; both are the one implementation.
        delegations = {
            "bash scripts/ci-job-steps.sh run release": "release",
            "bash scripts/release-contract.golden.sh": "release",
        }
        for name, body in {**root_stages, **root_end}.items():
            expected = delegations.get(body, body)
            actual = delegations.get(archived_stages[name], archived_stages[name])
            self.assertEqual(
                expected, actual, f"archived release stage {name!r} is stale"
            )

        # The start gates are the part most likely to be dropped when someone
        # edits one copy: both architecture waits must be present and first.
        for pipeline in (root, archived):
            stages = pipeline["stages"]
            self.assertEqual(
                ["cnb:await", "cnb:await"],
                [stage.get("type") for stage in stages[:2]],
            )
            self.assertEqual(
                ["validated-runtime-images-amd64", "validated-runtime-images-arm64"],
                [stage["options"]["key"] for stage in stages[:2]],
            )

        # The pipeline holding the registry credentials is the one that fetches
        # and signs, and it is the only place the artifact plugin may appear.
        self.assertIn("cnbcool/artifact", _flatten(root))
        self.assertNotIn("cnbcool/attachments", _flatten(root))


class ReleasePublisherTests(unittest.TestCase):
    """The publisher must be able to obtain the packages it verifies.

    Regression for a release that could never run on CNB. `docker-images (amd64)`
    and `docker-images (arm64)` are separate pipelines on separate native
    runners; the publisher is a third one. The GitHub mirror bridges that with
    an explicit `actions/download-artifact`, the CNB release pipeline had no
    equivalent, so a real release died at the first step:

      ==> Verify and load both platform packages
      missing validated package for amd64: validated-platforms/validated-runtime-images-amd64

    These contracts pin the four things that fix requires: the fetch exists, it
    is fail-closed for BOTH architectures, it never uses a credential-free
    pipeline, and the release cannot start before the packages do.
    """

    def _release_pipeline(self) -> dict:
        # Declared under `main`, the branch whose `push` also starts the image
        # pipelines this one awaits; see `_release_documents`.
        pipelines = [
            pipeline
            for pipeline in _cnb_pipelines("main", "push")
            if pipeline["name"] == "release"
        ]
        self.assertEqual(1, len(pipelines), "expected exactly one release pipeline")
        return pipelines[0]

    def test_publisher_fetches_the_packages_it_verifies(self) -> None:
        golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")

        # Section 0 exists and runs before any verification.
        self.assertIn("materialize_platform_packages", golden)
        self.assertLess(
            golden.index("materialize_platform_packages\n"),
            golden.index("Verify and load both platform packages"),
        )

        # It uses the plugin the platform documents for CI artifacts.
        self.assertIn("cnbcool/attachments", golden)
        self.assertIn("PLUGIN_TYPE=DOWNLOAD", golden)
        # ...and both architectures, never a single one discovered at runtime.
        self.assertRegex(golden, re.compile(r"RUNTIME_PACKAGE_ARCHES=\(amd64 arm64\)"))

        # Fail-closed: a package that does not materialize aborts the run.
        self.assertIn("failed to fetch the", golden)
        self.assertNotIn("continue", golden.split("fetch_platform_package")[1][:2000])

        # The verify pipelines stay credential-free; the fetch lives here.
        for pipeline in _cnb_pipelines("main", "pull_request"):
            self.assertNotIn("cnbcool/attachments", _flatten(pipeline))

    def test_platform_packages_must_describe_one_revision(self) -> None:
        golden = (ROOT / "scripts/release-contract.golden.sh").read_text(encoding="utf-8")
        verification = (ROOT / "scripts/build-release-image.sh").read_text(encoding="utf-8")

        # The verify pipeline records the revision it built from...
        self.assertIn("revision.txt", verification)
        self.assertIn("source-event.txt", verification)
        self.assertIn("SOURCE_REVISION", verification)
        self.assertIn("SOURCE_EVENT", verification)
        # ...and checksums it with the rest of the package.
        export_step = verification[verification.index("Export validated runtime images") :]
        self.assertIn("revision.txt", export_step[export_step.index("sha256sum") :])
        self.assertIn("source-event.txt", export_step[export_step.index("sha256sum") :])

        # The publisher compares both packages against each other and against
        # the revision the contract records: verified bytes from two different
        # builds would describe no single revision, so the provenance the
        # release signs would be false.
        self.assertIn("revision.txt", golden)
        self.assertIn("source-event.txt", golden)
        self.assertIn("platform packages disagree on the revision", golden)
        self.assertIn("platform packages disagree on the source event", golden)
        self.assertIn("but this release records", golden)

        # Both verify pipelines stamp the same variable the publisher reads.
        for name in ("docker-images (amd64)", "docker-images (arm64)"):
            pipeline = next(
                pipeline
                for pipeline in _cnb_pipelines("main", "push")
                if pipeline["name"] == name
            )
            self.assertIn("SOURCE_REVISION", pipeline.get("env", {}), name)
            self.assertIn("SOURCE_EVENT", pipeline.get("env", {}), name)

    def test_release_starts_only_after_the_verified_packages_exist(self) -> None:
        """Every pipeline of a `main` push starts at once; the release must not.

        The packages arrive as uploaded artifacts, so "the release pipeline runs
        after the image pipelines" is not automatic: without an explicit order
        the publisher races the builds it consumes.
        """
        release = self._release_pipeline()

        await_jobs = [
            stage
            for stage in release["stages"]
            if stage.get("type") == "cnb:await"
        ]
        self.assertEqual(2, len(await_jobs), "the release must await both image pipelines")
        self.assertEqual(
            ["validated-runtime-images-amd64", "validated-runtime-images-arm64"],
            [stage["options"]["key"] for stage in await_jobs],
        )
        # Both gates must precede publishing: waiting after publishing is useless.
        self.assertEqual(await_jobs, release["stages"][:2])

        # Each matching resolve is its verify pipeline's LAST job, so it fires
        # only once that architecture's images exist and are exported.
        for arch in ("amd64", "arm64"):
            verify = next(
                pipeline
                for pipeline in _cnb_pipelines("main", "push")
                if pipeline["name"] == f"docker-images ({arch})"
            )
            resolves = [
                stage for stage in verify["stages"] if stage.get("type") == "cnb:resolve"
            ]
            self.assertEqual(1, len(resolves), f"the {arch} image pipeline must hand off")
            self.assertEqual(
                f"validated-runtime-images-{arch}", resolves[0]["options"]["key"]
            )
            self.assertIs(resolves[0], verify["stages"][-1])

        # `cnb:await` / `cnb:resolve` only pair between pipelines of the SAME
        # event, so the publisher must be declared in the branch key that also
        # starts the image pipelines -- `main`, to which `docker-images (amd64)`
        # belongs. Declaring the pairing as a pipeline `resources:` key does not
        # work: CNB's pipeline schema has no such field, so it is rejected in
        # Prepare rather than honoured.
        self.assertIn(
            "release",
            _pipeline_names("main", "push"),
            "the publisher must share the image pipelines' event",
        )
        # A pipeline-level `resources:` field is not part of the CNB grammar.
        for branch, event in (
            ("main", "push"),
            ("$", "push"),
            ("$", "tag_push"),
            ("$", "web_trigger_release"),
        ):
            for pipeline in _cnb_pipelines(branch, event):
                self.assertNotIn(
                    "resources",
                    pipeline,
                    f"{pipeline['name']}: CNB has no pipeline-level `resources` key",
                )
        # Neither of these jobs may run outside `stages`.
        for branch, event in (
            ("main", "push"),
            ("$", "push"),
            ("$", "tag_push"),
            ("$", "web_trigger_release"),
        ):
            for pipeline in _cnb_pipelines(branch, event):
                for key in ("endStages", "failStages"):
                    for stage in pipeline.get(key, []) or []:
                        self.assertNotIn(
                            stage.get("type"),
                            {"cnb:await", "cnb:resolve"},
                            f"{pipeline['name']}: {key} cannot hold {stage.get('type')}",
                        )

    def test_tag_and_manual_release_are_closed_same_event_architecture_graphs(self) -> None:
        """Tag/button releases build, resolve, await, then publish in one event."""
        for event, publisher_name in (
            ("tag_push", "release-tagged"),
            ("web_trigger_release", "release-manual"),
        ):
            pipelines = _cnb_pipelines("$", event)
            names = {pipeline["name"] for pipeline in pipelines}
            self.assertLessEqual(
                {"docker-images (amd64)", "docker-images (arm64)", publisher_name},
                names,
                event,
            )
            publisher = next(
                pipeline for pipeline in pipelines if pipeline["name"] == publisher_name
            )
            awaits = [
                stage for stage in publisher.get("stages", [])
                if stage.get("type") == "cnb:await"
            ]
            self.assertEqual(2, len(awaits), f"{event} publisher must await both packages")
            self.assertEqual(
                ["validated-runtime-images-amd64", "validated-runtime-images-arm64"],
                [stage["options"]["key"] for stage in awaits],
            )
            self.assertEqual(awaits, publisher["stages"][:2])
            self.assertIn(
                "scripts/ci-job-steps.sh run release",
                _flatten(publisher),
            )
            for arch in ("amd64", "arm64"):
                image_pipeline = next(
                    pipeline
                    for pipeline in pipelines
                    if pipeline["name"] == f"docker-images ({arch})"
                )
                self.assertEqual(
                    f"validated-runtime-images-{arch}",
                    image_pipeline["stages"][-1]["options"]["key"],
                )
                self.assertEqual("$CNB_COMMIT", image_pipeline["env"]["SOURCE_REVISION"])
                self.assertEqual("$CNB_EVENT", image_pipeline["env"]["SOURCE_EVENT"])
                self.assertNotIn("imports", image_pipeline)
                self.assertNotIn("cnbcool/attachments", _flatten(image_pipeline))


class CnbVolumeGrammarTests(unittest.TestCase):
    """The volume parser must reject what CNB refuses to prepare."""

    def test_accepts_the_supported_forms(self) -> None:
        self.assertEqual(_cnb_volume_path("/cache/pnpm-store", "loc"), "/cache/pnpm-store")
        self.assertEqual(
            _cnb_volume_path("/root/.gradle:copy-on-write", "loc"), "/root/.gradle"
        )
        self.assertEqual(_cnb_volume_path("main:/root/.gradle:rw", "loc"), "/root/.gradle")

    def test_rejects_docker_host_container_syntax(self) -> None:
        # The exact entry that failed Prepare: the second segment is a path, so
        # CNB reads the first as an unknown volume type.
        with self.assertRaises(AssertionError) as raised:
            _cnb_volume_path("/cache/pnpm-store:/cache/pnpm-store", "main/pr/verify")
        self.assertIn("host:container", str(raised.exception))

    def test_rejects_unknown_type_and_relative_path(self) -> None:
        with self.assertRaises(AssertionError):
            _cnb_volume_path("/cache/thing:bogus", "loc")
        with self.assertRaises(AssertionError):
            _cnb_volume_path("cache/pnpm-store", "loc")

    def test_rejects_malformed_segment_counts(self) -> None:
        with self.assertRaises(AssertionError):
            _cnb_volume_path("a:b:c:d", "loc")


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()


def test_worker_native_suite_urls_are_exported_by_the_resolver() -> None:
    """The worker's PostgreSQL suites must be given a URL, not a skip.

    Regression for ISSUE #51: three worker suites read
    ``SOYMUTDB_NATIVE_TEST_DATABASE_URL`` / ``SOYMUTDB_STATIC_TEST_DATABASE_URL``
    and answered a missing value with ``pytest.skip``. Nothing in the repository
    produced those variables, so 25 identity, atomicity and export-claim
    assertions were reported as ``skipped`` on every build while the gate
    exported ``SOYMUTDB_RUN_POSTGRES_INTEGRATION=1`` to assert a real database
    was present. A skip is indistinguishable from a pass in the pytest summary;
    that is the hole this pins shut from both ends.

    Both ends matter and neither is sufficient alone:
      * the resolver must produce the variables (otherwise them being required
        below is a guaranteed failure), and
      * the suites must fail closed (otherwise a future producer regression
        silently returns to skipping).
    """
    root = Path(__file__).resolve().parents[1]
    resolver = (root / "scripts/with-postgres-service.sh").read_text(encoding="utf-8")

    for variable in (
        "SOYMUTDB_NATIVE_TEST_DATABASE_URL",
        "SOYMUTDB_STATIC_TEST_DATABASE_URL",
        "SOYMUTDB_WORKER_TEST_DATABASE_URL",
    ):
        # Exported through the shared print/ensure path, so both consumption
        # styles the gate supports (`--print-exports` and `--ensure`) carry it.
        assert f"printf '{variable}=%s\\n'" in resolver, (
            f"{variable} must be part of the resolver's exported KEY=VALUE lines"
        )
        assert f"export {variable}" in resolver, (
            f"{variable} must be exported by the resolver, not only printed"
        )

    # The suites must fail closed. A skip here is a merge-gate hole, so the
    # contract forbids the construct outright rather than trusting review.
    for suite in (
        "apps/worker/tests/test_postgres_variant_store.py",
        "apps/worker/tests/test_export_claim_postgres.py",
        "apps/worker/tests/test_static_page_postgres.py",
    ):
        source = (root / suite).read_text(encoding="utf-8")
        assert "pytest.skip" not in source, f"{suite} must not skip on a missing URL"
        assert "pytest.fail" in source, f"{suite} must fail closed on a missing URL"

    # The two BLAST suites carry a second, genuinely optional precondition next
    # to the database one: real NCBI binaries, which CI does not have and should
    # not pretend to have. Skipping on that is correct. Skipping on the database
    # URL is the same hole as the three suites above, only latent behind the
    # binary skip -- so the assertion here is narrower on purpose: the binary
    # skip may stay, the URL skip may not.
    for suite in (
        "apps/worker/tests/test_blast_index_build_real.py",
        "apps/worker/tests/test_blast_ncbi_pipeline.py",
    ):
        source = (root / suite).read_text(encoding="utf-8")
        assert "SOYMUTDB_WORKER_TEST_DATABASE_URL" in source, (
            f"{suite} must still read the database variable"
        )
        url_blocks = [
            block
            for block in source.split("pytest.skip(")[1:]
            if "SOYMUTDB_WORKER_TEST_DATABASE_URL" in block.split(")", 1)[0]
        ]
        assert not url_blocks, (
            f"{suite} must not skip when SOYMUTDB_WORKER_TEST_DATABASE_URL is missing"
        )
        assert (
            'SOYMUTDB_WORKER_TEST_DATABASE_URL is required' in source
            and "pytest.fail(" in source
        ), f"{suite} must fail closed on a missing database URL"

    # The derived URL has to be usable by the worker environment: those suites
    # build a synchronous engine, so an asyncpg URL would fail at connect time
    # instead of at collection time.
    assert "postgresql+psycopg2://" in resolver, (
        "the worker suite URL must use the synchronous psycopg2 driver"
    )


def test_postgres_service_script_remains_executable() -> None:
    """CI runs this resolver directly, so a Git mode change must fail contracts."""
    import stat

    root = Path(__file__).resolve().parents[1]
    mode = (root / "scripts/with-postgres-service.sh").stat().st_mode
    assert mode & stat.S_IXUSR, "with-postgres-service.sh must be executable (100755)"


def test_e2e_knip_workspace_tracks_real_test_entrypoints() -> None:
    """Knip must analyze the independent Playwright package, not mislabel its tests dead."""
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "knip.json").read_text(encoding="utf-8"))
    entry = config["workspaces"]["e2e"]["entry"]
    assert "tests/*.spec.ts" in entry
    assert "playwright*.config.ts" in entry


def test_pr_artifact_browser_acceptance_covers_frontend_changes() -> None:
    """A frontend-only PR must still run the current-artifact Playwright gate."""
    workflow = yaml.load(_workflow_text("e2e-smoke.yml"), Loader=yaml.BaseLoader)
    pr_paths = set(workflow["on"]["pull_request"]["paths"])
    required = {
        "e2e/**",
        ".github/workflows/e2e-smoke.yml",
        "apps/web/**",
        "apps/jbrowse/**",
        "packages/**",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "scripts/build-pages-artifact.sh",
        "scripts/build-static-apps.sh",
        "scripts/verify-frontend-artifacts.sh",
        "scripts/verify-pages-artifact.sh",
    }
    assert required <= pr_paths, (
        "PR browser E2E must be triggered by frontend and build-contract changes: "
        f"{sorted(required - pr_paths)}"
    )
    assert workflow["jobs"]["pr-artifact"]["if"] == "github.event_name == 'pull_request'"
    assert "github.event_name != 'pull_request'" in workflow["jobs"]["e2e"]["if"]


def _cnb_cpus(template_path: Path):
    """Yield ``(where, cpus, cost, depth)`` per runner declaration.

    ``.cnb.yml`` nests events under the ``main`` and ``$`` root branches, so the
    event name has to be read from the inner map: at top level every event looks
    like a pull request.

    ``cost`` answers the only question this walk exists for -- does the
    reservation land on a review branch?

    * ``"verify"``: a ``pull_request`` pipeline. Prepare freezes ``cpus x
      window`` for it on every push to a review branch.
    * ``"agent"``: an ``@npc`` pipeline. It rides the same event, but the
      platform buys its runner on its own budget, so the frozen reservation is
      not the same charge (and adding one here makes the bill worse, not
      clearer).
    * ``None``: anything else (push, tag, manual, schedule) -- never warm while
      somebody is reading a diff.
    """
    config = yaml.safe_load(template_path.read_text(encoding="utf-8"))

    def walk_stages(stages):
        """Yield every stage dict in a ``stages`` list, including nested ones."""
        for stage in stages or []:
            if not isinstance(stage, dict):
                continue
            yield stage
            yield from walk_stages(stage.get("stages"))

    for branches in config.values():
        if not isinstance(branches, dict):
            continue
        for event_name, pipelines in branches.items():
            if not isinstance(pipelines, list):
                continue
            cost = None
            if str(event_name) == "pull_request":
                cost = "verify"
            elif str(event_name).startswith("pull_request."):
                cost = "agent"
            for pipeline in pipelines:
                if not isinstance(pipeline, dict):
                    continue
                name = f"{event_name}/{pipeline.get('name')}"
                runner = pipeline.get("runner") or {}
                # ``None`` is a declaration too: a pipeline that forgets a
                # runner pays the platform default, which cannot be counted.
                yield name, runner.get("cpus"), cost, 1
                for stage in walk_stages(pipeline.get("stages")):
                    stage_runner = stage.get("runner") or {}
                    where = f"{name}/{stage.get('name')}"
                    yield where, stage_runner.get("cpus"), cost, 2


def test_cnb_runner_declarations_are_honest_and_measurable() -> None:
    """A runner is a charge, not a preference: declare it or inherit nothing.

    The only red reading on a pull request every time Prepare dies is
    ``Root Group's events CPU core-hours are insufficient for pre-freezing``.
    Nothing in the changed files causes it -- CNB freezes a reservation for
    ``cpus x freeze_window`` before the first stage runs, so a PR whose
    pipelines declare oversized runners dies before any script is reachable and
    reports it as a pipeline ``error`` rendered next to the commit. The cost is
    paid during review, on somebody else's PR, attributed to their diff.

    The gate is deliberately shallow, but it is scored twice over, because a
    depth-2-only walk has already gone green against a planted ``cpus: 32``:

    1. Every value under a ``cpus:`` key anywhere in the template must be one
       of the sizes this repo actually schedules. This half is a text scan, not
       a walk, so a shape the walker cannot descend into still cannot smuggle
       in ``cpus: 160``.
    2. The pull request pipeline -- the one that pays the reservation on every
       push to a review branch -- must stay inside a small, counted budget.
       Release and manual pipelines are excluded: they run once per release.

    It does not try to predict the org balance; that number is invisible here.
    """
    template = ROOT / ".cnb.yml"
    text = template.read_text(encoding="utf-8")

    # (1) Text scan: no nesting shape, anchor or merge key can hide a
    # declaration from a regex over `cpus:` values.
    seen = re.findall(r"^\s*cpus:\s*['\"]?(\d+)['\"]?\s*$", text, re.MULTILINE)
    assert seen, "no `cpus:` value found in .cnb.yml; the scan is broken"
    allowed = {"4", "8", "16"}
    offenders = sorted({value for value in seen if value not in allowed})
    assert not offenders, (
        f".cnb.yml declares runner sizes this repo never schedules: {offenders} "
        f"(allowed: {sorted(allowed)})"
    )

    # (2) Walk: what a review branch actually reserves.
    declarations = list(_cnb_cpus(template))
    # Guard the guard: a walk that descends into nothing passes everything
    # above, which is exactly how a stage override stayed invisible.
    assert len(declarations) >= 15, (
        f"only {len(declarations)} runner declarations walked from .cnb.yml; "
        "the walk is broken"
    )
    assert any(count == 2 for _w, _c, _warm, count in declarations), (
        "the walk found no stage declaration; it is not descending into `stages`"
    )
    # Only pipelines are scored for a missing runner: a stage inherits the
    # pipeline's, so `None` there is the normal case, not a hole.
    warm = [
        (where, cpus)
        for where, cpus, cost, depth in declarations
        if cost == "verify" and depth == 1
    ]
    assert warm, "no pull_request pipeline declares a runner"
    # The `@npc` pipelines stay outside this count on purpose: they do ride the
    # pull_request event, but they are summoned by a comment and the platform
    # buys their runner on its own budget, so a frozen `cpus x window`
    # reservation is not the same charge. They stay inside the scan above, which
    # is where an oversized one would show up.
    agents = [where for where, _cpus, cost, depth in declarations if cost == "agent"]
    assert agents, "the @npc pipelines left the walk; they are part of the pull request event"
    pr_cores = [(where, int(cpus)) for where, cpus in warm]
    # 16 cores are reserved for the pipeline that genuinely fans out (pnpm
    # install + turbo build + vitest projects + Python). PR pipelines pay that
    # reservation on every push; a second 16-core PR pipeline doubles the bill
    # and starts failing in Prepare before the diff is ever read -- which is
    # what made this PR look broken.
    assert len(pr_cores) <= 2 and sum(cpus for _w, cpus in pr_cores) <= 20, (
        f"pull request pipelines reserve too many cores per run: {pr_cores}"
    )
