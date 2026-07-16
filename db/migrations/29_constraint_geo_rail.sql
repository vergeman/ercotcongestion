-- 29_constraint_geo_rail.sql
--
-- Shape fields for the low-confidence verdict (docs/ERCOT_constraints.md §4).
-- binding_hours turned out to be a poor discriminator: clean-but-brief
-- constraints (TRDWEL, PLC_KAME) bind <50h yet have smooth, unclipped SF, while
-- the actual ridge-clamp artifacts (6429__D) bind plenty but pin several nodes
-- at exactly ±1 with a cliff to the noise floor. The tell is the *shape*, not
-- the hour count, so we persist two shape scalars per constraint:
--
--   n_rail       -- count of nodes with |SF| >= 0.999 (clamped at SF_ABS_CAP).
--                --   A real radial *resource* rails ONE node; a real radial
--                --   *pocket* plateaus just under the cap (VALEXP ~0.82). Several
--                --   nodes co-equal at exactly ±1 is the ill-conditioned clamp.
--   peak_offrail -- max |SF| among the NON-railed nodes = the top of the graded
--                --   body. A lone rail with a real body beneath it (BELCNTY:
--                --   1 rail, body at 0.26) is a radial resource; a rail with no
--                --   body (peak_offrail near 0) is an isolated artifact.
--
-- Low-confidence := n_rail >= 2  OR  (n_rail >= 1 AND peak_offrail < 0.10).
-- binding_hours is demoted to a "thin support" annotation, never a verdict.

ALTER TABLE constraint_geo ADD COLUMN IF NOT EXISTS n_rail       INTEGER;
ALTER TABLE constraint_geo ADD COLUMN IF NOT EXISTS peak_offrail REAL;
