#!/usr/bin/env python3
"""Static contracts for the nginx security headers.

The bug this exists to prevent is silent and severe: nginx inherits
``add_header`` from the enclosing level **only when the inner level declares no
``add_header`` of its own**. A single ``add_header Cache-Control`` inside a
``location`` therefore discards the server's entire security-header set, and the
configuration still parses and still serves — it just stops sending CSP,
``X-Frame-Options``, ``nosniff`` and ``Referrer-Policy`` on exactly the
responses that needed them (the SPA HTML, the API, the genomic-data endpoints).

Four classes of mistake are checked, all of them statically:

1. A ``location`` that sets any header without pulling in a security-header
   fragment.
2. A fragment that does not declare the full set of header names.
3. A fragment referenced from a config that never defines the variables the
   fragment uses. ``add_header X $var always`` with no ``map``/``set`` for
   ``$var`` is ``nginx: [emerg] unknown variable`` — a startup failure, not a
   warning, and the container would crash-loop.
4. A fragment named ``*.conf``. ``nginx.conf`` loads ``include
   /etc/nginx/conf.d/*.conf;``, so a ``.conf`` fragment is parsed as a server
   block at the http level and ``nginx -t`` fails.

It also pins the two registry-style rules that keep the header surface from
regressing: no ``X-XSS-Protection`` anywhere, and no reflected
``Access-Control-Allow-Origin`` (which would need ``Vary: Origin`` and is a
shared-cache hazard).

No nginx binary and no Docker daemon are required: this reads the files.
``nginx -t`` remains the authoritative syntax check and is run against the built
images; this gate is what runs on every commit.

Usage: python3 scripts/check_nginx_security_headers.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NGINX_DIR = ROOT / "infra" / "nginx"
CONF_D = NGINX_DIR / "conf.d"

# Every nginx config that can serve a response. The main proxy plus the three
# container configs; cloudflare-tunnel.conf is included because it terminates a
# public hostname and sets its own headers.
CONFIGS: tuple[Path, ...] = (
    NGINX_DIR / "nginx.conf",
    CONF_D / "default.conf",
    NGINX_DIR / "cloudflare-tunnel.conf",
    ROOT / "infra" / "docker" / "web-nginx.conf",
    ROOT / "infra" / "docker" / "admin-nginx.conf",
    ROOT / "apps" / "jbrowse" / "nginx.conf",
)

# Files that are read together by ONE nginx instance, so a `map` in any of them
# defines the variable for all of them. `infra/nginx/nginx.conf` loads
# `conf.d/*.conf`; the other three are standalone files mounted as the whole
# nginx.conf of their container, and the stock image defines none of these
# variables. Getting this grouping wrong produces a false "undefined variable"
# finding on the main proxy (or, worse, hides a real one in a container).
INSTANCES: tuple[tuple[Path, ...], ...] = (
    (NGINX_DIR / "nginx.conf", CONF_D / "default.conf"),
    (NGINX_DIR / "cloudflare-tunnel.conf",),
    (ROOT / "infra" / "docker" / "web-nginx.conf",),
    (ROOT / "infra" / "docker" / "admin-nginx.conf",),
    (ROOT / "apps" / "jbrowse" / "nginx.conf",),
)

# The header names a security-header fragment must declare.
REQUIRED_HEADERS: tuple[str, ...] = (
    "Content-Security-Policy",
    "Strict-Transport-Security",
    "X-Frame-Options",
    "X-Content-Type-Options",
    "Referrer-Policy",
    "Permissions-Policy",
)

# Directives that must be byte-identical between the nginx dev fragment and the
# build-generated policy (see the archived 2026-09-15 portal plan, §4.0).
# script-src / connect-src / frame-src
# are deliberately allowed to differ: the dev proxy target is arbitrary and the
# production HTML is not served from here.
MUST_MATCH_DIRECTIVES: tuple[str, ...] = (
    "default-src",
    "style-src",
    "img-src",
    "font-src",
    "base-uri",
    "form-action",
    "frame-ancestors",
    "object-src",
    "worker-src",
)

# Present in the generated policy, intentionally absent from the nginx literal:
# the portal ships no <video>/<audio>, and keeping the directive sets aligned is
# what makes the parity check meaningful.
FORBIDDEN_IN_NGINX_CSP: tuple[str, ...] = ("media-src",)

FRAGMENT_RE = re.compile(r"^\s*include\s+(\S*security-headers[^;\s]*)\s*;", re.M)
LOCATION_RE = re.compile(r"\s*location\s+(?:(=|\^~|~|~\*)\s+)?(\S+)\s*\{")
ADD_HEADER_RE = re.compile(r"^\s*add_header\s+(\S+)", re.M)
MAP_OR_SET_RE = re.compile(r"^\s*(?:map\s+\S+\s+\$(\w+)|set\s+\$(\w+))", re.M)
VAR_RE = re.compile(r"\$(\w+)")

FRAGMENT_PATTERN = re.compile(r"^security-headers(?:-[a-z]+)?\.inc$")

# `COPY [--flag] <src> <dest>`. Used to prove an image actually ships the
# fragment its server config includes. A substring search over the Dockerfile is
# not enough: the first `conf.d/default.conf` in these files is inside
# `RUN rm /etc/nginx/conf.d/default.conf`, which sits above the real COPY and
# silently made an earlier version of this check vacuous.
COPY_RE = re.compile(r"^\s*COPY\s+(?:--\S+\s+)*(\S+)\s+(\S+)\s*$", re.M)


@dataclass
class Finding:
    path: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    checked_locations: int = 0
    checked_configs: int = 0

    def fail(self, path: Path | str, message: str) -> None:
        rel = str(path).replace(f"{ROOT}/", "")
        self.findings.append(Finding(rel, message))


def strip_comments(text: str) -> str:
    """Drop `#` comments, honouring quoted strings.

    Brace counting must not see a `{` that only exists in prose — several of
    these files document nginx behaviour in comments that quote config.
    """
    out, in_single, in_double, i = [], False, False, 0
    while i < len(text):
        char = text[i]
        if char == "\n":
            out.append(char)
            in_single = in_double = False
            i += 1
            continue
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        out.append(char)
        i += 1
    return "".join(out)


def iter_locations(text: str) -> list[tuple[str, str]]:
    """Return `(name, block_text)` for every location block in `text`."""
    clean = strip_comments(text)
    lines = clean.split("\n")
    blocks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        match = LOCATION_RE.match(lines[i])
        if not match:
            i += 1
            continue
        name = f"{match.group(1) or ''} {match.group(2)}".strip()
        depth, j, collected = 0, i, []
        while j < len(lines):
            depth += lines[j].count("{") - lines[j].count("}")
            collected.append(lines[j])
            if depth <= 0 and j > i:
                break
            j += 1
        blocks.append((name, "\n".join(collected)))
        i = j + 1
    return blocks


def declared_headers(text: str) -> set[str]:
    """Security-header names a chunk of config effectively declares.

    A fragment include counts: the server level of every config here pulls its
    headers in with `include .../security-headers.inc`, not with literal
    `add_header` lines. Ignoring the include would compute an empty required set
    and make the whole location check vacuous — the flaw the mutation test for
    "drop one location include" caught.
    """
    names = {h for h in ADD_HEADER_RE.findall(text) if h in REQUIRED_HEADERS}
    for included in FRAGMENT_RE.findall(text):
        fragment = CONF_D / Path(included).name
        if fragment.is_file():
            fragment_text = strip_comments(fragment.read_text(encoding="utf-8"))
            names |= {h for h in ADD_HEADER_RE.findall(fragment_text) if h in REQUIRED_HEADERS}
    return names


def server_level_headers(text: str) -> set[str]:
    """Security headers declared at server level (outside any location).

    This is the set a location silently discards the moment it declares any
    `add_header` of its own, so it — not a fixed list — is what each such
    location has to re-declare. A data-plane proxy that deliberately carries
    only `nosniff` is held to `nosniff`, while an HTML surface that carries the
    full set is held to the full set.
    """
    clean = strip_comments(text)
    outside = clean
    for _name, block in iter_locations(clean):
        outside = outside.replace(block, "")
    return declared_headers(outside)


def fragments() -> list[Path]:
    return sorted(p for p in CONF_D.glob("*.inc") if FRAGMENT_PATTERN.match(p.name))


def check_fragment_naming(report: Report) -> None:
    """A fragment must be `.inc`, or conf.d auto-loads it as a server block."""
    for path in sorted(CONF_D.glob("*.conf")):
        if "security-headers" in path.name:
            report.fail(
                path,
                "security-header fragment uses the .conf extension: "
                "`include /etc/nginx/conf.d/*.conf;` would parse it as a server "
                "block and `nginx -t` would fail. Rename it to *.inc.",
            )


def check_fragment_completeness(report: Report) -> None:
    for path in fragments():
        text = strip_comments(path.read_text(encoding="utf-8"))
        declared = set(ADD_HEADER_RE.findall(text))
        missing = [h for h in REQUIRED_HEADERS if h not in declared]
        if missing:
            report.fail(path, f"fragment is missing required headers: {', '.join(missing)}")

        csp = re.search(r'add_header\s+Content-Security-Policy\s+"([^"]*)"', text)
        if not csp:
            report.fail(path, "fragment has no CSP literal")
            continue
        directives = {part.split()[0] for part in csp.group(1).split(";") if part.strip()}
        absent = [d for d in MUST_MATCH_DIRECTIVES if d not in directives]
        if absent:
            report.fail(path, f"CSP is missing directives the generated policy has: {', '.join(absent)}")
        extra = [d for d in FORBIDDEN_IN_NGINX_CSP if d in directives]
        if extra:
            report.fail(
                path,
                f"CSP carries directives absent from the generated policy: {', '.join(extra)} "
                "— the directive sets must stay aligned (portal plan §4.0)",
            )


def fragment_variables(fragment: Path) -> set[str]:
    return set(VAR_RE.findall(strip_comments(fragment.read_text(encoding="utf-8"))))


def check_variables_are_defined(report: Report) -> None:
    """Every variable a fragment uses must be defined by the including instance.

    `add_header X $undefined always` fails nginx startup with
    `unknown "undefined" variable`. The fragments are shared between the main
    proxy (which defines `$hsts_header_value` from `$scheme`) and the container
    configs (which must define it from `$http_x_forwarded_proto`), so this is a
    real cross-file coupling and not a theoretical one.
    """
    for instance in INSTANCES:
        files = [p for p in instance if p.is_file()]
        if not files:
            continue
        defined: set[str] = set()
        for path in files:
            clean = strip_comments(path.read_text(encoding="utf-8"))
            defined |= {a or b for a, b in MAP_OR_SET_RE.findall(clean)}
        for path in files:
            clean = strip_comments(path.read_text(encoding="utf-8"))
            for included in FRAGMENT_RE.findall(clean):
                fragment = CONF_D / Path(included).name
                if not fragment.is_file():
                    report.fail(path, f"includes {included}, which does not exist")
                    continue
                for variable in sorted(fragment_variables(fragment)):
                    if variable not in defined:
                        report.fail(
                            path,
                            f"includes {fragment.name}, which uses ${variable}, but no "
                            f"config in its nginx instance defines a `map`/`set` for "
                            f"${variable} — nginx would fail to start with "
                            f'`unknown "{variable}" variable`',
                        )


def check_locations(report: Report, config: Path, text: str) -> None:
    clean = strip_comments(text)
    required = server_level_headers(clean)
    for name, block in iter_locations(clean):
        report.checked_locations += 1
        declared = set(ADD_HEADER_RE.findall(block))
        if not declared:
            # Inherits the enclosing level's set, which is the point.
            continue
        if FRAGMENT_RE.search(block):
            continue
        # An inline fragment-equivalent also satisfies the rule, so compare
        # against the resolved set rather than the literal lines.
        missing = sorted(required - declared_headers(block))
        if missing:
            report.fail(
                config,
                f"location {name!r} declares {sorted(declared)} but not {missing}, "
                "and includes no security-headers fragment — nginx drops the "
                "whole inherited set for this location",
            )


def check_registry_rules(report: Report) -> None:
    for path in sorted(ROOT.glob("infra/**/*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "X-XSS-Protection" in text:
            report.fail(path, "X-XSS-Protection is obsolete and must not be sent (G-7)")
        if re.search(r'Access-Control-Allow-Origin\s+"?\$http_origin', text):
            report.fail(
                path,
                "reflected Origin must not be used: these endpoints are "
                "credential-free, and a reflected value in a shared cache is the "
                "hazard. Use a fixed `*` (see the archived portal plan, T8).",
            )


def check_dockerfiles_ship_fragments(report: Report) -> None:
    """An image whose server config includes a fragment must COPY that fragment.

    Without it the container fails to start with `open() "/etc/nginx/conf.d/
    security-headers.inc" failed` — an image-build-time omission that only shows
    up when the container runs.
    """
    for dockerfile in (
        ROOT / "infra" / "docker" / "Dockerfile.web",
        ROOT / "infra" / "docker" / "Dockerfile.admin",
        ROOT / "apps" / "jbrowse" / "Dockerfile",
    ):
        if not dockerfile.is_file():
            report.fail(dockerfile, "missing Dockerfile")
            continue
        text = dockerfile.read_text(encoding="utf-8")
        copies = {dest: src for src, dest in COPY_RE.findall(text)}
        shipped = {Path(dest).name for dest in copies}

        for dest, src in copies.items():
            if not dest.endswith("conf.d/default.conf"):
                continue
            source = ROOT / src
            if not source.is_file():
                report.fail(dockerfile, f"COPYs {src}, which does not exist")
                continue
            for included in FRAGMENT_RE.findall(source.read_text(encoding="utf-8")):
                name = Path(included).name
                if name not in shipped:
                    report.fail(
                        dockerfile,
                        f"{Path(src).name} includes {name} but this image never "
                        "COPYs it — the container would fail to start with "
                        '`open() "/etc/nginx/conf.d/' + name + '" failed`',
                    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    report = Report()
    check_fragment_naming(report)
    check_fragment_completeness(report)

    for config in CONFIGS:
        if not config.is_file():
            report.fail(config, "expected nginx config is missing")
            continue
        report.checked_configs += 1
        check_locations(report, config, config.read_text(encoding="utf-8"))
    check_variables_are_defined(report)

    check_registry_rules(report)
    check_dockerfiles_ship_fragments(report)

    if args.json:
        print(json.dumps(
            {
                "configs": report.checked_configs,
                "locations": report.checked_locations,
                "fragments": [p.name for p in fragments()],
                "findings": [{"path": f.path, "message": f.message} for f in report.findings],
            },
            indent=2,
        ))
    else:
        print(f"nginx security headers: {report.checked_configs} configs, "
              f"{report.checked_locations} locations, {len(fragments())} fragments")
        seen: set[tuple[str, str]] = set()
        for finding in report.findings:
            key = (finding.path, finding.message)
            if key in seen:
                continue
            seen.add(key)
            print(f"  FAIL  {finding.path}: {finding.message}")

    if report.findings:
        print(f"nginx security headers: FAILED — {len(report.findings)} finding(s)")
        return 1
    print("nginx security headers: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
