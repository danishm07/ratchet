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
judge validation: 17/20 agreement with human labels = 85% on rule 'legalname'

v1: 51/60 = 0.85
v2: 56/60 = 0.93  (4 regressed)
v3: 56/60 = 0.93  (4 regressed)
v4: 57/60 = 0.95  (3 regressed)
v5: 59/60 = 0.98  (1 regressed)

variance on v4 (k=3): 48/60 cases stable, flip rate 20%
  unstable rules: date (4/6), termmatch (4/6), legalname (3/6), daterange (1/6)
```

The aggregate score climbs steadily and looks like clean progress. The per-case view
shows four cases regressing at v2 and four more at v3 — improvements and regressions
cancelling inside a rising number, which is exactly the failure mode this exists to
expose.

**And then the honest part: at a 20% flip rate a three-case regression sits inside
the noise floor, so this README does not claim those regressions are real.** How
that was discovered, and what it would take to claim them, is §4.

---

## 2. External apps used

Three, all read live over their real APIs. Each contributes a **different kind** of
failure, so the suite is measurably worse without any one of them — they are inputs
to the decision, not notification targets.

| App | What it contributes | API |
|---|---|---|
| **Slack** | Informal complaints. The majority of real failure reports, and the ones that never get filed anywhere. | `conversations.history`, `users.info` |
| **Linear** | Bug tickets with reproduction steps — the highest-fidelity cases, because the reporter already isolated the failure. | GraphQL `issues` |
| **GitHub** | Commits and PR review comments. **A fix is the strongest signal available** and the one that is never written down. | `/repos/:r/commits`, `/repos/:r/pulls/comments` |

A source that fails is reported as failed and the run continues — a partial run is
never presented as a clean one.

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

Run the tests — they pin both grader bugs found during the build:

```bash
python -m pytest tests -q      # 13 passed
```

Offline, no tokens required — runs the identical pipeline against the same corpus
as a local fixture:

```bash
python -m ratchet run --source fixture --candidates
```

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

With k=3 sampling showing a 20% per-case flip rate, a regression of one to four
cases out of sixty **cannot be distinguished from generator variance**, and this
README does not claim otherwise. What would be needed to claim it: a larger k,
per-case confidence intervals, and a paired comparison on the stable subset. That
work is not done here, and the numbers above should be read with that bound.

Four rules are unstable across identical runs (`date`, `termmatch`, `legalname`,
`daterange`); six are perfectly stable. A change that moves only unstable cases has
not been shown to do anything.

### The judge is validated before any number is believed

An unvalidated LLM judge is a rubber ruler: you watch numbers move confidently and
they mean nothing. Ratchet measures agreement against hand-written human labels and
prints it on every run.

```
judge validation: 17/20 agreement with human labels = 85% on rule 'legalname'
```

`python -m ratchet validate` prints the three disagreements individually. 85% is
reported rather than rounded up, and it bounds how much any `legalname` result
should be trusted.

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
A: headings + B: term match    +2  (+4 / -2)
B: term match                  +0  (+4 / -4)
B: term match + C: date format +0  (+4 / -4)
A: headings                    -3  (+1 / -4)
C: date format                 -3  (+0 / -3)
A: headings + C: date format   -3  (+1 / -4)
```

All three are sensible-looking fixes. Measured against the full suite, two of the
three make the system **net worse on their own**, and the best result is a pair —
A+B at +2 — that a serial fix-one-thing-at-a-time loop would never have reached,
because it would have applied A first, seen −3, and backed it out.

The same noise caveat applies: these deltas are small relative to a 20% flip rate,
and the correct claim is "A+B is the only candidate that is not worse," not "A+B
is a +2 improvement."

### Known limitations, stated plainly

- **The noise floor is not far below the effect sizes.** k=3 gives a 20% flip
  rate; the observed regressions are 1–4 cases in 60. Nothing here is claimed as a
  significant regression, only as something to look at. Confidence intervals and a
  larger k are the next step.
- **Variance is sampled by perturbing the prompt with an inert marker,** because the
  CLI backend exposes no temperature control. With the OpenRouter backend this
  would be a temperature setting; the measurement is equivalent but the method is
  worth knowing.
- **Agreement is measured on one rule** (`legalname`, n=20), the only LLM-judged
  one. The deterministic graders are not judgements and are not measured this way.
- **Extraction is not perfect.** Of 15 items, 11 were accepted and 4 discarded as
  chatter; the counts are printed on every run rather than hidden.
- **The system under test is a stand-in.** A small engagement-letter generator with
  five prompt versions. Its regressions are genuine emergent behaviour — each
  version's prompt honestly drops a rule a previous one had, the way real prompt
  edits do — but it is a fixture, not a production system.

---

## 5. Demo video

**[Link to be added — ≤2 minutes]**

---

## Architecture

```
sources/        →  extract   →  cases  →  runner   →  matrix  →  report
slack.py            (LLM,        60      (graders)   per-case   report.html
linear.py            cached)                            ×
github.py                                            version
                                    judge.py validated
                                    against human labels first
```

Module boundaries are strict. Adapters do I/O only. `extract.py` is the sole place
prose becomes structure. `judge.py` grades and knows nothing about sources.
`matrix.py` computes, `report.py` presents. Every module runs standalone.

| file | role |
|---|---|
| `ratchet/sources/*.py` | one adapter per app, returning `SourceItem` |
| `ratchet/extract.py` | `SourceItem → Case`, one cached LLM call each |
| `ratchet/judge.py` | ten graders, nine deterministic, plus `validate()` |
| `ratchet/runner.py` | generates and grades every case per version |
| `ratchet/matrix.py` | per-case × per-version state, regression detection |
| `ratchet/candidates.py` | independent candidate runs plus their combinations |
| `ratchet/report.py` | the HTML |
| `fixtures/` | the synthetic firm, briefs, corpus and judge labels |

## Prior art this builds on

- [FActScore](https://arxiv.org/abs/2305.14251) — atomic claims as the unit of evaluation
- [MiniCheck](https://arxiv.org/abs/2404.10774) — verification is entailment, and a small specialised checker beats a large general one at 400× lower cost
- [Chain-of-Verification](https://arxiv.org/abs/2309.11495) — verification must be factored or the judge repeats the errors it can see
- [Hamel Husain & Shreya Shankar, AI Evals FAQ](https://hamel.dev/blog/posts/evals-faq/) — 60–80% of eval time goes to error analysis
