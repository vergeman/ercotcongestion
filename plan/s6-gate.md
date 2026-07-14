# s6-gate — the bars for Sprint 6, fixed in advance

**Status: PRE-REGISTERED. Written before a single 0088 number exists.**
Committed as commit 1 of `feat/0088-mu-panel-and-ablation`, before the panel was
touched, before any arm was trained, and before the ablation was run.

**This file is never edited after the fact.** Not to "clarify" a bar, not to add a
caveat, not to note that an arm came close. If reading the ablation makes anyone
want to change a number in this document, that impulse is the exact thing the
document exists to stop. Corrections to *facts* (a mis-transcribed baseline) may be
made **only before commit 5 runs**, and only by amending this commit.

Why it exists: 0085 (R5) failed by a margin small enough to argue about, and the
project's own summary records that the assumed fallback — persistence's 0.649
top-decile — was a **souvenir of a retired operating point**, never re-measured.
Sprint 6 is the last cheap shot at R5's failure. It is therefore exactly the
condition under which a marginal number gets talked into being a win.

---

## The measured baselines — restated, and one label corrected

All figures below are from `compute/mu/mu_score_weekly.csv`: **46 weeks,
2025-08-14 → 2026-06-25**, at the adopted operating point **(window 240d, refit 7d,
λ=1, min_hours=25)**, scored through `compute/mu/score.py`. These are the numbers
0088 must be compared against, and **nothing else is** — the retired `(60, λ=0.1)`
figures are not a baseline, they are a different experiment.

| μ source | pooled R² | rank-ρ | sign-agree | **top-decile** |
|---|---|---|---|---|
| oracle (realized μ — the ceiling) | 0.787 | 0.835 | 0.923 | 0.762 |
| model (0085) | 0.222 | 0.548 | 0.787 | 0.523 |
| **persistence** | **−0.011** | **0.496** | **0.736** | **0.561** |
| climatology | 0.046 | 0.381 | 0.688 | 0.455 |

> **Label correction, made before any 0088 run.** `plan/0088-mu-panel-and-ablation.md`
> quotes persistence as "0.496 R² / 0.736 rank-ρ / 0.561 top-decile". That triple is
> really **rank-ρ / sign-agree / top-decile**. **Persistence's pooled R² is −0.011 —
> it is *worse than predicting the mean*.** The plan's prose conclusion is unaffected
> (persistence still wins top-decile, which is the whole problem), but the gate must
> name its metrics correctly or the comparison is unreadable. Recorded here rather
> than silently fixed.

**Pre/post RTC+B (2025-12-05) — the same table, split.** The break is large enough
that a pooled-only read is not a read at all.

| μ source | pre R² | pre top-dec | post R² | post top-dec |
|---|---|---|---|---|
| oracle | 0.788 | 0.785 | 0.786 | 0.749 |
| model (0085) | 0.275 | 0.640 | 0.191 | 0.455 |
| **persistence** | 0.158 | **0.654** | −0.110 | **0.507** |

**Note what this says: the post-RTC+B world is harder for every forecast source and
unchanged for the oracle.** The map is fine on both sides; the *forecast* is what
degrades. Any 0088 arm that improves the pooled number by improving only the pre
half has not solved the live problem.

---

## Bar 1 — the existence test: beat persistence

**An arm passes the existence test iff it beats persistence in the screening
currency — which means beating `top-decile 0.561`, and not by losing elsewhere.**

Stated precisely, an arm passes iff, pooled over the 46 weeks:

* **top-decile hit > 0.561**, *and*
* it does not fall below persistence on rank-ρ (0.496) or sign-agree (0.736).

**Top-decile is the operative cell and the others are guardrails**, and that
asymmetry is deliberate: 0085's model already beat persistence on R², rank-ρ and
sign — and still failed, because it lost the one metric a screening tool exists to
serve. *Winning three of four is how R5 failed.* Do not report an arm as passing
because it won the easy cells.

**Ties fail.** An arm that lands at 0.561 has not beaten persistence.

**Report pre and post RTC+B alongside the pooled figure**, against
persistence's own 0.654 / 0.507. An arm that clears the pooled bar while losing the
post half is a **fail with an explanation**, not a pass.

## Bar 2 — the product test: §5.5, verbatim and unchanged

Reproduced exactly as pre-registered in the handoff. **Not edited, not reinterpreted,
not "adjusted for the harder post-RTC+B regime."** Either bar clears a row.

| outcome | magnitude bar | screening bar |
|---|---|---|
| Forecast product | pooled R² ≥ 0.5 | Spearman ≥ 0.70 **and** sign ≥ 0.85 |
| Screening tool | R² 0.3–0.5 | Spearman 0.60–0.70, **top-decile ≥ 0.60** |
| Forecast is not the product | R² < 0.3 | Spearman < 0.60 **and** top-decile ≤ 0.649 |

**The operative number for Sprint 6 is `top-decile ≥ 0.60`.**

---

## The distinction R5 blurred — and the one this gate is really for

**These are two different questions and passing one does not pass the other.**

**Persistence's own top-decile is 0.561, which is *below* the 0.60 product bar.**
That single fact is the whole reason this document exists. It means:

> **An arm can beat persistence, absorb it entirely, become the best μ source we
> have ever measured — and still not ship a product.** The interval **0.561 <
> top-decile < 0.60** is a **real and reachable outcome** in which the honest verdict
> is *"we finally beat yesterday, and it is still not a product."*

**Do not let a 0.56, or a 0.58, read as a win because it is finally above
persistence.** The existence test is about whether the covariate thesis is *alive*.
The product test is about whether anything **ships**. Sprint 6 must say **which test
was passed**, in those words, for each arm.

Three verdicts are available, and all three are acceptable outcomes:

| verdict | condition |
|---|---|
| **Product** | top-decile ≥ 0.60 (and the §5.5 row that goes with it) |
| **Alive, not shippable** | top-decile > 0.561 but < 0.60 — beat persistence, failed §5.5 |
| **Dead** | top-decile ≤ 0.561 — did not beat yesterday |

---

## Attribution — pre-registered, because it is where the pressure will be

The ablation runs `base` / `+lag` / `+geo` / `+wx` / `all`. **Each arm's contribution
is reported separately, against persistence and oracle, in one table.**

**The single most likely outcome is that `+lag` carries the sprint and `+geo` /
`+wx` add nothing.** That is not a disappointing result — **it is the most valuable
finding this sprint can produce**, because it would mean the μ-model was losing to
persistence for a *repairable defect* (it never saw yesterday's μ magnitude) rather
than for want of information we do not have. It would also mean 0086's "missing
outage data is the whole story" was overstated.

**Pre-registered, so it cannot be softened later:** if `+lag` alone accounts for the
lift and `+geo` and `+wx` are flat, **0088 says so plainly** and the two geography
arms are **reported as null results**, not as "directionally encouraging",
"promising given more features", or "limited by the current crosswalk."

**And the trap, named in advance:** `+lag` is *the closest thing the panel has to
persistence itself.* If `+lag` wins, the immediate next question — which 0088 must
ask rather than dodge — is **"has the model learned anything, or has it merely
reconstructed persistence internally?"** The diagnostic is already in the table:
compare `+lag` to persistence's own 0.561, and check whether `all` beats `+lag`.
**A model that has re-derived persistence and added nothing is a defect fix, not a
forecast** — and it lands in the "alive, not shippable" row unless it clears 0.60.

## What no result is allowed to do

* **Redefine the currency.** Top-decile is the screening metric. Not "top-quintile,"
  not "top-decile among constraints the model was confident about," not a new
  threshold that happens to fit.
* **Change the weeks.** 46 weeks, 2025-08-14 → 2026-06-25, read off the model's own
  output (`weeks_from_preds`). Not "excluding the RTC+B transition weeks."
* **Change the harness.** `score.py` and `propagate.py` are the control variable and
  are not touched in 0088.
* **Quote a pre-RTC+B number as the headline** because the post half is worse.
* **Move the operating point** to one where the arm looks better. `(240, 7, λ=1)`.

**Fail is an outcome.** Four first-generation risks have now closed by failing (R4,
R5, R6, R7), and the project is in good shape *because* they were recorded honestly.
A fifth costs nothing to record and everything to fudge.
