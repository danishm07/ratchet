# Ratchet — operating manual

A ratchet only turns one way. Once a case passes, it never silently goes back.

Ratchet turns the complaints and fixes a team already produces into a regression
suite for an AI feature, then scores every change **per case** so improvements
and regressions can't cancel each other out in one aggregate number.

**Hard deadline: 4:00 PM Pacific, Sunday 13 Sep 2026.** Feature freeze 2:00 PM PT.
Everything after the freeze is evaluation, README, and the demo video.

---

## Judging weights — build to these, in this order

| weight | criterion | what actually earns it here |
|---|---|---|
| 30% | Technical execution | Real API calls to three apps. Working per-case runner. Clean, readable modules. |
| 25% | Reliability & evaluation | **Judge validation against human labels**, an ablation, and honest numbers including where we lose. |
| 20% | Usefulness | The grid answers a question a real person has: what did my change break? |
| 15% | Originality | Cases are *derived from fixes and complaints*, not hand-written. Nobody does this. |
| 10% | Demo clarity | ≤2 min. The grid is the hero shot. |

Reliability is 25% and is the easiest category to win, because almost nobody
ships a measured error rate. **Never trade eval time for feature time.**

---

## Architecture

```
sources/  →  extract  →  cases  →  runner  →  matrix  →  report
(3 apps)     (LLM)       (json)    (judge)    (grid)    (html)
                                      ↑
                                 judge.py validated against
                                 human labels BEFORE trusted
```

Module boundaries, and nothing crosses them:

- `sources/*.py` — one adapter per external app. Each returns a list of
  `SourceItem`. Adapters do I/O and nothing else: no LLM calls, no parsing of
  meaning. A source is swappable without touching anything downstream.
- `extract.py` — `SourceItem → Case`. The only place that turns prose into
  structure. One LLM call per item, cached.
- `judge.py` — `(Case, output) → Verdict`. Deterministic graders where possible;
  LLM judge only where the criterion is genuinely subjective.
- `runner.py` — runs every case against one version of the target system.
  Pure orchestration; parallel; no scoring logic of its own.
- `matrix.py` — per-case × per-version state, and regression detection.
- `candidates.py` — runs N candidate changes independently, then their
  combinations. Never assumes effects are additive.
- `report.py` — writes the HTML. Presentation only; computes nothing.

## Non-negotiable engineering rules

**1. Cache every external call to disk, keyed by a hash of its inputs.**
Model calls, Slack fetches, everything. The suite must replay offline,
deterministically, in seconds, for free. This is not an optimisation — it is
what makes iterating on the judge possible at all, and it is a talking point
(it's Arga's thesis in miniature: a frozen environment you can test against).

**2. Verdicts are structured, never prose.** Every judge returns
`{verdict, quote, reason}`. A verdict with no supporting quote from the output
is rejected by the schema. If we can't point at the evidence, we don't have a
verdict.

**3. Judge before pipeline.** Any number produced by an unvalidated judge is a
rubber ruler. `judge.py` must report agreement with human labels on a held-out
set before any suite result is believed or shown. If agreement is low, fix the
judge — not the thing under test.

**4. Deterministic graders win.** If a criterion can be checked with a regex, a
parse, or arithmetic, do that. LLM judges are for genuinely subjective criteria
only. Cheaper, faster, and no agreement problem. Aim for the majority of cases
to be deterministic.

**5. Per-case, never aggregate-only.** Any surface that shows one number must
also show the cells. Aggregates hide exactly the thing this product exists to
reveal.

**6. Fail loud on partial results.** A run with three failed API calls must not
silently report as a clean run. Missing data is a distinct state from a failing
case, and the UI must show it as such.

## Data rules

**All content is synthetic.** No real client data, no real employer data, no
personal history. Fixtures in `fixtures/` are invented — a fictional consulting
firm and a fictional document generator. They get posted to *real* Slack,
Linear and GitHub, so the API integrations are genuine while the content is not.

The system under test is `fixtures/target/` — a small deliberately-flawed
document generator with five tagged versions, so regressions are real and
reproducible rather than staged.

## Python conventions

- Python 3.10+, `uv` for deps. Standard library first; `httpx` for HTTP,
  `pydantic` for the schemas that matter (Case, Verdict, RunResult).
- Type hints on every public function. Dataclasses or pydantic models over dicts
  for anything that crosses a module boundary.
- No class where a function will do. No framework. No ORM. No async unless a
  step is genuinely I/O-bound and wide — `ThreadPoolExecutor` is fine and is
  what we're using.
- Every module runnable standalone: `python -m ratchet.runner --version v3`.
  A judge should be able to reproduce any number in the README from one command.
- Errors carry context. `raise RuntimeError(f"slack: {resp.status_code} {resp.text[:200]}")`,
  never a bare except.
- Secrets from env only, via `config.py`. Nothing else reads `os.environ`.

## Prompt conventions

- Prompts live as module-level constants in the file that uses them, named in
  caps. Never inline in a function body, never built by string concatenation
  across functions.
- Every prompt that returns data specifies the exact JSON shape and says
  "Return ONLY JSON".
- **Factored judging.** The judge prompt contains the case and the output and
  nothing else — no transcript, no neighbouring cases, no prior verdict. Per
  Chain-of-Verification (Dhuliawala et al., ACL Findings 2024), a judge that
  sees a prior judgement conditions on it and repeats its errors: joint
  verification measured 0.29 precision against 0.36 for the factored version.

## What "done" looks like at 2:00 PM PT

- [ ] Three real APIs returning real items
- [ ] Cases extracted from all three, including at least one derived from a *fix*
- [ ] Runner scoring all cases across 5 versions of the target
- [ ] Judge agreement measured and printed
- [ ] Grid rendering with regressions marked
- [ ] One ablation: candidates run independently, plus their combination

Anything not on that list is out of scope today.
