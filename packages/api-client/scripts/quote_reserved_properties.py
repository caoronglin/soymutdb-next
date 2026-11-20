#!/usr/bin/env python3
"""Quote generated TypeScript property names that collide with TS modifiers.

The API schema legitimately publishes an `abstract` field; openapi-typescript
emits `abstract: string | null`, which is valid TypeScript and passes `tsc`,
but opengrep's TS parser reads it as a class modifier and aborts parsing the
whole file. That silently disables an entire scanner lane in pi-lens. A quoted
property name is exactly the same type and runtime shape -- only the parser
stops guessing.

Both the generator and its byte-for-byte consistency gate call this script so
the post-processing cannot drift between them.
"""

from __future__ import annotations

import pathlib
import sys

# An interface *property* line, indented exactly as openapi-typescript emits
# it. Not a class declaration or a keyword use.
RESERVED_PROPERTY_LINES = ("\n            abstract: string | null;",)


def normalize(source: str) -> str:
    result = source
    for raw in RESERVED_PROPERTY_LINES:
        quoted = raw.replace("abstract: string | null;", '"abstract": string | null;')
        result = result.replace(raw, quoted)
    return result


def main(argv: list[str]) -> int:
    path = pathlib.Path(argv[1])
    source = path.read_text(encoding="utf-8")
    quoted = normalize(source)
    if quoted != source:
        path.write_text(quoted, encoding="utf-8")
        print(f"quoted reserved-word property name(s) in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
