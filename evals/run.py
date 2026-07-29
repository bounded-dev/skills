#!/usr/bin/env python3
"""Eval harness for the skills in this repo.

Each case builds a throwaway git fixture, runs the skill under test against it
via `claude -p`, then grades the output in two layers: deterministic Python
assertions on format and side effects, then an LLM judge on the semantics.

Stdlib only. Run `python3 evals/run.py --help`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
CASES_DIR = EVALS_DIR / "cases"
JUDGE_PROMPT = EVALS_DIR / "judge.md"

# Fixtures live outside the repo, in the conventional ephemeral scratch dir.
SCRATCH = Path.home() / "dev" / "bounded-skills-tmp"

DOTS = ("\U0001f534", "\U0001f7e0", "\U0001f7e2")  # red, orange, green
RULE_CHAR = "─"
BANNER_MARK = "FLIGHT STATUS"

# The skill is instructed to run `git status`, `git stash list` and
# `git log --branches --not --remotes`. In a headless run anything outside the
# allow-list is denied silently, and the skill then honestly reports it could
# not verify — which grades as a skill failure when it is really the harness
# starving it. So every read-only inspection command it is told to use is
# granted explicitly.
#
# Write-capable tools are granted too, deliberately: C5 asserts the skill does
# not save anything, and that assertion is only meaningful if saving was
# actually available. The before/after snapshot is what enforces it.
SUBJECT_TOOLS = ",".join(
    [
        "Read",
        "Glob",
        "Grep",
        "Write",
        "Edit",
        "Bash(git status:*)",
        "Bash(git stash:*)",
        "Bash(git log:*)",
        "Bash(git diff:*)",
        "Bash(git branch:*)",
        "Bash(git remote:*)",
        "Bash(git rev-parse:*)",
        "Bash(git rev-list:*)",
        "Bash(git show:*)",
        "Bash(git ls-files:*)",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(git push:*)",
        "Bash(ls:*)",
        "Bash(find:*)",
        "Bash(cat:*)",
        "Bash(head:*)",
        "Bash(wc:*)",
    ]
)

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "matched": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "expected": {"type": "string"},
                    "line": {"type": "string"},
                },
                "required": ["expected", "line"],
                "additionalProperties": False,
            },
        },
        "missed": {"type": "array", "items": {"type": "string"}},
        "wrong_colour": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "expected": {"type": "string"},
                    "line": {"type": "string"},
                    "wanted_dot": {"type": "string"},
                    "got_dot": {"type": "string"},
                },
                "required": ["expected", "line", "wanted_dot", "got_dot"],
                "additionalProperties": False,
            },
        },
        "false_positives": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["matched", "missed", "wrong_colour", "false_positives", "notes"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# fixture
# --------------------------------------------------------------------------

BASE_FILES = {
    "CLAUDE.md": """# acme-api

Payments service.

## Durable stores

- Architecture decisions are recorded as ADRs in `docs/decisions/`.
- Specs live in `docs/specs/`.
- Work in progress is tracked as GitHub issues.

Nothing is considered settled until it is written into one of those.
""",
    "README.md": "# acme-api\n\nSee docs/ for details.\n",
    "src/auth.ts": "export function authenticate(token: string) {\n  return verify(token);\n}\n",
    "src/retry.ts": "export function retry(fn) {\n  return fn();\n}\n",
    "docs/decisions/0001-postgres.md": (
        "# 0001 — Use Postgres\n\nStatus: accepted\n\n"
        "We use Postgres for primary storage.\n"
    ),
    "docs/specs/.gitkeep": "",
}


def sh(cmd: str, cwd: Path, check: bool = True) -> str:
    """Run a shell command in cwd, returning stdout."""
    proc = subprocess.run(
        cmd, cwd=cwd, shell=True, capture_output=True, text=True
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed in {cwd}: {cmd}\n{proc.stderr}")
    return proc.stdout


def build_fixture(dest: Path, skill: str) -> Path:
    """Create a git repo with a local bare origin, and the skill symlinked in.

    Returns the working repo path. The bare origin is a sibling, so unpushed
    commits are detectable without touching the network.
    """
    if dest.exists():
        shutil.rmtree(dest)
    repo = dest / "repo"
    origin = dest / "origin.git"
    repo.mkdir(parents=True)
    origin.mkdir(parents=True)

    sh("git init -q --bare", origin)
    sh("git init -q -b main", repo)
    # Keep the fixture's git identity self-contained and unsigned; the user's
    # signing key must never be dragged into throwaway commits.
    sh("git config user.name 'Eval Fixture'", repo)
    sh("git config user.email 'eval@example.invalid'", repo)
    sh("git config commit.gpgsign false", repo)

    for rel, body in BASE_FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    skills_dir = repo / ".claude" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / skill).symlink_to(REPO_ROOT / "skills" / skill)

    sh("git add -A", repo)
    sh("git commit -qm 'initial commit'", repo)
    sh(f"git remote add origin {origin}", repo)
    sh("git push -q -u origin main", repo)
    return repo


# --------------------------------------------------------------------------
# side-effect snapshot (contract C5: read-only)
# --------------------------------------------------------------------------


def snapshot(repo: Path) -> dict:
    """Capture fixture state for before/after comparison.

    Working-tree files are hashed individually. Git internals are compared
    semantically rather than by file hash — plumbing like `git status`
    legitimately rewrites `.git/index` stat metadata on a read-only call, and
    hashing that would produce false violations.
    """
    files = {}
    for path in sorted(repo.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        rel = str(path.relative_to(repo))
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "files": files,
        "porcelain": sh("git status --porcelain", repo, check=False),
        "stash": sh("git stash list", repo, check=False),
        "log": sh("git log --all --format=%H%d", repo, check=False),
        "diff": sh("git diff HEAD", repo, check=False),
    }


def diff_snapshots(before: dict, after: dict) -> list[str]:
    problems = []
    b, a = before["files"], after["files"]
    for rel in sorted(set(a) - set(b)):
        problems.append(f"file created: {rel}")
    for rel in sorted(set(b) - set(a)):
        problems.append(f"file deleted: {rel}")
    for rel in sorted(set(b) & set(a)):
        if b[rel] != a[rel]:
            problems.append(f"file modified: {rel}")
    for key in ("porcelain", "stash", "log", "diff"):
        if before[key] != after[key]:
            problems.append(f"git state changed: {key}")
    return problems


# --------------------------------------------------------------------------
# invocation
# --------------------------------------------------------------------------


def run_claude(
    prompt: str,
    cwd: Path,
    model: str | None,
    allowed_tools: str,
    timeout: int,
    permission_mode: str,
    json_schema: dict | None = None,
) -> tuple[str, str]:
    """Invoke the CLI headlessly. Returns (result_text, error_or_empty)."""
    cmd = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--permission-mode",
        permission_mode,
        "--allowed-tools",
        allowed_tools,
    ]
    if model:
        cmd += ["--model", model]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return "", f"timed out after {timeout}s"

    if proc.returncode != 0:
        return "", f"claude exited {proc.returncode}: {proc.stderr.strip()[:400]}"

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "", f"unparseable CLI output: {proc.stdout[:400]}"

    if envelope.get("is_error"):
        return "", f"session error: {str(envelope.get('result'))[:400]}"
    return str(envelope.get("result", "")), ""


# --------------------------------------------------------------------------
# layer 1 — deterministic format assertions
# --------------------------------------------------------------------------


@dataclass
class Banner:
    items: list[str] = field(default_factory=list)
    outside: str = ""
    found: bool = False


def parse_banner(text: str) -> Banner:
    """Pull the banner block out of the response.

    Tolerates the whole thing being wrapped in a fenced code block, which is a
    presentation choice the skill doesn't forbid.
    """
    lines = text.splitlines()
    header_idx = next(
        (i for i, ln in enumerate(lines) if BANNER_MARK in ln and RULE_CHAR in ln),
        None,
    )
    if header_idx is None:
        return Banner()

    close_idx = None
    for i in range(header_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped and set(stripped) <= {RULE_CHAR}:
            close_idx = i
            break
    if close_idx is None:
        return Banner()

    items = [ln.strip() for ln in lines[header_idx + 1 : close_idx] if ln.strip()]
    outside_lines = lines[:header_idx] + lines[close_idx + 1 :]
    outside = "\n".join(
        ln for ln in outside_lines if ln.strip() and not ln.strip().startswith("```")
    ).strip()
    return Banner(items=items, outside=outside, found=True)


def layer1(case: dict, banner: Banner, effects: list[str]) -> list[str]:
    """Format and side-effect checks. Returns a list of failure strings."""
    failures = []

    if effects:
        failures.append("C5 read-only violated: " + "; ".join(effects))

    if not banner.found:
        failures.append("C4 no FLIGHT STATUS banner block found")
        return failures

    if not banner.items:
        failures.append("C4 banner is empty")
        return failures

    for line in banner.items:
        if not line.startswith(DOTS):
            failures.append(f"C4 line does not lead with a status dot: {line!r}")

    expected = case.get("expect", {}).get("items", [])
    is_green = len(expected) == 1 and expected[0]["dot"] == "\U0001f7e2"

    if is_green:
        if len(banner.items) != 1 or not banner.items[0].startswith("\U0001f7e2"):
            failures.append(
                f"C3 expected exactly one green line, got {len(banner.items)}: "
                f"{banner.items}"
            )

    # A case may relax individual layer-1 checks so that it isolates the
    # contract it exists to test. Relaxing never disables the judge, so items
    # are still graded for presence, colour, and invention.
    relax = set(case.get("relax", []))

    if "count" not in relax and len(banner.items) != len(expected):
        failures.append(
            f"C4 expected {len(expected)} item line(s), got {len(banner.items)}"
        )
    if "prose" not in relax and banner.outside:
        failures.append(f"C6 prose outside the banner: {banner.outside[:200]!r}")

    return failures


# --------------------------------------------------------------------------
# layer 2 — semantic judge
# --------------------------------------------------------------------------


def build_judge_prompt(case: dict, output: str) -> str:
    rubric = JUDGE_PROMPT.read_text()
    payload = {
        "expected_items": case.get("expect", {}).get("items", []),
        "must_not_appear": case.get("expect", {}).get("forbid", []),
        "skill_output": output,
    }
    return f"{rubric}\n\n## Input\n\n```json\n{json.dumps(payload, indent=2, ensure_ascii=False)}\n```\n"


def layer2(case: dict, output: str, judge_model: str, timeout: int) -> tuple[list[str], dict]:
    prompt = build_judge_prompt(case, output)
    # The judge runs in a neutral empty directory with no tools, so it can't
    # pick up the fixture's CLAUDE.md or inspect the repo it's grading.
    neutral = SCRATCH / "judge-cwd"
    neutral.mkdir(parents=True, exist_ok=True)

    text, err = run_claude(
        prompt,
        cwd=neutral,
        model=judge_model,
        allowed_tools="",
        timeout=timeout,
        permission_mode="plan",
        json_schema=JUDGE_SCHEMA,
    )
    if err:
        return [f"judge failed: {err}"], {}

    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        verdict = json.loads(cleaned)
    except json.JSONDecodeError:
        return [f"judge returned non-JSON: {text[:300]}"], {}

    failures = []
    for miss in verdict.get("missed", []):
        failures.append(f"missed expected item: {miss}")
    for wrong in verdict.get("wrong_colour", []):
        failures.append(
            f"wrong colour for {wrong.get('expected')!r}: "
            f"wanted {wrong.get('wanted_dot')}, got {wrong.get('got_dot')}"
        )
    for fp in verdict.get("false_positives", []):
        failures.append(f"false positive: {fp}")
    return failures, verdict


# --------------------------------------------------------------------------
# case execution
# --------------------------------------------------------------------------


@dataclass
class RunResult:
    case: str
    attempt: int
    passed: bool
    failures: list[str]
    output: str
    seconds: float


def run_once(case: dict, attempt: int, args) -> RunResult:
    started = time.time()
    name = case["name"]
    fixture_dir = SCRATCH / f"eval-{name}-{attempt}"
    skill = case.get("skill", "flight-status")

    try:
        repo = build_fixture(fixture_dir, skill)
        for cmd in case.get("setup", []):
            sh(cmd, repo)

        before = snapshot(repo)
        ask = case.get("ask", f"Now run /{skill}")
        prompt = f"{case['seed'].strip()}\n\n{ask}"
        output, err = run_claude(
            prompt,
            cwd=repo,
            model=args.model,
            allowed_tools=SUBJECT_TOOLS,
            timeout=args.timeout,
            permission_mode="acceptEdits",
        )
        after = snapshot(repo)

        if err:
            return RunResult(name, attempt, False, [err], "", time.time() - started)

        effects = diff_snapshots(before, after)
        failures = layer1(case, parse_banner(output), effects)

        # Layer 1 failures short-circuit — no point paying a judge to read a
        # banner that is already known to be malformed.
        if not failures:
            failures, _ = layer2(case, output, args.judge_model, args.timeout)

        return RunResult(
            name, attempt, not failures, failures, output, time.time() - started
        )
    except Exception as exc:  # harness bug or fixture failure
        return RunResult(
            name, attempt, False, [f"harness error: {exc}"], "", time.time() - started
        )
    finally:
        if not args.keep and fixture_dir.exists():
            shutil.rmtree(fixture_dir, ignore_errors=True)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

GREEN, RED, YELLOW, DIM, RESET = (
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[2m",
    "\033[0m",
)


def load_cases(selector: str | None) -> list[dict]:
    cases = []
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text())
        case["_file"] = path.name
        cases.append(case)
    if selector:
        wanted = {s.strip() for s in selector.split(",")}
        cases = [c for c in cases if c["name"] in wanted]
        missing = wanted - {c["name"] for c in cases}
        if missing:
            sys.exit(f"unknown case(s): {', '.join(sorted(missing))}")
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", help="comma-separated case names (default: all)")
    ap.add_argument("--repeat", type=int, default=3, help="runs per case (default 3)")
    ap.add_argument("--model", help="model under test (default: CLI default)")
    ap.add_argument("--judge-model", default="sonnet", help="grading model")
    ap.add_argument("--jobs", type=int, default=4, help="concurrent runs")
    ap.add_argument("--timeout", type=int, default=240, help="per-call timeout, seconds")
    ap.add_argument(
        "--flaky-threshold",
        type=float,
        default=1.0,
        help="pass ratio required per case (default 1.0 = every repeat must pass)",
    )
    ap.add_argument("--keep", action="store_true", help="retain fixtures for inspection")
    ap.add_argument("--verbose", action="store_true", help="print full skill output")
    args = ap.parse_args()

    cases = load_cases(args.case)
    if not cases:
        sys.exit("no cases found")

    SCRATCH.mkdir(parents=True, exist_ok=True)
    jobs = [(c, n + 1) for c in cases for n in range(args.repeat)]
    print(
        f"{len(cases)} case(s) x {args.repeat} repeat(s) = {len(jobs)} runs, "
        f"{args.jobs} at a time\n"
    )

    started = time.time()
    results: dict[str, list[RunResult]] = {c["name"]: [] for c in cases}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_once, c, n, args): (c, n) for c, n in jobs}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            results[res.case].append(res)
            mark = f"{GREEN}pass{RESET}" if res.passed else f"{RED}FAIL{RESET}"
            print(f"  {mark}  {res.case} #{res.attempt}  {DIM}{res.seconds:.0f}s{RESET}")
            for failure in res.failures:
                print(f"        {RED}-{RESET} {failure}")
            if args.verbose and res.output:
                indented = "\n".join(f"        {ln}" for ln in res.output.splitlines())
                print(f"{DIM}{indented}{RESET}")
            # Runs take minutes; keep progress visible when piped to a file.
            sys.stdout.flush()

    print("\n" + "=" * 60)
    passed_cases = 0
    contract_stats: dict[str, list[int]] = {}
    for case in cases:
        runs = results[case["name"]]
        wins = sum(1 for r in runs if r.passed)
        ratio = wins / len(runs) if runs else 0.0
        ok = ratio >= args.flaky_threshold
        passed_cases += ok
        colour = GREEN if ok else (YELLOW if wins else RED)
        print(
            f"{colour}{'PASS' if ok else 'FAIL'}{RESET}  {case['name']:<24} "
            f"{wins}/{len(runs)}  {DIM}{','.join(case.get('contracts', []))}{RESET}"
        )
        for contract in case.get("contracts", []):
            stats = contract_stats.setdefault(contract, [0, 0])
            stats[0] += wins
            stats[1] += len(runs)

    print(
        f"\n{passed_cases}/{len(cases)} cases passed "
        f"in {time.time() - started:.0f}s"
    )
    rollup = "  ".join(
        f"{c}:{s[0]}/{s[1]}" for c, s in sorted(contract_stats.items())
    )
    print(f"{DIM}contracts  {rollup}{RESET}")
    return 0 if passed_cases == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
