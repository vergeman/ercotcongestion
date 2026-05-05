## West Texas purple

**What you see:** the Δ Rank view shows clusters of light purple buses across
West Texas, particularly in the Permian region.

**What it means:**
- Purple = `pct_fragility < pct_|basis|` (for that snapshot's ranking).
- The bus's `|basis|` is high — its LMP deviates significantly from the hub.
- The bus's fragility is low — your model's topology + shadow prices don't
  predict pressure here.*- Translation: **the market is pricing real congestion
  at this bus, but the model doesn't see it.**

**Why this happens:** West Texas is the wind-and-Permian zone. Real ERCOT basis
there is dominated by:
- Export congestion out of West toward load centers (Houston/Dallas)
- Wind curtailment economics
- Specific real-world transmission paths (e.g. McCamey-area constraints)

Your DC-OPF runs on a *synthetic* topology with different export paths. There's
no curtailment economics in the optimization, and the synthetic line set doesn't
replicate which corridors actually bottleneck wind exports. So the model can't
see what real markets are pricing.

**Why it matters:** this is the validation panel's near-zero correlation made
spatially legible. The headline ρ=0.008 doesn't tell you *why* — it just says
model and market disagree on average. The map says: model and market disagree
*systematically* in West Texas, in a way consistent with known
synthetic-topology limitations. That's an honest, bounded finding rather than a
vague "the validation didn't work."

---

## Houston teal

**What you see:** in the Δ Rank view, Houston shows clusters of teal
(green-cyan) buses, particularly around the binding lines we observed in the
binding-constraints panel. The buses also have high fragility and non-trivial
`|basis|` (around $8).

**What it means:**
- Teal = `pct_fragility > pct_|basis|`.
- Both rankings are non-trivial — model says fragile, market says basis exists.
- But fragility is ranked *higher* in the snapshot than `|basis|` is.
- Translation: **the model and market both think there's stress here, but the
  model thinks it's a worse problem than the market is pricing.**

**Two ways to read it:**

1. **Model overcalls magnitude, right location.** The synthetic constraints
   binding in Houston really do correspond to where ERCOT congestion happens —
   but the model's PTDF² × shadow-price weighting amplifies the issue more than
   reality does. Calibration is hot.

2. **Right region, wrong buses.** Synthetic topology binds at *some*
   Houston-area lines and propagates fragility to specific buses; real ERCOT
   binds at *different* nearby lines that propagate to different buses. They
   cluster in the same metro but don't align bus-for-bus. So `|basis|` is
   non-zero across the area (real congestion is real), and fragility is high
   across the area (model congestion is real-ish), but they're not the *same*
   high-magnitude buses.

The Δ Rank view by itself can't distinguish these two interpretations. That's
where **PTDF halos** come in — hover a Houston binding line, see which buses the
model says should respond. If those are also the buses where you see basis
premium, it's interpretation #1 (calibration). If the responding buses are
different from the basis-premium buses, it's interpretation #2 (topology
mismatch).

---

## The contrast in plain English

> **West Texas:** the model is *blind*. Market sees something the model doesn't
> see at all.
>
> **Houston:** the model is *over-confident*. Market and model agree something
> is happening; they disagree on exactly where or how badly.

These are different failure modes, and the work distinguishes them rather than
collapsing both into "validation failed."
