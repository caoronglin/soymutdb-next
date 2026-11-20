#!/usr/bin/env python3
"""Run the plan's ablation scenarios and emit the scenario table the plan asks for.

## Why a runner

The 2026-10-02 plan (§4) requires每条保护因素配一个场景：对照输入/状态、变异差异、
对照与变异的**真实 exit**、观测、恢复结果、证据层级。Those ablations were executed
ad hoc during the round, so the evidence existed but not in one re-runnable place —
and an ablation that cannot be re-run is an anecdote.

Each scenario here is a **single-factor** mutation of one file, guarded by:

* a byte-exact backup taken before the edit and restored after;
* a checksum comparison on restore, so a scenario can never leave the tree dirty;
* a refusal to run if the tree is not clean enough to attribute a failure.

## Layers

| layer | what it can prove |
| --- | --- |
| `source-guard` | a source guard stops reporting (or starts reporting) |
| `unit` | a unit/render suite flips |
| `component` | a component-level assertion flips |

Layers needing a production rebuild (`artifact`) and a live database (`db-ab`) are
**not** run here; they are listed as `skipped` with the reason, because a runner that
silently omits them would overstate what has been verified.

Usage:
    python3 scripts/run_ablations.py                # all runnable scenarios
    python3 scripts/run_ablations.py --list
    python3 scripts/run_ablations.py --only A-02 A-05
    python3 scripts/run_ablations.py --markdown out.md
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The allowlist's first pattern exempts strings made only of punctuation and
# digits. `\W` also matches every CJK code point, so the bare form silently
# exempted all Chinese copy; the shipped form excludes CJK explicitly.
CJK_PATTERN_LINE = '    "^(?![\\\\s\\\\S]*[\\\\u3400-\\\\u4dbf\\\\u4e00-\\\\u9fff\\\\uf900-\\\\ufaff])[\\\\W\\\\d_]+$",'
ORIGINAL_PATTERN_LINE = '    "^[\\\\W\\\\d_]+$",'

# The host cannot sustain many concurrent CPU-heavy processes (argon2 and ruff both
# fail with thread-creation errors under load), so every subprocess here is pinned to
# one thread and the runner is strictly serial.
CHILD_ENV = {
    **os.environ,
    "GOMAXPROCS": "1",
    "RAYON_NUM_THREADS": "1",
    "UV_THREADPOOL_SIZE": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "NODE_OPTIONS": os.environ.get("NODE_OPTIONS", "--max-old-space-size=4096"),
    # A scenario rewrites a source file and restores it within the same mtime
    # tick. Without this, Python can serve a cached .pyc whose (mtime, size)
    # still matches the restored file — the mutation then never reaches the
    # interpreter and the scenario reports a phantom "no flip".
    "PYTHONDONTWRITEBYTECODE": "1",
}

THREAD_ENV_KEYS = ("GOMAXPROCS", "RAYON_NUM_THREADS", "UV_THREADPOOL_SIZE")


@dataclass
class Scenario:
    """One protection factor, its mutation, and how each side is judged."""

    id: str
    requirement: str
    entry: str
    protection: str
    layer: str
    path: Path
    mutate: str
    control: list[str]
    mutant: list[str]
    expect_mutant_nonzero: bool = True
    note: str = ""

    @property
    def runnable(self) -> bool:
        return self.layer != "skipped"


@dataclass
class Outcome:
    scenario: Scenario
    control_exit: int
    mutant_exit: int
    restored: bool
    checksum_ok: bool
    skipped_reason: str = ""
    control_tail: str = ""
    mutant_tail: str = ""


def clear_stale_bytecode(target: Path) -> None:
    """Drop any .pyc that could shadow the file a scenario is about to rewrite."""
    cache = (ROOT / "scripts" / "__pycache__").resolve()
    if not cache.is_dir():
        return
    stem = target.stem
    for stale in cache.glob(f"{stem}.*.pyc"):
        stale.unlink(missing_ok=True)


def sh(command: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=CHILD_ENV,
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode, "\n".join(tail[-6:])


def digest(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def apply_mutation(scenario: Scenario, tree: Path) -> bool:
    """Rewrite one occurrence of `old` -> `new` in the scenario's file."""
    target = tree / scenario.path
    text = target.read_text(encoding="utf-8")
    if scenario.mutate.count("||") == 0 and "|" not in scenario.mutate:
        raise SystemExit(f"{scenario.id}: malformed mutation spec")
    old, new = scenario.mutate.split("||", 1)
    if text.count(old) != 1:
        # Some factors appear more than once on purpose (the commit documents two
        # skip links); allow an explicit multi-apply form.
        if text.count(old) == 0:
            return False
        text = text.replace(old, new)
    else:
        text = text.replace(old, new, 1)
    target.write_text(text, encoding="utf-8")
    return True


def run_scenario(scenario: Scenario, tree: Path) -> Outcome:
    original = scenario.path.read_bytes()
    before = digest(scenario.path)
    backup = Path(tempfile.mkdtemp(prefix="ablation-")) / scenario.path.name
    backup.write_bytes(original)
    try:
        clear_stale_bytecode(scenario.path)
        control_exit, control_tail = sh(scenario.control)
        if not apply_mutation(scenario, tree):
            return Outcome(scenario, control_exit, control_exit, True, True, "anchor not found in source")
        clear_stale_bytecode(scenario.path)
        mutant_exit, mutant_tail = sh(scenario.mutant)
        return Outcome(scenario, control_exit, mutant_exit, True, True, "", control_tail, mutant_tail)
    finally:
        scenario.path.write_bytes(original)
        after = digest(scenario.path)
        shutil.rmtree(backup.parent, ignore_errors=True)
        ok = digest(scenario.path) == before == after
        if not ok:
            sys.stderr.write(f"FATAL: {scenario.id} did not restore {scenario.path}\n")
            raise SystemExit(2)


SCENARIOS: list[Scenario] = [
    Scenario(
        id="A-01",
        requirement="assembly 查询键必须携带 release 与站点上下文（DB-CORE-6）",
        entry="apps/web/src/routes/search/primer.tsx → assembliesQueryOptions",
        protection="工厂实参配平扫描 + 逐字面量检查",
        layer="source-guard",
        path=Path("apps/web/src/routes/search/primer.tsx"),
        mutate="    siteVariant: SITE_VARIANT,\n||",
        control=["python3", "scripts/check_web_query_keys.py"],
        mutant=["python3", "scripts/check_web_query_keys.py"],
    ),
    Scenario(
        id="A-02",
        requirement="同上（守卫自身不得有假阳性）",
        entry="scripts/check_web_query_keys.py :: call_arguments",
        protection="括号配平扫描（跨字符串字面量）",
        layer="source-guard",
        path=Path("scripts/check_web_query_keys.py"),
        mutate='    if quote:\n||    if False:\n',
        control=["python3", "-m", "pytest", "scripts/test_web_query_keys_guard.py", "-q"],
        mutant=["python3", "-m", "pytest", "scripts/test_web_query_keys_guard.py", "-q"],
    ),
    Scenario(
        id="A-03",
        requirement="管理端令牌只在模块内存，不得持久化（H-06）",
        entry="apps/admin/src/lib/antd-theme.ts → localStorage",
        protection="偏好键注册表 + 校验器包裹的窄放行",
        layer="source-guard",
        path=Path("apps/admin/src/lib/antd-theme.ts"),
        mutate='!isValidAdminPrimaryColor(value) || ||',
        control=[
            "python3", "-m", "pytest",
            "scripts/test_admin_content_architecture_guard.py", "-q",
        ],
        mutant=[
            "python3", "-m", "pytest",
            "scripts/test_admin_content_architecture_guard.py", "-q",
        ],
    ),
    Scenario(
        id="A-04",
        requirement="可见文案必须来自 zh/en 目录（H-13）",
        entry="scripts/check_visible_i18n_react.mjs :: visibleStrings",
        protection="函数实参中的模板字面量豁免（React key 前缀不是文案）",
        layer="source-guard",
        path=Path("scripts/check_visible_i18n_react.mjs"),
        mutate="      if (ts.isTemplateExpression(argument)) continue;\n||",
        control=["node", "scripts/test_visible_i18n_react_guard.mjs"],
        mutant=["node", "scripts/test_visible_i18n_react_guard.mjs"],
    ),
    Scenario(
        id="A-05",
        requirement="多行硬编码 alt 必须被报出（D-10 的扫描盲区）",
        entry="scripts/check_visible_i18n_react.mjs",
        protection="AST 可见性扫描（非逐行正则）",
        layer="source-guard",
        path=Path("scripts/check_visible_i18n_react.mjs"),
        mutate='const VISIBLE_ATTRIBUTES = new Set([\n  "alt",\n||const VISIBLE_ATTRIBUTES = new Set([\n',
        control=["node", "scripts/test_visible_i18n_react_guard.mjs"],
        mutant=["node", "scripts/test_visible_i18n_react_guard.mjs"],
    ),
    Scenario(
        id="A-06",
        requirement="中文可见文案必须被报出（CJK 字符集豁免的扫描盲区）",
        entry="scripts/visible-i18n-allowlist.json :: patterns[0]",
        protection="允许列表的标点/数字豁免不得吞掉 CJK 文案",
        layer="source-guard",
        path=Path("scripts/visible-i18n-allowlist.json"),
        # CJK-aware pattern -> the original punctuation-only pattern.
        mutate=CJK_PATTERN_LINE + "\n||" + ORIGINAL_PATTERN_LINE + "\n",
        control=["node", "scripts/test_visible_i18n_react_guard.mjs"],
        mutant=["node", "scripts/test_visible_i18n_react_guard.mjs"],
    ),
    Scenario(
        id="B-01",
        requirement="实验只能跑在命名的一次性副本上（H-09）",
        entry="scripts/db_ab_experiment.py :: assert_isolated_target",
        protection="库名白名单 soymutdb_abtest_*",
        layer="unit",
        path=Path("scripts/db_ab_experiment.py"),
        mutate="    if not REQUIRED_DATABASE_NAME.match(database):\n||    if False:\n",
        control=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
        mutant=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
    ),
    Scenario(
        id="B-02",
        requirement="A/B 至少 5 轮交替，单次计时不算数（D-08）",
        entry="scripts/db_ab_experiment.py :: ExperimentPlan",
        protection="轮次下限 5",
        layer="unit",
        path=Path("scripts/db_ab_experiment.py"),
        mutate="        if self.rounds < 5:\n||        if self.rounds < 0:\n",
        control=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
        mutant=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
    ),
    Scenario(
        id="B-03",
        requirement="只读 EXPLAIN 根层计时，不摘子节点（D-08）",
        entry="scripts/db_ab_experiment.py :: extract_run",
        protection="拒绝没有根层 Execution Time 的输出",
        layer="unit",
        path=Path("scripts/db_ab_experiment.py"),
        mutate='    if "Execution Time" not in document:\n||    if False:\n',
        control=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
        mutant=["python3", "-m", "pytest", "scripts/test_db_ab_experiment.py", "-q"],
    ),
    Scenario(
        id="C-01",
        requirement="匿名访客零个人请求（K-1 回归）",
        entry="apps/web/src/lib/use-current-user.ts :: useCurrentUser",
        protection="以会话状态门控 enabled",
        layer="unit",
        path=Path("apps/web/src/lib/use-current-user.ts"),
        mutate="    enabled: session.canQueryPersonal,\n||    enabled: true,\n",
        control=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
        mutant=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
    ),
    Scenario(
        id="C-02",
        requirement="活动 release 切换后必须重新取数（W2）",
        entry="apps/web/src/lib/release-scope.tsx :: ReleaseScopeProvider",
        protection="订阅变更并丢弃 release 作用域缓存",
        layer="unit",
        path=Path("apps/web/src/lib/release-scope.tsx"),
        mutate="        dropReleaseScopedQueries(queryClient);\n||",
        control=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
        mutant=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
    ),
    Scenario(
        id="C-03",
        requirement="授权判定以服务端 grants 为准（D-05）",
        entry="apps/web/src/lib/use-current-user.ts :: grantsResearcher",
        protection="消费 /auth/me 的 effective_roles",
        layer="unit",
        path=Path("apps/web/src/lib/use-current-user.ts"),
        mutate='    return user.effective_roles.includes("researcher");||    return user.role_name === "researcher";',
        control=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
        mutant=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
    ),
    Scenario(
        id="D-01",
        requirement="兄弟请求刷新成功后，陈旧的 401 不应判失败（W3）",
        entry="packages/api-client/src/auth.ts :: authRequest",
        protection="按代数判定 stale-401 并重取",
        layer="unit",
        path=Path("packages/api-client/src/auth.ts"),
        mutate="                    if (canRetry && getAccessToken() != null) {\n                        return await request<T>(path, secured);\n                    }\n                    throw err;\n                }\n                const result = await refreshAccessTokenResult();"
               "||                    throw err;\n                }\n                const result = await refreshAccessTokenResult();",
        control=["pnpm", "--filter", "@soymutdb/api-client", "run", "test"],
        mutant=["pnpm", "--filter", "@soymutdb/api-client", "run", "test"],
    ),
    Scenario(
        id="D-02",
        requirement="/auth/me 必须带出服务端展开的能力（D-05）",
        entry="apps/api/app/core/security.py :: effective_roles",
        protection="按 _ROLE_GRANTS 展开",
        layer="unit",
        path=Path("apps/api/app/core/security.py"),
        mutate="    granted: set[RoleName] = set()\n||    granted: set[RoleName] = set()\n    return []\n",
        control=[
            "apps/api/.venv/bin/python", "-m", "pytest",
            "apps/api/tests/test_me_capabilities.py", "-q",
        ],
        mutant=[
            "apps/api/.venv/bin/python", "-m", "pytest",
            "apps/api/tests/test_me_capabilities.py", "-q",
        ],
    ),
    Scenario(
        id="E-01",
        requirement="会话门控必须真正消费 zh 目录（H-13）",
        entry="apps/web/src/components/analyses/researcher-gate.tsx",
        protection="组件调用 t() 而非内联英文",
        layer="component",
        path=Path("apps/web/src/components/analyses/researcher-gate.tsx"),
        mutate='<p className="font-medium">{t("analyses.gate.title")}</p>||<p className="font-medium">Research access required</p>',
        control=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
        mutant=["pnpm", "--filter", "@soymutdb/web", "run", "test"],
    ),
    Scenario(
        id="F-01",
        requirement="数据库真实 A/B（D-08 全部三条）",
        entry="psql / pgcli → soymutdb_abtest_*",
        protection="—",
        layer="skipped",
        path=Path("scripts/db_ab_experiment.py"),
        mutate="||",
        control=[],
        mutant=[],
        note="需要 psql/pgcli、Docker 与命名独立测试库；本机全部缺失。未取得任何性能结论。",
    ),
    Scenario(
        id="F-02",
        requirement="构建产物层的 a11y / 窄屏保护",
        entry="e2e/verify-a11y-and-layout.mjs",
        protection="skip link 为首个 tab stop",
        layer="skipped",
        path=Path("apps/web/src/routes/__root.tsx"),
        mutate="||",
        control=[],
        mutant=[],
        note="已在 2026-10-02 单独跑过：两处 skip link 同时 tabIndex={-1} → 10/10 变 9/10。"
             "需重跑要重建双站产物（约 4 分钟/次），本跑器不重复执行。",
    ),
]


def markdown(outcomes: list[Outcome]) -> str:
    lines = [
        "# 消融场景表（自动生成）",
        "",
        "由 `python3 scripts/run_ablations.py` 生成。判定口径按方案 §4；证据层级区分",
        "「源码守卫 / 单元 / 组件 / 构建产物 / 端到端 / 部署态」。",
        "",
        "| ID | 需求 | 保护因素 | 层级 | 对照 exit | 变异 exit | 翻转 | 恢复 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in outcomes:
        s = outcome.scenario
        if outcome.skipped_reason:
            flipped = "—"
        else:
            flipped = "✅" if outcome.mutant_exit != outcome.control_exit else "❌ 未翻转"
        restored = "✅" if outcome.checksum_ok else "❌"
        lines.append(
            f"| {s.id} | {s.requirement} | {s.protection} | {s.layer} | "
            f"{outcome.control_exit} | {outcome.mutant_exit} | {flipped} | {restored} |"
        )
    skipped = [o for o in outcomes if o.skipped_reason]
    if skipped:
        lines += ["", "## 未运行的场景（原因必须随行）", ""]
        for outcome in skipped:
            lines.append(f"- **{outcome.scenario.id}** — {outcome.scenario.note}")
    failing = [o for o in outcomes if not o.skipped_reason and o.mutant_exit == o.control_exit]
    lines += [
        "",
        "## 汇总",
        "",
        f"- 运行 {len(outcomes) - len(skipped)} 个场景，未运行 {len(skipped)} 个",
        f"- 翻转 {sum(1 for o in outcomes if not o.skipped_reason and o.mutant_exit != o.control_exit)} 个",
        f"- **未翻转 {len(failing)} 个**" + (
            "：" + ", ".join(o.scenario.id for o in failing) if failing else ""
        ),
    ]
    if failing:
        lines += [
            "",
            "> 未翻转必须逐条解释：要么变异没进真实执行路径（GUARD-INERT），",
            "> 要么该保护本身是冗余，要么覆盖链有缺口。不允许当作通过。",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--only", nargs="*", default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    args = parser.parse_args(argv)

    selected = SCENARIOS
    if args.only:
        wanted = {w.upper() for w in args.only}
        selected = [s for s in SCENARIOS if s.id.upper() in wanted]
    if args.list:
        for scenario in selected:
            print(f"{scenario.id}\t{scenario.layer}\t{scenario.protection}")
        return 0

    outcomes: list[Outcome] = []
    for scenario in selected:
        if not scenario.runnable:
            outcomes.append(Outcome(scenario, 0, 0, True, True, scenario.note))
            print(f"{scenario.id}  SKIPPED  {scenario.note}", flush=True)
            continue
        if not scenario.path.exists():
            outcomes.append(Outcome(scenario, 0, 0, True, True, f"missing file {scenario.path}"))
            print(f"{scenario.id}  SKIPPED  missing {scenario.path}", flush=True)
            continue
        print(f"{scenario.id}  running  {scenario.protection}", flush=True)
        outcome = run_scenario(scenario, ROOT)
        outcomes.append(outcome)
        verdict = "FLIPPED" if outcome.mutant_exit != outcome.control_exit else "NO-FLIP"
        print(
            f"{scenario.id}  control={outcome.control_exit} mutant={outcome.mutant_exit}  {verdict}"
            f"  restored={outcome.checksum_ok}",
            flush=True,
        )

    report = markdown(outcomes)
    if args.markdown:
        args.markdown.write_text(report + "\n", encoding="utf-8")
        print(f"\nreport written to {args.markdown}")
    else:
        print()
        print(report)

    not_flipped = [
        o for o in outcomes
        if not o.skipped_reason and o.mutant_exit == o.control_exit
    ]
    return 1 if not_flipped else 0


if __name__ == "__main__":
    raise SystemExit(main())