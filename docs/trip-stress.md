# trip stress: the N-1 contingency stress metric

"Trip stress" is the **post-outage overload total** that would result if a
specific line tripped — not any current state of the line itself. From
`compute/contingency.py:52-67`:

```
stress[c] = Σ_ℓ max(0, |flow_base[ℓ] + LODF[ℓ, c] · flow_base[c]| / s_nom[ℓ]  −  1)
```

Reading it left to right:

1. **Simulate the outage.** Line `c` trips. The MW it was carrying gets
   redistributed onto every other line according to the LODF column for
   `c`:
   ```
   flow_post[ℓ] = flow_base[ℓ] + LODF[ℓ, c] · flow_base[c]
   ```
2. **Compute per-line loading post-outage:** `|flow_post[ℓ]| / s_nom[ℓ]`
   (a dimensionless ratio; 1.0 = at rating, 1.2 = 20% overloaded).
3. **Keep only overloads.** `max(0, loading − 1)` — lines that stay under
   their rating contribute 0.
4. **Sum across all lines.** One scalar per candidate outage `c`.

So the "stress" number attached to a line in `top_contingencies` answers:
*"if this line trips, what is the total per-unit overload spread across
the surviving network?"* The tripped line itself contributes 0 to the sum
(it carries no flow after the outage).

## Units and calibration

Sum of per-unit overloads — dimensionless. A comment in the code notes
this could be MW-weighted instead; it is currently unweighted, so
"one line 50% over" and "two lines 25% over each" both score 0.5.

Rough interpretation bands from the docstring (`contingency.py:100-104`):

| stress score | interpretation      |
| ------------ | ------------------- |
| 0.01 – 0.1   | trivial             |
| 0.1  – 1.5   | mid overload, watch |
| 1.5  – 5.0   | significant         |
| 5.0  – 10.0  | severe              |

## Radial-line filter

`radial_threshold = 5.0` (`contingency.py:35-36`) drops lines whose
`|LODF|` column exceeds 5 anywhere. Those are near-radial — tripping them
would island part of the grid, and LODF's linearized redistribution model
breaks down there and generates absurd stress numbers. The pipeline
treats those as math artifacts and skips them, so a genuinely radial line
doesn't appear in the top-K even if losing it would be catastrophic in
reality. Something to keep in mind when reading the ranked list: absence
from the top-K does not imply "safe to lose."

## Relationship to `binding_proximity`

`binding_proximity` is base-case only — it reflects the current dispatch.
`stress` is contingency-driven — it reflects the post-outage worst case
under a single-element outage. They answer different operational
questions:

* `stress = 0` for every candidate → no single line trip overloads
  anything. Nothing to worry about from N-1 even if `binding_proximity`
  shows lines binding right now.
* `stress > 1.5` on the top contingency + `binding_proximity` low → not
  stressed right now, but one specific trip would push the grid hard.

Those are the two questions the plan's Scope B `binding_proximity_n1`
metric (see `docs/binding_proximity.md` § *Two distinct proximity metrics*)
would tie together at the per-bus level: a bus lights up in
`binding_proximity_n1` when *some* top-K contingency would push a branch
it drives into overload.
