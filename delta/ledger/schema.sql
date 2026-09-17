-- delta/ledger/schema.sql
--
-- Ported from Phase1 guide §11, scoped per research-program-guide §1.1:
-- "Simplified hash chain, fewer columns ... drop the environment-fingerprint
-- columns that only matter for timing claims."
--
-- Dropped vs. the Phase1 reference schema, and why each is safe to drop for
-- Stage 1's correctness-only, single-island, no-fairness-budget scope:
--   island_id, g_t_snapshot, band_width, exploration_intensity
--       -> Phase 2/3 hooks (fairness budget, G_t controller). Not built in
--          Stage 1; add back with a plain ALTER TABLE if Stage 2 needs them.
--   latency_ns_median, peak_rss_bytes, timing_anomaly, env_fingerprint
--       -> timing-claim support only. No latency in the fitness function
--          (§1.1), so nothing downstream ever reads these.
--   fitness_std, fitness_runs
--       -> Phase 4 resampling (N>5 runs/candidate). Stage 1 runs each
--          candidate once; add back if Stage 2 resamples.
--   artifact_path
--       -> not needed at this scale; every candidate source is already
--          content-addressed via candidate_digest / semantic_fingerprint.
--
-- Kept: everything the five invariants (I1 Fixity, I3 Score non-authorship,
-- I4 Provenance) and the Week 4 elite-band-vs-single-winner ablation
-- actually need.

CREATE TABLE IF NOT EXISTS records (
  seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
  prev_digest         TEXT NOT NULL,
  digest              TEXT NOT NULL UNIQUE,
  ts_utc              TEXT NOT NULL,

  -- lineage (I4)
  clone_id            TEXT NOT NULL UNIQUE,
  parent_id           TEXT,
  task                TEXT NOT NULL,
  generation_index    INTEGER NOT NULL,
  p0_digest           TEXT NOT NULL,

  -- admission (G0-G5, Appendix B taxonomy)
  admitted            INTEGER NOT NULL,
  rejection_class     TEXT,                      -- E_* taxonomy, NULL if clean
  gate_failed         TEXT,                      -- G0..G5 or "post"
  candidate_digest    TEXT,
  semantic_fingerprint TEXT,

  -- frozen edit metrics (G4 -- recorded, not enforced, in Stage 1)
  ast_distance_parent REAL,
  ast_distance_p0     REAL,
  token_diff_parent   INTEGER,
  nodes_added         INTEGER,
  nodes_removed       INTEGER,
  max_depth_delta     INTEGER,

  -- evaluation
  seed                INTEGER,
  run_index           INTEGER,
  status              TEXT,                      -- ok/timeout/nonzero_exit/sandbox_error
  fitness             REAL,                       -- host-computed, never candidate-authored (I3)

  -- integrity (I1)
  manifest_pre        TEXT NOT NULL,
  manifest_post       TEXT,
  attested            INTEGER NOT NULL DEFAULT 0, -- 0 => MUST NOT enter selection

  -- minimal provenance (I4), NOT a timing fingerprint
  image_digest        TEXT,
  python_version      TEXT,

  -- Week 4 hook: elite-band vs. single-winner ablation
  ablation_config      TEXT,

  stderr_tail          TEXT
);

CREATE INDEX IF NOT EXISTS idx_lineage     ON records(parent_id);
CREATE INDEX IF NOT EXISTS idx_generation  ON records(task, generation_index);
CREATE INDEX IF NOT EXISTS idx_fingerprint ON records(semantic_fingerprint);
CREATE INDEX IF NOT EXISTS idx_rejection   ON records(rejection_class);
