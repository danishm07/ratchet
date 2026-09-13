# Demo video script — 2:00 hard cap

Record screen + voice. One take is fine; the content carries it. Have these open
in tabs before you start:

1. Terminal in the repo, cleared
2. `data/runs/report.html` in a browser
3. Your Slack channel, Linear issues, GitHub commits — one tab each

Speak at a normal pace. Do not rush the 1:10 beat; that's the whole video.

---

### 0:00 — 0:15 · the problem, concretely

> "You ship an AI feature. It gets something wrong. Someone says so in Slack, or
> files a ticket, or just quietly pushes a fix. That knowledge dies there. It
> never becomes a test — so three weeks later the same failure comes back and
> nobody recognises it as a regression."

*On screen: the Slack channel, the Linear issues, the GitHub commits, three
seconds each. Do not narrate what they are; they're self-evident.*

### 0:15 — 0:35 · what it does

> "Ratchet reads all three, turns each complaint and each fix into a runnable
> test case, and then scores every version of the system per case."

*Run it live:*

```
python -m ratchet run --candidates
```

> "Fifteen items in. Eleven were checkable, four were chatter and got discarded.
> Ten rules, sixty cases. Nothing here was hand-written as a test."

*The extraction line is on screen while you say this.*

### 0:35 — 0:50 · the grid

*Switch to `report.html`. Let it sit.*

> "Aggregate score goes 0.85 to 0.98 — clean progress. But four cases regress at
> v2 and four more at v3. Improvements and regressions cancelling inside a rising
> number is exactly why this seesaw is invisible when you're looking at one score."

*Point at two outlined cells. Don't list them.*

### 0:50 — 1:10 · where cases come from

> "The strongest source isn't complaints, it's fixes. When someone fixes
> something they know what went wrong and what right looks like — and that's
> precisely the moment nobody writes a test, because they're relieved and moving
> on. A fix is a complaint with the answer already attached."

*Scroll to the "where the cases came from" table, showing the GitHub-derived rows.*

### 1:10 — 1:40 · the part that matters — say this slowly

> "Then the honest part. My first run showed a dramatic seesaw — v3 losing
> thirteen cases. I didn't believe it, so I added a variance check: same version,
> sampled three times. Fifty percent of cases flipped between identical runs.
>
> That's not a system that regresses. That's an instrument that can't measure.
> The bug was mine — the generator emits markdown headings and two of my graders
> only matched plain ones. Fixed it, flip rate dropped to twenty percent, and the
> dramatic seesaw mostly went with it.
>
> So what I'm claiming now is narrower. Judge agreement is eighty-five percent
> against hand labels, measured, not assumed. Nine of ten graders are
> deterministic so they need no judge at all. And the regressions that are left
> are one to four cases out of sixty, which at a twenty percent flip rate I
> **can't** distinguish from noise — so the README says that rather than claiming
> a win."

*On screen: the variance line in the terminal, then the §4 heading in the README.*

### 1:40 — 1:55 · the ablation

> "Last thing. Three candidate fixes, each run against the full suite
> independently, then combined — because effects aren't additive. Two of the
> three make it worse alone. The best result is a pair a serial fix-one-thing
> loop would never reach, because it'd apply the first one, see it get worse, and
> back it out."

### 1:55 — 2:00 · stop

> "Repo has the setup, the numbers, and what I'd need to make the regression
> claims stick."

*Stop talking. Do not add a summary.*

---

## Notes

- **The 1:10 beat is the video.** Everything else is setup for it. Judges from
  two eval companies will have watched thirty demos claiming an agent works;
  yours is the one that says where its own measurement failed.
- Say "I can't distinguish that from noise" out loud. It is the most credible
  sentence available and almost nobody will say it.
- If a live run is risky on the day, record it separately and cut to it. Never
  debug on camera.
- Hard cap is two minutes. Over-length submissions get cut off, not forgiven.
