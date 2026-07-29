# bounded-dev / skills

Small, sharp skills for working with AI coding agents. Copy one in and go.

A skill is just a folder with a `SKILL.md` — plain, on-demand instructions an agent loads when they're relevant. It's a simple, increasingly common format across coding agents; [Claude Code](https://claude.com/claude-code) is one host, and these adapt easily to others.

> Part of [bounded.dev](https://bounded.dev) — Paul Grimshaw on software architecture and AI-assisted development.

## Skills

### 🛬 flight-status 🛬

A read-only snapshot of your current session. It flags anything you've decided, drafted, or produced — plus uncommitted, unpushed, or stashed git work — that isn't yet saved anywhere durable.

The premise: **AI sessions are disposable, your project is not.** Before you close a session, you want to know nothing worth keeping is still floating in the chat and nowhere else. Run it before you walk away:

```
──────────  🛬  FLIGHT STATUS  🛬  ──────────
🔴  disposable-sessions blog post — angle agreed, not written down
🟠  auth refactor — uncommitted in the working tree
🟠  spike branch — 3 commits, unpushed
──────────────────────────────────────────────
```

- 🔴 **only in the chat** — gone the instant you close the session
- 🟠 **on disk but not landed** — uncommitted, unpushed, or stashed; survives the close, but isn't durable
- 🟢 **all captured** — safe to close

→ [`skills/flight-status`](skills/flight-status/SKILL.md)

## Evals

A skill is a prompt, so the only way to know a wording change hasn't broken it
is to run it. [`evals/`](evals/) builds throwaway git repos, runs the skill
against them headlessly, and grades what comes back — format and side effects
deterministically, item detection and colour with an LLM judge.

```bash
python3 evals/run.py
```

Python stdlib only, nothing to install. See [`evals/README.md`](evals/README.md).

## Install

A skill goes wherever your agent looks for one. For Claude Code that's `.claude/skills/` — user-level (`~/.claude/skills/`) for every project, or a repo's own `.claude/skills/` for just that one.

**Quick — grab just this skill.** Downloads the file, runs nothing:

```bash
mkdir -p ~/.claude/skills/flight-status
curl -sSL https://raw.githubusercontent.com/bounded-dev/skills/main/skills/flight-status/SKILL.md \
  -o ~/.claude/skills/flight-status/SKILL.md
```

**Or clone and copy** — handy for browsing or taking several:

```bash
git clone https://github.com/bounded-dev/skills && cd skills
cp -R skills/flight-status ~/.claude/skills/
```

Then invoke it — in Claude Code, `/flight-status`.

## More coming

This is the start of a collection. ⭐ the repo to follow along.

## License

[MIT](LICENSE).
