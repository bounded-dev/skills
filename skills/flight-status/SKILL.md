---
name: flight-status
description: Read-only snapshot of the current session — flags anything decided, drafted, or produced, plus uncommitted, unpushed, or stashed git work, that isn't yet saved into the project's durable stores. Run before stepping away to see what's outstanding and whether the session is safe to close.
---

# flight-status

Flag anything this session produced that isn't durably saved yet — work you'd lose or have to reconstruct if you walked away now. Sessions are disposable; the project is not. Two loss surfaces set the colour:

- 🔴 **Only in the chat** — a decision, draft, fact, answer, or follow-up never written down. Gone the instant you close.
- 🟠 **On disk, not landed** — uncommitted changes, untracked files, unpushed commits, stashes, or files the session wrote outside the repo (scratchpad, tmp). Survives the close, but isn't durable.

1. Read the project's own docs to learn its durable stores — issue tracker, specs, ADRs, glossary, committed history. Projects differ; don't assume.
2. List what the session produced across both surfaces. For the on-disk 🟠 items run `git status`, `git stash list`, and `git log --branches --not --remotes`, and recall any files written outside the repo.
3. Verify each actually landed in a store. Chat-only → 🔴. Uncommitted, unpushed, stashed, or out-of-repo → 🟠.

Render as a **banner block** so it stands out when you scroll back — a `FLIGHT STATUS` header rule, one punchy line per outstanding item, and a closing rule. Every item leads with its own dot — 🔴 if it's chat-only, 🟠 if it's on disk — so the colours repeat down the list, one per line. Each line is a short label plus a few words of context: for 🔴 items, a hint of where it should land; for 🟠 items, where it sits. Nothing outstanding → a single 🟢 line.

```
──────────  🛬  FLIGHT STATUS  🛬  ──────────
🔴  disposable-sessions blog post — angle agreed, not in web/blog/ideas
🔴  naming rationale — flight-status + git-status choices, not in any ADR
🟠  flight-status skill — uncommitted in 4 repos
🟠  git-status rename — uncommitted in 4 repos
──────────────────────────────────────────────
```

All clear:

```
──────────  🛬  FLIGHT STATUS  🛬  ──────────
🟢  All captured. Safe to close.
──────────────────────────────────────────────
```

Expand only if asked — then give each item's where-it-belongs and the one action to save it.

Rules:
- Read-only — never save anything yourself.
- Outstanding only — list what's in flight; never mention what's already saved, and no preamble or recap of what you checked.
- Memory doesn't count as saved — the session being disposable is the exact risk this checks.
- Only flag a gap you verified against a real store.
