"""ClickHouse schema migration executor; SQL is always supplied by the caller."""
import re


SUMMARY_TABLES = [
    "gene_impact_summary", "chromosome_summary", "mutant_line_summary", "release_dashboard",
    "density_10kb", "density_100kb", "density_1mb", "substitution_spectrum",
]
MATERIALIZED_VIEWS = ["mv_" + name for name in (
    "gene_impact", "chromosome_summary", "mutant_line_summary", "release_dashboard",
    "density_10kb", "density_100kb", "density_1mb", "substitution_spectrum",
)]


class MigrationGateError(RuntimeError):
    pass


class CompletionError(RuntimeError):
    pass


def _rows(value):
    return getattr(value, "result_rows", value)


def _strip_line_comment(line):
    quote = None
    for i, ch in enumerate(line):
        if ch in "'\"`":
            if quote == ch:
                quote = None
            elif quote is None:
                quote = ch
        elif ch == "-" and i + 1 < len(line) and line[i + 1] == "-" and quote is None:
            return line[:i]
    return line


def _split_statements(text):
    statements, current, quote = [], [], None
    for raw in text.splitlines():
        line = _strip_line_comment(raw).rstrip()
        if not line.strip():
            continue
        for char in line:
            if char in "'\"`":
                if quote == char:
                    quote = None
                elif quote is None:
                    quote = char
            if char == ";" and quote is None:
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
            else:
                current.append(char)
        # Preserve the line boundary. Concatenating only the characters fused
        # the last token of a line to the first token of the next one, which is
        # how `TTL timestamp + INTERVAL 2 YEAR` followed by `SETTINGS …` reached
        # ClickHouse as the identifier `YEARSETTINGS`: the server then failed at
        # the token after it (`index_granularity`) with "Expected one of:
        # NANOSECOND, …, end of query", which points at the wrong place.
        current.append("\n")
    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def split_stages(sql_text):
    stages = {"stage1": [], "gate": [], "stage2": []}
    current = None
    marker = re.compile(r"^--\s*STAGE\s+(1)\s+GATE\s*:", re.I)
    for line in sql_text.splitlines():
        if marker.match(line):
            current = "gate"
        elif re.match(r"^--\s*STAGE\s+1\s*:", line, re.I):
            current = "stage1"
        elif re.match(r"^--\s*STAGE\s+2\s*:", line, re.I):
            current = "stage2"
        elif current is not None:
            stages[current].append(line)
    return {name: _split_statements("\n".join(lines)) for name, lines in stages.items()}


def detect_state(client):
    tables = {row[0] for row in _rows(client.query("SELECT name FROM system.tables WHERE database = currentDatabase()"))}
    if "variant_facts" not in tables:
        return "S3"
    columns = {row[0] for row in _rows(client.query("SELECT name FROM system.columns WHERE database = currentDatabase() AND table = 'variant_facts'"))}
    if "release_key" in columns:
        return "S2"
    return "S1" if "variant_facts_new" in tables else "S0"


def _value(client, sql):
    rows = _rows(client.query(sql))
    return rows[0][0]


def _gate(values, threshold):
    legacy, replacement, empty, zero = values
    return legacy == replacement and (legacy == 0 or empty / legacy < threshold) and (legacy == 0 or zero == 0)


def check_completion(client):
    rows = _rows(client.query("SELECT name, engine FROM system.tables WHERE database = currentDatabase()"))
    actual = {row[0]: row[1] for row in rows}
    missing = [name for name in SUMMARY_TABLES if name not in actual or actual[name].startswith("MaterializedView")]
    missing += [name for name in MATERIALIZED_VIEWS if name not in actual or not actual[name].startswith("MaterializedView")]
    return missing


def run_migration(client, sql_text, empty_key_threshold, dry_run=False):
    stages = split_stages(sql_text)
    state = "S0" if dry_run else detect_state(client)
    values = None
    if state == "S3":
        return {"state": state, "skipped": True}

    def execute(name, statements, skip_rename=False):
        for statement in statements:
            if skip_rename and statement.upper().startswith("RENAME TABLE VARIANT_FACTS"):
                continue
            if dry_run:
                print("[dry-run]", name, statement.splitlines()[0][:100])
            else:
                client.command(statement)

    if state == "S1":
        execute("recovery", ["DROP TABLE IF EXISTS variant_facts_new"])
    if state in ("S0", "S1"):
        execute("stage1", stages["stage1"])
        if dry_run:
            values = (0, 0, 0, 0)
        else:
            values = tuple(_value(client, statement) for statement in stages["gate"])
        if not _gate(values, empty_key_threshold):
            raise MigrationGateError(f"migration gate failed: {values}")
    execute("stage2", stages["stage2"], skip_rename=state == "S2")
    if not dry_run:
        missing = check_completion(client)
        if missing:
            raise CompletionError("completion check failed: " + ",".join(missing))
    return {"state": state, "skipped": False, "gate": values if state in ("S0", "S1") else None}
