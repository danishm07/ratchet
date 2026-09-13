# TASK — Ratchet: generalize the graders, then close the loop

You are working in `~/Documents/ratchet`. Read `CLAUDE.md` first — it has the
engineering rules and they are binding. Read `README.md` for what the project is.

**Hard deadline: 6:00 PM Central today.** At 5:15 PM stop building regardless of
state, make sure the repo runs, and update the README. A working smaller thing
beats a broken larger one.

Work in this order. Do not start Phase 2 until Phase 1's acceptance test passes.

---

## Phase 0 — prove the existing thing runs (target: 10 minutes)

Do not change any code in this phase.

```bash
cd ~/Documents/ratchet
python3 -m venv .venv && source .venv/bin/activate
pip install httpx pytest
python -m pytest tests -q                      # expect: 13 passed
python -m ratchet run --source fixture         # expect: ~2 min, writes data/runs/report.html
```

Expected output shape:
```
extraction: 15 items -> 11 checkable -> 10 rules -> 60 cases
judge validation: 17/20 agreement with human labels = 85% on rule 'legalname'
v1: 51/60 = 0.85
...
```

If anything fails, fix it before moving on and tell me what was broken. Model
calls go through `claude -p` by default (`RATCHET_BACKEND=cli`), so no API key
is needed. First run is slow; every run after is cached and near-instant.

---

## Phase 1 — make the graders general (target: 60 minutes)

### The problem

`ratchet/extract.py` has a hardcoded `RULE_MENU` of ten rules and
`ratchet/judge.py` has a hand-written grader function for each. That means the
system can only ever find failures someone anticipated. Shreya Shankar's UIST
2024 result names this exactly — **criteria drift**: *"users need criteria to
grade outputs, but grading outputs helps users define criteria."* A fixed menu
defined in advance is already behind the real failure distribution.

### What to build

**1. `ratchet/genjudge.py` — generate a grader from a failure description.**

Follow the G-Eval pattern (DeepEval / promptfoo). Two LLM calls, both cached:

- `derive_spec(expectation: str) -> GraderSpec` — decide whether the criterion
  is mechanically checkable. Return a structured spec, **never executable code**:

  ```python
  @dataclass
  class GraderSpec:
      kind: Literal["regex_present", "regex_absent", "numeric_match", "llm_rubric"]
      pattern: str | None          # for regex kinds
      field: str | None            # for numeric_match: which brief key to compare against
      steps: list[str]             # for llm_rubric: the generated evaluation steps
      rationale: str
  ```

- `grade_generated(spec, output, brief) -> Verdict` — execute the spec. Regex
  and numeric kinds run in Python with no model call. `llm_rubric` sends the
  generated steps plus the output and asks for `{passed, reason, quote}`.

**Do not generate and `exec()` Python.** A structured spec is safer, cacheable,
inspectable, and enough for the common cases.

**2. Rewrite `ratchet/extract.py` to stop classifying into a menu.**

The extraction prompt no longer receives a list of rules to choose from. It
reads the failure report and emits:

```json
{"checkable": true,
 "rule_id": "return_window",          // slug it derives itself
 "title": "wrong return window stated",
 "expectation": "the letter states a 30-day return window",
 "is_fix": false,
 "confidence": 0.9}
```

Then dedupe near-identical rules by asking the model whether rule A subsumes
rule B (SPADE's subsumption trick), keeping the higher-confidence one and still
preferring anything derived from a fix.

**3. Keep the ten hand-written graders — they become the ground truth.**

Do not delete `judge.py`. It is now the reference implementation used to prove
the generated graders work.

### Acceptance test — this is the whole point of Phase 1

Add `python -m ratchet compare-graders`, which:

1. Loads the ten known rules and their `expectation` strings
2. Generates a grader spec for each via `genjudge.derive_spec`
3. Runs **both** the hand-written grader and the generated grader over all
   60 cases × 5 versions = 300 gradings
4. Reports agreement, overall and per rule

```
generated vs hand-written graders: 271/300 = 90.3% agreement
  perfect:    totals, currency, assume, excl, daterange, headings
  divergent:  date 42/60, termmatch 51/60, percent 55/60
```

Write the number into the README under §4 whatever it turns out to be. **If
agreement is poor, report it as poor.** A measured 74% is worth more than a
claimed 95%, and "here is where generation fails" is a better finding than
silence. Print the specific disagreements so they can be inspected.

---

## Phase 2 — close the loop (target: 60 minutes)

### What to build

`ratchet/loop.py` — given one regression from the matrix, run an autonomous
fix loop that ends at a **pull request a human must merge**.

This is the standard production shape (GitHub Copilot coding agent, Cursor
background agents, Devin): fully autonomous through PR creation, human gates
the merge. Never auto-merge. Never force-push.

```
regression detected
  → create Linear issue          (Linear API, write)
  → create branch                (GitHub API, write)
  → propose up to 3 candidate fixes
  → for each: run the FULL suite
  → accept only if FAIL_TO_PASS and PASS_TO_PASS both hold
  → open draft PR with the before/after matrix in the body   (GitHub API, write)
  → if no candidate passes: comment the attempts on the Linear issue and stop
```

### The pieces

**Detect.** Read `data/runs/latest.json`, take the first case whose state is
`"r"` (passed in the previous version, fails now). That is the loop's input.

**Linear issue.** `issueCreate` mutation. Title = the rule and brief. Body =
the grader's `reason`, the offending quote, and which version broke it.
Store the returned issue identifier on the loop state.

**Branch.** `POST /repos/:repo/git/refs` from `main`'s SHA, named
`ratchet/fix-{rule}-{short_id}`.

**Propose.** The system under test is prompt-versioned, so a fix is an edit to
the rule list in `fixtures/target.py`. Ask the model for **three distinct
candidates**, each a concrete edit plus a one-line rationale. Commit each
candidate to the branch as a separate file under `candidates/` so the attempt
history is visible in the PR.

**Verify — this is the part that matters.** Adopt SWE-bench's split explicitly
and name it in the code:

- **FAIL_TO_PASS**: the regressed case must now pass
- **PASS_TO_PASS**: every case passing before the fix must still pass

A candidate that fixes the target and breaks anything else is **rejected**, and
the rejection is recorded with which cases it broke. The research is blunt that
this is the weakest-engineered step in every shipped agent — most just run the
suite and loop. Doing it properly, per-case, is the strongest thing this project
has.

**PR.** `POST /repos/:repo/pulls` with `draft: true`. The body must contain:
the Linear issue link, the failure that started it, all three candidates with
their fix/break counts, which one was chosen and why, and the before/after
matrix as a markdown table. A reviewer should be able to judge it without
opening anything else.

**Give up cleanly.** Top agents resolve ~75-90% on curated benchmarks and real
tickets are harder, so failure is a normal path, not an exception. If no
candidate passes, comment all three attempts and their break-lists on the Linear
issue, close the branch, exit non-zero. Do not open a PR with a failing fix.

### CLI

```bash
python -m ratchet loop --dry-run    # print every step, write nothing
python -m ratchet loop              # real: creates issue, branch, PR
```

`--dry-run` must exercise the whole path including candidate generation and
verification, and only skip the three write calls. Make it the default in
testing so we do not spam the repo.

---

## Constraints

- **Follow `CLAUDE.md`.** Cache every external call. Structured verdicts with
  evidence. Fail loud on partial results. Deterministic checks over LLM calls
  wherever the criterion allows it.
- **Never `exec()` model-generated code.**
- **Never auto-merge, never force-push, never write to `main`.**
- Secrets from `.env` via `config.py` only. `.env` is gitignored — keep it that way.
- Every new module needs tests. Phase 1 needs a test that a generated
  `regex_present` spec actually catches the failure it was derived from.
  Phase 2 needs a test that a candidate breaking a PASS_TO_PASS case is rejected.
- Commit after each phase with a real message describing what changed and why.
- If something takes more than 20 minutes past its target, stop, tell me, and
  ship what works.

## What NOT to do

- Do not refactor anything not named above.
- Do not add a web framework, a database, async, or a new dependency beyond
  what is already in `pyproject.toml`.
- Do not touch `report.py` styling.
- Do not delete the hand-written graders.
- Do not make the numbers look better than they are. If generated graders agree
  74% of the time, the README says 74%.

## Done means

```bash
python -m pytest tests -q                    # all green, including new tests
python -m ratchet run --source fixture       # still works end to end
python -m ratchet compare-graders            # prints an agreement number
python -m ratchet loop --dry-run             # prints a full loop with a verdict
```

and the README's §2 lists Linear and GitHub as **written**, not only read.
