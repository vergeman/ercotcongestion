# Experiment Plan: Option 4 — KKT Reconstruction of λ

**Goal:** Recover λ from existing solve outputs via least-squares on the LMP decomposition. Zero extra solves.

## Setup

- Use the existing baseline PyPSA solve. No model changes.
- For each snapshot, collect: nodal LMPs (vector of length N), shift-factor matrix SF (N × C, where C = number of transmission constraints), shadow prices SP_c for each constraint.

## Method

- For each snapshot, the LMP decomposition gives one equation per bus: `LMP_bus = λ − Σ_c SF_bus,c × SP_c`
- Rearrange: `LMP_bus + Σ_c SF_bus,c × SP_c = λ` for all N buses.
- If SP_c are taken from the solve, this is N equations in 1 unknown (λ). Solve by least squares; record both λ̂ and residual norm.
- Alternative: treat SP_c as unknowns too — N equations, (1 + C) unknowns. Overdetermined when N > C+1 (almost always true). Use least squares; compare recovered SP_c against solver-reported values as a consistency check.

## Outputs

- λ̂ per snapshot across the analysis window.
- Residual norm per snapshot (diagnostic — large residuals flag snapshots where decomposition is inconsistent).
- Histogram of λ̂ vs. `load_weighted` (informs Path A error characterization).

## Success criteria

- **GREEN:** residuals near machine epsilon for >95% of snapshots → λ̂ is reliable, promote to primary.
- **YELLOW:** residuals small for normal snapshots, large during stress/congestion → use λ̂ where clean, flag the rest.
- **RED:** large residuals throughout → SF matrix or SP_c extraction is wrong; debug or abandon.

## Effort

~1 day. Pure post-processing in numpy.
