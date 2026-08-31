-- Make explicit that these diagnostics describe shift-factor map quality, not
-- a general forecast grade. RENAME preserves every historical value. The
-- guards also make this safe for development databases renamed before this
-- migration was checked in.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_attribute
    WHERE attrelid = 'sf_window_meta'::regclass
      AND attname = 'fit_r2' AND NOT attisdropped
  ) THEN
    ALTER TABLE sf_window_meta RENAME COLUMN fit_r2 TO sf_fit_r2;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_attribute
    WHERE attrelid = 'sf_window_meta'::regclass
      AND attname = 'oos_r2' AND NOT attisdropped
  ) THEN
    ALTER TABLE sf_window_meta RENAME COLUMN oos_r2 TO sf_oos_r2;
  END IF;
END $$;

COMMENT ON COLUMN sf_window_meta.sf_fit_r2 IS
  'In-sample diagnostic for the shift-factor map fit; not a forecast grade.';
COMMENT ON COLUMN sf_window_meta.sf_oos_r2 IS
  'Out-of-sample confidence diagnostic for the shift-factor map; not a forecast grade.';
