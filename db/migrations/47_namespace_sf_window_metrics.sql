-- Make explicit that these diagnostics describe shift-factor map quality, not
-- a general forecast grade. RENAME preserves every historical value.
ALTER TABLE sf_window_meta RENAME COLUMN fit_r2 TO sf_fit_r2;
ALTER TABLE sf_window_meta RENAME COLUMN oos_r2 TO sf_oos_r2;

COMMENT ON COLUMN sf_window_meta.sf_fit_r2 IS
  'In-sample diagnostic for the shift-factor map fit; not a forecast grade.';
COMMENT ON COLUMN sf_window_meta.sf_oos_r2 IS
  'Out-of-sample confidence diagnostic for the shift-factor map; not a forecast grade.';
