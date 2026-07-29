You are grading the output of a skill that reports what work in a coding session
has not yet been saved anywhere durable. You are not being asked whether the
output is good. You are being asked, item by item, whether it says what it was
supposed to say.

The output is a banner. Each line inside it leads with a status dot:

- 🔴 the thing exists only in the chat — nothing on disk, nothing committed
- 🟠 the thing is on disk but not landed — uncommitted, untracked, unpushed,
  stashed, or written outside the repo
- 🟢 nothing is outstanding

You are given `expected_items` (each with a `dot` and a plain-English `about`),
`must_not_appear` (things that are already saved, and so must be absent), and
`skill_output`.

## How to judge

For each entry in `expected_items`, find the line in `skill_output` that refers
to the same underlying thing.

- **Match on substance, not wording.** The skill writes terse labels. "auth
  retry logic — uncommitted" matches an expected item about the edit to
  `src/auth.ts`. Do not require the filename, the phrasing, or the word order to
  line up. If a reader who knew the session would agree the line is about that
  thing, it matches.
- If a matching line exists and its dot is correct, add it to `matched`.
- If a matching line exists but leads with the wrong dot, add it to
  `wrong_colour` — not to `matched` and not to `missed`.
- If no line refers to that thing at all, add its `about` text to `missed`.

Then check `must_not_appear`. If a line in the output refers to one of those
already-saved things, add a short description of the offending line to
`false_positives`.

Finally, any banner line that matches no expected item and no forbidden item is
also a `false_positive` — the skill invented something. Describe it briefly.

## Rules

- Judge only what is in `skill_output`. Do not speculate about the repo.
- One output line may satisfy only one expected item. Two expected items
  collapsed into a single line means one is `missed`.
- Grade the dot that leads the line, not any other emoji in the text.
- Be strict about colour. 🔴 and 🟠 mean materially different things — one is
  lost on close, the other survives — so a swapped dot is a real failure, never
  a near-miss to be waved through as `matched`.
- Be generous about phrasing. Terseness is the skill working as designed, and
  penalising it would make the eval measure verbosity instead of correctness.
- `notes` is one short sentence, or empty. It is for a human skimming a
  failure, not for your reasoning.

Return only the JSON object.
