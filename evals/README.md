# evals

A skill is a prompt, so its contract is behavioural: does the agent flag the
right things, in the right shape, and refrain from doing what the skill says it
must never do? That is not something you can check by reading a diff. This
harness checks it by running the skill for real.

Each case builds a throwaway git repo, runs the skill against it headlessly,
and grades the result. Python 3 stdlib only — no dependencies to install.

## Run it

```bash
python3 evals/run.py                          # everything, 3 repeats per case
python3 evals/run.py --case mixed --repeat 1  # one case, once — for iterating
python3 evals/run.py --case read-only --keep  # leave the fixture behind to inspect
python3 evals/run.py --model opus             # pin the model under test
```

Exits non-zero if any case fails, so it drops straight into CI.

Useful flags: `--jobs` (concurrency, default 4), `--timeout` (per call, default
240s), `--judge-model` (default `sonnet`), `--verbose` (print what the skill
actually said), `--flaky-threshold` (accept a pass *ratio* rather than demanding
every repeat pass).

## How a case works

Cases are JSON, one file each, in `cases/`.

```json
{
  "name": "uncommitted",
  "contracts": ["C1", "C4"],
  "why": "The simplest orange surface: a tracked file modified in the working tree.",
  "setup": ["printf '...' >> src/auth.ts"],
  "seed": "I added a token refresh helper to src/auth.ts this session...",
  "expect": {
    "items": [{ "dot": "🟠", "about": "the edit to src/auth.ts, uncommitted" }],
    "forbid": ["docs/decisions/0001-postgres.md or any already-committed file"]
  }
}
```

`setup` shell commands run on top of a common base fixture: a small `acme-api`
repo, fully committed and pushed, with a `CLAUDE.md` that names its durable
stores (`docs/decisions/`, `docs/specs/`, GitHub issues) — the skill's first
instruction is to go and find those, so the fixture has to have some. Its
`origin` is a **local bare repo**, which makes unpushed commits genuinely
detectable without touching the network.

`seed` stands in for the session so far. `expect.items` are graded on substance,
not wording. `expect.forbid` lists things that are already saved and so must
*not* appear — the false-positive half, which matters as much as the detection
half.

Optional: `relax` disables individual layer-1 checks (`count`, `prose`) for
cases that exist to isolate a different contract; `ask` overrides the invocation
line. Both carry a `relax_why` / inline explanation in the cases that use them.

## Grading, in two layers

**Layer 1 — deterministic, free, no model.** Banner present and closed, every
line leading with a status dot, item count as expected, no prose outside the
banner, all-clear cases collapsing to a single 🟢.

And the one that matters most: **side effects**. The subject is handed `Write`,
`Edit`, `git add`, `git commit` and `git push` on purpose — asserting that a
skill saves nothing only means something if saving was available to it. Every
working-tree file is
hashed before and after the run, alongside `git status --porcelain`, the stash
list, the full commit graph, and the diff. Any change fails the case. The skill
claims it is read-only; that claim gets asserted rather than trusted. Git
internals are compared semantically instead of by file hash, because read-only
plumbing like `git status` legitimately rewrites `.git/index` and hashing that
would report violations that never happened.

Layer 1 failures short-circuit — no point paying a judge to read a banner
already known to be malformed.

**Layer 2 — an LLM judge** (`judge.md`), for the part regex cannot do: whether a
given line refers to the same underlying thing as an expected item, and whether
its dot is right. The rubric pushes the judge to be generous about phrasing and
strict about colour, since terseness is the skill working as designed but 🔴 and
🟠 mean materially different things. The judge runs on a separate model from the
subject, in an empty directory with no tools, so it can neither grade itself nor
peek at the fixture.

## What the cases cover

Contracts are lifted from `skills/flight-status/SKILL.md` and each case names
the ones it exercises, so a failure points at a line of the skill.

| Contract | Promise |
|---|---|
| C1 | 🟠 for uncommitted / untracked / unpushed / stashed / out-of-repo |
| C2 | 🔴 for things that exist only in the chat |
| C3 | Nothing outstanding → a single 🟢 line |
| C4 | Banner shape: rule, dot-led lines, closing rule |
| C5 | Read-only — never saves anything |
| C6 | Outstanding only — no already-saved items, no preamble or recap |
| C7 | Memory doesn't count as saved |
| C8 | Only flag gaps verified against a real store |
| C9 | Expand only if asked |

Thirteen cases: five narrow 🟠 detectors (one per surface, so a regression names
its own cause), two 🔴, a mixed case, an all-clear, a no-false-positives case,
and three behavioural ones (read-only, no-expansion, expand-on-ask).

## Baseline

At the time of writing, on the default model: **12–13 of 13 cases**, ~3.5
minutes for a full run. Every contract sits at 100% except C6.

The one live finding is a **recap footer**. Occasionally — roughly one run in
nine, and most often on `all-clear`, where a bare 🟢 line seems to invite
justification — the skill appends a sentence after the closing rule:

> Working tree clean, no stashes, no unpushed commits. The session's only
> outcome was reaffirming an existing ADR — nothing new to record.

`SKILL.md` forbids exactly this: *"never mention what's already saved, and no
preamble or recap of what you checked."* It is a real, low-rate deviation, left
unfixed on purpose — the eval was built to measure the skill as written, and
silently editing the subject to make its own test pass would defeat the point.
Which case catches it varies run to run, so treat a lone C6 failure as this
known behaviour rather than a fresh regression.

## Caveats worth knowing

**The seed is not a real session.** A single-shot prompt is the only way to
inject session history through the CLI, so 🔴 cases test *"recognises a stated
thing as unsaved"* rather than *"remembers something from forty turns ago"*.
That is the weaker half of the eval, and the gap is real — a skill could pass
every 🔴 case here and still miss things in a long live session.

**Output varies between runs.** Hence `--repeat`. A case passes only when every
repeat passes; loosen with `--flaky-threshold 0.67` if you want to distinguish
"broken" from "occasionally drifts".

**Item decomposition is a judgment call.** One session event can defensibly be
reported as one line or two, and a seed containing two clauses ("must be
audit-logged *before it ships*") or an open question ("we weren't sure where it
belonged") will sometimes be split into two items and sometimes not. Where a
case proved sensitive to this, the seed was tightened until only one reading
survived — rather than loosening the expectation, since an eval that needs a
generous judge to pass is measuring the judge.

**Denied tools look exactly like skill failures.** The first baseline run graded
at 5/13, and most of the failures were the harness's fault: the subject was
sandboxed, its `git log --branches --not --remotes` call was silently denied,
and it honestly appended "I couldn't check unpushed commits — approval denied"
to its output. That trailing sentence then tripped the no-prose check. Granting
the skill the commands it is documented to run took the same suite to 12/13 and
cut run time by a third. If you add a case and it fails on stray prose, suspect
the allow-list in `SUBJECT_TOOLS` before you suspect the skill.

## Cost

A full run is 13 cases × 3 repeats × (1 subject call + 1 judge call) — around 78
short calls, a few minutes at the default concurrency. Iterate with `--case` and
`--repeat 1`.

## Adding a case

Drop a JSON file in `cases/`. Then break it on purpose — demand an item the
skill cannot produce and confirm the run fails with that item in `missed`. A
case that has never failed has not been shown to test anything.
