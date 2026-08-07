# Open Code Review Environment

Deterministic code review pipeline inspired by alibaba/open-code-review.

## Usage
```bash
cd /home/claude-user
python3 tools/code-review/review.py --project apps --output tools/code-review/reports
python3 tools/code-review/review.py --project . --output tools/code-review/reports/full
```

## Rules

| ID | Category | Severity | Description |
|---|---|---|---|
| SEC-XSS | security | high | innerHTML/dangerouslySetInnerHTML without sanitization |
| SEC-SQLI | security | critical | f-string in SQL execute context |
| SEC-SECRET | security | critical | Hardcoded credentials, API keys, private keys |
| PERF-N1 | performance | high | DB calls inside loops (N+1 queries) |
| PERF-ANIM | performance | medium | Animating layout properties (top/left/width) |
| HTML5-VT | maintainability | info | View Transitions API opportunity |
| HTML5-WC | maintainability | info | Web Components opportunity for widgets |
| HTML5-IO | performance | low | IntersectionObserver lazy-loading opportunity |

## Output
- HTML report: review-report.html (open in browser)
- JSON report: review-report.json (machine-readable)
