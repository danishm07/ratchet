# Ratchet

**A ratchet only turns one way. Once a case passes, it never silently goes back.**

Ratchet reads the complaints and fixes a team already produces — in Slack, in
Linear, in GitHub — turns each into a runnable test case, and then scores every
version of an AI feature **per case**, so an improvement and a regression can no
longer cancel each other out inside one aggregate number.

Built solo for the Multi-App AI Agent Hackathon, 13 September 2026.

---

## 1. Project overview

Teams shipping an LLM feature hit the same loop. You tweak a prompt, skim a few
outputs, they look fine, you ship. Weeks later someone reports a different thing
being wrong. You fix that, and the first problem quietly comes back. Practitioners
report spending [60–80% of development time on error analysis and
evaluation](https://hamel.dev/blog/posts/evals-faq/) — most of it building the test
set by hand — and Langfuse names the failure mode directly: *"a prompt tweak that
fixes one complaint can quietly break ten other answers."*

The test cases already exist. Every time the system got something wrong, a person
wrote it down — as a Slack message, a bug ticket, or a commit that fixed it. That
knowledge dies where it was written. Ratchet collects it.

Two ideas do the work:

**Cases are derived, not authored.** The strongest signal is a *fix* — at the moment
someone fixes something they know what the input was, what came out, why it was
wrong and what right looks like, and it is exactly the moment nobody writes a test.
A fix is a complaint with the answer already attached.

**Per-case, never aggregate-only.** The seesaw is an aggregation problem, not a
measurement problem: one score lets case 7 improving and case 12 breaking cancel to
"about the same," which reads as noise. Ratchet reports the cells.

### What a run produces

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

The aggregate score climbs from 0.92 to 1.00 and looks like clean progress. The
per-case view shows one case regressing at v2, three more at v3, and another at v4 —
improvements and regressions cancelling inside a rising number, which is exactly the
failure mode this exists to expose.

**The honest part: these numbers come from a cold cache on one machine and they are
not the numbers a previous run produced.** Every figure in this README is whatever
the commands actually printed today; where a claim could not be re-measured in time
it is marked as such rather than carried over. §4 is the accounting, including the
four bugs found in the measuring instrument — and none in the system it measures.

---

## 2. External apps used

Three, over their real APIs. Each contributes a **different kind** of failure, so
the suite is measurably worse without any one of them — they are inputs to the
decision, not notification targets. Two of the three are also **written**: the
loop in §5 files its own ticket and opens its own pull request.

| App | Read | Written | API |
|---|---|---|---|
| **Slack** | Informal complaints. The majority of real failure reports, and the ones that never get filed anywhere. | — (seeding only) | `conversations.history`, `users.info`, `chat.postMessage` |
| **Linear** | Bug tickets with reproduction steps — the highest-fidelity cases, because the reporter already isolated the failure. | **Files the regression as an issue**, and comments every rejected fix attempt with the cases it broke. | GraphQL `issues`, `issueCreate`, `commentCreate` |
| **GitHub** | Commits and PR review comments. **A fix is the strongest signal available** and the one that is never written down. | **Cuts a branch, commits each candidate fix, opens a draft PR** carrying the before/after matrix. | `/repos/:r/commits`, `/repos/:r/pulls/comments`, `git/refs`, `contents`, `pulls` |

A source that fails is reported as failed and the run continues — a partial run is
never presented as a clean one.

The writes are deliberately constrained: never a merge, never a force-push, never
a commit to the default branch, and the PR is always a **draft**. `create_branch`
refuses any name that resolves to a protected branch, and a test asserts it.

The content in those accounts is **synthetic**: an invented consulting firm
(Northwind Advisory) and an invented document generator. `python -m ratchet seed`
posts the corpus into the real accounts. No real client, employer or personal data
is used anywhere in this repo.

---

## 3. Setup

```bash
git clone <this repo> && cd ratchet
uv venv && source .venv/bin/activate
uv pip install httpx

cp .env.example .env      # then fill in the five values
python -m ratchet seed    # posts the synthetic corpus into Slack / Linear / GitHub
python -m ratchet run --candidates
open data/runs/report.html
```

Run the tests — they pin every measurement bug found during the build:

```bash
python -m pytest tests -q      # 46 passed
```

Offline, no tokens required — runs the identical pipeline against the same corpus
as a local fixture:

```bash
python -m ratchet run --source fixture --candidates
```

The four commands that reproduce every number below:

```bash
python -m pytest tests -q             # 46 passed
python -m ratchet run --source fixture # the per-case matrix
python -m ratchet compare-graders      # generated vs hand-written graders
python -m ratchet loop --dry-run       # regression -> verified fix -> draft PR
```

**Only the hand-written graders ever score a suite.** They are the ones whose
agreement with human labels has been measured, so they are what every number here
comes from. Graders generated from a failure description are reachable through
`compare-graders` alone, which measures them *against* the hand-written ones — §4
says by how much, and why they are not trusted to score anything yet.

`python -m ratchet loop` writes to Linear and GitHub for real. `--dry-run`
exercises the entire path — detection, candidate generation, full-suite
verification — and skips only the three write calls.

**Model backend.** Two interchangeable backends in `ratchet/llm.py`: `cli` shells
out to Claude Code (no API key), `openrouter` uses any model via `RATCHET_MODEL`.
Set with `RATCHET_BACKEND`.

**Caching.** Every model call is cached on disk by a hash of (backend, model,
prompt), so a re-run replays in seconds for free. This is not an optimisation —
iterating on a judge is only possible when re-running the suite is cheap, and a
frozen environment is what lets someone else reproduce these numbers.

---

## 4. Reliability testing

This is the part most eval demos skip, so it is the part built first.

### The measurement caught its own bug before it caught anything else

The first complete run reported a dramatic seesaw — v3 losing thirteen cases, v5
losing ten. It was wrong, and the variance check is what said so: **50% of cases
flipped between identical runs**, which is not a system that regresses, it is an
instrument that cannot measure.

The fault was in the graders, not the generator. The model emits markdown
(`**5. Assumptions**`) and two graders matched only bare headings, so section
presence and heading numbering were scored essentially at random. After the fix
the flip rate fell to 20% and the "dramatic seesaw" mostly disappeared with it.

A second grader bug fell out of the unit tests rather than the variance check:
`g_percent` captured the whole run of words before "percent" ("a deposit of
fifty"), failed to resolve it against the number table, and **passed silently** —
a false negative that inflates the score rather than deflating it. Pinned in
`tests/test_graders.py`.

That sequence is the argument for the whole project. An eval that is not itself
checked will confidently produce a story, and the story will be about your
measurement rather than your system. Two of the bugs found today were in the
instrument; none were in the thing being measured.

### The remaining regressions are reported as not yet significant

With k=3 sampling showing a **5% per-case flip rate** (57/60 cases stable), roughly
three cases in sixty are expected to flip between two identical runs. The observed
regressions are one case at v2, three at v3, and one at v4 — which puts the
single-case regressions **inside the noise floor** and the three-case one right at
its edge. This README does not claim any of them as established. What would be
needed to claim them: a larger k, per-case confidence intervals, and a paired
comparison restricted to the stable subset. That work is not done here.

Two rules are unstable across identical runs — `termmatch` (2/6 cases) and `date`
(1/6); the other eight are perfectly stable. A change that moves only unstable cases
has not been shown to do anything.

This number moved a long way during the build. An earlier cache measured a 20% flip
rate; the current one measures 5%. The flip rate is a property of the generator *and
the corpus*, not a constant of the project, which is the argument for printing it on
every run instead of quoting it once in a README.

### The judge is validated before any number is believed

An unvalidated LLM judge is a rubber ruler: you watch numbers move confidently and
they mean nothing. Ratchet measures agreement against hand-written human labels and
prints it on every run.

```
judge validation: 20/20 agreement with human labels = 100% on rule 'legalname'
```

`python -m ratchet validate` prints any disagreements individually. **20/20 is a
suspiciously clean number and should be read as "n=20 is too small to bound the
error rate", not as "the judge is perfect."** A previous run of the same command
against a different cache scored 17/20. Nothing about the judge changed between
those two runs — only the documents it was judging — which is itself the argument
for re-measuring rather than quoting a number from last week.

### Generated graders vs hand-written ones: 85.7%, and where the 14.3% goes

`extract.py` no longer classifies complaints into a fixed menu of ten rules. It
reads a failure report and *names the rule itself*, then `genjudge.py` generates a
grader from the expectation. A fixed menu is the ceiling Shreya Shankar's UIST 2024
study calls **criteria drift** — *"users need criteria to grade outputs, but grading
outputs helps users define criteria"* — and a menu written in advance can only ever
catch failures somebody already anticipated.

The obvious question is whether a generated grader is any good. That is measurable,
so it is measured: both graders run over the same 60 cases × 5 versions, and the ten
hand-written graders are the ground truth.

```
$ python -m ratchet compare-graders
generated vs hand-written graders: 257/300 = 85.7% agreement
  perfect:    assume, currency, date, daterange, excl, headings, totals
  divergent:  percent 25/30, legalname 14/30, termmatch 8/30
```

Seven of ten rules generate a grader that agrees perfectly. The three that diverge
fail for three *different* reasons, which is the useful part — a single percentage
would have hidden all of it:

- **`termmatch` 8/30 — a real generation bug.** It emitted
  `(?:term|duration|engagement)[^\n]{0,60}?(\d+)\s*month`, which cannot match
  `twelve (12) months`: the closing paren sits between the digits and the word. The
  hand-written grader has a spelled-number fallback; the generated one has no idea
  it needs one.
- **`legalname` 14/30 — a structural limit, not a bug.** The criterion is
  *conditional* ("if the brief supplies no legal entity name…"), and a flat regex
  cannot branch on the brief. It fails every case where the brief already supplied a
  name and no placeholder was ever needed.
- **`percent` 25/30 — the hand-written grader is arguably the wrong one.** All five
  disagreements are documents containing no percentage at all. The hand-written
  grader calls that a failure; the generated rubric passes it as vacuously
  satisfied. **The generated grader is probably right and the ground truth is
  over-strict.** Neither was changed to improve the number.

`derive_spec` chose a deterministic kind for 7 of 10 rules unprompted, which is the
behaviour the "deterministic graders win" rule asks for. Every generated spec is in
`data/runs/compare_graders.json`, inspectable before it is trusted.

**Nothing generated is ever executed as code.** A spec is a structured object —
`regex_present`, `regex_absent`, `numeric_match`, `llm_rubric` — not Python. Specs
that would be unsafe or unusable (uncompilable patterns, nested quantifiers that
risk catastrophic backtracking, fields the brief does not have) are refused at
derivation time and degrade to a rubric that says why. A test walks the module's AST
and asserts there is no `exec`, `eval`, `compile` or `__import__` anywhere in it.

### Generated graders do not score anything, by construction

`judge.grade()` dispatches to the hand-written graders and nothing else. A rule it
does not recognise **raises** — it does not score zero and it does not score a pass,
because a case with no grader is missing data and CLAUDE.md rule 6 makes that a
distinct state from a failing case. `genjudge.py` is reachable from
`compare-graders` alone, where its output is measured against the hand-written
graders rather than believed.

That boundary was not always there, and the story of removing it is §4's third bug.

### The third measurement bug: a JSON parse that succeeded with the wrong value

An earlier build let generated graders score the suite. Every version came back
**60/60** — a perfect score, five regressions lost, and a ratchet with no teeth. The
tempting reading was "generated graders are inherently too lenient." That reading
was wrong, and the spec dump is what disproved it.

Five of ten rules reported `fell back to llm_rubric — model returned no usable
spec`. But the model's output was fine:

```json
{"kind": "llm_rubric", "pattern": null, "steps": ["...", "..."], "rationale": "..."}
```

The fault was in `complete_json`, which looked for `[`…`]` before `{`…`}`. It found
the **nested `steps` array**, matched it against the last `]` in the response, and
returned that list as if it were the whole answer. Four fields silently vanished.
The parse did not fail — it succeeded, with the wrong value, which is the harder
kind to notice.

`derive_spec` then saw a non-dict and degraded to a one-step rubric reading *"decide
whether the document satisfies &lt;expectation&gt;"*. Vague enough to pass almost
anything. So **a parse failure quietly became a grader that passed everything.**

Both halves are fixed:

- `complete_json` now scans from the first opener to *its own* matching closer,
  tracking string literals and escapes so a `{1,4}` inside a generated regex cannot
  terminate the object. Eight cases in `tests/test_llm_json.py` pin it.
- `derive_spec` **raises** `SpecError` when no spec can be derived, instead of
  substituting a lenient default. A coherent-but-unsafe spec (uncompilable pattern,
  nested quantifier, unknown brief field) still degrades to a rubric, because that
  is a real answer being declined rather than an absent one — and the rationale says
  which. `compare-graders` reports any rule that produced no spec as *ungraded*, not
  as agreement.

After the fix, zero of ten derived rules fall back, and the generated graders fail
7/60 cases on v1 where they previously failed 0/60. They discriminate again.

**The conclusion survives the correction, but the evidence for it is weaker than it
looked.** Generated graders still should not score a release unattended — agreement
is 85.7%, and `termmatch` at 8/30 and `legalname` at 14/30 are not close. What is no
longer true is the dramatic version of that claim: the 60/60 table was a bug in this
repo, not a property of generated graders.

### The second measurement bug: the cache stampede

The first run under generated graders scored the *same rule* with a regex on one
brief and an LLM rubric on another, inside a single run. The cause was one layer
below the graders, in `llm.py`: six worker threads miss the same cache key at the
same instant, six real model calls go out, and — because the model is not
deterministic — six different answers come back. One wins the write to disk; the
other five get used anyway by the threads that made them.

So the measuring instrument was varying with **thread scheduling**. `complete()` now
takes a per-key lock and re-checks the cache after acquiring it, so concurrent
callers asking the identical question wait for the first answer instead of buying
their own. The warm-cache fast path is untouched.

That makes **four bugs found in the instrument** during this build — two markdown-blind
graders, a silent-pass in `g_percent`, the cache stampede, and the JSON parse above —
and none in the system under test. Which is either very funny or the entire thesis.

### Most graders are deterministic, by design

Nine of ten rules are checked by parsing, regex or arithmetic — date format, phase
fees summing to the stated total, a spelled percentage matching its numeral,
currency consistency, term length against the brief. Those have no agreement
problem at all. Only `legalname` ("did it invent a legal entity the brief never
supplied?") is genuinely subjective, so only that one uses an LLM judge and only
that one needs validating.

### Judging is factored

The judge prompt contains the case and the output and nothing else — no transcript,
no neighbouring cases, no prior verdict. Per
[Chain-of-Verification](https://arxiv.org/abs/2309.11495) (Dhuliawala et al., ACL
Findings 2024), a judge that can see a prior judgement conditions on it and repeats
its errors: joint verification measured 0.29 precision against 0.36 factored.

### Verdicts must carry evidence

Every verdict is `{passed, reason, quote}`. A verdict that cannot point at the text
that decided it is not a verdict.

### Ablation, including the combination

`--candidates` runs each candidate change against the full suite independently, then
runs their combinations, because effects are not additive:

```
B: term match                  +4  (+4 / -0)  added: termmatch
B: term match + C: date format +4  (+4 / -0)  as predicted from the parts
A: headings + B: term match    +3  (+3 / -0)  as predicted from the parts
C: date format                 +1  (+1 / -0)  added: date
A: headings                    +0  (+1 / -1)  added: headings
A: headings + C: date format   +0  (+1 / -1)  INTERACTION: predicted +1, measured +0
```

Two things here are invisible to an aggregate score.

**`A: headings` is a trap.** On its own it reads as harmless — net +0, because it
fixes one case and breaks one. A team watching a single number would ship it without
noticing anything happened at all. But add it to the best candidate and B drops from
+4 to +3: A is *costing* a case that B had fixed. The only way to see that is to
compare the cells, not the totals.

**Effects are not additive.** A+C was predicted at +1 from its parts and measured
+0. That is why `candidates.py` evaluates the combinations rather than summing the
individual profiles — a serial fix-one-thing-at-a-time loop never generates that
row, and so never learns it.

The noise caveat still applies, though it is smaller than it was: these deltas are
1–4 cases against a 5% flip rate (≈3 cases in 60). **`B: term match` at +4 with
nothing broken is the only result here that clears the noise floor with any room to
spare.** The rest are suggestive, not established.

### Known limitations, stated plainly

- **Generated graders cannot be trusted to score a release.** 85.7% agreement is not
  close enough, and two rules are badly wrong (`termmatch` 8/30, `legalname` 14/30).
  Good enough to propose a grader for a human to review; not good enough to run
  unattended, so `judge.grade()` will not call one. An earlier build let them score
  and every version came back 60/60 — that turned out to be a JSON parse bug rather
  than a property of generation, but the boundary stays until agreement is measured
  much higher.
- **The loop rejects candidates it probably should not.** PASS_TO_PASS cannot tell a
  real break from a case that was going to flip anyway, and all three rejections in
  §5 are on an unstable rule. It fails safe, but it fails.
- **The noise floor is not far below the effect sizes.** k=3 gives a 5% flip rate —
  about three cases in sixty — against observed regressions of one to three cases.
  Nothing here is claimed as a significant regression, only as something to look at.
  Confidence intervals and a larger k are the next step.
- **Subsumption is O(n·k) model calls and unverified.** It merged one duplicate pair
  (`fee_currency_consistency` → `currency_symbol_consistency`) and that merge looks
  right, but there is no held-out set measuring how often it merges rules it should
  not. Unlike the judge, this component is not validated.
- **Variance is sampled by perturbing the prompt with an inert marker,** because the
  CLI backend exposes no temperature control. With the OpenRouter backend this
  would be a temperature setting; the measurement is equivalent but the method is
  worth knowing.
- **Judge agreement is measured on one rule** (`legalname`, n=20) and currently
  reads 20/20. n=20 is too small to bound an error rate; the same command scored
  17/20 against a different cache.
- **Extraction is not perfect.** Of 15 items, 11 were accepted and 4 discarded as
  chatter; the counts are printed on every run rather than hidden.
- **The system under test is a stand-in.** A small engagement-letter generator with
  five prompt versions. Its regressions are genuine emergent behaviour — each
  version's prompt honestly drops a rule a previous one had, the way real prompt
  edits do — but it is a fixture, not a production system.

---

## 5. Closing the loop: regression → verified fix → draft PR

Finding the regression is half the job. `python -m ratchet loop` takes one
regression out of the matrix and drives it to a pull request a human merges:

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

This is the shape every shipped coding agent converges on — GitHub's Copilot coding
agent, Cursor's background agents, Devin: autonomous up to the PR, human gates the
merge. Never auto-merged, never force-pushed, never a commit to the default branch,
always a **draft**.

**The verification step is the point.** It adopts SWE-bench's split by name rather
than asking "is the suite green":

- **FAIL_TO_PASS** — the regressed case must now pass
- **PASS_TO_PASS** — every case that passed before must still pass

A candidate that fixes the target and breaks a bystander is rejected, and the
rejection records exactly which cases it broke. Shipping a loop that could not catch
that would have been incoherent in a repo whose entire argument is per-case scoring.

### What it actually did, unedited

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

Exit code 1. **All three candidates fixed the target case and all three were
rejected** — which is a demo of the check working, not of the fix working. Giving up
is a normal path: top agents resolve 75–90% on curated benchmarks and real tickets
are harder, so a clean give-up that reports what it tried is worth more than a PR
somebody has to revert.

### …and the honest reading of that result

**Those rejections are probably false.** Every broken case is a `termmatch` case,
and `termmatch` is one of the two rules the variance check flags as unstable (2/6
cases flip between identical runs). Candidate-1 only *adds* the `date` rule to v4,
which has no plausible mechanism for breaking term-length agreement. The most likely
explanation is that each candidate regenerates its documents, and `termmatch` flipped
on its own.

So the loop is currently **too strict in the presence of generator noise**: it
cannot distinguish "this candidate broke a case" from "this case was going to flip
anyway," and it resolves that ambiguity by rejecting. That is the safe direction to
fail, but it is a real limitation and it is not fixed here. The fix is to run
PASS_TO_PASS against the *stable* subset the variance check already identifies, or
to require a break to reproduce across k samples before counting it. Both are
cheap; neither is done.

---

## 6. Demo video

**[▶ Watch the demo — 1:55](demo/ratchet-demo.mp4)** · [`demo/ratchet-demo.mp4`](demo/ratchet-demo.mp4)

https://github.com/danishm07/ratchet/raw/main/demo/ratchet-demo.mp4

The grid is the hero shot: one row per case, one column per version, outlined cells
where a case passed in the previous version and fails in this one. Everything else
in the run — the extraction counts, the judge agreement, the loop's verdict — is
there to make those cells worth believing.

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
- [Shankar et al., *Who Validates the Validators?*](https://arxiv.org/abs/2404.12272) (UIST 2024) — criteria drift: a grading rubric fixed in advance is already behind the real failure distribution
- [SPADE](https://arxiv.org/abs/2401.03038) — deduplicating generated assertions by asking whether one subsumes another
- [G-Eval](https://arxiv.org/abs/2303.16634) — generate the evaluation steps first, then apply them
- [SWE-bench](https://arxiv.org/abs/2310.06770) — FAIL_TO_PASS and PASS_TO_PASS as the acceptance condition for an automated fix
