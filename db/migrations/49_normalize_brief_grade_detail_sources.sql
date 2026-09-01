-- The initial Brief-grade materialization stored each source's metrics directly
-- under ``model``, ``persistence``, and ``climatology``.  The Brief now reads
-- the same values through source_metrics keyed by stable source IDs.  This is
-- a shape-only migration: it preserves every previously computed score.
--
-- The predicate makes the migration safe to run repeatedly and leaves any
-- already-current payload untouched.

UPDATE analysis_grade_daily
SET detail =
  (detail - 'model' - 'persistence' - 'climatology')
  || jsonb_build_object(
    'source_metrics',
    jsonb_build_array(
      jsonb_build_object(
        'id', 'brief_model_artifact_profile',
        'metrics', detail -> 'model'
      ),
      jsonb_build_object(
        'id', 'brief_persistence_prior_settled_profile',
        'metrics', detail -> 'persistence'
      ),
      jsonb_build_object(
        'id', 'brief_climatology_trailing_settled_profile',
        'metrics', detail -> 'climatology'
      )
    )
  )
WHERE detail IS NOT NULL
  AND detail ? 'model'
  AND detail ? 'persistence'
  AND detail ? 'climatology'
  AND NOT detail ? 'source_metrics';
