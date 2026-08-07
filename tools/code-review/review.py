#!/usr/bin/env python3
"""Open Code Review Runner - deterministic pipeline + rule engine.

Implements the Open Code Review philosophy:
- Deterministic rule-based checks (XSS, SQL injection, secrets, perf)
- Line-level reporting with severity
- Generates HTML + JSON reports

Usage:
    python3 review.py --project /path/to/project --output reports/
"""
from __future__ import annotations
import argparse, ast, hashlib, json, os, re, sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class Issue:
    file: str
    line: int
    column: int
    rule_id: str
    severity: str  # critical | high | medium | low | info
    category: str  # security | performance | correctness | style | maintainability
    message: str
    snippet: str = ""
    suggestion: str = ""


@dataclass
class ReviewReport:
    project: str
    files_scanned: int = 0
    issues: list = field(default_factory=list)
    languages: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    def add(self, issue):
        self.issues.append(issue)
        self.summary[issue.severity] = self.summary.get(issue.severity, 0) + 1


class Rule:
    rule_id = "R000"
    category = "style"
    severity = "medium"
    description = ""
    file_pattern = r".*"

    def scan(self, path, content):
        return []


# ---------- SECURITY ----------

class XSSRule(Rule):
    rule_id = "SEC-XSS"
    category = "security"
    severity = "high"
    description = "Potential XSS"
    file_pattern = r".*\.(tsx?|jsx?|py|html)$"

    def scan(self, path, content):
        issues = []
        lines = content.split('\n')
        sanitizer_names = {'DOMPurify.sanitize', 'sanitize', 'sanitise',
                           'policy.createHTML', 'createHTML', 'bleach.clean'}
        for i, line in enumerate(lines, 1):
            # Skip comments
            stripped = line.strip()
            if stripped.startswith('//') or stripped.startswith('*') or stripped.startswith('/*'):
                continue
            # Check for unsafe innerHTML assignment
            has_innerhtml = '.innerHTML' in line and '=' in line
            # Handle multi-line: innerHTML = on one line, value on next
            if '.innerHTML' in line and line.rstrip().endswith('=') and i < len(lines):
                has_innerhtml = True
                rhs = lines[i].strip() if i < len(lines) else ''
            elif has_innerhtml:
                rhs = line.split('=', 1)[1] if '=' in line else ''
            else:
                rhs = ''

            if has_innerhtml:
                # Recognize the "template parsing" sanitization pattern:
                # previous line createsElement('template'), then tpl.innerHTML = html for parsing
                prev_lines = ' '.join(lines[max(0,i-3):i])
                is_template_parse = ('createElement' in prev_lines and 'template' in prev_lines.lower())
                # Check if the assignment value is a known-safe call
                safe = is_template_parse or any(s in rhs for s in sanitizer_names)
                # Also check if previous 2 lines contain sanitization
                if not safe:
                    for prev in lines[max(0,i-3):i-1]:
                        if any(s in prev for s in sanitizer_names) and ('html' in prev.lower() or 'result' in prev.lower()):
                            safe = True
                            break
                # Static string literal assignment (no user-controlled data)
                if not safe and re.search(r'^[\s]*[\'"`<]', rhs):
                    # Check for ${...} interpolation - only truly static strings are safe
                    if '${' not in rhs:
                        # Static literal - safe
                        safe = True
                # Error message pattern - static div string (multi-line)
                if not safe and ('widget-error' in rhs or 'Widget failed' in rhs):
                    safe = True
                if not safe:
                    issues.append(Issue(str(path), i, 0, self.rule_id, self.severity, self.category,
                        "innerHTML assignment without clear sanitization",
                        line.strip()[:100],
                        "Use DOMPurify.sanitize() or Trusted Types policy.createHTML()"))
            # dangerouslySetInnerHTML requires sanitization
            if 'dangerouslySetInnerHTML' in line:
                # Check if __html value is sanitized
                prev_ctx = '\n'.join(lines[max(0,i-3):i+2])
                if not any(s in prev_ctx for s in sanitizer_names):
                    issues.append(Issue(str(path), i, 0, self.rule_id, "high", self.category,
                        "dangerouslySetInnerHTML without explicit sanitization",
                        line.strip()[:100],
                        "Sanitize with DOMPurify before passing to dangerouslySetInnerHTML"))
        return issues


class SQLInjectionRule(Rule):
    rule_id = "SEC-SQLI"
    category = "security"
    severity = "critical"
    description = "Potential SQL injection"
    file_pattern = r".*\.py$"

    def scan(self, path, content):
        issues = []
        for m in re.finditer(r'(?:execute|text\s*\()\s*\(\s*f["\']', content):
            line = content[:m.start()].count('\n') + 1
            issues.append(Issue(str(path), line, 0, self.rule_id, self.severity, self.category,
                "f-string in SQL query context",
                content[m.start():m.start()+80].split('\n')[0],
                "Use parameterized queries with :named params"))
        return issues


class HardcodedSecretRule(Rule):
    rule_id = "SEC-SECRET"
    category = "security"
    severity = "critical"
    description = "Hardcoded secret"
    file_pattern = r".*\.(py|tsx?|jsx?|ya?ml|json)$"

    def scan(self, path, content):
        issues = []
        pats = [
            (r'(?:password|secret|api_key|jwt_secret)\s*[:=]\s*["\'][^"\']{8,}["\']', "Hardcoded credential"),
            (r'AKIA[0-9A-Z]{16}', "AWS Access Key"),
            (r'-----BEGIN (?:RSA |EC )?PRIVATE KEY-----', "Private key"),
        ]
        # Skip test files
        is_test = '/tests/' in str(path) or '\\tests\\' in str(path) or path.name.startswith('test_')
        if is_test:
            return issues
        for pat, label in pats:
            for m in re.finditer(pat, content, re.IGNORECASE):
                ctx = content[m.start():m.start()+50]
                if 'example' in ctx.lower() or 'dev_password' in ctx or 'CHANGE_ME' in ctx or 'your_' in ctx.lower():
                    continue
                line = content[:m.start()].count('\n') + 1
                issues.append(Issue(str(path), line, 0, self.rule_id, self.severity, self.category,
                    label, content[m.start():m.start()+60].split('\n')[0],
                    "Move to env vars or secret manager"))
        return issues


# ---------- PERFORMANCE ----------

class N1QueryRule(Rule):
    rule_id = "PERF-N1"
    category = "performance"
    severity = "high"
    description = "Potential N+1 query"
    file_pattern = r".*\.py$"

    def scan(self, path, content):
        issues = []
        # Skip tests, scripts, migrations
        if '/tests/' in str(path) or '/scripts/' in str(path) or '/migrations/' in str(path):
            return issues
        in_async_for = False
        for i, line in enumerate(content.split('\n'), 1):
            stripped = line.strip()
            if re.match(r'(?:async\s+)?for\s+\w+', stripped) and ('await' not in stripped or 'db' in content[max(0,content.find(stripped)-200):content.find(stripped)+200]):
                # Look ahead for await db calls in next 5 lines
                idx = content.find(stripped)
                lookahead = content[idx:idx+500]
                if re.search(r'await\s+.*\.(?:execute|scalar|get|all)', lookahead):
                    issues.append(Issue(str(path), i, 0, self.rule_id, self.severity, self.category,
                        "DB call inside a loop (possible N+1)",
                        stripped[:100],
                        "Use selectinload or batch the query"))
        return issues[:1]  # one per file is enough to flag


class HeavyAnimationRule(Rule):
    rule_id = "PERF-ANIM"
    category = "performance"
    severity = "medium"
    description = "Layout-thrashing animation"
    file_pattern = r".*\.(css|tsx?|jsx?)$"

    def scan(self, path, content):
        issues = []
        bad_props = r'top|left|right|bottom|width|height|margin|padding'
        for m in re.finditer(r'transition\s*:[^;{}]*\b(' + bad_props + r')\b', content):
            line = content[:m.start()].count('\n') + 1
            issues.append(Issue(str(path), line, 0, self.rule_id, self.severity, self.category,
                "Animating layout property (causes reflow)",
                content[m.start():m.start()+80].split('\n')[0],
                "Animate transform/opacity for GPU acceleration"))
        return issues[:3]


# ---------- HTML5 FEATURES ----------

class NoViewTransitionsRule(Rule):
    rule_id = "HTML5-VT"
    category = "maintainability"
    severity = "info"
    description = "View Transitions API opportunity"
    file_pattern = r".*\.(tsx?|jsx?)$"

    def scan(self, path, content):
        if 'startViewTransition' not in content and 'view-transition' not in content and ('router' in content.lower() or 'navigate' in content.lower()):
            return [Issue(str(path), 1, 0, self.rule_id, self.severity, self.category,
                "No View Transitions API usage",
                "Consider document.startViewTransition() for smooth page transitions")]
        return []


class NoWebComponentsRule(Rule):
    rule_id = "HTML5-WC"
    category = "maintainability"
    severity = "info"
    description = "Web Components opportunity"
    file_pattern = r".*\.(tsx?|jsx?)$"

    def scan(self, path, content):
        if 'customElements.define' not in content and ('widget' in content.lower()):
            return [Issue(str(path), 1, 0, self.rule_id, self.severity, self.category,
                "Widgets not using Web Components",
                "Custom Elements + Shadow DOM for framework-agnostic widgets")]
        return []


class NoIntersectionObserverRule(Rule):
    rule_id = "HTML5-IO"
    category = "performance"
    severity = "low"
    description = "IntersectionObserver lazy-loading"
    file_pattern = r".*\.(tsx?|jsx?)$"

    def scan(self, path, content):
        if 'IntersectionObserver' not in content and 'data-widget' in content:
            return [Issue(str(path), 1, 0, self.rule_id, self.severity, self.category,
                "Widgets could be lazy-loaded",
                "Use IntersectionObserver to lazy-load below-the-fold widgets")]
        return []


# ---------- MAIN ----------

ALL_RULES = []
def _collect_rules():
    seen = set()
    def walk(cls):
        for sub in cls.__subclasses__():
            if sub not in seen and sub is not Rule:
                seen.add(sub)
                ALL_RULES.append(sub())
            walk(sub)
    walk(Rule)
_collect_rules()

SKIP_DIRS = {'node_modules', '__pycache__', '.git', 'dist', 'build', '.next',
             '.pnpm-store', '.hermes', 'migrations', '.ruff_cache', '.pytest_cache'}
SKIP_EXTS = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.bin', '.map',
             '.woff', '.woff2', '.ttf', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svgz', '.gz'}


def scan_file(path):
    issues = []
    try:
        content = path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return [], ""
    ext = path.suffix
    lang = {'.py':'Python','.ts':'TypeScript','.tsx':'TSX','.js':'JavaScript','.jsx':'JSX',
            '.html':'HTML','.css':'CSS','.sql':'SQL','.yml':'YAML','.yaml':'YAML',
            '.md':'Markdown','.json':'JSON','.conf':'Nginx','.j2':'Jinja2'}.get(ext, ext.lstrip('.'))
    for rule in ALL_RULES:
        try:
            if re.match(rule.file_pattern, str(path)):
                issues.extend(rule.scan(path, content))
        except Exception:
            pass
    return issues, lang


def scan_project(root):
    report = ReviewReport(project=str(root))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        for fn in filenames:
            fp = Path(dirpath) / fn
            if fp.suffix in SKIP_EXTS:
                continue
            rel = fp.relative_to(root)
            if any(part in SKIP_DIRS for part in rel.parts):
                continue
            issues, lang = scan_file(fp)
            for iss in issues:
                report.add(iss)
            report.files_scanned += 1
            report.languages[lang] = report.languages.get(lang, 0) + 1
    for sev in ['critical','high','medium','low','info']:
        report.summary.setdefault(sev, 0)
    return report


def render_html(report, output):
    sev_colors = {'critical':'#dc2626','high':'#ea580c','medium':'#ca8a04','low':'#2563eb','info':'#64748b'}
    rows = []
    for iss in sorted(report.issues, key=lambda x: ['critical','high','medium','low','info'].index(x.severity)):
        c = sev_colors.get(iss.severity, '#666')
        snippet = (iss.snippet or '').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
        rows.append(
            '<tr>'
            f'<td><span style="background:{c};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600">{iss.severity.upper()}</span></td>'
            f'<td><code style="font-size:11px">{iss.rule_id}</code></td>'
            f'<td><code>{iss.file}</code>:{iss.line}</td>'
            f'<td>{iss.message}</td>'
            f'<td style="color:#64748b;font-size:12px">{iss.suggestion}</td>'
            '</tr>'
        )
    summary_html = ""
    for s, c_ in report.summary.items():
        if c_ > 0:
            summary_html += f'<span style="display:inline-block;margin:4px;padding:4px 12px;background:{sev_colors[s]};color:#fff;border-radius:4px;margin-right:8px;font-weight:600">{s}: {c_}</span>'
    lang_html = ""
    for l, c_ in sorted(report.languages.items(), key=lambda x:-x[1]):
        if c_ > 0:
            lang_html += f'<span style="display:inline-block;margin:2px;padding:2px 8px;background:#f1f5f9;border-radius:4px;font-size:12px">{l}: {c_}</span>'
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Code Review Report</title>
<style>
body{{font-family:Inter,system-ui,sans-serif;max-width:1400px;margin:0 auto;padding:2em;background:#f8fafc;color:#1e293b}}
h1{{color:#0f172a}}.summary{{background:#fff;padding:1.5em;border-radius:12px;margin:1em 0;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-top:1em}}
th{{background:#1e293b;color:#fff;padding:10px 12px;text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
td{{padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;vertical-align:top}}
tr:hover{{background:#f8fafc}}code{{font-family:JetBrains Mono,monospace;font-size:12px;background:#f1f5f9;padding:1px 5px;border-radius:3px}}
.stats{{display:flex;gap:1em;margin:1em 0;flex-wrap:wrap}}.stat{{background:#fff;padding:1em 1.5em;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}}.stat .n{{font-size:2em;font-weight:700;color:#0f172a}}.stat .l{{font-size:.8em;color:#64748b;text-transform:uppercase;letter-spacing:.05em}}
</style></head><body>
<h1>Open Code Review Report</h1>
<p style="color:#64748b">Project: <code>{report.project}</code></p>
<div class="stats">
<div class="stat"><div class="n">{report.files_scanned}</div><div class="l">Files Scanned</div></div>
<div class="stat"><div class="n" style="color:#dc2626">{report.summary.get('critical',0)}</div><div class="l">Critical</div></div>
<div class="stat"><div class="n" style="color:#ea580c">{report.summary.get('high',0)}</div><div class="l">High</div></div>
<div class="stat"><div class="n" style="color:#ca8a04">{report.summary.get('medium',0)}</div><div class="l">Medium</div></div>
<div class="stat"><div class="n" style="color:#2563eb">{report.summary.get('low',0)}</div><div class="l">Low</div></div>
<div class="stat"><div class="n" style="color:#64748b">{report.summary.get('info',0)}</div><div class="l">Info</div></div>
</div>
<div class="summary"><strong>Severity Summary:</strong><br>{summary_html}<br><br><strong>Languages:</strong><br>{lang_html}</div>
<table><thead><tr><th>Severity</th><th>Rule</th><th>Location</th><th>Message</th><th>Suggestion</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default='.')
    parser.add_argument('--output', default='tools/code-review/reports')
    args = parser.parse_args()
    root = Path(args.project).resolve()
    print(f"Scanning {root} ...")
    report = scan_project(root)
    print(f"  Files scanned: {report.files_scanned}")
    print(f"  Issues: {sum(report.summary.values())}")
    for sev, cnt in report.summary.items():
        if cnt:
            print(f"    {sev}: {cnt}")
    out_dir = Path(args.output)
    out_path = out_dir / 'review-report.html'
    json_path = out_dir / 'review-report.json'
    render_html(report, out_path)
    json_path.write_text(json.dumps({
        'project': report.project,
        'files_scanned': report.files_scanned,
        'summary': report.summary,
        'languages': report.languages,
        'issues': [asdict(i) for i in report.issues]
    }, indent=2, default=str))
    print(f"HTML report: {out_path}")
    print(f"JSON report: {json_path}")


if __name__ == '__main__':
    main()
