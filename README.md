# Ratchet

**A ratchet only turns one way. Once a case passes, it never silently goes back.**

Ratchet reads the complaints and fixes a team already produces — in Slack, in
Linear, in GitHub — turns each into a runnable test case, and scores every version
of an AI feature **per case**, so an improvement and a regression can no longer
cancel out inside one aggregate number.

Built solo for the Multi-App AI Agent Hackathon, 13 September 2026.

---

## Demo

https://github.com/user-attachments/assets/29f04811-ba54-4505-93cd-1194a3a7eee9

1:55 · also committed at [`demo/ratchet-demo.mp4`](demo/ratchet-demo.mp4).

---

## 1. What it does

Teams shipping an LLM feature hit the same loop. You tweak a prompt, skim a few
outputs, they look fine, you ship. Weeks later someone reports a different thing
being wrong. You fix that, and the first problem quietly comes back. Practitioners
report spending [60–80% of development time on error analysis and
evaluation](https://hamel.dev/blog/posts/evals-faq/), most of it building the test
set by hand.

The test cases already exist. Every time the system got something wrong, a person
wrote it down — a Slack message, a bug ticket, a commit that fixed it. Ratchet
collects that and turns it into a suite.

Two ideas do the work:

**Cases are derived, not authored.** The strongest signal is a *fix*. At the moment
someone fixes something they know what the input was, what came out, why it was
wrong and what right looks like — and it is exactly the moment nobody writes a test.

**Per-case, never aggregate-only.** The seesaw is an aggregation problem: one score
lets case 7 improving and case 12 breaking cancel to "about the same," which reads
as noise. Ratchet reports the cells.

### A run

```
sources:
  slack    7 items
  linear   4 items
  github   4 items

extraction: 15 items -> 11 checkable -> 10 rules -> 60 cases (4 discarded, 0 unparseable)
  subsumption merged 1 duplicate rule(s): fee_currency_consistency→currency_symbol_consistency
  scored by 10 hand-written graders -> 60 cases
judge validation: 20/20 agreement with human labels = 100% on rule 'legalname'

v1: 55/60 = 0.92
v2: 59/60 = 0.98  (1 regressed)
v3: 56/60 = 0.93  (3 regressed)
v4: 59/60 = 0.98  (1 regressed)
v5: 60/60 = 1.00

variance on v4 (k=3): 57/60 cases stable, flip rate 5%
  unstable rules: date (1/6), termmatch (2/6)
```

The aggregate climbs from 0.92 to 1.00 and reads as clean progress. The per-case
view shows five regressions along the way — improvements and regressions cancelling
inside a rising number, which is the failure mode this exists to expose.

Every figure in this README is what the commands printed on a cold cache today.

---

## 2. External apps

Three, over their real APIs. Each contributes a different kind of failure, so the
suite is worse without any one of them — they are inputs to the decision, not
notification targets. Two are also **written**: the loop in §5 files its own ticket
and opens its own pull request.

| App | Read | Written | API |
|---|---|---|---|
| **Slack** | Informal complaints — the majority of real failure reports, and the ones that never get filed anywhere. | — (seeding only) | `conversations.history`, `users.info`, `chat.postMessage` |
| **Linear** | Bug tickets with reproduction steps: the highest-fidelity cases, because the reporter already isolated the failure. | Files the regression as an issue; comments every rejected fix attempt with the cases it broke. | GraphQL `issues`, `issueCreate`, `commentCreate` |
| **GitHub** | Commits and PR review comments. A fix is the strongest signal available. | Cuts a branch, commits each candidate fix, opens a draft PR carrying the before/after matrix. | `/repos/:r/commits`, `/repos/:r/pulls/comments`, `git/refs`, `contents`, `pulls` |

A source that fails is reported as failed and the run continues; a partial run is
never presented as a clean one.

Writes are constrained: never a merge, never a force-push, never a commit to the
default branch, and the PR is always a draft. `create_branch` refuses any name that
resolves to a protected branch, and a test asserts it.

Content in those accounts is **synthetic** — an invented consulting firm and an
invented document generator. `python -m ratchet seed` posts the corpus into the real
accounts. No real client, employer or personal data appears anywhere in this repo.

---

## 3. Setup

```bash
git clone https://github.com/danishm07/ratchet && cd ratchet
uv venv && source .venv/bin/activate
uv pip install httpx

cp .env.example .env      # then fill in the five values
python -m ratchet seed    # posts the synthetic corpus into Slack / Linear / GitHub
python -m ratchet run --candidates
open data/runs/report.html
```

Offline, no tokens required — the identical pipeline against the same corpus as a
local fixture:

```bash
python -m ratchet run --source fixture --candidates
```

The four commands that reproduce every number below:

```bash
python -m pytest tests -q               # 46 passed
python -m ratchet run --source fixture  # the per-case matrix
python -m ratchet compare-graders       # generated vs hand-written graders
python -m ratchet loop --dry-run        # regression → verified fix → draft PR
```

**Only the hand-written graders score a suite.** They are the ones whose agreement
with human labels has been measured, so every number here comes from them.
Generated graders are reachable through `compare-graders` alone, which measures them
*against* the hand-written ones.

`python -m ratchet loop` writes to Linear and GitHub for real. `--dry-run` exercises
the entire path — detection, candidate generation, full-suite verification — and
skips only the three write calls.

**Model backend.** Two interchangeable backends in `ratchet/llm.py`: `cli` shells
out to Claude Code (no API key), `openrouter` uses any model via `RATCHET_MODEL`.
Set with `RATCHET_BACKEND`.

**Caching.** Every model call is cached on disk by a hash of (backend, model,
prompt), so a re-run replays in seconds for free. Iterating on a judge is only
possible when re-running the suite is cheap, and a frozen environment is what lets
someone else reproduce these numbers.

---

## 4. Evaluation

### The judge is validated before any number is believed

An unvalidated LLM judge is a rubber ruler. Ratchet measures agreement against
hand-written human labels and prints it on every run.

```
judge validation: 20/20 agreement with human labels = 100% on rule 'legalname'
```

`python -m ratchet validate` prints any disagreements individually. At n=20 this
bounds the error rate weakly; the same command scored 17/20 against a different
cache, with no change to the judge.

### Most graders are deterministic, by design

Nine of ten rules are checked by parsing, regex or arithmetic — date format, phase
fees summing to the stated total, a spelled percentage matching its numeral,
currency consistency, term length against the brief. Those have no agreement problem
at all. Only `legalname` ("did it invent a legal entity the brief never supplied?")
is genuinely subjective, so only that one uses an LLM judge and only that one needs
validating.

### Judging is factored

The judge prompt contains the case and the output and nothing else — no transcript,
no neighbouring cases, no prior verdict. Per
[Chain-of-Verification](https://arxiv.org/abs/2309.11495) (Dhuliawala et al., ACL
Findings 2024), a judge that can see a prior judgement conditions on it and repeats
its errors: joint verification measured 0.29 precision against 0.36 factored.

Every verdict is `{passed, reason, quote}`. A verdict that cannot point at the text
that decided it is rejected by the schema.

### Generating graders from failure descriptions: 85.7%

`extract.py` does not classify complaints into a fixed menu. It reads a failure
report and names the rule itself; `genjudge.py` then generates a grader from the
expectation. A menu written in advance is the ceiling Shreya Shankar's UIST 2024
study calls **criteria drift** — it can only catch failures somebody anticipated.

Whether a generated grader is any good is measurable, so it is measured. Both
graders run over the same 60 cases × 5 versions, with the hand-written ten as ground
truth.

```
$ python -m ratchet compare-graders
generated vs hand-written graders: 257/300 = 85.7% agreement
  perfect:    assume, currency, date, daterange, excl, headings, totals
  divergent:  percent 25/30, legalname 14/30, termmatch 8/30
```

Seven of ten agree perfectly. The three that diverge do so for three different
reasons — the part a single percentage would hide:

- **`termmatch` 8/30** — a generation bug. It emitted
  `(?:term|duration|engagement)[^\n]{0,60}?(\d+)\s*month`, which cannot match
  `twelve (12) months`: the closing paren sits between the digits and the word.
- **`legalname` 14/30** — a structural limit. The criterion is conditional ("if the
  brief supplies no legal entity name…") and a flat regex cannot branch on the brief.
- **`percent` 25/30** — the hand-written grader is arguably the wrong one. All five
  disagreements are documents containing no percentage at all; the generated rubric
  passes them as vacuously satisfied. Neither side was changed to improve the number.

`derive_spec` chose a deterministic kind for 7 of 10 rules unprompted. Every
generated spec is in `data/runs/compare_graders.json`, inspectable before it is
trusted.

**Nothing generated is ever executed as code.** A spec is a structured object —
`regex_present`, `regex_absent`, `numeric_match`, `llm_rubric` — not Python. Specs
that would be unsafe or unusable (uncompilable patterns, nested quantifiers, fields
the brief does not have) are refused at derivation time and degrade to a rubric that
records why. A test walks the module's AST and asserts there is no `exec`, `eval`,
`compile` or `__import__` anywhere in it.

`judge.grade()` dispatches to hand-written graders only. A rule it does not
recognise raises rather than scoring a pass or a zero: a case with no grader is
missing data, which is a distinct state from a failing case.

### Ablation, including the combination

`--candidates` runs each candidate change against the full suite independently, then
runs their combinations:

```
B: term match                  +4  (+4 / -0)  added: termmatch
B: term match + C: date format +4  (+4 / -0)  as predicted from the parts
A: headings + B: term match    +3  (+3 / -0)  as predicted from the parts
C: date format                 +1  (+1 / -0)  added: date
A: headings                    +0  (+1 / -1)  added: headings
A: headings + C: date format   +0  (+1 / -1)  INTERACTION: predicted +1, measured +0
```

Two things here are invisible to an aggregate score.

**`A: headings` is a trap.** Alone it nets +0 — it fixes one case and breaks one, so
a team watching a single number ships it without noticing anything happened. Added to
the best candidate, B drops from +4 to +3: A is costing a case B had fixed.

**Effects are not additive.** A+C was predicted at +1 from its parts and measured +0,
which is why `candidates.py` evaluates combinations rather than summing individual
profiles.

Against a 5% flip rate (≈3 cases in 60), `B: term match` at +4 with nothing broken is
the only row here that clears the noise floor with room to spare.

### Four bugs found in the measuring instrument

Every one of these was in the eval, not in the system under test. All four are pinned
by tests.

| Bug | Effect | Fix |
|---|---|---|
| Two graders matched only bare headings, not markdown (`**5. Assumptions**`) | Section presence and heading numbering scored at random; 50% of cases flipped between identical runs | Tolerate markdown, bold and ATX heading forms |
| `g_percent` captured the whole run of words before "percent" | Failed to resolve against the number table and **passed silently** — a false negative that inflates the score | Resolve the trailing token |
| Cache stampede in `llm.py` — six workers miss the same key, six calls go out, six different answers come back | The same rule graded by a regex on one brief and an LLM rubric on another, inside one run. The instrument varied with thread scheduling | Per-key lock, re-check cache after acquiring |
| `complete_json` scanned for `[`…`]` before `{`…`}` | Returned a nested `steps` array as if it were the whole response. The parse *succeeded with the wrong value*; `derive_spec` then degraded to a vague rubric that passed everything | Scan from the first opener to its own matching closer, tracking strings and escapes |

The last one is the instructive one. It made generated graders score 60/60 on every
version, which looked like evidence that generation is inherently too lenient. It was
not — it was a parse bug. After the fix, zero of ten derived rules fall back and
generated graders fail 7/60 on v1 where they had failed 0/60.

### Limits

- **Generated graders are not trusted to score a release.** 85.7% agreement, with
  `termmatch` at 8/30 and `legalname` at 14/30. Good enough to propose a grader for
  review; not good enough to run unattended, so `judge.grade()` will not call one.
- **The noise floor is close to the effect sizes.** k=3 gives a 5% flip rate — about
  three cases in sixty — against observed regressions of one to three cases. No
  regression here is claimed as established. Confidence intervals and a larger k are
  the next step.
- **PASS_TO_PASS cannot separate a real break from an unstable case.** All three
  rejections in §5 land on `termmatch`, one of the two unstable rules. Running it
  against the stable subset, or requiring a break to reproduce across k samples,
  would fix it.
- **Subsumption is unvalidated.** It merged one duplicate pair and that merge looks
  right, but there is no held-out set measuring how often it merges rules it should
  not.
- **Variance is sampled by perturbing the prompt with an inert marker,** because the
  CLI backend exposes no temperature control. With OpenRouter this would be a
  temperature setting.
- **Judge agreement is measured on one rule** (`legalname`, n=20).
- **The system under test is a stand-in** — a small engagement-letter generator with
  five prompt versions. Its regressions are genuine emergent behaviour, each version
  honestly dropping a rule a previous one had, but it is a fixture.

---

## 5. Closing the loop: regression → verified fix → draft PR

Finding the regression is half the job. `python -m ratchet loop` takes one regression
out of the matrix and drives it to a pull request a human merges:

```
regression detected
  → Linear issue                  (write)
  → branch off the default branch (write)
  → propose 3 candidate fixes
  → run the FULL suite for each
  → accept only if FAIL_TO_PASS and PASS_TO_PASS both hold
  → draft PR carrying the before/after matrix   (write)
  → if nothing passes: comment the attempts on the issue, delete the branch, exit 1
```

This is the shape shipped coding agents converge on — Copilot's coding agent,
Cursor's background agents, Devin: autonomous up to the PR, human gates the merge.

**Verification is the point.** It adopts SWE-bench's split by name rather than asking
"is the suite green":

- **FAIL_TO_PASS** — the regressed case must now pass
- **PASS_TO_PASS** — every case that passed before must still pass

A candidate that fixes the target and breaks a bystander is rejected, and the
rejection records which cases it broke.

```
$ python -m ratchet loop --dry-run
1. detected regression
   case      date::calder
   rule      date — no date in the required '14 June 2026' form found
   broke at  v4 (passed at v3)

4. proposed 3 candidate(s)
5. verifying each against the FULL suite (60 cases) — FAIL_TO_PASS and PASS_TO_PASS
   candidate-1  FAIL_TO_PASS=yes PASS_TO_PASS=no   fixed 1, broke 1   REJECTED
        broke: termmatch::kestrel
   candidate-2  FAIL_TO_PASS=yes PASS_TO_PASS=no   fixed 1, broke 1   REJECTED
        broke: termmatch::harbourline
   candidate-3  FAIL_TO_PASS=yes PASS_TO_PASS=no   fixed 1, broke 3   REJECTED
        broke: termmatch::calder, termmatch::meridian, termmatch::solent

6. NO CANDIDATE PASSED BOTH CONDITIONS — giving up cleanly.
   No PR is opened for a fix that does not hold.
```

Exit code 1, no PR. Giving up is a normal path — top agents resolve 75–90% on curated
benchmarks and real tickets are harder — so a clean give-up that reports what it tried
beats a PR somebody has to revert.

All three rejections land on `termmatch`, an unstable rule, so they are more likely
noise than real breaks; see §4 Limits.

---

## Architecture

```
sources/    →  extract   →  cases  →  runner   →  matrix  →  report
slack.py       (LLM,         60      (graders)   per-case   report.html
linear.py       cached,                             ×
github.py       names its                        version         │
                own rules)                           │           │
                     │                               │           │
                genjudge.py                     judge.py     loop.py
                expectation →                   validated    regression →
                GraderSpec                      against      Linear issue →
                (never code)                    human        branch → 3 fixes →
                     │                          labels       FAIL_TO_PASS +
                     └──── measured at ─────────► first      PASS_TO_PASS →
                           85.7% agreement                   draft PR
```

Module boundaries are strict. Adapters do I/O only. `extract.py` is the sole place
prose becomes structure. `judge.py` grades and knows nothing about sources.
`matrix.py` computes, `report.py` presents. Every module runs standalone.

| file | role |
|---|---|
| `ratchet/sources/*.py` | one adapter per app, returning `SourceItem` |
| `ratchet/extract.py` | `SourceItem → Case`; names rules itself, then a subsumption pass merges duplicates |
| `ratchet/genjudge.py` | expectation → `GraderSpec` → `Verdict`. Structured specs, never generated code |
| `ratchet/judge.py` | the ten reference graders, nine deterministic, plus `validate()`; the single grading entry point |
| `ratchet/runner.py` | generates and grades every case per version |
| `ratchet/matrix.py` | per-case × per-version state, regression detection |
| `ratchet/candidates.py` | independent candidate runs plus their combinations |
| `ratchet/loop.py` | one regression → Linear issue → branch → verified fix → draft PR |
| `ratchet/report.py` | the HTML |
| `fixtures/` | the synthetic firm, briefs, corpus and judge labels |

## Prior art this builds on

- [FActScore](https://arxiv.org/abs/2305.14251) — atomic claims as the unit of evaluation
- [MiniCheck](https://arxiv.org/abs/2404.10774) — verification is entailment, and a small specialised checker beats a large general one at 400× lower cost
- [Chain-of-Verification](https://arxiv.org/abs/2309.11495) — verification must be factored or the judge repeats the errors it can see
- [Hamel Husain & Shreya Shankar, AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/) — 60–80% of eval time goes to error analysis
- [Shankar et al., *Who Validates the Validators?*](https://arxiv.org/abs/2404.12272) (UIST 2024) — criteria drift: a rubric fixed in advance is already behind the real failure distribution
- [SPADE](https://arxiv.org/abs/2401.03038) — deduplicating generated assertions by asking whether one subsumes another
- [G-Eval](https://arxiv.org/abs/2303.16634) — generate the evaluation steps first, then apply them
- [SWE-bench](https://arxiv.org/abs/2310.06770) — FAIL_TO_PASS and PASS_TO_PASS as the acceptance condition for an automated fix
