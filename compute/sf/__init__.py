"""ERCOT-side implied shift factors (SF).

Fits `C ≈ −M · SFᵀ` (ridge) on the shadow-price / congestion panels published
by NP4-191-CD and NP4-190-CD, recovering the per-constraint implied shift
factors `SF[c, sp]` that map constraint shadow prices to nodal congestion.
The map surfaces read these from ``implied_shift_factors``.
"""
