"""ERCOT-side implied binding proximity.

Fits `C ≈ −M · SFᵀ` (ridge) on the shadow-price / congestion panels published
by NP4-191-CD and NP4-190-CD, then reports per-hour
`bp_ercot[sp] = max_{c binding} |SF_implied[c, sp]|` for the map's ERCOT
layer.

See ``docs/implied_binding_proximity.md`` for the derivation.
"""
